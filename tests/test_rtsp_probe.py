# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from tuya_onvif_local_bridge.rtsp_probe import StreamInfo, authenticated_uri, probe


def test_uri_credentials_are_escaped():
    assert authenticated_uri('rtsp://10.0.0.1:554/stream1', 'u@x', 'p:/?#') == 'rtsp://u%40x:p%3A%2F%3F%23@10.0.0.1:554/stream1'


def test_uri_embedded_credentials_rejected():
    with pytest.raises(ValueError):
        authenticated_uri('rtsp://u:p@10.0.0.1/stream1', 'u', 'p')


@pytest.mark.asyncio
async def test_probe_failure_does_not_expose_secrets(monkeypatch, caplog):
    from tuya_onvif_local_bridge import rtsp_probe
    def fail(*args):
        raise RuntimeError('rtsp://admin:secret@10.0.0.1/stream1')
    monkeypatch.setattr(rtsp_probe, '_inspect', fail)
    result = await probe('rtsp://10.0.0.1/stream1', 'admin', 'secret')
    assert result == StreamInfo()
    assert 'secret' not in caplog.text


def test_sample_video_measures_fps_and_fixed_gop(monkeypatch):
    from fractions import Fraction
    from types import SimpleNamespace
    from tuya_onvif_local_bridge.rtsp_probe import _sample_video

    class Packet:
        dts = 1
        pts = 1
        def __init__(self, n):
            self.n = n
        def decode(self):
            return [SimpleNamespace(pts=self.n, time_base=Fraction(1, 15),
                                    key_frame=self.n % 30 == 0)]

    class Container:
        def demux(self, stream):
            return (Packet(n) for n in range(91))

    fps, gop = _sample_video(Container(), object(), seconds=30)
    assert fps == pytest.approx(15)
    assert gop == 30


def test_sample_video_does_not_invent_irregular_gop():
    from fractions import Fraction
    from types import SimpleNamespace
    from tuya_onvif_local_bridge.rtsp_probe import _sample_video

    class Packet:
        dts = 1
        pts = 1
        def __init__(self, n): self.n = n
        def decode(self):
            return [SimpleNamespace(pts=self.n, time_base=Fraction(1, 10),
                                    key_frame=self.n in (0, 20, 51))]

    class Container:
        def demux(self, stream):
            return (Packet(n) for n in range(70))

    fps, gop = _sample_video(Container(), object(), seconds=30)
    assert fps == pytest.approx(10)
    assert gop == 0
