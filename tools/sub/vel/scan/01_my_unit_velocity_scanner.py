#!/usr/bin/env python3
"""
01_my_unit_velocity_scanner.py — My Unit Velocity Scanner (Exclusive Single-Unit Mode)

เครื่องมือค้นหาและกรอง Offset ของความเร็ว (Velocity) เฉพาะเครื่องบิน/ยานพาหนะที่เราขับเอง (My Unit เท่านั้น)
ไม่สแกนยูนิตอื่นในแมป เพื่อความรวดเร็ว แม่นยำ และตัดสัญญาณรบกวน 100%
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
    get_cgame_base, get_local_team, get_unit_status, is_valid_ptr,
    OFF_AIR_MOVEMENT, OFF_AIR_VEL, OFF_MY_AIR_MOVEMENT, OFF_MY_AIR_VEL
)

def clear_screen():
    os.system('clear')

def get_my_unit_info(scanner, base_address):
    """ค้นหา My Unit Pointer และชื่อยูนิต."""
    my_unit_ptr, my_team = get_local_team(scanner, base_address)
    unit_name = "UNKNOWN"
    if my_unit_ptr and is_valid_ptr(my_unit_ptr):
        st = get_unit_status(scanner, my_unit_ptr, read_name=True)
        if st:
            if isinstance(st, tuple) and len(st) >= 3 and st[2]:
                unit_name = st[2]
            elif isinstance(st, dict):
                unit_name = st.get("short_name") or st.get("name", "VEHICLE")
    return my_unit_ptr, my_team, unit_name

def print_header(candidates_count, my_unit_ptr, my_team, unit_name):
    clear_screen()
    print("==================================================")
    print("✈️  WTM TACTICAL: MY UNIT VELOCITY SCANNER")
    print("==================================================")
    if my_unit_ptr:
        print(f"🎮 My Unit: {unit_name} ({hex(my_unit_ptr)}) | Team: {my_team}")
    else:
        print("⚠️  สถานะ: ไม่พบ My Unit (กรุณาเข้าห้องรบ/Test Flight/Test Drive)")
    print(f"🎯 ผู้ต้องสงสัย (Candidates) ที่เหลืออยู่: {candidates_count} รายการ")
    print("==================================================")

def save_candidates_to_log(candidates, unit_name, my_unit_ptr):
    if not candidates:
        print("[-] ไม่มีข้อมูลให้บันทึก")
        return None
    
    os.makedirs("dumps", exist_ok=True)
    filename = os.path.join(
        "dumps",
        f"01_my_unit_velocity_scan_{time.strftime('%Y%m%d_%H%M%S')}.txt",
    )
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"=== WTM MY UNIT SCAN RESULTS ({time.strftime('%Y-%m-%d %H:%M:%S')}) ===\n")
            f.write(f"Unit: {unit_name} ({hex(my_unit_ptr) if my_unit_ptr else 'N/A'})\n")
            f.write(f"Total Candidates: {len(candidates)}\n")
            f.write("-" * 65 + "\n")
            for u_ptr, p_off, v_off, dt in candidates:
                match_tag = ""
                if p_off == OFF_MY_AIR_MOVEMENT and v_off == OFF_MY_AIR_VEL:
                    match_tag = " ⭐ [MATCH OFF_MY_AIR_VEL (Double 50Hz)]"
                elif p_off == OFF_AIR_MOVEMENT and v_off == OFF_AIR_VEL:
                    match_tag = " ⭐ [MATCH OFF_AIR_VEL (Float Net)]"
                line = f"Unit: {hex(u_ptr)} | Move Ptr: 0x{p_off:04X} | Vel Offset: 0x{v_off:04X} | Type: {dt}{match_tag}\n"
                f.write(line)
        return filename
    except Exception as e:
        print(f"[-] ไม่สามารถบันทึกไฟล์ได้: {e}")
        return None

def save_candidates_to_json(candidates, target_speed, tolerance, my_unit_ptr, unit_name):
    os.makedirs("dumps", exist_ok=True)
    payload = {
        "captured_at": time.time(),
        "captured_at_text": time.strftime("%Y-%m-%d %H:%M:%S"),
        "scan_target": "MY_UNIT_ONLY",
        "my_unit_ptr": hex(my_unit_ptr) if my_unit_ptr else None,
        "my_unit_name": unit_name,
        "target_speed_kmh": float(target_speed),
        "tolerance_kmh": float(tolerance),
        "candidate_count": len(candidates),
        "candidates": [
            {
                "unit_ptr": hex(u_ptr),
                "move_ptr_offset": hex(p_off),
                "vel_offset": hex(v_off),
                "data_type": dt,
                "is_verified_double_50hz": (p_off == OFF_MY_AIR_MOVEMENT and v_off == OFF_MY_AIR_VEL),
                "is_verified_float_net": (p_off == OFF_AIR_MOVEMENT and v_off == OFF_AIR_VEL),
            }
            for u_ptr, p_off, v_off, dt in candidates
        ],
    }
    filename = os.path.join(
        "dumps",
        f"01_my_unit_velocity_scan_{time.strftime('%Y%m%d_%H%M%S')}.json",
    )
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    latest_filename = os.path.join("dumps", "01_my_unit_velocity_scan_latest.json")
    with open(latest_filename, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return filename, latest_filename

def main():
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_address)

    tolerance = 2.0
    candidates = []
    last_target_speed = 0.0

    while True:
        my_unit_ptr, my_team, unit_name = get_my_unit_info(scanner, base_address)
        print_header(len(candidates), my_unit_ptr, my_team, unit_name)
        print(f"[+] 🎯 โหมดสแกน: MY UNIT ONLY (คันเดียว) | Tolerance: +- {tolerance} km/h")
        print("-" * 50)
        print("[1] 🔍 สแกนครั้งแรก (First Scan - My Unit Only)")
        print("[2] 🎯 สแกนคัดกรอง (Next Scan - กรองความเร็วใหม่)")
        print("[3] 👀 เฝ้าระวังสด (Watch Live Candidates)")
        print("[4] ⚙️  ตั้งค่า Tolerance (ระยะบวกลบ)")
        print("[5] 🗑️  ล้างค่า (Reset Candidates)")
        print("[6] 💾 บันทึกผลลงไฟล์ (Log TXT & JSON)")
        print("[0] ❌ ออกจากโปรแกรม")
        print("-" * 50)
        
        choice = input("👉 เลือกคำสั่ง: ").strip()
        
        if choice == '0':
            break
            
        elif choice == '4':
            val = input("   > ระยะบวกลบ (km/h) [ปัจจุบัน: {:.1f}]: ".format(tolerance)).strip()
            try:
                tolerance = float(val)
            except:
                pass

        elif choice == '5':
            candidates = []
            print("[!] Reset เรียบร้อย")
            time.sleep(0.5)

        elif choice == '6':
            if not candidates:
                print("[-] ไม่มี candidates ให้บันทึก")
                input("\nกด Enter เพื่อกลับไปเมนู...")
                continue
            log_path = save_candidates_to_log(candidates, unit_name, my_unit_ptr)
            try:
                json_path, latest_json_path = save_candidates_to_json(candidates, last_target_speed, tolerance, my_unit_ptr, unit_name)
            except Exception as e:
                json_path, latest_json_path = None, None
                print(f"[-] บันทึก JSON ไม่สำเร็จ: {e}")
            if log_path:
                print(f"\n[✅] TXT -> {log_path}")
            if json_path:
                print(f"[✅] JSON(unique) -> {json_path}")
            if latest_json_path:
                print(f"[✅] JSON(latest overwrite) -> {latest_json_path}")
            input("\nกด Enter เพื่อกลับไปเมนู...")

        elif choice == '1':
            my_unit_ptr, my_team, unit_name = get_my_unit_info(scanner, base_address)
            if not my_unit_ptr:
                print("\n[-] ⚠️ ไม่พบ My Unit! กรุณาเข้า Test Flight / Test Drive หรือห้องรบก่อน")
                input("กด Enter เพื่อกลับ...")
                continue

            val = input(f"   > ใส่ความเร็วปัจจุบันของ {unit_name} (km/h): ").strip()
            try:
                target_speed = float(val)
            except:
                continue
            last_target_speed = target_speed
            
            min_s, max_s = target_speed - tolerance, target_speed + tolerance
            print(f"[*] 🚀 กำลังสแกน My Unit ({hex(my_unit_ptr)}) ในช่วงความเร็ว {min_s:.1f} - {max_s:.1f} km/h...")
            
            candidates = []
            unit_data = scanner.read_mem(my_unit_ptr, 0x2500)
            if not unit_data:
                print("[-] ไม่สามารถอ่าน memory ของ My Unit ได้")
                input("Enter...")
                continue

            for ptr_off in range(0, len(unit_data) - 8, 8):
                ptr_val = struct.unpack_from("<Q", unit_data, ptr_off)[0]
                if is_valid_ptr(ptr_val):
                    mem_block = scanner.read_mem(ptr_val, 0x1000)
                    if not mem_block:
                        continue
                    # 1. Scan FLOAT vec3 (12 bytes)
                    for off in range(0, len(mem_block) - 12, 4):
                        try:
                            vx, vy, vz = struct.unpack_from("<fff", mem_block, off)
                            if math.isfinite(vx) and math.isfinite(vy) and math.isfinite(vz):
                                speed = math.sqrt(vx**2 + vy**2 + vz**2) * 3.6
                                if min_s <= speed <= max_s:
                                    candidates.append((my_unit_ptr, ptr_off, off, "FLOAT"))
                        except:
                            pass
                    # 2. Scan DOUBLE vec3 (24 bytes)
                    for off in range(0, len(mem_block) - 24, 8):
                        try:
                            vx, vy, vz = struct.unpack_from("<ddd", mem_block, off)
                            if math.isfinite(vx) and math.isfinite(vy) and math.isfinite(vz):
                                speed = math.sqrt(vx**2 + vy**2 + vz**2) * 3.6
                                if min_s <= speed <= max_s:
                                    candidates.append((my_unit_ptr, ptr_off, off, "DOUBLE"))
                        except:
                            pass

            print(f"[+] ✅ สแกนเสร็จสิ้น! พบผู้ต้องสงสัย {len(candidates)} รายการ")
            if 0 < len(candidates) <= 20:
                print("\nรายการที่ตรวจพบ:")
                for u, p, v, d in candidates:
                    tag = ""
                    if p == OFF_MY_AIR_MOVEMENT and v == OFF_MY_AIR_VEL:
                        tag = " 🌟 [OFF_MY_AIR_VEL DOUBLE (High-Tick 50Hz)]"
                    elif p == OFF_AIR_MOVEMENT and v == OFF_AIR_VEL:
                        tag = " 🌟 [OFF_AIR_VEL FLOAT (Standard Net)]"
                    print(f" -> Move Ptr: 0x{p:04X} | Vel Off: 0x{v:04X} ({d}){tag}")
            input("\nกด Enter เพื่อดำเนินการต่อ...")

        elif choice == '2':
            if not candidates:
                print("[-] ไม่มีรายการให้คัดกรอง กรุณาทำ First Scan ก่อน")
                input("Enter...")
                continue

            my_unit_ptr, my_team, unit_name = get_my_unit_info(scanner, base_address)
            val = input(f"   > เปลี่ยนความเร็วของ {unit_name} แล้วใส่ค่าใหม่ (km/h): ").strip()
            try:
                target_speed = float(val)
            except:
                continue
            last_target_speed = target_speed
                
            min_s, max_s = target_speed - tolerance, target_speed + tolerance
            print(f"[*] 🎯 กำลังคัดกรองรายการเดิมด้วยความเร็วใหม่ {min_s:.1f} - {max_s:.1f} km/h...")
            new_candidates = []

            for u_ptr, ptr_off, vel_off, dtype in candidates:
                # อัปเดต u_ptr ให้เป็น my_unit_ptr ล่าสุดเผื่อเกิดการ Respawn
                active_u = my_unit_ptr if my_unit_ptr else u_ptr
                unit_data = scanner.read_mem(active_u, 0x2500)
                if unit_data:
                    ptr_val = struct.unpack_from("<Q", unit_data, ptr_off)[0]
                    if is_valid_ptr(ptr_val):
                        vel_data = scanner.read_mem(ptr_val + vel_off, 24 if dtype == "DOUBLE" else 12)
                        if vel_data:
                            try:
                                if dtype == "FLOAT":
                                    vx, vy, vz = struct.unpack("<fff", vel_data)
                                else:
                                    vx, vy, vz = struct.unpack("<ddd", vel_data)
                                if math.isfinite(vx) and math.isfinite(vy) and math.isfinite(vz):
                                    speed = math.sqrt(vx**2 + vy**2 + vz**2) * 3.6
                                    if min_s <= speed <= max_s:
                                        new_candidates.append((active_u, ptr_off, vel_off, dtype))
                            except:
                                pass
            candidates = new_candidates
            print(f"[+] ✅ คัดกรองเสร็จสิ้น! เหลือผู้ต้องสงสัย {len(candidates)} รายการ")
            if 0 < len(candidates) <= 25:
                print("\nรายการที่ยังตรงเงื่อนไข:")
                for u, p, v, d in candidates:
                    tag = ""
                    if p == OFF_MY_AIR_MOVEMENT and v == OFF_MY_AIR_VEL:
                        tag = " 🌟 [OFF_MY_AIR_VEL DOUBLE (High-Tick 50Hz)]"
                    elif p == OFF_AIR_MOVEMENT and v == OFF_AIR_VEL:
                        tag = " 🌟 [OFF_AIR_VEL FLOAT (Standard Net)]"
                    print(f" -> Move Ptr: 0x{p:04X} | Vel Off: 0x{v:04X} ({d}){tag}")
            input("\nกด Enter เพื่อดำเนินการต่อ...")

        elif choice == '3':
            if not candidates:
                print("[-] ไม่มีรายการให้เฝ้าดู กรุณาทำ First Scan ก่อน")
                input("Enter...")
                continue
            try:
                clear_screen()
                print("══════════════════════════════════════════════════════════")
                print(f"👀 WATCH LIVE: เฝ้าดูความเร็วสดบน My Unit ({len(candidates)} รายการ)")
                print("   (กด Ctrl+C เพื่อกลับสู่เมนูหลัก)")
                print("══════════════════════════════════════════════════════════")
                while True:
                    cur_u, _, _ = get_my_unit_info(scanner, base_address)
                    active_u = cur_u if cur_u else candidates[0][0]
                    unit_data = scanner.read_mem(active_u, 0x2500)
                    if not unit_data:
                        time.sleep(0.3)
                        continue

                    lines = []
                    for u_ptr, p_off, v_off, dt in candidates[:12]:
                        ptr_val = struct.unpack_from("<Q", unit_data, p_off)[0]
                        if not is_valid_ptr(ptr_val):
                            continue
                        vel_data = scanner.read_mem(ptr_val + v_off, 24 if dt == "DOUBLE" else 12)
                        if not vel_data:
                            continue
                        if dt == "FLOAT":
                            vx, vy, vz = struct.unpack("<fff", vel_data)
                        else:
                            vx, vy, vz = struct.unpack("<ddd", vel_data)
                        if all(math.isfinite(x) for x in (vx, vy, vz)):
                            spd = math.sqrt(vx**2 + vy**2 + vz**2) * 3.6
                            tag = ""
                            if p_off == OFF_MY_AIR_MOVEMENT and v_off == OFF_MY_AIR_VEL:
                                tag = " 🌟 [50Hz Double]"
                            elif p_off == OFF_AIR_MOVEMENT and v_off == OFF_AIR_VEL:
                                tag = " 🌟 [Net Float]"
                            lines.append(f"Move: 0x{p_off:04X} | Vel: 0x{v_off:04X} ({dt:<6s}) -> Speed: {spd:6.1f} km/h | Vec: ({vx:6.1f}, {vy:6.1f}, {vz:6.1f}){tag}")

                    clear_screen()
                    print("══════════════════════════════════════════════════════════")
                    print(f"👀 WATCH LIVE: เฝ้าดูความเร็วสดบน My Unit ({len(candidates)} รายการ) [Ctrl+C หยุด]")
                    print("══════════════════════════════════════════════════════════")
                    for l in lines:
                        print(l)
                    time.sleep(0.2)
            except KeyboardInterrupt:
                pass

if __name__ == '__main__':
    main()
