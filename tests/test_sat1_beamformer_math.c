#include <assert.h>
#include <stdio.h>

/* Exercise private arithmetic without adding a firmware test API. */
#include "beamforming/sat1_beamformer.c"
#include "beamformer_reference.h"

#if defined(__XS3A__)
#include <xcore/hwtimer.h>
/* Still cover every fraction/mask on target; bound cycle-accurate simulation
 * by keeping the larger deterministic random/transition run on the host. */
#define RANDOM_DIVIDES (128)
#define RANDOM_VECTORS (8)
#define TRANSITION_FRAMES (16)
#else
#define RANDOM_DIVIDES (2048)
#define RANDOM_VECTORS (64)
#define TRANSITION_FRAMES (32)
#endif

void reference_sat1_beamformer_process_calibrated_frame(
    sat1_beamformer_t *, int32_t *, const int32_t *[4], size_t,
    const doa_estimator_state_t *);

static uint32_t random_state = UINT32_C(0x8a5cd789);
static unsigned interpolation_checks, frame_checks, divide_checks;

static int32_t random_sample(void)
{
    random_state ^= random_state << 13;
    random_state ^= random_state >> 17;
    random_state ^= random_state << 5;
    /* Defined conversion over the complete signed range, including INT32_MIN. */
    return (int32_t)(random_state & INT32_MAX) -
           (random_state & UINT32_C(0x80000000) ? INT32_MAX : 0) -
           (random_state & UINT32_C(0x80000000) ? 1 : 0);
}

static void check_divide(int64_t numerator, uint32_t divisor)
{
    assert(divide_saturate_i32(numerator, divisor) ==
           saturate_i32(numerator / divisor));
    ++divide_checks;
}

static void test_division_edges(void)
{
    const uint32_t divisors[] = {1, 3, 32768, 100663296, UINT32_MAX};
    const int32_t quotients[] = {INT32_MIN, INT32_MIN + 1, -32768, -1,
                                0, 1, 32768, INT32_MAX - 1, INT32_MAX};
    for (unsigned d = 0; d < sizeof(divisors) / sizeof(divisors[0]); ++d) {
        uint32_t divisor = divisors[d];
        const int64_t offsets[] = {-(int64_t)divisor + 1, -1, 0, 1,
                                  divisor / 2, divisor - 1};
        check_divide(INT64_MIN, divisor);
        check_divide(INT64_MAX, divisor);
        for (unsigned q = 0; q < sizeof(quotients) / sizeof(quotients[0]); ++q) {
            int64_t base = (int64_t)quotients[q] * divisor;
            for (unsigned o = 0; o < sizeof(offsets) / sizeof(offsets[0]); ++o) {
                /* Avoid overflowing the reference fixture at 64-bit limits. */
                if ((offsets[o] > 0 && base > INT64_MAX - offsets[o]) ||
                    (offsets[o] < 0 && base < INT64_MIN - offsets[o])) continue;
                check_divide(base + offsets[o], divisor);
            }
        }
        for (unsigned i = 0; i < RANDOM_DIVIDES; ++i) {
            int64_t numerator = (int64_t)random_sample() * divisor;
            check_divide(numerator, divisor);
        }
    }
}

static void check_sample(const int32_t *input, const int32_t *history,
                         size_t index, int delay)
{
    int32_t expected = reference_fractional_delay_sample(input, history, index, delay);
    int32_t actual = fractional_delay_sample(input, history, index, delay);
    if (actual != expected) {
        fprintf(stderr, "fraction mismatch: index=%u delay=%d actual=%ld expected=%ld\n",
                (unsigned)index, delay, (long)actual, (long)expected);
        assert(actual == expected);
    }
    ++interpolation_checks;
}

static void test_all_fractions(void)
{
    int32_t input[240], history[SAT1_BEAMFORMER_HISTORY_SAMPLES] = {0};
    const int32_t dc[] = {INT32_MIN, INT32_MIN + 1, -32768, -1,
                          0, 1, 32768, INT32_MAX - 1, INT32_MAX};
    for (int fraction = 0; fraction < DOA_ESTIMATOR_LAG_Q8_SCALE; ++fraction) {
        /* All extreme sign combinations cover positive/negative overshoot. */
        for (unsigned mask = 0; mask < 16; ++mask) {
            for (unsigned i = 0; i < 4; ++i)
                input[i] = mask & (1u << i) ? INT32_MIN : INT32_MAX;
            check_sample(input, history, 3, fraction);
        }
        for (unsigned d = 0; d < sizeof(dc) / sizeof(dc[0]); ++d) {
            for (unsigned i = 0; i < 4; ++i) input[i] = dc[d];
            check_sample(input, history, 3, fraction);
            assert(fractional_delay_sample(input, history, 3, fraction) == dc[d]);
        }
        for (unsigned vector = 0; vector < RANDOM_VECTORS; ++vector) {
            for (unsigned i = 0; i < 4; ++i) input[i] = random_sample();
            check_sample(input, history, 3, fraction);
        }
    }
    /* Every allowed delay at frame start, history crossover and frame end. */
    for (unsigned i = 0; i < 240; ++i) input[i] = random_sample();
    for (unsigned i = 0; i < SAT1_BEAMFORMER_HISTORY_SAMPLES; ++i)
        history[i] = random_sample();
    const unsigned indices[] = {0, 1, 2, 3, 4, 5, 6, 239};
    for (int delay = 0; delay <= SAT1_BEAMFORMER_MAX_DELAY_Q8; ++delay)
        for (unsigned i = 0; i < sizeof(indices) / sizeof(indices[0]); ++i)
            check_sample(input, history, indices[i], delay);

    /* Exact half-way values round away from zero, symmetrically. */
    for (int sign = -1; sign <= 1; sign += 2) {
        input[0] = input[1] = 0;
        input[2] = sign * 8;
        input[3] = 0;
        assert(fractional_delay_sample(input, history, 3, 128) == sign * 8);
        check_sample(input, history, 3, 128);
    }
}

static void test_frames(void)
{
    static int32_t input[4][240], output[240], expected[240];
    const int32_t *mics[4] = {input[0], input[1], input[2], input[3]};
    const unsigned lengths[] = {1, 3, 7, 31, 240};
    for (unsigned mask = 0; mask < 16; ++mask) {
        sat1_beamformer_t actual, reference;
        sat1_beamformer_reset(&actual);
        actual.active_mic_mask = mask;
        for (unsigned mic = 0; mic < 4; ++mic)
            actual.mic_gain_q15[mic] = mic == 0 ? 23170 : mic == 3 ? 46341 : 32768;
        reference = actual;
        for (unsigned frame = 0; frame < TRANSITION_FRAMES; ++frame) {
            unsigned length = lengths[frame % 5];
            for (unsigned mic = 0; mic < 4; ++mic)
                for (unsigned i = 0; i < length; ++i) input[mic][i] = random_sample();
            doa_estimator_state_t direction;
            memset(&direction, 0, sizeof(direction));
            direction.flags = frame % 16 < 8
                ? DOA_ESTIMATOR_FLAG_VALID | DOA_ESTIMATOR_FLAG_FOUR_MIC : 0;
            direction.sample_delay_q8 = (int)(frame * 157 % 2049) - 1024;
            direction.vertical_delay_q8 = 1024 - (int)(frame * 199 % 2049);
            const doa_estimator_state_t *dir = frame % 16 == 15 ? NULL : &direction;
            sat1_beamformer_process_calibrated_frame(&actual, output, mics, length, dir);
            reference_sat1_beamformer_process_calibrated_frame(
                &reference, expected, mics, length, dir);
            assert(memcmp(output, expected, length * sizeof(output[0])) == 0);
            assert(memcmp(&actual, &reference, sizeof(actual)) == 0);
            ++frame_checks;
        }
    }
}

static void test_timing(void)
{
#if defined(__XS3A__)
    static int32_t input[4][240], output[240], expected[240];
    const int32_t *mics[4] = {input[0], input[1], input[2], input[3]};
    for (unsigned mic = 0; mic < 4; ++mic)
        for (unsigned i = 0; i < 240; ++i) input[mic][i] = random_sample();
    unsigned maximum = 0;
    for (unsigned mode = 0; mode < 4; ++mode) {
        sat1_beamformer_t actual, reference;
        sat1_beamformer_reset(&actual);
        doa_estimator_state_t direction;
        memset(&direction, 0, sizeof(direction));
        direction.flags = DOA_ESTIMATOR_FLAG_VALID | DOA_ESTIMATOR_FLAG_FOUR_MIC;
        direction.sample_delay_q8 = mode == 0 ? 0 : mode == 1 ? 256 : 128;
        direction.vertical_delay_q8 = direction.sample_delay_q8;
        sat1_beamformer_process_calibrated_frame(&actual, output, mics, 240, &direction);
        reference = actual;
        if (mode == 3) {
            direction.sample_delay_q8 = -891;
            direction.vertical_delay_q8 = 715;
        }
        unsigned start = get_reference_time();
        sat1_beamformer_process_calibrated_frame(&actual, output, mics, 240, &direction);
        unsigned optimized_ticks = get_reference_time() - start;
        start = get_reference_time();
        reference_sat1_beamformer_process_calibrated_frame(
            &reference, expected, mics, 240, &direction);
        unsigned reference_ticks = get_reference_time() - start;
        assert(memcmp(output, expected, sizeof(output)) == 0);
        /* Single-thread simulator budget; hardware qualification is separate. */
        assert(optimized_ticks < 250000);
        if (mode != 0) assert(optimized_ticks * 2 < reference_ticks);
        if (optimized_ticks > maximum) maximum = optimized_ticks;
        printf("beam timing mode=%u optimized_ticks=%u reference_ticks=%u\n",
               mode, optimized_ticks, reference_ticks);
    }
    printf("maximum simulator beam ticks=%u (budget 250000)\n", maximum);
#endif
}

int main(void)
{
    test_division_edges();
    puts("beam divide edges passed");
    test_all_fractions();
    puts("beam all fractions and history edges passed");
    test_timing();
    test_frames();
    puts("beam frame/state comparison passed");
    printf("beam arithmetic passed: %u divides, %u interpolation cases, %u frames\n",
           divide_checks, interpolation_checks, frame_checks);
    return 0;
}
