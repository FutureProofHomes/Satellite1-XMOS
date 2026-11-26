#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "beamforming/sat1_beamformer.h"

#define FRAME_SAMPLES (240)
#define TEST_FRAMES (3)
#define TOTAL_SAMPLES (FRAME_SAMPLES * TEST_FRAMES)
#define SOURCE_PADDING (16)

static int32_t source_audio[TOTAL_SAMPLES + SOURCE_PADDING];
static int32_t microphone_audio[SAT1_BEAMFORMER_MIC_COUNT][TOTAL_SAMPLES];

static void build_directional_audio(void)
{
    static const int arrival_delay[SAT1_BEAMFORMER_MIC_COUNT] = {0, 4, 2, 2};
    uint32_t random_state = 0x8a5cd789U;

    for (size_t i = 0; i < TOTAL_SAMPLES + SOURCE_PADDING; i++) {
        random_state ^= random_state << 13;
        random_state ^= random_state >> 17;
        random_state ^= random_state << 5;
        source_audio[i] = ((int32_t)(random_state & 0xffffU) - 32768) * 1024;
    }

    for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
        for (size_t sample = 0; sample < TOTAL_SAMPLES; sample++) {
            int source_index = (int)sample - arrival_delay[mic];
            microphone_audio[mic][sample] =
                source_index >= 0 ? source_audio[source_index] : 0;
        }
    }
}

static void expect_directional_gain(void)
{
    sat1_beamformer_t beamformer;
    sat1_beamformer_reset(&beamformer);

    doa_estimator_state_t east = {
        .sample_delay = 4,
        .sample_delay_q8 = 4 * DOA_ESTIMATOR_LAG_Q8_SCALE,
        .flags = DOA_ESTIMATOR_FLAG_VALID | DOA_ESTIMATOR_FLAG_FOUR_MIC,
    };
    uint64_t beam_error = 0;
    uint64_t omni_error = 0;

    for (size_t frame = 0; frame < TEST_FRAMES; frame++) {
        const int32_t *microphones[SAT1_BEAMFORMER_MIC_COUNT];
        int32_t output[FRAME_SAMPLES];
        for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
            microphones[mic] = &microphone_audio[mic][frame * FRAME_SAMPLES];
        }

        sat1_beamformer_process_frame(&beamformer,
                                      output,
                                      microphones,
                                      FRAME_SAMPLES,
                                      &east);

        if (frame == 0) {
            continue;
        }
        for (size_t sample = 0; sample < FRAME_SAMPLES; sample++) {
            size_t global_sample = (frame * FRAME_SAMPLES) + sample;
            int32_t expected = source_audio[global_sample - 4];
            int64_t beam_delta = (int64_t)output[sample] - expected;
            int64_t omni = 0;
            for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
                omni += microphone_audio[mic][global_sample];
            }
            omni /= SAT1_BEAMFORMER_MIC_COUNT;
            int64_t omni_delta = omni - expected;
            beam_error += (uint64_t)(beam_delta * beam_delta);
            omni_error += (uint64_t)(omni_delta * omni_delta);
        }
    }

    if (beam_error != 0 || omni_error == 0) {
        fprintf(stderr,
                "directional alignment failed: beam_error=%llu omni_error=%llu\n",
                (unsigned long long)beam_error,
                (unsigned long long)omni_error);
        exit(1);
    }
}

static void expect_fractional_steering(void)
{
    static const int arrival_q8[SAT1_BEAMFORMER_MIC_COUNT] = {
        0,
        DOA_ESTIMATOR_LAG_Q8_SCALE,
        DOA_ESTIMATOR_LAG_Q8_SCALE / 2,
        DOA_ESTIMATOR_LAG_Q8_SCALE / 2,
    };
    int32_t fractional_mics[SAT1_BEAMFORMER_MIC_COUNT][TOTAL_SAMPLES];
    for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
        for (size_t sample = 0; sample < TOTAL_SAMPLES; sample++) {
            fractional_mics[mic][sample] =
                ((int32_t)sample * DOA_ESTIMATOR_LAG_Q8_SCALE) -
                arrival_q8[mic];
        }
    }

    sat1_beamformer_t beamformer;
    sat1_beamformer_reset(&beamformer);
    doa_estimator_state_t direction = {
        .sample_delay = 1,
        .sample_delay_q8 = DOA_ESTIMATOR_LAG_Q8_SCALE,
        .flags = DOA_ESTIMATOR_FLAG_VALID | DOA_ESTIMATOR_FLAG_FOUR_MIC,
    };

    for (size_t frame = 0; frame < TEST_FRAMES; frame++) {
        const int32_t *microphones[SAT1_BEAMFORMER_MIC_COUNT];
        int32_t output[FRAME_SAMPLES];
        for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
            microphones[mic] = &fractional_mics[mic][frame * FRAME_SAMPLES];
        }

        sat1_beamformer_process_frame(&beamformer,
                                      output,
                                      microphones,
                                      FRAME_SAMPLES,
                                      &direction);
        if (frame == 0) {
            continue;
        }

        for (size_t sample = 0; sample < FRAME_SAMPLES; sample++) {
            size_t global_sample = (frame * FRAME_SAMPLES) + sample;
            int32_t expected =
                ((int32_t)global_sample * DOA_ESTIMATOR_LAG_Q8_SCALE) -
                ((5 * DOA_ESTIMATOR_LAG_Q8_SCALE) / 2);
            if (output[sample] != expected) {
                fprintf(stderr,
                        "fractional steering failed at %zu: got=%d expected=%d\n",
                        global_sample,
                        output[sample],
                        expected);
                exit(1);
            }
        }
    }
}

static void expect_direction_hold_and_release(void)
{
    sat1_beamformer_t beamformer;
    sat1_beamformer_reset(&beamformer);

    doa_estimator_state_t east = {
        .sample_delay_q8 = 4 * DOA_ESTIMATOR_LAG_Q8_SCALE,
        .flags = DOA_ESTIMATOR_FLAG_VALID | DOA_ESTIMATOR_FLAG_FOUR_MIC,
    };
    doa_estimator_state_t invalid = {
        .flags = DOA_ESTIMATOR_FLAG_FOUR_MIC,
    };
    const int32_t *microphones[SAT1_BEAMFORMER_MIC_COUNT];
    int32_t output[FRAME_SAMPLES];
    for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
        microphones[mic] = microphone_audio[mic];
    }

    sat1_beamformer_process_frame(&beamformer,
                                  output,
                                  microphones,
                                  FRAME_SAMPLES,
                                  &east);
    if (beamformer.current_delay_q8[0] !=
            4 * DOA_ESTIMATOR_LAG_Q8_SCALE ||
        beamformer.current_delay_q8[1] != 0) {
        fprintf(stderr, "beamformer did not acquire east steering\n");
        exit(1);
    }

    for (size_t frame = 0; frame < 5; frame++) {
        sat1_beamformer_process_frame(&beamformer,
                                      output,
                                      microphones,
                                      FRAME_SAMPLES,
                                      &invalid);
        if (beamformer.current_delay_q8[0] !=
                4 * DOA_ESTIMATOR_LAG_Q8_SCALE ||
            beamformer.current_delay_q8[1] != 0) {
            fprintf(stderr, "beamformer released direction too early\n");
            exit(1);
        }
    }

    sat1_beamformer_process_frame(&beamformer,
                                  output,
                                  microphones,
                                  FRAME_SAMPLES,
                                  &invalid);
    for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
        if (beamformer.current_delay_q8[mic] !=
            2 * DOA_ESTIMATOR_LAG_Q8_SCALE) {
            fprintf(stderr, "beamformer did not return to omni steering\n");
            exit(1);
        }
    }
}

static void expect_cubic_fractional_interpolation(void)
{
    int32_t quadratic_mics[SAT1_BEAMFORMER_MIC_COUNT][TOTAL_SAMPLES];
    for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
        for (size_t sample = 0; sample < TOTAL_SAMPLES; sample++) {
            quadratic_mics[mic][sample] =
                4 * (int32_t)sample * (int32_t)sample;
        }
    }

    sat1_beamformer_t beamformer;
    sat1_beamformer_reset(&beamformer);
    doa_estimator_state_t direction = {
        .sample_delay_q8 = DOA_ESTIMATOR_LAG_Q8_SCALE,
        .flags = DOA_ESTIMATOR_FLAG_VALID | DOA_ESTIMATOR_FLAG_FOUR_MIC,
    };

    for (size_t frame = 0; frame < TEST_FRAMES; frame++) {
        const int32_t *microphones[SAT1_BEAMFORMER_MIC_COUNT];
        int32_t output[FRAME_SAMPLES];
        for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
            microphones[mic] =
                &quadratic_mics[mic][frame * FRAME_SAMPLES];
        }
        sat1_beamformer_process_frame(&beamformer,
                                      output,
                                      microphones,
                                      FRAME_SAMPLES,
                                      &direction);
        if (frame == 0) {
            continue;
        }

        for (size_t sample = 0; sample < FRAME_SAMPLES; sample++) {
            int32_t n = (int32_t)((frame * FRAME_SAMPLES) + sample);
            int32_t east = (2 * n - 5) * (2 * n - 5);
            int32_t west = (2 * n - 3) * (2 * n - 3);
            int32_t north_south = 4 * (n - 2) * (n - 2);
            int32_t expected =
                (east + west + (2 * north_south)) / 4;
            if (output[sample] != expected) {
                fprintf(stderr,
                        "cubic interpolation failed at %d: got=%d expected=%d\n",
                        n,
                        output[sample],
                        expected);
                exit(1);
            }
        }
    }
}

static void expect_failed_mic_fallback(void)
{
    int32_t silent[FRAME_SAMPLES] = {0};
    const int32_t *microphones[SAT1_BEAMFORMER_MIC_COUNT] = {
        silent,
        microphone_audio[1],
        microphone_audio[2],
        microphone_audio[3],
    };
    doa_estimator_state_t invalid = {
        .flags = DOA_ESTIMATOR_FLAG_FOUR_MIC,
    };
    sat1_beamformer_t beamformer;
    sat1_beamformer_reset(&beamformer);
    int32_t output[FRAME_SAMPLES];

    for (size_t frame = 0; frame < 24; frame++) {
        sat1_beamformer_process_frame(&beamformer,
                                      output,
                                      microphones,
                                      FRAME_SAMPLES,
                                      &invalid);
    }
    if ((beamformer.active_mic_mask & 0x01u) != 0 ||
        !(beamformer.mic_health_flags[0] & SAT1_MIC_HEALTH_DEAD)) {
        fprintf(stderr,
                "dead mic was not removed: mask=0x%02x health=0x%02x\n",
                beamformer.active_mic_mask,
                beamformer.mic_health_flags[0]);
        exit(1);
    }

    microphones[0] = microphone_audio[0];
    for (size_t frame = 0; frame < 160; frame++) {
        sat1_beamformer_process_frame(&beamformer,
                                      output,
                                      microphones,
                                      FRAME_SAMPLES,
                                      &invalid);
    }
    if ((beamformer.active_mic_mask & 0x01u) == 0 ||
        beamformer.mic_health_flags[0] != 0) {
        fprintf(stderr,
                "recovered mic was not restored: mask=0x%02x health=0x%02x\n",
                beamformer.active_mic_mask,
                beamformer.mic_health_flags[0]);
        exit(1);
    }
}

static void expect_cleaned_audio_does_not_change_calibration(void)
{
    sat1_beamformer_t beamformer = {0};
    const int32_t *raw[4] = {microphone_audio[0], microphone_audio[1],
                              microphone_audio[2], microphone_audio[3]};
    int32_t cleaned[4][FRAME_SAMPLES] = {{0}};
    const int32_t *cleaned_mics[4] = {cleaned[0], cleaned[1], cleaned[2], cleaned[3]};
    int32_t output[FRAME_SAMPLES];
    for (size_t frame = 0; frame < 80; ++frame)
        sat1_beamformer_analyze_frame(&beamformer, raw, FRAME_SAMPLES);
    sat1_beamformer_t calibrated = beamformer;
    for (size_t frame = 0; frame < 80; ++frame)
        sat1_beamformer_process_calibrated_frame(&beamformer, output, cleaned_mics,
                                                 FRAME_SAMPLES, NULL);
    if (beamformer.calibration_frames != calibrated.calibration_frames ||
        memcmp(beamformer.mic_level_ema, calibrated.mic_level_ema,
               sizeof(beamformer.mic_level_ema)) != 0 ||
        memcmp(beamformer.mic_gain_q15, calibrated.mic_gain_q15,
               sizeof(beamformer.mic_gain_q15)) != 0 ||
        beamformer.active_mic_mask != calibrated.active_mic_mask) {
        fprintf(stderr, "Echo-cancelled silence changed raw microphone calibration\n");
        exit(1);
    }
}

int main(void)
{
    build_directional_audio();
    expect_directional_gain();
    expect_fractional_steering();
    expect_cubic_fractional_interpolation();
    expect_direction_hold_and_release();
    expect_failed_mic_fallback();
    expect_cleaned_audio_does_not_change_calibration();
    puts("Sat1 beamformer host tests passed.");
    return 0;
}
