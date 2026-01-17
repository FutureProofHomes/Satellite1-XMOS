#include "debug_print.h"

#include <string.h>
#include <platform.h>
#include <xassert.h>

#include "doa/doa.h"
#include "doa/doa_cmds.h"
#include "doa/doa_servicer.h"
#include "servicer.h"

#include "FreeRTOS.h"

static control_cmd_info_t doa_servicer_resid_cmd_map[] = {
    { DOA_SERVICER_CMD_GET_RESULT, DOA_SERVICER_CMD_GET_RESULT_NUM_VALUES, sizeof(float), CMD_READ_ONLY },
    { DOA_SERVICER_CMD_GET_CAPS, DOA_SERVICER_CMD_GET_CAPS_NUM_VALUES, sizeof(uint8_t), CMD_READ_ONLY },
    { DOA_SERVICER_CMD_SET_OFFSETS, DOA_SERVICER_CMD_SET_OFFSETS_NUM_VALUES, sizeof(float), CMD_WRITE_ONLY },
};

DEVICE_CONTROL_CALLBACK_ATTR
static control_ret_t doa_servicer_read_cmd(control_resid_t resid, control_cmd_t cmd, uint8_t *payload, size_t payload_len, void *app_data)
{
    control_ret_t ret = CONTROL_SUCCESS;
    servicer_t *servicer = (servicer_t *) app_data;

    payload_len -= 1;
    uint8_t *payload_ptr = &payload[1];

    control_resource_info_t *current_res_info = get_res_info(resid, servicer);
    if (current_res_info == NULL) {
        payload[0] = CONTROL_BAD_RESOURCE;
        return CONTROL_BAD_RESOURCE;
    }

    control_cmd_info_t *current_cmd_info;
    ret = validate_cmd(&current_cmd_info, current_res_info, cmd, payload_ptr, payload_len);
    if (ret != CONTROL_SUCCESS) {
        payload[0] = ret;
        return ret;
    }

    uint8_t cmd_id = CONTROL_CMD_CLEAR_READ(cmd);
    switch (cmd_id) {
    case DOA_SERVICER_CMD_GET_RESULT: {
        doa_result_t result;
        float out_vals[2] = {0.0f, 0.0f};
        if (doa_get_latest(&result)) {
            out_vals[0] = result.azimuth_deg;
            out_vals[1] = result.confidence;
        }
        memcpy(payload_ptr, out_vals, sizeof(out_vals));
        payload[0] = CONTROL_SUCCESS;
        break;
    }
    case DOA_SERVICER_CMD_GET_CAPS: {
        payload_ptr[0] = 0xA5;
        payload_ptr[1] = 0x02;
        payload[0] = CONTROL_SUCCESS;
        break;
    }
    default:
        ret = CONTROL_BAD_COMMAND;
        payload[0] = ret;
        break;
    }

    return ret;
}

DEVICE_CONTROL_CALLBACK_ATTR
static control_ret_t doa_servicer_write_cmd(control_resid_t resid, control_cmd_t cmd, const uint8_t *payload, size_t payload_len, void *app_data)
{
    control_ret_t ret = CONTROL_SUCCESS;
    servicer_t *servicer = (servicer_t *) app_data;

    control_resource_info_t *current_res_info = get_res_info(resid, servicer);
    if (current_res_info == NULL) {
        return CONTROL_BAD_RESOURCE;
    }

    control_cmd_info_t *current_cmd_info;
    ret = validate_cmd(&current_cmd_info, current_res_info, cmd, payload, payload_len);
    if (ret != CONTROL_SUCCESS) {
        return ret;
    }

    uint8_t cmd_id = CONTROL_CMD_CLEAR_READ(cmd);
    switch (cmd_id) {
    case DOA_SERVICER_CMD_SET_OFFSETS: {
        float offsets[4];
        memcpy(offsets, payload, sizeof(offsets));
        doa_set_delay_offsets_samples(offsets, 4);
        ret = CONTROL_SUCCESS;
        break;
    }
    default:
        ret = CONTROL_BAD_COMMAND;
        break;
    }

    return ret;
}

void doa_servicer_init(servicer_t *servicer)
{
    static control_resource_info_t doa_res_info[NUM_RESOURCES_DOA];

    memset(servicer, 0, sizeof(servicer_t));
    servicer->id = DOA_SERVICER_RESID;
    servicer->start_io = 0;
    servicer->num_resources = NUM_RESOURCES_DOA;

    servicer->res_info = &doa_res_info[0];
    servicer->res_info[0].resource = DOA_SERVICER_RESID;
    servicer->res_info[0].command_map.num_commands = NUM_DOA_SERVICER_CMDS;
    servicer->res_info[0].command_map.commands = doa_servicer_resid_cmd_map;
}

void doa_servicer(void *args)
{
    device_control_servicer_t servicer_ctx;

    servicer_register_ctx_t *servicer_reg_ctx = (servicer_register_ctx_t *) args;
    servicer_t *servicer = servicer_reg_ctx->servicer;

    xassert(servicer != NULL);

    control_resid_t *resources = (control_resid_t *) pvPortMalloc(servicer->num_resources * sizeof(control_resid_t));
    for (int i = 0; i < servicer->num_resources; i++) {
        resources[i] = servicer->res_info[i].resource;
    }

    control_ret_t dc_ret;
    debug_printf("Calling device_control_servicer_register(), servicer ID %d, on tile %d, core %d.\n", servicer->id, THIS_XCORE_TILE, rtos_core_id_get());

    dc_ret = device_control_servicer_register(&servicer_ctx,
                                              servicer_reg_ctx->device_control_ctx,
                                              1,
                                              resources, servicer->num_resources);
    debug_printf("Out of device_control_servicer_register(), servicer ID %d, on tile %d. servicer_ctx address = 0x%x\n", servicer->id, THIS_XCORE_TILE, &servicer_ctx);

    vPortFree(resources);

    for (;;) {
        device_control_servicer_cmd_recv(&servicer_ctx, doa_servicer_read_cmd, doa_servicer_write_cmd, servicer, RTOS_OSAL_WAIT_FOREVER);
    }
}
