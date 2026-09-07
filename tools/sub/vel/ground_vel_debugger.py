#!/usr/bin/env python3
"""
Ground Velocity Telemetry Debugger & Dumper
เครื่องมือสำหรับบันทึกและวิเคราะห์ความเร็วภาคพื้นดิน (Ground Velocity) แบบ Real-time เฟรมต่อเฟรม
ใช้ตรวจจับ Jitter Spikes, Staircase Frame (พิกัดค้างในรอบ Tick) และเปรียบเทียบ Memory Raw vs Pos Delta vs Stabilized
"""

import os
import sys
import time
import math
import struct
import csv
import signal

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import (
    get_cgame_base, get_all_units, get_local_team, get_unit_pos, get_ground_velocity,
    get_unit_filter_profile, get_unit_status, is_valid_ptr,
    OFF_GROUND_MOVEMENT, OFF_GROUND_VEL
)

CSV_OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ground_vel_log.csv")

# Class จำลอง _stabilize_velocity แบบเดียวกับ radar_overlay.py เป๊ะๆ
class VelocityStabilizer:
    def __init__(self, scanner):
        self.scanner = scanner
        self.velocity_cache = {}
        self.last_velocity_meta = {}

    def stabilize(self, u_ptr, is_air, pos, curr_t):
        if u_ptr and pos:
            raw_vel = get_ground_velocity(self.scanner, u_ptr) if not is_air else (0.0, 0.0, 0.0)
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
                    # World-space ground lead uses X/Z as horizontal motion; Y is height and must stay zero.
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

        if not is_air:
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

            prev_vel = cached.get('vel') if cached else None
            prev_source = prev_meta.get("source", "")

            if prev_vel and pos_vel and pos_mag > 0.5 and source in ("raw", "blended"):
                prev_planar = math.hypot(prev_vel[0], prev_vel[2])
                chosen_delta = math.hypot(chosen_vel[0] - prev_vel[0], chosen_vel[2] - prev_vel[2])
                pos_delta = math.hypot(pos_vel[0] - prev_vel[0], pos_vel[2] - prev_vel[2])
                if prev_source.startswith("pos_") and prev_planar > 0.1 and pos_delta <= (chosen_delta + 0.75):
                    chosen_vel = pos_vel
                    source = "pos_ground_sticky"

            # Ground lead solver should not react to height/slope noise as vertical motion.
            chosen_vel = (chosen_vel[0], 0.0, chosen_vel[2])
            chosen_vel = tuple(0.0 if abs(v) < 0.05 else v for v in chosen_vel)

            # Ground world velocity is derived from noisy local raw fields + short-frame position deltas.
            # Smooth the final vector to prevent source flapping and visible jitter on moving vehicles.
            if prev_vel and len(prev_vel) == 3:
                prev_mag = math.sqrt(prev_vel[0]**2 + prev_vel[1]**2 + prev_vel[2]**2)
                if prev_mag > 0.0 or raw_mag > 0.05 or pos_mag > 0.05:
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
            'ground_motion_state': "move" if not is_air else "",
        }
        return chosen_vel, raw_vel, pos_vel, source


def replay_csv(csv_path=CSV_OUTPUT_PATH):
    if not os.path.isfile(csv_path):
        print(f"❌ ไม่พบไฟล์ log สำหรับ replay: {csv_path}")
        return
    print(f"[+] Replaying telemetry from: {csv_path}")
    with open(csv_path, mode="r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("❌ ไฟล์ log ว่างเปล่า")
        return

    stabilizer = VelocityStabilizer(None)
    global get_ground_velocity
    orig_get_ground_vel = get_ground_velocity
    get_ground_velocity = lambda s, u: (0.0, 0.0, 0.0)

    out_rows = []
    fieldnames = list(rows[0].keys())

    staircase_count = 0
    jitter_spike_count = 0
    total_moving_frames = 0
    last_my_pos = None
    last_my_chosen_kmh = 0.0

    u_ptr = 0x12345678

    for r in rows:
        frame_id = int(r["frame_id"])
        curr_t = float(r["timestamp"])
        pos = (float(r["my_x"]), float(r["my_y"]), float(r["my_z"]))

        chosen_vel, raw_vel, pos_vel, source = stabilizer.stabilize(u_ptr, False, pos, curr_t)
        my_chosen_kmh = math.sqrt(chosen_vel[0]**2 + chosen_vel[1]**2 + chosen_vel[2]**2) * 3.6
        my_pos_kmh = (math.sqrt(pos_vel[0]**2 + pos_vel[1]**2 + pos_vel[2]**2) * 3.6) if pos_vel else 0.0

        is_staircase = False
        if last_my_pos and my_chosen_kmh > 2.0:
            pos_disp = math.hypot(pos[0] - last_my_pos[0], pos[2] - last_my_pos[2])
            if pos_disp < 0.001:
                is_staircase = True
                staircase_count += 1

        speed_jump = abs(my_chosen_kmh - last_my_chosen_kmh)
        if my_chosen_kmh > 2.0 and speed_jump > 3.0:
            jitter_spike_count += 1

        if my_chosen_kmh > 2.0:
            total_moving_frames += 1

        last_my_pos = pos
        last_my_chosen_kmh = my_chosen_kmh

        r_copy = dict(r)
        r_copy["my_pos_kmh"] = f"{my_pos_kmh:.1f}"
        r_copy["my_chosen_vx"] = f"{chosen_vel[0]:.2f}"
        r_copy["my_chosen_vy"] = f"{chosen_vel[1]:.2f}"
        r_copy["my_chosen_vz"] = f"{chosen_vel[2]:.2f}"
        r_copy["my_chosen_kmh"] = f"{my_chosen_kmh:.1f}"
        r_copy["my_source"] = source
        r_copy["my_is_staircase"] = 1 if is_staircase else 0
        r_copy["my_speed_delta_kmh"] = f"{speed_jump:.2f}"
        out_rows.append(r_copy)

        if frame_id % 6 == 0:
            status_line = (
                f"\r[Frame {frame_id:04d}] "
                f"MyVel: {my_chosen_kmh:4.1f} km/h (Pos:{my_pos_kmh:4.1f}) "
                f"Src: {source:<18} "
                f"Staircase: {staircase_count} "
                f"Spikes: {jitter_spike_count}"
            )
            sys.stdout.write(status_line)
            sys.stdout.flush()

    get_ground_velocity = orig_get_ground_vel

    with open(csv_path, mode="w", newline="", buffering=1) as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    print("\n" + "=" * 70)
    print("📊 สรุปผลการวิเคราะห์ TELEMETRY (ZERO-JITTER STABILIZER REPLAY):")
    print("=" * 70)
    print(f"  • จำนวนเฟรมทั้งหมด: {len(rows)} เฟรม")
    print(f"  • เฟรมที่มีการเคลื่อนที่ (>2 km/h): {total_moving_frames} เฟรม")
    if total_moving_frames > 0:
        stair_rate = (staircase_count / total_moving_frames) * 100.0
        spike_rate = (jitter_spike_count / total_moving_frames) * 100.0
        print(f"  • พิกัดค้างใน Tick (Staircase Frames): {staircase_count} ครั้ง ({stair_rate:.1f}%)")
        print(f"  • Jitter Spikes (>3 km/h jump): {jitter_spike_count} ครั้ง ({spike_rate:.1f}%)")
    print(f"  • บันทึกไฟล์ CSV สมบูรณ์ที่: {csv_path}")
    print("=" * 70)


def main():
    if "--replay" in sys.argv:
        custom_csv = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("-") else CSV_OUTPUT_PATH
        replay_csv(custom_csv)
        return

    print("=" * 70)
    print("🚗 WAR THUNDER GROUND VELOCITY TELEMETRY DEBUGGER")
    print("=" * 70)

    try:
        pid = get_game_pid()
    except Exception as e:
        print(f"❌ ไม่พบ Process เกม: {e}")
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
        print("❌ ไม่สามารถหา CGame Base ได้ (อาจยังไม่ได้เข้าห้องรบ)")
        sys.exit(1)
    print(f"[*] CGame Base: {hex(cgame)}")

    stabilizer = VelocityStabilizer(scanner)

    # เตรียมไฟล์ CSV
    fieldnames = [
        "frame_id", "timestamp", "dt_ms",
        "my_x", "my_y", "my_z",
        "my_raw_vx", "my_raw_vy", "my_raw_vz", "my_raw_kmh",
        "my_pos_vx", "my_pos_vy", "my_pos_vz", "my_pos_kmh",
        "my_chosen_vx", "my_chosen_vy", "my_chosen_vz", "my_chosen_kmh",
        "my_source", "my_is_staircase", "my_speed_delta_kmh",
        "tg_ptr", "tg_raw_kmh", "tg_pos_kmh", "tg_chosen_kmh", "tg_source"
    ]
    
    csv_file = open(CSV_OUTPUT_PATH, mode="w", newline="", buffering=1)
    writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
    writer.writeheader()

    running = True
    def sigint_handler(sig, frame):
        nonlocal running
        running = False
        print("\n[!] ได้รับคำสั่งหยุด (Ctrl+C)... กำลังสรุปข้อมูล")

    signal.signal(signal.SIGINT, sigint_handler)

    print(f"[+] บันทึก Log ลงที่: {CSV_OUTPUT_PATH}")
    print("[+] เริ่มบันทึกที่ ~60 FPS (กด Ctrl+C เมื่อต้องการหยุดและดูรายงาน)")
    print("-" * 70)

    frame_id = 0
    last_frame_time = time.time()
    last_my_pos = None
    last_my_chosen_kmh = 0.0

    # สถิติ
    staircase_count = 0
    jitter_spike_count = 0
    total_moving_frames = 0

    try:
        while running:
            loop_start = time.time()
            curr_t = loop_start
            dt = curr_t - last_frame_time
            last_frame_time = curr_t
            frame_id += 1

            # 1. ค้นหา My Unit
            my_unit, my_team = get_local_team(scanner, base_address)
            my_pos = get_unit_pos(scanner, my_unit) if my_unit else None

            # 2. ค้นหาเป้าหมายศัตรู 1 คัน
            all_units = get_all_units(scanner, cgame)
            target_unit = 0
            target_pos = None
            if my_unit:
                for u_ptr, is_air in all_units:
                    if u_ptr == my_unit or is_air:
                        continue
                    status = get_unit_status(scanner, u_ptr, read_name=False)
                    if status and status[0] != my_team and status[1] == 0:
                        t_p = get_unit_pos(scanner, u_ptr)
                        if t_p:
                            target_unit = u_ptr
                            target_pos = t_p
                            break

            # 3. คำนวณ My Velocity
            my_chosen = (0.0, 0.0, 0.0)
            my_raw = (0.0, 0.0, 0.0)
            my_pos_v = None
            my_source = "none"

            if my_unit and my_pos:
                my_chosen, my_raw, my_pos_v, my_source = stabilizer.stabilize(my_unit, False, my_pos, curr_t)

            my_raw_kmh = math.sqrt(my_raw[0]**2 + my_raw[1]**2 + my_raw[2]**2) * 3.6
            my_pos_kmh = (math.sqrt(my_pos_v[0]**2 + my_pos_v[1]**2 + my_pos_v[2]**2) * 3.6) if my_pos_v else 0.0
            my_chosen_kmh = math.sqrt(my_chosen[0]**2 + my_chosen[1]**2 + my_chosen[2]**2) * 3.6

            # ตรวจสอบ Staircase (พิกัดไม่ขยับเลยใน 1 เฟรมขณะที่รถกำลังวิ่ง)
            is_staircase = False
            if last_my_pos and my_pos and my_chosen_kmh > 2.0:
                pos_disp = math.hypot(my_pos[0] - last_my_pos[0], my_pos[2] - last_my_pos[2])
                if pos_disp < 0.001:  # ไม่ขยับเลย
                    is_staircase = True
                    staircase_count += 1

            speed_jump = abs(my_chosen_kmh - last_my_chosen_kmh)
            if my_chosen_kmh > 2.0 and speed_jump > 3.0:  # โดดเกิน 3 km/h ใน 16ms
                jitter_spike_count += 1

            if my_chosen_kmh > 2.0:
                total_moving_frames += 1

            last_my_pos = my_pos
            last_my_chosen_kmh = my_chosen_kmh

            # 4. Target Velocity
            tg_raw_kmh = 0.0
            tg_pos_kmh = 0.0
            tg_chosen_kmh = 0.0
            tg_source = "none"
            if target_unit and target_pos:
                tg_ch, tg_r, tg_pv, tg_source = stabilizer.stabilize(target_unit, False, target_pos, curr_t)
                tg_raw_kmh = math.sqrt(tg_r[0]**2 + tg_r[1]**2 + tg_r[2]**2) * 3.6
                tg_pos_kmh = (math.sqrt(tg_pv[0]**2 + tg_pv[1]**2 + tg_pv[2]**2) * 3.6) if tg_pv else 0.0
                tg_chosen_kmh = math.sqrt(tg_ch[0]**2 + tg_ch[1]**2 + tg_ch[2]**2) * 3.6

            # บันทึก CSV
            row = {
                "frame_id": frame_id,
                "timestamp": f"{curr_t:.4f}",
                "dt_ms": f"{dt * 1000.0:.2f}",
                "my_x": f"{my_pos[0]:.3f}" if my_pos else "0",
                "my_y": f"{my_pos[1]:.3f}" if my_pos else "0",
                "my_z": f"{my_pos[2]:.3f}" if my_pos else "0",
                "my_raw_vx": f"{my_raw[0]:.2f}",
                "my_raw_vy": f"{my_raw[1]:.2f}",
                "my_raw_vz": f"{my_raw[2]:.2f}",
                "my_raw_kmh": f"{my_raw_kmh:.1f}",
                "my_pos_vx": f"{my_pos_v[0]:.2f}" if my_pos_v else "0.0",
                "my_pos_vy": f"{my_pos_v[1]:.2f}" if my_pos_v else "0.0",
                "my_pos_vz": f"{my_pos_v[2]:.2f}" if my_pos_v else "0.0",
                "my_pos_kmh": f"{my_pos_kmh:.1f}",
                "my_chosen_vx": f"{my_chosen[0]:.2f}",
                "my_chosen_vy": f"{my_chosen[1]:.2f}",
                "my_chosen_vz": f"{my_chosen[2]:.2f}",
                "my_chosen_kmh": f"{my_chosen_kmh:.1f}",
                "my_source": my_source,
                "my_is_staircase": 1 if is_staircase else 0,
                "my_speed_delta_kmh": f"{speed_jump:.2f}",
                "tg_ptr": hex(target_unit) if target_unit else "0",
                "tg_raw_kmh": f"{tg_raw_kmh:.1f}",
                "tg_pos_kmh": f"{tg_pos_kmh:.1f}",
                "tg_chosen_kmh": f"{tg_chosen_kmh:.1f}",
                "tg_source": tg_source,
            }
            writer.writerow(row)

            # แสดงผลบรรทัดสถานะแบบ Terminal Update
            if frame_id % 6 == 0:  # แสดงทุกๆ ~100ms
                status_line = (
                    f"\r[Frame {frame_id:04d}] "
                    f"MyVel: {my_chosen_kmh:4.1f} km/h (Raw:{my_raw_kmh:4.1f} Pos:{my_pos_kmh:4.1f}) "
                    f"Src: {my_source:<18} "
                    f"Tg: {tg_chosen_kmh:4.1f} km/h "
                    f"Staircase: {staircase_count} "
                    f"Spikes: {jitter_spike_count}"
                )
                sys.stdout.write(status_line)
                sys.stdout.flush()

            # Target 60 FPS (~16.6ms)
            elapsed = time.time() - loop_start
            sleep_time = max(0.001, 0.0166 - elapsed)
            time.sleep(sleep_time)

    finally:
        csv_file.close()
        print("\n" + "=" * 70)
        print("📊 สรุปผลการวิเคราะห์ TELEMETRY:")
        print("=" * 70)
        print(f"  • จำนวนเฟรมทั้งหมด: {frame_id} เฟรม")
        print(f"  • เฟรมที่มีการเคลื่อนที่ (>2 km/h): {total_moving_frames} เฟรม")
        if total_moving_frames > 0:
            stair_rate = (staircase_count / total_moving_frames) * 100.0
            spike_rate = (jitter_spike_count / total_moving_frames) * 100.0
            print(f"  • พิกัดค้างใน Tick (Staircase Frames): {staircase_count} ครั้ง ({stair_rate:.1f}%)")
            print(f"  • Jitter Spikes (>3 km/h jump): {jitter_spike_count} ครั้ง ({spike_rate:.1f}%)")
        print(f"  • บันทึกไฟล์ CSV สมบูรณ์ที่: {CSV_OUTPUT_PATH}")
        print("=" * 70)


if __name__ == "__main__":
    main()
