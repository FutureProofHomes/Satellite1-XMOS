
if((${CMAKE_SYSTEM_NAME} STREQUAL XCORE_XS3A) OR (${CMAKE_SYSTEM_NAME} STREQUAL XCORE_XS2A))
    ## Create library target
    add_library(framework_rtos_drivers_spi INTERFACE)
    target_sources(framework_rtos_drivers_spi
        INTERFACE
            src/rtos_spi_master.c
            src/rtos_spi_master_rpc.c
            src/rtos_spi_slave.c
    )
    target_include_directories(framework_rtos_drivers_spi
        INTERFACE
            api
    )
    target_link_libraries(framework_rtos_drivers_spi
        INTERFACE
            lib_spi
            rtos::osal
    )

    ## Create an alias
    add_library(rtos::drivers::spi ALIAS framework_rtos_drivers_spi)
endif()
