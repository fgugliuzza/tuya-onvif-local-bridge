# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

"""Real SOAP/HTTP client sequence against an in-process bridge.

Tuya transport is deliberately mocked: this is a wire-protocol integration
check, NOT evidence that the physical camera executed a movement.
"""
import base64
import datetime as dt
import hashlib
import secrets
from types import SimpleNamespace

import pytest
from aiohttp import ClientSession, web
from lxml import etree as E

from tuya_onvif_local_bridge.onvif import Onvif
from tuya_onvif_local_bridge.soap import M, P, S, T, TT, W, U, el, envelope, xml
from tuya_onvif_local_bridge.discovery import Discovery, A, D


class FakeCamera:
    def __init__(self):
        self.calls = []

    async def move(self, direction, timeout):
        self.calls.append(('move', direction, timeout))

    async def stop(self):
        self.calls.append(('stop',))


class CaptureTransport:
    def __init__(self): self.packets = []
    def sendto(self, data, addr): self.packets.append((data, addr))


def digest_header(root, username='admin', password='secret'):
    nonce = secrets.token_bytes(16)
    created = dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z')
    digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + password.encode()).digest()).decode()
    header = E.Element(f'{{{S}}}Header')
    root.insert(0, header)
    security = el(header, W, 'Security')
    token = el(security, W, 'UsernameToken')
    el(token, W, 'Username', username)
    el(token, W, 'Password', digest, Type='http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest')
    el(token, W, 'Nonce', base64.b64encode(nonce).decode())
    el(token, U, 'Created', created)


@pytest.mark.asyncio
async def test_discovery_to_stream_to_ptz_over_http():
    camera = FakeCamera()
    cfg = SimpleNamespace(name='Test camera', stream_uri='rtsp://127.0.0.1:8554/camera',
        default_timeout=5, max_timeout=30, advertise_ip='127.0.0.1', port=0,
        device_id='test', uuid='12345678-1234-1234-1234-123456789abc',
        username='admin', password='secret')
    bridge = Onvif(cfg, camera, SimpleNamespace(data={'presets': []}))
    app = web.Application()
    for service in ('device', 'media', 'ptz'):
        app.router.add_post(f'/onvif/{service}_service', bridge.handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    cfg.port = site._server.sockets[0].getsockname()[1]

    async def call(session, url, ns, operation, args=(), auth=True):
        root, action = envelope(ns, operation)
        for key, value in args:
            if isinstance(value, dict):
                parent = el(action, ns, key)
                for child, attrs in value.items():
                    el(parent, TT, child, **attrs)
            else:
                el(action, ns, key, value)
        if auth: digest_header(root)
        async with session.post(url, data=xml(root), headers={'Content-Type': 'application/soap+xml'}) as response:
            body = E.fromstring(await response.read())
            assert response.status == 200, E.tostring(body, encoding='unicode')
            assert body.tag == f'{{{S}}}Envelope'
            content = body.find(f'{{{S}}}Body')
            assert content is not None and len(content) == 1
            assert content[0].tag == f'{{{ns}}}{operation}Response'
            return content[0]

    try:
        # The same WS-Discovery Probe an ONVIF client sends on UDP 3702.
        probe = E.Element(f'{{{S}}}Envelope', nsmap={'s': S, 'a': A, 'd': D})
        head = el(probe, S, 'Header')
        el(head, A, 'Action', D + '/Probe')
        el(head, A, 'MessageID', 'urn:uuid:11111111-1111-1111-1111-111111111111')
        body = el(probe, S, 'Body')
        el(body, D, 'Probe')
        discovery = Discovery(bridge)
        transport = CaptureTransport()
        discovery.transport = transport
        discovery.datagram_received(xml(probe), ('127.0.0.1', 50000))
        assert len(transport.packets) == 1
        discovery_response = E.fromstring(transport.packets[0][0])
        device_url = discovery_response.findtext(f'.//{{{D}}}XAddrs')
        assert device_url == bridge.url('device')

        async with ClientSession() as session:
            services = await call(session, device_url, T, 'GetServices', auth=False)
            advertised = {
                s.findtext(f'{{{T}}}Namespace'): s.findtext(f'{{{T}}}XAddr')
                for s in services.findall(f'{{{T}}}Service')
            }
            assert advertised[T] == device_url
            assert advertised[M] == bridge.url('media')
            assert advertised[P] == bridge.url('ptz')

            profiles = await call(session, advertised[M], M, 'GetProfiles')
            profile = profiles.find(f'{{{M}}}Profiles')
            assert profile is not None
            token = profile.get('token')
            assert token
            assert profile.find(f'{{{TT}}}PTZConfiguration') is not None

            uri_response = await call(session, advertised[M], M, 'GetStreamUri',
                [('ProfileToken', token)])
            assert uri_response.findtext(f'.//{{{TT}}}Uri') == cfg.stream_uri

            await call(session, advertised[P], P, 'ContinuousMove', [
                ('ProfileToken', token),
                ('Velocity', {'PanTilt': {'x': '0.5', 'y': '-0.5',
                    'space': 'http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace'}}),
                ('Timeout', 'PT2S'),
            ])
            await call(session, advertised[P], P, 'Stop', [('ProfileToken', token), ('PanTilt', 'true')])
            assert camera.calls == [('move', 'down-right', 2.0), ('stop',)]
    finally:
        await runner.cleanup()
