#!/usr/bin/env python3

import argparse
import collections
import json
import math
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DoaReading:
    doa_mrad: int
    seq: int
    valid: int


def wrap_deg(deg: float) -> float:
    while deg > 180.0:
        deg -= 360.0
    while deg < -180.0:
        deg += 360.0
    return deg


def angle_err_deg(expected: float, actual: float) -> float:
    return abs(wrap_deg(actual - expected))


def circular_mean_deg(values: list[float]) -> float:
    if not values:
        return 0.0
    sx = 0.0
    sy = 0.0
    for v in values:
        r = math.radians(v)
        sx += math.cos(r)
        sy += math.sin(r)
    return wrap_deg(math.degrees(math.atan2(sy, sx)))


def run_ssh(
    host: str, cmd: str, timeout: float = 30.0
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, cmd],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def sat1_cmd_default_from_env() -> str:
    return (
        os.getenv("SAT1_RPI_CLI_CMD", "").strip()
        or os.getenv("SQ66_RPI_CLI_CMD", "").strip()
        or "sat1"
    )


def sat1_xmos_cmd(sat1_cmd: str, board: str | None, subcmd: str) -> str:
    if board:
        return f"{sat1_cmd} --board {board} xmos {subcmd}"
    return f"{sat1_cmd} xmos {subcmd}"


def _supports_required_xmos_cli(host: str, sat1_cmd: str, timeout_s: float) -> bool:
    get_pipeline = run_ssh(
        host,
        sat1_xmos_cmd(sat1_cmd, None, "get-mic-pipeline-settings -h"),
        timeout=timeout_s,
    )
    if get_pipeline.returncode != 0:
        return False

    get_doa_help = run_ssh(
        host,
        sat1_xmos_cmd(sat1_cmd, None, "get-doa -h"),
        timeout=timeout_s,
    )
    if get_doa_help.returncode != 0:
        return False
    return "--stream" in (get_doa_help.stdout + get_doa_help.stderr)


def resolve_remote_sat1_cmd(host: str, requested_cmd: str, timeout_s: float) -> str:
    candidates: list[str] = [requested_cmd]
    if requested_cmd == "sat1":
        candidates.extend(
            [
                "/home/pi/.cache/venvs/satellite1-rpi-e2e/bin/sat1",
                "/opt/satellite1/venv/bin/sat1",
            ]
        )

    seen: set[str] = set()
    for cmd in candidates:
        if cmd in seen:
            continue
        seen.add(cmd)
        if _supports_required_xmos_cli(host, cmd, timeout_s):
            return cmd

    raise SystemExit(
        "Remote sat1 CLI does not support required commands "
        "(xmos get-mic-pipeline-settings, get-doa --stream). "
        "Deploy newer SDK or pass --sat1-cmd with the correct remote binary path."
    )


def _reading_from_stream_line(line: str, key: str) -> DoaReading | None:
    try:
        body = json.loads(line)
        node = body[key]
        return DoaReading(
            doa_mrad=int(node["doa_mrad"]),
            seq=int(node["seq"]),
            valid=int(node["valid"]),
        )
    except Exception:
        return None


class RemoteDoaCollector:
    def __init__(
        self,
        host: str,
        sat1_cmd: str,
        board: str | None,
        period_s: float,
    ) -> None:
        self.host = host
        self.sat1_cmd = sat1_cmd
        self.board = board
        self.period_s = max(0.05, period_s)
        self.proc: subprocess.Popen[str] | None = None
        self._samples: collections.deque[tuple[float, DoaReading, DoaReading]] = (
            collections.deque()
        )
        self._lock = threading.Lock()
        self._running = False

    def start(self) -> None:
        remote_cmd = sat1_xmos_cmd(
            self.sat1_cmd,
            self.board,
            f"get-doa --stream --period-s {self.period_s}",
        )

        self.proc = subprocess.Popen(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                self.host,
                remote_cmd,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._running = True
        threading.Thread(target=self._reader_loop, daemon=True).start()

    def _reader_loop(self) -> None:
        assert self.proc is not None
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            if not self._running:
                break
            raw = _reading_from_stream_line(line.strip(), "raw")
            if raw is None:
                continue
            smooth = _reading_from_stream_line(line.strip(), "smooth")
            if smooth is None:
                smooth = raw
            with self._lock:
                self._samples.append((time.time(), raw, smooth))

    def get_samples_since(
        self, t0: float
    ) -> list[tuple[float, DoaReading, DoaReading]]:
        with self._lock:
            return [(t, r, s) for (t, r, s) in self._samples if t >= t0]

    def stop(self) -> None:
        self._running = False
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()


def expected_angle_for_t(schedule: list[dict], t_s: float) -> float | None:
    for seg in schedule:
        if float(seg["start_s"]) <= t_s < float(seg["end_s"]):
            return float(seg["angle_deg"])
    return None


def expected_segment_index_for_t(schedule: list[dict], t_s: float) -> int | None:
    for i, seg in enumerate(schedule):
        if float(seg["start_s"]) <= t_s < float(seg["end_s"]):
            return i
    return None


def infer_time_offset_s(
    observations: list[dict],
    schedule: list[dict],
    poll_s: float,
    max_abs_offset_s: float,
) -> float:
    if not observations:
        return 0.0

    step = max(0.02, min(0.1, poll_s))
    best_offset = 0.0
    best_score = float("inf")
    k = int(max_abs_offset_s / step)

    for i in range(-k, k + 1):
        off = i * step
        errs: list[float] = []
        for o in observations:
            exp = expected_angle_for_t(schedule, o["t_s"] - off)
            if exp is None:
                continue
            errs.append(angle_err_deg(exp, o["raw_deg"]))
        if not errs:
            continue
        score = sum(errs) / float(len(errs))
        if score < best_score:
            best_score = score
            best_offset = off

    return best_offset


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run generic HIL DoA WAV evaluation and report expected vs estimated angles"
    )
    parser.add_argument("--host", required=True, help="SSH host (e.g. rasp0core2)")
    parser.add_argument("--wav", required=True, help="Local packaged WAV path")
    parser.add_argument(
        "--expected-file", default="", help="Expected schedule JSON path"
    )
    parser.add_argument(
        "--remote-wav", default="/tmp/doa_hil_eval.wav", help="Remote WAV path"
    )
    parser.add_argument("--aplay-dev", default="hw:0,0", help="Remote ALSA device")
    parser.add_argument(
        "--sat1-cmd",
        default=sat1_cmd_default_from_env(),
        help="Remote sat1 command for get-doa polling",
    )
    parser.add_argument(
        "--board",
        default="",
        help="Optional board name for sat1 get-doa",
    )
    parser.add_argument(
        "--mic-map", default="1,2,3,4", help="Mic map CSV (default N,E,S,W lanes)"
    )
    parser.add_argument(
        "--poll-s", type=float, default=0.1, help="Polling period seconds"
    )
    parser.add_argument(
        "--tail-s", type=float, default=0.8, help="Post-playback polling tail seconds"
    )
    parser.add_argument(
        "--analysis-offset-s",
        type=float,
        default=0.0,
        help="Manual time offset for expected schedule alignment (seconds)",
    )
    parser.add_argument(
        "--auto-offset",
        action="store_true",
        help="Automatically infer best time offset from captured raw estimates",
    )
    parser.add_argument(
        "--max-auto-offset-s",
        type=float,
        default=2.0,
        help="Maximum absolute offset searched when --auto-offset is enabled",
    )
    parser.add_argument("--out-json", default="", help="Output report JSON path")
    parser.add_argument(
        "--show-plot", action="store_true", help="Also show live plot GUI during test"
    )
    args = parser.parse_args()

    args.sat1_cmd = resolve_remote_sat1_cmd(args.host, args.sat1_cmd, 10.0)

    wav = Path(args.wav).expanduser().resolve()
    if not wav.is_file():
        print(f"error: wav file not found: {wav}", file=sys.stderr)
        return 2

    expected_path = (
        Path(args.expected_file).expanduser().resolve()
        if args.expected_file
        else wav.with_suffix(".expected.json")
    )
    if not expected_path.is_file():
        print(
            f"error: expected schedule file not found: {expected_path}", file=sys.stderr
        )
        return 2
    schedule = json.loads(expected_path.read_text())
    if not isinstance(schedule, list) or not schedule:
        print("error: expected schedule must be a non-empty JSON list", file=sys.stderr)
        return 2

    with wave.open(str(wav), "rb") as wf:
        duration_s = float(wf.getnframes()) / float(max(wf.getframerate(), 1))

    if args.out_json:
        out_json = Path(args.out_json).expanduser().resolve()
    else:
        out_json = Path(tempfile.gettempdir()) / f"doa_hil_eval_{int(time.time())}.json"

    mic_map = [int(v.strip()) for v in args.mic_map.split(",") if v.strip()]
    if len(mic_map) != 4:
        print("error: --mic-map must have 4 integers", file=sys.stderr)
        return 2

    plot_proc: subprocess.Popen[str] | None = None
    play_proc: subprocess.Popen[str] | None = None
    collector: RemoteDoaCollector | None = None

    original_settings = None
    observations: list[dict] = []
    per_segment: dict[int, dict] = {}

    try:
        get_cmd = sat1_xmos_cmd(
            args.sat1_cmd, args.board, "get-mic-pipeline-settings --json"
        )
        res = run_ssh(args.host, get_cmd, timeout=20)
        if res.returncode != 0:
            print(res.stdout + res.stderr, file=sys.stderr)
            return 1
        original_settings = json.loads(
            [ln for ln in res.stdout.splitlines() if ln.strip()][-1]
        )

        set_payload = {
            "mic_input": {
                "mic_source_mode": 1,
                "mic_input_channel_map": mic_map,
            }
        }
        set_cmd = (
            f"{sat1_xmos_cmd(args.sat1_cmd, args.board, 'set-mic-pipeline-settings')} --json "
            f"{shlex.quote(json.dumps(set_payload, separators=(',', ':')))}"
        )
        res = run_ssh(args.host, set_cmd, timeout=20)
        if res.returncode != 0:
            print(res.stdout + res.stderr, file=sys.stderr)
            return 1

        scp = subprocess.run(
            ["scp", str(wav), f"{args.host}:{args.remote_wav}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if scp.returncode != 0:
            print(scp.stdout + scp.stderr, file=sys.stderr)
            return 1

        if args.show_plot:
            plot_proc = subprocess.Popen(
                [
                    sys.executable,
                    str(
                        Path(__file__).resolve().parents[1]
                        / "doa"
                        / "plot_doa_gui_stream.py"
                    ),
                    "--expected-file",
                    str(expected_path),
                ],
                cwd=Path(__file__).resolve().parents[2],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            time.sleep(0.6)
            if plot_proc.poll() is not None:
                pout, perr = plot_proc.communicate(timeout=2)
                print("warning: GUI plot process exited early", file=sys.stderr)
                if pout.strip():
                    print("--- plot stdout ---", file=sys.stderr)
                    print(
                        pout, file=sys.stderr, end="" if pout.endswith("\n") else "\n"
                    )
                if perr.strip():
                    print("--- plot stderr ---", file=sys.stderr)
                    print(
                        perr, file=sys.stderr, end="" if perr.endswith("\n") else "\n"
                    )
                plot_proc = None

        collector = RemoteDoaCollector(
            args.host, args.sat1_cmd, args.board, args.poll_s
        )
        collector.start()
        warmup_deadline = time.time() + 6.0
        while time.time() < warmup_deadline:
            if collector.get_samples_since(0.0):
                break
            time.sleep(0.05)

        aplay_cmd = f"aplay -D {args.aplay_dev} -f S32_LE -r 48000 -c 2 {shlex.quote(args.remote_wav)}"
        play_proc = subprocess.Popen(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                args.host,
                aplay_cmd,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        t0 = time.time()
        play_deadline = t0 + duration_s + 10.0
        emitted_count = 0
        while time.time() < play_deadline and play_proc.poll() is None:
            if (
                collector is not None
                and args.show_plot
                and plot_proc is not None
                and plot_proc.stdin is not None
            ):
                samples = collector.get_samples_since(t0)
                for t_abs, raw, smooth in samples[emitted_count:]:
                    t_rel = t_abs - t0
                    raw_deg = wrap_deg(math.degrees(raw.doa_mrad / 1000.0))
                    smooth_deg = wrap_deg(math.degrees(smooth.doa_mrad / 1000.0))
                    row = {
                        "t_s": t_rel,
                        "raw_deg": raw_deg,
                        "smooth_deg": smooth_deg,
                        "raw_seq": raw.seq,
                        "smooth_seq": smooth.seq,
                    }
                    try:
                        plot_proc.stdin.write(json.dumps(row) + "\n")
                    except Exception:
                        pass
                emitted_count = len(samples)
                try:
                    plot_proc.stdin.flush()
                except Exception:
                    pass
            time.sleep(0.05)

        if play_proc.poll() is None:
            play_proc.terminate()

        time.sleep(max(args.tail_s, 0.0))

        if collector is not None:
            for t_abs, raw, smooth in collector.get_samples_since(t0):
                t_rel = t_abs - t0
                exp = expected_angle_for_t(schedule, t_rel)
                if exp is None:
                    continue
                if not (raw.valid and smooth.valid):
                    continue
                raw_deg = wrap_deg(math.degrees(raw.doa_mrad / 1000.0))
                smooth_deg = wrap_deg(math.degrees(smooth.doa_mrad / 1000.0))
                observations.append(
                    {
                        "t_s": t_rel,
                        "expected_deg": exp,
                        "raw_deg": raw_deg,
                        "smooth_deg": smooth_deg,
                        "raw_seq": raw.seq,
                        "smooth_seq": smooth.seq,
                    }
                )

        out, err = play_proc.communicate(timeout=10)
        if play_proc.returncode not in (0, None):
            print(out + err, file=sys.stderr)

        analysis_offset_s = args.analysis_offset_s
        if args.auto_offset:
            analysis_offset_s = infer_time_offset_s(
                observations,
                schedule,
                args.poll_s,
                max(args.max_auto_offset_s, 0.0),
            )

        buckets: dict[int, list[dict]] = {i: [] for i in range(len(schedule))}
        for o in observations:
            idx = expected_segment_index_for_t(schedule, o["t_s"] - analysis_offset_s)
            if idx is None:
                continue
            buckets[idx].append(o)

        for i, seg in enumerate(schedule):
            start_s = float(seg["start_s"])
            end_s = float(seg["end_s"])
            expected_deg = float(seg["angle_deg"])
            in_seg = buckets.get(i, [])
            raw_vals = [o["raw_deg"] for o in in_seg]
            smooth_vals = [o["smooth_deg"] for o in in_seg]
            raw_mean = circular_mean_deg(raw_vals) if raw_vals else None
            smooth_mean = circular_mean_deg(smooth_vals) if smooth_vals else None
            per_segment[i] = {
                "start_s": start_s,
                "end_s": end_s,
                "expected_deg": expected_deg,
                "sample_count": len(in_seg),
                "raw_mean_deg": raw_mean,
                "raw_err_deg": None
                if raw_mean is None
                else angle_err_deg(expected_deg, raw_mean),
                "smooth_mean_deg": smooth_mean,
                "smooth_err_deg": None
                if smooth_mean is None
                else angle_err_deg(expected_deg, smooth_mean),
            }

        print("\nDoA HIL evaluation summary")
        print(f"- analysis_offset_s={analysis_offset_s:.3f}")
        for idx in sorted(per_segment.keys()):
            s = per_segment[idx]
            raw_mean_txt = (
                "NA" if s["raw_mean_deg"] is None else f"{s['raw_mean_deg']:.2f}"
            )
            raw_err_txt = (
                "NA" if s["raw_err_deg"] is None else f"{s['raw_err_deg']:.2f}"
            )
            smooth_mean_txt = (
                "NA" if s["smooth_mean_deg"] is None else f"{s['smooth_mean_deg']:.2f}"
            )
            smooth_err_txt = (
                "NA" if s["smooth_err_deg"] is None else f"{s['smooth_err_deg']:.2f}"
            )
            print(
                f"- seg {idx}: exp={s['expected_deg']:.2f} "
                f"raw={raw_mean_txt} "
                f"raw_err={raw_err_txt} "
                f"smooth={smooth_mean_txt} "
                f"smooth_err={smooth_err_txt} "
                f"samples={s['sample_count']}"
            )

        report = {
            "host": args.host,
            "wav": str(wav),
            "expected_file": str(expected_path),
            "remote_wav": args.remote_wav,
            "mic_map": mic_map,
            "poll_s": args.poll_s,
            "duration_s": duration_s,
            "analysis_offset_s": analysis_offset_s,
            "auto_offset": bool(args.auto_offset),
            "observations_count": len(observations),
            "segments": [per_segment[i] for i in sorted(per_segment.keys())],
            "original_settings": original_settings,
        }
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(report, indent=2) + "\n")
        print(f"\nWrote report: {out_json}")
        return 0

    finally:
        if collector is not None:
            collector.stop()

        if plot_proc is not None:
            if plot_proc.stdin is not None:
                try:
                    plot_proc.stdin.close()
                except Exception:
                    pass
            if plot_proc.poll() is None:
                plot_proc.terminate()
                try:
                    plot_proc.wait(timeout=3)
                except Exception:
                    plot_proc.kill()

        run_ssh(
            args.host,
            f"pkill -f 'aplay .*{shlex.quote(Path(args.remote_wav).name)}' >/dev/null 2>&1 || true; rm -f {shlex.quote(args.remote_wav)}",
            timeout=8,
        )

        if original_settings is not None:
            mic_input = original_settings.get("mic_input", {})
            restore_payload = {
                "mic_input": {
                    "mic_source_mode": int(mic_input["mic_source_mode"]),
                    "ref_source_mode": int(mic_input["ref_source_mode"]),
                    "mic_input_channel_map": [
                        int(v) for v in mic_input["mic_input_channel_map"]
                    ],
                    "ref_input_channel_map": [
                        int(v) for v in mic_input["ref_input_channel_map"]
                    ],
                }
            }
            restore_cmd = (
                f"{sat1_xmos_cmd(args.sat1_cmd, args.board, 'set-mic-pipeline-settings')} --json "
                f"{shlex.quote(json.dumps(restore_payload, separators=(',', ':')))}"
            )
            run_ssh(args.host, restore_cmd, timeout=15)


if __name__ == "__main__":
    raise SystemExit(main())
