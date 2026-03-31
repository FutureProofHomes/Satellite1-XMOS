#!/usr/bin/env python3

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def maybe_git_rev(repo_root: Path) -> str:
    res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        return ""
    return res.stdout.strip()


def run_cmd(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)


def print_stage_failure(stage: str, res: subprocess.CompletedProcess[str]) -> None:
    print(f"error: {stage} failed (rc={res.returncode})", file=sys.stderr)
    if res.stdout.strip():
        print(f"--- {stage} stdout ---", file=sys.stderr)
        print(
            res.stdout, file=sys.stderr, end="" if res.stdout.endswith("\n") else "\n"
        )
    if res.stderr.strip():
        print(f"--- {stage} stderr ---", file=sys.stderr)
        print(
            res.stderr, file=sys.stderr, end="" if res.stderr.endswith("\n") else "\n"
        )


def parse_segment_results(text: str) -> list[dict]:
    results: list[dict] = []
    pattern = re.compile(
        r"^SEGMENT_RESULT\s+idx=(?P<idx>\d+)\s+"
        r"expected_deg=(?P<expected>-?\d+(?:\.\d+)?)\s+"
        r"mean_est_deg=(?P<mean_est>-?\d+(?:\.\d+)?)\s+"
        r"mean_err_deg=(?P<mean_err>-?\d+(?:\.\d+)?)\s+"
        r"frames=(?P<frames>\d+)\s*$"
    )
    for line in text.splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        results.append(
            {
                "segment_index": int(m.group("idx")),
                "expected_deg": float(m.group("expected")),
                "mean_est_deg": float(m.group("mean_est")),
                "mean_err_deg": float(m.group("mean_err")),
                "frames": int(m.group("frames")),
            }
        )
    return results


def classify_run_failure(
    run: subprocess.CompletedProcess[str], segment_results: list[dict]
) -> dict:
    lines = [
        ln.strip() for ln in (run.stderr + "\n" + run.stdout).splitlines() if ln.strip()
    ]

    tol_re = re.compile(
        r"^FAIL wav segment \d+ expected .* mean_err .* \(frames=\d+\)$"
    )
    no_frames_re = re.compile(r"^FAIL wav segment \d+ has no evaluated frames$")

    tolerance_lines = [ln for ln in lines if tol_re.match(ln)]
    no_frames_lines = [ln for ln in lines if no_frames_re.match(ln)]

    ignored_prefixes = (
        "doa_gcc_phat_test (wav mode):",
        "SEGMENT_RESULT ",
    )
    other_fail_lines = [
        ln
        for ln in lines
        if ln.startswith("FAIL ")
        and ln not in tolerance_lines
        and ln not in no_frames_lines
        and not ln.startswith(ignored_prefixes)
    ]

    estimate_failure = len(tolerance_lines) > 0
    structural_failure = run.returncode != 0 and (
        len(segment_results) == 0
        or len(no_frames_lines) > 0
        or len(other_fail_lines) > 0
        or (not estimate_failure)
    )

    return {
        "estimate_failure": estimate_failure,
        "structural_failure": structural_failure,
        "tolerance_failure_lines": tolerance_lines,
        "no_frame_failure_lines": no_frames_lines,
        "other_failure_lines": other_fail_lines,
    }


def print_summary(segment_results: list[dict], classification: dict) -> None:
    print("\n=== DoA GCC Eval Summary ===")
    if not segment_results:
        print("No segment results parsed.")
    else:
        mean_errs = [float(seg["mean_err_deg"]) for seg in segment_results]
        max_err = max(mean_errs)
        avg_err = sum(mean_errs) / len(mean_errs)
        print(
            f"Segments evaluated: {len(segment_results)} | "
            f"mean(mean_err_deg): {avg_err:.3f} | max(mean_err_deg): {max_err:.3f}"
        )
        for seg in segment_results:
            print(
                f"- seg {seg['segment_index']}: expected={seg['expected_deg']:.3f} "
                f"mean_est={seg['mean_est_deg']:.3f} "
                f"mean_err={seg['mean_err_deg']:.3f} frames={seg['frames']}"
            )

    if classification["structural_failure"]:
        print("Result: STRUCTURAL FAILURE")
    elif classification["estimate_failure"]:
        print("Result: ESTIMATION OUT OF RANGE (non-structural)")
    else:
        print("Result: OK")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build/run doa_gcc_phat_test against a WAV and write reproducibility JSON"
    )
    parser.add_argument("--wav", required=True, help="Input packaged WAV")
    parser.add_argument("--out-json", required=True, help="Output JSON report path")
    parser.add_argument(
        "--build-dir", default="build_doa_tests", help="CMake build dir"
    )
    parser.add_argument(
        "--skip-build", action="store_true", help="Skip CMake configure/build"
    )
    parser.add_argument(
        "--angles-deg", default="", help="Optional override for expected angles"
    )
    parser.add_argument(
        "--segment-s", type=float, default=0.0, help="Optional override segment length"
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    wav_path = Path(args.wav).expanduser().resolve()
    out_json = Path(args.out_json).expanduser().resolve()
    build_dir = (repo_root / args.build_dir).resolve()

    if not wav_path.is_file():
        print(f"error: wav not found: {wav_path}", file=sys.stderr)
        return 2

    configure = None
    build = None
    if not args.skip_build:
        configure = run_cmd(
            ["cmake", "-S", "modules/fph/doa/tests", "-B", str(build_dir)],
            cwd=repo_root,
        )
        if configure.returncode != 0:
            report = {
                "status": "configure_failed",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "repo_root": str(repo_root),
                "wav": str(wav_path),
                "configure": {
                    "cmd": [
                        "cmake",
                        "-S",
                        "modules/fph/doa/tests",
                        "-B",
                        str(build_dir),
                    ],
                    "returncode": configure.returncode,
                    "stdout": configure.stdout,
                    "stderr": configure.stderr,
                },
            }
            out_json.parent.mkdir(parents=True, exist_ok=True)
            out_json.write_text(json.dumps(report, indent=2) + "\n")
            print_stage_failure("cmake configure", configure)
            print(f"Wrote report: {out_json}", file=sys.stderr)
            return configure.returncode

        build = run_cmd(["cmake", "--build", str(build_dir), "-j"], cwd=repo_root)
        if build.returncode != 0:
            report = {
                "status": "build_failed",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "repo_root": str(repo_root),
                "wav": str(wav_path),
                "build": {
                    "cmd": ["cmake", "--build", str(build_dir), "-j"],
                    "returncode": build.returncode,
                    "stdout": build.stdout,
                    "stderr": build.stderr,
                },
            }
            out_json.parent.mkdir(parents=True, exist_ok=True)
            out_json.write_text(json.dumps(report, indent=2) + "\n")
            print_stage_failure("cmake build", build)
            print(f"Wrote report: {out_json}", file=sys.stderr)
            return build.returncode

    test_bin = build_dir / "doa_gcc_phat_test"
    if not test_bin.is_file():
        print(f"error: test binary not found: {test_bin}", file=sys.stderr)
        return 2

    run_cmdline = [str(test_bin), "--wav", str(wav_path)]
    if args.angles_deg or args.segment_s > 0.0:
        if not args.angles_deg or args.segment_s <= 0.0:
            print("error: use --angles-deg and --segment-s together", file=sys.stderr)
            return 2
        run_cmdline += [
            "--angles-deg",
            args.angles_deg,
            "--segment-s",
            str(args.segment_s),
        ]

    run = run_cmd(run_cmdline, cwd=repo_root)

    expected_json_path = wav_path.with_suffix(".expected.json")
    expected_json = None
    if expected_json_path.is_file():
        try:
            expected_json = json.loads(expected_json_path.read_text())
        except Exception:
            expected_json = None

    segment_results = parse_segment_results(run.stdout + "\n" + run.stderr)
    classification = classify_run_failure(run, segment_results)

    if classification["structural_failure"]:
        status = "structural_failure"
    elif classification["estimate_failure"]:
        status = "estimates_out_of_range"
    else:
        status = "ok"

    report = {
        "status": status,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "git_rev": maybe_git_rev(repo_root),
        "platform": platform.platform(),
        "python": sys.version,
        "inputs": {
            "wav": str(wav_path),
            "wav_size_bytes": wav_path.stat().st_size,
            "wav_sha256": sha256_file(wav_path),
            "angles_deg_override": args.angles_deg,
            "segment_s_override": args.segment_s,
            "adjacent_expected_json": str(expected_json_path)
            if expected_json_path.is_file()
            else "",
            "adjacent_expected_schedule": expected_json,
        },
        "build": {
            "build_dir": str(build_dir),
            "skip_build": args.skip_build,
            "configure": None
            if configure is None
            else {
                "cmd": ["cmake", "-S", "modules/fph/doa/tests", "-B", str(build_dir)],
                "returncode": configure.returncode,
                "stdout": configure.stdout,
                "stderr": configure.stderr,
            },
            "compile": None
            if build is None
            else {
                "cmd": ["cmake", "--build", str(build_dir), "-j"],
                "returncode": build.returncode,
                "stdout": build.stdout,
                "stderr": build.stderr,
            },
        },
        "run": {
            "cmd": run_cmdline,
            "returncode": run.returncode,
            "stdout": run.stdout,
            "stderr": run.stderr,
            "segment_results": segment_results,
            "classification": classification,
        },
    }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2) + "\n")

    print_summary(segment_results, classification)

    if classification["structural_failure"]:
        print_stage_failure("doa_gcc_phat_test", run)
        print(f"Wrote report: {out_json}", file=sys.stderr)
        return run.returncode if run.returncode != 0 else 1

    if classification["estimate_failure"]:
        print(
            "warning: estimation errors exceed tolerance (non-structural)",
            file=sys.stderr,
        )

    print(f"Wrote report: {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
