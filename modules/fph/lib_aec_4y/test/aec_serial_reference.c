// Copyright 2026 Future Proof Homes
#include "aec.h"
#include "aec_priv.h"

/* Independent channel loops exercise the same AEC primitives without using
 * aec_process_frame or its task distribution tables.
 */
void aec_serial_reference(aec_filter_state_t *main, aec_filter_state_t *shadow,
        int32_t (*output)[AEC_FRAME_ADVANCE],
        int32_t (*shadow_output)[AEC_FRAME_ADVANCE],
        const int32_t (*y)[AEC_FRAME_ADVANCE],
        const int32_t (*x)[AEC_FRAME_ADVANCE])
{
    unsigned ny = main->shared_state->num_y_channels;
    unsigned nx = main->shared_state->num_x_channels;
    aec_frame_init(main, shadow, y, x);
    for (unsigned ch = 0; ch < ny; ++ch) {
        aec_calc_time_domain_ema_energy(&main->shared_state->y_ema_energy[ch],
            &main->shared_state->y[ch], AEC_PROC_FRAME_LENGTH - AEC_FRAME_ADVANCE,
            AEC_FRAME_ADVANCE, &main->shared_state->config_params);
        aec_forward_fft(&main->shared_state->Y[ch], &main->shared_state->y[ch]);
    }
    for (unsigned ch = 0; ch < nx; ++ch) {
        aec_calc_time_domain_ema_energy(&main->shared_state->x_ema_energy[ch],
            &main->shared_state->x[ch], AEC_PROC_FRAME_LENGTH - AEC_FRAME_ADVANCE,
            AEC_FRAME_ADVANCE, &main->shared_state->config_params);
        aec_forward_fft(&main->shared_state->X[ch], &main->shared_state->x[ch]);
        aec_calc_X_fifo_energy(main, ch, main->shared_state->X_energy_recalc_bin);
        aec_calc_X_fifo_energy(shadow, ch, main->shared_state->X_energy_recalc_bin);
        aec_update_X_fifo_and_calc_sigmaXX(main, ch);
    }
    main->shared_state->X_energy_recalc_bin =
        (main->shared_state->X_energy_recalc_bin + 1) % AEC_FD_FRAME_LENGTH;
    aec_update_X_fifo_1d(main);
    aec_update_X_fifo_1d(shadow);
    for (unsigned ch = 0; ch < ny; ++ch) {
        aec_calc_Error_and_Y_hat(main, ch);
        aec_calc_Error_and_Y_hat(shadow, ch);
        aec_inverse_fft(&main->error[ch], &main->Error[ch]);
        aec_inverse_fft(&shadow->error[ch], &shadow->Error[ch]);
        aec_inverse_fft(&main->y_hat[ch], &main->Y_hat[ch]);
        aec_calc_coherence(main, ch);
        aec_calc_output(main, &output[ch], ch);
        aec_calc_output(shadow, shadow_output ? &shadow_output[ch] : NULL, ch);
        bfp_s32_t temp;
        bfp_s32_init(&temp, output[ch], -31, AEC_FRAME_ADVANCE, 1);
        aec_calc_time_domain_ema_energy(&main->error_ema_energy[ch], &temp,
            0, AEC_FRAME_ADVANCE, &main->shared_state->config_params);
        aec_forward_fft(&main->Error[ch], &main->error[ch]);
        aec_forward_fft(&shadow->Error[ch], &shadow->error[ch]);
        aec_calc_freq_domain_energy(&main->overall_Error[ch], &main->Error[ch]);
        aec_calc_freq_domain_energy(&shadow->overall_Error[ch], &shadow->Error[ch]);
        aec_calc_freq_domain_energy(&main->shared_state->overall_Y[ch], &main->shared_state->Y[ch]);
    }
    aec_compare_filters_and_calc_mu(main, shadow);
    for (unsigned ch = 0; ch < nx; ++ch) {
        aec_calc_normalisation_spectrum(main, ch, 0);
        aec_calc_normalisation_spectrum(shadow, ch, 1);
    }
    for (unsigned ych = 0; ych < ny; ++ych) {
        for (unsigned xch = 0; xch < nx; ++xch) {
            aec_calc_T(main, ych, xch);
            aec_calc_T(shadow, ych, xch);
        }
        aec_filter_adapt(main, ych);
        aec_filter_adapt(shadow, ych);
    }
}
