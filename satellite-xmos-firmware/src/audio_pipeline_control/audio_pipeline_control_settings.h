#pragma once

#include <stdbool.h>
#include <stdint.h>

#define AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID       (230)
#define AUDIO_PIPELINE_SPEAKER_SETTINGS_RESID          (231)
#define AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID        (232)

#define AUDIO_PIPELINE_OUTPUT_CHANNEL_COUNT            (2)
#define AUDIO_PIPELINE_OUTPUT_CHANNEL_INDEX_MIN        (0)
#define AUDIO_PIPELINE_OUTPUT_CHANNEL_INDEX_MAX        (5)
#define AUDIO_PIPELINE_UPSAMPLE_CHANNEL_MAP_COUNT      (6)

typedef int32_t audio_pipeline_gain_t;

typedef enum
{
    AUDIO_PIPELINE_SPK_EQ_PROFILE_NONE = 0,
    AUDIO_PIPELINE_SPK_EQ_PROFILE_1,
    AUDIO_PIPELINE_SPK_EQ_PROFILE_2,

    NUM_AUDIO_PIPELINE_SPK_EQ_PROFILES
} audio_pipeline_speaker_eq_profile_id_t;

typedef struct
{
    uint8_t pack_extra_upsample_channels;
    uint8_t i2s_channel_map[AUDIO_PIPELINE_OUTPUT_CHANNEL_COUNT];
    uint8_t upsample_channel_map[AUDIO_PIPELINE_UPSAMPLE_CHANNEL_MAP_COUNT];
} mic_output_pipeline_settings_t;

typedef struct
{
    uint32_t field_mask;
    mic_output_pipeline_settings_t settings;
} mic_output_pipeline_settings_update_t;

typedef struct
{
    audio_pipeline_gain_t mic_gain;
    audio_pipeline_gain_t ref_gain;
} mic_input_pipeline_settings_t;

typedef struct
{
    uint32_t field_mask;
    mic_input_pipeline_settings_t settings;
} mic_input_pipeline_settings_update_t;

typedef struct
{
    uint8_t eq_enabled;
    uint8_t eq_profile_id;
} speaker_pipeline_settings_t;

typedef struct
{
    uint32_t field_mask;
    speaker_pipeline_settings_t settings;
} speaker_pipeline_settings_update_t;

void mic_output_pipeline_settings_default(
    mic_output_pipeline_settings_t *settings);

void mic_input_pipeline_settings_default(
    mic_input_pipeline_settings_t *settings);

void speaker_pipeline_settings_default(
    speaker_pipeline_settings_t *settings);

bool audio_pipeline_output_channel_index_is_valid(uint8_t channel_index);

bool mic_output_pipeline_settings_channel_maps_are_valid(
    const mic_output_pipeline_settings_t *settings);

bool mic_output_pipeline_settings_update_is_valid(
    const mic_output_pipeline_settings_update_t *settings_update);

bool mic_input_pipeline_settings_are_valid(
    const mic_input_pipeline_settings_t *settings);

bool mic_input_pipeline_settings_update_is_valid(
    const mic_input_pipeline_settings_update_t *settings_update);

bool speaker_pipeline_settings_are_valid(
    const speaker_pipeline_settings_t *settings);

bool speaker_pipeline_settings_update_is_valid(
    const speaker_pipeline_settings_update_t *settings_update);
