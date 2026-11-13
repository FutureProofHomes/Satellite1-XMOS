// Copyright 2026 Future Proof Homes
#ifndef VOICE_COMPAT_H_
#define VOICE_COMPAT_H_

#include "ic.h"
#include "vnr.h"

/* IC now owns only input VNR. Keep the output-spectrum VNR and smoothing used
 * by the pipelines' existing AGC gate, independently of IC adaptation. */
typedef struct {
    vnr_feature_state_t feature_state;
    float_s32_t input_vnr_pred;
    float_s32_t output_vnr_pred;
} voice_output_vnr_state_t;

static inline int32_t voice_ic_init(ic_state_t *ic, voice_output_vnr_state_t *vnr)
{
    int32_t status = ic_init(ic);
    vnr_feature_state_init(&vnr->feature_state);
    vnr->input_vnr_pred = f32_to_float_s32(IC_INIT_INPUT_VNR_PRED);
    vnr->output_vnr_pred = f32_to_float_s32(0.5);
    return status;
}

static inline void voice_ic_calc_vnr_pred(ic_state_t *ic, voice_output_vnr_state_t *vnr)
{
    float_s32_t prediction;
    ic_calc_vnr_pred(ic, &prediction);
    vnr->input_vnr_pred = ic->vnr_pred_state.input_vnr_pred;

    bfp_s32_t patch;
    int32_t DWORD_ALIGNED patch_data[VNR_PATCH_WIDTH * VNR_MEL_FILTERS];
    vnr_extract_features(&vnr->feature_state, &patch, patch_data, &ic->Error_bfp[0]);
    vnr_inference(&prediction, &patch);
    vnr->output_vnr_pred = float_s32_ema(vnr->output_vnr_pred, prediction,
                                      ic->vnr_pred_state.pred_alpha_q30);
}

#endif
