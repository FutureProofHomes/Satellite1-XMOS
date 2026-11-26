#include "sat1_beamformer.h"

#include <limits.h>
#include <string.h>

#define SAT1_BEAMFORMER_CENTER_DELAY_Q8 \
    ((DOA_ESTIMATOR_MAX_LAG_SAMPLES * DOA_ESTIMATOR_LAG_Q8_SCALE) / 2)
#define SAT1_BEAMFORMER_MAX_DELAY_Q8 \
    (DOA_ESTIMATOR_MAX_LAG_SAMPLES * DOA_ESTIMATOR_LAG_Q8_SCALE)
#define SAT1_BEAMFORMER_DIRECTION_HOLD_FRAMES (6)
#define SAT1_BEAMFORMER_GAIN_Q15_SCALE (32768U)
#define SAT1_BEAMFORMER_GAIN_MIN_Q15   (23170U)
#define SAT1_BEAMFORMER_GAIN_MAX_Q15   (46341U)
#define SAT1_BEAMFORMER_LEVEL_EMA_SHIFT (4)
#define SAT1_BEAMFORMER_GAIN_EMA_SHIFT  (6)
#define SAT1_BEAMFORMER_HEALTH_MIN_LEVEL (4096U)
#define SAT1_BEAMFORMER_FAULT_FRAMES     (16U)
#define SAT1_BEAMFORMER_RECOVERY_FRAMES  (64U)
#define SAT1_BEAMFORMER_CALIBRATION_WARMUP_FRAMES (32U)
#define SAT1_BEAMFORMER_DEAD_RATIO       (32U)
#define SAT1_BEAMFORMER_NOISY_RATIO      (16U)

static volatile sat1_beamformer_diagnostics_t latest_diagnostics;

static int32_t saturate_i32(int64_t value)
{
    if (value > INT32_MAX) {
        return INT32_MAX;
    }
    if (value < INT32_MIN) {
        return INT32_MIN;
    }
    return (int32_t)value;
}

/* Positive divisor; preserve C's truncation toward zero before saturation. */
static int32_t divide_saturate_i32(int64_t numerator, uint32_t divisor)
{
    if (numerator > (int64_t)INT32_MAX * divisor) {
        return INT32_MAX;
    }
    if (numerator < (int64_t)INT32_MIN * divisor) {
        return INT32_MIN;
    }
#if defined(__XS3A__)
    /*
     * The bounded quotient fits ldivu's 32-bit result. These clamps also
     * exclude INT64_MIN and guarantee that the high word is below divisor.
     * Avoid the general signed 64-bit software divide in every fractional sample.
     */
    uint64_t magnitude = numerator < 0 ? (uint64_t)(-numerator)
                                       : (uint64_t)numerator;
    uint32_t quotient, remainder;
    __asm__("ldivu %0, %1, %2, %3, %4"
            : "=&r"(quotient), "=&r"(remainder)
            : "r"((uint32_t)(magnitude >> 32)), "r"((uint32_t)magnitude),
              "r"(divisor));
    return numerator < 0 ? (int32_t)(-(int64_t)quotient) : (int32_t)quotient;
#else
    return (int32_t)(numerator / divisor);
#endif
}

static int16_t clamp_delay_q8(int32_t delay_q8)
{
    if (delay_q8 < 0) {
        return 0;
    }
    if (delay_q8 > SAT1_BEAMFORMER_MAX_DELAY_Q8) {
        return SAT1_BEAMFORMER_MAX_DELAY_Q8;
    }
    return (int16_t)delay_q8;
}

static int32_t sample_at(const int32_t *input,
                         const int32_t history[SAT1_BEAMFORMER_HISTORY_SAMPLES],
                         int index)
{
    if (index >= 0) {
        return input[index];
    }

    int history_index = SAT1_BEAMFORMER_HISTORY_SAMPLES + index;
    if (history_index < 0) {
        return 0;
    }
    return history[history_index];
}

static int32_t fractional_delay_sample(
    const int32_t *input,
    const int32_t history[SAT1_BEAMFORMER_HISTORY_SAMPLES],
    size_t sample_index,
    int delay_q8)
{
    int whole_samples = delay_q8 / DOA_ESTIMATOR_LAG_Q8_SCALE;
    int fraction_q8 = delay_q8 % DOA_ESTIMATOR_LAG_Q8_SCALE;
    int newest_index = (int)sample_index - whole_samples;
    int32_t sample0 = sample_at(input, history, newest_index);

    if (fraction_q8 == 0) {
        return sample0;
    }

    int32_t sample1 = sample_at(input, history, newest_index - 1);
    int32_t sample2 = sample_at(input, history, newest_index - 2);
    int32_t sample3 = sample_at(input, history, newest_index - 3);
    int32_t scale = DOA_ESTIMATOR_LAG_Q8_SCALE;
    int32_t fraction = fraction_q8;

    /*
     * Four-point causal Lagrange interpolation. Keeping the polynomial in
     * one rational expression avoids quantizing each tap independently and
     * preserves both DC and linear ramps exactly at Q8 delay positions.
     */
    /* Q8 coefficients fit int32; accumulate sample products in int64. */
    int32_t coefficient0 =
        (scale - fraction) * (2 * scale - fraction) * (3 * scale - fraction);
    int32_t coefficient1 =
        3 * fraction * (2 * scale - fraction) * (3 * scale - fraction);
    int32_t coefficient2 =
        -3 * fraction * (scale - fraction) * (3 * scale - fraction);
    int32_t coefficient3 =
        fraction * (scale - fraction) * (2 * scale - fraction);
    int64_t numerator = (int64_t)sample0 * coefficient0 +
                        (int64_t)sample1 * coefficient1 +
                        (int64_t)sample2 * coefficient2 +
                        (int64_t)sample3 * coefficient3;
    const uint32_t denominator = 6U * scale * scale * scale;
    if (numerator >= 0) {
        numerator += denominator / 2;
    } else {
        numerator -= denominator / 2;
    }
    return divide_saturate_i32(numerator, denominator);
}

static uint32_t frame_mean_abs(const int32_t *samples,
                               size_t frame_count,
                               size_t *clipped_samples)
{
    uint64_t sum = 0;
    size_t clipped = 0;
    for (size_t i = 0; i < frame_count; i++) {
        uint32_t magnitude = samples[i] < 0
                                 ? (uint32_t)(-(int64_t)samples[i])
                                 : (uint32_t)samples[i];
        sum += magnitude;
        if (magnitude >= 0x7f000000U) {
            clipped++;
        }
    }
    if (clipped_samples != NULL) {
        *clipped_samples = clipped;
    }
    return (uint32_t)(sum / frame_count);
}

static uint32_t middle_level_reference(
    const uint32_t levels[SAT1_BEAMFORMER_MIC_COUNT])
{
    uint32_t sorted[SAT1_BEAMFORMER_MIC_COUNT];
    memcpy(sorted, levels, sizeof(sorted));
    for (size_t i = 1; i < SAT1_BEAMFORMER_MIC_COUNT; i++) {
        uint32_t value = sorted[i];
        size_t position = i;
        while (position > 0 && sorted[position - 1] > value) {
            sorted[position] = sorted[position - 1];
            position--;
        }
        sorted[position] = value;
    }
    return (uint32_t)(((uint64_t)sorted[1] + sorted[2]) / 2U);
}

static void update_mic_calibration(
    sat1_beamformer_t *beamformer,
    const int32_t *microphones[SAT1_BEAMFORMER_MIC_COUNT],
    size_t frame_count)
{
    uint32_t frame_level[SAT1_BEAMFORMER_MIC_COUNT];
    size_t clipped[SAT1_BEAMFORMER_MIC_COUNT];
    for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
        frame_level[mic] = frame_mean_abs(
            microphones[mic], frame_count, &clipped[mic]);
        if (beamformer->mic_level_ema[mic] == 0) {
            beamformer->mic_level_ema[mic] = frame_level[mic];
        } else if (frame_level[mic] >= beamformer->mic_level_ema[mic]) {
            beamformer->mic_level_ema[mic] +=
                (frame_level[mic] - beamformer->mic_level_ema[mic]) >>
                SAT1_BEAMFORMER_LEVEL_EMA_SHIFT;
        } else {
            beamformer->mic_level_ema[mic] -=
                (beamformer->mic_level_ema[mic] - frame_level[mic]) >>
                SAT1_BEAMFORMER_LEVEL_EMA_SHIFT;
        }
    }

    uint32_t reference = middle_level_reference(beamformer->mic_level_ema);
    for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
        uint32_t level = beamformer->mic_level_ema[mic];
        uint8_t current_fault = 0;
        if (reference >= SAT1_BEAMFORMER_HEALTH_MIN_LEVEL) {
            if ((uint64_t)level * SAT1_BEAMFORMER_DEAD_RATIO < reference) {
                current_fault |= SAT1_MIC_HEALTH_DEAD;
            }
            if ((uint64_t)level >
                (uint64_t)reference * SAT1_BEAMFORMER_NOISY_RATIO) {
                current_fault |= SAT1_MIC_HEALTH_NOISY;
            }
        }
        if (clipped[mic] > (frame_count / 32U)) {
            current_fault |= SAT1_MIC_HEALTH_CLIPPING;
        }

        if (current_fault != 0) {
            beamformer->mic_recovery_streak[mic] = 0;
            if (beamformer->mic_fault_streak[mic] < UINT8_MAX) {
                beamformer->mic_fault_streak[mic]++;
            }
            if (beamformer->mic_fault_streak[mic] >=
                SAT1_BEAMFORMER_FAULT_FRAMES) {
                beamformer->mic_health_flags[mic] = current_fault;
            }
        } else {
            beamformer->mic_fault_streak[mic] = 0;
            if (beamformer->mic_recovery_streak[mic] < UINT8_MAX) {
                beamformer->mic_recovery_streak[mic]++;
            }
            if (beamformer->mic_recovery_streak[mic] >=
                SAT1_BEAMFORMER_RECOVERY_FRAMES) {
                beamformer->mic_health_flags[mic] = 0;
            }
        }

        if (beamformer->calibration_frames >=
                SAT1_BEAMFORMER_CALIBRATION_WARMUP_FRAMES &&
            reference >= SAT1_BEAMFORMER_HEALTH_MIN_LEVEL &&
            level > 0 && current_fault == 0 &&
            beamformer->mic_health_flags[mic] == 0) {
            uint64_t target =
                ((uint64_t)reference * SAT1_BEAMFORMER_GAIN_Q15_SCALE) /
                level;
            if (target < SAT1_BEAMFORMER_GAIN_MIN_Q15) {
                target = SAT1_BEAMFORMER_GAIN_MIN_Q15;
            } else if (target > SAT1_BEAMFORMER_GAIN_MAX_Q15) {
                target = SAT1_BEAMFORMER_GAIN_MAX_Q15;
            }
            int32_t delta = (int32_t)target -
                            beamformer->mic_gain_q15[mic];
            beamformer->mic_gain_q15[mic] = (uint16_t)(
                beamformer->mic_gain_q15[mic] +
                (delta >> SAT1_BEAMFORMER_GAIN_EMA_SHIFT));
        }
    }

    uint8_t active_mask = 0;
    for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
        if (beamformer->mic_health_flags[mic] == 0) {
            active_mask |= (uint8_t)(1u << mic);
        }
    }
    beamformer->active_mic_mask = active_mask != 0 ? active_mask : 0x0f;
    if (beamformer->calibration_frames < UINT16_MAX) {
        beamformer->calibration_frames++;
    }
}

static void publish_diagnostics(const sat1_beamformer_t *beamformer)
{
    for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
        latest_diagnostics.current_delay_q8[mic] =
            beamformer->current_delay_q8[mic];
        latest_diagnostics.mic_level[mic] =
            beamformer->mic_level_ema[mic];
        latest_diagnostics.mic_gain_q15[mic] =
            beamformer->mic_gain_q15[mic];
        latest_diagnostics.mic_health_flags[mic] =
            beamformer->mic_health_flags[mic];
    }
    latest_diagnostics.active_mic_mask = beamformer->active_mic_mask;
}

static void update_history(
    sat1_beamformer_t *beamformer,
    const int32_t *microphones[SAT1_BEAMFORMER_MIC_COUNT],
    size_t frame_count)
{
    for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
        if (frame_count >= SAT1_BEAMFORMER_HISTORY_SAMPLES) {
            memcpy(beamformer->history[mic],
                   &microphones[mic][frame_count -
                                     SAT1_BEAMFORMER_HISTORY_SAMPLES],
                   sizeof(beamformer->history[mic]));
            continue;
        }

        size_t keep = SAT1_BEAMFORMER_HISTORY_SAMPLES - frame_count;
        memmove(beamformer->history[mic],
                &beamformer->history[mic][frame_count],
                keep * sizeof(int32_t));
        memcpy(&beamformer->history[mic][keep],
               microphones[mic],
               frame_count * sizeof(int32_t));
    }
}

static void select_target_delays(
    sat1_beamformer_t *beamformer,
    int16_t target_delay_q8[SAT1_BEAMFORMER_MIC_COUNT],
    const doa_estimator_state_t *direction)
{
    memcpy(target_delay_q8,
           beamformer->current_delay_q8,
           sizeof(beamformer->current_delay_q8));

    uint8_t valid = direction != NULL &&
                    (direction->flags & DOA_ESTIMATOR_FLAG_VALID) != 0 &&
                    (direction->flags & DOA_ESTIMATOR_FLAG_FOUR_MIC) != 0;
    if (valid) {
        int32_t half_ew_q8 = direction->sample_delay_q8 / 2;
        int32_t half_ns_q8 = direction->vertical_delay_q8 / 2;

        target_delay_q8[0] = clamp_delay_q8(
            SAT1_BEAMFORMER_CENTER_DELAY_Q8 + half_ew_q8);
        target_delay_q8[1] = clamp_delay_q8(
            SAT1_BEAMFORMER_CENTER_DELAY_Q8 - half_ew_q8);
        target_delay_q8[2] = clamp_delay_q8(
            SAT1_BEAMFORMER_CENTER_DELAY_Q8 + half_ns_q8);
        target_delay_q8[3] = clamp_delay_q8(
            SAT1_BEAMFORMER_CENTER_DELAY_Q8 - half_ns_q8);
        beamformer->invalid_direction_frames = 0;
        beamformer->has_direction = 1;
        return;
    }

    if (!beamformer->has_direction) {
        return;
    }

    if (beamformer->invalid_direction_frames < UINT8_MAX) {
        beamformer->invalid_direction_frames++;
    }
    if (beamformer->invalid_direction_frames <
        SAT1_BEAMFORMER_DIRECTION_HOLD_FRAMES) {
        return;
    }

    for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
        target_delay_q8[mic] = SAT1_BEAMFORMER_CENTER_DELAY_Q8;
    }
    beamformer->has_direction = 0;
}

void sat1_beamformer_reset(sat1_beamformer_t *beamformer)
{
    if (beamformer == NULL) {
        return;
    }

    memset(beamformer, 0, sizeof(*beamformer));
    for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
        beamformer->current_delay_q8[mic] =
            SAT1_BEAMFORMER_CENTER_DELAY_Q8;
        beamformer->mic_gain_q15[mic] =
            SAT1_BEAMFORMER_GAIN_Q15_SCALE;
    }
    beamformer->active_mic_mask = 0x0f;
    beamformer->initialized = 1;
    publish_diagnostics(beamformer);
}

void sat1_beamformer_analyze_frame(sat1_beamformer_t *beamformer,
                                  const int32_t *microphones[4], size_t frame_count)
{
    if (beamformer == NULL || microphones == NULL || frame_count == 0) return;
    for (size_t mic = 0; mic < 4; ++mic) if (microphones[mic] == NULL) return;
    if (!beamformer->initialized) sat1_beamformer_reset(beamformer);
    update_mic_calibration(beamformer, microphones, frame_count);
    publish_diagnostics(beamformer);
}

void sat1_beamformer_process_frame(sat1_beamformer_t *beamformer,
                                  int32_t *output, const int32_t *microphones[4],
                                  size_t frame_count, const doa_estimator_state_t *direction)
{
    if (output == NULL) {
        return;
    }
    sat1_beamformer_analyze_frame(beamformer, microphones, frame_count);
    sat1_beamformer_process_calibrated_frame(beamformer, output, microphones,
                                            frame_count, direction);
}

void sat1_beamformer_process_calibrated_frame(
    sat1_beamformer_t *beamformer,
    int32_t *output,
    const int32_t *microphones[SAT1_BEAMFORMER_MIC_COUNT],
    size_t frame_count,
    const doa_estimator_state_t *direction)
{
    sat1_beamformer_process_calibrated_frame_with_reference(
        beamformer, output, NULL, microphones, frame_count, direction);
}

void sat1_beamformer_set_calibration(sat1_beamformer_t *beamformer,
    const sat1_beamformer_diagnostics_t *calibration)
{
    if (beamformer == NULL || calibration == NULL) return;
    if (!beamformer->initialized) sat1_beamformer_reset(beamformer);
    memcpy(beamformer->mic_level_ema, calibration->mic_level,
           sizeof(beamformer->mic_level_ema));
    memcpy(beamformer->mic_gain_q15, calibration->mic_gain_q15,
           sizeof(beamformer->mic_gain_q15));
    memcpy(beamformer->mic_health_flags, calibration->mic_health_flags,
           sizeof(beamformer->mic_health_flags));
    beamformer->active_mic_mask = calibration->active_mic_mask & 0x0f;
}

void sat1_beamformer_process_calibrated_frame_with_reference(
    sat1_beamformer_t *beamformer, int32_t *output, int32_t *noise_reference,
    const int32_t *microphones[4], size_t frame_count,
    const doa_estimator_state_t *direction)
{
    if (beamformer == NULL || output == NULL || microphones == NULL ||
        frame_count == 0) {
        return;
    }
    for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
        if (microphones[mic] == NULL) {
            return;
        }
    }

    if (!beamformer->initialized) {
        sat1_beamformer_reset(beamformer);
    }


    int16_t target_delay_q8[SAT1_BEAMFORMER_MIC_COUNT];
    select_target_delays(beamformer, target_delay_q8, direction);

    for (size_t sample = 0; sample < frame_count; sample++) {
        int64_t sum = 0;
        int64_t first = 0;
        uint32_t active_count = 0;
        for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
            if ((beamformer->active_mic_mask & (1u << mic)) == 0) {
                continue;
            }
            int32_t delta = target_delay_q8[mic] -
                            beamformer->current_delay_q8[mic];
            int delay_q8 = beamformer->current_delay_q8[mic] +
                           ((delta * (int32_t)(sample + 1)) /
                            (int32_t)frame_count);
            int32_t delayed = fractional_delay_sample(
                microphones[mic],
                beamformer->history[mic],
                sample,
                delay_q8);
            int64_t calibrated = ((int64_t)delayed * beamformer->mic_gain_q15[mic]) /
                                 SAT1_BEAMFORMER_GAIN_Q15_SCALE;
            if (active_count == 0) first = calibrated;
            sum += calibrated;
            active_count++;
        }
        output[sample] = active_count > 0
                             ? saturate_i32(sum / active_count)
                             : 0;
        if (noise_reference != NULL) {
            noise_reference[sample] = active_count > 1
                ? saturate_i32((first - sum / active_count) / 2) : 0;
        }
    }

    memcpy(beamformer->current_delay_q8,
           target_delay_q8,
           sizeof(beamformer->current_delay_q8));
    update_history(beamformer, microphones, frame_count);
    publish_diagnostics(beamformer);
}

void sat1_beamformer_get_diagnostics(
    sat1_beamformer_diagnostics_t *diagnostics)
{
    if (diagnostics == NULL) {
        return;
    }

    for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
        diagnostics->current_delay_q8[mic] =
            latest_diagnostics.current_delay_q8[mic];
        diagnostics->mic_level[mic] =
            latest_diagnostics.mic_level[mic];
        diagnostics->mic_gain_q15[mic] =
            latest_diagnostics.mic_gain_q15[mic];
        diagnostics->mic_health_flags[mic] =
            latest_diagnostics.mic_health_flags[mic];
    }
    diagnostics->active_mic_mask = latest_diagnostics.active_mic_mask;
}
