#pragma once

/* GPIO and DFU are always registered; the LED servicer is board-configurable. */
#define APP_DEVICE_CTRL_TOTAL_SERVICER_COUNT (2 + appconfLED_RING)
