#!/usr/bin/env python3
"""
02_vel_hunter_scanner.py — Close Air Unit Velocity & Tickrate Hunter (Multi-Team Edition)

เฝ้าดูและวิเคราะห์ Offset ความเร็ว (Velocity) และ Tick Rate บนเครื่องบินลำใกล้เคียง
รองรับทั้งเครื่องบินฝ่ายเดียวกัน (Friendly) และศัตรู (Enemy)
โดยนำรายชื่อ Offset ความเร็วทั้งหมด 27 รายการที่สแกนได้จาก 01_my_unit_velocity_scanner
มาทดสอบแบบ Realtime บนยูนิตเป้าหมาย
"""

import os
import sys
import struct
import time
import math
import json

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import (
    get_cgame_base, get_all_units, get_local_team,
    get_unit_pos, get_unit_status, is_valid_ptr,
    OFF_AIR_MOVEMENT, OFF_AIR_VEL, OFF_MY_AIR_MOVEMENT, OFF_MY_AIR_VEL
)

# ═══════════════════════════════════════════════════════════
# CONFIGURATION & FALLBACK CANDIDATES
# ═══════════════════════════════════════════════════════════
MAX_SEARCH_DISTANCE = 50000.0  # 50 กิโลเมตร (ครอบคลุมทั้งแผนที่ขนาดใหญ่)
CHANGE_THRESHOLD    = 0.005    # ค่าความต่างขั้นต่ำที่นับเป็น 1 Tick
MONITOR_SLEEP       = 0.01     # หน่วงเวลาลูปมอนิเตอร์ (~100 Hz)

# Fallback Candidates กรณีไม่มีไฟล์ JSON จาก 01_my_unit_velocity_scanner
FALLBACK_CANDIDATES = [
    {"move_ptr_offset": "0x18",   "vel_offset": "0x318", "data_type": "FLOAT"},
    {"move_ptr_offset": "0x18",   "vel_offset": "0x358", "data_type": "FLOAT"},
    {"move_ptr_offset": "0x18",   "vel_offset": "0x398", "data_type": "FLOAT"},
    {"move_ptr_offset": "0x18",   "vel_offset": "0x3d8", "data_type": "FLOAT"},
    {"move_ptr_offset": "0x18",   "vel_offset": "0x418", "data_type": "FLOAT"},
    {"move_ptr_offset": "0x18",   "vel_offset": "0x458", "data_type": "FLOAT"},
    {"move_ptr_offset": "0x18",   "vel_offset": "0x498", "data_type": "FLOAT"},
    {"move_ptr_offset": "0x18",   "vel_offset": "0x4d8", "data_type": "FLOAT"},
    {"move_ptr_offset": "0x18",   "vel_offset": "0x518", "data_type": "FLOAT"},
    {"move_ptr_offset": "0xd48",  "vel_offset": "0x68",  "data_type": "DOUBLE"},
    {"move_ptr_offset": "0xd48",  "vel_offset": "0xc8",  "data_type": "DOUBLE"},
    {"move_ptr_offset": "0xd48",  "vel_offset": "0xd0",  "data_type": "DOUBLE"},
    {"move_ptr_offset": "0xd50",  "vel_offset": "0x68",  "data_type": "DOUBLE"},
    {"move_ptr_offset": "0xd50",  "vel_offset": "0xc8",  "data_type": "DOUBLE"},
    {"move_ptr_offset": "0xd50",  "vel_offset": "0xd0",  "data_type": "DOUBLE"},
    {"move_ptr_offset": "0x1150", "vel_offset": "0x104", "data_type": "FLOAT"},
    {"move_ptr_offset": "0x1150", "vel_offset": "0x134", "data_type": "FLOAT"},
    {"move_ptr_offset": "0x11a8", "vel_offset": "0x200", "data_type": "FLOAT"},
    {"move_ptr_offset": "0x11a8", "vel_offset": "0x204", "data_type": "FLOAT"},
    {"move_ptr_offset": "0x12b0", "vel_offset": "0x104", "data_type": "FLOAT"},
    {"move_ptr_offset": "0x12b0", "vel_offset": "0x134", "data_type": "FLOAT"},
    {"move_ptr_offset": "0x1628", "vel_offset": "0x58",  "data_type": "DOUBLE"},
    {"move_ptr_offset": "0x1628", "vel_offset": "0xb8",  "data_type": "DOUBLE"},
    {"move_ptr_offset": "0x1628", "vel_offset": "0xc0",  "data_type": "DOUBLE"},
    {"move_ptr_offset": "0x24c0", "vel_offset": "0xe90", "data_type": "FLOAT"},
    {"move_ptr_offset": "0x24c8", "vel_offset": "0xdb8", "data_type": "FLOAT"},
    {"move_ptr_offset": "0x24d0", "vel_offset": "0xdb8", "data_type": "FLOAT"},
]


def load_candidate_offsets():
    """โหลดรายการ Candidate Velocity Offsets จากไฟล์ JSON ล่าสุด."""
    latest_json = os.path.join(PROJECT_ROOT, "dumps", "01_my_unit_velocity_scan_latest.json")
    if os.path.exists(latest_json):
        try:
            with open(latest_json, "r", encoding="utf-8") as f:
                data = json.load(f)
                cands = data.get("candidates", [])
                if cands:
                    parsed = []
                    for c in cands:
                        p_off = int(c["move_ptr_offset"], 16) if isinstance(c["move_ptr_offset"], str) else int(c["move_ptr_offset"])
                        v_off = int(c["vel_offset"], 16) if isinstance(c["vel_offset"], str) else int(c["vel_offset"])
                        dtype = c.get("data_type", "FLOAT")
                        parsed.append((p_off, v_off, dtype))
                    return parsed, latest_json
        except Exception as e:
            print(f"[-] ไม่สามารถอ่าน {latest_json}: {e}")

    # Fallback
    parsed = []
    for c in FALLBACK_CANDIDATES:
        p_off = int(c["move_ptr_offset"], 16)
        v_off = int(c["vel_offset"], 16)
        dtype = c["data_type"]
        parsed.append((p_off, v_off, dtype))
    return parsed, "BUILTIN_FALLBACK"


def calc_3d_dist(p1, p2):
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2 + (p1[2] - p2[2])**2)


def get_all_close_air_units(scanner, cgame_base, my_unit_ptr, my_team, my_pos, max_dist=MAX_SEARCH_DISTANCE):
    """
    ค้นหาเครื่องบินทุกลำในระยะ (รวมทั้งมิตรและศัตรู - Include Team).
    Returns list of dict:
        [{
            'ptr': u_ptr, 'name': name, 'team': team, 'is_friendly': (team==my_team),
            'dist': dist, 'pos': pos
        }, ...]
    """
    if not my_pos:
        return []

    raw_units = get_all_units(scanner, cgame_base)
    air_list = []

    for u_ptr, is_air in raw_units:
        if u_ptr == my_unit_ptr or not is_air:
            continue

        status = get_unit_status(scanner, u_ptr, read_name=True)
        if not status:
            continue

        team = status[0] if isinstance(status, tuple) else status.get("team", 0)
        state = status[1] if isinstance(status, tuple) else status.get("state", 0)
        name = status[2] if (isinstance(status, tuple) and len(status) >= 3 and status[2]) else "AIR"

        if state >= 2:  # ซากเครื่องตก
            continue

        pos = get_unit_pos(scanner, u_ptr)
        if not pos or all(abs(p) < 0.1 for p in pos):
            continue

        dist = calc_3d_dist(my_pos, pos)
        if dist <= max_dist:
            air_list.append({
                "ptr": u_ptr,
                "name": name,
                "team": team,
                "is_friendly": (team == my_team and my_team > 0),
                "dist": dist,
                "pos": pos,
            })

    air_list.sort(key=lambda x: x["dist"])
    return air_list


def read_velocity_vec(scanner, move_ptr, vel_off, data_type):
    """อ่านเวกเตอร์ความเร็ว 3 มิติ."""
    if not is_valid_ptr(move_ptr):
        return None
    try:
        size = 24 if data_type == "DOUBLE" else 12
        fmt = "<ddd" if data_type == "DOUBLE" else "<fff"
        raw = scanner.read_mem(move_ptr + vel_off, size)
        if not raw or len(raw) < size:
            return None
        v = struct.unpack(fmt, raw)
        if not all(math.isfinite(x) for x in v):
            return None
        return v
    except Exception:
        return None


def run_target_velocity_monitor(scanner, target_info, candidate_offsets, base_address, my_unit_ptr):
    """เฝ้าดูและคำนวณ Tickrate ของ Offset ความเร็วทั้ง 27 รายการบนยูนิตที่เลือกแบบ Realtime."""
    u_ptr = target_info["ptr"]
    name = target_info["name"]
    team = target_info["team"]
    is_friendly = target_info["is_friendly"]
    team_label = "🟢 FRIENDLY" if is_friendly else "🔴 ENEMY"

    # โครงสร้างสำหรับเก็บสถานะแต่ละ candidate
    # (p_off, v_off, dtype) -> dict
    metrics = {}
    for p_off, v_off, dtype in candidate_offsets:
        metrics[(p_off, v_off, dtype)] = {
            "ticks": 0,
            "reads": 0,
            "last_vec": None,
            "current_spd": 0.0,
            "peak_spd": 0.0,
            "current_vec": (0.0, 0.0, 0.0),
            "move_ptr": 0,
            "is_valid_ptr": False,
        }

    start_time = time.time()
    last_ui = 0.0
    loop_count = 0

    try:
        while True:
            loop_count += 1
            curr_t = time.time()
            elapsed = max(curr_t - start_time, 1e-6)

            # ตรวจสอบว่าเป้าหมายยังอยู่หรือไม่
            pos = get_unit_pos(scanner, u_ptr)
            my_pos = get_unit_pos(scanner, my_unit_ptr) if my_unit_ptr else None
            cur_dist = calc_3d_dist(my_pos, pos) if (my_pos and pos) else target_info["dist"]

            # อัปเดตการอ่าน Memory
            for (p_off, v_off, dtype), m in metrics.items():
                raw_p = scanner.read_mem(u_ptr + p_off, 8)
                p_val = struct.unpack("<Q", raw_p)[0] if raw_p else 0
                if is_valid_ptr(p_val):
                    m["move_ptr"] = p_val
                    m["is_valid_ptr"] = True
                    vec = read_velocity_vec(scanner, p_val, v_off, dtype)
                    if vec:
                        m["reads"] += 1
                        spd = math.sqrt(sum(x*x for x in vec)) * 3.6
                        m["current_spd"] = spd
                        m["current_vec"] = vec
                        if spd > m["peak_spd"] and spd < 5000.0:
                            m["peak_spd"] = spd

                        if m["last_vec"] is not None:
                            diff = sum(abs(vec[i] - m["last_vec"][i]) for i in range(3))
                            if diff > CHANGE_THRESHOLD:
                                m["ticks"] += 1
                        m["last_vec"] = vec
                else:
                    m["is_valid_ptr"] = False

            # อัปเดต UI ทุกๆ 0.1s
            if curr_t - last_ui >= 0.1:
                last_ui = curr_t
                os.system("clear")
                print("═══════════════════════════════════════════════════════════════════════════════════════════")
                print(f"  🎯 TARGET VELOCITY & TICKRATE HUNTER — {name} ({hex(u_ptr)})")
                print(f"  Team: {team} [{team_label}] | Distance: {cur_dist:.0f} m | Time: {elapsed:5.1f}s | Loops: {loop_count}")
                print("═══════════════════════════════════════════════════════════════════════════════════════════")
                print(f"{'Move Ptr':<10s} | {'Vel Off':<9s} | {'Type':<6s} | {'Speed (km/h)':<13s} | {'Ticks':<6s} | {'Tickrate':<10s} | {'Verdict / Status':<22s}")
                print("─" * 91)

                # เรียงตาม Ticks สูงสุด และความเร็วที่ไม่ใช่ศูนย์
                sorted_metrics = sorted(
                    metrics.items(),
                    key=lambda item: (item[1]["ticks"], item[1]["current_spd"] > 0.1),
                    reverse=True
                )

                for (p_off, v_off, dtype), m in sorted_metrics:
                    hz = m["ticks"] / elapsed
                    p_str = f"0x{p_off:04X}"
                    v_str = f"0x{v_off:04X}"
                    
                    if not m["is_valid_ptr"]:
                        status_tag = "⚪ (Null Pointer)"
                        spd_str = "    N/A"
                    elif m["current_spd"] < 0.1 and m["ticks"] == 0:
                        status_tag = "⚪ (Zero / Static)"
                        spd_str = f"{m['current_spd']:7.1f}"
                    else:
                        spd_str = f"{m['current_spd']:7.1f}"
                        if hz >= 40.0:
                            status_tag = f"⚡ ULTRA SMOOTH ({hz:4.1f} Hz)"
                        elif hz >= 10.0:
                            status_tag = f"🟢 SMOOTH ({hz:4.1f} Hz)"
                        elif hz >= 1.0:
                            status_tag = f"🟡 NETWORK ({hz:4.1f} Hz)"
                        else:
                            status_tag = f"⚪ STATIC ({hz:4.1f} Hz)"

                    # Badge สำหรับ Offset สำคัญ
                    note = ""
                    if p_off == OFF_AIR_MOVEMENT and v_off == OFF_AIR_VEL:
                        note = " [0x018 Net]"
                    elif p_off == OFF_MY_AIR_MOVEMENT and v_off == OFF_MY_AIR_VEL:
                        note = " [0xD48 Hi]"
                    elif p_off == 0x24C0 and v_off == 0x0E90:
                        note = " [24C0 Flt]"
                    elif p_off == 0x24C8 and v_off == 0x0DB8:
                        note = " [24C8 Flt]"

                    print(f"0x{p_off:04X}     | 0x{v_off:04X}    | {dtype:<6s} | {spd_str} km/h   | {m['ticks']:5d}  | {hz:6.1f} Hz   | {status_tag}{note}")

                print("═══════════════════════════════════════════════════════════════════════════════════════════")
                print("  [Ctrl+C] กลับสู่เมนูหลัก  |  ข้อมูลกำลังอัปเดตแบบ Realtime...")

            time.sleep(MONITOR_SLEEP)

    except KeyboardInterrupt:
        print("\n\n🛑 ผู้ใช้กดหยุดการเฝ้าดู...")
        time.sleep(0.5)


def show_close_air_units_menu(scanner, cgame_base, my_unit_ptr, my_team, my_pos, candidate_offsets, base_address):
    """หน้าต่างแสดงรายชื่อเครื่องบินลำใกล้เคียงทั้งหมด (รวมทีมเดียวกันและศัตรู)."""
    while True:
        os.system("clear")
        my_pos = get_unit_pos(scanner, my_unit_ptr) if my_unit_ptr else None
        units = get_all_close_air_units(scanner, cgame_base, my_unit_ptr, my_team, my_pos)

        print("═══════════════════════════════════════════════════════════════════════════════════")
        print("  ✈️  CLOSE AIR UNITS LIST (INCLUDES FRIENDLY & ENEMY)")
        print(f"  My Unit: {hex(my_unit_ptr) if my_unit_ptr else 'N/A'} | Team: {my_team} | Loaded VEL Offsets: {len(candidate_offsets)} รายการ")
        print("═══════════════════════════════════════════════════════════════════════════════════")

        if not units:
            print(f"\n[-] ไม่พบเครื่องบินอื่นในระยะ {int(MAX_SEARCH_DISTANCE/1000)} กิโลเมตร")
            print("    (กรุณาเข้าห้องรบ/Custom Match/Test Flight ที่มีบอทบิน)")
            print("\n[r] รีเฟรช  |  [0] กลับเมนูหลัก")
            choice = input("\n👉 เลือก: ").strip()
            if choice == "0":
                break
            continue

        print(f"{'#':<3s} | {'Unit Name':<18s} | {'Pointer':<12s} | {'Team':<16s} | {'Distance':<10s} | {'Status':<10s}")
        print("─" * 83)

        for idx, u in enumerate(units[:20], 1):
            team_str = f"🟢 Team {u['team']} [FRIENDLY]" if u["is_friendly"] else f"🔴 Team {u['team']} [ENEMY]"
            dist_str = f"{u['dist']:.0f} m"
            print(f"{idx:2d}  | {u['name']:<18s} | {hex(u['ptr']):<12s} | {team_str:<16s} | {dist_str:<10s} | ✈️ ALIVE")

        print("═══════════════════════════════════════════════════════════════════════════════════")
        print("👉 ใส่หมายเลข [1-20] เพื่อเลือกเป้าหมายและวิเคราะห์ VEL Offsets + Tickrate")
        print("   [r] รีเฟรชรายการ  |  [0] กลับเมนูหลัก")
        cmd = input("\n👉 เลือกคำสั่ง: ").strip().lower()

        if cmd == "0":
            break
        elif cmd == "r":
            continue
        elif cmd.isdigit():
            idx = int(cmd) - 1
            if 0 <= idx < len(units):
                selected = units[idx]
                run_target_velocity_monitor(scanner, selected, candidate_offsets, base_address, my_unit_ptr)


def auto_lock_closest_air_unit(scanner, cgame_base, my_unit_ptr, my_team, my_pos, candidate_offsets, base_address):
    """ล็อกเป้าหมายเครื่องบินลำที่ใกล้ที่สุดทันที (ทั้งมิตรและศัตรู)."""
    my_pos = get_unit_pos(scanner, my_unit_ptr) if my_unit_ptr else None
    units = get_all_close_air_units(scanner, cgame_base, my_unit_ptr, my_team, my_pos)
    if not units:
        print("\n[-] ไม่พบเครื่องบินในระยะ...")
        time.sleep(1.0)
        return
    closest = units[0]
    run_target_velocity_monitor(scanner, closest, candidate_offsets, base_address, my_unit_ptr)


def main():
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_address)

    candidate_offsets, source_path = load_candidate_offsets()

    while True:
        os.system("clear")
        cgame_base = get_cgame_base(scanner, base_address)
        my_unit_ptr, my_team = get_local_team(scanner, base_address) if base_address else (None, 0)
        my_pos = get_unit_pos(scanner, my_unit_ptr) if my_unit_ptr else None

        # สรุปชื่อยูนิตเรา
        my_name = "UNKNOWN"
        if my_unit_ptr:
            st = get_unit_status(scanner, my_unit_ptr, read_name=True)
            if st and len(st) >= 3 and st[2]:
                my_name = st[2]

        print("══════════════════════════════════════════════════════════════════════")
        print("  🚀 REWORKED VELOCITY HUNTER SCANNER (MULTI-TEAM AIR TARGETS)")
        print(f"  PID: {pid} | Base: {hex(base_address)}")
        print(f"  🎮 My Unit: {my_name} ({hex(my_unit_ptr) if my_unit_ptr else 'N/A'}) | Team: {my_team}")
        print(f"  📁 Offsets Loaded: {len(candidate_offsets)} รายการ จาก [{os.path.basename(source_path)}]")
        print("══════════════════════════════════════════════════════════════════════")
        print("[1] 🔒 ล็อกเป้าหมายเครื่องบินลำที่ใกล้ที่สุดอัตโนมัติ (Auto-Lock Closest Air)")
        print("[2] 📋 แสดงรายการเครื่องบินใกล้เคียงทุกลำ (Include Friendly & Enemy)")
        print("[3] 🔄 โหลดไฟล์ Offset Candidates ใหม่ (Reload 01_my_unit_velocity_scan)")
        print("[0] ❌ ออกจากโปรแกรม")
        print("──────────────────────────────────────────────────────────────────────")

        choice = input("👉 เลือกคำสั่ง: ").strip()

        if choice == "0":
            break
        elif choice == "1":
            if not cgame_base or not my_pos:
                print("[-] ยังไม่พบตำแหน่งเครื่องบิน กรุณาเข้าห้องบินในเกม...")
                time.sleep(1.0)
                continue
            auto_lock_closest_air_unit(scanner, cgame_base, my_unit_ptr, my_team, my_pos, candidate_offsets, base_address)
        elif choice == "2":
            if not cgame_base or not my_pos:
                print("[-] ยังไม่พบตำแหน่งเครื่องบิน กรุณาเข้าห้องบินในเกม...")
                time.sleep(1.0)
                continue
            show_close_air_units_menu(scanner, cgame_base, my_unit_ptr, my_team, my_pos, candidate_offsets, base_address)
        elif choice == "3":
            candidate_offsets, source_path = load_candidate_offsets()
            print(f"\n[+] โหลดสำเร็จ {len(candidate_offsets)} รายการ จาก {source_path}")
            time.sleep(1.0)


if __name__ == "__main__":
    main()