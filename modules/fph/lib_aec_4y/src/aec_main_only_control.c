#include <string.h>
#include "aec_main_only_control.h"
#include "aec_priv.h"

/* The fixed-delay wrapper has one AEC owner, as does its X-energy recalc cursor. */
static aec_main_only_control_t control;

void aec_main_only_control_reset(void)
{
    memset(&control, 0, sizeof(control));
}

const aec_main_only_control_t *aec_main_only_control_stats(void)
{
    return &control;
}

void aec_main_only_control_update(aec_filter_state_t *main_state)
{
    aec_shared_filter_state_t *shared = main_state->shared_state;
    const coherence_mu_config_params_t *config = &shared->config_params.coh_mu_conf;
    const float_s32_t zero = {0, 0};
    float_s32_t maximum = zero, reference_energy = zero;
    uint32_t mask = 0;

    for (unsigned x = 0; x < shared->num_x_channels; ++x) {
        float_s32_t energy = shared->sum_X_energy[x];
        reference_energy = float_s32_add(reference_energy, energy);
        if (float_s32_gt(energy, maximum)) maximum = energy;
    }
    float_s32_t relative_floor = float_s32_mul(maximum, config->thresh_minus20dB);
    for (unsigned x = 0; x < shared->num_x_channels; ++x) {
        if (float_s32_gt(shared->sum_X_energy[x], config->x_energy_thresh) &&
            !float_s32_gt(relative_floor, shared->sum_X_energy[x])) mask |= 1u << x;
    }
    uint32_t new_reference = mask & ~control.seen_reference_mask;
    uint32_t restarted = mask != 0 && control.previous_reference_mask == 0;
    uint32_t changed = mask != control.previous_reference_mask;
    control.seen_reference_mask |= mask;
    control.previous_reference_mask = mask;

    for (unsigned y = 0; y < shared->num_y_channels; ++y) {
        coherence_mu_params_t *coherence = &shared->coh_mu_state[y];
        if (changed) control.learned_echo_ratio[y] = zero;
        if (mask == 0) {
            control.frozen_frames[y] = control.divergence_frames[y] = 0;
            control.coherent_frames[y] = 0;
            for (unsigned x = 0; x < shared->num_x_channels; ++x) main_state->mu[y][x] = zero;
            continue;
        }

        float_s32_t input = shared->overall_Y[y];
        float_s32_t ratio = input.mant > 0 ? float_s32_div(input, reference_energy) : zero;
        float_s32_t comparable_input = input;
        comparable_input.exp -= 1; /* Same 512-vs-windowed-error adjustment as shadow comparison. */
        int coherent = !float_s32_gt(config->coh_thresh_abs, coherence->coh);
        int near_end = control.learned_echo_ratio[y].mant > 0 &&
            float_s32_gt(ratio, float_s32_mul(control.learned_echo_ratio[y], f64_to_float_s32(4.0)));
        int useful_estimate = coherent && float_s32_gt(coherence->coh, f64_to_float_s32(0.8)) &&
            float_s32_gt(float_s32_mul(comparable_input, f64_to_float_s32(0.25)), main_state->overall_Error[y]);
        if (useful_estimate) {
            if (control.learned_echo_ratio[y].mant == 0) control.learned_echo_ratio[y] = ratio;
            else control.learned_echo_ratio[y] = float_s32_ema(control.learned_echo_ratio[y], ratio, 1052266988u); /* 0.98 */
        }
        if (useful_estimate) control.coherent_frames[y]++;
        else control.coherent_frames[y] = 0;
        if (control.coherent_frames[y] >= 5) control.bootstrap_remaining[y] = 0;
        if (new_reference || (restarted && !coherent)) {
            control.bootstrap_remaining[y] = control.bootstrap_events[y] == 0 ?
                AEC_MAIN_ONLY_BOOTSTRAP_FRAMES : AEC_MAIN_ONLY_RECOVERY_FRAMES;
            control.bootstrap_events[y]++;
        }
        int ineffective = !coherent || float_s32_gt(main_state->overall_Error[y],
            float_s32_mul(comparable_input, f64_to_float_s32(0.8)));
        if (ineffective) control.frozen_frames[y]++;
        else control.frozen_frames[y] = 0;
        if (!near_end && control.frozen_frames[y] >= AEC_MAIN_ONLY_RECOVERY_DELAY_FRAMES &&
            control.bootstrap_remaining[y] == 0) {
            control.bootstrap_remaining[y] = AEC_MAIN_ONLY_RECOVERY_FRAMES;
            control.bootstrap_events[y]++;
            control.frozen_frames[y] = 0;
        }
        /* Absolute coherence also stays high for a polarity-inverted model.
         * Persistent amplification is therefore an independent reset trigger. */
        if (float_s32_gt(main_state->overall_Error[y],
                float_s32_mul(comparable_input, f64_to_float_s32(1.5)))) control.divergence_frames[y]++;
        else control.divergence_frames[y] = 0;
        int reset_now = control.divergence_frames[y] >= AEC_MAIN_ONLY_DIVERGENCE_FRAMES;
        if (reset_now) {
            aec_priv_reset_filter(main_state->H_hat[y], shared->num_x_channels, main_state->num_phases);
            control.reset_events[y]++;
            control.divergence_frames[y] = control.frozen_frames[y] = 0;
            control.coherent_frames[y] = 0;
            control.bootstrap_remaining[y] = AEC_MAIN_ONLY_BOOTSTRAP_FRAMES;
            control.learned_echo_ratio[y] = zero;
            coherence->coh = coherence->coh_slow = zero;
        }
        for (unsigned x = 0; x < shared->num_x_channels; ++x) {
            if (!(mask & (1u << x)) || near_end || reset_now) main_state->mu[y][x] = zero;
            else if (control.bootstrap_remaining[y] > 0) {
                main_state->mu[y][x].mant = AEC_MAIN_ONLY_BOOTSTRAP_MU_Q30;
                main_state->mu[y][x].exp = -30;
            }
        }
        if (!near_end && !reset_now && control.bootstrap_remaining[y] > 0) control.bootstrap_remaining[y]--;
    }
}
