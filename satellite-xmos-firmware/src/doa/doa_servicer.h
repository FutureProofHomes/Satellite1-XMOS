#pragma once

#include "servicer.h"

#define DOA_SERVICER_RESID           (230)
#define NUM_RESOURCES_DOA            (1)

void doa_servicer_init(servicer_t *servicer);
void doa_servicer(void *args);
