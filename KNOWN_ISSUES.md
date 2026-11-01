# Known Issues

This file documents confirmed bugs and limitations in Tuya ONVIF Local Bridge.

## Spaces disappear from preset names in the Tuya app

- **Status:** Open
- **Severity:** Low
- **Component:** PTZ preset creation (DP178, type 1)
- **Observed firmware:** 1.5.616

### Description

When a PTZ preset is created through the ONVIF bridge with spaces in its name, the Tuya app displays the name without those spaces. For example, `sito 1` appears as `sito1`.

The bridge retains the original name (`sito 1`) in its local `presets.json` registry. Presets created directly in the Tuya app retain spaces normally.

### Expected behavior

Preset names retain their spaces regardless of how they are created.

### Actual behavior

The Tuya app removes spaces from names of presets created through the bridge. This occurs immediately and persists after closing and reopening the app.

### Suspected cause

The camera firmware may process names supplied through the local DP178 interface differently from names created through the app. The cause has **not** been verified.

### Workaround

Use names without spaces for presets created through the ONVIF bridge.

### Notes

Preset creation succeeds, and the bridge's local registry preserves the original name. Further investigation is deferred.

## Preset recall has no application-level acknowledgement

- **Status:** Open (handled by best-effort behavior)
- **Severity:** Low
- **Component:** PTZ preset recall (DP178, type 3)
- **Observed firmware:** 1.5.616

### Description

On preset recall, the camera has been observed to send a valid Tuya protocol `cmd=13` frame with an empty payload. TinyTuya may subsequently return `None` instead of an application-level acknowledgement, even when the camera moves to the requested preset.

### Current behavior

The bridge accepts this response as **unconfirmed, best-effort completion** and does **not** retry the recall. This avoids reporting a false transport failure or causing duplicate movement. The unconfirmed outcome is logged at `DEBUG` level rather than `WARNING`. Explicit transport errors are still reported.

### Limitation

A `None` result does not prove that the camera executed the command: a genuine missing response can look the same. No reliable application-level confirmation is currently available for this observed response pattern.
