#include <stddef.h>

#include "audio_pipeline_control_cmds.h"
#include "audio_pipeline_control_settings.h"

static const audio_pipeline_gain_t audio_pipeline_unity_gain = 0x40000000;

void fixed_delay_mic_pipeline_settings_default(
    fixed_delay_mic_pipeline_settings_t *settings)
{
    settings->mic_gain = audio_pipeline_unity_gain;
    settings->ref_gain = audio_pipeline_unity_gain;
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

bool fixed_delay_mic_pipeline_settings_channel_maps_are_valid(
    const fixed_delay_mic_pipeline_settings_t *settings)
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

bool fixed_delay_mic_pipeline_settings_update_is_valid(
    const fixed_delay_mic_pipeline_settings_update_t *settings_update)
{
    uint32_t field_mask = settings_update->field_mask;

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
