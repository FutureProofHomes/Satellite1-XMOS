# IC-enabled dev.4: initial hardware observations

Observed November 24, 2026, with the FPH ESPHome host and Home Assistant.
No IC-bypassed image was installed in this run.

## Installed candidate

- XMOS: `v1.2.0-dev.4`, calibrated pre-AEC beam/omni, stereo-reference 2Y2X
  AEC, IC/VNR enabled, NS and AGC.
- XMOS factory SHA256:
  `c982e4cae654e22d80341093cc97e284ef5877ee2c032452d38437319f81a6ad`.
- XMOS flash MD5 verified during installation:
  `041cda8d3a804caa6732a52189d46087`.
- ESPHome host OTA image SHA256:
  `d5f76681a81f1cde7eb92467527f79cb9b658662dfa97f6f85e25b4c4c8d46e2`.
- FPH host source: `ef0b3d974e686c70bb4556321e1322b750eacc5c`,
  ESPHome 2026.10.2, project version `tater-xmos-calibrated_beam-dev`.
- XMOS source: `4a71d29b4a0882a969e3d3f18a4a436c151a14e6`;
  the later packaging-only commit does not alter its DSP sources.

The PR-readiness rebuild explicitly enables IC/VNR and reproduces the installed
XMOS factory image byte for byte, including the SHA256 above. The direction
estimator and beamformer host suites also pass on the cleaned-up branch.

## Voice observations

The user confirmed clear wake and voice replies from about one metre and
from the opposite side. The user also confirmed clear wake and reply while
the Sat1 was playing audio. The latter is a user-reported interruption check;
a controlled playback/wake timing trace has not yet been collected.

The initial USB trace captured two wake detections, with sliding probabilities
0.99 and 1.00, microphone streaming, speech transcription, response playback
completion and return to idle. One captured command was the time query. A
second captured query received Home Assistant's unsupported-intent response;
that is not a measured speech-recognition accuracy result. No panic, watchdog
or error-level DSP failure appeared in this observation window. These few
samples do not establish long-term stability or a benefit over IC bypass.

## Why the alternative pipeline is optional

Earlier Tater Native four-mic AEC integrations, dev.2 and dev.3, failed the
physical startup/liveness test: their DSP frame counters stopped advancing
and the wake microphone repeated a constant sample. The pre-AEC beam plus
two-channel AEC layout worked, so that layout was retained for the optional
pipeline tested here. Those candidates included Tater integration changes;
they were not byte-identical stock FPH images. These observations do not
establish that FPH's AEC algorithm caused the failure, identify a root cause,
or constitute a fix for a reported reboot issue. FPH's default four-mic AEC
pipeline remains unchanged in this branch.

## Subsequent tester reboot report

The tester subsequently reported hardware tests on a Satellite1 running Tater
Native firmware: both four-microphone AEC variants (residual averaging and
post-AEC beamforming) still exhibited the
reboot/audio stall with PR #132 applied. The tester also reported continued
normal operation after several reboots with this PR's calibrated-beam/two-channel
AEC pipeline running under FPH ESPHome. These are tester-reported reboot observations; the exact count,
reset methods and a controlled cold-power-cycle matrix were not recorded.
The FPH default four-mic AEC pipeline is unchanged by this PR.

## Follow-up ESPHome direction-display test

The same dev.4 XMOS image was subsequently used with the optional LED effects
in the [ESPHome companion branch](https://github.com/TaterTotterson/Satellite1-ESPHome/tree/feature/directional-led-animations).
The tester confirmed correct listening direction from opposite sides,
audio-reactive replies at the remembered direction, immediate live off/on
restoration of the original/new effects, and the later white-tip styling.
Voice replies worked in both modes. The host selects directional effects
only after observing an advancing XMOS frame counter; this exercises resource
233 and its progress gate, but is not a direct numerical telemetry/timing
capture. Microphone-health fault recovery remains unqualified on hardware.

## ESP32 boot-selection issue

A restart selected an older FPH ESP32 host in OTA app1 at `0x7d0000`:
project `satellite1`, ESPHome 2026.7.3, FPH v0.2.1, advertising an embedded
XMOS v1.0.3 image. That host reported `XMOS not responding`. The original test
host remained in app0 at `0x10000`. Both OTA selection records were valid,
with sequence 1 selecting app0 and sequence 2 selecting app1.

Only the ESP32 OTA-selection records at `0x9000..0xafff` were erased to restore
the original test host. No ESP32 application image or XMOS image was written
during this recovery. A subsequent boot selected app0, and the user confirmed
that wake and voice replies worked clearly again. Saved settings were retained.

The origin of the older image is unconfirmed; the user reported no manual
update. Do not attribute this observation to IC or classify it as a clean
restart qualification. Post-restore USB application logging was unavailable,
so voice recovery is user-confirmed rather than supported by a complete
post-restore DSP telemetry trace.

## Remaining checks

- Repeated cold-power cycles and repeatable host restart/OTA-slot behavior.
- Direct numerical direction-counter/health capture and measured DSP timing.
- Longer playback, moving talkers, distant speech, mute/volume and AUX routes.

The tester waived a controlled IC-on/off comparison after reporting that the
IC-enabled candidate worked well and appeared helpful. That comparison is not
a prerequisite for requesting upstream review; no isolated IC benefit is
claimed. Keep dev.4 as the selected candidate while collecting further results.
