#pragma once

#include "servicer.h"

#define GPIO_CONTROLLER_SERVICER_RESID        (250)
#define GPIO_CONTROLLER_SERVICER_RESID_PORTA  (252)
#define GPIO_CONTROLLER_SERVICER_RESID_PORTB  (254)
#define NUM_RESOURCES_GPIO_SERVICER           (  3)

#define GPIO_CTRL_PORT_A   PORT_LEDS
#define GPIO_CTRL_PORT_B   PORT_BUTTONS

enum gpio_servicer_res_port_map
{
  GPIO_CTRL_RES_IDX_PORT_A  = 0,
  GPIO_CTRL_RES_IDX_PORT_B,
  NUM_OF_GPIO_CTRL_PORTS
};


typedef struct {
    servicer_t  *servicer;
    rtos_gpio_t *gpio_ctx;    
}gpio_servicer_ctx_t;



/**
 * @brief GPIO servicer task.
 *
 * This task handles GPIO commands from the device control interface and relays
 * them to the internal GPIO cntrl.
 *
 * \param args      Pointer to the Servicer's state data structure
 */
void gpio_servicer(void *args);

// Servicer initialization functions
/**
 * @brief GPIO servicer initialisation function.
 * \param servicer      Pointer to the Servicer's state data structure
 */
void gpio_servicer_init(servicer_t *servicer );

