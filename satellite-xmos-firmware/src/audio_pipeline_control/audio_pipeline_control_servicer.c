#include <string.h>
#include <platform.h>
#include <xassert.h>

#include "FreeRTOS.h"

#include "audio_pipeline_control_cmds.h"
#include "audio_pipeline_control_servicer.h"
#include "platform/platform_conf.h"

static control_cmd_info_t audio_pipeline_mic_settings_cmd_map[] = {
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_SETTINGS, 1,
      sizeof(mic_output_pipeline_settings_t), CMD_READ_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_SET_SETTINGS_PARTIAL, 1,
      sizeof(mic_output_pipeline_settings_update_t), CMD_WRITE_ONLY },
};

static control_cmd_info_t audio_pipeline_mic_input_settings_cmd_map[] = {
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_SETTINGS, 1,
      sizeof(mic_input_pipeline_settings_t), CMD_READ_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_SET_SETTINGS_PARTIAL, 1,
      sizeof(mic_input_pipeline_settings_update_t), CMD_WRITE_ONLY },
};

static control_cmd_info_t audio_pipeline_speaker_settings_cmd_map[] = {
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_SETTINGS, 1,
      sizeof(speaker_pipeline_settings_t), CMD_READ_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_SET_SETTINGS_PARTIAL, 1,
      sizeof(speaker_pipeline_settings_update_t), CMD_WRITE_ONLY },
};

static void mic_output_pipeline_settings_apply_update(
    mic_output_pipeline_settings_runtime_t *settings_runtime,
    const mic_output_pipeline_settings_update_t *settings_update)
{
    mic_output_pipeline_settings_t *settings = &settings_runtime->pending;

    if ((settings_update->field_mask &
            AUDIO_PIPELINE_SETTINGS_PACK_EXTRA_UPSAMPLE_CHANNELS_FIELD) != 0) {
        settings->pack_extra_upsample_channels =
            settings_update->settings.pack_extra_upsample_channels;
    }

    if ((settings_update->field_mask & AUDIO_PIPELINE_SETTINGS_I2S_CHANNEL_MAP_FIELD) != 0) {
        memcpy(settings->i2s_channel_map,
               settings_update->settings.i2s_channel_map,
               sizeof(settings->i2s_channel_map));
    }

    if ((settings_update->field_mask & AUDIO_PIPELINE_SETTINGS_UPSAMPLE_CHANNEL_MAP_FIELD) != 0) {
        memcpy(settings->upsample_channel_map,
               settings_update->settings.upsample_channel_map,
               sizeof(settings->upsample_channel_map));
    }

    settings_runtime->active = settings_runtime->pending;
    settings_runtime->pending_valid = 1;
}

static void mic_input_pipeline_settings_apply_update(
    mic_input_pipeline_settings_runtime_t *settings_runtime,
    const mic_input_pipeline_settings_update_t *settings_update)
{
    mic_input_pipeline_settings_t *settings = &settings_runtime->pending;

    if ((settings_update->field_mask & AUDIO_PIPELINE_SETTINGS_MIC_GAIN_FIELD) != 0) {
        settings->mic_gain = settings_update->settings.mic_gain;
    }

    if ((settings_update->field_mask & AUDIO_PIPELINE_SETTINGS_REF_GAIN_FIELD) != 0) {
        settings->ref_gain = settings_update->settings.ref_gain;
    }

    settings_runtime->active = settings_runtime->pending;
    settings_runtime->pending_valid = 1;
}

static void speaker_pipeline_settings_apply_update(
    speaker_pipeline_settings_runtime_t *settings_runtime,
    const speaker_pipeline_settings_update_t *settings_update)
{
    speaker_pipeline_settings_t *settings = &settings_runtime->pending;

    if ((settings_update->field_mask &
            AUDIO_PIPELINE_SETTINGS_SPK_EQ_ENABLED_FIELD) != 0) {
        settings->eq_enabled = settings_update->settings.eq_enabled;
    }

    if ((settings_update->field_mask &
            AUDIO_PIPELINE_SETTINGS_SPK_EQ_PROFILE_ID_FIELD) != 0) {
        settings->eq_profile_id = settings_update->settings.eq_profile_id;
    }

    settings_runtime->active = settings_runtime->pending;
    settings_runtime->pending_valid = 1;
}

void mic_output_pipeline_settings_runtime_init(
    mic_output_pipeline_settings_runtime_t *settings_runtime)
{
    mic_output_pipeline_settings_default(&settings_runtime->active);
    settings_runtime->pending = settings_runtime->active;
    settings_runtime->pending_valid = 0;
}

void mic_input_pipeline_settings_runtime_init(
    mic_input_pipeline_settings_runtime_t *settings_runtime)
{
    mic_input_pipeline_settings_default(&settings_runtime->active);
    settings_runtime->pending = settings_runtime->active;
    settings_runtime->pending_valid = 0;
}

void speaker_pipeline_settings_runtime_init(
    speaker_pipeline_settings_runtime_t *settings_runtime)
{
    speaker_pipeline_settings_default(&settings_runtime->active);
    settings_runtime->pending = settings_runtime->active;
    settings_runtime->pending_valid = 0;
}

static control_ret_t audio_pipeline_servicer_read_cmd(
    control_resid_t resid,
    control_cmd_t cmd,
    uint8_t *payload,
    size_t payload_len,
    void *app_data)
{
    control_ret_t ret = CONTROL_SUCCESS;
    audio_pipeline_servicer_ctx_t *ctx = app_data;
    servicer_t *servicer = ctx->servicer;
    control_resource_info_t *current_res_info = get_res_info(resid, servicer);
    control_cmd_info_t *current_cmd_info;

    xassert(current_res_info != NULL);

    payload_len -= 1;
    payload += 1;

    ret = validate_cmd(&current_cmd_info, current_res_info, cmd, payload, payload_len);
    if (ret != CONTROL_SUCCESS) {
        payload[-1] = ret;
        return ret;
    }

    switch (resid) {
    case AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID:
        xassert(ctx->mic_output_settings != NULL);
        memcpy(payload, &ctx->mic_output_settings->active,
               sizeof(ctx->mic_output_settings->active));
        break;
    case AUDIO_PIPELINE_SPEAKER_SETTINGS_RESID:
        xassert(ctx->speaker_settings != NULL);
        memcpy(payload, &ctx->speaker_settings->active,
               sizeof(ctx->speaker_settings->active));
        break;
    case AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID:
        xassert(ctx->mic_input_settings != NULL);
        memcpy(payload, &ctx->mic_input_settings->active,
               sizeof(ctx->mic_input_settings->active));
        break;
    default:
        ret = CONTROL_BAD_RESOURCE;
        break;
    }

    payload[-1] = ret;
    return ret;
}

static control_ret_t audio_pipeline_servicer_write_cmd(
    control_resid_t resid,
    control_cmd_t cmd,
    const uint8_t *payload,
    size_t payload_len,
    void *app_data)
{
    control_ret_t ret = CONTROL_SUCCESS;
    audio_pipeline_servicer_ctx_t *ctx = app_data;
    servicer_t *servicer = ctx->servicer;
    control_resource_info_t *current_res_info = get_res_info(resid, servicer);
    control_cmd_info_t *current_cmd_info;

    xassert(current_res_info != NULL);

    ret = validate_cmd(&current_cmd_info, current_res_info, cmd, payload, payload_len);
    if (ret != CONTROL_SUCCESS) {
        return ret;
    }

    switch (resid) {
    case AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID:
    {
        mic_output_pipeline_settings_update_t settings_update;

        memcpy(&settings_update, payload, sizeof(settings_update));

        if (!mic_output_pipeline_settings_update_is_valid(&settings_update)) {
            return SERVICER_WRONG_PAYLOAD;
        }

        xassert(ctx->mic_output_settings != NULL);
        mic_output_pipeline_settings_apply_update(ctx->mic_output_settings,
                                                  &settings_update);
        break;
    }
    case AUDIO_PIPELINE_SPEAKER_SETTINGS_RESID:
    {
        speaker_pipeline_settings_update_t settings_update;

        memcpy(&settings_update, payload, sizeof(settings_update));

        if (!speaker_pipeline_settings_update_is_valid(&settings_update)) {
            return SERVICER_WRONG_PAYLOAD;
        }

        xassert(ctx->speaker_settings != NULL);
        speaker_pipeline_settings_apply_update(ctx->speaker_settings,
                                               &settings_update);
        break;
    }
    case AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID:
    {
        mic_input_pipeline_settings_update_t settings_update;

        memcpy(&settings_update, payload, sizeof(settings_update));

        if (!mic_input_pipeline_settings_update_is_valid(&settings_update)) {
            return SERVICER_WRONG_PAYLOAD;
        }

        xassert(ctx->mic_input_settings != NULL);
        mic_input_pipeline_settings_apply_update(ctx->mic_input_settings,
                                                 &settings_update);
        break;
    }
    default:
        ret = CONTROL_BAD_RESOURCE;
        break;
    }

    return ret;
}

void audio_pipeline_tile0_servicer_init(servicer_t *servicer)
{
    static control_resource_info_t audio_pipeline_tile0_res_info[
        NUM_RESOURCES_AUDIO_PIPELINE_TILE0_SERVICER];

    memset(servicer, 0, sizeof(servicer_t));
    servicer->id = AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID;
    servicer->start_io = 0;
    servicer->num_resources = NUM_RESOURCES_AUDIO_PIPELINE_TILE0_SERVICER;
    servicer->res_info = &audio_pipeline_tile0_res_info[0];

    servicer->res_info[0].resource = AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID;
    servicer->res_info[0].command_map.num_commands = NUM_AUDIO_PIPELINE_SETTINGS_CMDS;
    servicer->res_info[0].command_map.commands = audio_pipeline_mic_settings_cmd_map;
}

void audio_pipeline_tile1_servicer_init(servicer_t *servicer)
{
    static control_resource_info_t audio_pipeline_tile1_res_info[
        NUM_RESOURCES_AUDIO_PIPELINE_TILE1_SERVICER];

    memset(servicer, 0, sizeof(servicer_t));
    servicer->id = AUDIO_PIPELINE_SPEAKER_SETTINGS_RESID;
    servicer->start_io = 0;
    servicer->num_resources = NUM_RESOURCES_AUDIO_PIPELINE_TILE1_SERVICER;
    servicer->res_info = &audio_pipeline_tile1_res_info[0];

    servicer->res_info[0].resource = AUDIO_PIPELINE_SPEAKER_SETTINGS_RESID;
    servicer->res_info[0].command_map.num_commands = NUM_AUDIO_PIPELINE_SETTINGS_CMDS;
    servicer->res_info[0].command_map.commands = audio_pipeline_speaker_settings_cmd_map;

    servicer->res_info[1].resource = AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID;
    servicer->res_info[1].command_map.num_commands = NUM_AUDIO_PIPELINE_SETTINGS_CMDS;
    servicer->res_info[1].command_map.commands = audio_pipeline_mic_input_settings_cmd_map;
}

void audio_pipeline_servicer(void *args)
{
    device_control_servicer_t servicer_ctx;
    servicer_register_ctx_t *servicer_reg_ctx = (servicer_register_ctx_t *) args;
    audio_pipeline_servicer_ctx_t *audio_ctx =
        (audio_pipeline_servicer_ctx_t *) servicer_reg_ctx->app_data;
    servicer_t *servicer = servicer_reg_ctx->servicer;
    control_resid_t *resources;
    int i;

    xassert(servicer != NULL);
    xassert(audio_ctx != NULL);

    resources = pvPortMalloc(servicer->num_resources * sizeof(control_resid_t));
    for (i = 0; i < servicer->num_resources; i++) {
        resources[i] = servicer->res_info[i].resource;
    }

    (void) device_control_servicer_register(&servicer_ctx,
                                            servicer_reg_ctx->device_control_ctx,
                                            servicer_reg_ctx->device_control_ctx_count,
                                            resources,
                                            servicer->num_resources);

    vPortFree(resources);

    for (;;) {
        (void) device_control_servicer_cmd_recv(&servicer_ctx,
                                                audio_pipeline_servicer_read_cmd,
                                                audio_pipeline_servicer_write_cmd,
                                                audio_ctx,
                                                RTOS_OSAL_WAIT_FOREVER);
    }
}
