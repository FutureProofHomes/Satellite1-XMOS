define print_rtos_contexts
  printf "=== RTOS Context Dumps ===\n\n"

  printf "-- intertile_ctx --\n"
  p *intertile_ctx

  printf "\n-- intertile_usb_audio_ctx --\n"
  p *intertile_usb_audio_ctx

  printf "\n-- qspi_flash_ctx --\n"
  p *qspi_flash_ctx

  printf "\n-- gpio_ctx_t0 --\n"
  p *gpio_ctx_t0

  printf "\n-- gpio_ctx_t1 --\n"
  p *gpio_ctx_t1

  printf "\n-- mic_array_ctx --\n"
  p *mic_array_ctx

  printf "\n-- i2s_ctx --\n"
  p *i2s_ctx

  printf "\n-- spi_slave_ctx --\n"
  p *spi_slave_ctx

  printf "\n-- dfu_image_ctx --\n"
  p *dfu_image_ctx

  printf "\n-- ws2812_ctx --\n"
  p *ws2812_ctx

  printf "\n-- device_control_spi_ctx --\n"
  p *device_control_spi_ctx

  printf "\n-- device_control_gpio_ctx --\n"
  p *device_control_gpio_ctx
end

# Run it
print_rtos_contexts
