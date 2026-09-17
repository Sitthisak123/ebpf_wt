#!/usr/bin/env python3
"""
06_target_airmove_tickrate_dumper.py — Target Air Movement & Omega Tickrate Auto-Dumper (RotMatrix Edition)

เฝ้าดูและบันทึกข้อมูล Tickrate (AirVEL และ Omega) ของเครื่องบินศัตรูโดยอัตโนมัติ
รองรับการมอนิเตอร์แบบหลายช่องทาง (Multi-Channel):
  1. Net AirVEL (Move_0x0018 + 0x0318 FLOAT vec3): Network Replication Speed (~1-5 Hz)
  2. Kinematic Omega (u_ptr + 0x0D14 3x3 Rotation Matrix): ⚡ Ultra High-Tick (~46.5 Hz เมื่อเลี้ยว)
  3. Raw Net Omega (Move_0x0018 + 0x0550 FLOAT vec3): Local Physics Buffer (มักเป็น 0 บนบอท/ศัตรู)
  4. Raw Hi-Tick Move (Move_0x0D48 + 0x0068 / 0x0098 DOUBLE vec3): Local Player Physics Buffer

ตรวจจับสถานะการบินอัจฉริยะ (Flight State Detection):
  - ✈️ STRAIGHT CRUISING: เมื่อเครื่องบินบินตรง ไม่เลี้ยว (|ω| < 0.015 rad/s)
  - 🌪️ MANEUVERING / DOGFIGHT: เมื่อเครื่องบินเลี้ยว หมุนตัว หรือทำท่ารบ (|ω| >= 0.015 rad/s)
"""

import os
import sys
import time
import math
import struct
import json

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import (
    get_cgame_base, get_all_units, get_local_team, get_unit_pos,
    get_unit_status, is_valid_ptr,
    OFF_AIR_MOVEMENT, OFF_AIR_VEL, OFF_AIR_OMEGA,
    OFF_AIR_HIGH_TICK_MOVEMENT, OFF_AIR_HIGH_TICK_VEL,
    OFF_MY_AIR_MOVEMENT, OFF_MY_AIR_VEL, OFF_MY_AIR_OMEGA,
    OFF_UNIT_ROTATION,
)

# ═══════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════
MAX_WATCH_DISTANCE   = 5000.0   # 5 กิโลเมตร (5,000 เมตร)
MIN_WATCH_SECONDS    = 5.0      # เฝ้าดูอย่างน้อย 5 วินาทีต่อเป้าหมายจึงบันทึกผล
CHUNK_AUTO_SAVE      = 10.0     # บันทึกเป็นช็อตทุกๆ 10 วินาทีหากเป้าหมายยังบินอยู่ในระยะต่อเนื่อง
CHANGE_EPSILON       = 0.001    # ค่าความต่างขั้นต่ำที่นับเป็น 1 Tick
MANEUVER_THRESHOLD   = 0.015    # เกณฑ์ Angular Velocity (rad/s) ที่ถือว่ากำลังเลี้ยว/หมุนตัว


def calc_3d_distance(pos_a, pos_b):
    """คำนวณระยะทาง 3 มิติ (เมตร) ระหว่างสองพิกัด."""
    return math.sqrt(
        (pos_a[0] - pos_b[0]) ** 2 +
        (pos_a[1] - pos_b[1]) ** 2 +
        (pos_a[2] - pos_b[2]) ** 2
    )


def read_vec3(scanner, base_ptr, offset, data_type="FLOAT"):
    """อ่าน Vec3 จาก base_ptr + offset."""
    if not is_valid_ptr(base_ptr):
        return None
    try:
        size = 24 if data_type == "DOUBLE" else 12
        fmt = "<ddd" if data_type == "DOUBLE" else "<fff"
        raw = scanner.read_mem(base_ptr + offset, size)
        if not raw or len(raw) < size:
            return None
        v = struct.unpack(fmt, raw)
        if not all(math.isfinite(x) for x in v):
            return None
        return v
    except Exception:
        return None


def vec_mag(vec):
    """คำนวณ Magnitude ของเวกเตอร์ 3D."""
    if not vec:
        return 0.0
    return math.sqrt(vec[0]**2 + vec[1]**2 + vec[2]**2)


def get_move_pointers(scanner, u_ptr):
    """อ่าน Move Pointers ทั้งสองตัวของยูนิต (Move_0x0018 และ Move_0x20F0 / Move_0x0D48)."""
    m0018 = 0
    m_hi = 0
    try:
        raw18 = scanner.read_mem(u_ptr + OFF_AIR_MOVEMENT, 8)
        if raw18 and len(raw18) == 8:
            p18 = struct.unpack("<Q", raw18)[0]
            if is_valid_ptr(p18):
                m0018 = p18
    except Exception:
        pass

    try:
        raw_hi = scanner.read_mem(u_ptr + OFF_AIR_HIGH_TICK_MOVEMENT, 8)
        if raw_hi and len(raw_hi) == 8:
            p_hi = struct.unpack("<Q", raw_hi)[0]
            if is_valid_ptr(p_hi):
                m_hi = p_hi
        if not m_hi:
            raw_d48 = scanner.read_mem(u_ptr + OFF_MY_AIR_MOVEMENT, 8)
            if raw_d48 and len(raw_d48) == 8:
                p_d48 = struct.unpack("<Q", raw_d48)[0]
                if is_valid_ptr(p_d48):
                    m_hi = p_d48
    except Exception:
        pass

    return m0018, m_hi


def find_best_air_target(scanner, cgame_base, my_unit_ptr, my_team, my_pos):
    """ค้นหาเครื่องบินศัตรูที่อยู่ใกล้เราที่สุดและระยะทาง < 5,000 เมตร."""
    if not my_pos:
        return None, 0, "", 0, None

    all_units = get_all_units(scanner, cgame_base)
    if not all_units:
        return None, 0, "", 0, None

    best_ptr  = None
    best_dist = float("inf")
    best_name = "UNKNOWN_AIR"
    best_team = 0
    best_pos  = None

    for u_ptr, is_air in all_units:
        if u_ptr == my_unit_ptr or not is_air:
            continue

        status = get_unit_status(scanner, u_ptr, read_name=False)
        u_team = 0
        u_state = 0
        if status:
            if isinstance(status, tuple) and len(status) >= 2:
                u_team = status[0]
                u_state = status[1]
            elif isinstance(status, dict):
                u_team = status.get("team", 0)
                u_state = status.get("state", 0)

        if u_state >= 2:
            continue

        if my_team > 0 and u_team > 0 and u_team == my_team:
            continue

        pos = get_unit_pos(scanner, u_ptr)
        if not pos or all(abs(p) < 0.1 for p in pos):
            continue

        dist = calc_3d_distance(my_pos, pos)
        if dist <= MAX_WATCH_DISTANCE and dist < best_dist:
            best_dist = dist
            best_ptr  = u_ptr
            best_team = u_team
            best_pos  = pos

    if best_ptr:
        status = get_unit_status(scanner, best_ptr, read_name=True)
        if status:
            if isinstance(status, tuple) and len(status) >= 3 and status[2]:
                best_name = status[2]
            elif isinstance(status, dict):
                best_name = status.get("short_name") or status.get("name", "UNKNOWN_AIR")

        return best_ptr, best_dist, best_name, best_team, best_pos

    return None, 0, "", 0, None


def validate_target(scanner, target_ptr, my_pos, my_team):
    """ตรวจสอบว่าเป้าหมายที่ล็อกไว้ยังเข้าเกณฑ์หรือไม่."""
    try:
        t_pos = get_unit_pos(scanner, target_ptr)
        if not t_pos or not my_pos:
            return False, 0, None

        dist = calc_3d_distance(my_pos, t_pos)
        if dist > MAX_WATCH_DISTANCE:
            return False, dist, t_pos

        status = get_unit_status(scanner, target_ptr, read_name=False)
        if status:
            state = status[1] if (isinstance(status, tuple) and len(status) >= 2) else status.get("state", 0)
            if state >= 2:
                return False, dist, t_pos

        return True, dist, t_pos
    except Exception:
        return False, 0, None


class ChannelTracker:
    """มอนิเตอร์และวัด Tickrate สำหรับ 1 ช่องทางหน่วยความจำ."""

    def __init__(self, name, offset, data_type="FLOAT", unit="km/h", to_user_val=None):
        self.name = name
        self.offset = offset
        self.data_type = data_type
        self.unit = unit
        self.to_user_val = to_user_val or (lambda v: vec_mag(v))

        self.ticks = 0
        self.reads = 0
        self.last_vec = None
        self.peak_val = 0.0
        self.current_val = 0.0
        self.current_vec = (0.0, 0.0, 0.0)
        self.samples = []

    def update(self, scanner, base_ptr):
        if not is_valid_ptr(base_ptr):
            return

        vec = read_vec3(scanner, base_ptr, self.offset, self.data_type)
        if vec is not None:
            self.reads += 1
            val = self.to_user_val(vec)
            self.current_val = val
            self.current_vec = vec
            self.samples.append(val)
            if val > self.peak_val:
                self.peak_val = val

            if self.last_vec is not None:
                diff = sum(abs(vec[i] - self.last_vec[i]) for i in range(3))
                if diff > CHANGE_EPSILON:
                    self.ticks += 1
            self.last_vec = vec

    def get_stats(self, elapsed):
        hz = self.ticks / max(elapsed, 1e-6)
        avg = sum(self.samples) / len(self.samples) if self.samples else 0.0
        return {
            "name": self.name,
            "offset": hex(self.offset),
            "data_type": self.data_type,
            "unit": self.unit,
            "ticks": self.ticks,
            "tickrate_hz": round(hz, 1),
            "peak": round(self.peak_val, 2),
            "avg": round(avg, 2),
            "current_vec": [round(x, 3) for x in self.current_vec],
        }


class KinematicOmegaTracker:
    """คำนวณและวัด Tickrate ของความเร็วเชิงมุม (rad/s) จาก Rotation Matrix (0x0D14) แบบ Kinematic Differential."""

    def __init__(self):
        self.name = "Kinematic Omega (0x0D14 Matrix)"
        self.offset = OFF_UNIT_ROTATION
        self.data_type = "ROT_MATRIX_3x3"
        self.unit = "rad/s"

        self.ticks = 0
        self.reads = 0
        self.last_R = None
        self.last_t = None
        self.current_val = 0.0
        self.current_vec = (0.0, 0.0, 0.0)
        self.peak_val = 0.0
        self.samples = []

    def update(self, scanner, unit_ptr):
        raw = scanner.read_mem(unit_ptr + OFF_UNIT_ROTATION, 36)
        if not raw or len(raw) < 36:
            return
        r = struct.unpack("<9f", raw)
        if not all(math.isfinite(x) for x in r):
            return

        now = time.time()
        self.reads += 1
        if self.last_R is not None and self.last_t is not None:
            dt = now - self.last_t
            if 0.003 <= dt <= 0.5:
                diff = sum(abs(r[i] - self.last_R[i]) for i in range(9))
                if diff > 0.0002:
                    self.ticks += 1
                    r_rel = [0.0] * 9
                    for i in range(3):
                        for j in range(3):
                            r_rel[i*3 + j] = sum(r[i*3 + k] * self.last_R[j*3 + k] for k in range(3))
                    trace = r_rel[0] + r_rel[4] + r_rel[8]
                    val = max(-1.0, min(1.0, (trace - 1.0) * 0.5))
                    angle = math.acos(val)
                    if angle >= 1e-4:
                        sin_a = math.sin(angle)
                        if abs(sin_a) >= 1e-4:
                            scale = angle / (2.0 * sin_a * dt)
                            wx = (r_rel[7] - r_rel[5]) * scale
                            wy = (r_rel[2] - r_rel[6]) * scale
                            wz = (r_rel[3] - r_rel[1]) * scale
                            w_mag = angle / dt
                            if all(math.isfinite(x) for x in (wx, wy, wz)):
                                self.current_vec = (wx, wy, wz)
                                self.current_val = w_mag
                                self.samples.append(w_mag)
                                if w_mag > self.peak_val:
                                    self.peak_val = w_mag
                    self.last_R = r
                    self.last_t = now
                    return
        self.last_R = r
        self.last_t = now

    def get_stats(self, elapsed):
        hz = self.ticks / max(elapsed, 1e-6)
        avg = sum(self.samples) / len(self.samples) if self.samples else 0.0
        return {
            "name": self.name,
            "offset": hex(self.offset),
            "data_type": self.data_type,
            "unit": self.unit,
            "ticks": self.ticks,
            "tickrate_hz": round(hz, 1),
            "peak": round(self.peak_val, 3),
            "avg": round(avg, 3),
            "current_vec": [round(x, 3) for x in self.current_vec],
        }


class TargetWatchSession:
    """จัดการ Session การเฝ้าดูและวัด Tickrate ของเป้าหมายแบบ Multi-Channel."""

    def __init__(self, target_ptr, target_name, target_team, initial_dist):
        self.target_ptr = target_ptr
        self.target_name = target_name
        self.target_team = target_team
        self.start_time = time.time()
        self.last_save_time = self.start_time

        self.distances = [initial_dist]
        self.loop_count = 0

        self.m0018 = 0
        self.m0d48 = 0

        # Channels:
        # 1. Net Velocity (Move_0x0018 + 0x0318 Float)
        self.net_vel = ChannelTracker("Net AirVEL (0x0318)", OFF_AIR_VEL, "FLOAT", "km/h", lambda v: vec_mag(v) * 3.6)
        # 2. Kinematic Omega (u_ptr + 0x0D14 Rotation Matrix) - ⭐ ACTIVE & PROVEN (~46.5 Hz)
        self.kin_omg = KinematicOmegaTracker()
        # 3. Raw Net Omega (Move_0x0018 + 0x0550 Float) - Local buffer
        self.net_omg = ChannelTracker("Raw Net Omega (0x0550)", OFF_AIR_OMEGA, "FLOAT", "rad/s", lambda v: vec_mag(v))
        # 4. Hi-Tick Velocity (Move_0x20F0 + 0x07C0 Float, 41Hz)
        self.hi_vel  = ChannelTracker("Hi AirVEL (0x20F0)", OFF_AIR_HIGH_TICK_VEL, "FLOAT", "km/h", lambda v: vec_mag(v) * 3.6)

        # Flight State
        self.cruising_count = 0
        self.maneuver_count = 0
        self.is_maneuvering = False

    def update(self, scanner, current_dist):
        self.loop_count += 1
        self.distances.append(current_dist)

        if not is_valid_ptr(self.m0018) or not is_valid_ptr(self.m0d48):
            m18, md48 = get_move_pointers(scanner, self.target_ptr)
            if m18: self.m0018 = m18
            if md48: self.m0d48 = md48

        # 1. Update Kinematic Omega (from 0x0D14 Rotation Matrix)
        self.kin_omg.update(scanner, self.target_ptr)

        # 2. Update Net Move
        if self.m0018:
            self.net_vel.update(scanner, self.m0018)
            self.net_omg.update(scanner, self.m0018)

        # 3. Update Hi Move
        if self.m0d48:
            self.hi_vel.update(scanner, self.m0d48)

        # Flight State
        active_omg = max(self.kin_omg.current_val, self.net_omg.current_val)
        if active_omg >= MANEUVER_THRESHOLD:
            self.is_maneuvering = True
            self.maneuver_count += 1
        else:
            self.is_maneuvering = False
            self.cruising_count += 1

    def get_summary_record(self):
        now = time.time()
        elapsed = max(now - self.start_time, 1e-6)

        avg_dist = sum(self.distances) / len(self.distances) if self.distances else 0.0
        min_dist = min(self.distances) if self.distances else 0.0
        max_dist = max(self.distances) if self.distances else 0.0

        net_v_stat = self.net_vel.get_stats(elapsed)
        kin_w_stat = self.kin_omg.get_stats(elapsed)
        net_w_stat = self.net_omg.get_stats(elapsed)
        hi_v_stat  = self.hi_vel.get_stats(elapsed)

        def grade(hz):
            if hz >= 40.0: return f"⚡ ULTRA SMOOTH ({hz:.1f} Hz)"
            if hz >= 15.0: return f"🟢 SMOOTH ({hz:.1f} Hz)"
            if hz >= 3.0:  return f"🟡 NETWORK ({hz:.1f} Hz)"
            return f"⚪ STATIC/IDLE ({hz:.1f} Hz)"

        net_v_stat["verdict"] = grade(net_v_stat["tickrate_hz"])
        kin_w_stat["verdict"] = grade(kin_w_stat["tickrate_hz"])
        net_w_stat["verdict"] = grade(net_w_stat["tickrate_hz"])
        hi_v_stat["verdict"]  = grade(hi_v_stat["tickrate_hz"])

        maneuver_pct = (self.maneuver_count / max(self.loop_count, 1)) * 100.0

        return {
            "target_name": self.target_name,
            "target_ptr": hex(self.target_ptr),
            "target_team": self.target_team,
            "move_0018_ptr": hex(self.m0018) if self.m0018 else None,
            "move_0d48_ptr": hex(self.m0d48) if self.m0d48 else None,
            "watch_duration_sec": round(elapsed, 2),
            "total_loops": self.loop_count,
            "avg_loop_rate_hz": round(self.loop_count / elapsed, 1),
            "flight_behavior": {
                "maneuvering_percent": round(maneuver_pct, 1),
                "cruising_percent": round(100.0 - maneuver_pct, 1),
                "dominant_state": "MANEUVERING" if maneuver_pct >= 25.0 else "STRAIGHT_CRUISING",
            },
            "dist_m": {
                "min": round(min_dist, 1),
                "max": round(max_dist, 1),
                "avg": round(avg_dist, 1),
            },
            "channels": {
                "net_air_vel": net_v_stat,
                "kinematic_omega": kin_w_stat,
                "raw_net_omega": net_w_stat,
                "raw_hi_vel": hi_v_stat,
            },
            "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }


def save_records_to_disk(all_records, session_timestamp):
    dump_dir = os.path.join(PROJECT_ROOT, "dumps")
    os.makedirs(dump_dir, exist_ok=True)

    json_file = os.path.join(dump_dir, f"06_target_airmove_tickrate_{session_timestamp}.json")
    latest_json = os.path.join(dump_dir, "06_target_airmove_tickrate_latest.json")
    txt_file = os.path.join(dump_dir, f"06_target_airmove_tickrate_{session_timestamp}.txt")

    payload = {
        "session_timestamp": session_timestamp,
        "total_records": len(all_records),
        "min_watch_seconds_threshold": MIN_WATCH_SECONDS,
        "max_watch_distance_m": MAX_WATCH_DISTANCE,
        "records": all_records,
    }

    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    with open(latest_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    with open(txt_file, "w", encoding="utf-8") as f:
        f.write("═════════════════════════════════════════════════════════════════════════════════════════════════\n")
        f.write(f"  🎯 TARGET AIRMOVE TICKRATE DUMP REPORT (ROTATION MATRIX EDITION) — {session_timestamp}\n")
        f.write(f"  Total Targets Captured: {len(all_records)}\n")
        f.write("═════════════════════════════════════════════════════════════════════════════════════════════════\n\n")
        for idx, rec in enumerate(all_records, 1):
            c = rec["channels"]
            f.write(f"#{idx:02d} Target: {rec['target_name']} ({rec['target_ptr']}) | Team: {rec['target_team']}\n")
            f.write(f"     Duration: {rec['watch_duration_sec']}s | Distance: {rec['dist_m']['min']}m - {rec['dist_m']['max']}m (avg {rec['dist_m']['avg']}m)\n")
            f.write(f"     Flight Behavior: {rec['flight_behavior']['dominant_state']} (Maneuver: {rec['flight_behavior']['maneuvering_percent']}%, Cruise: {rec['flight_behavior']['cruising_percent']}%)\n")
            f.write(f"     • Net AirVEL (0x0318 Float):   {c['net_air_vel']['tickrate_hz']:5.1f} Hz ({c['net_air_vel']['ticks']:4d} ticks) | Peak: {c['net_air_vel']['peak']:6.1f} km/h | {c['net_air_vel']['verdict']}\n")
            f.write(f"     • Kinematic Omega (0x0D14 R):   {c['kinematic_omega']['tickrate_hz']:5.1f} Hz ({c['kinematic_omega']['ticks']:4d} ticks) | Peak: {c['kinematic_omega']['peak']:6.3f} rad/s| {c['kinematic_omega']['verdict']}\n")
            f.write(f"     • Raw Net Omega (0x0550 Float): {c['raw_net_omega']['tickrate_hz']:5.1f} Hz ({c['raw_net_omega']['ticks']:4d} ticks) | (Local buffer)\n")
            f.write(f"     • 🚀 Hi-Tick Move (0x20F0 Flt): {c['raw_hi_vel']['tickrate_hz']:5.1f} Hz ({c['raw_hi_vel']['ticks']:4d} ticks) | Peak: {c['raw_hi_vel']['peak']:6.1f} km/h | {c['raw_hi_vel']['verdict']}\n")
            f.write("─" * 97 + "\n")

    return json_file, txt_file


def main():
    print("[*] กำลังเริ่มต้นระบบ Target AirMove Auto-Dumper (RotMatrix Edition)...")
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_address)

    session_timestamp = time.strftime("%Y%m%d_%H%M%S")
    saved_records = []
    active_session = None
    last_ui_draw = 0.0

    print("\n" + "=" * 60)
    print("  🎯 TARGET AIRMOVE TICKRATE AUTO-DUMPER (RotMatrix Edition)")
    print(f"  Max Distance: < {MAX_WATCH_DISTANCE:.0f}m (5 km)  |  Min Watch: >= {MIN_WATCH_SECONDS:.1f}s")
    print("  Active Omega Source: 0x0D14 Rotation Matrix Differential (~46.5 Hz)")
    print("  บันทึกต่อเนื่องอัตโนมัติ — กด [Ctrl+C] เมื่อต้องการหยุดและดูสรุป")
    print("=" * 60)
    time.sleep(1.0)

    try:
        while True:
            curr_t = time.time()
            cgame_base = get_cgame_base(scanner, base_address)
            if not cgame_base:
                time.sleep(0.3)
                continue

            my_unit_ptr, my_team = get_local_team(scanner, base_address)
            my_pos = get_unit_pos(scanner, my_unit_ptr) if my_unit_ptr else None

            # ─────────────────────────────────────────────────────────
            # 1. ตรวจสอบเป้าหมายปัจจุบัน (ถ้ามีล็อกอยู่)
            # ─────────────────────────────────────────────────────────
            if active_session:
                is_valid, cur_dist, cur_pos = validate_target(scanner, active_session.target_ptr, my_pos, my_team)
                session_elapsed = curr_t - active_session.start_time

                if is_valid:
                    active_session.update(scanner, cur_dist)

                    if curr_t - active_session.last_save_time >= CHUNK_AUTO_SAVE:
                        active_session.last_save_time = curr_t
                        rec = active_session.get_summary_record()
                        saved_records.append(rec)
                        save_records_to_disk(saved_records, session_timestamp)
                else:
                    if session_elapsed >= MIN_WATCH_SECONDS:
                        rec = active_session.get_summary_record()
                        saved_records.append(rec)
                        save_records_to_disk(saved_records, session_timestamp)
                        print(f"\n💾 [AUTO-SAVED] บันทึก {active_session.target_name} ({rec['watch_duration_sec']}s)")
                    else:
                        print(f"\n[-] ข้ามเป้าหมาย {active_session.target_name} (เฝ้าดูได้เพียง {session_elapsed:.1f}s < เกณฑ์ 5.0s)")

                    active_session = None
                    time.sleep(0.3)

            # ─────────────────────────────────────────────────────────
            # 2. ค้นหาเป้าหมายใหม่ (ถ้ายังไม่มีการล็อก)
            # ─────────────────────────────────────────────────────────
            if not active_session and my_pos:
                t_ptr, t_dist, t_name, t_team, t_pos = find_best_air_target(scanner, cgame_base, my_unit_ptr, my_team, my_pos)
                if t_ptr:
                    active_session = TargetWatchSession(t_ptr, t_name, t_team, t_dist)
                    print(f"\n🔒 [TARGET LOCKED] {t_name} ({hex(t_ptr)}) | ระยะ: {t_dist:.0f}m | เริ่มนับเวลา >= 5s...")

            # ─────────────────────────────────────────────────────────
            # 3. อัปเดตหน้าจอแบบ Realtime (~20 FPS)
            # ─────────────────────────────────────────────────────────
            if curr_t - last_ui_draw >= 0.05:
                last_ui_draw = curr_t
                os.system("clear")
                print("═══════════════════════════════════════════════════════════════════════════════════════")
                print("  🎯 TARGET AIRMOVE TICKRATE AUTO-DUMPER (RotMatrix Edition)")
                print(f"  PID: {pid}  |  Session Records Saved: {len(saved_records)} รายการ  |  [Ctrl+C เพื่อหยุด]")
                print("═══════════════════════════════════════════════════════════════════════════════════════")

                if my_unit_ptr and my_pos:
                    print(f"✈️ My Unit: {hex(my_unit_ptr)} (Team {my_team}) | Pos: ({my_pos[0]:.0f}, {my_pos[1]:.0f}, {my_pos[2]:.0f})")
                else:
                    print("⏳ รอตรวจพบเครื่องบินเราเอง...")

                print("─" * 87)

                if active_session:
                    cur_elapsed = max(curr_t - active_session.start_time, 1e-6)
                    cur_dist = active_session.distances[-1] if active_session.distances else 0.0

                    dist_ratio = min(max(cur_dist / MAX_WATCH_DISTANCE, 0.0), 1.0)
                    dist_bar_len = 20
                    dist_filled = int(dist_bar_len * (1.0 - dist_ratio))
                    dist_bar = "█" * dist_filled + "░" * (dist_bar_len - dist_filled)

                    if cur_elapsed >= MIN_WATCH_SECONDS:
                        time_badge = f"✅ QUALIFIED ({cur_elapsed:4.1f}s >= 5.0s)"
                    else:
                        time_badge = f"⏳ RECORDING ({cur_elapsed:4.1f}s / 5.0s min)"

                    if active_session.is_maneuvering:
                        flight_badge = "🌪️ MANEUVERING / TURNING (High-Tick Active)"
                    else:
                        flight_badge = "✈️ STRAIGHT CRUISING (No Turn / ω ≈ 0)"

                    net_vhz = active_session.net_vel.ticks / cur_elapsed
                    kin_whz = active_session.kin_omg.ticks / cur_elapsed
                    net_whz = active_session.net_omg.ticks / cur_elapsed

                    print(f"🔒 TARGET LOCKED:  {active_session.target_name} ({hex(active_session.target_ptr)}) | Team: {active_session.target_team}")
                    print(f"📏 Distance:       [{dist_bar}] {cur_dist:5.0f}m / {MAX_WATCH_DISTANCE:.0f}m")
                    print(f"⏱️  Watch Status:   {time_badge}  |  Loop Rate: {active_session.loop_count / cur_elapsed:6.1f} Hz")
                    print(f"🎮 Flight State:   {flight_badge}")
                    print("─" * 87)
                    print("📊 ACTIVE METRICS:")
                    print(f"  ⚡ Kinematic Omega (0x0D14 Matrix): {active_session.kin_omg.current_val:6.3f} rad/s (Peak: {active_session.kin_omg.peak_val:6.3f}) | {kin_whz:5.1f} Hz ({active_session.kin_omg.ticks} ticks)")
                    print(f"  🏎️  Net AirVEL       (0x0318 Float):  {active_session.net_vel.current_val:6.1f} km/h  (Peak: {active_session.net_vel.peak_val:6.1f}) | {net_vhz:5.1f} Hz ({active_session.net_vel.ticks} ticks)")
                    print("─" * 87)
                    print("🔍 RAW MEMORY BUFFERS COMPARISON:")
                    print(f"  • Raw Net Omega    (0x0550 Float):  {active_session.net_omg.current_val:6.3f} rad/s | {net_whz:5.1f} Hz ({active_session.net_omg.ticks} ticks) [Static buffer]")
                    hi_vhz = active_session.hi_vel.ticks / cur_elapsed
                    print(f"  • 🚀 Target Hi-Tick (0x20F0 Float):  {active_session.hi_vel.current_val:6.1f} km/h  | {hi_vhz:5.1f} Hz ({active_session.hi_vel.ticks} ticks)")
                else:
                    print("👀 กำลังค้นหาเครื่องบินศัตรูในระยะ < 5,000 เมตร...")
                    print("   (เครื่องบินจะถูกล็อกและบันทึกอัตโนมัติทันทีที่เข้าสู่ระยะ)")

                if saved_records:
                    print("───────────────────────────────────────────────────────────────────────────────────────")
                    print(f"📁 รายการล่าสุดที่บันทึกไว้ ({len(saved_records)} รายการ):")
                    for r in saved_records[-3:]:
                        c = r["channels"]
                        print(f"   • {r['target_name']} ({r['watch_duration_sec']}s) | KinOmg: {c['kinematic_omega']['tickrate_hz']}Hz | NetVel: {c['net_air_vel']['tickrate_hz']}Hz | State: {r['flight_behavior']['dominant_state']}")

            time.sleep(0.003)

    except KeyboardInterrupt:
        print("\n\n🛑 ผู้ใช้กดหยุดการทำงาน (Ctrl+C)... กำลังสรุปข้อมูลรอบสุดท้าย...")

    if active_session:
        final_elapsed = time.time() - active_session.start_time
        if final_elapsed >= MIN_WATCH_SECONDS:
            rec = active_session.get_summary_record()
            saved_records.append(rec)
            print(f"💾 [SAVED LAST TARGET] บันทึก {active_session.target_name} ({rec['watch_duration_sec']}s)")

    if saved_records:
        j_path, t_path = save_records_to_disk(saved_records, session_timestamp)
        os.system("clear")
        print("═══════════════════════════════════════════════════════════════════════════════════════════════════════")
        print("  🏆 TARGET AIRMOVE AUTO-DUMP SESSION COMPLETE")
        print(f"  Total Saved Records: {len(saved_records)} รายการ")
        print(f"  JSON Dump File:      {j_path}")
        print(f"  Text Report File:    {t_path}")
        print("═══════════════════════════════════════════════════════════════════════════════════════════════════════")
        print(f"{'Target Name':<20s} | {'Time':>6s} | {'Dist':>6s} | {'NetVel':>7s} | {'KinOmg':>8s} | {'Peak Omg':>9s} | {'Flight State':<14s}")
        print("─" * 87)
        for r in saved_records:
            c = r["channels"]
            print(f"{r['target_name']:<20s} | {r['watch_duration_sec']:5.1f}s | {r['dist_m']['avg']:5.0f}m | {c['net_air_vel']['tickrate_hz']:6.1f}H | {c['kinematic_omega']['tickrate_hz']:7.1f}H | {c['kinematic_omega']['peak']:7.3f}r | {r['flight_behavior']['dominant_state']:<14s}")
        print("═══════════════════════════════════════════════════════════════════════════════════════════════════════\n")
    else:
        print("\n[-] ไม่มีการบันทึกข้อมูล (ยังไม่มีเป้าหมายที่เข้าเกณฑ์ระยะ < 5km นานเกิน 5 วินาที)")


if __name__ == "__main__":
    main()
