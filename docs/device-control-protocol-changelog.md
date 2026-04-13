# Device-Control Protocol Changelog

This changelog documents device-control protocol changes since `origin/main`.

Because `CONTROL_VERSION` was not consistently bumped during this period, the
entries below are keyed by commit. Starting now, every device-control protocol
change must also bump `CONTROL_VERSION` and add a versioned entry here.

## Scope

This file tracks changes that affect host-visible behavior, including:

- SPI transport framing or status semantics
- Resource IDs and command IDs
- Payload size or layout changes
- New or removed read/write commands

## Commit-based history (since `origin/main`)

### 2026-04-07 — 01748de

**fix mic output settings wire layout**

- Adjusted mic-output settings byte order to match the SDK wire layout.
- Gated ref-overwrite reads to tile 0 and explicitly disabled ref overwrite for
  ref-gain validation.
- Compatibility: breaking for hosts assuming the old mic-output settings layout.

### 2026-04-06 — 60f9977

**add mic output ref overwrite toggle**

- Added a device-control field and mask bit to enable/disable IC/NS ref
  overwrite in mic-output settings.
- Updated SPI protocol documentation and command index to include the new field.
- Compatibility: payload layout changed for mic-output settings (host decoder
  must be updated).

### 2026-04-06 — 92794ba

**add packaged-input debug plumbing**

- Added device-control-visible debug/diagnostic support for packaged input
  routing in the audio pipeline control servicer.
- Introduced additional command surface and payload structures for mic-input
  diagnostics and routing visibility.
- Compatibility: additive commands/payloads; update host to consume new fields.

### 2026-04-06 — a803b75

**Seed initial SPI status response to avoid zero-header false alarms**

- SPI transport now emits a status-only frame on the first transfer after
  registration (`tx[0]=1`, `tx[1]=CONTROL_SUCCESS`, plus status buffer).
- Host should treat this as a valid "device alive" response rather than a
  malformed header.
- Compatibility: transport behavior change; host retry logic must accept the
  initial status-only frame.

### 2026-03-30 — 3d42f15

**document and expose DoA SPI command payload types**

- Added/clarified payload structures for DoA read commands in the audio
  pipeline control servicer.
- Updated command index to include the new DoA-related payload definitions.
- Compatibility: additive command payload definitions; host may need struct
  updates for correct parsing.

### 2026-03-30 — d916967

**fix sat1 mic-input DoA frame handling and restore DoA SPI reads**

- Restored SPI read behavior for mic-input DoA data and corrected frame
  handling in the audio pipeline control servicer.
- Compatibility: host DoA read flows should now return valid data where
  previously they could fail or return stale/invalid payloads.

### 2026-03-28 — c837de7

**document 4-mic routing and mic-count command**

- Documented expanded mic-input routing layout and introduced
  `GET_AVAILABLE_MIC_COUNT` for resource `232` in the command index.
- Compatibility: new read command; host can use this to gate channel-count
  dependent behavior.

### 2026-03-28 — 1541459

**port audio pipeline control to four-mic sandbox**

- Split audio pipeline control into dedicated resources (`230`, `231`, `232`).
- Added a deprecated compatibility shim for the legacy audio_cfg servicer.
- Compatibility: resource IDs and routing changed; hosts must target the new
  resources to control mic output, speaker, and mic input settings.

### 2026-03-27 — 56796be

**extend mic-input device-control routing and document protocol changes**

- Expanded mic-input settings payloads to support routing modes and channel maps.
- Updated command index and SPI protocol docs to match new payload sizes/layouts.
- Compatibility: breaking payload size/layout change for mic-input settings
  commands (resource `232`).

### 2026-03-21 — 05c9c89

**split audio pipeline control resources by tile**

- Reassigned audio pipeline control resources to distinct tiles and updated
  settings structures accordingly.
- Compatibility: resource placement and routing changed; hosts must use the
  correct resource ID for tile-specific settings.

### 2026-03-21 — cfa4a16

**fix unaligned audio pipeline control payload handling**

- Corrected payload handling in the audio pipeline control servicer for
  unaligned access.
- Compatibility: payload layout unchanged; improves correctness for hosts
  sending previously valid payloads.

### 2026-03-21 — c7b1fcf

**report device-control readiness over status register**

- Device-control now reports readiness via the status buffer/register.
- Compatibility: additive status signaling; hosts can key readiness checks on
  the status buffer values.

### 2026-03-19 — 950a903

**introduce audio_pipeline_control servicer**

- Added the audio pipeline control servicer and the initial command surface for
  pipeline settings over device control.
- Compatibility: new servicer/resources; host support required to use these
  controls.
