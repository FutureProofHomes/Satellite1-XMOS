#include "sat1_voice_policy.h"
#include <limits.h>
#include <string.h>

static int32_t clamp_sample(int64_t sample)
{
    if (sample > INT32_MAX) return INT32_MAX;
    if (sample < INT32_MIN) return INT32_MIN;
    return (int32_t)sample;
}

static uint16_t correlation_score(int64_t cross, uint64_t mic_energy,
                                  uint64_t reference_energy)
{
    uint64_t magnitude = cross < 0 ? (uint64_t)-cross : (uint64_t)cross;
    /* Normalize before squaring. The Q15 numerator then fits uint64 even
     * for full-scale input, and score is independent of reference gain. */
    while (mic_energy > 65535U || reference_energy > 65535U) {
        mic_energy >>= 1;
        reference_energy >>= 1;
        magnitude >>= 1;
    }
    uint32_t denominator = (uint32_t)(mic_energy * reference_energy);
    if (denominator == 0) return 0;
    uint64_t numerator = magnitude * magnitude * SAT1_VOICE_Q15_ONE;
    if (numerator >= (uint64_t)denominator * SAT1_VOICE_Q15_ONE) return SAT1_VOICE_Q15_ONE;
#if defined(__XS3A__)
    /* Quotient <32768 and the high word is below divisor: ldivu cannot
     * overflow. Avoid a general 64/64 software divide for every lag. */
    uint32_t quotient, remainder;
    __asm__("ldivu %0, %1, %2, %3, %4"
        : "=&r"(quotient), "=&r"(remainder)
        : "r"((uint32_t)(numerator >> 32)), "r"((uint32_t)numerator), "r"(denominator));
    return (uint16_t)quotient;
#else
    return (uint16_t)(numerator / denominator);
#endif
}

void sat1_voice_policy_reset(sat1_voice_policy_t *state)
{
    memset(state, 0, sizeof(*state));
}

uint8_t sat1_voice_policy_analyze(sat1_voice_policy_t *state,
    const int32_t microphone[240], const int32_t reference[240],
    uint16_t speech_q15, bool reference_active)
{
    const unsigned window = SAT1_VOICE_CORRELATION_WINDOW;
    const unsigned advance = SAT1_VOICE_DECIMATED_FRAME;
    const unsigned ref_count = window + SAT1_VOICE_REFERENCE_LAGS;
    memmove(state->microphone, state->microphone + advance,
            (window - advance) * sizeof(int32_t));
    memmove(state->reference, state->reference + advance,
            (ref_count - advance) * sizeof(int32_t));
    for (unsigned i = 0; i < advance; ++i) {
        int64_t mic_sum = 0, ref_sum = 0;
        for (unsigned j = 0; j < 4; ++j) {
            mic_sum += microphone[4 * i + j];
            ref_sum += reference[4 * i + j];
        }
        state->microphone[window - advance + i] = (int32_t)(mic_sum / 4) / 4096;
        state->reference[ref_count - advance + i] = (int32_t)(ref_sum / 4) / 4096;
    }
    if (state->history_count < ref_count) {
        state->history_count += advance;
        if (state->history_count > ref_count) state->history_count = ref_count;
    }
    state->echo_q15 = 0;
    state->echo_lag_samples = 0;
    if (reference_active && state->history_count >= window) {
        uint64_t mic_energy = 0;
        int64_t mic_sum = 0;
        for (unsigned i = 0; i < window; ++i) {
            int64_t value = state->microphone[i];
            mic_energy += (uint64_t)(value * value);
            mic_sum += value;
        }
        /* Mean-centred correlation prevents unrelated DC offsets from being
         * mistaken for speaker echo. Scaled full-range inputs fit int64. */
        mic_energy = window * mic_energy - (uint64_t)(mic_sum * mic_sum);
        unsigned lags = state->history_count - window;
        if (lags > SAT1_VOICE_REFERENCE_LAGS) lags = SAT1_VOICE_REFERENCE_LAGS;
        uint64_t ref_energy = 0;
        int64_t ref_sum = 0;
        for (unsigned i = 0; i < window; ++i) {
            int64_t value = state->reference[ref_count - window + i];
            ref_energy += (uint64_t)(value * value);
            ref_sum += value;
        }
        for (unsigned lag = 0; lag <= lags; ++lag) {
            int64_t cross = 0;
            unsigned start = ref_count - window - lag;
            if (lag != 0) {
                int64_t entering = state->reference[start];
                int64_t leaving = state->reference[start + window];
                ref_energy += (uint64_t)(entering * entering);
                ref_energy -= (uint64_t)(leaving * leaving);
                ref_sum += entering - leaving;
            }
            for (unsigned i = 0; i < window; ++i) {
                int64_t m = state->microphone[i];
                int64_t r = state->reference[start + i];
                cross += m * r;
            }
            uint64_t centred_ref_energy = window * ref_energy - (uint64_t)(ref_sum * ref_sum);
            cross = window * cross - mic_sum * ref_sum;
            uint16_t score = correlation_score(cross, mic_energy, centred_ref_energy);
            if (score > state->echo_q15) {
                state->echo_q15 = score;
                state->echo_lag_samples = (uint16_t)(4 * lag);
            }
        }
    }

    bool echo_only = reference_active && state->echo_q15 >= 22938U; /* r^2 >= .70 */
    if (state->history_count >= window && speech_q15 >= 16384U && !echo_only)
        state->speech_hold = 6;
    else if (state->speech_hold > 0) --state->speech_hold;
    uint8_t flags = state->speech_hold > 0 ? SAT1_VOICE_NEAR_SPEECH : 0;
    if (echo_only) flags |= SAT1_VOICE_ECHO_ONLY;
    return flags;
}

void sat1_voice_protected_cleanup(const int32_t delayed_primary[240],
    const int32_t cancelled[240], int32_t output[240], uint8_t flags,
    uint16_t *residual_gain_q15)
{
    uint32_t weight = SAT1_VOICE_Q15_ONE;
    if (flags & SAT1_VOICE_UNSETTLED) {
        weight = 0;
    } else if (flags & SAT1_VOICE_NEAR_SPEECH) {
        uint64_t primary_energy = 0, estimate_energy = 0;
        for (unsigned i = 0; i < 240; ++i) {
            int64_t primary = delayed_primary[i] / 256;
            int64_t estimate = ((int64_t)delayed_primary[i] - cancelled[i]) / 256;
            primary_energy += (uint64_t)(primary * primary);
            estimate_energy += (uint64_t)(estimate * estimate);
        }
        while (weight > 0 && estimate_energy > primary_energy / 16U) {
            weight >>= 1;
            estimate_energy = (estimate_energy + 3) / 4U;
        }
    }
    uint32_t before = *residual_gain_q15;
    uint32_t target = (flags & SAT1_VOICE_ECHO_ONLY) &&
                      !(flags & SAT1_VOICE_NEAR_SPEECH) ? 16384U : SAT1_VOICE_Q15_ONE;
    uint32_t after = target >= before ? target : before - (before - target + 7) / 8U;
    for (unsigned i = 0; i < 240; ++i) {
        int64_t estimate = (int64_t)delayed_primary[i] - cancelled[i];
        int64_t clean = delayed_primary[i] - estimate * weight / SAT1_VOICE_Q15_ONE;
        int64_t gain = before + ((int64_t)after - before) * (i + 1) / 240;
        output[i] = clamp_sample(clean * gain / SAT1_VOICE_Q15_ONE);
    }
    *residual_gain_q15 = (uint16_t)after;
}
