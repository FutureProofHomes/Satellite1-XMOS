#include <string.h>
#include <platform.h>
#include <xassert.h>

#include "FreeRTOS.h"

#include "audio_pipeline_control_cmds.h"
#include "audio_pipeline_control_servicer.h"
#include "platform/platform_conf.h"

#if appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG && ON_TILE(0)
extern audio_pipeline_debug_counters_t audio_pipeline_tile0_debug;
extern fixed_delay_stage_snapshot_t fixed_delay_stage_snapshot;
extern void fixed_delay_ic_vnr_capture_arm(const fixed_delay_ic_vnr_capture_arm_t *arm);
extern void fixed_delay_ic_vnr_capture_get_status(fixed_delay_ic_vnr_capture_status_t *status);
extern void fixed_delay_ic_vnr_capture_get_probe(fixed_delay_ic_vnr_capture_probe_t *probe);
extern int fixed_delay_ic_vnr_capture_select_chunk(uint16_t chunk_index);
extern void fixed_delay_ic_vnr_capture_get_selected_chunk(
    fixed_delay_ic_vnr_capture_chunk_t *chunk);
#endif

#if appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG && ON_TILE(1)
extern audio_pipeline_debug_counters_t audio_pipeline_tile1_debug;
extern void fixed_delay_aec_capture_arm(const fixed_delay_aec_capture_arm_t *arm);
extern void fixed_delay_aec_capture_get_status(fixed_delay_aec_capture_status_t *status);
extern void fixed_delay_aec_capture_get_probe(fixed_delay_aec_capture_probe_t *probe);
extern int fixed_delay_aec_capture_select_chunk(uint16_t chunk_index);
extern void fixed_delay_aec_capture_get_selected_chunk(
    fixed_delay_aec_capture_chunk_t *chunk);
#endif

#define ARRAY_LENGTH(x) (sizeof(x) / sizeof((x)[0]))

static control_cmd_info_t audio_pipeline_mic_settings_cmd_map[] = {
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_SETTINGS, 1,
      sizeof(mic_output_pipeline_settings_t), CMD_READ_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_SET_SETTINGS_PARTIAL, 1,
      sizeof(mic_output_pipeline_settings_update_t), CMD_WRITE_ONLY },
#if appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_MIC_OUTPUT_PACKAGED_SNAPSHOT, 1,
      sizeof(mic_output_packaged_snapshot_t), CMD_READ_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_PIPELINE_DEBUG_COUNTERS, 1,
      sizeof(audio_pipeline_debug_counters_t), CMD_READ_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_FIXED_DELAY_STAGE_SNAPSHOT, 1,
      sizeof(fixed_delay_stage_snapshot_t), CMD_READ_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_ARM_FIXED_DELAY_IC_VNR_CAPTURE, 1,
      sizeof(fixed_delay_ic_vnr_capture_arm_t), CMD_WRITE_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_FIXED_DELAY_IC_VNR_CAPTURE_STATUS, 1,
      sizeof(fixed_delay_ic_vnr_capture_status_t), CMD_READ_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_SELECT_FIXED_DELAY_IC_VNR_CAPTURE_CHUNK, 1,
      sizeof(fixed_delay_ic_vnr_capture_chunk_select_t), CMD_WRITE_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_FIXED_DELAY_IC_VNR_CAPTURE_CHUNK, 1,
      sizeof(fixed_delay_ic_vnr_capture_chunk_t), CMD_READ_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_FIXED_DELAY_IC_VNR_CAPTURE_PROBE, 1,
      sizeof(fixed_delay_ic_vnr_capture_probe_t), CMD_READ_ONLY },
#endif
};

static control_cmd_info_t audio_pipeline_mic_input_settings_cmd_map[] = {
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_SETTINGS, 1,
      sizeof(mic_input_pipeline_settings_t), CMD_READ_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_SET_SETTINGS_PARTIAL, 1,
      sizeof(mic_input_pipeline_settings_update_t), CMD_WRITE_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_AVAILABLE_MIC_COUNT, 1,
      sizeof(uint8_t), CMD_READ_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_DOA_RAW, 1,
      sizeof(doa_reading_t), CMD_READ_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_DOA_SMOOTH, 1,
      sizeof(doa_reading_t), CMD_READ_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_MIC_INPUT_DEBUG_STATS, 1,
      sizeof(mic_input_debug_stats_t), CMD_READ_ONLY },
#if appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_MIC_INPUT_PACKAGED_SNAPSHOT, 1,
      sizeof(mic_input_packaged_snapshot_t), CMD_READ_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_SPK_INPUT_PACKAGED_SNAPSHOT, 1,
      sizeof(spk_input_packaged_snapshot_t), CMD_READ_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_PIPELINE_DEBUG_COUNTERS, 1,
      sizeof(audio_pipeline_debug_counters_t), CMD_READ_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_ARM_FIXED_DELAY_AEC_CAPTURE, 1,
      sizeof(fixed_delay_aec_capture_arm_t), CMD_WRITE_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_FIXED_DELAY_AEC_CAPTURE_STATUS, 1,
      sizeof(fixed_delay_aec_capture_status_t), CMD_READ_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_SELECT_FIXED_DELAY_AEC_CAPTURE_CHUNK, 1,
      sizeof(fixed_delay_aec_capture_chunk_select_t), CMD_WRITE_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_FIXED_DELAY_AEC_CAPTURE_CHUNK, 1,
      sizeof(fixed_delay_aec_capture_chunk_t), CMD_READ_ONLY },
    { AUDIO_PIPELINE_SETTINGS_CMD_GET_FIXED_DELAY_AEC_CAPTURE_PROBE, 1,
      sizeof(fixed_delay_aec_capture_probe_t), CMD_READ_ONLY },
#endif
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

    if ((settings_update->field_mask &
            AUDIO_PIPELINE_SETTINGS_OVERWRITE_REF_WITH_IC_NS_OUTPUT_FIELD) != 0) {
        settings->overwrite_ref_with_ic_ns_output =
            settings_update->settings.overwrite_ref_with_ic_ns_output;
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

    if ((settings_update->field_mask &
            AUDIO_PIPELINE_SETTINGS_REF_SOURCE_MODE_FIELD) != 0) {
        settings->ref_source_mode = settings_update->settings.ref_source_mode;
    }

    if ((settings_update->field_mask &
            AUDIO_PIPELINE_SETTINGS_MIC_SOURCE_MODE_FIELD) != 0) {
        settings->mic_source_mode = settings_update->settings.mic_source_mode;
    }

    if ((settings_update->field_mask &
            AUDIO_PIPELINE_SETTINGS_REF_INPUT_CHANNEL_MAP_FIELD) != 0) {
        memcpy(settings->ref_input_channel_map,
               settings_update->settings.ref_input_channel_map,
               sizeof(settings->ref_input_channel_map));
    }

    if ((settings_update->field_mask &
            AUDIO_PIPELINE_SETTINGS_MIC_INPUT_CHANNEL_MAP_FIELD) != 0) {
        memcpy(settings->mic_input_channel_map,
               settings_update->settings.mic_input_channel_map,
               sizeof(settings->mic_input_channel_map));
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
#if appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    memset(&settings_runtime->packaged_snapshot,
           0,
           sizeof(settings_runtime->packaged_snapshot));
#endif
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
    uint8_t cmd_id;

    xassert(current_res_info != NULL);

    payload_len -= 1;
    payload += 1;

    ret = validate_cmd(&current_cmd_info, current_res_info, cmd, payload, payload_len);
    if (ret != CONTROL_SUCCESS) {
        payload[-1] = ret;
        return ret;
    }

    cmd_id = CONTROL_CMD_CLEAR_READ(cmd);

    if (cmd_id == AUDIO_PIPELINE_SETTINGS_CMD_GET_AVAILABLE_MIC_COUNT) {
        if (resid != AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID) {
            ret = CONTROL_BAD_COMMAND;
            payload[-1] = ret;
            return ret;
        }

        payload[0] = AUDIO_PIPELINE_MIC_INPUT_CHANNEL_MAP_COUNT;
        payload[-1] = ret;
        return ret;
    }

    if (cmd_id == AUDIO_PIPELINE_SETTINGS_CMD_GET_DOA_RAW ||
        cmd_id == AUDIO_PIPELINE_SETTINGS_CMD_GET_DOA_SMOOTH) {
        if (resid != AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID ||
            ctx->doa == NULL) {
            ret = CONTROL_BAD_COMMAND;
            payload[-1] = ret;
            return ret;
        }

        if (cmd_id == AUDIO_PIPELINE_SETTINGS_CMD_GET_DOA_RAW) {
            memcpy(payload, &ctx->doa->raw, sizeof(ctx->doa->raw));
        } else {
            memcpy(payload, &ctx->doa->smooth, sizeof(ctx->doa->smooth));
        }
        payload[-1] = ret;
        return ret;
    }

    if (cmd_id == AUDIO_PIPELINE_SETTINGS_CMD_GET_MIC_INPUT_DEBUG_STATS) {
        if (resid != AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID ||
            ctx->doa == NULL) {
            ret = CONTROL_BAD_COMMAND;
            payload[-1] = ret;
            return ret;
        }

        memcpy(payload, &ctx->doa->mic_input_debug, sizeof(ctx->doa->mic_input_debug));
        payload[-1] = ret;
        return ret;
    }

#if appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    if (cmd_id == AUDIO_PIPELINE_SETTINGS_CMD_GET_MIC_INPUT_PACKAGED_SNAPSHOT) {
        if (resid != AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID ||
            ctx->doa == NULL) {
            ret = CONTROL_BAD_COMMAND;
            payload[-1] = ret;
            return ret;
        }

        memcpy(payload,
               &ctx->doa->mic_input_packaged_snapshot,
               sizeof(ctx->doa->mic_input_packaged_snapshot));
        payload[-1] = ret;
        return ret;
    }

    if (cmd_id == AUDIO_PIPELINE_SETTINGS_CMD_GET_SPK_INPUT_PACKAGED_SNAPSHOT) {
        if (resid != AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID ||
            ctx->doa == NULL) {
            ret = CONTROL_BAD_COMMAND;
            payload[-1] = ret;
            return ret;
        }

        memcpy(payload,
               &ctx->doa->spk_input_packaged_snapshot,
               sizeof(ctx->doa->spk_input_packaged_snapshot));
        payload[-1] = ret;
        return ret;
    }

    if (cmd_id == AUDIO_PIPELINE_SETTINGS_CMD_GET_MIC_OUTPUT_PACKAGED_SNAPSHOT) {
        if (resid != AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID ||
            ctx->mic_output_settings == NULL) {
            ret = CONTROL_BAD_COMMAND;
            payload[-1] = ret;
            return ret;
        }

        memcpy(payload,
               &ctx->mic_output_settings->packaged_snapshot,
               sizeof(ctx->mic_output_settings->packaged_snapshot));
        payload[-1] = ret;
        return ret;
    }

    if (cmd_id == AUDIO_PIPELINE_SETTINGS_CMD_GET_PIPELINE_DEBUG_COUNTERS) {
#if ON_TILE(0)
        if (resid != AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID) {
            ret = CONTROL_BAD_COMMAND;
            payload[-1] = ret;
            return ret;
        }
        memcpy(payload,
               &audio_pipeline_tile0_debug,
               sizeof(audio_pipeline_tile0_debug));
#elif ON_TILE(1)
        if (resid != AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID) {
            ret = CONTROL_BAD_COMMAND;
            payload[-1] = ret;
            return ret;
        }
        memcpy(payload,
               &audio_pipeline_tile1_debug,
               sizeof(audio_pipeline_tile1_debug));
#else
        ret = CONTROL_BAD_COMMAND;
#endif
        payload[-1] = ret;
        return ret;
    }

    if (cmd_id == AUDIO_PIPELINE_SETTINGS_CMD_GET_FIXED_DELAY_STAGE_SNAPSHOT) {
#if ON_TILE(0)
        if (resid != AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID) {
            ret = CONTROL_BAD_COMMAND;
            payload[-1] = ret;
            return ret;
        }
        memcpy(payload,
               &fixed_delay_stage_snapshot,
               sizeof(fixed_delay_stage_snapshot));
#else
        ret = CONTROL_BAD_COMMAND;
#endif
        payload[-1] = ret;
        return ret;
    }

    if (cmd_id == AUDIO_PIPELINE_SETTINGS_CMD_GET_FIXED_DELAY_AEC_CAPTURE_STATUS) {
#if ON_TILE(1)
        if (resid != AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID) {
            ret = CONTROL_BAD_COMMAND;
            payload[-1] = ret;
            return ret;
        }
        fixed_delay_aec_capture_get_status(
            (fixed_delay_aec_capture_status_t *)payload);
#else
        ret = CONTROL_BAD_COMMAND;
#endif
        payload[-1] = ret;
        return ret;
    }

    if (cmd_id == AUDIO_PIPELINE_SETTINGS_CMD_GET_FIXED_DELAY_AEC_CAPTURE_CHUNK) {
#if ON_TILE(1)
        if (resid != AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID) {
            ret = CONTROL_BAD_COMMAND;
            payload[-1] = ret;
            return ret;
        }
        fixed_delay_aec_capture_chunk_t chunk;
        fixed_delay_aec_capture_get_selected_chunk(&chunk);
        memcpy(payload, &chunk, sizeof(chunk));
#else
        ret = CONTROL_BAD_COMMAND;
#endif
        payload[-1] = ret;
        return ret;
    }

    if (cmd_id == AUDIO_PIPELINE_SETTINGS_CMD_GET_FIXED_DELAY_AEC_CAPTURE_PROBE) {
#if ON_TILE(1)
        if (resid != AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID) {
            ret = CONTROL_BAD_COMMAND;
            payload[-1] = ret;
            return ret;
        }
        fixed_delay_aec_capture_probe_t probe;
        fixed_delay_aec_capture_get_probe(&probe);
        memcpy(payload, &probe, sizeof(probe));
#else
        ret = CONTROL_BAD_COMMAND;
#endif
        payload[-1] = ret;
        return ret;
    }

    if (cmd_id == AUDIO_PIPELINE_SETTINGS_CMD_GET_FIXED_DELAY_IC_VNR_CAPTURE_STATUS) {
#if ON_TILE(0)
        if (resid != AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID) {
            ret = CONTROL_BAD_COMMAND;
            payload[-1] = ret;
            return ret;
        }
        fixed_delay_ic_vnr_capture_get_status(
            (fixed_delay_ic_vnr_capture_status_t *)payload);
#else
        ret = CONTROL_BAD_COMMAND;
#endif
        payload[-1] = ret;
        return ret;
    }

    if (cmd_id == AUDIO_PIPELINE_SETTINGS_CMD_GET_FIXED_DELAY_IC_VNR_CAPTURE_CHUNK) {
#if ON_TILE(0)
        if (resid != AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID) {
            ret = CONTROL_BAD_COMMAND;
            payload[-1] = ret;
            return ret;
        }
        fixed_delay_ic_vnr_capture_chunk_t chunk;
        fixed_delay_ic_vnr_capture_get_selected_chunk(&chunk);
        memcpy(payload, &chunk, sizeof(chunk));
#else
        ret = CONTROL_BAD_COMMAND;
#endif
        payload[-1] = ret;
        return ret;
    }

    if (cmd_id == AUDIO_PIPELINE_SETTINGS_CMD_GET_FIXED_DELAY_IC_VNR_CAPTURE_PROBE) {
#if ON_TILE(0)
        if (resid != AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID) {
            ret = CONTROL_BAD_COMMAND;
            payload[-1] = ret;
            return ret;
        }
        fixed_delay_ic_vnr_capture_probe_t probe;
        fixed_delay_ic_vnr_capture_get_probe(&probe);
        memcpy(payload, &probe, sizeof(probe));
#else
        ret = CONTROL_BAD_COMMAND;
#endif
        payload[-1] = ret;
        return ret;
    }
#endif

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

#if appconfAUDIO_PIPELINE_DEVELOPMENT_DEBUG
    if (CONTROL_CMD_CLEAR_READ(cmd) ==
        AUDIO_PIPELINE_SETTINGS_CMD_ARM_FIXED_DELAY_AEC_CAPTURE) {
#if ON_TILE(1)
        fixed_delay_aec_capture_arm_t arm;

        if (resid != AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID) {
            return CONTROL_BAD_RESOURCE;
        }
        memcpy(&arm, payload, sizeof(arm));
        fixed_delay_aec_capture_arm(&arm);
        return ret;
#else
        return CONTROL_BAD_COMMAND;
#endif
    }

    if (CONTROL_CMD_CLEAR_READ(cmd) ==
        AUDIO_PIPELINE_SETTINGS_CMD_SELECT_FIXED_DELAY_AEC_CAPTURE_CHUNK) {
#if ON_TILE(1)
        fixed_delay_aec_capture_chunk_select_t select;

        if (resid != AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID) {
            return CONTROL_BAD_RESOURCE;
        }
        memcpy(&select, payload, sizeof(select));
        if (fixed_delay_aec_capture_select_chunk(select.chunk_index) != 0) {
            return SERVICER_WRONG_PAYLOAD;
        }
        return ret;
#else
        return CONTROL_BAD_COMMAND;
#endif
    }

    if (CONTROL_CMD_CLEAR_READ(cmd) ==
        AUDIO_PIPELINE_SETTINGS_CMD_ARM_FIXED_DELAY_IC_VNR_CAPTURE) {
#if ON_TILE(0)
        fixed_delay_ic_vnr_capture_arm_t arm;

        if (resid != AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID) {
            return CONTROL_BAD_RESOURCE;
        }
        memcpy(&arm, payload, sizeof(arm));
        fixed_delay_ic_vnr_capture_arm(&arm);
        return ret;
#else
        return CONTROL_BAD_COMMAND;
#endif
    }

    if (CONTROL_CMD_CLEAR_READ(cmd) ==
        AUDIO_PIPELINE_SETTINGS_CMD_SELECT_FIXED_DELAY_IC_VNR_CAPTURE_CHUNK) {
#if ON_TILE(0)
        fixed_delay_ic_vnr_capture_chunk_select_t select;

        if (resid != AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID) {
            return CONTROL_BAD_RESOURCE;
        }
        memcpy(&select, payload, sizeof(select));
        if (fixed_delay_ic_vnr_capture_select_chunk(select.chunk_index) != 0) {
            return SERVICER_WRONG_PAYLOAD;
        }
        return ret;
#else
        return CONTROL_BAD_COMMAND;
#endif
    }
#endif

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
    servicer->res_info[0].command_map.num_commands =
        ARRAY_LENGTH(audio_pipeline_mic_settings_cmd_map);
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
    servicer->res_info[0].command_map.num_commands =
        ARRAY_LENGTH(audio_pipeline_speaker_settings_cmd_map);
    servicer->res_info[0].command_map.commands = audio_pipeline_speaker_settings_cmd_map;

    servicer->res_info[1].resource = AUDIO_PIPELINE_MIC_INPUT_SETTINGS_RESID;
    servicer->res_info[1].command_map.num_commands =
        ARRAY_LENGTH(audio_pipeline_mic_input_settings_cmd_map);
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
    control_ret_t dc_ret;
    int i;

    xassert(servicer != NULL);
    xassert(audio_ctx != NULL);

    resources = pvPortMalloc(servicer->num_resources * sizeof(control_resid_t));
    xassert(resources != NULL);
    for (i = 0; i < servicer->num_resources; i++) {
        resources[i] = servicer->res_info[i].resource;
    }

    dc_ret = device_control_servicer_register(&servicer_ctx,
                                              servicer_reg_ctx->device_control_ctx,
                                              servicer_reg_ctx->device_control_ctx_count,
                                              resources,
                                              servicer->num_resources);
    xassert(dc_ret == CONTROL_SUCCESS);

    vPortFree(resources);

    for (;;) {
        (void) device_control_servicer_cmd_recv(&servicer_ctx,
                                                audio_pipeline_servicer_read_cmd,
                                                audio_pipeline_servicer_write_cmd,
                                                audio_ctx,
                                                RTOS_OSAL_WAIT_FOREVER);
    }
}
