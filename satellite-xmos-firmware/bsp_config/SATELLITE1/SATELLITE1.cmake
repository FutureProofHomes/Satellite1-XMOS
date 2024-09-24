
## Create custom board targets for application
add_library(fph_ffva_board_support_satellite1 INTERFACE)
target_sources(fph_ffva_board_support_satellite1
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/platform/app_pll_ctrl.c
        ${CMAKE_CURRENT_LIST_DIR}/platform/driver_instances.c
        ${CMAKE_CURRENT_LIST_DIR}/platform/platform_init.c
        ${CMAKE_CURRENT_LIST_DIR}/platform/platform_start.c
)
target_include_directories(fph_ffva_board_support_satellite1
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}
)
target_link_libraries(fph_ffva_board_support_satellite1
    INTERFACE
        core::general
        fph::i2s_sync
        fph::rtos_mic_array
        rtos::freertos
        rtos::drivers::general
        rtos::drivers::usb
        rtos::drivers::dfu_image
)
target_compile_options(fph_ffva_board_support_satellite1
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/SATTELITE1.xn
)
target_link_options(fph_ffva_board_support_satellite1
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/SATTELITE1.xn
)
target_compile_definitions(fph_ffva_board_support_satellite1
    INTERFACE
        XCOREAI_EXPLORER=1
        PLATFORM_SUPPORTS_TILE_0=1
        PLATFORM_SUPPORTS_TILE_1=1
        PLATFORM_SUPPORTS_TILE_2=0
        PLATFORM_SUPPORTS_TILE_3=0
        USB_TILE_NO=0
        USB_TILE=tile[USB_TILE_NO]

        MIC_ARRAY_CONFIG_MCLK_FREQ=24576000
        MIC_ARRAY_CONFIG_PDM_FREQ=3072000
        MIC_ARRAY_CONFIG_SAMPLES_PER_FRAME=240
        MIC_ARRAY_CONFIG_MIC_COUNT=2
        MIC_ARRAY_CONFIG_MIC_INPUT=8
        MIC_ARRAY_CONFIG_USE_DDR=1
        MIC_ARRAY_CONFIG_MIC_DDR_INTERLEAVE=1
        MIC_ARRAY_CONFIG_CLOCK_BLOCK_A=XS1_CLKBLK_1
        MIC_ARRAY_CONFIG_CLOCK_BLOCK_B=XS1_CLKBLK_2
        MIC_ARRAY_CONFIG_PORT_MCLK=PORT_MCLK_IN
        MIC_ARRAY_CONFIG_PORT_PDM_CLK=PORT_PDM_CLK
        MIC_ARRAY_CONFIG_PORT_PDM_DATA=PORT_PDM_DATA
)

## Create an alias
add_library(fph::ffva::satellite1 ALIAS fph_ffva_board_support_satellite1)
