## Add audio pipelines
add_subdirectory(reference)
if(NOT FIXED_DELAY_ONLY)
    add_subdirectory(referenceless)
endif()
add_subdirectory(speaker)
