
## Create custom board targets for application
add_library(fph_ffva_board_support_sq66 INTERFACE)
target_sources(fph_ffva_board_support_sq66
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/platform/app_pll_ctrl.c
        ${CMAKE_CURRENT_LIST_DIR}/platform/driver_instances.c
        ${CMAKE_CURRENT_LIST_DIR}/platform/platform_init.c
        ${CMAKE_CURRENT_LIST_DIR}/platform/platform_start.c
)
target_include_directories(fph_ffva_board_support_sq66
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}
)
target_link_libraries(fph_ffva_board_support_sq66
    INTERFACE
        core::general
        rtos::freertos
        rtos::drivers::general
        rtos::drivers::dfu_image
        fph::rtos_mic_array
        fph::i2s_sync
)
target_compile_options(fph_ffva_board_support_sq66
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/XK_VOICE_SQ66.xn
)
target_link_options(fph_ffva_board_support_sq66
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/XK_VOICE_SQ66.xn
)

# MICS: 
# pins 0-3 are not used for PDM data, DDR is not used
# North: 4 (pin 4 falling edge) 
# South: 5 (pin 5 falling edge)
# South: 6 (pin 6 falling edge)
# East:  7 (pin 7 falling edge ) 
 
# use East as first and West as second mic
set(MIC_MAPPING "4, 5")

target_compile_definitions(fph_ffva_board_support_sq66
    INTERFACE
        XCOREAI_EXPLORER=1
        PLATFORM_SUPPORTS_TILE_0=1
        PLATFORM_SUPPORTS_TILE_1=1
        PLATFORM_SUPPORTS_TILE_2=0
        PLATFORM_SUPPORTS_TILE_3=0

        MIC_ARRAY_CONFIG_MCLK_FREQ=24576000
        MIC_ARRAY_CONFIG_PDM_FREQ=3072000
        MIC_ARRAY_CONFIG_SAMPLES_PER_FRAME=240
        MIC_ARRAY_CONFIG_USE_DDR=0
        MIC_ARRAY_CONFIG_MIC_INPUT=8
        MIC_ARRAY_CONFIG_MIC_COUNT=2
        MIC_ARRAY_CONFIG_INPUT_MAPPING={${MIC_MAPPING}}
        
        MIC_ARRAY_CONFIG_CLOCK_BLOCK_A=XS1_CLKBLK_1
        MIC_ARRAY_CONFIG_CLOCK_BLOCK_B=XS1_CLKBLK_2
        MIC_ARRAY_CONFIG_PORT_MCLK=PORT_MCLK_IN
        MIC_ARRAY_CONFIG_PORT_PDM_CLK=PORT_PDM_CLK
        MIC_ARRAY_CONFIG_PORT_PDM_DATA=PORT_PDM_DATA
)

## Create an alias
add_library(fph::ffva::sq66 ALIAS fph_ffva_board_support_sq66)
