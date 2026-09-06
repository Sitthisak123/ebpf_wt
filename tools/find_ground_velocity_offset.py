import os
import sys
import struct
import math
import time

sys.path.insert(0, "/home/xda-7/MyProjects/Python/ebpf_wt")

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import get_cgame_base, get_local_team, get_unit_pos, is_valid_ptr

def scan_for_vel():
    pid = get_game_pid()
    scanner = MemoryScanner(pid)
    base_addr = get_game_base_address(pid)
    init_dynamic_offsets(scanner, base_addr)
    cgame = get_cgame_base(scanner, base_addr)
    my_unit, my_team = get_local_team(scanner, base_addr)

    print(f"[*] ติดตาม MyUnit: {hex(my_unit)}")
    print("[*] กรุณาขับรถถังวิ่งด้วยความเร็วปกติ (เช่น 20-70 km/h) ระบบจะค้นหา Offset Velocity อัตโนมัติ...")

    last_pos = None
    last_t = time.time()
    
    match_votes = {}  # key: (source_label, offset), value: count

    for step in range(300):  # ตรวจสอบ 300 รอบ (~5 วินาที)
        time.sleep(0.016)
        curr_t = time.time()
        dt = curr_t - last_t
        last_t = curr_t

        pos = get_unit_pos(scanner, my_unit)
        if not pos or not last_pos:
            last_pos = pos
            continue

        dx = pos[0] - last_pos[0]
        dy = pos[1] - last_pos[1]
        dz = pos[2] - last_pos[2]
        last_pos = pos

        if dt <= 0.001:
            continue

        pv_x, pv_y, pv_z = dx / dt, dy / dt, dz / dt
        speed_ms = math.hypot(pv_x, pv_z)
        speed_kmh = speed_ms * 3.6

        if speed_kmh < 15.0:  # รอให้รถวิ่งเร็วกว่า 15 km/h
            sys.stdout.write(f"\r[รอรถวิ่ง] ความเร็วปัจจุบัน: {speed_kmh:.1f} km/h (กรุณาเหยียบคันเร่ง)")
            sys.stdout.flush()
            continue

        sys.stdout.write(f"\r[กำลังสแกน] ความเร็วรถ: {speed_kmh:.1f} km/h ...          ")
        sys.stdout.flush()

        # 1. สแกนอ่าน memory ของ my_unit โดยตรง (0x000 ถึง 0x2000)
        u_mem = scanner.read_mem(my_unit, 0x2000)
        if u_mem:
            for off in range(0, len(u_mem) - 12, 4):
                fx, fy, fz = struct.unpack_from("<fff", u_mem, off)
                mag = math.hypot(fx, fz)
                if abs(mag - speed_ms) < 2.5:  # ใกล้เคียงกับความเร็วจริง +- 2.5 m/s
                    # ตรวจสอบว่าทิศทางสอดคล้องกันไหม
                    dot = (fx * pv_x + fz * pv_z) / (mag * speed_ms + 1e-6)
                    if dot > 0.85:  # ทิศทางเดียวกัน > 85%
                        key = ("my_unit direct", off)
                        match_votes[key] = match_votes.get(key, 0) + 1

        # 2. สแกน pointers ย่อยใน my_unit (sub-structures เช่น Movement, Physics, Controller)
        if u_mem:
            for p_off in range(0x100, len(u_mem) - 8, 8):
                sub_ptr = struct.unpack_from("<Q", u_mem, p_off)[0]
                if is_valid_ptr(sub_ptr) and sub_ptr != my_unit:
                    sub_data = scanner.read_mem(sub_ptr, 0x400)
                    if sub_data:
                        for s_off in range(0, len(sub_data) - 12, 4):
                            fx, fy, fz = struct.unpack_from("<fff", sub_data, s_off)
                            mag = math.hypot(fx, fz)
                            if abs(mag - speed_ms) < 2.5:
                                dot = (fx * pv_x + fz * pv_z) / (mag * speed_ms + 1e-6)
                                if dot > 0.85:
                                    key = (f"ptr at my_unit+{hex(p_off)}", s_off)
                                    match_votes[key] = match_votes.get(key, 0) + 1

        if len(match_votes) > 0 and max(match_votes.values()) >= 15:
            print("\n[+] พบผู้ต้องสงสัยที่มีคะแนนโหวตสูง!")
            break

    print("\n" + "=" * 70)
    print("🎯 สรุปผลการสแกนหา Offset Ground Velocity:")
    print("=" * 70)
    if not match_votes:
        print("[-] ไม่พบ Offset ที่ตรงกับความเร็วรถ (อาจเป็นเพราะรถไม่ได้วิ่งเร็วกว่า 15 km/h ขณะสแกน)")
    else:
        sorted_matches = sorted(match_votes.items(), key=lambda x: x[1], reverse=True)
        for (src, off), votes in sorted_matches[:10]:
            print(f"  [+] {src} + {hex(off)}: โหวต {votes} ครั้ง")
    print("=" * 70)

if __name__ == "__main__":
    scan_for_vel()
