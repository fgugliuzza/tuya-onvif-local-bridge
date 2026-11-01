# Tuya ONVIF PTZ bridge (experimental)

A Python bridge exposing ONVIF Device, Media (minimal), PTZ, and WS-Discovery for a Tuya LAN camera using TinyTuya. **Not yet hardware-validated or ONVIF-conformance-certified.**

## Setup

1. `cp .env.example .env`, edit every mandatory setting (including `TUYA_VERSION` and `ONVIF_STREAM_URI`).
2. `mkdir -p data && sudo chown 10001:10001 data` (container runs as UID 10001).
3. `docker compose up --build -d`.
4. Inspect `docker compose logs -f`; check `curl http://localhost:8080/healthz`.
5. The ONVIF Device service is `http://<bridge-ip>:8080/onvif/device_service`. WS-Discovery uses UDP multicast `239.255.255.250:3702`.

Use a separate `.env` and data directory per camera. Don't expose the ONVIF HTTP port to untrusted networks; HTTP is unencrypted and the bridge supports UsernameToken authentication. `ONVIF_ADVERTISE_IP` is useful on multihomed hosts. `ONVIF_NAME` is used in WS-Discovery scopes. UUIDv5 is deterministically derived from `TUYA_DEVICE_ID`.

## Presets

The bridge starts with an empty JSON registry and **does not import** Smart Life favorites. It allocates the lowest available positive `seq`, stores `mpId=str(seq)` separately, and rejects malformed registry data on startup. Creation requires matching DP178 `type=1` and `data.error=0`; recall sends `type=3` once and treats an empty TinyTuya response as best-effort (not confirmed) success; explicit transport errors still fail. Deletion and overwrite are deliberately unsupported. Failed/timeout operations are not persisted; retry may reuse `seq`. Since Tuya status can contain stale acknowledgements, validate behavior on the actual camera before production use.

## Movement

Eight directions are mapped via `TUYA_DIRECTION_CODES`. **Default numeric codes are provisional** and must be validated against your camera before use. Movement is serialized and auto-stops after the requested ONVIF timeout, bounded by `PTZ_MAX_TIMEOUT`. DP119/DP116 don't yet have camera-verified application-level acknowledgements. See TODO.

## Development

`pip install -e '.[test]' && pytest -q`. The test suite uses mock devices; hardware tests should be performed separately and carefully. TinyTuya debug logs may contain sensitive data, so don't enable them in production.

## Limitations

The Media profile advertises H.264 video encoder metadata and a required `ONVIF_STREAM_URI` (RTSP/RTSPS). The URI is returned verbatim by `GetStreamUri`; the bridge does not proxy or validate the stream. Resolution, frame rate, bitrate and codec settings are currently fixed advertised metadata, not discovered from the camera: adjust the code if your stream differs. Authentication for the RTSP server is independent of ONVIF authentication. WS-Discovery supports Probe and Resolve; Hello/Bye are pending. Client interoperability needs testing. A lost connection triggers bounded reconnect attempts, then process exit for Docker restart.

### Important acknowledgement caveat

DP178 status is a latched datapoint rather than a correlated request/response channel. The implementation requires the acknowledgement value to change after the command. A repeated operation whose successful acknowledgement is byte-for-byte identical to the previous value can therefore time out even when the camera executes it. This intentionally favors avoiding false success; a stronger correlation mechanism remains a hardware-validation TODO. DP119/DP116 acknowledgement semantics remain unverified and currently rely on TinyTuya transport acceptance.

## WS-Discovery interoperability (v0.1.1)

ONVIF Device Manager sends WS-Discovery April 2005 Probe messages using WS-Addressing August 2004. The bridge uses these namespaces for its discovery replies. Discovery replies are logged at INFO level; run `docker compose logs -f tuya-onvif-local-bridge` and look for `WS-Discovery ProbeMatches sent` while scanning. This version does not implement dual-stack 2005/2009 WS-Discovery negotiation.

## v0.1.2

`ONVIF_STREAM_URI` is required at startup (no default). Media `GetProfiles` now includes a video encoder configuration, plus read-only video configuration query endpoints for ODM interoperability. Video metadata is provisional; no RTSP proxy is provided.

## v0.1.3 — ONVIF XML interoperability

Corrected Media response wrapper element namespaces (`trt:Profiles`, `trt:Profile`,
`trt:VideoSources`, and configuration wrappers), and PTZ response wrappers.
The nested profile/configuration objects still use the ONVIF common schema (`tt`).
`ONVIF_STREAM_URI` remains mandatory and unchanged.

Run `python -m pytest -q` for offline qualified-name regression checks.
Run `ONVIF_VALIDATE_UPSTREAM=1 python -m pytest -q tests/test_wsdl_contract.py`
with internet access for checks against the official Device, Media and PTZ WSDLs.
These upstream checks verify top-level response declarations, **not** complete
nested XSD validation; full transitive schema validation remains future work.

### Full XSD response validation (v0.1.4)

The `tests/test_schema_conformance.py` suite validates **actual SOAP response
body elements** against the official Device, Media and PTZ WSDL inline XSDs,
including their imported ONVIF schemas. Supply a local mirror of the official
WSDL/XSD dependencies, preserving URL paths, then run:

```sh
ONVIF_SCHEMA_DIR=/path/to/onvif-schema-mirror python -m pytest -q tests/test_schema_conformance.py
```

Without `ONVIF_SCHEMA_DIR`, these integration tests skip. With it set, missing
imports and schema violations are failures. This checks the responses in the
`CASES` table, not every possible ONVIF operation, nor WS-Discovery or transport.
The schema mirror must include external standards XSD imports too.

### Offline official-schema validation (XSD 1.1)

Install the test extras (`pip install -e '.[test]'`) and supply a local
ONVIF WSDL/XSD mirror, including the eight external namespace dependencies:

```sh
ONVIF_SCHEMA_DIR=/path/to/onvif-schema-mirror python -m pytest -q tests/test_schema_conformance.py
```

The suite uses `xmlschema.XMLSchema11` rather than libxml2's XSD 1.0 compiler,
which rejects ambiguous element/wildcard content models in the unmodified
upstream schemas. The test **fails**, rather than skips, when the mirror is set
but a dependency is missing or a response violates the schema. These are
22 representative response cases, not ONVIF certification.

### Bootstrap official ONVIF WSDLs and external XSDs for offline schema tests

Set `ONVIF_SCHEMA_DIR` to an actual directory containing the official ONVIF
`ver10/` and `ver20/` WSDL/XSD tree (not the literal example path).
The script downloads the official ONVIF `development` WSDL/XSD tree from the
ONVIF specs GitHub archive if it is missing, as well as external dependencies.
The downloader fetches only missing or invalid **external** XSDs and verifies
their `targetNamespace` before saving. Use `--external-only` to skip the ONVIF archive.

```bash
python scripts/download_onvif_xsds.py --directory "$ONVIF_SCHEMA_DIR"
python -m pytest -q tests/test_schema_conformance.py
```

The test suite itself never downloads dependencies. Network access is required
only for the explicit bootstrap command.

### ONVIF client control sequence (v0.1.9)

`tests/test_control_sequence.py` exercises a real loopback HTTP server and SOAP
UsernameToken authentication, from a WS-Discovery Probe through GetServices,
GetProfiles, GetStreamUri, ContinuousMove, and Stop. The Tuya camera is mocked;
physical PTZ operation and third-party client interoperability remain manual checks.

```sh
python -m pytest -q tests/test_control_sequence.py
```

## v0.1.13 — project rename

Distribution/repository/CLI/Compose service: `tuya-onvif-local-bridge`; Python import: `tuya_onvif_local_bridge`. Existing `.env` variables, `/data/presets.json` and deterministic ONVIF UUID seed remain unchanged. The CLI and Python imports are intentionally breaking changes.

## Known issues

See [KNOWN_ISSUES.md](KNOWN_ISSUES.md) for confirmed bugs and limitations.


## AI-assisted development

This project was developed by Francesco Gugliuzza with the assistance of OpenAI's ChatGPT.

AI assistance was used for code generation, debugging, documentation, and testing. Project requirements, technical decisions, and development direction were provided by the author.

The project is maintained by Francesco Gugliuzza and distributed under the GNU General Public License v3.0 or later (`GPL-3.0-or-later`).

## Copyright and license

Copyright © 2026 Francesco Gugliuzza.

Licensed under the GNU General Public License, version 3 or (at your option) any later version (`GPL-3.0-or-later`). See [LICENSE](LICENSE) for the full license text.

- Author: [Francesco Gugliuzza](https://github.com/fgugliuzza)
- Website: https://gugliuzza.cloud
- Project source: https://github.com/fgugliuzza/tuya-onvif-local-bridge

The project’s third-party dependencies retain their respective licenses.
