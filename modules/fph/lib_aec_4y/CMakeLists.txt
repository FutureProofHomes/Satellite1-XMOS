# FPH-owned 4Y AEC ABI variant. Upstream lib_aec remains unchanged for 2Y users.
get_filename_component(FPH_UPSTREAM_AEC_ROOT
    "${CMAKE_CURRENT_LIST_DIR}/../../voice/modules/lib_aec" ABSOLUTE)

add_library(fph_lib_aec_4y STATIC)
target_sources(fph_lib_aec_4y PRIVATE
    src/aec_impl.c
    src/aec_schedule_4y.c
    src/aec_process_frame.c
    "${FPH_UPSTREAM_AEC_ROOT}/src/aec_l2_impl.c"
    "${FPH_UPSTREAM_AEC_ROOT}/src/aec_priv_impl.c")
target_include_directories(fph_lib_aec_4y PUBLIC
    api
    "${FPH_UPSTREAM_AEC_ROOT}/api"
    "${FPH_UPSTREAM_AEC_ROOT}/src")
# Every consumer, including IC, must use the same state and embedded-pool ABI.
if(SATELLITE1_FIXED_DELAY_AEC_4Y2X_MAIN_ONLY)
    set(SATELLITE1_AEC_PHASE_CAPACITY 20 CACHE STRING "AEC phase descriptors per microphone row")
    if(NOT SATELLITE1_AEC_PHASE_CAPACITY STREQUAL "20")
        message(FATAL_ERROR "The main-only 4Y2X ABI requires phase capacity 20")
    endif()
    target_compile_definitions(fph_lib_aec_4y PUBLIC
        AEC_MAX_Y_CHANNELS=4 AEC_MAX_X_CHANNELS=2
        AEC_MAIN_FILTER_PHASES=10 AEC_SHADOW_FILTER_PHASES=0
        AEC_LIB_MAX_PHASES=20 AEC_MAIN_ONLY=1)
    target_sources(fph_lib_aec_4y PRIVATE src/aec_main_only_control.c)
else()
    target_compile_definitions(fph_lib_aec_4y PUBLIC
        AEC_MAX_Y_CHANNELS=4 AEC_MAX_X_CHANNELS=1
        AEC_MAIN_FILTER_PHASES=10 AEC_SHADOW_FILTER_PHASES=5 AEC_MAIN_ONLY=0)
endif()
target_compile_options(fph_lib_aec_4y PRIVATE -Os -g)
if(CMAKE_SYSTEM_NAME STREQUAL XCORE_XS3A)
    target_compile_options(fph_lib_aec_4y PRIVATE -mcmodel=large)
endif()
target_link_libraries(fph_lib_aec_4y PUBLIC lib_xcore_math)

add_library(fph::aec_4y ALIAS fph_lib_aec_4y)

option(FPH_AEC_4Y_TESTS "Build AEC serial-reference and canary tests" OFF)
if(FPH_AEC_4Y_TESTS OR NOT CMAKE_SYSTEM_NAME STREQUAL XCORE_XS3A)
    if(SATELLITE1_FIXED_DELAY_AEC_4Y2X_MAIN_ONLY)
        add_executable(fph_aec_4y_init_canary_test test/main_only_test.c)
    else()
        add_executable(fph_aec_4y_init_canary_test
            test/init_canary_test.c test/aec_serial_reference.c)
    endif()
    target_link_libraries(fph_aec_4y_init_canary_test PRIVATE fph::aec_4y)
    target_include_directories(fph_aec_4y_init_canary_test PRIVATE src)
    if(CMAKE_SYSTEM_NAME STREQUAL XCORE_XS3A)
        target_compile_options(fph_aec_4y_init_canary_test PRIVATE -target=XCORE-AI-EXPLORER -Os -g -mcmodel=large)
        target_link_options(fph_aec_4y_init_canary_test PRIVATE -target=XCORE-AI-EXPLORER -report -mcmodel=large)
    endif()
endif()
