# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

import dataclasses
import ipaddress
import json
import os
import socket
import uuid
from urllib.parse import urlsplit


def lan_ip(destination: str) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((destination, 6668))
        return s.getsockname()[0]


@dataclasses.dataclass(frozen=True)
class Config:
    device_id: str
    local_key: str
    ip: str
    version: str
    username: str
    password: str
    name: str
    port: int
    advertise_ip: str
    uuid: str
    data_path: str
    default_timeout: float
    max_timeout: float
    reconnect_attempts: int
    reconnect_delay: float
    direction_codes: dict[str, str]
    stream_uri: str

    @classmethod
    def from_env(cls):
        mandatory = ['TUYA_DEVICE_ID', 'TUYA_LOCAL_KEY', 'TUYA_IP', 'TUYA_VERSION', 'ONVIF_USERNAME', 'ONVIF_PASSWORD', 'ONVIF_STREAM_URI']
        missing = [x for x in mandatory if not os.getenv(x)]
        if missing:
            raise ValueError('Missing required environment variables: ' + ', '.join(missing))
        stream_uri = os.environ['ONVIF_STREAM_URI']
        parsed = urlsplit(stream_uri)
        if parsed.scheme.lower() not in ('rtsp', 'rtsps') or not parsed.hostname or not parsed.netloc or any(ch.isspace() for ch in stream_uri):
            raise ValueError('ONVIF_STREAM_URI must be a valid rtsp:// or rtsps:// URI with a host')
        try:
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError('ONVIF_STREAM_URI port out of range')
        except ValueError as exc:
            raise ValueError('Invalid ONVIF_STREAM_URI port') from exc
        ip = os.environ['TUYA_IP']
        advertised = os.getenv('ONVIF_ADVERTISE_IP') or lan_ip(ip)
        ipaddress.IPv4Address(advertised)
        port = int(os.getenv('ONVIF_PORT', '8080'))
        if not 1 <= port <= 65535:
            raise ValueError('ONVIF_PORT out of range')
        default_timeout = float(os.getenv('PTZ_DEFAULT_TIMEOUT', '5'))
        max_timeout = float(os.getenv('PTZ_MAX_TIMEOUT', '30'))
        if not 0 < default_timeout <= max_timeout:
            raise ValueError('Invalid PTZ timeout limits')
        # Camera-specific codes: override via TUYA_DIRECTION_CODES after hardware validation.
        codes = json.loads(os.getenv('TUYA_DIRECTION_CODES', '{"up":"0","up-right":"1","right":"2","down-right":"3","down":"4","down-left":"5","left":"6","up-left":"7"}'))
        if set(codes) != {'up','up-right','right','down-right','down','down-left','left','up-left'} or not all(isinstance(v, str) for v in codes.values()):
            raise ValueError('TUYA_DIRECTION_CODES must map all eight directions to strings')
        return cls(os.environ['TUYA_DEVICE_ID'], os.environ['TUYA_LOCAL_KEY'], ip,
                   os.environ['TUYA_VERSION'], os.environ['ONVIF_USERNAME'], os.environ['ONVIF_PASSWORD'],
                   os.getenv('ONVIF_NAME', 'Tuya ONVIF Local Bridge'), port, advertised,
                   str(uuid.uuid5(uuid.NAMESPACE_URL, 'tuya-onvif:' + os.environ['TUYA_DEVICE_ID'])),
                   os.getenv('ONVIF_DATA_PATH', '/data/presets.json'), default_timeout, max_timeout,
                   int(os.getenv('TUYA_RECONNECT_ATTEMPTS', '3')), float(os.getenv('TUYA_RECONNECT_DELAY', '2')),
                   codes, stream_uri)
