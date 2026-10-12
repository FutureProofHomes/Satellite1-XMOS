#include "speaker_eq.h"

#include <limits.h>
#include <math.h>
#include <string.h>

#include "control/adsp_control.h"

#define Q30_SCALE 1073741824.0
#define SPEAKER_EQ_HARD_PEAK_GAIN_DB 18.0f
#define SPEAKER_EQ_HARD_SHELF_GAIN_DB 12.0f
#define SPEAKER_EQ_HARD_MINIMUM_Q 0.01f
#define SPEAKER_EQ_HARD_MAXIMUM_Q 100.0f

static bool finite_in_range(float value, float minimum, float maximum)
{
    return isfinite(value) && value >= minimum && value <= maximum;
}

static bool valid_frequency(float frequency_hz,
                            const speaker_eq_limits_t *limits,
                            uint32_t sample_rate_hz)
{
    return finite_in_range(frequency_hz,
                           limits->minimum_frequency_hz,
                           limits->maximum_frequency_hz) &&
           frequency_hz < ((float)sample_rate_hz / 2.0f);
}

static bool stable_biquad(const q2_30 coeffs[5])
{
    const double a1 = -(double)coeffs[3] / Q30_SCALE;
    const double a2 = -(double)coeffs[4] / Q30_SCALE;

    /* Jury stability criteria for z^2 + a1*z + a2. */
    return (1.0 + a1 + a2) > 0.0 &&
           (1.0 - a1 + a2) > 0.0 &&
           (1.0 - a2) > 0.0;
}

static speaker_eq_status_t design_pass_filter_unchecked(
    q2_30 coeffs[SPEAKER_EQ_PASS_SECTION_COUNT * 5],
    left_shift_t shifts[SPEAKER_EQ_PASS_SECTION_COUNT],
    speaker_eq_pass_kind_t kind,
    speaker_eq_pass_mode_t mode,
    float frequency_hz,
    uint32_t sample_rate_hz)
{
    static const float butterworth_24_q[] = {0.54119610f, 1.30656297f};
    float q[SPEAKER_EQ_PASS_SECTION_COUNT] = {0.0f, 0.0f};
    size_t section_count = 0;

    switch (mode) {
    case SPEAKER_EQ_PASS_BYPASS:
        break;
    case SPEAKER_EQ_PASS_BUTTERWORTH_12:
        q[0] = 0.70710678f;
        section_count = 1;
        break;
    case SPEAKER_EQ_PASS_BUTTERWORTH_24:
        q[0] = butterworth_24_q[0];
        q[1] = butterworth_24_q[1];
        section_count = 2;
        break;
    case SPEAKER_EQ_PASS_LINKWITZ_RILEY_12:
        q[0] = 0.5f;
        section_count = 1;
        break;
    case SPEAKER_EQ_PASS_LINKWITZ_RILEY_24:
        q[0] = 0.70710678f;
        q[1] = 0.70710678f;
        section_count = 2;
        break;
    default:
        return SPEAKER_EQ_STATUS_INVALID_PASS_MODE;
    }

    for (size_t i = 0; i < SPEAKER_EQ_PASS_SECTION_COUNT; ++i) {
        q2_30 *section = &coeffs[i * 5];
        if (i >= section_count) {
            shifts[i] = adsp_design_biquad_bypass(section);
        } else if (kind == SPEAKER_EQ_PASS_HIGH) {
            shifts[i] = adsp_design_biquad_highpass(
                section, frequency_hz, (float)sample_rate_hz, q[i]);
        } else {
            shifts[i] = adsp_design_biquad_lowpass(
                section, frequency_hz, (float)sample_rate_hz, q[i]);
        }

        if (!stable_biquad(section)) {
            return SPEAKER_EQ_STATUS_UNSTABLE_FILTER;
        }
    }

    return SPEAKER_EQ_STATUS_OK;
}

speaker_eq_status_t speaker_eq_design_pass_filter(
    q2_30 coeffs[SPEAKER_EQ_PASS_SECTION_COUNT * 5],
    left_shift_t shifts[SPEAKER_EQ_PASS_SECTION_COUNT],
    speaker_eq_pass_kind_t kind,
    speaker_eq_pass_mode_t mode,
    float frequency_hz,
    uint32_t sample_rate_hz)
{
    if (coeffs == NULL || shifts == NULL) {
        return SPEAKER_EQ_STATUS_INVALID_ARGUMENT;
    }
    if (sample_rate_hz == 0) {
        return SPEAKER_EQ_STATUS_INVALID_SAMPLE_RATE;
    }
    if (kind != SPEAKER_EQ_PASS_HIGH && kind != SPEAKER_EQ_PASS_LOW) {
        return SPEAKER_EQ_STATUS_INVALID_ARGUMENT;
    }
    if (mode < SPEAKER_EQ_PASS_BYPASS ||
        mode > SPEAKER_EQ_PASS_LINKWITZ_RILEY_24) {
        return SPEAKER_EQ_STATUS_INVALID_PASS_MODE;
    }
    if (mode != SPEAKER_EQ_PASS_BYPASS &&
        (!isfinite(frequency_hz) || frequency_hz <= 0.0f ||
         frequency_hz >= ((float)sample_rate_hz / 2.0f))) {
        return SPEAKER_EQ_STATUS_OUT_OF_RANGE;
    }

    return design_pass_filter_unchecked(
        coeffs, shifts, kind, mode, frequency_hz, sample_rate_hz);
}

speaker_eq_status_t speaker_eq_design_program(
    speaker_eq_program_t *program,
    const speaker_eq_config_t *config,
    const speaker_eq_limits_t *limits,
    uint32_t sample_rate_hz)
{
    if (program == NULL || config == NULL || limits == NULL) {
        return SPEAKER_EQ_STATUS_INVALID_ARGUMENT;
    }
    if (sample_rate_hz == 0) {
        return SPEAKER_EQ_STATUS_INVALID_SAMPLE_RATE;
    }
    if (config->channel_mode != SPEAKER_EQ_MODE_STEREO_LINKED &&
        config->channel_mode != SPEAKER_EQ_MODE_MONO) {
        return SPEAKER_EQ_STATUS_INVALID_CHANNEL_MODE;
    }
    if (config->hpf_mode < SPEAKER_EQ_PASS_BYPASS ||
        config->hpf_mode > SPEAKER_EQ_PASS_LINKWITZ_RILEY_24) {
        return SPEAKER_EQ_STATUS_INVALID_PASS_MODE;
    }

    const float limit_values[] = {
        limits->minimum_frequency_hz, limits->maximum_frequency_hz,
        limits->minimum_q, limits->maximum_q,
        limits->minimum_peak_gain_db, limits->maximum_peak_gain_db,
        limits->minimum_shelf_gain_db, limits->maximum_shelf_gain_db,
        limits->minimum_pregain_db, limits->maximum_pregain_db,
        limits->minimum_clip_level_dbfs, limits->headroom_margin_db,
    };
    for (size_t i = 0; i < sizeof(limit_values) / sizeof(limit_values[0]); ++i) {
        if (!isfinite(limit_values[i])) {
            return SPEAKER_EQ_STATUS_OUT_OF_RANGE;
        }
    }
    if (limits->minimum_frequency_hz <= 0.0f ||
        limits->minimum_frequency_hz > limits->maximum_frequency_hz ||
        limits->minimum_q < SPEAKER_EQ_HARD_MINIMUM_Q ||
        limits->maximum_q > SPEAKER_EQ_HARD_MAXIMUM_Q ||
        limits->minimum_q > limits->maximum_q ||
        limits->minimum_peak_gain_db > limits->maximum_peak_gain_db ||
        limits->minimum_shelf_gain_db > limits->maximum_shelf_gain_db ||
        limits->minimum_pregain_db > limits->maximum_pregain_db ||
        limits->maximum_pregain_db > 0.0f ||
        limits->minimum_clip_level_dbfs > 0.0f ||
        limits->headroom_margin_db < 0.0f ||
        limits->minimum_peak_gain_db < -SPEAKER_EQ_HARD_PEAK_GAIN_DB ||
        limits->maximum_peak_gain_db > SPEAKER_EQ_HARD_PEAK_GAIN_DB ||
        limits->minimum_shelf_gain_db < -SPEAKER_EQ_HARD_SHELF_GAIN_DB ||
        limits->maximum_shelf_gain_db > SPEAKER_EQ_HARD_SHELF_GAIN_DB) {
        return SPEAKER_EQ_STATUS_OUT_OF_RANGE;
    }
    if (!finite_in_range(config->pregain_db,
                         limits->minimum_pregain_db,
                         limits->maximum_pregain_db) ||
        !finite_in_range(config->clip_level_dbfs,
                         limits->minimum_clip_level_dbfs,
                         0.0f)) {
        return SPEAKER_EQ_STATUS_OUT_OF_RANGE;
    }
    if (config->hpf_mode != SPEAKER_EQ_PASS_BYPASS &&
        !valid_frequency(config->hpf_frequency_hz, limits, sample_rate_hz)) {
        return SPEAKER_EQ_STATUS_OUT_OF_RANGE;
    }

    float positive_boost_db = 0.0f;
    for (size_t i = 0; i < SPEAKER_EQ_PEAK_COUNT; ++i) {
        const speaker_eq_parametric_t *peak = &config->peak[i];
        if (!peak->enabled) {
            continue;
        }
        if (!valid_frequency(peak->frequency_hz, limits, sample_rate_hz) ||
            !finite_in_range(peak->q, limits->minimum_q, limits->maximum_q) ||
            !finite_in_range(peak->gain_db,
                             limits->minimum_peak_gain_db,
                             limits->maximum_peak_gain_db)) {
            return SPEAKER_EQ_STATUS_OUT_OF_RANGE;
        }
        if (peak->gain_db > 0.0f) {
            positive_boost_db += peak->gain_db;
        }
    }

    if (config->high_shelf.enabled) {
        const speaker_eq_high_shelf_t *shelf = &config->high_shelf;
        if (!valid_frequency(shelf->frequency_hz, limits, sample_rate_hz) ||
            !finite_in_range(shelf->q, limits->minimum_q, limits->maximum_q) ||
            !finite_in_range(shelf->gain_db,
                             limits->minimum_shelf_gain_db,
                             limits->maximum_shelf_gain_db)) {
            return SPEAKER_EQ_STATUS_OUT_OF_RANGE;
        }
        if (shelf->gain_db > 0.0f) {
            positive_boost_db += shelf->gain_db;
        }
    }

    const float recommended_pregain_db =
        -(positive_boost_db + limits->headroom_margin_db);
    if (!config->bypass && limits->enforce_headroom &&
        config->pregain_db > recommended_pregain_db + 0.0001f) {
        return SPEAKER_EQ_STATUS_INSUFFICIENT_HEADROOM;
    }

    speaker_eq_program_t designed;
    memset(&designed, 0, sizeof(designed));
    designed.channel_mode = config->channel_mode;
    designed.bypass = config->bypass;
    designed.pregain_q27 = adsp_dB_to_gain(config->pregain_db);
    designed.recommended_pregain_db = recommended_pregain_db;

    if (config->clip_level_dbfs == 0.0f) {
        designed.clip_threshold = INT32_MAX;
    } else {
        const double linear = pow(10.0, (double)config->clip_level_dbfs / 20.0);
        designed.clip_threshold = (int32_t)llround(linear * INT32_MAX);
    }

    speaker_eq_status_t status = design_pass_filter_unchecked(
        &designed.coeffs[0], &designed.shifts[0], SPEAKER_EQ_PASS_HIGH,
        config->hpf_mode, config->hpf_frequency_hz, sample_rate_hz);
    if (status != SPEAKER_EQ_STATUS_OK) {
        return status;
    }

    for (size_t i = 0; i < SPEAKER_EQ_PEAK_COUNT; ++i) {
        const size_t section_index = i + SPEAKER_EQ_PASS_SECTION_COUNT;
        q2_30 *coeffs = &designed.coeffs[section_index * 5];
        if (config->peak[i].enabled) {
            designed.shifts[section_index] = adsp_design_biquad_peaking(
                coeffs,
                config->peak[i].frequency_hz,
                (float)sample_rate_hz,
                config->peak[i].q,
                config->peak[i].gain_db);
        } else {
            designed.shifts[section_index] = adsp_design_biquad_bypass(coeffs);
        }
        if (!stable_biquad(coeffs)) {
            return SPEAKER_EQ_STATUS_UNSTABLE_FILTER;
        }
    }

    const size_t shelf_index = SPEAKER_EQ_SECTION_COUNT - 1;
    q2_30 *shelf_coeffs = &designed.coeffs[shelf_index * 5];
    if (config->high_shelf.enabled) {
        designed.shifts[shelf_index] = adsp_design_biquad_highshelf(
            shelf_coeffs,
            config->high_shelf.frequency_hz,
            (float)sample_rate_hz,
            config->high_shelf.q,
            config->high_shelf.gain_db);
    } else {
        designed.shifts[shelf_index] = adsp_design_biquad_bypass(shelf_coeffs);
    }
    if (!stable_biquad(shelf_coeffs)) {
        return SPEAKER_EQ_STATUS_UNSTABLE_FILTER;
    }

    memcpy(program, &designed, sizeof(*program));
    return SPEAKER_EQ_STATUS_OK;
}
