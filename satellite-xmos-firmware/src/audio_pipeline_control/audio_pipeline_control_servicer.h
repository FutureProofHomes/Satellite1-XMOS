#pragma once

#include "../control/servicer.h"

#include "audio_pipeline_control_settings.h"

#define NUM_RESOURCES_AUDIO_PIPELINE_SERVICER          (2)

typedef struct {
    fixed_delay_mic_pipeline_settings_t active;
    fixed_delay_mic_pipeline_settings_t pending;
    uint8_t pending_valid;
} fixed_delay_mic_pipeline_settings_runtime_t;

typedef struct {
    speaker_pipeline_settings_t active;
    speaker_pipeline_settings_t pending;
    uint8_t pending_valid;
} speaker_pipeline_settings_runtime_t;

typedef struct {
    servicer_t *servicer;
    fixed_delay_mic_pipeline_settings_runtime_t *mic_settings;
    speaker_pipeline_settings_runtime_t *speaker_settings;
} audio_pipeline_servicer_ctx_t;

void audio_pipeline_servicer(void *args);

void audio_pipeline_servicer_init(servicer_t *servicer);

void fixed_delay_mic_pipeline_settings_runtime_init(
    fixed_delay_mic_pipeline_settings_runtime_t *settings_runtime);

void speaker_pipeline_settings_runtime_init(
    speaker_pipeline_settings_runtime_t *settings_runtime);
