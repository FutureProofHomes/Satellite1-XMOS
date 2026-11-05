## Add audio pipelines
add_library(voice_compat INTERFACE)
target_include_directories(voice_compat INTERFACE ${CMAKE_CURRENT_LIST_DIR})
add_subdirectory(reference)
add_subdirectory(referenceless)
add_subdirectory(speaker)

option(BUILD_VOICE_COMPAT_TESTS "Build voice API compatibility simulator tests" OFF)
if(BUILD_VOICE_COMPAT_TESTS)
    add_executable(voice_compat_test
        ${XMOS_FIRMWARE_ROOT_PATH}/tests/test_voice_compat/voice_compat_test.c
        reference/fixed_delay/aec/aec_process_frame_1thread.c)
    target_link_libraries(voice_compat_test PRIVATE voice_compat fwk_voice::aec fwk_voice::ic fwk_voice::agc)
    target_compile_options(voice_compat_test PRIVATE -target=XCORE-AI-EXPLORER -Os -g)
    target_link_options(voice_compat_test PRIVATE -target=XCORE-AI-EXPLORER -report)
endif()
