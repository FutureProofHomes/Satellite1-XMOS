# Optional four-microphone direction and health diagnostics

Configure with `-DENABLE_SAT1_DIRECTION_FINDING=ON` to expose SPI resource
**233** on four-microphone targets. The default is **OFF**. This option observes
the raw East, West, North, South microphone frames before input gain. It does
not change the upstream AEC, residual averaging, input gain, noise suppression,
AGC, I2S channel layout, or default build selection.

Resource 233 reserves the speaker/EQ and input-configuration resource range.
Protocol 0x11 framing is unchanged. Read commands request one additional byte
for handler status, and the transport adds its payload-available marker.

| Command | Direction | Data bytes | Contents |
| --- | --- | ---: | --- |
| 0 | Read | 32 | Direction, confidence, activity flags, energy, frame counter, four mic energies |
| 1 | Read | 48 | Fractional delays, noise floor, controls, active mic mask, gains, health, levels |
| 2 | Write | 1 | Steering control flags: freeze, TV mode, force omni |

Exact byte offsets and flag values are documented in `doa/doa_cmds.h` and
`doa/doa_estimator.h`. Calibration and health are computed from raw levels;
echo-cancelled silence does not train calibration. Diagnostic gains/delays do
not alter audio unless the optional calibrated-beam pipeline is selected.

The algorithms come from Tater Native's tested pre-AEC directional pipeline
(native source release `native-0.7.0-r1`, XMOS `1.2.0-dev.1`). This upstream
integration is a new build and requires its own hardware tests. Run the host
arithmetic, direction, health and recovery checks with:

```sh
bash scripts/test_doa_estimator_host.sh
```

Physical checks must confirm advancing frame counters, changing processed
microphone samples, startup/restart recovery and playback behavior. A working
SPI version read alone is insufficient evidence of live DSP.
