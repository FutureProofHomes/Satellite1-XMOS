#ifndef appconfSAT1_SPEECH_FRONTEND
#define appconfSAT1_SPEECH_FRONTEND 0
#endif
#if appconfSAT1_SPEECH_FRONTEND && THIS_XCORE_TILE == 0
#include "sat1_voice_frontend.h"
#include "vnr.h"
#include "ic.h"
#include <limits.h>
#include <string.h>
#include <xcore/assert.h>

/* Stage 1 exclusively owns the inference engine and direction/beam state.
 * Stage 2 owns IC state and consumes per-frame evidence, never inference. */
static vnr_state_t speech_vnr;
static sat1_voice_policy_t policy;
static sat1_beamformer_t beam;
static ic_state_t ic;
static uint16_t residual_gain;
static unsigned unsettled_frames;
static int16_t previous_delays[4];
static int32_t bypass_overlap[32];

static uint16_t probability_q15(float_s32_t probability)
{
    if (probability.mant <= 0) return 0;
    int shift = probability.exp + 15;
    if (shift >= 15) return 32768;
    if (shift <= -32) return 0;
    uint64_t value = shift >= 0 ? (uint64_t)probability.mant << shift
                                : (uint32_t)probability.mant >> -shift;
    return value > 32768 ? 32768 : (uint16_t)value;
}

void sat1_voice_frontend_init(void)
{
    sat1_voice_policy_reset(&policy);
    sat1_beamformer_reset(&beam);
    doa_estimator_reset();
    xassert(ic_init(&ic) == 0); /* Also initializes this tile's VNR engine. */
    vnr_input_state_init(&speech_vnr.input_state);
    vnr_feature_state_init(&speech_vnr.feature_state);
    memset(bypass_overlap, 0, sizeof(bypass_overlap));
    memset(previous_delays, 0, sizeof(previous_delays));
    unsettled_frames = 6;
    residual_gain = SAT1_VOICE_Q15_ONE;
}

void sat1_voice_frontend_analyze(int32_t samples[4][240],
    const int32_t reference[240], float_s32_t aec_correlation,
    int reference_active, sat1_voice_frame_t *metadata)
{
    int32_t DWORD_ALIGNED omni[240], target[240], noise_reference[240];
    const int32_t *microphones[4] = {samples[0], samples[1], samples[2], samples[3]};
    sat1_beamformer_set_calibration(&beam, &metadata->calibration);
    for (unsigned i = 0; i < 240; ++i) {
        int64_t sum = 0;
        unsigned count = 0;
        for (unsigned mic = 0; mic < 4; ++mic) {
            if (beam.active_mic_mask & (1U << mic)) {
                sum += samples[mic][i];
                ++count;
            }
        }
        omni[i] = count ? (int32_t)(sum / count) : 0;
    }
    float_s32_t speech_probability;
    vnr_process_frame(&speech_vnr, &speech_probability, omni);
    metadata->speech_q15 = probability_q15(speech_probability);
    metadata->flags = sat1_voice_policy_analyze(&policy, omni, reference,
                                               metadata->speech_q15, reference_active != 0);
    metadata->echo_q15 = policy.echo_q15;
    doa_estimator_diagnostics_t control;
    doa_estimator_get_diagnostics(&control);
    bool voice_session = (control.control_flags & DOA_ESTIMATOR_CONTROL_VOICE_ACTIVE) != 0;
    bool echo_dominated = (metadata->flags & SAT1_VOICE_ECHO_ONLY) != 0 ||
        (reference_active && !voice_session &&
         float_s32_gt(aec_correlation, f32_to_float_s32(0.97f)));
    doa_estimator_set_mic_health(beam.active_mic_mask);
    doa_estimator_set_tracking_evidence(
        (metadata->flags & SAT1_VOICE_NEAR_SPEECH) != 0, echo_dominated);
    doa_estimator_process_frame_4(samples[0], samples[1], samples[2], samples[3], 240);
    doa_estimator_state_t direction;
    doa_estimator_get_state(&direction);
    if (direction.flags & DOA_ESTIMATOR_FLAG_VALID)
        metadata->flags |= SAT1_VOICE_DIRECTION_VALID;
    sat1_beamformer_process_calibrated_frame_with_reference(
        &beam, target, noise_reference, microphones, 240, &direction);
    unsigned movement = 0;
    for (unsigned mic = 0; mic < 4; ++mic) {
        int difference = beam.current_delay_q8[mic] - previous_delays[mic];
        movement += difference < 0 ? -difference : difference;
        previous_delays[mic] = beam.current_delay_q8[mic];
    }
    if (movement > 64) unsettled_frames = 6;
    if (unsettled_frames) {
        metadata->flags |= SAT1_VOICE_UNSETTLED;
        --unsettled_frames;
    }
    memcpy(samples[0], target, sizeof(target));
    memcpy(samples[1], noise_reference, sizeof(noise_reference));
}

void sat1_voice_frontend_cleanup(int32_t samples[4][240],
    const sat1_voice_frame_t *metadata)
{
    int32_t DWORD_ALIGNED cancelled[240], delayed_primary[240];
    ic_filter(&ic, samples[0], samples[1], cancelled);
    /* IC delays its primary by 600 samples; WOLA contributes another 32.
     * Match both delays before blending, including on every bypass frame. */
    memcpy(delayed_primary, bypass_overlap, sizeof(bypass_overlap));
    memcpy(delayed_primary + 32, samples[0], 208 * sizeof(int32_t));
    memcpy(bypass_overlap, samples[0] + 208, sizeof(bypass_overlap));
    ic.vnr_pred_state.input_vnr_pred =
        (float_s32_t){metadata->speech_q15, -15};
    ic.ic_adaption_controller_state.adaption_controller_config.enable_adaption =
        metadata->speech_q15 < 6554U &&
        !(metadata->flags & (SAT1_VOICE_NEAR_SPEECH | SAT1_VOICE_UNSETTLED));
    ic_adapt(&ic);
    sat1_voice_protected_cleanup(delayed_primary, cancelled, samples[0],
                                 metadata->flags, &residual_gain);
}
#endif
