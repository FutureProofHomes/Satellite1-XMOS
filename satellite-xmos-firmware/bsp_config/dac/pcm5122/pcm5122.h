#ifndef PCM5122_H_
#define PCM5122_H_

#include <stdint.h>

// PCM5122 Device I2C Address
#define PCM5122_I2C_DEVICE_ADDR 0x4D

/**
 * Initialize the DAC
 *
 * \returns   0 on success
 *            -1 otherwise
 */
int pcm5122_init(void);

/**
 * User defined function to perform the reg write
 *
 * \returns   0 on success
 *            -1 otherwise
 */
int pcm5122_reg_write(uint8_t reg, uint8_t val);

/**
 * User defined function to perform the reg write
 *
 * \returns   0 on success
 *            -1 otherwise
 */
int pcm5122_reg_read(uint8_t reg, uint8_t *val);


/**
 * User defined function to perform the reset the device
 */
void pcm5122_codec_reset(void);

/**
 * User defined function to perform a wait
 *
 * When called, this function must not return until
 * at least wait_ms milliseconds has passed
 */
void pcm5122_wait(uint32_t wait_ms);


#endif /*PCM5122_H_*/
