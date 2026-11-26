#include "debug_print.h"

#include <platform.h>
#include <stdint.h>
#include <string.h>
#include <xassert.h>

#include "FreeRTOS.h"
#include "app_conf.h"

#include "doa_cmds.h"
#include "doa_estimator.h"
#include "doa_servicer.h"
#include "beamforming/sat1_beamformer.h"
#include "servicer.h"

static control_cmd_info_t doa_servicer_cmd_map[] = {
    { DOA_SERVICER_CMD_READ_STATE, DOA_SERVICER_STATE_NUM_VALUES, sizeof(uint8_t), CMD_READ_ONLY },
    { DOA_SERVICER_CMD_READ_DIAGNOSTICS, DOA_SERVICER_DIAGNOSTICS_NUM_VALUES, sizeof(uint8_t), CMD_READ_ONLY },
    { DOA_SERVICER_CMD_SET_CONTROL, DOA_SERVICER_CONTROL_NUM_VALUES, sizeof(uint8_t), CMD_WRITE_ONLY },
    { DOA_SERVICER_CMD_READ_CAPABILITIES, DOA_SERVICER_CAPABILITIES_NUM_VALUES, sizeof(uint8_t), CMD_READ_ONLY },
    { DOA_SERVICER_CMD_SET_HOST_HINTS, DOA_SERVICER_CONTROL_NUM_VALUES, sizeof(uint8_t), CMD_WRITE_ONLY },
};

static void store_u16_le(uint8_t *dst, uint16_t value)
{
    dst[0] = (uint8_t)(value & 0xFF);
    dst[1] = (uint8_t)((value >> 8) & 0xFF);
}

static void store_u32_le(uint8_t *dst, uint32_t value)
{
    dst[0] = (uint8_t)(value & 0xFF);
    dst[1] = (uint8_t)((value >> 8) & 0xFF);
    dst[2] = (uint8_t)((value >> 16) & 0xFF);
    dst[3] = (uint8_t)((value >> 24) & 0xFF);
}

DEVICE_CONTROL_CALLBACK_ATTR
static control_ret_t doa_servicer_read_cmd(control_resid_t resid,
                                           control_cmd_t cmd,
                                           uint8_t *payload,
                                           size_t payload_len,
                                           void *app_data)
{
    control_ret_t ret = CONTROL_SUCCESS;
    servicer_t *servicer = (servicer_t *)app_data;

    payload_len -= 1;
    uint8_t *payload_ptr = &payload[1];

    control_resource_info_t *current_res_info = get_res_info(resid, servicer);
    xassert(current_res_info != NULL);

    control_cmd_info_t *current_cmd_info;
    ret = validate_cmd(&current_cmd_info, current_res_info, cmd, payload_ptr, payload_len);
    if (ret != CONTROL_SUCCESS) {
        payload[0] = ret;
        return ret;
    }

    switch (CONTROL_CMD_CLEAR_READ(cmd)) {
    case DOA_SERVICER_CMD_READ_CAPABILITIES:
        payload_ptr[0] = 'S';
        payload_ptr[1] = '1';
        payload_ptr[2] = 'D';
        payload_ptr[3] = 1;
        store_u32_le(&payload_ptr[4], appconfSAT1_SPEECH_FRONTEND
            ? DOA_SERVICER_CAPABILITY_HOST_HINTS : 0);
        payload[0] = CONTROL_SUCCESS;
        return CONTROL_SUCCESS;

    case DOA_SERVICER_CMD_READ_STATE:
    {
        doa_estimator_state_t state;
#if appconfSAT1_SPEECH_FRONTEND
        doa_estimator_get_observation(&state);
#else
        doa_estimator_get_state(&state);
#endif

        store_u16_le(&payload_ptr[0], (uint16_t)state.sample_delay);
        payload_ptr[2] = state.confidence;
        payload_ptr[3] = state.flags;
        store_u32_le(&payload_ptr[4], state.energy);
        store_u32_le(&payload_ptr[8], state.frame_counter);
        store_u16_le(&payload_ptr[12], (uint16_t)state.vertical_delay);
        payload_ptr[14] = state.angle_index;
        payload_ptr[15] = 0;
        store_u32_le(&payload_ptr[16], state.mic_energy[0]);
        store_u32_le(&payload_ptr[20], state.mic_energy[1]);
        store_u32_le(&payload_ptr[24], state.mic_energy[2]);
        store_u32_le(&payload_ptr[28], state.mic_energy[3]);

        payload[0] = CONTROL_SUCCESS;
        return CONTROL_SUCCESS;
    }

    case DOA_SERVICER_CMD_READ_DIAGNOSTICS:
    {
        doa_estimator_diagnostics_t doa = {0};
        sat1_beamformer_diagnostics_t beam;
        memset(&beam, 0, sizeof(beam));
        doa_estimator_get_diagnostics(&doa);
        sat1_beamformer_get_diagnostics(&beam);

        store_u16_le(&payload_ptr[0],
                     (uint16_t)doa.steering_delay_q8);
        store_u16_le(&payload_ptr[2],
                     (uint16_t)doa.vertical_steering_delay_q8);
        store_u32_le(&payload_ptr[4], doa.noise_floor_energy);
        payload_ptr[8] = doa.signal_active;
        payload_ptr[9] = doa.control_flags;
        payload_ptr[10] = doa.mode_flags;
        payload_ptr[11] = beam.active_mic_mask != 0
                              ? beam.active_mic_mask
                              : doa.active_mic_mask;
        for (size_t mic = 0; mic < SAT1_BEAMFORMER_MIC_COUNT; mic++) {
            store_u16_le(&payload_ptr[12 + (mic * 2)],
                         (uint16_t)beam.current_delay_q8[mic]);
            store_u16_le(&payload_ptr[20 + (mic * 2)],
                         beam.mic_gain_q15[mic]);
            payload_ptr[28 + mic] = beam.mic_health_flags[mic];
            store_u32_le(&payload_ptr[32 + (mic * 4)],
                         beam.mic_level[mic]);
        }

        payload[0] = CONTROL_SUCCESS;
        return CONTROL_SUCCESS;
    }

    default:
        payload[0] = CONTROL_BAD_COMMAND;
        return CONTROL_BAD_COMMAND;
    }
}

DEVICE_CONTROL_CALLBACK_ATTR
static control_ret_t doa_servicer_write_cmd(control_resid_t resid,
                                            control_cmd_t cmd,
                                            const uint8_t *payload,
                                            size_t payload_len,
                                            void *app_data)
{
    servicer_t *servicer = (servicer_t *)app_data;
    control_resource_info_t *current_res_info = get_res_info(resid, servicer);
    if (current_res_info == NULL) {
        return CONTROL_BAD_RESOURCE;
    }

    control_cmd_info_t *current_cmd_info;
    control_ret_t ret = validate_cmd(&current_cmd_info,
                                     current_res_info,
                                     cmd,
                                     payload,
                                     payload_len);
    if (ret != CONTROL_SUCCESS) {
        return ret;
    }

    switch (CONTROL_CMD_CLEAR_READ(cmd)) {
    case DOA_SERVICER_CMD_SET_CONTROL:
        doa_estimator_set_control(payload[0]);
        return CONTROL_SUCCESS;
    case DOA_SERVICER_CMD_SET_HOST_HINTS:
#if appconfSAT1_SPEECH_FRONTEND
        doa_estimator_set_host_hints(payload[0]);
        return CONTROL_SUCCESS;
#else
        return CONTROL_BAD_COMMAND;
#endif
    default:
        return CONTROL_BAD_COMMAND;
    }
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
    servicer->res_info[0].command_map.commands = doa_servicer_cmd_map;
}

void doa_servicer(void *args)
{
    device_control_servicer_t servicer_ctx;
    servicer_register_ctx_t *servicer_reg_ctx = (servicer_register_ctx_t *)args;
    servicer_t *servicer = servicer_reg_ctx->servicer;

    xassert(servicer != NULL);

    control_resid_t resources[NUM_RESOURCES_DOA];
    for (int i = 0; i < servicer->num_resources; i++) {
        resources[i] = servicer->res_info[i].resource;
    }

    (void)device_control_servicer_register(&servicer_ctx,
                                           servicer_reg_ctx->device_control_ctx,
                                           servicer_reg_ctx->device_control_ctx_count,
                                           resources,
                                           servicer->num_resources);

    for (;;) {
        device_control_servicer_cmd_recv(&servicer_ctx,
                                         doa_servicer_read_cmd,
                                         doa_servicer_write_cmd,
                                         servicer,
                                         RTOS_OSAL_WAIT_FOREVER);
    }
}
