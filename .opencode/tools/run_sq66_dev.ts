import { tool } from "@opencode-ai/plugin"
import path from "path"

const ModeSchema = tool.schema.enum(["build", "run", "debug"])

export default tool({
  description:
    "Build, run, or debug the SQ66 dev firmware through the repository wrapper script. Use this instead of calling XMOS build/xrun/xgdb commands directly.",

  args: {
    mode: ModeSchema
      .default("run")
      .describe("Execution mode: build, run, or debug."),

    adapterId: tool.schema
      .string()
      .optional()
      .describe("Optional xTAG adapter id, for example 7A3VAER2."),

    buildDir: tool.schema
      .string()
      .optional()
      .describe("Optional build directory override. Defaults to build_sq66_dev."),

    target: tool.schema
      .string()
      .optional()
      .describe(
        "Optional firmware target override. Defaults to sq66_firmware_fixed_delay.",
      ),

    skipBuild: tool.schema
      .boolean()
      .default(false)
      .describe("Skip the configure/build step before launch."),

    detectOnly: tool.schema
      .boolean()
      .default(false)
      .describe("Only detect and print the adapter id, then exit."),

    dryRun: tool.schema
      .boolean()
      .default(false)
      .describe("Print the commands that would run without executing them."),
  },

  async execute(args, context) {
    const worktree = context.worktree || context.directory
    if (!worktree) {
      throw new Error("Unable to determine repository root from tool context.")
    }

    const script = path.join(worktree, "tools", "e2e", "run_sq66_dev.sh")

    const cmd: string[] = [script]

    if (args.detectOnly) {
      cmd.push("--detect-only")
    } else {
      switch (args.mode) {
        case "build":
          cmd.push("--build")
          break
        case "run":
          cmd.push("--run")
          break
        case "debug":
          cmd.push("--debug")
          break
      }
    }

    if (args.adapterId) {
      cmd.push("--adapter-id", args.adapterId)
    }

    if (args.buildDir) {
      cmd.push("--build-dir", args.buildDir)
    }

    if (args.target) {
      cmd.push("--target", args.target)
    }

    if (args.skipBuild) {
      cmd.push("--skip-build")
    }

    if (args.dryRun) {
      cmd.push("--dry-run")
    }

    try {
      const proc = Bun.spawn(cmd, {
        cwd: worktree,
        stdout: "pipe",
        stderr: "pipe",
      })

      const [stdout, stderr, exitCode] = await Promise.all([
        new Response(proc.stdout).text(),
        new Response(proc.stderr).text(),
        proc.exited,
      ])

      const result = {
        ok: exitCode === 0,
        exitCode,
        command: cmd.join(" "),
        stdout: stdout.trim(),
        stderr: stderr.trim(),
      }

      if (exitCode !== 0) {
        return JSON.stringify(
          {
            ...result,
            error: "SQ66 dev firmware command failed.",
          },
          null,
          2,
        )
      }

      return JSON.stringify(result, null, 2)
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown tool execution error"

      return JSON.stringify(
        {
          ok: false,
          exitCode: -1,
          command: cmd.join(" "),
          error: message,
        },
        null,
        2,
      )
    }
  },
})