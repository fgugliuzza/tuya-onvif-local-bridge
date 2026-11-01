# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

"""Qualified-name regression tests plus opt-in checks against upstream ONVIF WSDLs.

Run `ONVIF_VALIDATE_UPSTREAM=1 pytest -q tests/test_wsdl_contract.py` with
network access to validate operation response element declarations against the
published WSDLs. The offline tests always run.
"""
import os
from types import SimpleNamespace
from urllib.request import urlopen
from lxml import etree as ET
import pytest
from tuya_onvif_local_bridge.onvif import Onvif
from tuya_onvif_local_bridge.soap import M, P, T, TT, envelope

WSDL_URLS = {
    T: 'https://www.onvif.org/ver10/device/wsdl/devicemgmt.wsdl',
    M: 'https://www.onvif.org/ver10/media/wsdl/media.wsdl',
    P: 'https://www.onvif.org/ver20/ptz/wsdl/ptz.wsdl',
}

@pytest.fixture
def bridge():
    config = SimpleNamespace(name='Test camera', stream_uri='rtsp://127.0.0.1/test',
                             default_timeout=5, max_timeout=30, advertise_ip='127.0.0.1',
                             port=8080, device_id='test', uuid='uuid')
    return Onvif(config, None, SimpleNamespace(data={'presets': []}))

@pytest.mark.asyncio
@pytest.mark.parametrize('service,operation,child,namespace', [
    ('media','GetProfiles','Profiles',M),
    ('media','GetProfile','Profile',M),
    ('media','GetVideoSources','VideoSources',M),
    ('media','GetVideoSourceConfigurations','Configurations',M),
    ('media','GetVideoSourceConfiguration','Configuration',M),
    ('media','GetVideoEncoderConfigurations','Configurations',M),
    ('media','GetVideoEncoderConfiguration','Configuration',M),
    ('media','GetVideoEncoderConfigurationOptions','Options',M),
    ('media','GetStreamUri','MediaUri',M),
    ('ptz','GetNodes','PTZNode',P),
    ('ptz','GetNode','PTZNode',P),
    ('ptz','GetConfigurations','PTZConfiguration',P),
    ('ptz','GetConfiguration','PTZConfiguration',P),
    ('ptz','GetPresets',None,P),
])
async def test_response_element_qnames(bridge, service, operation, child, namespace):
    ns = M if service == 'media' else P
    _, request = envelope(ns, operation)
    if operation == 'GetProfile': ET.SubElement(request, f'{{{ns}}}ProfileToken').text = bridge.profile
    if operation in ('GetVideoSourceConfiguration', 'GetVideoEncoderConfiguration'):
        ET.SubElement(request, f'{{{ns}}}ConfigurationToken').text = (
            'video_source_config_1' if 'Source' in operation else 'video_encoder_config_1')
    if operation == 'GetNode': ET.SubElement(request, f'{{{ns}}}NodeToken').text = bridge.node
    if operation == 'GetConfiguration': ET.SubElement(request, f'{{{ns}}}PTZConfigurationToken').text = bridge.ptzconfig
    response = await getattr(bridge, f'{service}_{operation}')(request)
    body = response.find('{http://www.w3.org/2003/05/soap-envelope}Body')
    result = body[0]
    assert result.tag == f'{{{ns}}}{operation}Response'
    if child:
        assert len(result) == 1
        assert result[0].tag == f'{{{namespace}}}{child}'
    else:
        assert len(result) == 0

@pytest.mark.asyncio
async def test_nested_profile_qnames(bridge):
    _, request = envelope(M, 'GetProfiles')
    result = (await bridge.media_GetProfiles(request)).find(f'.//{{{M}}}Profiles')
    assert result is not None
    assert [x.tag for x in result] == [f'{{{TT}}}{n}' for n in (
        'Name', 'VideoSourceConfiguration', 'VideoEncoderConfiguration', 'PTZConfiguration')]
    assert result.find(f'{{{TT}}}VideoSourceConfiguration/{{{TT}}}SourceToken').text == 'video_source_1'
    assert result.find(f'{{{TT}}}PTZConfiguration/{{{TT}}}NodeToken').text == 'node_1'

@pytest.mark.skipif(os.environ.get('ONVIF_VALIDATE_UPSTREAM') != '1',
                    reason='Opt-in live ONVIF WSDL check (requires internet)')
@pytest.mark.parametrize('namespace,operations', [
    (T, ['GetServices', 'GetCapabilities', 'GetDeviceInformation', 'GetScopes']),
    (M, ['GetProfiles', 'GetProfile', 'GetVideoSources', 'GetVideoSourceConfigurations',
         'GetVideoSourceConfiguration', 'GetVideoEncoderConfigurations',
         'GetVideoEncoderConfiguration', 'GetVideoEncoderConfigurationOptions',
         'GetStreamUri', 'GetServiceCapabilities']),
    (P, ['GetNodes', 'GetNode', 'GetConfigurations', 'GetConfiguration',
         'GetConfigurationOptions', 'GetPresets', 'SetPreset', 'GotoPreset',
         'RemovePreset', 'ContinuousMove', 'Stop']),
])
def test_official_wsdl_declares_response_elements(namespace, operations):
    # This checks the actual upstream WSDL declarations and their target namespace.
    # It is NOT full schema validation of every nested response type.
    with urlopen(WSDL_URLS[namespace], timeout=20) as response:
        root = ET.fromstring(response.read(), parser=ET.XMLParser(resolve_entities=False, no_network=True))
    xs = 'http://www.w3.org/2001/XMLSchema'
    schemas = root.xpath('.//xs:schema', namespaces={'xs': xs})
    own_schemas = [s for s in schemas if s.get('targetNamespace') == namespace]
    assert own_schemas, f'No inline schema for {namespace}; resolve WSDL imports to validate it'
    names = {e.get('name') for s in own_schemas for e in s.findall(f'{{{xs}}}element')}
    for op in operations:
        assert f'{op}Response' in names, (namespace, op)
