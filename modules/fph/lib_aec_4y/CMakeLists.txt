# FPH-owned 4Y AEC ABI variant. Upstream lib_aec remains unchanged for 2Y users.
get_filename_component(FPH_UPSTREAM_AEC_ROOT
    "${CMAKE_CURRENT_LIST_DIR}/../../voice/modules/lib_aec" ABSOLUTE)

add_library(fph_lib_aec_4y STATIC)
target_sources(fph_lib_aec_4y PRIVATE
    src/aec_impl.c
    src/aec_schedule_4y.c
    "${FPH_UPSTREAM_AEC_ROOT}/src/aec_process_frame.c"
    "${FPH_UPSTREAM_AEC_ROOT}/src/aec_l2_impl.c"
    "${FPH_UPSTREAM_AEC_ROOT}/src/aec_priv_impl.c")
target_include_directories(fph_lib_aec_4y PUBLIC
    api
    "${FPH_UPSTREAM_AEC_ROOT}/api"
    "${FPH_UPSTREAM_AEC_ROOT}/src")
# Every consumer, including IC, must use the same state and embedded-pool ABI.
target_compile_definitions(fph_lib_aec_4y PUBLIC
    AEC_MAX_Y_CHANNELS=4 AEC_MAX_X_CHANNELS=1
    AEC_MAIN_FILTER_PHASES=10 AEC_SHADOW_FILTER_PHASES=5)
target_compile_options(fph_lib_aec_4y PRIVATE -Os -g)
target_link_libraries(fph_lib_aec_4y PUBLIC lib_xcore_math)

add_library(fph::aec_4y ALIAS fph_lib_aec_4y)

option(FPH_AEC_4Y_TESTS "Build the 4Y1X AEC serial-reference and canary test" OFF)
if(FPH_AEC_4Y_TESTS OR NOT CMAKE_SYSTEM_NAME STREQUAL XCORE_XS3A)
    add_executable(fph_aec_4y_init_canary_test
        test/init_canary_test.c test/aec_serial_reference.c)
    target_link_libraries(fph_aec_4y_init_canary_test PRIVATE fph::aec_4y)
    if(CMAKE_SYSTEM_NAME STREQUAL XCORE_XS3A)
        target_compile_options(fph_aec_4y_init_canary_test PRIVATE -target=XCORE-AI-EXPLORER -Os -g)
        target_link_options(fph_aec_4y_init_canary_test PRIVATE -target=XCORE-AI-EXPLORER -report)
    endif()
endif()
