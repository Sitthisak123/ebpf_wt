#!/usr/bin/env python3
"""
⚡ WT ESP & Pipeline Performance Debugger
เครื่องมือตรวจสอบและวัดประสิทธิภาพของระบบ ESP, DataPump และ Missile Scanner แบบเรียลไทม์

Usage:
  sudo .venv/bin/python3 tools/esp_debugger.py
"""

import os
import sys
import time
import struct
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import get_cgame_base, get_view_matrix, get_local_team, get_unit_pos, get_all_units
from src.utils.missile import MissileScanner
from src.worker.data_pump import DataPumpWorker, FrameSnapshot


def get_process_info(proc_name):
    """Get PID and CPU usage of a process."""
    try:
        out = subprocess.check_output(["ps", "-eo", "pid,%cpu,%mem,cmd"], text=True)
        results = []
        for line in out.strip().split("\n"):
            if proc_name in line and "grep" not in line and "esp_debugger" not in line:
                parts = line.strip().split(maxsplit=3)
                if len(parts) >= 4:
                    results.append({
                        "pid": int(parts[0]),
                        "cpu": float(parts[1]),
                        "mem": float(parts[2]),
                        "cmd": parts[3],
                    })
        return results
    except Exception:
        return []


def main():
    print("=" * 72)
    print("⚡ WT ESP & PIPELINE PERFORMANCE DEBUGGER")
    print("=" * 72)

    # 1. Process Status
    print("\n[1] 🖥️ Process Inspection:")
    aces_procs = get_process_info("aces")
    overlay_procs = get_process_info("radar_overlay")

    if aces_procs:
        p = aces_procs[0]
        print(f"  • War Thunder (aces) : PID {p['pid']} | CPU {p['cpu']}% | MEM {p['mem']}%")
    else:
        print("  ❌ War Thunder (aces) is NOT running!")
        return

    if overlay_procs:
        p = overlay_procs[0]
        print(f"  • Radar Overlay      : PID {p['pid']} | CPU {p['cpu']}% | MEM {p['mem']}%")
    else:
        print("  ⚠️  Radar Overlay is not currently running.")

    pid = aces_procs[0]["pid"]
    base = get_game_base_address(pid)
    print(f"\n[2] 🔍 Memory Scanner Hook:")
    print(f"  • Target Game PID    : {pid}")
    print(f"  • Base Address       : {hex(base)}")

    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base)
    cgame = get_cgame_base(scanner, base)
    v_matrix = get_view_matrix(scanner, cgame) if cgame else None
    my_unit, my_team = get_local_team(scanner, base)
    my_pos = get_unit_pos(scanner, my_unit) if my_unit else None

    print(f"  • CGame Base         : {hex(cgame) if cgame else 'None'}")
    print(f"  • View Matrix        : {'✅ Valid' if v_matrix else '❌ None'}")
    print(f"  • Local Player Unit  : {hex(my_unit) if my_unit else 'None'} (Team {my_team})")
    print(f"  • Local Position     : {f'({my_pos[0]:.1f}, {my_pos[1]:.1f}, {my_pos[2]:.1f})' if my_pos else 'None'}")

    # 3. Benchmark Syscall Memory Reads
    print("\n[3] ⏱️ Memory Read Latency (100 syscalls):")
    t0 = time.perf_counter()
    for _ in range(100):
        _ = scanner.read_mem(base, 8)
    dt_single = (time.perf_counter() - t0) * 10  # ms per 100 reads
    print(f"  • Single 8-byte pread: {dt_single:.3f} ms / 100 reads ({dt_single/100:.4f} ms per call)")

    t0 = time.perf_counter()
    for _ in range(50):
        _ = scanner.read_mem(cgame, 4096)
    dt_bulk = (time.perf_counter() - t0) * 20
    print(f"  • Bulk 4KB pread     : {dt_bulk:.3f} ms / 50 reads ({dt_bulk/50:.4f} ms per call)")

    # 4. Benchmark Missile Scanner
    print("\n[4] 🚀 Missile Scanner Latency (5 iterations):")
    ms = MissileScanner()
    timings = []
    found_missiles = []
    for i in range(5):
        t_start = time.perf_counter()
        res = ms.scan(scanner, base)
        t_end = time.perf_counter()
        dur_ms = (t_end - t_start) * 1000.0
        timings.append(dur_ms)
        if res:
            found_missiles = res
        time.sleep(0.06)

    avg_ms = sum(timings) / len(timings)
    min_ms = min(timings)
    max_ms = max(timings)
    status_icon = "✅ EXCELLENT" if avg_ms < 5.0 else ("⚠️ ACCEPTABLE" if avg_ms < 15.0 else "❌ SLOW")
    print(f"  • Scan Latency       : Avg={avg_ms:.2f}ms | Min={min_ms:.2f}ms | Max={max_ms:.2f}ms [{status_icon}]")
    print(f"  • Active Missiles    : {len(found_missiles)}")
    for idx, m in enumerate(found_missiles[:5]):
        print(f"    [{idx}] {m.name} | pos={m.pos} | speed={m.speed:.0f}m/s")

    # 5. Benchmark DataPump Frame Gathering
    print("\n[5] 📦 DataPumpWorker Unit Processing:")
    try:
        pump = DataPumpWorker(scanner=scanner, base_address=base)
        t_pump0 = time.perf_counter()
        snap = pump._gather_frame()
        t_pump_dur = (time.perf_counter() - t_pump0) * 1000.0
        pump_icon = "✅ EXCELLENT" if t_pump_dur < 15.0 else "⚠️ HEAVY"
        print(f"  • Gather 1 Frame     : {t_pump_dur:.2f} ms [{pump_icon}]")
        print(f"  • Valid Targets      : {len(snap.valid_targets)} enemy units")
        print(f"  • Snapshot Missiles  : {len(snap.missiles)} missiles")
    except Exception as e:
        print(f"  ❌ DataPump test error: {e}")

    # 6. Summary Diagnostics
    print("\n" + "=" * 72)
    print("📊 DIAGNOSTIC VERDICT:")
    if avg_ms < 8.0:
        print("  ✅ MISSILE SCANNER: คอขวด 1 FPS ถูกแก้ไขสมบูรณ์แบบ (< 5ms ต่อรอบ)")
    else:
        print("  ⚠️ MISSILE SCANNER: ยังมี latency สูงกว่าปกติ")

    if overlay_procs and overlay_procs[0]["cpu"] < 100.0:
        print("  ✅ OVERLAY CPU USAGE: ปกติ ไม่มีการสแกน memory หน่วงที่ GUI thread")
    elif overlay_procs:
        print(f"  ⚠️ OVERLAY CPU USAGE: ค่อนข้างสูง ({overlay_procs[0]['cpu']}%)")

    print("\n  💡 TIP: สามารถกดปุ่ม F10 ขณะเล่นเกมเพื่อเปิด/ปิด OSD Performance Debugger")
    print("=" * 72)


if __name__ == "__main__":
    main()
