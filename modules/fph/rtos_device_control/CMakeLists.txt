
if((${CMAKE_SYSTEM_NAME} STREQUAL XCORE_XS3A) OR (${CMAKE_SYSTEM_NAME} STREQUAL XCORE_XS2A))
    ## Create library target
    add_library(fph_rtos_sw_services_device_control INTERFACE)
    target_sources(fph_rtos_sw_services_device_control
        INTERFACE
            src/device_control.c
            src/resource_table.c
            transport/i2c/device_control_i2c.c
            transport/spi/device_control_spi.c
    )
    target_include_directories(fph_rtos_sw_services_device_control
        INTERFACE
            api
            transport/i2c
            transport/spi
    )
    target_link_libraries(fph_rtos_sw_services_device_control
        INTERFACE
            rtos::osal
            rtos::drivers::i2c
            rtos::drivers::spi
    )

    ## Create an alias
    add_library(fph::device_control ALIAS fph_rtos_sw_services_device_control)
endif()
