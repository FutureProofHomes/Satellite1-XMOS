#include <string.h>
#include "debug_print.h"
#include "servicer.h"
#include "audio_cfg_servicer.h"
#include "FreeRTOS.h"
#include "audio_pipeline_control/audio_pipeline_control_settings.h"

#include "platform/platform_conf.h"

static control_cmd_info_t audio_cfg_servicer_cmd_map[] = {
    { CFG_SERVICER_CMD_MIC_LEFT_SELECT,  1, sizeof(uint8_t), CMD_READ_WRITE  },
    { CFG_SERVICER_CMD_MIC_RIGHT_SELECT,  1, sizeof(uint8_t), CMD_READ_WRITE  },
};

static uint8_t clamp_channel_select(uint8_t channel)
{
    if (channel > AUDIO_PIPELINE_OUTPUT_CHANNEL_INDEX_MAX) {
        return AUDIO_PIPELINE_OUTPUT_CHANNEL_INDEX_MAX;
    }

    return channel;
}

static void update_mic_output_channel_map(device_control_audio_cfg_ctx_t *ctx)
{
    mic_output_pipeline_settings_t *settings;

    xassert(ctx->mic_output_settings != NULL);

    settings = &ctx->mic_output_settings->pending;
    if (settings->pack_extra_upsample_channels) {
        settings->upsample_channel_map[0] = ctx->mic_out_ch_select.left;
        settings->upsample_channel_map[1] = ctx->mic_out_ch_select.left;
        settings->upsample_channel_map[2] = ctx->mic_out_ch_select.left;
        settings->upsample_channel_map[3] = ctx->mic_out_ch_select.right;
        settings->upsample_channel_map[4] = ctx->mic_out_ch_select.right;
        settings->upsample_channel_map[5] = ctx->mic_out_ch_select.right;
    } else {
        settings->i2s_channel_map[0] = ctx->mic_out_ch_select.left;
        settings->i2s_channel_map[1] = ctx->mic_out_ch_select.right;
    }

    ctx->mic_output_settings->active = *settings;
    ctx->mic_output_settings->pending_valid = 1;
}

//-----------------Servicer read write callback functions-----------------------//
DEVICE_CONTROL_CALLBACK_ATTR
static control_ret_t audio_cfg_servicer_read_cmd(control_resid_t resid, control_cmd_t cmd, uint8_t *payload, size_t payload_len, void *app_data)
{
    control_ret_t ret = CONTROL_SUCCESS;
    device_control_audio_cfg_ctx_t *ctx = (device_control_audio_cfg_ctx_t*) app_data;
    servicer_t *servicer = ctx->servicer;

    // For read commands, payload[0] is reserved from status. So payload_len is one more than the payload_len stored in the resource command map
    payload_len -= 1;
    uint8_t *payload_ptr = &payload[1]; //Excluding the status byte, which is updated later.

    debug_printf("Audio config servicer on tile %d received READ command %02x for resid %02x\n\t", THIS_XCORE_TILE, cmd, resid);
    debug_printf("The command is requesting %d bytes\n\t", payload_len);


    control_resource_info_t *current_res_info = get_res_info(resid, servicer);
    xassert(current_res_info != NULL); // This should never happen
    control_cmd_info_t *current_cmd_info;
    ret = validate_cmd(&current_cmd_info, current_res_info, cmd, payload_ptr, payload_len);
    if(ret != CONTROL_SUCCESS)
    {
        payload[0] = ret; // Update status in byte 0
        return ret;
    }
    
    // Handle command
    uint8_t cmd_id = CONTROL_CMD_CLEAR_READ(cmd);
    switch (cmd_id)
    {
    case CFG_SERVICER_CMD_MIC_LEFT_SELECT:
        {
          debug_printf("CFG_SERVICER_CMD_MIC_LEFT_SELECT: %d\n", ctx->mic_out_ch_select.left);
          payload[1] = ctx->mic_out_ch_select.left;
          payload[0] = CONTROL_SUCCESS;
          return CONTROL_SUCCESS;
        }
    
    case CFG_SERVICER_CMD_MIC_RIGHT_SELECT:
        {
          debug_printf("CFG_SERVICER_CMD_MIC_RIGHT_SELECT: %d\n", ctx->mic_out_ch_select.right);
          payload[1] = ctx->mic_out_ch_select.right;
          payload[0] = CONTROL_SUCCESS;
          return CONTROL_SUCCESS;
        }
    
    default:
        {
          debug_printf("CFG_SERVICER_CMD UNHANDLED COMMAND!!!\n");
          ret = CONTROL_BAD_COMMAND;
          payload[0] = ret;
          return ret;
        }
    }
    return CONTROL_ERROR;
}

DEVICE_CONTROL_CALLBACK_ATTR
static control_ret_t audio_cfg_servicer_write_cmd(control_resid_t resid, control_cmd_t cmd, const uint8_t *payload, size_t payload_len, void *app_data)
{
    control_ret_t ret = CONTROL_SUCCESS;
    device_control_audio_cfg_ctx_t *ctx = (device_control_audio_cfg_ctx_t*) app_data;
    servicer_t *servicer = ctx->servicer;

    debug_printf("Audio config servicer on tile %d received WRITE command %02x for resid %02x\n\t", THIS_XCORE_TILE, cmd, resid);
    debug_printf("The command has %d bytes\n\t", payload_len);

    control_resource_info_t *current_res_info = get_res_info(resid, servicer);
    xassert(current_res_info != NULL);
    control_cmd_info_t *current_cmd_info;
    ret = validate_cmd(&current_cmd_info, current_res_info, cmd, payload, payload_len);
    if(ret != CONTROL_SUCCESS)
    {
        debug_printf("Validation of command failed! error: %d\n", ret);
        return ret;
    }
    
    //handle command
    uint8_t cmd_id = CONTROL_CMD_CLEAR_READ(cmd);

    switch (cmd_id)
    {
    case CFG_SERVICER_CMD_MIC_LEFT_SELECT:
    {
        debug_printf("CFG_SERVICER_CMD_MIC_LEFT_SELECT: %d\n", payload[0]);
        ctx->mic_out_ch_select.left = clamp_channel_select(payload[0]);
        update_mic_output_channel_map(ctx);
        break;
    }
    case CFG_SERVICER_CMD_MIC_RIGHT_SELECT:
    {        
        debug_printf("CFG_SERVICER_CMD_MIC_RIGHT_SELECT: %d\n", payload[0]);
        ctx->mic_out_ch_select.right = clamp_channel_select(payload[0]);
        update_mic_output_channel_map(ctx);
        break;
    }
    default:
        debug_printf("CFG_SERVICER UNHANDLED COMMAND!!!\n");
        ret = CONTROL_BAD_COMMAND;
        break;
    }

    return ret;
}




void audio_cfg_servicer_task(void *args) {
    device_control_servicer_t servicer_ctx;
    
    device_control_audio_cfg_ctx_t *ctx = (device_control_audio_cfg_ctx_t*) args;
    servicer_t *servicer = ctx->servicer;
    
    xassert(servicer != NULL);
    
    control_resid_t *resources = (control_resid_t*)pvPortMalloc(servicer->num_resources * sizeof(control_resid_t));
    for(int i=0; i<servicer->num_resources; i++)
    {
        resources[i] = servicer->res_info[i].resource;
    }

    control_ret_t dc_ret;
    debug_printf("Calling device_control_servicer_register(), servicer ID %d, on tile %d, core %d.\n", servicer->id, THIS_XCORE_TILE, rtos_core_id_get());

    dc_ret = device_control_servicer_register(&servicer_ctx,
                                            ctx->device_control_ctx,
                                            ctx->device_control_ctx_count,
                                            resources, servicer->num_resources);
    debug_printf("Out of device_control_servicer_register(), servicer ID %d, on tile %d. servicer_ctx address = 0x%x\n", servicer->id, THIS_XCORE_TILE, &servicer_ctx);

    vPortFree(resources);

    for(;;){
        device_control_servicer_cmd_recv(&servicer_ctx, audio_cfg_servicer_read_cmd, audio_cfg_servicer_write_cmd, ctx, RTOS_OSAL_WAIT_FOREVER);
    }
}

void audio_cfg_servicer_init(device_control_audio_cfg_ctx_t *ctx,
                             mic_output_pipeline_settings_runtime_t *mic_output_settings){
    static servicer_t servicer;
    static control_resource_info_t servicer_res_info[AUDIO_CFG_SERVICER_NUM_RESOURCES];
    
    ctx->servicer = &servicer;
    
    memset(&servicer, 0, sizeof(servicer_t));
    /* Deprecated: use AUDIO_PIPELINE_MIC_OUTPUT_SETTINGS_RESID (230) instead. */
    servicer.id = AUDIO_CFG_SERVICER_RESID;
    servicer.start_io = 0;
    servicer.num_resources = AUDIO_CFG_SERVICER_NUM_RESOURCES;
    
    servicer.res_info = &servicer_res_info[0];
    servicer.res_info[0].resource = AUDIO_CFG_SERVICER_RESID; 
    servicer.res_info[0].command_map.num_commands = NUM_CFG_SERVICER_RESID_CMDS;
    servicer.res_info[0].command_map.commands = audio_cfg_servicer_cmd_map; 
    
    ctx->mic_output_settings = mic_output_settings;
    if (mic_output_settings != NULL) {
        ctx->mic_out_ch_select.left =
            mic_output_settings->active.i2s_channel_map[0];
        ctx->mic_out_ch_select.right =
            mic_output_settings->active.i2s_channel_map[1];
    } else {
        ctx->mic_out_ch_select.left = 7;
        ctx->mic_out_ch_select.right = 5;
    }
}

void audio_cfg_servicer_start(device_control_audio_cfg_ctx_t *ctx, device_control_t **device_control_ctx, size_t device_control_ctx_count ){
    ctx->device_control_ctx = device_control_ctx;
    ctx->device_control_ctx_count = device_control_ctx_count;
    
    xTaskCreate(
        audio_cfg_servicer_task,
        "AudioCfg servicer",
        RTOS_THREAD_STACK_SIZE(audio_cfg_servicer_task),
        ctx,
        appconfDEVICE_CONTROL_SPI_PRIORITY-1,
        NULL
    );
}
