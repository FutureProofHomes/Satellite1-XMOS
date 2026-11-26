#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "../satellite-xmos-firmware/src/doa/doa_estimator.h"

#define FRAME_SAMPLES 240
#define TEST_FRAMES 4
#define CALIBRATION_FRAMES 10
#define SOURCE_SAMPLES 2048

static int32_t source_audio[SOURCE_SAMPLES];

static void build_source_audio(void)
{
    uint32_t state = 0x6d2b79f5U;
    for (size_t i = 0; i < SOURCE_SAMPLES; i++) {
        state ^= state << 13;
        state ^= state >> 17;
        state ^= state << 5;
        int32_t sample = (int32_t)(state & 0xffffU) - 32768;
        source_audio[i] = sample * 4096;
    }
}

static int32_t scaled_source_sample(size_t index,
                                    int delay,
                                    int gain_percent,
                                    int amplitude_divisor)
{
    int source_index = (int)index - delay;
    if (source_index < 0 || source_index >= SOURCE_SAMPLES) {
        return 0;
    }
    return (int32_t)(((int64_t)source_audio[source_index] * gain_percent) /
                     (100 * amplitude_divisor));
}

static void feed_room_noise(size_t frame_count)
{
    int32_t frames[4][FRAME_SAMPLES];

    for (size_t frame = 0; frame < frame_count; frame++) {
        size_t source_offset = 32 + (frame * FRAME_SAMPLES);
        for (size_t mic = 0; mic < 4; mic++) {
            size_t mic_offset = (mic * 347) % SOURCE_SAMPLES;
            for (size_t sample = 0; sample < FRAME_SAMPLES; sample++) {
                size_t index =
                    (source_offset + mic_offset + sample) % SOURCE_SAMPLES;
                frames[mic][sample] = source_audio[index] / 512;
            }
        }
        doa_estimator_process_frame_4(
            frames[0], frames[1], frames[2], frames[3], FRAME_SAMPLES);
    }
}

static void feed_direction(const int delays[4],
                           size_t frame_count,
                           int amplitude_divisor)
{
    static const int gains[4] = {100, 115, 90, 130};
    int32_t frames[4][FRAME_SAMPLES];

    for (size_t frame = 0; frame < frame_count; frame++) {
        size_t source_offset = 32 + (frame * FRAME_SAMPLES);
        for (size_t mic = 0; mic < 4; mic++) {
            for (size_t sample = 0; sample < FRAME_SAMPLES; sample++) {
                frames[mic][sample] = scaled_source_sample(
                    source_offset + sample,
                    delays[mic],
                    gains[mic],
                    amplitude_divisor);
            }
        }
        doa_estimator_process_frame_4(
            frames[0], frames[1], frames[2], frames[3], FRAME_SAMPLES);
    }
}

static doa_estimator_state_t run_direction_case_at_level(const int delays[4],
                                                         int amplitude_divisor)
{
    doa_estimator_reset();
    feed_room_noise(CALIBRATION_FRAMES);
    feed_direction(delays, TEST_FRAMES, amplitude_divisor);

    doa_estimator_state_t state = {0};
    doa_estimator_get_state(&state);
    return state;
}

static doa_estimator_state_t run_direction_case(const int delays[4])
{
    return run_direction_case_at_level(delays, 1);
}

static int ring_distance(int left, int right)
{
    int distance = abs(left - right);
    return distance > 12 ? 24 - distance : distance;
}

static void expect_direction(const char *name,
                             const int delays[4],
                             int expected_angle,
                             int expected_x_sign,
                             int expected_y_sign)
{
    doa_estimator_state_t state = run_direction_case(delays);
    if (!(state.flags & DOA_ESTIMATOR_FLAG_FOUR_MIC) ||
        !(state.flags & DOA_ESTIMATOR_FLAG_VALID) ||
        ring_distance(state.angle_index, expected_angle) > 1 ||
        (expected_x_sign > 0 && state.sample_delay <= 0) ||
        (expected_x_sign < 0 && state.sample_delay >= 0) ||
        (expected_x_sign > 0 && state.sample_delay_q8 <= 0) ||
        (expected_x_sign < 0 && state.sample_delay_q8 >= 0) ||
        (expected_y_sign > 0 && state.vertical_delay <= 0) ||
        (expected_y_sign < 0 && state.vertical_delay >= 0) ||
        (expected_y_sign > 0 && state.vertical_delay_q8 <= 0) ||
        (expected_y_sign < 0 && state.vertical_delay_q8 >= 0) ||
        state.confidence < 64) {
        fprintf(
            stderr,
            "%s failed: flags=%u angle=%u x=%d y=%d confidence=%u\n",
            name,
            state.flags,
            state.angle_index,
            state.sample_delay,
            state.vertical_delay,
            state.confidence);
        exit(1);
    }
}

static void expect_playback_aware_locking(const int east[4],
                                          const int west[4],
                                          const int south[4])
{
    doa_estimator_state_t state = run_direction_case(east);
    if (!(state.flags & DOA_ESTIMATOR_FLAG_VALID)) {
        fprintf(stderr, "control test could not acquire initial direction\n");
        exit(1);
    }

    doa_estimator_set_control(DOA_ESTIMATOR_CONTROL_VOICE_LOCK);
    feed_direction(west, TEST_FRAMES, 1);
    doa_estimator_get_state(&state);
    if (!(state.flags & DOA_ESTIMATOR_FLAG_LOCKED) ||
        ring_distance(state.angle_index, 18) > 1) {
        fprintf(stderr,
                "voice lock moved: flags=%u angle=%u\n",
                state.flags,
                state.angle_index);
        exit(1);
    }

    doa_estimator_set_control(DOA_ESTIMATOR_CONTROL_PLAYBACK_ACTIVE);
    feed_direction(south, TEST_FRAMES, 1);
    doa_estimator_get_state(&state);
    if (!(state.flags & DOA_ESTIMATOR_FLAG_PLAYBACK) ||
        ring_distance(state.angle_index, 18) > 1) {
        fprintf(stderr,
                "playback freeze moved: flags=%u angle=%u\n",
                state.flags,
                state.angle_index);
        exit(1);
    }

    doa_estimator_diagnostics_t diagnostics = {0};
    doa_estimator_get_diagnostics(&diagnostics);
    if (!(diagnostics.mode_flags &
          DOA_ESTIMATOR_MODE_PLAYBACK_FROZEN) ||
        diagnostics.control_flags !=
            DOA_ESTIMATOR_CONTROL_PLAYBACK_ACTIVE) {
        fprintf(stderr,
                "playback diagnostics failed: mode=%u control=%u\n",
                diagnostics.mode_flags,
                diagnostics.control_flags);
        exit(1);
    }

    doa_estimator_set_control(0);
    feed_direction(west, TEST_FRAMES, 1);
    doa_estimator_get_state(&state);
    if (!(state.flags & DOA_ESTIMATOR_FLAG_VALID) ||
        ring_distance(state.angle_index, 6) > 1) {
        fprintf(stderr,
                "unlock did not resume scanning: flags=%u angle=%u\n",
                state.flags,
                state.angle_index);
        exit(1);
    }

    doa_estimator_set_control(DOA_ESTIMATOR_CONTROL_FORCE_OMNI);
    feed_direction(east, 1, 1);
    doa_estimator_get_state(&state);
    if ((state.flags & DOA_ESTIMATOR_FLAG_VALID) ||
        state.angle_index != 12) {
        fprintf(stderr,
                "force omni failed: flags=%u angle=%u\n",
                state.flags,
                state.angle_index);
        exit(1);
    }
}

int main(void)
{
    build_source_audio();

    const int east[4] = {0, 3, 1, 1};
    const int west[4] = {3, 0, 1, 1};
    const int north[4] = {1, 1, 0, 3};
    const int south[4] = {1, 1, 3, 0};
    const int northeast[4] = {0, 2, 0, 2};
    const int centered[4] = {0, 0, 0, 0};

    expect_direction("east", east, 18, 1, 0);
    expect_direction("west", west, 6, -1, 0);
    expect_direction("north", north, 12, 0, 1);
    expect_direction("south", south, 0, 0, -1);
    expect_direction("northeast", northeast, 15, 1, 1);

    doa_estimator_state_t quiet_state =
        run_direction_case_at_level(east, 256);
    if (!(quiet_state.flags & DOA_ESTIMATOR_FLAG_VALID) ||
        ring_distance(quiet_state.angle_index, 18) > 1) {
        fprintf(
            stderr,
            "quiet speech failed: flags=%u angle=%u confidence=%u energy=%u\n",
            quiet_state.flags,
            quiet_state.angle_index,
            quiet_state.confidence,
            quiet_state.energy);
        return 1;
    }

    doa_estimator_state_t centered_state = run_direction_case(centered);
    if (!(centered_state.flags & DOA_ESTIMATOR_FLAG_FOUR_MIC) ||
        (centered_state.flags & DOA_ESTIMATOR_FLAG_VALID)) {
        fprintf(
            stderr,
            "centered failed: flags=%u angle=%u x=%d y=%d confidence=%u\n",
            centered_state.flags,
            centered_state.angle_index,
            centered_state.sample_delay,
            centered_state.vertical_delay,
            centered_state.confidence);
        return 1;
    }

    /*
     * Correlated residual audio is deliberately directional and energetic
     * enough to fool the old fixed threshold. Once calibrated as room noise,
     * it must never produce a valid direction after speech ends.
     */
    doa_estimator_reset();
    feed_room_noise(CALIBRATION_FRAMES);
    feed_direction(east, TEST_FRAMES, 1);
    doa_estimator_state_t transition_state = {0};
    doa_estimator_get_state(&transition_state);
    if (!(transition_state.flags & DOA_ESTIMATOR_FLAG_VALID)) {
        fprintf(stderr, "speech-to-silence setup did not acquire east\n");
        return 1;
    }

    const int *noise_directions[4] = {west, north, south, northeast};
    for (size_t frame = 0; frame < 12; frame++) {
        feed_direction(noise_directions[frame % 4], 1, 512);
        doa_estimator_get_state(&transition_state);
        if (transition_state.flags & DOA_ESTIMATOR_FLAG_VALID) {
            fprintf(
                stderr,
                "silence gate failed at frame %zu: angle=%u confidence=%u energy=%u\n",
                frame,
                transition_state.angle_index,
                transition_state.confidence,
                transition_state.energy);
            return 1;
        }
    }

    feed_direction(west, TEST_FRAMES, 1);
    doa_estimator_get_state(&transition_state);
    if (!(transition_state.flags & DOA_ESTIMATOR_FLAG_VALID) ||
        ring_distance(transition_state.angle_index, 6) > 1) {
        fprintf(
            stderr,
            "direction reacquisition failed: flags=%u angle=%u confidence=%u\n",
            transition_state.flags,
            transition_state.angle_index,
            transition_state.confidence);
        return 1;
    }

    expect_playback_aware_locking(east, west, south);

    puts("DoA estimator host tests passed.");
    return 0;
}
