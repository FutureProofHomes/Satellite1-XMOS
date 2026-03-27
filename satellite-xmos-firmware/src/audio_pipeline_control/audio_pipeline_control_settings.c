#include <stddef.h>
#include <string.h>

#include "audio_pipeline_control_cmds.h"
#include "audio_pipeline_control_settings.h"

static const audio_pipeline_gain_t audio_pipeline_unity_gain = 0x40000000;

static bool audio_pipeline_packaged_input_channel_index_is_valid(
    uint8_t channel_index)
{
    return channel_index >= AUDIO_PIPELINE_PACKAGED_INPUT_INDEX_MIN &&
           channel_index <= AUDIO_PIPELINE_PACKAGED_INPUT_INDEX_MAX;
}

void mic_output_pipeline_settings_default(
    mic_output_pipeline_settings_t *settings)
{
    settings->pack_extra_upsample_channels = 0;

    settings->i2s_channel_map[0] = 0;
    settings->i2s_channel_map[1] = 3;

    settings->upsample_channel_map[0] = 0;
    settings->upsample_channel_map[1] = 3;
    settings->upsample_channel_map[2] = 0;
    settings->upsample_channel_map[3] = 3;
    settings->upsample_channel_map[4] = 0;
    settings->upsample_channel_map[5] = 3;
}

void mic_input_pipeline_settings_default(
    mic_input_pipeline_settings_t *settings)
{
    size_t index;

    settings->mic_gain = audio_pipeline_unity_gain;
    settings->ref_gain = audio_pipeline_unity_gain;
    settings->ref_source_mode = AUDIO_PIPELINE_REF_SOURCE_LEGACY_DOWNSAMPLED;
    settings->mic_source_mode = AUDIO_PIPELINE_MIC_SOURCE_PDM;

    settings->ref_input_channel_map[0] = 0;
    settings->ref_input_channel_map[1] = 3;

    for (index = 0; index < AUDIO_PIPELINE_MIC_INPUT_CHANNEL_MAP_COUNT; index++) {
        settings->mic_input_channel_map[index] =
            (4 + index) % AUDIO_PIPELINE_PACKAGED_INPUT_CHANNEL_COUNT;
    }
}

void speaker_pipeline_settings_default(
    speaker_pipeline_settings_t *settings)
{
    settings->eq_enabled = 0;
    settings->eq_profile_id = AUDIO_PIPELINE_SPK_EQ_PROFILE_NONE;
}

bool audio_pipeline_output_channel_index_is_valid(uint8_t channel_index)
{
    return channel_index >= AUDIO_PIPELINE_OUTPUT_CHANNEL_INDEX_MIN &&
           channel_index <= AUDIO_PIPELINE_OUTPUT_CHANNEL_INDEX_MAX;
}

bool mic_output_pipeline_settings_channel_maps_are_valid(
    const mic_output_pipeline_settings_t *settings)
{
    size_t index;

    for (index = 0; index < AUDIO_PIPELINE_OUTPUT_CHANNEL_COUNT; index++) {
        if (!audio_pipeline_output_channel_index_is_valid(
                settings->i2s_channel_map[index])) {
            return false;
        }
    }

    for (index = 0; index < AUDIO_PIPELINE_UPSAMPLE_CHANNEL_MAP_COUNT; index++) {
        if (!audio_pipeline_output_channel_index_is_valid(
                settings->upsample_channel_map[index])) {
            return false;
        }
    }

    return true;
}

bool mic_output_pipeline_settings_update_is_valid(
    const mic_output_pipeline_settings_update_t *settings_update)
{
    uint32_t field_mask = settings_update->field_mask;

    if ((field_mask &
            ~(AUDIO_PIPELINE_SETTINGS_PACK_EXTRA_UPSAMPLE_CHANNELS_FIELD |
              AUDIO_PIPELINE_SETTINGS_I2S_CHANNEL_MAP_FIELD |
              AUDIO_PIPELINE_SETTINGS_UPSAMPLE_CHANNEL_MAP_FIELD)) != 0) {
        return false;
    }

    if ((field_mask & AUDIO_PIPELINE_SETTINGS_I2S_CHANNEL_MAP_FIELD) != 0) {
        size_t index;

        for (index = 0; index < AUDIO_PIPELINE_OUTPUT_CHANNEL_COUNT; index++) {
            if (!audio_pipeline_output_channel_index_is_valid(
                    settings_update->settings.i2s_channel_map[index])) {
                return false;
            }
        }
    }

    if ((field_mask & AUDIO_PIPELINE_SETTINGS_UPSAMPLE_CHANNEL_MAP_FIELD) != 0) {
        size_t index;

        for (index = 0; index < AUDIO_PIPELINE_UPSAMPLE_CHANNEL_MAP_COUNT; index++) {
            if (!audio_pipeline_output_channel_index_is_valid(
                    settings_update->settings.upsample_channel_map[index])) {
                return false;
            }
        }
    }

    return true;
}

bool mic_input_pipeline_settings_are_valid(
    const mic_input_pipeline_settings_t *settings)
{
    size_t index;

    if (settings->ref_source_mode >= NUM_AUDIO_PIPELINE_REF_SOURCE_MODES) {
        return false;
    }

    if (settings->mic_source_mode >= NUM_AUDIO_PIPELINE_MIC_SOURCE_MODES) {
        return false;
    }

    for (index = 0; index < AUDIO_PIPELINE_REF_INPUT_CHANNEL_COUNT; index++) {
        if (!audio_pipeline_packaged_input_channel_index_is_valid(
                settings->ref_input_channel_map[index])) {
            return false;
        }
    }

    for (index = 0; index < AUDIO_PIPELINE_MIC_INPUT_CHANNEL_MAP_COUNT; index++) {
        if (!audio_pipeline_packaged_input_channel_index_is_valid(
                settings->mic_input_channel_map[index])) {
            return false;
        }
    }

    return true;
}

bool mic_input_pipeline_settings_update_is_valid(
    const mic_input_pipeline_settings_update_t *settings_update)
{
    mic_input_pipeline_settings_t settings;

    if ((settings_update->field_mask &
            ~(AUDIO_PIPELINE_SETTINGS_MIC_GAIN_FIELD |
              AUDIO_PIPELINE_SETTINGS_REF_GAIN_FIELD |
              AUDIO_PIPELINE_SETTINGS_REF_SOURCE_MODE_FIELD |
              AUDIO_PIPELINE_SETTINGS_MIC_SOURCE_MODE_FIELD |
              AUDIO_PIPELINE_SETTINGS_REF_INPUT_CHANNEL_MAP_FIELD |
              AUDIO_PIPELINE_SETTINGS_MIC_INPUT_CHANNEL_MAP_FIELD)) != 0) {
        return false;
    }

    mic_input_pipeline_settings_default(&settings);

    if ((settings_update->field_mask & AUDIO_PIPELINE_SETTINGS_MIC_GAIN_FIELD) != 0) {
        settings.mic_gain = settings_update->settings.mic_gain;
    }

    if ((settings_update->field_mask & AUDIO_PIPELINE_SETTINGS_REF_GAIN_FIELD) != 0) {
        settings.ref_gain = settings_update->settings.ref_gain;
    }

    if ((settings_update->field_mask &
            AUDIO_PIPELINE_SETTINGS_REF_SOURCE_MODE_FIELD) != 0) {
        settings.ref_source_mode = settings_update->settings.ref_source_mode;
    }

    if ((settings_update->field_mask &
            AUDIO_PIPELINE_SETTINGS_MIC_SOURCE_MODE_FIELD) != 0) {
        settings.mic_source_mode = settings_update->settings.mic_source_mode;
    }

    if ((settings_update->field_mask &
            AUDIO_PIPELINE_SETTINGS_REF_INPUT_CHANNEL_MAP_FIELD) != 0) {
        memcpy(settings.ref_input_channel_map,
               settings_update->settings.ref_input_channel_map,
               sizeof(settings.ref_input_channel_map));
    }

    if ((settings_update->field_mask &
            AUDIO_PIPELINE_SETTINGS_MIC_INPUT_CHANNEL_MAP_FIELD) != 0) {
        memcpy(settings.mic_input_channel_map,
               settings_update->settings.mic_input_channel_map,
               sizeof(settings.mic_input_channel_map));
    }

    return mic_input_pipeline_settings_are_valid(&settings);
}

bool speaker_pipeline_settings_are_valid(
    const speaker_pipeline_settings_t *settings)
{
    return settings->eq_profile_id < NUM_AUDIO_PIPELINE_SPK_EQ_PROFILES;
}

bool speaker_pipeline_settings_update_is_valid(
    const speaker_pipeline_settings_update_t *settings_update)
{
    if ((settings_update->field_mask &
            AUDIO_PIPELINE_SETTINGS_SPK_EQ_PROFILE_ID_FIELD) == 0) {
        return true;
    }

    return settings_update->settings.eq_profile_id <
           NUM_AUDIO_PIPELINE_SPK_EQ_PROFILES;
}
