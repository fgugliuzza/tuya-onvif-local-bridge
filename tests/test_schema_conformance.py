# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

"""Validate actual generated ONVIF SOAP bodies against official transitive XSDs.

Requires a local mirror of the official ONVIF WSDL/XSD tree and its external
imports. Run: ONVIF_SCHEMA_DIR=/path/to/schema-tree pytest -q tests/test_schema_conformance.py

The mirror should preserve the URL paths (e.g. ver10/media/wsdl/media.wsdl,
ver10/schema/onvif.xsd) and external imported schemas under their URL hostnames.
Missing dependencies or invalid schemas FAIL, never silently skip.
"""
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from lxml import etree as ET
import pytest
from tuya_onvif_local_bridge.onvif import Onvif
from tuya_onvif_local_bridge.soap import T, M, P, envelope

S = 'http://www.w3.org/2003/05/soap-envelope'
XSD = 'http://www.w3.org/2001/XMLSchema'
WSDL = 'http://schemas.xmlsoap.org/wsdl/'
WSDL_PATHS = {
    T: 'ver10/device/wsdl/devicemgmt.wsdl',
    M: 'ver10/media/wsdl/media.wsdl',
    P: 'ver20/ptz/wsdl/ptz.wsdl',
}

@pytest.fixture(scope='module')
def schemas():
    directory = os.environ.get('ONVIF_SCHEMA_DIR')
    if not directory:
        pytest.skip('Set ONVIF_SCHEMA_DIR to enable full response schema validation')
    # Do not use lxml/libxml2's XSD 1.0 compiler here: the upstream ONVIF
    # schemas contain element/wildcard content models that it rejects as UPA.
    # XML Schema 1.1 relaxes this particular restriction; keep the official
    # documents byte-for-byte intact rather than patching them for testing.
    import xmlschema
    directory = Path(directory).resolve()
    # Explicit namespace mapping prevents attempts to download dependencies.
    # The XMLSchema11 loader still resolves relative includes against each
    # schema's actual source file, preserving the official WSDL layout.
    from schema_dependencies import EXTERNAL_SCHEMAS
    externals = {namespace: relative for namespace, (relative, _) in EXTERNAL_SCHEMAS.items()}
    locations = []
    for namespace, relative in externals.items():
        path = directory / relative
        if not path.is_file():
            raise FileNotFoundError(f'Missing external XSD for {namespace}: {path}. Run: python scripts/download_onvif_xsds.py --directory {directory}')
        locations.append((namespace, str(path)))
    compiled = {}
    for namespace, relative in WSDL_PATHS.items():
        wsdl_path = directory / relative
        if not wsdl_path.is_file():
            raise FileNotFoundError(f'Missing official WSDL: {wsdl_path}')
        document = ET.parse(str(wsdl_path), ET.XMLParser(no_network=True, resolve_entities=False))
        embedded = document.xpath('//wsdl:types/xs:schema', namespaces={'wsdl': WSDL, 'xs': XSD})
        selected = [node for node in embedded if node.get('targetNamespace') == namespace]
        assert len(selected) == 1, f'Expected exactly one inline schema for {namespace}'
        # Use the WSDL's parent as the base for its relative schema imports.
        compiled[namespace] = xmlschema.XMLSchema11(
            ET.tostring(selected[0]), base_url=wsdl_path.parent.as_uri() + '/',
            locations=locations, allow='local', validation='strict',
        )
    return compiled

@pytest.fixture
def bridge():
    cfg = SimpleNamespace(name='Test camera', stream_uri='rtsp://127.0.0.1/test',
        default_timeout=5, max_timeout=30, advertise_ip='127.0.0.1',
        port=8080, device_id='test', uuid='uuid')
    return Onvif(cfg, None, SimpleNamespace(data={'presets': []}))

CASES = [
    ('device', 'GetSystemDateAndTime'), ('device', 'GetDeviceInformation'),
    ('device', 'GetServices'), ('device', 'GetCapabilities'),
    ('device', 'GetScopes'), ('device', 'GetHostname'),
    ('media', 'GetProfiles'), ('media', 'GetProfile'),
    ('media', 'GetVideoSources'), ('media', 'GetVideoSourceConfigurations'),
    ('media', 'GetVideoSourceConfiguration'), ('media', 'GetVideoEncoderConfigurations'),
    ('media', 'GetVideoEncoderConfiguration'),
    ('media', 'GetVideoEncoderConfigurationOptions'), ('media', 'GetStreamUri'),
    ('media', 'GetServiceCapabilities'),
    ('ptz', 'GetNodes'), ('ptz', 'GetNode'),
    ('ptz', 'GetConfigurations'), ('ptz', 'GetConfiguration'),
    ('ptz', 'GetConfigurationOptions'), ('ptz', 'GetPresets'),
]

@pytest.mark.asyncio
@pytest.mark.parametrize('service,operation', CASES)
async def test_response_schema(bridge, schemas, service, operation):
    namespace = {'device': T, 'media': M, 'ptz': P}[service]
    _, request = envelope(namespace, operation)
    params = {
        'GetProfile': ('ProfileToken', bridge.profile),
        'GetVideoSourceConfiguration': ('ConfigurationToken', 'video_source_config_1'),
        'GetVideoEncoderConfiguration': ('ConfigurationToken', 'video_encoder_config_1'),
        'GetNode': ('NodeToken', bridge.node),
        'GetConfiguration': ('PTZConfigurationToken', bridge.ptzconfig),
        'GetConfigurationOptions': ('ConfigurationToken', bridge.ptzconfig),
        'GetStreamUri': ('ProfileToken', bridge.profile),
    }
    if operation in params:
        name, value = params[operation]
        ET.SubElement(request, f'{{{namespace}}}{name}').text = value
    response = await getattr(bridge, f'{service}_{operation}')(request)
    body = response.find(f'{{{S}}}Body')
    assert body is not None and len(body) == 1
    element = body[0]
    schema = schemas[namespace]
    errors = list(schema.iter_errors(ET.tostring(element)))
    assert not errors, (
        f'{service}.{operation}:\n' + '\n'.join(str(error) for error in errors)
        + '\n' + ET.tostring(element, pretty_print=True, encoding='unicode')
    )
