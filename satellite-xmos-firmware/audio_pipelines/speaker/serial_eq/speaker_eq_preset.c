#include "speaker_eq_preset.h"

const speaker_eq_config_t speaker_eq_preset_config = {
    .channel_mode = SPEAKER_EQ_MODE_MONO,
    .bypass = false,
    .pregain_db = -8.0f,
    .clip_level_dbfs = 0.0f,
    .hpf_mode = SPEAKER_EQ_PASS_BUTTERWORTH_24,
    .hpf_frequency_hz = 70.0f,
    .peak = {
        {.enabled = true, .frequency_hz = 133.0f, .q = 1.690f, .gain_db = -4.0f},
        {.enabled = true, .frequency_hz = 1944.0f, .q = 1.300f, .gain_db = -13.5f},
        {.enabled = true, .frequency_hz = 3557.0f, .q = 3.100f, .gain_db = -5.0f},
        {.enabled = true, .frequency_hz = 14603.0f, .q = 1.300f, .gain_db = -7.0f},
        {.enabled = true, .frequency_hz = 5500.0f, .q = 2.000f, .gain_db = 5.0f},
    },
    .high_shelf = {
        .enabled = false,
        .frequency_hz = 10000.0f,
        .q = 0.70710678f,
        .gain_db = -3.0f,
    },
};

const speaker_eq_limits_t speaker_eq_preset_limits = {
    .minimum_frequency_hz = 10.0f,
    .maximum_frequency_hz = 20000.0f,
    .minimum_q = 0.1f,
    .maximum_q = 10.0f,
    .minimum_peak_gain_db = -18.0f,
    .maximum_peak_gain_db = 12.0f,
    .minimum_shelf_gain_db = -12.0f,
    .maximum_shelf_gain_db = 12.0f,
    .minimum_pregain_db = -24.0f,
    .maximum_pregain_db = 0.0f,
    .minimum_clip_level_dbfs = -12.0f,
    .headroom_margin_db = 3.0f,
    .enforce_headroom = true,
};
