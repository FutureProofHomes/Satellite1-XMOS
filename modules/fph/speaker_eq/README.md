# Speaker EQ

`fph::speaker_eq` provides fixed-topology speaker equalization using the XMOS
`lib_audio_dsp` fixed-point biquads. Coefficients are designed outside the
real-time path and installed as complete programs at frame boundaries.

The runtime cascade contains two pass-filter sections, five peaking sections,
and one high-shelf section. Stereo-linked processing uses independent state per
channel. Mono processing averages the two inputs with a 64-bit intermediate,
processes one cascade, and duplicates the result.

The library owns no heap memory and provides no synchronization. A caller must
not call `speaker_eq_apply_program()` concurrently with
`speaker_eq_process_frame()`.

Headroom enforcement is a configurable product policy based on enabled boosts
and a safety margin. It reduces practical overflow risk but is not a proof
against every bounded full-scale input sequence because the upstream XMOS
biquad implementation does not saturate intermediate section outputs.

The reusable designer accepts product Q policies within the hard range 0.01 to
100. Product profiles should normally use a narrower range appropriate to their
tuning interface.
