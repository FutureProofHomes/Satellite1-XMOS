// Copyright 2026 Future Proof Homes

#include <stdint.h>
#include <stdio.h>

#include "aec_api.h"

#define CANARY 0x8a4c2d19f6e735b0ULL
#define POOL_BYTES (1u << 20)

#if defined(__GNUC__) || defined(__clang__)
#define FPH_ALIGNED __attribute__((aligned(8)))
#else
#define FPH_ALIGNED
#endif

typedef struct {
    uint64_t before;
    aec_state_t state;
    uint64_t after;
} state_with_canaries_t;

typedef struct {
    uint64_t before;
    uint8_t FPH_ALIGNED bytes[POOL_BYTES];
    uint64_t after;
} pool_with_canaries_t;

static state_with_canaries_t FPH_ALIGNED main_state;
static state_with_canaries_t FPH_ALIGNED shadow_state;
static aec_shared_state_t FPH_ALIGNED shared_state;
static pool_with_canaries_t FPH_ALIGNED main_pool;
static pool_with_canaries_t FPH_ALIGNED shadow_pool;

static int canaries_intact(void) {
    return main_state.before == CANARY && main_state.after == CANARY &&
           shadow_state.before == CANARY && shadow_state.after == CANARY &&
           main_pool.before == CANARY && main_pool.after == CANARY &&
           shadow_pool.before == CANARY && shadow_pool.after == CANARY;
}

int main(void) {
    main_state.before = CANARY;
    main_state.after = CANARY;
    shadow_state.before = CANARY;
    shadow_state.after = CANARY;
    main_pool.before = CANARY;
    main_pool.after = CANARY;
    shadow_pool.before = CANARY;
    shadow_pool.after = CANARY;

    aec_init(
        &main_state.state,
        &shadow_state.state,
        &shared_state,
        main_pool.bytes,
        shadow_pool.bytes,
        4,
        1,
        10,
        5);

    if (!canaries_intact() || shared_state.num_y_channels != 4 ||
        shared_state.num_x_channels != 1 || main_state.state.shared_state != &shared_state ||
        shadow_state.state.shared_state != &shared_state) {
        fprintf(stderr, "4Y x 1X AEC initialization failed canary or state validation\n");
        return 1;
    }

    return 0;
}
