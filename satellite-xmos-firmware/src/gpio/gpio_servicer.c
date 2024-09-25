#include "debug_print.h"

#include <stdio.h>
#include <string.h>
#include <platform.h>
#include <xassert.h>

#include "platform/platform_conf.h"
#include "servicer.h"
#include "gpio_servicer.h"

#include "gpio_cmds.h"
#include "rtos_gpio.h"

#include "FreeRTOS.h"

//#include "platform/app_pll_ctrl.h"

#define GPIO_BITMASK (3)


static rtos_gpio_port_id_t gpio_ctrl_ports[NUM_OF_GPIO_CTRL_PORTS]; 
static rtos_gpio_t *gpio_servicer_gpio_ctx = NULL;

static control_cmd_info_t gpio_controller_servicer_resid_cmd_map[] = {
    { GPIO_CONTROLLER_SERVICER_CMD_READ_PORT,  1, sizeof(uint8_t), CMD_READ_ONLY   },
    { GPIO_CONTROLLER_SERVICER_CMD_WRITE_PORT, 1, sizeof(uint8_t), CMD_WRITE_ONLY  },
    { GPIO_CONTROLLER_SERVICER_CMD_SET_PIN,    2, sizeof(uint8_t), CMD_WRITE_ONLY  },
};

//-----------------Servicer read write callback functions-----------------------//
DEVICE_CONTROL_CALLBACK_ATTR
static control_ret_t gpio_servicer_read_cmd(control_resid_t resid, control_cmd_t cmd, uint8_t *payload, size_t payload_len, void *app_data)
{
    control_ret_t ret = CONTROL_SUCCESS;
    servicer_t *servicer = (servicer_t*)app_data;

    // For read commands, payload[0] is reserved from status. So payload_len is one more than the payload_len stored in the resource command map
    payload_len -= 1;
    uint8_t *payload_ptr = &payload[1]; //Excluding the status byte, which is updated later.

    debug_printf("GPIO servicer on tile %d received READ command %02x for resid %02x\n\t", THIS_XCORE_TILE, cmd, resid);
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
    
    rtos_gpio_port_id_t target_port;
    switch( resid ){
        case GPIO_CONTROLLER_SERVICER_RESID_PORTA:
            target_port = gpio_ctrl_ports[GPIO_CTRL_RES_IDX_PORT_A];
            break;
        case GPIO_CONTROLLER_SERVICER_RESID_PORTB:
            target_port = gpio_ctrl_ports[GPIO_CTRL_RES_IDX_PORT_B];
            break;
        default:
            debug_printf("GPIO_CONTROLLER_SERVICER unknown resource!!!\n");
            ret = CONTROL_BAD_RESOURCE;
            payload[0] = ret;
            return ret;  
    }
    
    // Handle command
    uint8_t cmd_id = CONTROL_CMD_CLEAR_READ(cmd);
    switch (cmd_id)
    {
    case GPIO_CONTROLLER_SERVICER_CMD_READ_PORT:
        {
          debug_printf("GPIO_CONTROLLER_SERVICER_RESID_GET_PIN\n");
          payload[1] = rtos_gpio_port_in( gpio_servicer_gpio_ctx, target_port );
          payload[0] = CONTROL_SUCCESS;
          return CONTROL_SUCCESS;
        }

    default:
        {
          debug_printf("GPIO_CONTROLLER_SERVICER UNHANDLED COMMAND!!!\n");
          ret = CONTROL_BAD_COMMAND;
          payload[0] = ret;
          return ret;
        }
    }
    return CONTROL_ERROR;
}

DEVICE_CONTROL_CALLBACK_ATTR
static control_ret_t gpio_servicer_write_cmd(control_resid_t resid, control_cmd_t cmd, const uint8_t *payload, size_t payload_len, void *app_data)
{
    control_ret_t ret = CONTROL_SUCCESS;
    servicer_t *servicer = (servicer_t*)app_data;
    //debug_printf("Device control WRITE. Servicer ID %d\n\t", servicer->id);

    debug_printf("GPIO servicer on tile %d received WRITE command %02x for resid %02x\n\t", THIS_XCORE_TILE, cmd, resid);
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
    
    rtos_gpio_port_id_t target_port;
    switch( resid ){
        case GPIO_CONTROLLER_SERVICER_RESID_PORTA:
            target_port = gpio_ctrl_ports[GPIO_CTRL_RES_IDX_PORT_A];
            break;
        case GPIO_CONTROLLER_SERVICER_RESID_PORTB:
            debug_printf("Writing to PORTB not allowed!!!\n");
            ret = CONTROL_BAD_RESOURCE;
            return ret;  
            //target_port = gpio_ctrl_ports[GPIO_CTRL_RES_IDX_PORT_B];
            break;
        default:
            debug_printf("GPIO_CONTROLLER_SERVICER unknown resource!!!\n");
            ret = CONTROL_BAD_RESOURCE;
            return ret;  
    }
    
    //handle command
    uint8_t cmd_id = CONTROL_CMD_CLEAR_READ(cmd);
    debug_printf("gpio_servicer_write_cmd cmd_id %d.\n", cmd_id);

    switch (cmd_id)
    {
    case GPIO_CONTROLLER_SERVICER_CMD_WRITE_PORT:
    {
        debug_printf("GPIO_CONTROLLER_SERVICER_RESID_WRITE_PORT\n");
        const uint8_t val  = payload[0];
        rtos_gpio_port_out( gpio_servicer_gpio_ctx, target_port, val );
        break;
    }
    case GPIO_CONTROLLER_SERVICER_CMD_SET_PIN:
    {        
        const uint8_t pin  = payload[0];
        const uint8_t val  = payload[1];
        debug_printf("GPIO_CONTROLLER_SERVICER_RESID_SET_PIN pin: %d val: %d\n", payload[0], payload[1]);
        uint8_t port_val = rtos_gpio_port_in( gpio_servicer_gpio_ctx, target_port );
        if ( val ){
            port_val |=  (( val & 1) << pin );
        } else {
            port_val &= ~( 1 << pin );
        }
        rtos_gpio_port_out( gpio_servicer_gpio_ctx, target_port, port_val );
        break;
    }
    default:
        debug_printf("GPIO_CONTROLLER_SERVICER UNHANDLED COMMAND!!!\n");
        ret = CONTROL_BAD_COMMAND;
        break;
    }

    return ret;
}

RTOS_GPIO_ISR_CALLBACK_ATTR
static void gpio_callback(rtos_gpio_t *ctx, void *app_data, rtos_gpio_port_id_t port_id, uint32_t value)
{
    TaskHandle_t task = app_data;
    BaseType_t yield_required = pdFALSE;

    value = (~value) & GPIO_BITMASK;

    xTaskNotifyFromISR(task, value, eSetValueWithOverwrite, &yield_required);

    portYIELD_FROM_ISR(yield_required);
}


void gpio_handler_task( servicer_register_ctx_t *servicer_reg_ctx )
{
    debug_printf("GPIO handler task on tile %d, core %d.\n", THIS_XCORE_TILE, rtos_core_id_get());
    uint32_t value;
    uint32_t gpio_val;
    rtos_gpio_t *gpio_ctx = (rtos_gpio_t *) servicer_reg_ctx->app_data;
    const rtos_gpio_port_id_t gpio_port = rtos_gpio_port(GPIO_CTRL_PORT_B);
        
    rtos_gpio_isr_callback_set(gpio_ctx, gpio_port, gpio_callback, xTaskGetCurrentTaskHandle());
    rtos_gpio_interrupt_enable(gpio_ctx, gpio_port);

    for (;;) {
        xTaskNotifyWait(
                0x00000000UL,    /* Don't clear notification bits on entry */
                0xFFFFFFFFUL,    /* Reset full notification value on exit */
                &value,          /* Pass out notification value into value */
                portMAX_DELAY ); /* Wait indefinitely until next notification */

        gpio_val = rtos_gpio_port_in(gpio_ctx, gpio_port);
        debug_printf("GPIO handler task:  Port B changed to %d.\n", gpio_val );
        device_control_set_resource_status( servicer_reg_ctx->device_control_ctx[0], 0, gpio_val );
        
    }
}






void gpio_servicer_init(servicer_t *servicer)
{
    // Servicer resource info
    static control_resource_info_t gpio_res_info[NUM_RESOURCES_GPIO_SERVICER];

    memset(servicer, 0, sizeof(servicer_t));
    servicer->id = GPIO_CONTROLLER_SERVICER_RESID;
    servicer->start_io = 0;
    servicer->num_resources = NUM_RESOURCES_GPIO_SERVICER;

    servicer->res_info = &gpio_res_info[0];
    // Servicer resource
    servicer->res_info[0].resource = GPIO_CONTROLLER_SERVICER_RESID;
    servicer->res_info[0].command_map.num_commands = NUM_GPIO_CONTROLLER_SERVICER_RESID_CMDS;
    servicer->res_info[0].command_map.commands = gpio_controller_servicer_resid_cmd_map;
    
    servicer->res_info[1].resource = GPIO_CONTROLLER_SERVICER_RESID_PORTA;
    servicer->res_info[1].command_map.num_commands = NUM_GPIO_CONTROLLER_SERVICER_RESID_CMDS;
    servicer->res_info[1].command_map.commands = gpio_controller_servicer_resid_cmd_map;

    servicer->res_info[2].resource = GPIO_CONTROLLER_SERVICER_RESID_PORTB;
    servicer->res_info[2].command_map.num_commands = NUM_GPIO_CONTROLLER_SERVICER_RESID_CMDS;
    servicer->res_info[2].command_map.commands = gpio_controller_servicer_resid_cmd_map;
}

void gpio_servicer(void *args) {
    device_control_servicer_t servicer_ctx;

    servicer_register_ctx_t *servicer_reg_ctx = (servicer_register_ctx_t*)args;
    
    servicer_t *servicer = servicer_reg_ctx->servicer;
    rtos_gpio_t *gpio_ctx = (rtos_gpio_t *) servicer_reg_ctx->app_data;
    
    xassert(servicer != NULL);
    xassert(gpio_ctx != NULL);
    
    gpio_servicer_gpio_ctx = gpio_ctx;
    gpio_ctrl_ports[GPIO_CTRL_RES_IDX_PORT_A] = rtos_gpio_port(GPIO_CTRL_PORT_A); 
    gpio_ctrl_ports[GPIO_CTRL_RES_IDX_PORT_B] = rtos_gpio_port(GPIO_CTRL_PORT_B); 
    
    rtos_gpio_port_enable(gpio_ctx, gpio_ctrl_ports[0]);
    rtos_gpio_port_enable(gpio_ctx, gpio_ctrl_ports[1]);

    control_resid_t *resources = (control_resid_t*)pvPortMalloc(servicer->num_resources * sizeof(control_resid_t));
    for(int i=0; i<servicer->num_resources; i++)
    {
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

    if (GPIO_CTRL_PORT_B != 0) {
        xTaskCreate((TaskFunction_t) gpio_handler_task,
                    "gpio_handler",
                    RTOS_THREAD_STACK_SIZE(gpio_handler_task),
                    servicer_reg_ctx,
                    configMAX_PRIORITIES-1,
                    NULL);
    }
    
    
    for(;;){
        device_control_servicer_cmd_recv(&servicer_ctx, gpio_servicer_read_cmd, gpio_servicer_write_cmd, servicer, RTOS_OSAL_WAIT_FOREVER);
    }
}

