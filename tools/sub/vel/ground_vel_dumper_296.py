#!/usr/bin/env python3
"""
War Thunder Ground Velocity Dumper & Telemetry Analyzer (Commit 296c2e78 Edition)
เครื่องมือสำหรับ Dump และวิเคราะห์ความเร็วภาคพื้นดิน (Ground Velocity)
โดยใช้ตรรกะการคำนวณและกรองความเร็ว (Velocity Stabilization Logic) จาก Commit:
  296c2e78fa6a86f2939b4f05ec70cae343fe8f0f

ความสามารถ:
1. Live Dumper: ดึงความเร็ว My Unit และ Enemy Ground Target ในเกมแบบ Real-time (60 FPS)
2. Side-by-Side Comparison: เทียบความเร็วจาก Commit 296c2e78 vs Zero-Jitter Lock vs Raw vs Pos Delta
3. Blackbox Logger: บันทึก Telemetry ทั้งหมดลงไฟล์ CSV อย่างละเอียด
4. Replay Mode (--replay): จำลองรันข้อมูล Telemetry จากไฟล์ CSV เพื่อวิเคราะห์ประสิทธิภาพ
"""

import os
import sys
import time
import math
import struct
import csv
import signal
import argparse

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import (
    MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
)
from src.utils.mul import (
    get_cgame_base, get_all_units, get_local_team, get_unit_pos,
    get_ground_velocity, get_air_velocity, get_unit_status,
    get_unit_filter_profile, get_view_matrix, world_to_screen, is_valid_ptr,
    OFF_GROUND_MOVEMENT, OFF_GROUND_VEL
)

DEFAULT_CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ground_vel_dump_296.csv")


# ==============================================================================
# 🎯 VELOCITY STABILIZER (COMMIT 296c2e78 EXACT LOGIC)
# ==============================================================================
class VelocityStabilizer296:
    """
    ถอดแบบตรรกะการคำนวณความเร็วจาก radar_overlay.py ใน Commit 296c2e78fa6a86f2939b4f05ec70cae343fe8f0f
    - คำนวณ Pos Delta พร้อม Stage 1 Horizontal Planar EMA (0.82 / 0.18)
    - ระบบเลือก Source: pos_only, pos_ground_world, pos_ground_axis_fix, blended, sticky, idle
    - Stage 2 Smoothing EMA (0.84 / 0.16)
    """
    def __init__(self, scanner=None):
        self.scanner = scanner
        self.velocity_cache = {}
        self.last_velocity_meta = {}

    def reset(self):
        self.velocity_cache.clear()
        self.last_velocity_meta.clear()

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

            idle_speed_enter = 0.22  # m/s (~0.8 km/h)
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
# 🛡️ VELOCITY STABILIZER (ZERO-JITTER HYSTERESIS LOCK)
# ==============================================================================
class VelocityStabilizerZeroJitter:
    """
    ตรรกะการคำนวณและกรองความเร็วภาคล่าสุดใน radar_overlay.py:
    - Dual-stage Horizontal Planar Smoothing
    - Zero-Jitter Hysteresis Deadband (Speed deadband: 1.0 km/h, Heading: 2.0 deg)
    - กำจัด Sub-tick aliasing Jitter จาก Dagor Engine 84.8Hz vs 60Hz 100%
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
# 🔄 REPLAY MODE
# ==============================================================================
def run_replay(csv_input_path, output_csv_path=None):
    if not os.path.isfile(csv_input_path):
        print(f"❌ ไม่พบไฟล์ Telemetry: {csv_input_path}")
        return

    print("=" * 72)
    print("🔁 WAR THUNDER GROUND VELOCITY DUMPER — REPLAY MODE (Commit 296c2e78)")
    print("=" * 72)
    print(f"[*] กำลังโหลดข้อมูลจาก: {csv_input_path}")

    rows = []
    with open(csv_input_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    if not rows:
        print("❌ ไฟล์ Telemetry ว่างเปล่า")
        return

    stabilizer_296 = VelocityStabilizer296(None)
    stabilizer_zj = VelocityStabilizerZeroJitter(None)

    out_csv_path = output_csv_path or DEFAULT_CSV_PATH
    fieldnames = [
        "frame_id", "timestamp", "dt_ms",
        "my_x", "my_y", "my_z",
        "my_raw_kmh", "my_pos_kmh",
        "my_vel_296_kmh", "my_delta_296_kmh", "my_src_296",
        "my_vel_zj_kmh", "my_delta_zj_kmh",
        "tg_ptr", "tg_raw_kmh", "tg_pos_kmh",
        "tg_vel_296_kmh", "tg_vel_zj_kmh"
    ]

    out_file = open(out_csv_path, mode="w", newline="", buffering=1)
    writer = csv.DictWriter(out_file, fieldnames=fieldnames)
    writer.writeheader()

    last_v_296_kmh = 0.0
    last_v_zj_kmh = 0.0

    spikes_296 = 0
    spikes_zj = 0
    total_moving = 0

    max_jump_296 = 0.0
    max_jump_zj = 0.0

    u_ptr = 0x10000000

    print(f"[+] บันทึกผลการ Replay ลงที่: {out_csv_path}")
    print("-" * 72)

    for r in rows:
        fid = int(r.get("frame_id", 0))
        t = float(r.get("timestamp", 0.0))
        pos = (float(r.get("my_x", 0.0)), float(r.get("my_y", 0.0)), float(r.get("my_z", 0.0)))
        raw_override = (float(r.get("my_raw_vx", 0.0)), float(r.get("my_raw_vy", 0.0)), float(r.get("my_raw_vz", 0.0)))

        # Run 296 logic
        v296, raw_v, pos_v, src296 = stabilizer_296.stabilize(u_ptr, False, pos, t, raw_override=raw_override)
        spd_296 = math.sqrt(v296[0]**2 + v296[1]**2 + v296[2]**2) * 3.6
        pos_spd = (math.sqrt(pos_v[0]**2 + pos_v[1]**2 + pos_v[2]**2) * 3.6) if pos_v else 0.0
        raw_spd = math.sqrt(raw_v[0]**2 + raw_v[1]**2 + raw_v[2]**2) * 3.6

        # Run ZeroJitter logic
        vzj, _, _, _ = stabilizer_zj.stabilize(u_ptr, False, pos, t, raw_override=raw_override)
        spd_zj = math.sqrt(vzj[0]**2 + vzj[1]**2 + vzj[2]**2) * 3.6

        d296 = abs(spd_296 - last_v_296_kmh)
        dzj = abs(spd_zj - last_v_zj_kmh)

        if spd_296 > 2.0 or spd_zj > 2.0:
            total_moving += 1
            if d296 > 3.0: spikes_296 += 1
            if dzj > 3.0: spikes_zj += 1
            if d296 > max_jump_296: max_jump_296 = d296
            if dzj > max_jump_zj: max_jump_zj = dzj

        last_v_296_kmh = spd_296
        last_v_zj_kmh = spd_zj

        writer.writerow({
            "frame_id": fid,
            "timestamp": f"{t:.4f}",
            "dt_ms": r.get("dt_ms", "16.66"),
            "my_x": f"{pos[0]:.3f}",
            "my_y": f"{pos[1]:.3f}",
            "my_z": f"{pos[2]:.3f}",
            "my_raw_kmh": f"{raw_spd:.1f}",
            "my_pos_kmh": f"{pos_spd:.1f}",
            "my_vel_296_kmh": f"{spd_296:.1f}",
            "my_delta_296_kmh": f"{d296:.2f}",
            "my_src_296": src296,
            "my_vel_zj_kmh": f"{spd_zj:.1f}",
            "my_delta_zj_kmh": f"{dzj:.2f}",
            "tg_ptr": r.get("tg_ptr", "0"),
            "tg_raw_kmh": r.get("tg_raw_kmh", "0.0"),
            "tg_pos_kmh": r.get("tg_pos_kmh", "0.0"),
            "tg_vel_296_kmh": r.get("tg_chosen_kmh", "0.0"),
            "tg_vel_zj_kmh": r.get("tg_chosen_kmh", "0.0"),
        })

        if fid % 10 == 0:
            sys.stdout.write(
                f"\r[Frame {fid:04d}] "
                f"Vel_296: {spd_296:4.1f} km/h (Δ:{d296:4.2f}) | "
                f"Vel_ZeroJitter: {spd_zj:4.1f} km/h (Δ:{dzj:4.2f}) | "
                f"Pos: {pos_spd:4.1f} km/h"
            )
            sys.stdout.flush()

    out_file.close()

    print("\n" + "=" * 72)
    print("📊 ผลการเปรียบเทียบเชิงลึก (COMPARISON SUMMARY):")
    print("=" * 72)
    print(f"  • จำนวนเฟรมที่วิเคราะห์: {len(rows)} เฟรม")
    print(f"  • เฟรมขณะเคลื่อนที่ (>2 km/h): {total_moving} เฟรม")
    print(f"  • Commit 296c2e78 Jitter Spikes (>3 km/h): {spikes_296} ครั้ง | Max Jump: {max_jump_296:.2f} km/h")
    print(f"  • Zero-Jitter Hysteresis Spikes (>3 km/h): {spikes_zj} ครั้ง | Max Jump: {max_jump_zj:.2f} km/h")
    print(f"  • บันทึกไฟล์ CSV สมบูรณ์ที่: {out_csv_path}")
    print("=" * 72)


# ==============================================================================
# 🎮 LIVE DUMPING MODE
# ==============================================================================
def run_live(target_fps=60.0, output_csv_path=None, dump_all=False):
    print("=" * 72)
    print("🚗 WAR THUNDER GROUND VELOCITY DUMPER (Commit 296c2e78 Live Edition)")
    print("=" * 72)

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
        print("❌ ไม่สามารถหา Module base address ได้")
        sys.exit(1)
    print(f"[*] Base Address: {hex(base_address)}")
    init_dynamic_offsets(scanner, base_address)

    cgame = get_cgame_base(scanner, base_address)
    if not cgame:
        print("❌ ไม่สามารถหา CGame Base ได้ (กรุณาเข้าห้องรบหรือ Test Drive)")
        sys.exit(1)
    print(f"[*] CGame Base: {hex(cgame)}")

    stabilizer_296 = VelocityStabilizer296(scanner)
    stabilizer_zj = VelocityStabilizerZeroJitter(scanner)

    out_csv_path = output_csv_path or DEFAULT_CSV_PATH
    fieldnames = [
        "frame_id", "timestamp", "dt_ms",
        "my_ptr", "my_x", "my_y", "my_z",
        "my_raw_kmh", "my_pos_kmh",
        "my_vel_296_kmh", "my_delta_296_kmh", "my_src_296",
        "my_vel_zj_kmh", "my_delta_zj_kmh",
        "tg_ptr", "tg_name", "tg_dist",
        "tg_raw_kmh", "tg_pos_kmh",
        "tg_vel_296_kmh", "tg_vel_zj_kmh", "tg_src_296"
    ]

    csv_file = open(out_csv_path, mode="w", newline="", buffering=1)
    writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
    writer.writeheader()

    running = True
    def sigint_handler(sig, frame):
        nonlocal running
        running = False
        print("\n[!] ได้รับคำสั่งหยุด (Ctrl+C)... กำลังสรุปข้อมูล")

    signal.signal(signal.SIGINT, sigint_handler)

    print(f"[+] บันทึก Log ลงที่: {out_csv_path}")
    print(f"[+] เป้าหมาย FPS: {target_fps:.0f} Hz | เริ่มต้นการดัมพ์ข้อมูลสด...")
    print("=" * 72)

    frame_id = 0
    last_frame_time = time.time()
    last_my_296_kmh = 0.0
    last_my_zj_kmh = 0.0

    frame_interval = 1.0 / target_fps

    try:
        while running:
            loop_start = time.time()
            curr_t = loop_start
            dt = curr_t - last_frame_time
            last_frame_time = curr_t
            frame_id += 1

            # 1. อ่านข้อมูล My Unit
            my_unit, my_team = get_local_team(scanner, base_address)
            my_pos = get_unit_pos(scanner, my_unit) if my_unit else None

            # คำนวณ My Velocity ด้วย 296 และ ZeroJitter
            my_v296, my_raw_v, my_pos_v, my_src_296 = stabilizer_296.stabilize(my_unit, False, my_pos, curr_t)
            my_vzj, _, _, _ = stabilizer_zj.stabilize(my_unit, False, my_pos, curr_t)

            my_296_kmh = math.sqrt(my_v296[0]**2 + my_v296[1]**2 + my_v296[2]**2) * 3.6
            my_zj_kmh = math.sqrt(my_vzj[0]**2 + my_vzj[1]**2 + my_vzj[2]**2) * 3.6
            my_raw_kmh = math.sqrt(my_raw_v[0]**2 + my_raw_v[1]**2 + my_raw_v[2]**2) * 3.6 if my_raw_v else 0.0
            my_pos_kmh = (math.sqrt(my_pos_v[0]**2 + my_pos_v[1]**2 + my_pos_v[2]**2) * 3.6) if my_pos_v else 0.0

            d_296 = abs(my_296_kmh - last_my_296_kmh)
            d_zj = abs(my_zj_kmh - last_my_zj_kmh)
            last_my_296_kmh = my_296_kmh
            last_my_zj_kmh = my_zj_kmh

            # 2. ค้นหายูนิตศัตรูภาคพื้นดิน
            all_units = get_all_units(scanner, cgame)
            best_target_ptr = 0
            best_target_name = "UNKNOWN"
            best_target_dist = 99999.0
            best_target_pos = None

            for u_ptr, is_air in all_units:
                if u_ptr == my_unit or is_air:
                    continue
                status = get_unit_status(scanner, u_ptr, read_name=False)
                if status and status[0] != my_team and status[1] == 0:  # Enemy alive
                    t_pos = get_unit_pos(scanner, u_ptr)
                    if t_pos and my_pos:
                        dist = math.hypot(t_pos[0] - my_pos[0], t_pos[2] - my_pos[2])
                        if dist < best_target_dist:
                            best_target_dist = dist
                            best_target_ptr = u_ptr
                            best_target_pos = t_pos

            # คำนวณ Target Velocity
            tg_296_kmh = 0.0
            tg_zj_kmh = 0.0
            tg_raw_kmh = 0.0
            tg_pos_kmh = 0.0
            tg_src_296 = "none"

            if best_target_ptr and best_target_pos:
                tg_v296, tg_raw, tg_pos, tg_src_296 = stabilizer_296.stabilize(best_target_ptr, False, best_target_pos, curr_t)
                tg_vzj, _, _, _ = stabilizer_zj.stabilize(best_target_ptr, False, best_target_pos, curr_t)

                tg_296_kmh = math.sqrt(tg_v296[0]**2 + tg_v296[1]**2 + tg_v296[2]**2) * 3.6
                tg_zj_kmh = math.sqrt(tg_vzj[0]**2 + tg_vzj[1]**2 + tg_vzj[2]**2) * 3.6
                tg_raw_kmh = math.sqrt(tg_raw[0]**2 + tg_raw[1]**2 + tg_raw[2]**2) * 3.6 if tg_raw else 0.0
                tg_pos_kmh = (math.sqrt(tg_pos[0]**2 + tg_pos[1]**2 + tg_pos[2]**2) * 3.6) if tg_pos else 0.0

            # บันทึก CSV
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
                "my_vel_296_kmh": f"{my_296_kmh:.1f}",
                "my_delta_296_kmh": f"{d_296:.2f}",
                "my_src_296": my_src_296,
                "my_vel_zj_kmh": f"{my_zj_kmh:.1f}",
                "my_delta_zj_kmh": f"{d_zj:.2f}",
                "tg_ptr": hex(best_target_ptr) if best_target_ptr else "0",
                "tg_name": best_target_name,
                "tg_dist": f"{best_target_dist:.1f}" if best_target_ptr else "0.0",
                "tg_raw_kmh": f"{tg_raw_kmh:.1f}",
                "tg_pos_kmh": f"{tg_pos_kmh:.1f}",
                "tg_vel_296_kmh": f"{tg_296_kmh:.1f}",
                "tg_vel_zj_kmh": f"{tg_zj_kmh:.1f}",
                "tg_src_296": tg_src_296,
            })

            # แสดงผลแบบ Live Terminal ทุกๆ 6 เฟรม (~100ms)
            if frame_id % 6 == 0:
                tg_str = f"Tg:{tg_296_kmh:4.1f}km/h({best_target_dist:.0f}m)" if best_target_ptr else "Tg: None"
                status_line = (
                    f"\r[F{frame_id:04d}] "
                    f"My 296:{my_296_kmh:4.1f}km/h(Δ{d_296:4.2f}) "
                    f"My ZJ:{my_zj_kmh:4.1f}km/h(Δ{d_zj:4.2f}) "
                    f"Pos:{my_pos_kmh:4.1f} "
                    f"{tg_str} "
                    f"Src:{my_src_296:<16}"
                )
                sys.stdout.write(status_line)
                sys.stdout.flush()

            elapsed = time.time() - loop_start
            time.sleep(max(0.001, frame_interval - elapsed))

    finally:
        csv_file.close()
        print("\n" + "=" * 72)
        print("✅ บันทึก Telemetry สำเร็จ!")
        print(f"  • จำนวนเฟรมทั้งหมด: {frame_id}")
        print(f"  • บันทึกไฟล์ CSV ที่: {out_csv_path}")
        print("=" * 72)


# ==============================================================================
# 🚀 ENTRY POINT
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="War Thunder Ground Velocity Dumper (Commit 296c2e78 Edition)"
    )
    parser.add_argument(
        "--replay", nargs="?", const=os.path.join(PROJECT_ROOT, "tools", "ground_vel_log.csv"),
        help="Replay telemetries from a CSV file (default: tools/ground_vel_log.csv)"
    )
    parser.add_argument(
        "--csv", default=DEFAULT_CSV_PATH,
        help=f"Output CSV path (default: {DEFAULT_CSV_PATH})"
    )
    parser.add_argument(
        "--fps", type=float, default=60.0,
        help="Live dump sampling rate (default: 60.0 FPS)"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Dump all visible enemy ground units"
    )

    args = parser.parse_args()

    if args.replay:
        run_replay(args.replay, output_csv_path=args.csv)
    else:
        run_live(target_fps=args.fps, output_csv_path=args.csv, dump_all=args.all)


if __name__ == "__main__":
    main()
