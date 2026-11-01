# SPDX-FileCopyrightText: 2026 Francesco Gugliuzza
# SPDX-License-Identifier: GPL-3.0-or-later

#!/usr/bin/env python3
"""Explicitly fetch missing external schemas for offline ONVIF contract tests."""
import argparse
import io
import zipfile
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from schema_dependencies import EXTERNAL_SCHEMAS

ONVIF_ARCHIVE_URL = "https://github.com/onvif/specs/archive/refs/heads/development.zip"
REQUIRED_ONVIF_FILES = (
    "ver10/device/wsdl/devicemgmt.wsdl",
    "ver10/media/wsdl/media.wsdl",
    "ver20/ptz/wsdl/ptz.wsdl",
    "ver10/schema/onvif.xsd",
)
MAX_ARCHIVE_SIZE = 32 * 1024 * 1024
MAX_EXTRACTED_SIZE = 64 * 1024 * 1024


def download_onvif(directory, opener=urlopen):
    """Install the official ONVIF WSDL/XSD tree from the upstream specs archive."""
    if all((directory / name).is_file() for name in REQUIRED_ONVIF_FILES):
        print("OK official ONVIF WSDL/XSD tree")
        return
    print(f"Fetching {ONVIF_ARCHIVE_URL}")
    request = Request(ONVIF_ARCHIVE_URL, headers={"User-Agent": "tuya-onvif-local-bridge-schema-bootstrap/0.1.7"})
    with opener(request, timeout=60) as response:
        data = response.read(MAX_ARCHIVE_SIZE + 1)
    if len(data) > MAX_ARCHIVE_SIZE:
        raise ValueError("ONVIF archive exceeds download size limit")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = {}
        total = 0
        for entry in archive.infolist():
            parts = Path(entry.filename).parts
            if len(parts) < 4 or parts[1] != "wsdl" or entry.is_dir():
                continue
            relative = Path(*parts[2:])
            if any(part in (".", "..") for part in relative.parts):
                raise ValueError(f"Unsafe archive path: {entry.filename}")
            if relative.suffix not in (".wsdl", ".xsd", ".xml"):
                continue
            total += entry.file_size
            if total > MAX_EXTRACTED_SIZE:
                raise ValueError("ONVIF WSDL/XSD tree exceeds extracted size limit")
            members[relative.as_posix()] = entry
        missing = set(REQUIRED_ONVIF_FILES) - set(members)
        if missing:
            raise ValueError(f"ONVIF archive is missing required files: {sorted(missing)}")
        for relative, entry in members.items():
            destination = directory / relative
            if destination.is_file():
                continue
            content = archive.read(entry)
            if len(content) != entry.file_size:
                raise ValueError(f"Unexpected size for {relative}")
            # Reject HTML error pages and malformed XML before installation.
            root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
            if relative.endswith(".wsdl") and root.tag != "{http://schemas.xmlsoap.org/wsdl/}definitions":
                raise ValueError(f"Not a WSDL document: {relative}")
            if relative.endswith(".xsd") and root.tag != "{http://www.w3.org/2001/XMLSchema}schema":
                raise ValueError(f"Not an XSD document: {relative}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + ".tmp")
            try:
                temporary.write_bytes(content)
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
        print(f"Official ONVIF WSDL/XSD tree ready ({len(members)} archive files checked)")



def download(directory, opener=urlopen):
    for namespace, (relative, url) in EXTERNAL_SCHEMAS.items():
        destination = directory / relative
        if destination.is_file():
            try:
                root = etree.parse(str(destination)).getroot()
                if root.tag == '{http://www.w3.org/2001/XMLSchema}schema' and root.get('targetNamespace') == namespace:
                    print(f'OK {destination}')
                    continue
            except etree.XMLSyntaxError:
                pass
            print(f'Replacing invalid schema: {destination}')
        print(f'Fetching {url}')
        request = Request(url, headers={'User-Agent': 'tuya-onvif-local-bridge-schema-bootstrap/0.1.6'})
        with opener(request, timeout=30) as response:
            data = response.read(4 * 1024 * 1024 + 1)
        if len(data) > 4 * 1024 * 1024:
            raise ValueError(f'Schema exceeds size limit: {url}')
        parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
        root = etree.fromstring(data, parser)
        if root.tag != '{http://www.w3.org/2001/XMLSchema}schema' or root.get('targetNamespace') != namespace:
            raise ValueError(f'Incorrect XSD targetNamespace at {url}: {root.get("targetNamespace")!r}')
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + '.tmp')
        try:
            temporary.write_bytes(data)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    print('External schemas ready.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True, help='Root of ONVIF schema mirror')
    parser.add_argument('--external-only', action='store_true', help='Skip official ONVIF WSDL/XSD download')
    args = parser.parse_args()
    directory = args.directory.expanduser().resolve()
    if not args.external_only:
        download_onvif(directory)
    download(directory)
