// Copyright 2026 Future Proof Homes
/* Compile the upstream implementation with the target's 4Y1X pool dimensions.
 * Rename only its initializer so the public entry point can validate pool bounds
 * before upstream initialization touches state. No upstream sources are changed.
 */
#define aec_init fph_aec_init_unchecked
#include "../../../voice/modules/lib_aec/src/aec_impl.c"
#undef aec_init

void aec_init(aec_state_t *state, unsigned y_channels, unsigned x_channels,
              unsigned main_phases, unsigned shadow_phases,
              const aec_task_distribution_t *tdist)
{
    if (state == NULL || tdist == NULL || tdist->thread_count != 1 ||
        y_channels == 0 || y_channels > AEC_MAX_Y_CHANNELS ||
        x_channels == 0 || x_channels > AEC_MAX_X_CHANNELS ||
        main_phases == 0 || main_phases > AEC_MAIN_FILTER_PHASES ||
        shadow_phases == 0 || shadow_phases > AEC_SHADOW_FILTER_PHASES ||
        shadow_phases > main_phases) {
        return;
    }
    fph_aec_init_unchecked(state, y_channels, x_channels,
                          main_phases, shadow_phases, tdist);
}
