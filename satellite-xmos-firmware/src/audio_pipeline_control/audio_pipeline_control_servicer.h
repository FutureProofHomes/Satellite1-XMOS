#pragma once

#include "../control/servicer.h"

#include "audio_pipeline_control_settings.h"

#define NUM_RESOURCES_AUDIO_PIPELINE_TILE0_SERVICER    (1)
#define NUM_RESOURCES_AUDIO_PIPELINE_TILE1_SERVICER    (2)

typedef struct {
    mic_output_pipeline_settings_t active;
    mic_output_pipeline_settings_t pending;
    uint8_t pending_valid;
} mic_output_pipeline_settings_runtime_t;

typedef struct {
    mic_input_pipeline_settings_t active;
    mic_input_pipeline_settings_t pending;
    uint8_t pending_valid;
} mic_input_pipeline_settings_runtime_t;

typedef struct {
    speaker_pipeline_settings_t active;
    speaker_pipeline_settings_t pending;
    uint8_t pending_valid;
} speaker_pipeline_settings_runtime_t;

typedef struct {
    servicer_t *servicer;
    mic_output_pipeline_settings_runtime_t *mic_output_settings;
    speaker_pipeline_settings_runtime_t *speaker_settings;
    mic_input_pipeline_settings_runtime_t *mic_input_settings;
} audio_pipeline_servicer_ctx_t;

void audio_pipeline_servicer(void *args);

void audio_pipeline_tile0_servicer_init(servicer_t *servicer);

void audio_pipeline_tile1_servicer_init(servicer_t *servicer);

void mic_output_pipeline_settings_runtime_init(
    mic_output_pipeline_settings_runtime_t *settings_runtime);

void mic_input_pipeline_settings_runtime_init(
    mic_input_pipeline_settings_runtime_t *settings_runtime);

void speaker_pipeline_settings_runtime_init(
    speaker_pipeline_settings_runtime_t *settings_runtime);
