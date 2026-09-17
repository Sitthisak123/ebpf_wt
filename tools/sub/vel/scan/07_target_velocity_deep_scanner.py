#!/usr/bin/env python3
"""
07_target_velocity_deep_scanner.py — Target Air Velocity Deep Memory & Tickrate Hunter

เครื่องมือสแกนหา Offset ความเร็ว (Velocity) และวัด Tick Rate บนเครื่องบินเป้าหมาย (Target) โดยตรง
ด้วยวิธี Deep Memory Scan:
  1. ตรวจจับเครื่องบินเป้าหมาย (ทั้งมิตรและศัตรู) และวัดความเร็วเคลื่อนที่จริง (Delta Pos / Delta t)
  2. กวาดหา Pointer ทั้งหมดในโครงสร้างของ Target (0x0000 - 0x3000)
  3. สแกนหา Float/Double Vec3 ในทุก Memory Block ที่ความเร็วสอดคล้องกับความเร็วจริง
  4. มอนิเตอร์วัด Tick Rate (Hz) แบบ Realtime เพื่อค้นหา High-Tick Target Velocity
  5. บันทึกผลลัพธ์เป็น TXT และ JSON อัตโนมัติ
"""

import os
import sys
import struct
import math
import time
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

MAX_SCAN_DISTANCE = 50000.0   # ระยะค้นหาสูงสุด 50 กม.
CHANGE_THRESHOLD  = 0.005     # ค่าความต่างเวกเตอร์ขั้นต่ำที่นับเป็น 1 Tick
MONITOR_INTERVAL  = 3.0       # รอบเวลาเก็บตัวอย่างต่อครั้ง (วินาที)


def calc_3d_dist(p1, p2):
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2 + (p1[2] - p2[2])**2)


def get_all_air_targets(scanner, cgame_base, my_unit_ptr, my_team, my_pos):
    """ค้นหาเครื่องบินทุกลำที่ยังมีชีวิตอยู่ในแผนที่."""
    all_units = get_all_units(scanner, cgame_base)
    if not all_units:
        return []

    targets = []
    for u_ptr, is_air in all_units:
        if u_ptr == my_unit_ptr or not is_air:
            continue

        st = get_unit_status(scanner, u_ptr, read_name=True)
        if not st:
            continue

        team = st[0] if isinstance(st, tuple) else st.get("team", 0)
        state = st[1] if isinstance(st, tuple) else st.get("state", 0)
        name = st[2] if (isinstance(st, tuple) and len(st) >= 3 and st[2]) else "AIR"

        if state >= 2:  # ยูนิตตาย/ตกแล้ว
            continue

        pos = get_unit_pos(scanner, u_ptr)
        if not pos or all(abs(p) < 0.1 for p in pos):
            continue

        dist = calc_3d_dist(my_pos, pos) if my_pos else 0.0
        if dist <= MAX_SCAN_DISTANCE:
            targets.append({
                "ptr": u_ptr,
                "name": name,
                "team": team,
                "is_friendly": (team == my_team and my_team > 0),
                "dist": dist,
                "pos": pos,
                "spd": 0.0,
            })

    targets.sort(key=lambda x: x["dist"])
    return targets


def measure_ground_truth_speed(scanner, u_ptr, sample_sec=0.5):
    """วัดความเร็วจริงของยูนิตจากอัตราการเปลี่ยนตำแหน่ง (Delta Pos / Delta t)."""
    p1 = get_unit_pos(scanner, u_ptr)
    t1 = time.time()
    time.sleep(sample_sec)
    p2 = get_unit_pos(scanner, u_ptr)
    t2 = time.time()

    if not p1 or not p2:
        return 0.0, (0.0, 0.0, 0.0)

    dt = max(t2 - t1, 1e-4)
    vx = (p2[0] - p1[0]) / dt
    vy = (p2[1] - p1[1]) / dt
    vz = (p2[2] - p1[2]) / dt
    spd_kmh = math.sqrt(vx*vx + vy*vy + vz*vz) * 3.6
    return spd_kmh, (vx, vy, vz)


def scan_target_velocity_candidates(scanner, target_ptr, expected_spd_kmh, tolerance_pct=40.0):
    """
    กวาดสแกนหาเวกเตอร์ความเร็ว (FLOAT & DOUBLE) ในทุก Pointer และตัวถังของ Target Unit.
    """
    candidates = []
    seen_addrs = set()

    if expected_spd_kmh > 30.0:
        min_spd = max(10.0, expected_spd_kmh * (1.0 - tolerance_pct / 100.0))
        max_spd = min(3500.0, expected_spd_kmh * (1.0 + tolerance_pct / 100.0))
    else:
        min_spd = 50.0
        max_spd = 2500.0

    u_data = scanner.read_mem(target_ptr, 0x3000)
    if not u_data:
        return []

    target_pointers = [
        (0x0, target_ptr, "DIRECT_UNIT")
    ]

    for p_off in range(0, len(u_data) - 8, 8):
        p_val = struct.unpack_from("<Q", u_data, p_off)[0]
        if is_valid_ptr(p_val) and p_val != target_ptr:
            target_pointers.append((p_off, p_val, f"PTR_0x{p_off:04X}"))

    for p_off, p_val, label in target_pointers:
        block_size = 0x1000
        mem = scanner.read_mem(p_val, block_size)
        if not mem:
            continue

        # 1. FLOAT Vec3
        for v_off in range(0, len(mem) - 12, 4):
            try:
                vx, vy, vz = struct.unpack_from("<fff", mem, v_off)
                if not (math.isfinite(vx) and math.isfinite(vy) and math.isfinite(vz)):
                    continue
                spd = math.sqrt(vx*vx + vy*vy + vz*vz) * 3.6
                if min_spd <= spd <= max_spd:
                    abs_addr = p_val + v_off
                    if abs_addr not in seen_addrs:
                        seen_addrs.add(abs_addr)
                        candidates.append({
                            "move_ptr_offset": p_off,
                            "move_ptr_val": p_val,
                            "label": label,
                            "vel_offset": v_off,
                            "data_type": "FLOAT",
                            "init_speed": spd,
                            "abs_addr": abs_addr
                        })
            except Exception:
                pass

        # 2. DOUBLE Vec3
        for v_off in range(0, len(mem) - 24, 8):
            try:
                vx, vy, vz = struct.unpack_from("<ddd", mem, v_off)
                if not (math.isfinite(vx) and math.isfinite(vy) and math.isfinite(vz)):
                    continue
                spd = math.sqrt(vx*vx + vy*vy + vz*vz) * 3.6
                if min_spd <= spd <= max_spd:
                    abs_addr = p_val + v_off
                    if abs_addr not in seen_addrs:
                        seen_addrs.add(abs_addr)
                        candidates.append({
                            "move_ptr_offset": p_off,
                            "move_ptr_val": p_val,
                            "label": label,
                            "vel_offset": v_off,
                            "data_type": "DOUBLE",
                            "init_speed": spd,
                            "abs_addr": abs_addr
                        })
            except Exception:
                pass

    return candidates


def run_target_tickrate_profiler(scanner, target_ptr, target_name, candidates, duration=MONITOR_INTERVAL):
    """มอนิเตอร์ความถี่การเปลี่ยนค่า (Tick Rate) ของทุก Candidate บนตัว Target."""
    for c in candidates:
        c["ticks"] = 0
        c["reads"] = 0
        c["last_vec"] = None
        c["current_speed"] = c["init_speed"]
        c["current_vec"] = (0.0, 0.0, 0.0)

    start_time = time.time()
    loops = 0
    p_cache = {}

    while True:
        curr_t = time.time()
        elapsed = curr_t - start_time
        if elapsed >= duration:
            break

        loops += 1

        for c in candidates:
            p_off = c["move_ptr_offset"]
            dtype = c["data_type"]
            v_off = c["vel_offset"]

            if p_off == 0x0:
                p_val = target_ptr
            else:
                if p_off not in p_cache:
                    raw_p = scanner.read_mem(target_ptr + p_off, 8)
                    p_val = struct.unpack("<Q", raw_p)[0] if raw_p else 0
                    p_cache[p_off] = p_val
                else:
                    p_val = p_cache[p_off]

            if not is_valid_ptr(p_val):
                continue

            size = 24 if dtype == "DOUBLE" else 12
            fmt = "<ddd" if dtype == "DOUBLE" else "<fff"
            raw_v = scanner.read_mem(p_val + v_off, size)
            if not raw_v or len(raw_v) < size:
                continue

            try:
                vec = struct.unpack(fmt, raw_v)
                if not all(math.isfinite(x) for x in vec):
                    continue

                spd = math.sqrt(sum(x*x for x in vec)) * 3.6
                c["current_speed"] = spd
                c["current_vec"] = vec
                c["reads"] += 1

                if c["last_vec"] is not None:
                    diff = sum(abs(vec[i] - c["last_vec"][i]) for i in range(3))
                    if diff > CHANGE_THRESHOLD:
                        c["ticks"] += 1
                c["last_vec"] = vec
            except Exception:
                pass

        time.sleep(0.001)

    total_elapsed = max(time.time() - start_time, 1e-4)
    for c in candidates:
        c["hz"] = c["ticks"] / total_elapsed

    candidates.sort(key=lambda x: (x["hz"], x["ticks"]), reverse=True)
    return candidates, total_elapsed, loops


def save_results(target_info, ground_truth_spd, ranked_candidates, monitor_duration):
    """บันทึกรายงานผลลัพธ์ลง Text File และ JSON."""
    os.makedirs(os.path.join(PROJECT_ROOT, "dumps"), exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    txt_path = os.path.join(PROJECT_ROOT, "dumps", f"07_target_velocity_deep_scan_{ts}.txt")
    json_path = os.path.join(PROJECT_ROOT, "dumps", f"07_target_velocity_deep_scan_{ts}.json")
    latest_json = os.path.join(PROJECT_ROOT, "dumps", "07_target_velocity_deep_scan_latest.json")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("═══════════════════════════════════════════════════════════════════════════════════\n")
        f.write("  🎯 TARGET AIR VELOCITY DEEP SCAN REPORT\n")
        f.write(f"  Target: {target_info['name']} ({hex(target_info['ptr'])}) | Team: {target_info['team']}\n")
        f.write(f"  Distance: {target_info['dist']:.1f} m | Physical Speed (ΔPos/Δt): {ground_truth_spd:.1f} km/h\n")
        f.write(f"  Monitor Duration: {monitor_duration:.2f} s | Total Candidates: {len(ranked_candidates)}\n")
        f.write("═══════════════════════════════════════════════════════════════════════════════════\n\n")
        f.write(f"{'#':<3} | {'Move Off':<10} | {'Vel Off':<8} | {'Type':<6} | {'Tick Rate':<10} | {'Ticks':<6} | {'Speed (km/h)':<12} | {'Note'}\n")
        f.write("-" * 90 + "\n")

        for idx, c in enumerate(ranked_candidates, 1):
            note = ""
            if c["hz"] >= 30.0:
                note = "⭐⭐⭐ ULTRA HIGH-TICK (>30Hz)"
            elif c["hz"] >= 10.0:
                note = "⭐⭐ MID-TICK (10-30Hz)"
            elif c["hz"] > 0.5:
                note = "⭐ LOW-TICK (0.5-10Hz)"
            else:
                note = "⚪ STATIC/STALL"

            if c["move_ptr_offset"] == OFF_AIR_MOVEMENT and c["vel_offset"] == OFF_AIR_VEL:
                note += " [MATCH OFF_AIR_VEL (0x18/0x318)]"
            elif c["move_ptr_offset"] == OFF_MY_AIR_MOVEMENT:
                note += " [MY_AIR_MOVEMENT (0xD48)]"

            line = f"{idx:02d}  | 0x{c['move_ptr_offset']:04X}     | 0x{c['vel_offset']:04X}   | {c['data_type']:<6} | {c['hz']:5.1f} Hz  | {c['ticks']:5d}  | {c['current_speed']:10.1f}   | {note}\n"
            f.write(line)

    payload = {
        "timestamp": ts,
        "target": {
            "ptr": hex(target_info["ptr"]),
            "name": target_info["name"],
            "team": target_info["team"],
            "distance_m": target_info["dist"],
            "ground_truth_spd_kmh": ground_truth_spd
        },
        "monitor_duration_sec": monitor_duration,
        "total_candidates": len(ranked_candidates),
        "candidates": [
            {
                "rank": idx,
                "move_ptr_offset": hex(c["move_ptr_offset"]),
                "vel_offset": hex(c["vel_offset"]),
                "data_type": c["data_type"],
                "tickrate_hz": round(c["hz"], 2),
                "ticks": c["ticks"],
                "speed_kmh": round(c["current_speed"], 2),
                "is_ultra_high_tick": c["hz"] >= 30.0
            }
            for idx, c in enumerate(ranked_candidates, 1)
        ]
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    with open(latest_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    return txt_path, json_path, latest_json


def main():
    print("=" * 60)
    print("🚀 [07] TARGET AIR VELOCITY DEEP MEMORY & TICKRATE SCANNER")
    print("=" * 60)

    pid = get_game_pid()
    if not pid:
        print("[-] ไม่พบโปรเซสเกม War Thunder (aces)!")
        return

    base_addr = get_game_base_address(pid)
    if not base_addr:
        print("[-] ไม่พบ Base Address ของเกม!")
        return

    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)

    cgame_base = get_cgame_base(scanner, base_addr)
    if not cgame_base:
        print("[-] ไม่พบ CGame Base Address!")
        return

    my_unit_ptr, my_team = get_local_team(scanner, base_addr)
    my_pos = get_unit_pos(scanner, my_unit_ptr) if my_unit_ptr else None

    print(f"[+] My Unit: {hex(my_unit_ptr) if my_unit_ptr else 'NONE'} | My Team: {my_team}")

    targets = get_all_air_targets(scanner, cgame_base, my_unit_ptr, my_team, my_pos)
    if not targets:
        print("[-] ไม่พบเครื่องบินเป้าหมายอื่นในระยะ 50 กม.!")
        return

    # วัดความเร็วเบื้องต้นของ 5 ลำแรกเพื่อค้นหาลำที่บินอยู่
    print("\n[*] ⏳ กำลังตรวจสอบความเร็วการเคลื่อนที่ของเป้าหมาย...")
    moving_target = None
    for t in targets[:8]:
        s, _ = measure_ground_truth_speed(scanner, t["ptr"], sample_sec=0.15)
        t["spd"] = s
        if s > 25.0 and moving_target is None:
            moving_target = t

    print(f"\n[+] พบเครื่องบินเป้าหมาย {len(targets)} ลำ (แสดงลำดับต้นๆ):")
    print(f"{'#':<3} | {'Team':<10} | {'Name':<20} | {'Distance':<10} | {'Speed':<12} | {'Pointer'}")
    print("-" * 75)
    for i, t in enumerate(targets[:10], 1):
        t_label = "🟢 FRIEND" if t["is_friendly"] else "🔴 ENEMY"
        spd_str = f"{t['spd']:.1f} km/h" if t["spd"] > 5.0 else "PARKED (0)"
        print(f"{i:<3} | {t_label:<10} | {t['name']:<20} | {t['dist']:7.1f}m | {spd_str:<12} | {hex(t['ptr'])}")

    # เลือกลำที่กำลังบินอยู่เป็นอันดับแรก หากไม่มีให้เลือกลำดับแรก
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        choice = int(sys.argv[1]) - 1
        selected_target = targets[choice] if 0 <= choice < len(targets) else targets[0]
    elif moving_target:
        selected_target = moving_target
        print(f"\n🎯 ตรวจพบเป้าหมายที่กำลังบินอยู่! เลือกลำนี้อัตโนมัติ: {selected_target['name']} ({selected_target['spd']:.1f} km/h)")
    else:
        selected_target = targets[0]
        print(f"\n👉 เลือกเป้าหมายใกล้สุด: {selected_target['name']} ({hex(selected_target['ptr'])}) ระยะ {selected_target['dist']:.1f}m")

    # 1. วัดความเร็วจริง (Ground Truth Speed)
    print("\n[*] ⏳ กำลังวัดความเร็วทางกายภาพจริงของเป้าหมาย (ΔPos/Δt)...")
    gt_spd, gt_vec = measure_ground_truth_speed(scanner, selected_target["ptr"], sample_sec=0.6)
    print(f"    └─ 📍 Ground Truth Speed: {gt_spd:.1f} km/h (Vec: {gt_vec[0]:.1f}, {gt_vec[1]:.1f}, {gt_vec[2]:.1f})")

    if gt_spd < 15.0:
        print("    ⚠️  คำเตือน: เป้าหมายจอดอยู่นิ่งๆ (ความเร็ว ~0 km/h) ค่าความเร็วใน Memory จะไม่เปลี่ยนแปลงมาก")
        print("    💡 แนะนำ: สแกนขณะที่เป้าหมายกำลังบินอยู่ในอากาศ เพื่อแยกแยะ High-Tick จากการเปลี่ยนแปลงของเวกเตอร์")

    # 2. ทำ Deep Memory Scan
    print(f"\n[*] 🔍 กำลังทำ Deep Memory Scan บนตัว {selected_target['name']} ({hex(selected_target['ptr'])})...")
    candidates = scan_target_velocity_candidates(scanner, selected_target["ptr"], expected_spd_kmh=gt_spd)
    print(f"    └─ 🎯 พบ Memory Vector Candidates ทั้งหมด: {len(candidates)} รายการ")

    if not candidates:
        print("[-] ไม่พบ Candidate เวกเตอร์ที่ตรงกับช่วงความเร็วนี้")
        return

    # 3. มอนิเตอร์วัด Tick Rate แบบละเอียด
    print(f"\n[*] ⏱️  กำลังเริ่มมอนิเตอร์วัด Tick Rate ({MONITOR_INTERVAL:.1f} วินาที)...")
    ranked, elapsed, loop_count = run_target_tickrate_profiler(scanner, selected_target["ptr"], selected_target["name"], candidates, duration=MONITOR_INTERVAL)

    # 4. แสดงผลลัพธ์
    print("\n" + "=" * 80)
    print(f"🏆 TOP HIGH-TICK VELOCITY CANDIDATES FOR {selected_target['name']}")
    print(f"   Physical Speed: {gt_spd:.1f} km/h | Loops: {loop_count} ({loop_count/elapsed:.1f} Hz)")
    print("=" * 80)
    print(f"{'#':<3} | {'Move Off':<10} | {'Vel Off':<8} | {'Type':<6} | {'Tick Rate':<10} | {'Ticks':<6} | {'Speed (km/h)':<12} | {'Note'}")
    print("-" * 80)

    for idx, c in enumerate(ranked[:15], 1):
        note = ""
        if c["hz"] >= 30.0:
            note = "⭐⭐⭐ ULTRA HIGH-TICK"
        elif c["hz"] >= 10.0:
            note = "⭐⭐ MID-TICK"
        elif c["hz"] > 0.5:
            note = "⭐ LOW-TICK"
        else:
            note = "⚪ STATIC"

        if c["move_ptr_offset"] == OFF_AIR_MOVEMENT and c["vel_offset"] == OFF_AIR_VEL:
            note += " [OFF_AIR_VEL 0x18/0x318]"

        print(f"{idx:02d}  | 0x{c['move_ptr_offset']:04X}     | 0x{c['vel_offset']:04X}   | {c['data_type']:<6} | {c['hz']:5.1f} Hz  | {c['ticks']:5d}  | {c['current_speed']:10.1f}   | {note}")

    # 5. บันทึกผลลงไฟล์
    txt_path, json_path, latest_json = save_results(selected_target, gt_spd, ranked, elapsed)
    print("\n" + "=" * 80)
    print(f"[✅] บันทึกรายงาน Text: {txt_path}")
    print(f"[✅] บันทึกผลลัพธ์ JSON: {json_path}")
    print(f"[✅] อัปเดต Latest JSON: {latest_json}")
    print("=" * 80)


if __name__ == "__main__":
    main()
