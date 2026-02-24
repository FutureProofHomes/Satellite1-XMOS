#if BUILTIN_TESTS_SPI_ECHO_SERVICER

#include <string.h>
#include "debug_print.h"
#include "servicer.h"
#include "spi_echo_servicer.h"
#include "FreeRTOS.h"

#include "platform/platform_conf.h"

#define SPI_ECHO_BUFFER_LEN 128

static uint8_t data_buffer[SPI_ECHO_BUFFER_LEN];

static control_cmd_info_t spi_echo_servicer_cmd_map[] = {
    { SPI_ECHO_SERVICER_CMD_SET,  SPI_ECHO_BUFFER_LEN, sizeof(uint8_t), CMD_WRITE_ONLY  },
    { SPI_ECHO_SERVICER_CMD_GET,  SPI_ECHO_BUFFER_LEN, sizeof(uint8_t), CMD_READ_ONLY  },
};


//-----------------Servicer read write callback functions-----------------------//
DEVICE_CONTROL_CALLBACK_ATTR
static control_ret_t spi_echo_servicer_read_cmd(control_resid_t resid, control_cmd_t cmd, uint8_t *payload, size_t payload_len, void *app_data)
{
    control_ret_t ret = CONTROL_SUCCESS;
    spi_echo_servicer_ctx_t *ctx = (spi_echo_servicer_ctx_t*) app_data;
    servicer_t *servicer = ctx->servicer;

    // For read commands, payload[0] is reserved from status. So payload_len is one more than the payload_len stored in the resource command map
    payload_len -= 1;
    uint8_t *payload_ptr = &payload[1]; //Excluding the status byte, which is updated later.

    debug_printf("SPI echo servicer on tile %d received READ command %02x for resid %02x\n\t", THIS_XCORE_TILE, cmd, resid);
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
    case SPI_ECHO_SERVICER_CMD_GET:
        {
          payload[0] = CONTROL_SUCCESS;
          memcpy(payload+1, data_buffer, SPI_ECHO_BUFFER_LEN); 
          return CONTROL_SUCCESS;
        }
    
    default:
        {
          debug_printf("SPI_ECHO_SERVICER_CMD UNHANDLED COMMAND!!!\n");
          ret = CONTROL_BAD_COMMAND;
          payload[0] = ret;
          return ret;
        }
    }
    return CONTROL_ERROR;
}

DEVICE_CONTROL_CALLBACK_ATTR
static control_ret_t spi_echo_servicer_write_cmd(control_resid_t resid, control_cmd_t cmd, const uint8_t *payload, size_t payload_len, void *app_data)
{
    control_ret_t ret = CONTROL_SUCCESS;
    spi_echo_servicer_ctx_t *ctx = (spi_echo_servicer_ctx_t*) app_data;
    servicer_t *servicer = ctx->servicer;

    debug_printf("SPI echo servicer on tile %d received WRITE command %02x for resid %02x\n\t", THIS_XCORE_TILE, cmd, resid);
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
    case SPI_ECHO_SERVICER_CMD_SET:
    {
        memcpy(data_buffer, payload, SPI_ECHO_BUFFER_LEN); 
        break;
    }
    
    default:
        debug_printf("SPI_ECHO_SERVICER UNHANDLED COMMAND!!!\n");
        ret = CONTROL_BAD_COMMAND;
        break;
    }

    return ret;
}




void spi_echo_servicer_task(void *args) {
    device_control_servicer_t servicer_ctx;
    
    spi_echo_servicer_ctx_t *ctx = (spi_echo_servicer_ctx_t*) args;
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
        device_control_servicer_cmd_recv(&servicer_ctx, spi_echo_servicer_read_cmd, spi_echo_servicer_write_cmd, ctx, RTOS_OSAL_WAIT_FOREVER);
    }
}

void spi_echo_servicer_init(spi_echo_servicer_ctx_t *ctx){
    static servicer_t servicer;
    static control_resource_info_t servicer_res_info[SPI_ECHO_SERVICER_NUM_RESOURCES];
    
    ctx->servicer = &servicer;
    
    memset(&servicer, 0, sizeof(servicer_t));
    servicer.id = SPI_ECHO_SERVICER_RESID;
    servicer.start_io = 0;
    servicer.num_resources = SPI_ECHO_SERVICER_NUM_RESOURCES;
    
    servicer.res_info = &servicer_res_info[0];
    servicer.res_info[0].resource = SPI_ECHO_SERVICER_RESID; 
    servicer.res_info[0].command_map.num_commands = NUM_SPI_ECHO_SERVICER_RESID_CMDS;
    servicer.res_info[0].command_map.commands = spi_echo_servicer_cmd_map; 
    
    memset(data_buffer, 0, SPI_ECHO_BUFFER_LEN);
}

void spi_echo_servicer_start(spi_echo_servicer_ctx_t *ctx, device_control_t **device_control_ctx, size_t device_control_ctx_count ){
    ctx->device_control_ctx = device_control_ctx;
    ctx->device_control_ctx_count = device_control_ctx_count;
    
    xTaskCreate(
        spi_echo_servicer_task,
        "echo servicer",
        RTOS_THREAD_STACK_SIZE(spi_echo_servicer_task),
        ctx,
        appconfDEVICE_CONTROL_SPI_PRIORITY-1,
        NULL
    );
}


#endif