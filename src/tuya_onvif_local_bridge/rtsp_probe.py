# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bounded, best-effort RTSP media inspection. Never log authenticated URLs."""
import asyncio
from dataclasses import dataclass
import time
import logging
from urllib.parse import quote, urlsplit, urlunsplit

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StreamInfo:
    codec: str = 'H264'
    profile: str = 'Main'
    width: int = 1920
    height: int = 1080
    fps: float = 15.0
    bitrate_kbps: int = 2048
    gop: int = 30
    audio_codec: str | None = None
    audio_rate: int | None = None
    audio_channels: int | None = None
    verified: bool = False


def authenticated_uri(uri: str, username: str, password: str) -> str:
    parsed = urlsplit(uri)
    if parsed.scheme not in ('rtsp', 'rtsps') or not parsed.hostname:
        raise ValueError('Invalid RTSP URI')
    if parsed.username is not None or parsed.password is not None:
        raise ValueError('ONVIF_STREAM_URI must not embed credentials')
    netloc = quote(username, safe='') + ':' + quote(password, safe='') + '@' + parsed.netloc
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _positive_int(value, default):
    try:
        value = int(value)
        return value if value > 0 else default
    except (TypeError, ValueError, OverflowError):
        return default


def _fps(stream):
    for rate in (getattr(stream, 'average_rate', None), getattr(stream, 'base_rate', None)):
        try:
            value = float(rate)
            if 0 < value <= 240:
                return value
        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
            pass
    return 15.0


def _sample_video(container, video, seconds=60.0, minimum_seconds=10.0):
    """Measure RTP-derived presentation timestamps and complete keyframe intervals.

    Packet timestamps are not wall-clock arrival times (network jitter can be high).
    A GOP is reported only when at least two *complete*, equal keyframe-to-keyframe
    intervals are observed. Missing timestamps or irregular GOPs remain unknown.
    """
    timestamps = []
    keyframes = []
    frame_count = 0
    complete = False
    start = time.monotonic()
    deadline = start + seconds
    for packet in container.demux(video):
        if complete or time.monotonic() >= deadline:
            break
        if packet.dts is None and packet.pts is None:
            continue
        try:
            frames = packet.decode()
        except Exception:
            continue
        for frame in frames:
            if frame.pts is None or frame.time_base is None:
                continue
            timestamp = float(frame.pts * frame.time_base)
            if timestamps and timestamp <= timestamps[-1]:
                continue
            timestamps.append(timestamp)
            if frame.key_frame:
                keyframes.append(frame_count)
            frame_count += 1
            # Stop once the minimum observation period and two matching GOP
            # intervals have been observed. Long GOPs can use the full window.
            if (time.monotonic() - start >= minimum_seconds and len(timestamps) >= 6
                    and len(keyframes) >= 3 and
                    keyframes[-1] - keyframes[-2] == keyframes[-2] - keyframes[-3]):
                complete = True
                break
    fps = None
    if len(timestamps) >= 6:
        intervals = [b - a for a, b in zip(timestamps, timestamps[1:])]
        # Use the observed presentation span, not a nominal SDP framerate.
        span = timestamps[-1] - timestamps[0]
        if span > 0 and all(0 < d < 2 for d in intervals):
            measured = (len(timestamps) - 1) / span
            if 0 < measured <= 240:
                fps = measured
    gop = 0
    if len(keyframes) >= 3:
        lengths = [b - a for a, b in zip(keyframes, keyframes[1:])]
        if len(set(lengths)) == 1 and lengths[0] > 0:
            gop = lengths[0]
    return fps, gop


def _inspect(uri, username, password, connect_timeout=10.0, read_timeout=10.0,
             sample_duration=60.0, total_timeout=75.0):
    import av
    authenticated = authenticated_uri(uri, username, password)
    deadline = time.monotonic() + total_timeout
    with av.open(authenticated, mode='r', options={
        'rtsp_transport': 'tcp',
        'timeout': str(int(read_timeout * 1_000_000)),
    }, timeout=(min(connect_timeout, total_timeout), read_timeout)) as container:
        video = next((s for s in container.streams if s.type == 'video'), None)
        if video is None:
            raise ValueError('RTSP has no video stream')
        cc = video.codec_context
        codec = str(cc.name or '').lower()
        if codec not in ('h264', 'mpeg4', 'mjpeg'):
            raise ValueError('Unsupported ONVIF Media1 video encoding')
        encoding = {'h264': 'H264', 'mpeg4': 'MPEG4', 'mjpeg': 'JPEG'}[codec]
        profile = str(getattr(cc, 'profile', '') or '')
        if encoding == 'H264':
            profile = next((p for p in ('Baseline', 'Main', 'High', 'Extended') if p.lower() in profile.lower()), 'Main')
        audio = next((s for s in container.streams if s.type == 'audio'), None)
        acc = audio.codec_context if audio else None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('RTSP probe deadline exceeded')
        measured_fps, gop = _sample_video(container, video, seconds=min(sample_duration, remaining))
        return StreamInfo(codec=encoding, profile=profile,
            width=_positive_int(cc.width, 1920), height=_positive_int(cc.height, 1080),
            fps=measured_fps or _fps(video),
            bitrate_kbps=_positive_int(getattr(video, 'bit_rate', None) or cc.bit_rate, 2048000)//1000,
            gop=gop,
            audio_codec=str(acc.name) if acc else None,
            audio_rate=_positive_int(acc.sample_rate, 0) if acc else None,
            audio_channels=_positive_int(getattr(acc, 'channels', None), 0) if acc else None,
            verified=True)


async def probe(uri: str, username: str, password: str, *,
                connect_timeout: float = 10.0, read_timeout: float = 10.0,
                sample_duration: float = 60.0, total_timeout: float = 75.0) -> StreamInfo:
    """Return fallback metadata on error; never expose the RTSP URI in diagnostics.

    The asyncio deadline is not a hard cancellation of an FFmpeg worker thread.
    Per-I/O FFmpeg timeouts constrain blocking calls independently.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_inspect, uri, username, password,
                              connect_timeout, read_timeout, sample_duration, total_timeout),
            timeout=total_timeout)
    except Exception as exc:
        # Exception messages from FFmpeg can include authenticated URLs.
        log.warning('RTSP metadata probe unavailable (%s); using provisional metadata', type(exc).__name__)
        return StreamInfo()
