// Copyright 2022-2023 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

#ifndef AUDIO_PIPELINE_DSP_H_
#define AUDIO_PIPELINE_DSP_H_

#include <stdint.h>
#include <stddef.h>
#include "FreeRTOS.h"
#include "stream_buffer.h"
#include "app_conf.h"
#include <stdint.h>

/* Pipeline config */
#define AP_MAX_Y_CHANNELS (4)
#if appconfFIXED_DELAY_AEC_4Y2X_MAIN_ONLY
#define AP_MAX_X_CHANNELS (2)
#if appconfMIC_PIPELINE_PROC_CHANNELS != 2 || appconfMIC_PIPELINE_INPUT_CHANNELS != 4 || appconfMIC_PIPELINE_REF_CHANNELS != 2
#error Main-only 4Y2X requires four microphones and two exported E/W slots
#endif
#if appconfINPUT_SAMPLES_MIC_DELAY_MS != 0
#error Main-only 4Y2X requires zero static microphone delay
#endif
#else
#define AP_MAX_X_CHANNELS (1)
#endif
#define AP_FRAME_ADVANCE (240)

/* AEC config */
/* AEC bounds and phase counts propagate from fph::aec_4y to every TU. */

/* Delay buffer config */
#define MAX_DELAY_BUF_CHANNELS (2)
#define DELAY_BUF_MAX_DELAY_MS                ( 150 )
#define DELAY_BUF_MAX_DELAY_SAMPLES           ( 16000*DELAY_BUF_MAX_DELAY_MS/1000 )

#include "aec.h"
#include "aec_schedule_4y.h"
#include "agc.h"
#include "ic.h"
#include "ns.h"

_Static_assert(AEC_MAX_Y_CHANNELS == AP_MAX_Y_CHANNELS, "AEC microphone ABI mismatch");
_Static_assert(AEC_MAX_X_CHANNELS == AP_MAX_X_CHANNELS, "AEC reference ABI mismatch");


/* Note: Changing the order here will effect the channel order for
 * audio_pipeline_input() and audio_pipeline_output()
 */
typedef struct {
    int32_t samples[appconfMIC_PIPELINE_PROC_CHANNELS][appconfAUDIO_PIPELINE_FRAME_ADVANCE];
    int32_t aec_reference_audio_samples[appconfMIC_PIPELINE_REF_CHANNELS][appconfAUDIO_PIPELINE_FRAME_ADVANCE];
    int32_t mic_samples_passthrough[appconfMIC_PIPELINE_INPUT_CHANNELS][appconfAUDIO_PIPELINE_FRAME_ADVANCE];

    /* Below is additional context needed by other stages on a per frame basis */
    float_s32_t vnr_pred;
    float_s32_t max_ref_energy;
    float_s32_t aec_corr_factor;
    int32_t ref_active_flag;
} frame_data_t;

_Static_assert(offsetof(frame_data_t, mic_samples_passthrough) ==
        offsetof(frame_data_t, aec_reference_audio_samples) +
        sizeof(((frame_data_t *)0)->aec_reference_audio_samples),
        "Input callback requires contiguous reference and raw microphone slots");
_Static_assert(appconfMIC_PIPELINE_PROC_CHANNELS <= AEC_MAX_Y_CHANNELS,
        "Exported residuals must fit the AEC output scratch");

typedef struct stage_delay_ctx {
    StreamBufferHandle_t delay_buf;
} stage_delay_ctx_t;

typedef struct aec_ctx {
    aec_state_t DWORD_ALIGNED state;
} aec_ctx_t;

typedef struct ic_stage_ctx {
    ic_state_t DWORD_ALIGNED state;
} ic_stage_ctx_t;

typedef struct ns_stage_ctx {
    ns_state_t DWORD_ALIGNED state;
} ns_stage_ctx_t;

typedef struct agc_stage_ctx {
    agc_meta_data_t md;
    agc_state_t DWORD_ALIGNED state;
} agc_stage_ctx_t;

/**
 * Delay buffer contains the configured buffer delay size + 1 frame worth of audio
 * When appconfINPUT_SAMPLES_MIC_DELAY_MS  is positive, the mic is delayed
 * When appconfINPUT_SAMPLES_MIC_DELAY_MS is negative, the mic is "advanced" by delaying ref
 */
#define ABS(A) ((A >= 0) ? A : -A)
#define AP_INPUT_SAMPLES_MIC_DELAY_SIZE_PER_CHAN        ( 16000*ABS(appconfINPUT_SAMPLES_MIC_DELAY_MS)/1000 )
#define AP_INPUT_SAMPLES_MIC_DELAY_CHAN_CNT             ( (appconfINPUT_SAMPLES_MIC_DELAY_MS > 0) ? AEC_MAX_Y_CHANNELS : AEC_MAX_X_CHANNELS )
#define AP_INPUT_SAMPLES_MIC_DELAY_SIZE_CHAN            ( AP_INPUT_SAMPLES_MIC_DELAY_SIZE_PER_CHAN * AP_INPUT_SAMPLES_MIC_DELAY_CHAN_CNT )
#define AP_INPUT_SAMPLES_MIC_DELAY_SIZE_CUR_FRAME_WORDS ( AP_INPUT_SAMPLES_MIC_DELAY_CHAN_CNT * appconfAUDIO_PIPELINE_FRAME_ADVANCE)
#define AP_INPUT_SAMPLES_MIC_DELAY_CUR_FRAME_BYTES      ( AP_INPUT_SAMPLES_MIC_DELAY_SIZE_CUR_FRAME_WORDS * sizeof(int32_t))
#define AP_INPUT_SAMPLES_MIC_DELAY_BUF_SIZE_BYTES       ( AP_INPUT_SAMPLES_MIC_DELAY_SIZE_CHAN * sizeof(int32_t) )

#endif /* AUDIO_PIPELINE_DSP_H_ */
