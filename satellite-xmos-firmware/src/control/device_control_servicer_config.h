#pragma once

#ifndef appconfAUDIO_CFG_SERVICER_COMPAT_ENABLED
#define appconfAUDIO_CFG_SERVICER_COMPAT_ENABLED 1
#endif

/*
 * Base SQ66/SATELLITE1 servicers under appconfDEVICE_CTRL_SPI:
 * - GPIO servicer
 * - DFU servicer
 * - Audio pipeline tile0 servicer (mic output)
 * - Audio pipeline tile1 servicer (speaker + mic input)
 */
#define APP_DEVICE_CTRL_BASE_SERVICER_COUNT 4

#define APP_DEVICE_CTRL_TOTAL_SERVICER_COUNT \
    (APP_DEVICE_CTRL_BASE_SERVICER_COUNT + \
     appconfAUDIO_CFG_SERVICER_COMPAT_ENABLED + \
     appconfLED_RING + \
     !!(BUILTIN_TESTS_SPI_ECHO_SERVICER))
