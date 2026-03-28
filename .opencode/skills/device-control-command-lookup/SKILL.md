---
name: device-control-command-lookup
description: Answer command-inventory questions quickly using targeted device-control files instead of full-repo scans.
compatibility: opencode
metadata:
  scope: device-control-query
  workflow: fast-lookup
---

## Purpose

Use this skill for prompts like:
- "list available device control commands"
- "what are the audio pipeline commands"
- "which resource/command IDs exist for <servicer>"

## Fast lookup policy

- Do not run broad repo scans first.
- Read existing docs first, then verify only required source files.

## Lookup order

1. Check fast index first:
   - `docs/device-control-command-index.md`
2. Check protocol doc if needed:
   - `docs/device-control-spi-protocol.md`
3. Verify IDs/names in servicer-local command definitions:
   - `satellite-xmos-firmware/src/audio_pipeline_control/*cmds*.h`
   - `satellite-xmos-firmware/src/*/*cmds*.h` (only relevant servicer)
4. Verify command map/direction/payload from implementation:
   - `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_servicer.c`
   - or specific servicer `*_servicer.c` requested by prompt

## Audio pipeline query defaults

For audio-pipeline command listing, prioritize only:
- `docs/device-control-command-index.md`
- `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_settings.h`
- `satellite-xmos-firmware/src/audio_pipeline_control/audio_pipeline_control_servicer.c`

If these files fully answer the question, stop there.

## Output format

- Resource ID(s)
- Command ID(s)
- Direction (`read`/`write`)
- Short purpose per command
- Optional payload size/shape note (if obvious from command map)

## Guardrails

- If command docs and code disagree, report code as source of truth.
- If uncertain, state exactly which file/line needs confirmation.
