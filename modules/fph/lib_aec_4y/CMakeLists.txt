# FPH-owned 4Y AEC ABI variant. Upstream lib_aec remains unchanged for 2Y users.
get_filename_component(FPH_UPSTREAM_AEC_ROOT
    "${CMAKE_CURRENT_LIST_DIR}/../../voice/modules/lib_aec" ABSOLUTE)

add_library(fph_lib_aec_4y STATIC)
target_sources(fph_lib_aec_4y PRIVATE
    src/aec_impl.c
    "${FPH_UPSTREAM_AEC_ROOT}/src/aec_l2_impl.c"
    "${FPH_UPSTREAM_AEC_ROOT}/src/aec_priv_impl.c")
target_include_directories(fph_lib_aec_4y PUBLIC
    api
    "${FPH_UPSTREAM_AEC_ROOT}/src")
target_compile_definitions(fph_lib_aec_4y PUBLIC AEC_LIB_MAX_Y_CHANNELS=4)
target_compile_options(fph_lib_aec_4y PRIVATE -Os -g)
target_link_libraries(fph_lib_aec_4y PUBLIC lib_xcore_math)

add_library(fph::aec_4y ALIAS fph_lib_aec_4y)

if(NOT CMAKE_SYSTEM_NAME STREQUAL XCORE_XS3A)
    add_executable(fph_aec_4y_init_canary_test test/init_canary_test.c)
    target_link_libraries(fph_aec_4y_init_canary_test PRIVATE fph::aec_4y)
endif()
