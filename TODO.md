# TODO

- [ ] Implement safe Tuya preset deletion and ONVIF RemovePreset. Never send speculative DP178 type=2 payloads.
- [ ] Implement SetPreset overwrite. Potential method: delete existing camera preset and recreate with same seq/mpId; consider recovery if recreation fails.
- [ ] Synchronize favorites created by Smart Life (currently intentionally ignored).
- [ ] Implement full RTSP/media integration and Media2; optional ONVIF_STREAM_URI is currently a pass-through only.
- [ ] Confirm DP119 direction codes, DP116 stop semantics, and acknowledgements on hardware.
- [ ] Verify DP178 type=1 and type=3 acknowledgements and repeated identical operations on hardware.
- [ ] Implement verified status/position reporting and absolute/relative movement if supported.
- [ ] Add Hello/Bye WS-Discovery announcements and complete Resolve/Probe scopes matching.
- [ ] Improve ONVIF WSDL conformance and client interoperability (especially Frigate).
- [ ] Add hardware-based integration tests for real camera and client-specific tests.
- [ ] Resolve identical repeated DP178 acknowledgements without treating stale latched status as new success.
- [ ] Verify whether DP119 and DP116 provide application-level acknowledgements; current implementation only validates TinyTuya transport response.

- [ ] Consider supporting WS-Discovery 2009/01 and WS-Addressing 2005/08 in addition to the ONVIF/ODM 2005/04 + 2004/08 dialect.

- [ ] Autodetect actual RTSP stream parameters rather than advertising provisional H264 1920x1080/15fps metadata. Inspect video codec/profile, resolution, frame rate (measured where possible, not just nominal SDP), bitrate, GOP/keyframe interval when reliably available, and audio codec/sample rate/channels; propagate supported values consistently into ONVIF Media configurations and capabilities.
  - Prefer an in-process Python solution: evaluate **PyAV** (`av`, Python bindings to FFmpeg/libavformat) for RTSP probing; compare with `ffprobe -show_streams -of json` as a robust subprocess fallback. A fully pure-Python RTSP/SDP probe could avoid FFmpeg but may not reliably establish FPS/bitrate or codec details without examining RTP packets.
  - [x] Pass the **same ONVIF username/password from `.env`** to PyAV/libavformat for RTSP authentication; no specific RTSP authentication scheme is required.
  - [ ] Avoid exposing credentials in logs, process arguments, returned GetStreamUri values, exceptions, or diagnostics. Safely escape URL userinfo if used internally; ensure clients can still access the advertised stream using their own ONVIF credentials.
  - [ ] Probe at startup with bounded timeouts and handle failures gracefully; cache results and refresh on reconnection or stream configuration changes. Test unusual codecs and variable frame rates against physical hardware. Secondary stream URL discovery is explicitly out of scope; configure the intended stream URI manually.

- [ ] Full transitive WSDL/XSD schema validation (including imported ONVIF common schema), pinned and reproducible offline; current upstream checks verify only response declarations.
- [ ] Test v0.1.3 profile enumeration and PTZ UI with a real ODM instance.

- [ ] Investigate `xmlschema.XMLSchemaTypeTableWarning` for the upstream `tds:Capabilities` declarations; do not alter official ONVIF XSDs or globally suppress warnings.
- [ ] Run discovery → GetServices → GetProfiles → GetStreamUri → ContinuousMove → Stop against a real ONVIF client and physical Tuya camera; the automated HTTP test mocks Tuya transport.

- [ ] Hardware-verify the DP178 write-response acknowledgement fix with ONVIF Device Manager; capture the immediate `set_value()` result when reproducing. The 2026-11-01 capture confirmed a transient `type=1,error=0` status, but did not establish what TinyTuya's write response contains.

- [ ] Complete RTSP metadata probing: validate measured frame rate and GOP on physical cameras, refresh on stream URI configuration changes (currently requires restart), and advertise audio configurations where ONVIF-compatible. Automatic secondary stream discovery is out of scope. v0.1.17 samples presentation timestamps/keyframes and refreshes on Tuya reconnection.
