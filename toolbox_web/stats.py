"""System stats (htop-style, read from host /proc).

A background thread samples CPU/mem so the API just returns the latest snapshot.
"""

import os
import threading
import time

from flask import Blueprint, jsonify

from .settings import DISK_PATH

bp = Blueprint("stats", __name__)

_stats_lock = threading.Lock()
_stats: dict = {}
_prev_cpu: dict = {}  # cpu-line name → (total_jiffies, idle_jiffies)


def _sample_cpu() -> tuple[dict, int]:
    """Read per-cpu jiffy counters and the running-process count from /proc/stat."""
    times: dict = {}
    running = 0
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("cpu"):
                parts = line.split()
                vals = [int(x) for x in parts[1:]]
                idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
                times[parts[0]] = (sum(vals), idle)
            elif line.startswith("procs_running"):
                running = int(line.split()[1])
    return times, running


def _cpu_percent(name: str, cur: dict, prev: dict) -> float:
    total, idle = cur[name]
    ptotal, pidle = prev.get(name, (total, idle))
    dt = total - ptotal
    if dt <= 0:
        return 0.0
    return max(0.0, min(100.0, (1.0 - (idle - pidle) / dt) * 100.0))


def _read_mem() -> dict:
    info: dict = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, _, rest = line.partition(":")
            info[k] = int(rest.strip().split()[0])  # values are in kB
    total = info.get("MemTotal", 0)
    # htop-style "used": exclude buffers and reclaimable page cache, the way
    # htop's green bar does, so the footer matches what htop reports.
    cache = info.get("Cached", 0) + info.get("SReclaimable", 0) - info.get("Shmem", 0)
    used = total - info.get("MemFree", 0) - info.get("Buffers", 0) - cache
    swt = info.get("SwapTotal", 0)
    swf = info.get("SwapFree", 0)
    return {
        "mem_used_kb": used,
        "mem_total_kb": total,
        "swap_used_kb": swt - swf,
        "swap_total_kb": swt,
    }


def _count_tasks() -> int:
    return sum(1 for e in os.listdir("/proc") if e.isdigit())


def _read_disk() -> dict:
    try:
        st = os.statvfs(DISK_PATH)
    except OSError:
        return {"disk_used_kb": 0, "disk_total_kb": 0, "disk_free_kb": 0}
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize  # available to this user
    used = (st.f_blocks - st.f_bfree) * st.f_frsize  # used by everyone (df semantics)
    return {
        "disk_used_kb": used // 1024,
        "disk_total_kb": total // 1024,
        "disk_free_kb": free // 1024,
    }


def _stats_sampler() -> None:
    global _prev_cpu
    try:
        _prev_cpu, _ = _sample_cpu()
    except Exception:
        _prev_cpu = {}
    while True:
        time.sleep(1.5)
        try:
            cur, running = _sample_cpu()
            cores = []
            i = 0
            while f"cpu{i}" in cur:
                cores.append(round(_cpu_percent(f"cpu{i}", cur, _prev_cpu), 1))
                i += 1
            overall = (
                round(_cpu_percent("cpu", cur, _prev_cpu), 1) if "cpu" in cur else 0.0
            )
            _prev_cpu = cur
            with open("/proc/uptime") as f:
                uptime = float(f.read().split()[0])
            snap = {
                "cpu_overall": overall,
                "cpu_cores": cores,
                "running": running,
                "tasks": _count_tasks(),
                "load": [round(x, 2) for x in os.getloadavg()],
                "uptime": uptime,
                **_read_mem(),
                **_read_disk(),
            }
            with _stats_lock:
                _stats.clear()
                _stats.update(snap)
        except Exception:
            pass


@bp.route("/api/stats")
def api_stats():
    with _stats_lock:
        return jsonify(dict(_stats))
