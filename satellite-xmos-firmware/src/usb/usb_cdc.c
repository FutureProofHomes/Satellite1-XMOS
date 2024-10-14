#include "usb_cdc.h"
#include <stdio.h>
#include <stdarg.h>

int cdc_printf(const char *format, ...) {
    // Check if the USB CDC interface is ready
    if (!tud_cdc_connected()) {
        return 0;  // Return early if not connected
    }

    char buffer[128];  // Buffer to store the formatted output
    va_list args;
    va_start(args, format);
    int len = vsnprintf(buffer, sizeof(buffer), format, args);  // Format the string
    va_end(args);

    if (len > 0) {
        tud_cdc_write(buffer, len);  // Send formatted output through USB CDC
        tud_cdc_write_flush();       // Ensure data is sent immediately
    }

    return len;  // Return the number of characters sent
}

// Callback when CDC data is received from the host
void tud_cdc_rx_cb(uint8_t itf) {
    char buf[64];

    // Read data from the host
    uint32_t count = tud_cdc_read(buf, sizeof(buf));

    // Echo back to the host
    tud_cdc_write(buf, count);
    tud_cdc_write_flush();
}


