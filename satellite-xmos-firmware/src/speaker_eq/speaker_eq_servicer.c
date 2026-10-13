#include "speaker_eq/speaker_eq.h"

#if SPEAKER_EQ_ACTIVE

#include <xcore/assert.h>

#include "FreeRTOS.h"
#include "task.h"

#include "platform/platform_conf.h"
#include "rtos_macros.h"
#include "servicer.h"

/* Reads carry a status byte ahead of the payload. */
_Static_assert(SPEAKER_EQ_SLOT_BYTES + 1 <= 253, "EQ slot exceeds the SPI payload limit");

static control_cmd_info_t speaker_eq_cmd_map[] = {
    { SPEAKER_EQ_CMD_GET_INFO, 1, SPEAKER_EQ_INFO_BYTES, CMD_READ_ONLY },
    { SPEAKER_EQ_CMD_GET_STATS, 1, SPEAKER_EQ_STATS_BYTES, CMD_READ_ONLY },
    { SPEAKER_EQ_CMD_SET_ROUTING, 1, SPEAKER_EQ_ROUTING_BYTES, CMD_WRITE_ONLY },
    { SPEAKER_EQ_CMD_SET_SLOT, 1, SPEAKER_EQ_SLOT_BYTES, CMD_WRITE_ONLY },
    { SPEAKER_EQ_CMD_GET_SLOT, 1, SPEAKER_EQ_SLOT_BYTES, CMD_READ_ONLY },
};

static control_resource_info_t speaker_eq_res_info[1];
static servicer_t speaker_eq_servicer_state;

DEVICE_CONTROL_CALLBACK_ATTR
static control_ret_t speaker_eq_servicer_read_cmd(control_resid_t resid, control_cmd_t cmd,
                                                  uint8_t *payload, size_t payload_len,
                                                  void *app_data)
{
    servicer_t *servicer = (servicer_t *)app_data;
    control_resource_info_t *res_info = get_res_info(resid, servicer);
    control_cmd_info_t *cmd_info;
    const uint8_t cmd_id = CONTROL_CMD_CLEAR_READ(cmd);
    uint8_t *data = &payload[1];
    const size_t data_len = payload_len - 1;
    control_ret_t ret;

    xassert(res_info != NULL);
    ret = validate_cmd(&cmd_info, res_info, cmd, data, data_len);
    if (ret == CONTROL_SUCCESS && !speaker_eq_cmd_read(cmd_id, data, data_len)) {
        ret = CONTROL_BAD_COMMAND;
    }
    payload[0] = ret;
    return ret;
}

DEVICE_CONTROL_CALLBACK_ATTR
static control_ret_t speaker_eq_servicer_write_cmd(control_resid_t resid, control_cmd_t cmd,
                                                   const uint8_t *payload, size_t payload_len,
                                                   void *app_data)
{
    servicer_t *servicer = (servicer_t *)app_data;
    control_resource_info_t *res_info = get_res_info(resid, servicer);
    control_cmd_info_t *cmd_info;
    const uint8_t cmd_id = CONTROL_CMD_CLEAR_READ(cmd);
    control_ret_t ret;

    xassert(res_info != NULL);
    ret = validate_cmd(&cmd_info, res_info, cmd, payload, payload_len);
    if (ret != CONTROL_SUCCESS) {
        return ret;
    }
    return speaker_eq_cmd_write(cmd_id, payload, payload_len) ?
           CONTROL_SUCCESS : SERVICER_WRONG_PAYLOAD;
}

static void speaker_eq_servicer(void *arg)
{
    device_control_servicer_t servicer_ctx;
    device_control_t *device_control_ctx[1] = { device_control_spi_ctx };
    const control_resid_t resid = SPEAKER_EQ_RESID;

    (void)arg;
    xassert(device_control_servicer_register(&servicer_ctx, device_control_ctx, 1,
                                             &resid, 1) == CONTROL_SUCCESS);
    for (;;) {
        device_control_servicer_cmd_recv(&servicer_ctx,
                                         speaker_eq_servicer_read_cmd,
                                         speaker_eq_servicer_write_cmd,
                                         &speaker_eq_servicer_state,
                                         RTOS_OSAL_WAIT_FOREVER);
    }
}

void speaker_eq_servicer_start(void)
{
    speaker_eq_servicer_state.id = SPEAKER_EQ_RESID;
    speaker_eq_servicer_state.num_resources = 1;
    speaker_eq_servicer_state.res_info = speaker_eq_res_info;
    speaker_eq_res_info[0].resource = SPEAKER_EQ_RESID;
    speaker_eq_res_info[0].command_map.num_commands =
        sizeof(speaker_eq_cmd_map) / sizeof(speaker_eq_cmd_map[0]);
    speaker_eq_res_info[0].command_map.commands = speaker_eq_cmd_map;

    xassert(xTaskCreate(speaker_eq_servicer,
                        "spk_eq_servicer",
                        RTOS_THREAD_STACK_SIZE(speaker_eq_servicer),
                        NULL,
                        appconfDEVICE_CONTROL_SPI_PRIORITY,
                        NULL) == pdPASS);
}

#endif
