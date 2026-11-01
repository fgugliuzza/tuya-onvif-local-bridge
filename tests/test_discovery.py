# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

import uuid
from types import SimpleNamespace
from lxml import etree as E
from tuya_onvif_local_bridge.discovery import Discovery, A, D, SOAP

class Transport:
    def __init__(self): self.sent = []
    def sendto(self, payload, addr): self.sent.append((payload, addr))

class FakeOnvif:
    cfg = SimpleNamespace(uuid=str(uuid.uuid4()))
    def scopes(self): return ['onvif://www.onvif.org/name/Test']
    def url(self, service): return 'http://192.168.0.104:8080/onvif/device_service'

def test_odm_probe_2005_responds():
    for type_name, namespace in [('NetworkVideoTransmitter', 'network'), ('Device', 'device')]:
        payload = f'''<s:Envelope xmlns:s="{SOAP}" xmlns:a="{A}"><s:Header>
          <a:Action>{D}/Probe</a:Action><a:MessageID>uuid:12345678-1234-1234-1234-123456789abc</a:MessageID>
          </s:Header><s:Body><Probe xmlns="{D}"><d:Types xmlns:d="{D}"
          xmlns:dp0="http://www.onvif.org/ver10/{namespace}/wsdl">dp0:{type_name}</d:Types>
          </Probe></s:Body></s:Envelope>'''.encode()
        discovery = Discovery(FakeOnvif())
        discovery.transport = Transport()
        discovery.datagram_received(payload, ('192.168.0.100', 64460))
        assert len(discovery.transport.sent) == 1
        response, addr = discovery.transport.sent[0]
        root = E.fromstring(response)
        assert addr == ('192.168.0.100', 64460)
        assert root.findtext(f'.//{{{A}}}Action') == f'{D}/ProbeMatches'
        assert root.findtext(f'.//{{{A}}}RelatesTo') == 'uuid:12345678-1234-1234-1234-123456789abc'
        assert root.findtext(f'.//{{{D}}}XAddrs') == 'http://192.168.0.104:8080/onvif/device_service'
