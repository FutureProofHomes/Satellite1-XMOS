#include <assert.h>
#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "speaker_eq.h"
#include "speaker_eq_preset.h"

#define SAMPLE_RATE_HZ 48000u
#define PI 3.14159265358979323846

static double pass_magnitude_db(const q2_30 coeffs[10],
                                const left_shift_t shifts[2],
                                double frequency_hz)
{
    const double omega = 2.0 * PI * frequency_hz / SAMPLE_RATE_HZ;
    const double c1 = cos(omega);
    const double s1 = -sin(omega);
    const double c2 = cos(2.0 * omega);
    const double s2 = -sin(2.0 * omega);
    double magnitude = 1.0;

    for (size_t section = 0; section < 2; ++section) {
        const q2_30 *c = &coeffs[section * 5];
        const double scale = ldexp(1.0, shifts[section]) / 1073741824.0;
        const double numerator_real =
            scale * (c[0] + c[1] * c1 + c[2] * c2);
        const double numerator_imag = scale * (c[1] * s1 + c[2] * s2);
        const double denominator_real =
            1.0 - ((double)c[3] * c1 + (double)c[4] * c2) / 1073741824.0;
        const double denominator_imag =
            -((double)c[3] * s1 + (double)c[4] * s2) / 1073741824.0;
        magnitude *= hypot(numerator_real, numerator_imag) /
                     hypot(denominator_real, denominator_imag);
    }
    return 20.0 * log10(magnitude);
}

static speaker_eq_limits_t test_limits(void)
{
    speaker_eq_limits_t limits = {
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
    return limits;
}

static void test_pass_filters(void)
{
    q2_30 coeffs[10];
    left_shift_t shifts[2];
    static const struct {
        speaker_eq_pass_mode_t mode;
        double expected_db;
    } cases[] = {
        {SPEAKER_EQ_PASS_BUTTERWORTH_12, -3.0103},
        {SPEAKER_EQ_PASS_BUTTERWORTH_24, -3.0103},
        {SPEAKER_EQ_PASS_LINKWITZ_RILEY_12, -6.0206},
        {SPEAKER_EQ_PASS_LINKWITZ_RILEY_24, -6.0206},
    };

    for (size_t kind = SPEAKER_EQ_PASS_HIGH;
         kind <= SPEAKER_EQ_PASS_LOW;
         ++kind) {
        for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
            assert(speaker_eq_design_pass_filter(
                       coeffs, shifts, (speaker_eq_pass_kind_t)kind,
                       cases[i].mode, 1000.0f, SAMPLE_RATE_HZ) ==
                   SPEAKER_EQ_STATUS_OK);
            assert(fabs(pass_magnitude_db(coeffs, shifts, 1000.0) -
                        cases[i].expected_db) < 0.1);
        }
    }
}

static void test_runtime_state(void)
{
    speaker_eq_config_t config = {
        .channel_mode = SPEAKER_EQ_MODE_MONO,
        .pregain_db = -3.0f,
        .clip_level_dbfs = 0.0f,
        .hpf_mode = SPEAKER_EQ_PASS_BUTTERWORTH_12,
        .hpf_frequency_hz = 100.0f,
    };
    speaker_eq_limits_t limits = test_limits();
    limits.headroom_margin_db = 3.0f;
    speaker_eq_program_t program;
    assert(speaker_eq_design_program(
               &program, &config, &limits, SAMPLE_RATE_HZ) ==
           SPEAKER_EQ_STATUS_OK);

    int32_t original_left[] = {
        1 << 24, 0, 0, 0, 0, 0, 0, 0,
    };
    int32_t original_right[] = {
        1 << 24, 0, 0, 0, 0, 0, 0, 0,
    };
    int32_t whole_left[8];
    int32_t whole_right[8];
    int32_t split_left[8];
    int32_t split_right[8];
    memcpy(whole_left, original_left, sizeof(whole_left));
    memcpy(whole_right, original_right, sizeof(whole_right));
    memcpy(split_left, original_left, sizeof(split_left));
    memcpy(split_right, original_right, sizeof(split_right));

    speaker_eq_t whole_eq;
    speaker_eq_t split_eq;
    assert(speaker_eq_init(&whole_eq, &program) == SPEAKER_EQ_STATUS_OK);
    assert(speaker_eq_init(&split_eq, &program) == SPEAKER_EQ_STATUS_OK);

    int32_t *whole_channels[] = {whole_left, whole_right};
    speaker_eq_process_frame(&whole_eq, whole_channels, 8);

    int32_t *split_channels_0[] = {split_left, split_right};
    speaker_eq_process_frame(&split_eq, split_channels_0, 3);
    int32_t *split_channels_1[] = {&split_left[3], &split_right[3]};
    speaker_eq_process_frame(&split_eq, split_channels_1, 5);

    assert(memcmp(whole_left, whole_right, sizeof(whole_left)) == 0);
    assert(memcmp(whole_left, split_left, sizeof(whole_left)) == 0);
    assert(memcmp(whole_right, split_right, sizeof(whole_right)) == 0);

    int32_t cleared_state[SPEAKER_EQ_STATE_WORDS] = {0};
    assert(memcmp(whole_eq.state[1], cleared_state, sizeof(cleared_state)) == 0);
    assert(memcmp(whole_eq.state[0], cleared_state, sizeof(cleared_state)) != 0);

    assert(speaker_eq_apply_program(&whole_eq, &program) ==
           SPEAKER_EQ_STATUS_OK);
    assert(memcmp(whole_eq.state[0], cleared_state, sizeof(cleared_state)) == 0);
}

static void test_stereo_bypass(void)
{
    speaker_eq_program_t program;
    memset(&program, 0, sizeof(program));
    program.channel_mode = SPEAKER_EQ_MODE_STEREO_LINKED;
    program.bypass = true;

    speaker_eq_t eq;
    assert(speaker_eq_init(&eq, &program) == SPEAKER_EQ_STATUS_OK);
    int32_t left[] = {INT32_MIN, -3, 0, 7, INT32_MAX};
    int32_t right[] = {INT32_MAX, 9, 0, -5, INT32_MIN};
    int32_t expected_left[5];
    int32_t expected_right[5];
    memcpy(expected_left, left, sizeof(left));
    memcpy(expected_right, right, sizeof(right));

    int32_t *channels[] = {left, right};
    speaker_eq_process_frame(&eq, channels, 5);
    assert(memcmp(left, expected_left, sizeof(left)) == 0);
    assert(memcmp(right, expected_right, sizeof(right)) == 0);
}

static void test_mono_bypass(void)
{
    speaker_eq_program_t program;
    memset(&program, 0, sizeof(program));
    program.channel_mode = SPEAKER_EQ_MODE_MONO;
    program.bypass = true;

    speaker_eq_t eq;
    assert(speaker_eq_init(&eq, &program) == SPEAKER_EQ_STATUS_OK);

    int32_t left[] = {INT32_MAX, INT32_MIN, INT32_MAX, 5};
    int32_t right[] = {INT32_MAX, INT32_MIN, INT32_MIN, 0};
    int32_t *channels[] = {left, right};
    speaker_eq_process_frame(&eq, channels, 4);

    assert(left[0] == INT32_MAX && right[0] == INT32_MAX);
    assert(left[1] == INT32_MIN && right[1] == INT32_MIN);
    assert(left[2] == 0 && right[2] == 0);
    assert(left[3] == 2 && right[3] == 2);
}

static void test_confirmed_program(void)
{
    speaker_eq_program_t program;

    assert(speaker_eq_design_program(
               &program,
               &speaker_eq_preset_config,
               &speaker_eq_preset_limits,
               SAMPLE_RATE_HZ) ==
           SPEAKER_EQ_STATUS_OK);
    assert(fabsf(program.recommended_pregain_db + 8.0f) < 0.001f);
    assert(program.clip_threshold == INT32_MAX);

    speaker_eq_config_t config = speaker_eq_preset_config;
    config.pregain_db = 0.0f;
    assert(speaker_eq_design_program(
               &program, &config, &speaker_eq_preset_limits, SAMPLE_RATE_HZ) ==
           SPEAKER_EQ_STATUS_INSUFFICIENT_HEADROOM);

    speaker_eq_limits_t invalid_limits = speaker_eq_preset_limits;
    invalid_limits.minimum_q = 0.001f;
    assert(speaker_eq_design_program(
               &program,
               &speaker_eq_preset_config,
               &invalid_limits,
               SAMPLE_RATE_HZ) == SPEAKER_EQ_STATUS_OUT_OF_RANGE);
}

int main(void)
{
    test_pass_filters();
    test_mono_bypass();
    test_runtime_state();
    test_stereo_bypass();
    test_confirmed_program();
    puts("speaker_eq tests passed");
    return 0;
}
