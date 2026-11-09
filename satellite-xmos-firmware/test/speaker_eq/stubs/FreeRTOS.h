#pragma once

/* Single-threaded stand-ins; the test drives the design task by hand. */

#include <stddef.h>
#include <stdint.h>

typedef void *TaskHandle_t;
typedef long BaseType_t;
typedef unsigned long UBaseType_t;
typedef uint32_t TickType_t;

#define pdPASS                      1
#define pdTRUE                      1
#define portMAX_DELAY               0xffffffffu
#define configMINIMAL_STACK_SIZE    256

#define taskENTER_CRITICAL()        do { } while (0)
#define taskEXIT_CRITICAL()         do { } while (0)

BaseType_t xTaskCreate(void (*fn)(void *), const char *name, uint32_t stack_words,
                       void *arg, UBaseType_t priority, TaskHandle_t *handle);
BaseType_t xTaskNotifyGive(TaskHandle_t handle);
uint32_t ulTaskNotifyTake(BaseType_t clear, TickType_t wait);
size_t xPortGetFreeHeapSize(void);
size_t xPortGetMinimumEverFreeHeapSize(void);
