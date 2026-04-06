---
name: opencode-topology-audit
description: Audit the repository's OpenCode setup across AGENTS.md, agents, skills, commands, and helper scripts to keep context small and responsibilities clean
compatibility: opencode
metadata:
  area: opencode
  task: audit
---

## Purpose

Use this skill to review whether the current OpenCode setup is still well-structured.

Audit:
- `AGENTS.md`
- `.opencode/agents/`
- `.opencode/skills/`
- `.opencode/commands/`
- helper scripts used by agents or skills

The goal is to keep always-loaded context small, keep procedures in on-demand skills, and keep deterministic operational logic in scripts.

## Core audit principles

1. `AGENTS.md` should stay short and always relevant.
2. Skills should contain reusable task procedures and decision guidance.
3. Scripts should implement deterministic build/test/deploy mechanics when possible.
4. Agents should be few, clearly differentiated, and justified by permissions, workflow boundaries, or model behavior.
5. Commands are optional ergonomic wrappers for humans and should not carry essential architecture.
6. Avoid duplicate instructions across AGENTS, agents, skills, and commands.

## What to check

### 1. Global context hygiene
Check whether `AGENTS.md` contains only:
- canonical build/test/deploy entrypoints
- repo structure and non-obvious conventions
- critical always-relevant constraints

Flag as a problem:
- long procedures
- duplicated checklists
- target-specific operational detail that belongs in a skill
- shell logic that belongs in a script

### 2. Agent topology
For each agent, check:
- primary responsibility
- overlap with other agents
- whether its existence is justified
- whether permissions are too broad
- whether it should instead be:
  - merged into another agent
  - replaced by a skill
  - replaced by a command
  - kept as-is

Create a new agent only if it materially changes:
- permissions
- model/behavior
- workflow boundary
- context isolation needs

### 3. Skill quality
For each skill, check:
- is it narrow enough to load only when needed
- does it describe when to use it
- does it identify the canonical script or command to run
- does it define required inputs/env vars
- does it define expected outputs/artifacts
- does it provide concise failure triage
- is it mixing multiple unrelated workflow phases

Flag as a problem:
- one skill per trivial parameter variant
- repeated instructions across multiple skills
- shell implementation detail that should live in a script
- large multi-phase skills where phases are operationally distinct

### 4. Script usage
For each build/test/deploy script referenced by agents or skills, check:
- whether there is one clear canonical entrypoint
- whether the script boundary is stable enough that agents only need to know how to call it
- whether the script interface is documented in the relevant skill
- whether the script meaningfully reduces prompt complexity

Prefer scripts when:
- the workflow is deterministic
- the same mechanics are reused often
- CI and local execution should share one path

Flag as a problem:
- multiple competing scripts for the same workflow without clear ownership
- agents re-implementing script logic in prose
- undocumented script arguments that the skill depends on

### 5. Commands
Check whether commands are only convenience wrappers.
Flag as a problem:
- commands containing essential logic not documented anywhere else
- commands duplicating large portions of skill content
- commands being used to paper over weak agent/skill design

## Heuristics for splitting or merging

### Split a skill when:
- it spans clearly different phases such as build vs deploy vs verify
- different phases have different failure modes or different required inputs
- different agents should own different phases
- the skill is becoming a mini-handbook rather than a targeted playbook

### Do not split a skill when:
- the difference is only a target parameter or artifact name
- the command path and triage are mostly the same
- the split would create many tiny near-duplicate skills

### Add a new agent only when:
- the workflow needs different permissions
- the workflow needs isolation from the main session
- the workflow consistently uses a different behavior/model
- the workflow is recurring and operationally distinct

Otherwise prefer:
- reuse an existing agent
- add or improve a skill
- add a convenience command if humans trigger it often

## Recommended audit workflow

1. Inventory:
   - `AGENTS.md`
   - `.opencode/agents/`
   - `.opencode/skills/`
   - `.opencode/commands/`
   - workflow scripts under `tools/`, `scripts/`, or equivalent
2. Classify each instruction as one of:
   - always-loaded global rule
   - agent responsibility
   - skill procedure
   - script implementation
   - command convenience wrapper
3. Identify duplication and ambiguity.
4. Identify skills that are too broad or too fragmented.
5. Identify scripts that should become canonical entrypoints.
6. Recommend merges, splits, or relocations.
7. Estimate which parts are always-loaded vs on-demand.

## Output format

### Topology summary
- current global rules
- current agents
- current skills
- current script entrypoints
- current commands

### Findings
- healthy boundaries
- context bloat risks
- duplicated instructions
- unclear ownership
- script/interface gaps
- permission issues

### Recommendations
For each recommendation, say one of:
- keep
- merge
- split
- move to script
- move to skill
- move to AGENTS.md
- replace with command
- tighten permissions

### Final judgment
End with:
- overall health: healthy / acceptable / drifting / bloated
- top 3 next edits