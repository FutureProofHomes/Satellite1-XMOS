if(${CMAKE_SYSTEM_NAME} STREQUAL XCORE_XS3A)
    add_library(fph_speaker_eq STATIC
        src/speaker_eq.c
        src/speaker_eq_design.c
    )
    add_library(fph::speaker_eq ALIAS fph_speaker_eq)

    target_include_directories(fph_speaker_eq
        PUBLIC
            api
    )
    target_link_libraries(fph_speaker_eq
        PUBLIC
            audio_dsp::lib_audio_dsp
    )
    target_compile_options(fph_speaker_eq
        PRIVATE
            -O3
            -Wall
            -Werror
    )

    if(SPEAKER_EQ_BUILD_TESTS)
        add_executable(speaker_eq_tests
            test/test_speaker_eq.c
            ${XMOS_FIRMWARE_ROOT_PATH}/satellite-xmos-firmware/audio_pipelines/speaker/serial_eq/speaker_eq_preset.c
        )
        target_include_directories(speaker_eq_tests PRIVATE
            ${XMOS_FIRMWARE_ROOT_PATH}/satellite-xmos-firmware/audio_pipelines/speaker/serial_eq
        )
        target_link_libraries(speaker_eq_tests PRIVATE fph::speaker_eq)
        target_compile_options(speaker_eq_tests PRIVATE -Wall -Werror)
        target_link_options(speaker_eq_tests PRIVATE -target=XCORE-AI-EXPLORER)

        add_test(NAME speaker_eq_xsim
            COMMAND xsim $<TARGET_FILE:speaker_eq_tests>
        )
    endif()
endif()
