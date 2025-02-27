#include "platform/driver_instances.h"
#include "pcm5122.h"

int pcm5122_init(void)
{
    pcm5122_codec_reset();

    uint8_t err_detect; 
    pcm5122_reg_read(0x25, &err_detect);
    // set 'Ignore Clock Halt Detection'
    err_detect |= (1 << 3);
    // enable Clock Divider Autoset
    err_detect &= ~(1 << 1);
    pcm5122_reg_write(0x25, err_detect);
    
    // set 32bit - I2S
    pcm5122_reg_write(0x28, 3); // 32bits
    
    // 001: The PLL reference clock is BCK
    uint8_t pll_ref; 
    pcm5122_reg_read(0x0D, &pll_ref);
    pll_ref &= ~(7 << 4); 
    pll_ref |=  (1 << 4);
    pcm5122_reg_write(0x0D, pll_ref);

    return 0;
}

int pcm5122_reg_write(uint8_t reg, uint8_t val)
{
    i2c_regop_res_t ret;
    ret = rtos_i2c_master_reg_write(i2c_master_ctx, PCM5122_I2C_DEVICE_ADDR, reg, val);

    if (ret == I2C_REGOP_SUCCESS) {
        return 0;
    } else {
        return -1;
    }
}

int pcm5122_reg_read(uint8_t reg, uint8_t* val)
{
    i2c_regop_res_t ret;
    ret = rtos_i2c_master_reg_read(i2c_master_ctx, PCM5122_I2C_DEVICE_ADDR, reg, val);

    if (ret == I2C_REGOP_SUCCESS) {
        return 0;
    } else {
        return -1;
    }
}



void pcm5122_codec_reset(void)
{
    pcm5122_reg_write(0x01, 0x10);
    pcm5122_wait(20);
    pcm5122_reg_write(0x01, 0x00);
}

void pcm5122_wait(uint32_t wait_ms)
{
    vTaskDelay(pdMS_TO_TICKS(wait_ms));
}

