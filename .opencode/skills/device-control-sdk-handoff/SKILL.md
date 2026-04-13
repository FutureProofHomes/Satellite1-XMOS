---
name: device-control-sdk-handoff
description: Create a structured handoff description for Satellite1-RPi SDK agents after device-control protocol or servicer changes.
compatibility: opencode
metadata:
  scope: device-control-handoff
  workflow: cross-repo-handoff
---

## Purpose

Use this skill when XMOS firmware changes affect SPI device-control behavior and
the Satellite1-RPi SDK must be updated to match.

This skill produces a handoff file in this repository that can be passed to an
agent session in `Satellite1-RPi`.

## Output location

Create one file per protocol-impacting change:

- `docs/handoffs/rpi-sdk/YYYY-MM-DD-<short-topic>-handoff.md`

Use `docs/handoffs/rpi-sdk/HANDOFF_TEMPLATE.md` as the baseline structure.

## Required content

The handoff file must include:

1. Firmware context
- branch name
- commit hash(es)
- affected files

2. Protocol deltas
- resource IDs changed/added/removed
- command IDs and read/write direction changes
- payload format before/after (sizes, field order, types, endian)
- response/status code behavior changes

3. Compatibility statement
- backward compatibility status
- expected behavior on old firmware vs new firmware
- SDK fallback requirements (if any)
- protocol version bump (`CONTROL_VERSION`) and changelog entry reference

4. SDK implementation requirements
- exact Python modules expected to change in `Satellite1-RPi`
- parsing/encoding updates required
- CLI behavior updates required
- config/env changes required

5. Verification plan
- minimum SDK tests to add/update
- minimum firmware+SDK HIL checks to run
- clear acceptance criteria

## Execution policy

- Keep the handoff factual and implementation-oriented.
- Include concrete IDs/bytes; avoid vague summaries.
- Do not update RPi code from this skill; only generate the handoff artifact.

## Trigger guidance

Use this skill whenever any of these change:
- `*_servicer.c` command map or callbacks
- `*_cmds.h` resource/command definitions
- transport-visible payload structures
- status/return-code semantics

This includes changes inside an existing servicer, for example:
- adding a new command ID
- changing command direction (read/write)
- changing payload size/layout for an existing command
