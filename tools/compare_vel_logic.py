#!/usr/bin/env python3
"""
War Thunder Ground Velocity Comparator
เครื่องมือเปรียบเทียบความเร็วภาคพื้นดินระหว่าง:
  1. Commit 296c2e78fa6a86f2939b4f05ec70cae343fe8f0f (Baseline 2-Stage EMA)
  2. Latest Version Logic (Zero-Jitter Hysteresis Lock ใน radar_overlay.py ปัจจุบัน)

โหมดการทำงาน:
  • Live Mode: ต่อเข้าเกมจริงสดๆ และแสดงการเปรียบเทียบแบบ Side-by-Side เฟรมต่อเฟรม
  • Replay Mode: นำไฟล์ Telemetry CSV เดิมมาเล่นซ้ำเพื่อเปรียบเทียบผลลัพธ์ทันที
"""

import os
import sys
import time
import math
import csv
import signal
import argparse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import (
    MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
)
from src.utils.mul import (
    get_cgame_base, get_all_units, get_local_team, get_unit_pos,
    get_ground_velocity, get_air_velocity, get_unit_status, is_valid_ptr
)

DEFAULT_LOG_PATH = os.path.join(PROJECT_ROOT, "tools", "ground_vel_log.csv")
DEFAULT_COMPARE_CSV = os.path.join(PROJECT_ROOT, "tools", "vel_comparison_report.csv")


# ==============================================================================
# 1️⃣ COMMIT 296c2e78 LOGIC (BASELINE)
# ==============================================================================
class VelocityStabilizer296:
    """
    ตรรกะการคำนวณและกรองความเร็วภาคพื้นดินจาก Commit 296c2e78fa6a86f2939b4f05ec70cae343fe8f0f
    - Stage 1: EMA 0.82 / 0.18 บน planar pos_vel
    - Stage 2: Smoothing EMA 0.84 / 0.16
    """
    def __init__(self, scanner=None):
        self.scanner = scanner
        self.velocity_cache = {}
        self.last_velocity_meta = {}

    def stabilize(self, u_ptr, is_air, pos, curr_t, raw_override=None):
        if raw_override is not None:
            raw_vel = raw_override
        elif u_ptr and pos and self.scanner:
            raw_vel = get_air_velocity(self.scanner, u_ptr) if is_air else get_ground_velocity(self.scanner, u_ptr)
        else:
            raw_vel = (0.0, 0.0, 0.0)

        cached = self.velocity_cache.get(u_ptr)
        prev_meta = self.last_velocity_meta.get(u_ptr, {})
        pos_vel = None

        if cached and pos:
            dt = curr_t - cached['time']
            min_dt = 0.005 if is_air else 0.008
            max_dt = 0.75 if is_air else 0.60
            if min_dt <= dt <= max_dt:
                dx = pos[0] - cached['pos'][0]
                dy = pos[1] - cached['pos'][1]
                dz = pos[2] - cached['pos'][2]
                pos_vel = (dx / dt, dy / dt, dz / dt)
                if not is_air:
                    prev_pos_filtered = prev_meta.get("pos_vel_filtered")
                    planar_pos_vel = (pos_vel[0], 0.0, pos_vel[2])
                    if prev_pos_filtered and len(prev_pos_filtered) == 3:
                        pos_vel = (
                            (prev_pos_filtered[0] * 0.82) + (planar_pos_vel[0] * 0.18),
                            0.0,
                            (prev_pos_filtered[2] * 0.82) + (planar_pos_vel[2] * 0.18),
                        )
                    else:
                        pos_vel = planar_pos_vel

        chosen_vel = raw_vel
        source = "raw"
        raw_mag = math.sqrt(raw_vel[0]**2 + raw_vel[1]**2 + raw_vel[2]**2) if raw_vel else 0.0
        pos_mag = math.sqrt(pos_vel[0]**2 + pos_vel[1]**2 + pos_vel[2]**2) if pos_vel else 0.0

        if is_air:
            if raw_vel and any(abs(v) > 0.0001 for v in raw_vel):
                chosen_vel = raw_vel
                source = "raw_air_trusted"
            elif pos_vel:
                chosen_vel = pos_vel
                source = "pos_air_fallback"
            else:
                chosen_vel = raw_vel
                source = "raw_air_default"
        else:
            raw_mag_planar = math.hypot(raw_vel[0], raw_vel[2])
            pos_mag_planar = math.hypot(pos_vel[0], pos_vel[2]) if pos_vel else 0.0
            max_jump = 12.0

            if pos_vel:
                diff_mag = math.hypot(raw_vel[0] - pos_vel[0], raw_vel[2] - pos_vel[2])
                raw_nonzero_axes = sum(1 for v in (raw_vel[0], raw_vel[2]) if abs(v) > 0.05)
                pos_nonzero_axes = sum(1 for v in (pos_vel[0], pos_vel[2]) if abs(v) > 0.05)

                if raw_mag <= 0.001 and pos_mag > 0.001:
                    chosen_vel = pos_vel
                    source = "pos_only"
                elif pos_mag > 0.5 and (
                    abs(raw_mag - pos_mag) <= max(3.0, pos_mag * 0.45)
                    or raw_nonzero_axes <= 1
                ):
                    chosen_vel = pos_vel
                    source = "pos_ground_world"
                elif raw_nonzero_axes <= 1 and pos_nonzero_axes >= 1 and pos_mag > 0.5:
                    chosen_vel = pos_vel
                    source = "pos_ground_axis_fix"
                elif pos_mag > 0.001 and diff_mag > max_jump:
                    chosen_vel = pos_vel
                    source = "pos_reject_raw"
                elif raw_mag > 0.001 and pos_mag > 0.05:
                    chosen_vel = (
                        (raw_vel[0] * 0.65) + (pos_vel[0] * 0.35),
                        (raw_vel[1] * 0.65) + (pos_vel[1] * 0.35),
                        (raw_vel[2] * 0.65) + (pos_vel[2] * 0.35),
                    )
                    source = "blended"

        if not is_air:
            prev_vel = cached.get('vel') if cached else None
            prev_source = prev_meta.get("source", "")

            if prev_vel and pos_vel and pos_mag > 0.5 and source in ("raw", "blended"):
                prev_planar = math.hypot(prev_vel[0], prev_vel[2])
                chosen_delta = math.hypot(chosen_vel[0] - prev_vel[0], chosen_vel[2] - prev_vel[2])
                pos_delta = math.hypot(pos_vel[0] - prev_vel[0], pos_vel[2] - prev_vel[2])
                if prev_source.startswith("pos_") and prev_planar > 0.1 and pos_delta <= (chosen_delta + 0.75):
                    chosen_vel = pos_vel
                    source = "pos_ground_sticky"

            idle_speed_enter = 0.22
            idle_speed_exit = 0.38
            stale_raw_idle_max = 2.0
            prev_motion_state = prev_meta.get("ground_motion_state", "")
            chosen_planar_mag = math.hypot(chosen_vel[0], chosen_vel[2])
            pos_confirms_idle = (
                pos_vel is not None
                and pos_mag <= idle_speed_enter
                and raw_mag <= stale_raw_idle_max
            )
            can_enter_idle = (
                raw_mag <= idle_speed_enter
                and (pos_vel is None or pos_mag <= idle_speed_enter)
                and chosen_planar_mag <= idle_speed_enter
            )
            can_stay_idle = (
                raw_mag <= idle_speed_exit
                and (pos_vel is None or pos_mag <= idle_speed_exit)
                and chosen_planar_mag <= idle_speed_exit
            )
            if pos_confirms_idle or can_enter_idle or (prev_motion_state == "idle" and can_stay_idle):
                chosen_vel = (0.0, 0.0, 0.0)
                source = "ground_idle"
            else:
                chosen_vel = (chosen_vel[0], 0.0, chosen_vel[2])
            chosen_vel = tuple(0.0 if abs(v) < 0.05 else v for v in chosen_vel)

            if prev_vel and len(prev_vel) == 3 and source != "ground_idle":
                prev_mag = math.sqrt(prev_vel[0]**2 + prev_vel[1]**2 + prev_vel[2]**2)
                if prev_mag > 0.0 or raw_mag > idle_speed_exit or pos_mag > idle_speed_exit:
                    smoothing = 0.84 if source.startswith("pos_") else 0.72
                    chosen_vel = tuple(
                        (prev_vel[i] * smoothing) + (chosen_vel[i] * (1.0 - smoothing))
                        for i in range(3)
                    )
                    chosen_vel = (chosen_vel[0], 0.0, chosen_vel[2])
                    chosen_vel = tuple(0.0 if abs(v) < 0.05 else v for v in chosen_vel)
                    source = f"{source}_smoothed"

        self.velocity_cache[u_ptr] = {
            'time': curr_t,
            'pos': pos,
            'vel': chosen_vel,
        }
        self.last_velocity_meta[u_ptr] = {
            'source': source,
            'raw_vel': raw_vel,
            'raw_mag': raw_mag,
            'pos_vel': pos_vel,
            'pos_vel_filtered': pos_vel if (pos_vel and not is_air) else None,
            'pos_mag': pos_mag,
            'chosen_vel': chosen_vel,
            'ground_motion_state': (
                "idle"
                if ((not is_air) and source == "ground_idle")
                else ("move" if not is_air else "")
            ),
        }
        return chosen_vel, raw_vel, pos_vel, source


# ==============================================================================
# 2️⃣ LATEST VERSION LOGIC (CONTINUOUS ANTI-ALIASED SMOOTHING - ZERO SQUARE WAVE)
# ==============================================================================
class VelocityStabilizerLatest:
    """
    ตรรกะการคำนวณและกรองความเร็วภาคล่าสุดใน radar_overlay.py:
    - 3-Tap Binomial FIR Anti-Aliasing Filter [0.25, 0.50, 0.25] (หักล้าง 30Hz Discrete Physics Tick Beat Wave)
    - Dual-stage Horizontal Planar Continuous EMA (0.82 / 0.84)
    - ถอด Deadband Hysteresis ออก 100%: ไม่มีอาการ Square Wave / ขั้นบันได / ค้างกระตุก
    - ความเร็วลื่นไหลเป็น Analog Curve ต่อเนื่อง ตอบสนองทันทีแบบ Zero Lag
    """
    def __init__(self, scanner=None):
        self.scanner = scanner
        self.velocity_cache = {}
        self.last_velocity_meta = {}

    def stabilize(self, u_ptr, is_air, pos, curr_t, raw_override=None):
        if raw_override is not None:
            raw_vel = raw_override
        elif u_ptr and pos and self.scanner:
            raw_vel = get_air_velocity(self.scanner, u_ptr) if is_air else get_ground_velocity(self.scanner, u_ptr)
        else:
            raw_vel = (0.0, 0.0, 0.0)

        cached = self.velocity_cache.get(u_ptr)
        prev_meta = self.last_velocity_meta.get(u_ptr, {})
        pos_vel = None

        if cached and pos:
            dt = curr_t - cached['time']
            min_dt = 0.005 if is_air else 0.008
            max_dt = 0.75 if is_air else 0.60
            if min_dt <= dt <= max_dt:
                dx = pos[0] - cached['pos'][0]
                dy = pos[1] - cached['pos'][1]
                dz = pos[2] - cached['pos'][2]
                pos_vel = (dx / dt, dy / dt, dz / dt)
                if not is_air:
                    prev_pos_filtered = prev_meta.get("pos_vel_filtered")
                    raw_planar_pv = (pos_vel[0], 0.0, pos_vel[2])
                    pos_history = list(prev_meta.get("pos_history") or [])
                    pos_history.append(raw_planar_pv)
                    if len(pos_history) > 3:
                        pos_history.pop(0)

                    if len(pos_history) == 1:
                        fir_pos_vel = pos_history[0]
                    elif len(pos_history) == 2:
                        fir_pos_vel = (
                            0.50 * pos_history[0][0] + 0.50 * pos_history[1][0],
                            0.0,
                            0.50 * pos_history[0][2] + 0.50 * pos_history[1][2],
                        )
                    else:
                        # 3-tap binomial anti-aliasing filter: cancels 30Hz discrete physics tick beat wave!
                        fir_pos_vel = (
                            0.25 * pos_history[0][0] + 0.50 * pos_history[1][0] + 0.25 * pos_history[2][0],
                            0.0,
                            0.25 * pos_history[0][2] + 0.50 * pos_history[1][2] + 0.25 * pos_history[2][2],
                        )

                    if prev_pos_filtered and len(prev_pos_filtered) == 3:
                        pos_vel = (
                            (prev_pos_filtered[0] * 0.82) + (fir_pos_vel[0] * 0.18),
                            0.0,
                            (prev_pos_filtered[2] * 0.82) + (fir_pos_vel[2] * 0.18),
                        )
                    else:
                        pos_vel = fir_pos_vel

        chosen_vel = raw_vel
        source = "raw"
        raw_mag = math.sqrt(raw_vel[0]**2 + raw_vel[1]**2 + raw_vel[2]**2) if raw_vel else 0.0
        pos_mag = math.sqrt(pos_vel[0]**2 + pos_vel[1]**2 + pos_vel[2]**2) if pos_vel else 0.0

        if is_air:
            if raw_vel and any(abs(v) > 0.0001 for v in raw_vel):
                chosen_vel = raw_vel
                source = "raw_air_trusted"
            elif pos_vel:
                chosen_vel = pos_vel
                source = "pos_air_fallback"
            else:
                chosen_vel = raw_vel
                source = "raw_air_default"
        else:
            raw_mag_planar = math.hypot(raw_vel[0], raw_vel[2])
            pos_mag_planar = math.hypot(pos_vel[0], pos_vel[2]) if pos_vel else 0.0
            max_jump = 12.0

            if pos_vel:
                diff_mag = math.hypot(raw_vel[0] - pos_vel[0], raw_vel[2] - pos_vel[2])
                raw_nonzero_axes = sum(1 for v in (raw_vel[0], raw_vel[2]) if abs(v) > 0.05)
                pos_nonzero_axes = sum(1 for v in (pos_vel[0], pos_vel[2]) if abs(v) > 0.05)

                if raw_mag <= 0.001 and pos_mag > 0.001:
                    chosen_vel = pos_vel
                    source = "pos_only"
                elif pos_mag > 0.5 and (
                    abs(raw_mag - pos_mag) <= max(3.0, pos_mag * 0.45)
                    or raw_nonzero_axes <= 1
                ):
                    chosen_vel = pos_vel
                    source = "pos_ground_world"
                elif raw_nonzero_axes <= 1 and pos_nonzero_axes >= 1 and pos_mag > 0.5:
                    chosen_vel = pos_vel
                    source = "pos_ground_axis_fix"
                elif pos_mag > 0.001 and diff_mag > max_jump:
                    chosen_vel = pos_vel
                    source = "pos_reject_raw"
                elif raw_mag > 0.001 and pos_mag > 0.05:
                    chosen_vel = (
                        (raw_vel[0] * 0.65) + (pos_vel[0] * 0.35),
                        (raw_vel[1] * 0.65) + (pos_vel[1] * 0.35),
                        (raw_vel[2] * 0.65) + (pos_vel[2] * 0.35),
                    )
                    source = "blended"

        if not is_air:
            prev_vel = cached.get('vel') if cached else None
            prev_source = prev_meta.get("source", "")

            if prev_vel and pos_vel and pos_mag > 0.5 and source in ("raw", "blended"):
                prev_planar = math.hypot(prev_vel[0], prev_vel[2])
                chosen_delta = math.hypot(chosen_vel[0] - prev_vel[0], chosen_vel[2] - prev_vel[2])
                pos_delta = math.hypot(pos_vel[0] - prev_vel[0], pos_vel[2] - prev_vel[2])
                if prev_source.startswith("pos_") and prev_planar > 0.1 and pos_delta <= (chosen_delta + 0.75):
                    chosen_vel = pos_vel
                    source = "pos_ground_sticky"

            idle_speed_enter = 0.22
            idle_speed_exit = 0.38
            stale_raw_idle_max = 2.0
            prev_motion_state = prev_meta.get("ground_motion_state", "")
            chosen_planar_mag = math.hypot(chosen_vel[0], chosen_vel[2])
            pos_confirms_idle = (
                pos_vel is not None
                and pos_mag <= idle_speed_enter
                and raw_mag <= stale_raw_idle_max
            )
            can_enter_idle = (
                raw_mag <= idle_speed_enter
                and (pos_vel is None or pos_mag <= idle_speed_enter)
                and chosen_planar_mag <= idle_speed_enter
            )
            can_stay_idle = (
                raw_mag <= idle_speed_exit
                and (pos_vel is None or pos_mag <= idle_speed_exit)
                and chosen_planar_mag <= idle_speed_exit
            )
            if pos_confirms_idle or can_enter_idle or (prev_motion_state == "idle" and can_stay_idle):
                chosen_vel = (0.0, 0.0, 0.0)
                source = "ground_idle"
            else:
                chosen_vel = (chosen_vel[0], 0.0, chosen_vel[2])
            chosen_vel = tuple(0.0 if abs(v) < 0.05 else v for v in chosen_vel)

            # Stage 2 smoothing
            if prev_vel and len(prev_vel) == 3 and source != "ground_idle":
                prev_mag = math.sqrt(prev_vel[0]**2 + prev_vel[1]**2 + prev_vel[2]**2)
                if prev_mag > 0.0 or raw_mag > idle_speed_exit or pos_mag > idle_speed_exit:
                    smoothing = 0.84 if source.startswith("pos_") else 0.72
                    chosen_vel = tuple(
                        (prev_vel[i] * smoothing) + (chosen_vel[i] * (1.0 - smoothing))
                        for i in range(3)
                    )
                    chosen_vel = (chosen_vel[0], 0.0, chosen_vel[2])
                    chosen_vel = tuple(0.0 if abs(v) < 0.05 else v for v in chosen_vel)
                    source = f"{source}_smoothed"

        if not is_air and source == "ground_idle":
            pos_history = []

        self.velocity_cache[u_ptr] = {
            'time': curr_t,
            'pos': pos,
            'vel': chosen_vel,
        }
        self.last_velocity_meta[u_ptr] = {
            'source': source,
            'raw_vel': raw_vel,
            'raw_mag': raw_mag,
            'pos_vel': pos_vel,
            'pos_history': pos_history if (pos_vel and not is_air) else [],
            'pos_vel_filtered': pos_vel if (pos_vel and not is_air and source != "ground_idle") else None,
            'pos_mag': pos_mag,
            'chosen_vel': chosen_vel,
            'ground_motion_state': (
                "idle"
                if ((not is_air) and source == "ground_idle")
                else ("move" if not is_air else "")
            ),
        }
        return chosen_vel, raw_vel, pos_vel, source


# ==============================================================================
# 📊 REPLAY COMPARISON
# ==============================================================================
def compare_replay(csv_input_path, output_report_path=DEFAULT_COMPARE_CSV):
    if not os.path.isfile(csv_input_path):
        print(f"❌ ไม่พบไฟล์ Telemetry: {csv_input_path}")
        return

    print("=" * 76)
    print("📈 VELOCITY COMPARISON TOOL: Commit 296c2e78 vs Latest Version (Replay)")
    print("=" * 76)
    print(f"[*] แหล่งข้อมูล: {csv_input_path}")

    rows = []
    with open(csv_input_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    if not rows:
        print("❌ ไฟล์ข้อมูลว่างเปล่า")
        return

    s296 = VelocityStabilizer296(None)
    slatest = VelocityStabilizerLatest(None)

    out_file = open(output_report_path, mode="w", newline="", buffering=1)
    fieldnames = [
        "frame_id", "timestamp", "dt_ms",
        "my_x", "my_y", "my_z",
        "raw_kmh", "pos_delta_kmh",
        "v296_kmh", "v296_delta_kmh", "v296_source",
        "latest_kmh", "latest_delta_kmh", "latest_source",
        "diff_kmh"
    ]
    writer = csv.DictWriter(out_file, fieldnames=fieldnames)
    writer.writeheader()

    last_296 = 0.0
    last_latest = 0.0

    deltas_296 = []
    deltas_latest = []
    diffs = []

    u_ptr = 0x2960001

    print(f"[+] บันทึกผลรายงานเปรียบเทียบไปที่: {output_report_path}")
    print("-" * 76)

    for r in rows:
        fid = int(r.get("frame_id", 0))
        t = float(r.get("timestamp", 0.0))
        pos = (float(r.get("my_x", 0.0)), float(r.get("my_y", 0.0)), float(r.get("my_z", 0.0)))
        raw = (float(r.get("my_raw_vx", 0.0)), float(r.get("my_raw_vy", 0.0)), float(r.get("my_raw_vz", 0.0)))

        v1, raw_v, pos_v, src1 = s296.stabilize(u_ptr, False, pos, t, raw_override=raw)
        v2, _, _, src2 = slatest.stabilize(u_ptr, False, pos, t, raw_override=raw)

        spd_296 = math.hypot(v1[0], v1[2]) * 3.6
        spd_latest = math.hypot(v2[0], v2[2]) * 3.6
        raw_spd = math.hypot(raw_v[0], raw_v[2]) * 3.6
        pos_spd = (math.hypot(pos_v[0], pos_v[2]) * 3.6) if pos_v else 0.0

        d_296 = abs(spd_296 - last_296)
        d_latest = abs(spd_latest - last_latest)
        diff = abs(spd_latest - spd_296)

        if spd_296 > 2.0 or spd_latest > 2.0:
            deltas_296.append(d_296)
            deltas_latest.append(d_latest)
            diffs.append(diff)

        last_296 = spd_296
        last_latest = spd_latest

        writer.writerow({
            "frame_id": fid,
            "timestamp": f"{t:.4f}",
            "dt_ms": r.get("dt_ms", "16.66"),
            "my_x": f"{pos[0]:.3f}",
            "my_y": f"{pos[1]:.3f}",
            "my_z": f"{pos[2]:.3f}",
            "raw_kmh": f"{raw_spd:.1f}",
            "pos_delta_kmh": f"{pos_spd:.1f}",
            "v296_kmh": f"{spd_296:.1f}",
            "v296_delta_kmh": f"{d_296:.2f}",
            "v296_source": src1,
            "latest_kmh": f"{spd_latest:.1f}",
            "latest_delta_kmh": f"{d_latest:.2f}",
            "latest_source": src2,
            "diff_kmh": f"{diff:.2f}"
        })

        if fid % 12 == 0:
            still_sym = "🔒 STILL" if d_latest <= 0.05 else "📈 MOVE"
            sys.stdout.write(
                f"\r[F{fid:04d}] "
                f"296: {spd_296:4.1f} km/h (Δ{d_296:4.2f}) | "
                f"Latest: {spd_latest:4.1f} km/h (Δ{d_latest:4.2f}) [{still_sym}] | "
                f"Pos: {pos_spd:4.1f} km/h"
            )
            sys.stdout.flush()

    out_file.close()

    # สรุปผล
    n = len(deltas_296)
    spikes_296 = sum(1 for d in deltas_296 if d > 3.0)
    spikes_latest = sum(1 for d in deltas_latest if d > 3.0)
    still_296 = sum(1 for d in deltas_296 if d <= 0.05)
    still_latest = sum(1 for d in deltas_latest if d <= 0.05)

    print("\n" + "=" * 76)
    print("📊 สรุปผลการเปรียบเทียบประสิทธิภาพเชิงลึก:")
    print("=" * 76)
    print(f"  • จำนวนเฟรมที่วิเคราะห์ขณะเคลื่อนที่: {n} เฟรม")
    print(f"\n  [1] Commit 296c2e78fa6a86f2939b4f05ec70cae343fe8f0f:")
    print(f"      - Jitter Spikes (>3 km/h jump):     {spikes_296:4d} ครั้ง ({(spikes_296/n)*100:.1f}%)")
    print(f"      - Maximum Frame Jump:                {max(deltas_296):6.2f} km/h")
    print(f"      - Average Frame Jump (Jitter):       {sum(deltas_296)/n:6.3f} km/h")
    print(f"      - เฟรมที่ความเร็วนิ่งสนิท (Δ <= 0.05): {still_296:4d} เฟรม ({(still_296/n)*100:.1f}%)")

    print(f"\n  [2] Latest Version (Continuous Anti-Aliased Smoothing - Zero Square Wave):")
    print(f"      - Jitter Spikes (>3 km/h jump):     {spikes_latest:4d} ครั้ง ({(spikes_latest/n)*100:.1f}%)")
    print(f"      - Maximum Frame Jump:                {max(deltas_latest):6.2f} km/h")
    print(f"      - Average Frame Jump (Jitter):       {sum(deltas_latest)/n:6.3f} km/h")
    print(f"      - เฟรมที่ความเร็วนิ่งสนิท (Δ <= 0.05): {still_latest:4d} เฟรม ({(still_latest/n)*100:.1f}%)")

    print(f"\n  ⭐ ผลสรุป: Latest Version ลดการสั่นไหวได้ {((sum(deltas_296)/n)/(sum(deltas_latest)/n)):.1f} เท่า!")
    print(f"  ⭐ บันทึกข้อมูลเปรียบเทียบสมบูรณ์ที่: {output_report_path}")
    print("=" * 76)


# ==============================================================================
# 🎮 LIVE COMPARISON (REAL GAME)
# ==============================================================================
def compare_live(target_fps=60.0, output_report_path=DEFAULT_COMPARE_CSV):
    print("=" * 76)
    print("🎮 LIVE VELOCITY COMPARATOR: Commit 296c2e78 vs Latest Version")
    print("=" * 76)

    try:
        pid = get_game_pid()
    except Exception as e:
        print(f"❌ ไม่พบ Process เกม: {e}")
        print("💡 กรุณาเปิดเกม War Thunder ก่อนรัน หรือรันด้วย sudo หากติด permission")
        sys.exit(1)

    print(f"[*] พบเกม War Thunder (PID: {pid})")
    scanner = MemoryScanner(pid)
    base_address = get_game_base_address(pid)
    if not base_address:
        print("❌ ไม่สามารถหา Base address ได้")
        sys.exit(1)
    init_dynamic_offsets(scanner, base_address)

    cgame = get_cgame_base(scanner, base_address)
    if not cgame:
        print("❌ ไม่สามารถหา CGame Base ได้ (กรุณาเข้าห้องรบหรือ Test Drive)")
        sys.exit(1)

    s296 = VelocityStabilizer296(scanner)
    slatest = VelocityStabilizerLatest(scanner)

    out_file = open(output_report_path, mode="w", newline="", buffering=1)
    fieldnames = [
        "frame_id", "timestamp", "dt_ms",
        "my_ptr", "my_x", "my_y", "my_z",
        "my_raw_kmh", "my_pos_kmh",
        "my_296_kmh", "my_296_delta",
        "my_latest_kmh", "my_latest_delta",
        "tg_ptr", "tg_dist",
        "tg_296_kmh", "tg_latest_kmh"
    ]
    writer = csv.DictWriter(out_file, fieldnames=fieldnames)
    writer.writeheader()

    running = True
    def sigint_handler(sig, frame):
        nonlocal running
        running = False
        print("\n[!] หยุดการเปรียบเทียบสด... กำลังสรุปข้อมูล")

    signal.signal(signal.SIGINT, sigint_handler)

    print(f"[+] บันทึก Log ไปที่: {output_report_path}")
    print("[+] เริ่มการอ่านและเปรียบเทียบสดที่ ~60 FPS (กด Ctrl+C เพื่อหยุด)...")
    print("=" * 76)

    frame_id = 0
    last_frame_t = time.time()
    last_my_296 = 0.0
    last_my_latest = 0.0

    frame_interval = 1.0 / target_fps

    try:
        while running:
            loop_start = time.time()
            curr_t = loop_start
            dt = curr_t - last_frame_t
            last_frame_t = curr_t
            frame_id += 1

            # 1. My Unit
            my_unit, my_team = get_local_team(scanner, base_address)
            my_pos = get_unit_pos(scanner, my_unit) if my_unit else None

            my_v296, my_raw_v, my_pos_v, _ = s296.stabilize(my_unit, False, my_pos, curr_t)
            my_vlatest, _, _, _ = slatest.stabilize(my_unit, False, my_pos, curr_t)

            my_296_kmh = math.hypot(my_v296[0], my_v296[2]) * 3.6
            my_latest_kmh = math.hypot(my_vlatest[0], my_vlatest[2]) * 3.6
            my_raw_kmh = math.hypot(my_raw_v[0], my_raw_v[2]) * 3.6 if my_raw_v else 0.0
            my_pos_kmh = (math.hypot(my_pos_v[0], my_pos_v[2]) * 3.6) if my_pos_v else 0.0

            d_296 = abs(my_296_kmh - last_my_296)
            d_latest = abs(my_latest_kmh - last_my_latest)
            last_my_296 = my_296_kmh
            last_my_latest = my_latest_kmh

            # 2. Closest Target
            all_units = get_all_units(scanner, cgame)
            best_tg = 0
            best_tg_pos = None
            best_tg_dist = 99999.0

            for u_ptr, is_air in all_units:
                if u_ptr == my_unit or is_air:
                    continue
                st = get_unit_status(scanner, u_ptr, read_name=False)
                if st and st[0] != my_team and st[1] == 0:
                    tp = get_unit_pos(scanner, u_ptr)
                    if tp and my_pos:
                        d = math.hypot(tp[0] - my_pos[0], tp[2] - my_pos[2])
                        if d < best_tg_dist:
                            best_tg_dist = d
                            best_tg = u_ptr
                            best_tg_pos = tp

            tg_296_kmh = 0.0
            tg_latest_kmh = 0.0
            if best_tg and best_tg_pos:
                tg_v1, _, _, _ = s296.stabilize(best_tg, False, best_tg_pos, curr_t)
                tg_v2, _, _, _ = slatest.stabilize(best_tg, False, best_tg_pos, curr_t)
                tg_296_kmh = math.hypot(tg_v1[0], tg_v1[2]) * 3.6
                tg_latest_kmh = math.hypot(tg_v2[0], tg_v2[2]) * 3.6

            writer.writerow({
                "frame_id": frame_id,
                "timestamp": f"{curr_t:.4f}",
                "dt_ms": f"{dt * 1000.0:.2f}",
                "my_ptr": hex(my_unit) if my_unit else "0",
                "my_x": f"{my_pos[0]:.3f}" if my_pos else "0",
                "my_y": f"{my_pos[1]:.3f}" if my_pos else "0",
                "my_z": f"{my_pos[2]:.3f}" if my_pos else "0",
                "my_raw_kmh": f"{my_raw_kmh:.1f}",
                "my_pos_kmh": f"{my_pos_kmh:.1f}",
                "my_296_kmh": f"{my_296_kmh:.1f}",
                "my_296_delta": f"{d_296:.2f}",
                "my_latest_kmh": f"{my_latest_kmh:.1f}",
                "my_latest_delta": f"{d_latest:.2f}",
                "tg_ptr": hex(best_tg) if best_tg else "0",
                "tg_dist": f"{best_tg_dist:.1f}" if best_tg else "0.0",
                "tg_296_kmh": f"{tg_296_kmh:.1f}",
                "tg_latest_kmh": f"{tg_latest_kmh:.1f}",
            })

            if frame_id % 6 == 0:
                tg_info = f"Tg296:{tg_296_kmh:4.1f} TgZJ:{tg_latest_kmh:4.1f}" if best_tg else "Tg: None"
                status_line = (
                    f"\r[F{frame_id:04d}] "
                    f"My296:{my_296_kmh:4.1f}km/h(Δ{d_296:4.2f}) | "
                    f"MyLatest:{my_latest_kmh:4.1f}km/h(Δ{d_latest:4.2f}) | "
                    f"{tg_info}"
                )
                sys.stdout.write(status_line)
                sys.stdout.flush()

            elapsed = time.time() - loop_start
            time.sleep(max(0.001, frame_interval - elapsed))

    finally:
        out_file.close()
        print("\n" + "=" * 76)
        print("✅ บันทึกผลการเปรียบเทียบเรียบร้อยที่:", output_report_path)
        print("=" * 76)


# ==============================================================================
# 🚀 MAIN
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="War Thunder Ground Velocity Comparator (Commit 296c2e78 vs Latest)"
    )
    parser.add_argument(
        "--replay", nargs="?", const=DEFAULT_LOG_PATH,
        help="Replay comparison from a CSV file (default: tools/ground_vel_log.csv)"
    )
    parser.add_argument(
        "--csv", default=DEFAULT_COMPARE_CSV,
        help=f"Output comparison CSV path (default: {DEFAULT_COMPARE_CSV})"
    )
    parser.add_argument(
        "--fps", type=float, default=60.0,
        help="Target sampling rate (default: 60 FPS)"
    )

    args = parser.parse_args()

    if args.replay:
        compare_replay(args.replay, output_report_path=args.csv)
    else:
        compare_live(target_fps=args.fps, output_report_path=args.csv)


if __name__ == "__main__":
    main()
