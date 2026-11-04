#include "aec_schedule_4y.h"

#if AEC_MAX_Y_CHANNELS != 4 || (AEC_MAX_X_CHANNELS != 1 && AEC_MAX_X_CHANNELS != 2)
#error The single-thread 4Y schedule requires four microphones and one or two references
#endif

/* Channel-major order matches the serial AEC: all tasks for a channel finish
 * before the next channel. Reference tasks skip channels beyond num_x_channels.
 * Only thread zero is active; no additional hardware threads are requested.
 */
const aec_task_distribution_t aec_tdist_chans4_threads1 = {
    .thread_count = 1,
    .passes_for_3_tasks_and_channels = 12,
    .par_3_tasks_and_channels = {{
        {0, 0, 1}, {1, 0, 1}, {2, 0, 1},
        {0, 1, 1}, {1, 1, 1}, {2, 1, 1},
        {0, 2, 1}, {1, 2, 1}, {2, 2, 1},
        {0, 3, 1}, {1, 3, 1}, {2, 3, 1},
    }},
    .passes_for_2_tasks_and_channels = 8,
    .par_2_tasks_and_channels = {{
        {0, 0, 1}, {1, 0, 1}, {0, 1, 1}, {1, 1, 1},
        {0, 2, 1}, {1, 2, 1}, {0, 3, 1}, {1, 3, 1},
    }},
    .passes_for_1_tasks_and_channels = 4,
    .par_1_tasks_and_channels = {{
        {0, 0, 1}, {0, 1, 1}, {0, 2, 1}, {0, 3, 1},
    }},
    .passes_for_3_tasks = 3,
    .par_3_tasks = {{{0, 1}, {1, 1}, {2, 1}}},
    .passes_for_2_tasks = 2,
    .par_2_tasks = {{{0, 1}, {1, 1}}},
};
