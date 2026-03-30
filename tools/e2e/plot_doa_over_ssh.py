#!/usr/bin/env python3

import argparse
import json
import math
import re
import signal
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from collections import deque
from dataclasses import dataclass


DOA_RE = re.compile(r"doa_mrad\s*=\s*(-?\d+)")
SEQ_RE = re.compile(r"seq\s*=\s*(\d+)")
VALID_RE = re.compile(r"valid\s*=\s*(\d+)")
STREAM_MARKER = "sat1_doa_stream_marker_v1"


@dataclass
class DoaReading:
    doa_mrad: int
    seq: int
    valid: int

    @property
    def deg(self) -> float:
        return math.degrees(self.doa_mrad / 1000.0)


@dataclass
class ExpectedWindow:
    start_s: float
    end_s: float
    angle_deg: float


def load_expected_windows(path: str | None) -> list[ExpectedWindow]:
    if not path:
        return []
    body = json.loads(Path(path).read_text())
    windows: list[ExpectedWindow] = []
    for row in body:
        windows.append(
            ExpectedWindow(
                start_s=float(row["start_s"]),
                end_s=float(row["end_s"]),
                angle_deg=float(row["angle_deg"]),
            )
        )
    return windows


def expected_angle_at(
    t_s: float,
    windows: list[ExpectedWindow],
    loop: bool,
) -> float | None:
    if not windows:
        return None

    t_eval = t_s
    if loop:
        total = max(w.end_s for w in windows)
        if total > 0:
            t_eval = t_s % total

    for w in windows:
        if w.start_s <= t_eval < w.end_s:
            return w.angle_deg
    return None


def wrap_deg(angle_deg: float) -> float:
    while angle_deg > 180.0:
        angle_deg -= 360.0
    while angle_deg < -180.0:
        angle_deg += 360.0
    return angle_deg


def readings_from_body(body: dict) -> tuple[DoaReading, DoaReading]:
    raw = DoaReading(
        doa_mrad=int(body["raw"]["doa_mrad"]),
        seq=int(body["raw"]["seq"]),
        valid=int(body["raw"]["valid"]),
    )
    smooth = DoaReading(
        doa_mrad=int(body["smooth"]["doa_mrad"]),
        seq=int(body["smooth"]["seq"]),
        valid=int(body["smooth"]["valid"]),
    )
    return raw, smooth


def parse_reading(text: str) -> DoaReading | None:
    doa_match = DOA_RE.search(text)
    seq_match = SEQ_RE.search(text)
    valid_match = VALID_RE.search(text)
    if not doa_match or not seq_match or not valid_match:
        return None
    return DoaReading(
        doa_mrad=int(doa_match.group(1)),
        seq=int(seq_match.group(1)),
        valid=int(valid_match.group(1)),
    )


def fetch_raw_smooth(
    host: str,
    sat1_cmd: str,
    board: str | None,
    timeout_s: float,
    ssh_mux: bool,
    ssh_control_path: str,
) -> tuple[DoaReading | None, DoaReading | None]:
    board_arg = ""
    if board:
        board_arg = f" --board {board}"

    remote_cmd = (
        f"{sat1_cmd} xmos{board_arg} get-doa --mode raw && "
        f"{sat1_cmd} xmos{board_arg} get-doa --mode smooth"
    )

    ssh_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
    if ssh_mux:
        ssh_cmd.extend(
            [
                "-o",
                "ControlMaster=auto",
                "-o",
                "ControlPersist=60",
                "-o",
                f"ControlPath={ssh_control_path}",
            ]
        )
    ssh_cmd.extend([host, remote_cmd])

    try:
        proc = subprocess.run(
            [
                *ssh_cmd,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return None, None

    if proc.returncode != 0:
        return None, None

    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        return None, None

    raw = parse_reading(lines[0])
    smooth = parse_reading(lines[1])
    return raw, smooth


def fetch_raw_smooth_python(
    host: str,
    py_cmd: str,
    timeout_s: float,
    ssh_mux: bool,
    ssh_control_path: str,
) -> tuple[DoaReading | None, DoaReading | None]:
    script = (
        "import json;"
        "from satellite1.sat1_hat import XMOS;"
        "x=XMOS();x.setup();"
        "r=x.get_doa_raw();s=x.get_doa_smooth();"
        "print(json.dumps({'raw':{'doa_mrad':int(r.doa_mrad),'seq':int(r.seq),'valid':int(r.valid)},'smooth':{'doa_mrad':int(s.doa_mrad),'seq':int(s.seq),'valid':int(s.valid)}}));"
        "c=getattr(x,'_cntrl',None);"
        "c.close() if c is not None and hasattr(c,'close') else None"
    )
    cmd_tokens = shlex.split(py_cmd)
    if not cmd_tokens:
        return None, None

    remote_cmd = " ".join(shlex.quote(v) for v in cmd_tokens + ["-c", script])
    ssh_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
    if ssh_mux:
        ssh_cmd.extend(
            [
                "-o",
                "ControlMaster=auto",
                "-o",
                "ControlPersist=60",
                "-o",
                f"ControlPath={ssh_control_path}",
            ]
        )
    ssh_cmd.extend([host, remote_cmd])
    try:
        proc = subprocess.run(
            [*ssh_cmd],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return None, None

    if proc.returncode != 0:
        return None, None

    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        return None, None

    try:
        body = json.loads(lines[-1])
        return readings_from_body(body)
    except Exception:
        return None, None


class RemoteDoaStream:
    def __init__(
        self,
        *,
        host: str,
        py_cmd: str,
        period_s: float,
        ssh_mux: bool,
        ssh_control_path: str,
    ) -> None:
        self.host = host
        self.py_cmd = py_cmd
        self.period_s = max(0.05, period_s)
        self.ssh_mux = ssh_mux
        self.ssh_control_path = ssh_control_path
        self.proc: subprocess.Popen[str] | None = None
        self._latest: tuple[DoaReading, DoaReading] | None = None
        self._latest_monotonic: float = 0.0
        self._latest_lock = threading.Lock()
        self._stderr_tail: deque[str] = deque(maxlen=20)
        self._running = False

    def start(self) -> None:
        cmd_tokens = shlex.split(self.py_cmd)
        if not cmd_tokens:
            raise RuntimeError("--py-cmd resolved to empty command")

        script = f"""
import json
import signal
import time
from satellite1.sat1_hat import XMOS

MARKER = "{STREAM_MARKER}"

period = {self.period_s!r}
running = True

def _handle_stop(_sig, _frm):
    global running
    running = False

signal.signal(signal.SIGTERM, _handle_stop)
signal.signal(signal.SIGINT, _handle_stop)
signal.signal(signal.SIGHUP, _handle_stop)

def open_xmos():
    x = XMOS()
    x.setup()
    _ = x.read_firmware()
    _ = x.wait_until_ready(timeout_s=3.0, poll_interval_s=0.1)
    return x

x = open_xmos()

try:
    while running:
        try:
            r = x.get_doa_raw()
            s = x.get_doa_smooth()
            raw_mrad = int(r.doa_mrad)
            smooth_mrad = int(s.doa_mrad)

            if abs(raw_mrad) > 5000 or abs(smooth_mrad) > 5000:
                time.sleep(period)
                continue

            print(json.dumps({{
                'raw': {{
                    'doa_mrad': raw_mrad,
                    'seq': int(r.seq),
                    'valid': int(r.valid),
                }},
                'smooth': {{
                    'doa_mrad': smooth_mrad,
                    'seq': int(s.seq),
                    'valid': int(s.valid),
                }},
            }}), flush=True)
        except Exception:
            c = getattr(x, '_cntrl', None)
            if c is not None and hasattr(c, 'close'):
                try:
                    c.close()
                except Exception:
                    pass
            if not running:
                break
            time.sleep(period)
            x = open_xmos()
            continue
        time.sleep(period)
finally:
    c = getattr(x, '_cntrl', None)
    if c is not None and hasattr(c, 'close'):
        c.close()
"""
        remote_cmd = " ".join(shlex.quote(v) for v in cmd_tokens + ["-u", "-c", script])

        ssh_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
        if self.ssh_mux:
            ssh_cmd.extend(
                [
                    "-o",
                    "ControlMaster=auto",
                    "-o",
                    "ControlPersist=60",
                    "-o",
                    f"ControlPath={self.ssh_control_path}",
                ]
            )
        ssh_cmd.extend([self.host, remote_cmd])

        kill_prev_cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            self.host,
            f"pkill -f {shlex.quote(STREAM_MARKER)} >/dev/null 2>&1 || true",
        ]
        subprocess.run(kill_prev_cmd, check=False, capture_output=True, text=True)

        self.proc = subprocess.Popen(
            ssh_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._running = True
        threading.Thread(target=self._stdout_loop, daemon=True).start()
        threading.Thread(target=self._stderr_loop, daemon=True).start()

    def _stdout_loop(self) -> None:
        assert self.proc is not None
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                body = json.loads(line)
                parsed = readings_from_body(body)
            except Exception:
                continue
            with self._latest_lock:
                self._latest = parsed
                self._latest_monotonic = time.monotonic()
        self._running = False

    def _stderr_loop(self) -> None:
        assert self.proc is not None
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            line = line.strip()
            if line:
                self._stderr_tail.append(line)

    def latest(self) -> tuple[DoaReading, DoaReading] | None:
        with self._latest_lock:
            return self._latest

    def latest_age_s(self) -> float:
        with self._latest_lock:
            if self._latest is None or self._latest_monotonic <= 0.0:
                return float("inf")
            return max(0.0, time.monotonic() - self._latest_monotonic)

    def is_running(self) -> bool:
        if self.proc is None:
            return False
        return self.proc.poll() is None and self._running

    def stderr_summary(self) -> str:
        if not self._stderr_tail:
            return ""
        return " | ".join(self._stderr_tail)

    def stop(self) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2)
        self._running = False

        kill_prev_cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            self.host,
            f"pkill -f {shlex.quote(STREAM_MARKER)} >/dev/null 2>&1 || true",
        ]
        subprocess.run(kill_prev_cmd, check=False, capture_output=True, text=True)

    def restart(self) -> None:
        self.stop()
        self._latest = None
        self._latest_monotonic = 0.0
        self._stderr_tail.clear()
        self.start()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live DoA plot from remote sat1 CLI over SSH"
    )
    parser.add_argument("--host", required=True, help="SSH host (e.g. rasp0core2)")
    parser.add_argument(
        "--sat1-cmd",
        default="sat1",
        help="Remote sat1 command (default: sat1)",
    )
    parser.add_argument(
        "--py-cmd",
        default="/opt/satellite1/venv/bin/python",
        help="Remote python command for fast mode (default: /opt/satellite1/venv/bin/python)",
    )
    parser.add_argument(
        "--source",
        choices=["stream", "python", "cli"],
        default="stream",
        help="Data source mode: stream is smoothest, python is single-shot, cli is simplest (default: stream)",
    )
    parser.add_argument(
        "--board",
        choices=["satellite1", "sq66"],
        default=None,
        help="Optional board override passed to sat1 xmos",
    )
    parser.add_argument(
        "--poll-s",
        type=float,
        default=0.2,
        help="Polling interval in seconds (default: 0.2)",
    )
    parser.add_argument(
        "--history-s",
        type=float,
        default=30.0,
        help="Seconds of history to display (default: 30)",
    )
    parser.add_argument(
        "--ssh-timeout-s",
        type=float,
        default=8.0,
        help="Per-poll SSH command timeout in seconds (default: 8)",
    )
    parser.add_argument(
        "--no-ssh-mux",
        action="store_true",
        help="Disable SSH connection multiplexing",
    )
    parser.add_argument(
        "--ssh-control-path",
        default="/tmp/plot_doa_mux_%r_%h_%p",
        help="SSH ControlPath template used when multiplexing is enabled",
    )
    parser.add_argument(
        "--expected-file",
        default=None,
        help="Optional JSON file with expected DoA windows: [{'start_s','end_s','angle_deg'}]",
    )
    parser.add_argument(
        "--expected-offset-deg",
        type=float,
        default=0.0,
        help="Optional expected-angle offset compensation in degrees (default: 0)",
    )
    parser.add_argument(
        "--expected-loop",
        action="store_true",
        help="Loop expected schedule over time",
    )
    args = parser.parse_args()

    try:
        import matplotlib.pyplot as plt
        from matplotlib.animation import FuncAnimation
    except Exception as exc:
        print(
            "matplotlib is required. Install with: python3 -m pip install matplotlib",
            file=sys.stderr,
        )
        print(f"Import error: {exc}", file=sys.stderr)
        return 2

    max_points = max(10, int(args.history_s / max(args.poll_s, 0.05)))
    t_hist: deque[float] = deque(maxlen=max_points)
    raw_hist: deque[float] = deque(maxlen=max_points)
    smooth_hist: deque[float] = deque(maxlen=max_points)
    expected_hist: deque[float] = deque(maxlen=max_points)
    expected_windows = load_expected_windows(args.expected_file)

    fig = plt.figure(figsize=(10, 6))
    ax_polar = fig.add_subplot(211, projection="polar")
    ax_ts = fig.add_subplot(212)

    ax_polar.set_theta_zero_location("N")
    ax_polar.set_theta_direction(-1)
    ax_polar.set_ylim(0, 1.0)
    ax_polar.set_yticks([])
    ax_polar.set_title("Live DoA")

    (raw_line,) = ax_polar.plot([], [], color="tab:red", linewidth=3, label="raw")
    (smooth_line,) = ax_polar.plot(
        [], [], color="tab:blue", linewidth=3, label="smooth"
    )
    (expected_line,) = ax_polar.plot(
        [], [], color="tab:green", linewidth=2, linestyle="--", label="expected"
    )
    ax_polar.legend(loc="lower left")

    (ts_raw_line,) = ax_ts.plot([], [], color="tab:red", label="raw")
    (ts_smooth_line,) = ax_ts.plot([], [], color="tab:blue", label="smooth")
    (ts_expected_line,) = ax_ts.plot(
        [], [], color="tab:green", linestyle="--", label="expected"
    )
    ax_ts.set_ylabel("Degrees")
    ax_ts.set_xlabel("Time (s)")
    ax_ts.set_ylim(-190, 190)
    ax_ts.grid(True, alpha=0.3)
    ax_ts.legend(loc="upper right")

    start_t = time.time()
    stream: RemoteDoaStream | None = None
    last_stream_restart_t = 0.0
    last_raw_seq: int | None = None
    last_smooth_seq: int | None = None
    last_raw_change_t = start_t
    last_smooth_change_t = start_t
    if args.source == "stream":
        stream = RemoteDoaStream(
            host=args.host,
            py_cmd=args.py_cmd,
            period_s=args.poll_s,
            ssh_mux=not args.no_ssh_mux,
            ssh_control_path=args.ssh_control_path,
        )
        stream.start()

    def update(_frame):
        nonlocal last_raw_seq, last_smooth_seq, last_raw_change_t, last_smooth_change_t
        nonlocal last_stream_restart_t
        if args.source == "stream":
            assert stream is not None
            now_monotonic = time.monotonic()
            if (not stream.is_running()) and (
                now_monotonic - last_stream_restart_t > 2.0
            ):
                stream.restart()
                last_stream_restart_t = now_monotonic
            latest = stream.latest()
            if latest is None:
                if not stream.is_running():
                    ax_ts.set_title(
                        "stream stopped; check remote python command or SSH "
                        + stream.stderr_summary()
                    )
                return (
                    raw_line,
                    smooth_line,
                    expected_line,
                    ts_raw_line,
                    ts_smooth_line,
                    ts_expected_line,
                )
            if stream.latest_age_s() > max(2.0, (4.0 * args.poll_s)):
                if now_monotonic - last_stream_restart_t > 2.0:
                    stream.restart()
                    last_stream_restart_t = now_monotonic
                ax_ts.set_title("stream stale; attempting restart")
                return (
                    raw_line,
                    smooth_line,
                    expected_line,
                    ts_raw_line,
                    ts_smooth_line,
                    ts_expected_line,
                )
            raw, smooth = latest
        elif args.source == "python":
            raw, smooth = fetch_raw_smooth_python(
                host=args.host,
                py_cmd=args.py_cmd,
                timeout_s=args.ssh_timeout_s,
                ssh_mux=not args.no_ssh_mux,
                ssh_control_path=args.ssh_control_path,
            )
        else:
            raw, smooth = fetch_raw_smooth(
                host=args.host,
                sat1_cmd=args.sat1_cmd,
                board=args.board,
                timeout_s=args.ssh_timeout_s,
                ssh_mux=not args.no_ssh_mux,
                ssh_control_path=args.ssh_control_path,
            )

        if raw is None or smooth is None:
            return (
                raw_line,
                smooth_line,
                expected_line,
                ts_raw_line,
                ts_smooth_line,
                ts_expected_line,
            )

        if not raw.valid or not smooth.valid:
            return (
                raw_line,
                smooth_line,
                expected_line,
                ts_raw_line,
                ts_smooth_line,
                ts_expected_line,
            )

        now = time.time() - start_t
        abs_now = time.time()
        if last_raw_seq is None or raw.seq != last_raw_seq:
            last_raw_change_t = abs_now
            last_raw_seq = raw.seq
        if last_smooth_seq is None or smooth.seq != last_smooth_seq:
            last_smooth_change_t = abs_now
            last_smooth_seq = smooth.seq
        t_hist.append(now)
        raw_hist.append(raw.deg)
        smooth_hist.append(smooth.deg)
        expected_deg = expected_angle_at(now, expected_windows, args.expected_loop)
        if expected_deg is not None:
            expected_deg = wrap_deg(expected_deg + args.expected_offset_deg)
        expected_hist.append(float("nan") if expected_deg is None else expected_deg)

        raw_rad = raw.doa_mrad / 1000.0
        smooth_rad = smooth.doa_mrad / 1000.0
        raw_line.set_data([raw_rad, raw_rad], [0, 1.0])
        smooth_line.set_data([smooth_rad, smooth_rad], [0, 1.0])
        if expected_deg is None:
            expected_line.set_data([], [])
        else:
            expected_line.set_data(
                [math.radians(expected_deg), math.radians(expected_deg)], [0, 1.0]
            )

        t_vals = list(t_hist)
        ts_raw_line.set_data(t_vals, list(raw_hist))
        ts_smooth_line.set_data(t_vals, list(smooth_hist))
        ts_expected_line.set_data(t_vals, list(expected_hist))

        if t_vals:
            ax_ts.set_xlim(max(0, t_vals[0]), max(1.0, t_vals[-1]))

        title = (
            f"latest raw={raw.deg:.1f} deg (seq={raw.seq}) | "
            f"smooth={smooth.deg:.1f} deg (seq={smooth.seq})"
        )
        title += (
            f" | stale raw={abs_now - last_raw_change_t:.1f}s"
            f" smooth={abs_now - last_smooth_change_t:.1f}s"
        )
        if expected_deg is not None:
            title += f" | expected={expected_deg:.1f} deg"
        ax_ts.set_title(title)

        return (
            raw_line,
            smooth_line,
            expected_line,
            ts_raw_line,
            ts_smooth_line,
            ts_expected_line,
        )

    interval_ms = int(max(50, args.poll_s * 1000.0))
    anim = FuncAnimation(
        fig,
        update,
        interval=interval_ms,
        blit=False,
        cache_frame_data=False,
    )
    # Keep a strong reference to avoid garbage collection while the window is open.
    _ = anim
    if stream is not None:
        fig.canvas.mpl_connect("close_event", lambda _evt: stream.stop())
    plt.tight_layout()
    plt.show()
    if stream is not None:
        stream.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
