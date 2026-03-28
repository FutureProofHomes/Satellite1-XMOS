#pragma once

#include "servicer.h"
#include "audio_pipeline_control/audio_pipeline_control_servicer.h"

/* Deprecated compatibility shim: use AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID (230). */
#define AUDIO_CFG_SERVICER_RESID (30)
#define AUDIO_CFG_SERVICER_NUM_RESOURCES (1)

#define NUM_MIC_I2S_CHANNELS 2

enum e_audio_cfg_servicer_cmd_map {
  CFG_SERVICER_CMD_MIC_LEFT_SELECT = 10,
  CFG_SERVICER_CMD_MIC_RIGHT_SELECT,
  NUM_CFG_SERVICER_RESID_CMDS = 2
};


typedef struct { uint8_t left, right; } channel_sel_t;

typedef struct {
    servicer_t  *servicer;
    device_control_t **device_control_ctx;
    size_t device_control_ctx_count;
    mic_output_pipeline_settings_runtime_t *mic_output_settings;
    channel_sel_t mic_out_ch_select;
} device_control_audio_cfg_ctx_t;



void audio_cfg_servicer_init(device_control_audio_cfg_ctx_t *ctx,
                             mic_output_pipeline_settings_runtime_t *mic_output_settings);
void audio_cfg_servicer_start(device_control_audio_cfg_ctx_t *ctx, device_control_t **device_control_ctx, size_t device_control_ctx_count);
