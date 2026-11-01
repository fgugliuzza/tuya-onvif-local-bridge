# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

from io import BytesIO
from pathlib import Path
import importlib.util
import pytest
from schema_dependencies import EXTERNAL_SCHEMAS

SPEC = importlib.util.spec_from_file_location('download_onvif_xsds', Path(__file__).resolve().parents[1] / 'scripts/download_onvif_xsds.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

class Response(BytesIO):
    def __enter__(self): return self
    def __exit__(self, *args): self.close()

def test_download_and_reuse(tmp_path):
    calls = []
    def opener(request, timeout):
        calls.append(request.full_url)
        namespace = next(ns for ns, (_, url) in EXTERNAL_SCHEMAS.items() if url == request.full_url)
        return Response(f'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="{namespace}"/>'.encode())
    MODULE.download(tmp_path, opener)
    assert len(calls) == len(EXTERNAL_SCHEMAS)
    MODULE.download(tmp_path, opener)
    assert len(calls) == len(EXTERNAL_SCHEMAS)

def test_rejects_wrong_namespace_without_writing(tmp_path):
    def opener(request, timeout):
        return Response(b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="wrong"/>')
    with pytest.raises(ValueError, match='targetNamespace'):
        MODULE.download(tmp_path, opener)
    assert not list(tmp_path.rglob('*.xsd'))


def test_onvif_archive_download_and_reuse(tmp_path):
    import zipfile
    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, 'w') as archive:
        for name in MODULE.REQUIRED_ONVIF_FILES:
            tag = 'definitions' if name.endswith('.wsdl') else 'schema'
            ns = 'http://schemas.xmlsoap.org/wsdl/' if name.endswith('.wsdl') else 'http://www.w3.org/2001/XMLSchema'
            archive.writestr(f'specs-development/wsdl/{name}', f'<root:{tag} xmlns:root="{ns}"/>')
    calls = []
    def opener(request, timeout):
        calls.append(request.full_url)
        return Response(archive_buffer.getvalue())
    MODULE.download_onvif(tmp_path, opener)
    assert len(calls) == 1
    for name in MODULE.REQUIRED_ONVIF_FILES:
        assert (tmp_path / name).is_file()
    MODULE.download_onvif(tmp_path, opener)
    assert len(calls) == 1

def test_onvif_archive_rejects_missing_files(tmp_path):
    import zipfile
    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, 'w') as archive:
        archive.writestr('specs-development/wsdl/ver10/schema/onvif.xsd', '<x/>')
    with pytest.raises(ValueError, match='missing required files'):
        MODULE.download_onvif(tmp_path, lambda request, timeout: Response(archive_buffer.getvalue()))
    assert not list(tmp_path.rglob('*.xsd'))
