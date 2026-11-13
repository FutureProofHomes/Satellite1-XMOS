// Copyright 2026 Future Proof Homes
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "aec.h"
#include "agc.h"
#include "voice_compat.h"

void aec_process_frame_1thread(aec_filter_state_t *, aec_filter_state_t *,
        int32_t (*)[AEC_FRAME_ADVANCE], int32_t (*)[AEC_FRAME_ADVANCE],
        const int32_t (*)[AEC_FRAME_ADVANCE], const int32_t (*)[AEC_FRAME_ADVANCE]);

#define CANARY UINT64_C(0x6e37f491a582c0bd)
typedef struct {
    uint64_t before;
    aec_state_t state;
    uint64_t after;
} guarded_aec_t;
static guarded_aec_t *guarded;
static int32_t DWORD_ALIGNED y[2][AEC_FRAME_ADVANCE];
static int32_t DWORD_ALIGNED x[2][AEC_FRAME_ADVANCE];
static int32_t DWORD_ALIGNED output[2][AEC_FRAME_ADVANCE];
static ic_state_t *ic;
static voice_output_vnr_state_t vnr;
static vnr_feature_state_t expected_features;

static void fill_frame(unsigned frame)
{
    for (unsigned ch = 0; ch < 2; ++ch) {
        for (unsigned i = 0; i < AEC_FRAME_ADVANCE; ++i) {
            unsigned sample = frame * AEC_FRAME_ADVANCE + i;
            y[ch][i] = (int32_t)(((sample + ch * 97u) * 3571u) % 100019u) * 512;
            x[ch][i] = (int32_t)(((sample + ch * 31u) * 7919u) % 100003u) * 1024;
        }
    }
}

static void test_aec_configurations(void)
{
    /* Normal fixed/ADEC, alt-arch, and delay-estimation configurations. */
    const unsigned configs[][4] = {{2, 2, 10, 5}, {1, 2, 15, 5}, {1, 1, 30, 0}};
    for (unsigned c = 0; c < sizeof(configs) / sizeof(configs[0]); ++c) {
        memset(guarded, 0, sizeof(*guarded));
        guarded->before = guarded->after = CANARY;
        aec_state_t *state = &guarded->state;
        aec_init(state, configs[c][0], configs[c][1], configs[c][2], configs[c][3],
                 &aec_tdist_chans2_threads1);
        assert(state->main_state.shared_state == &state->shared_state);
        assert(state->shadow_state.shared_state == &state->shared_state);
        assert((uint8_t *)(state->main_state.overlap[configs[c][0] - 1].data + 32)
                <= (uint8_t *)(&state->main_mem_pool + 1));
        assert((uint8_t *)(state->shadow_state.overlap[configs[c][0] - 1].data + 32)
                <= (uint8_t *)(&state->shadow_mem_pool + 1));
        for (unsigned frame = 0; frame < 8; ++frame) {
            fill_frame(frame);
            aec_process_frame_1thread(&state->main_state, &state->shadow_state,
                                      output, NULL, y, x);
            assert(guarded->before == CANARY && guarded->after == CANARY);
        }
        aec_reset_state(state);
        assert(guarded->before == CANARY && guarded->after == CANARY);
        assert(state->main_state.H_hat[0][0].exp == AEC_ZEROVAL_EXP);
    }
}

static void test_output_vnr(void)
{
    assert(voice_ic_init(ic, &vnr) == 0);
    vnr_feature_state_init(&expected_features);
    float_s32_t expected = f32_to_float_s32(0.5);
    for (unsigned frame = 0; frame < 8; ++frame) {
        fill_frame(frame);
        ic_filter(ic, y[0], y[1], output[0]);
        voice_ic_calc_vnr_pred(ic, &vnr);

        bfp_s32_t patch;
        int32_t DWORD_ALIGNED patch_data[VNR_PATCH_WIDTH * VNR_MEL_FILTERS];
        float_s32_t prediction;
        vnr_extract_features(&expected_features, &patch, patch_data, &ic->Error_bfp[0]);
        vnr_inference(&prediction, &patch);
        expected = float_s32_ema(expected, prediction, ic->vnr_pred_state.pred_alpha_q30);
        assert(vnr.output_vnr_pred.mant == expected.mant);
        assert(vnr.output_vnr_pred.exp == expected.exp);
        assert(vnr.input_vnr_pred.mant == ic->vnr_pred_state.input_vnr_pred.mant);
        assert(vnr.input_vnr_pred.exp == ic->vnr_pred_state.input_vnr_pred.exp);
        ic_adapt(ic);
    }
    for (int flag = 0; flag <= 1; ++flag) {
        float_s32_t metadata = f32_to_float_s32(flag);
        assert(float_s32_gt(metadata, f32_to_float_s32(0.5)) == flag);
    }
}

int main(void)
{
    guarded = malloc(sizeof(*guarded));
    ic = malloc(sizeof(*ic));
    assert(guarded && ic);
    test_aec_configurations();
    test_output_vnr();
    free(ic);
    free(guarded);
    puts("Voice compatibility: 24 serial AEC frames, pool bounds, reset, 8 output-VNR frames and Boolean AGC metadata passed");
    return 0;
}
