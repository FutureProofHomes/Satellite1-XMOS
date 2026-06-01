
if((${CMAKE_SYSTEM_NAME} STREQUAL XCORE_XS3A) OR (${CMAKE_SYSTEM_NAME} STREQUAL XCORE_XS2A))
    ## Create library target
    add_library(fph_qspi_flash_ext INTERFACE)
    target_sources(fph_qspi_flash_ext
        INTERFACE
            src/fph_qspi_flash_ext.c
    )
    target_include_directories(fph_qspi_flash_ext
        INTERFACE
            api
    )
    target_link_libraries(fph_qspi_flash_ext
        INTERFACE
            rtos::drivers::qspi_io
            rtos::osal
    )

    ## Create an alias
    add_library(fph::qspi_flash_ext ALIAS fph_qspi_flash_ext)
endif()
