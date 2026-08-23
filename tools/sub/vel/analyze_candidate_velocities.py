#!/usr/bin/env python3
"""
🧪 Candidate Velocity Classifier (World Vel vs Body Vel Analyzer)
สคริปต์วิเคราะห์แยกประเภท Candidates ทั้ง 15 รายการ เพื่อหาว่าตัวไหนเป็น World Vel และตัวไหนเป็น Body Vel
"""
import os
import sys
import time
import math
import struct

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul

# รายการ Candidates ทั้ง 15 รายการจากการสแกนของคุณ
CANDIDATES = [
    (0x0018, 0x0318, "FLOAT"),
    (0x0018, 0x0358, "FLOAT"),
    (0x0018, 0x0398, "FLOAT"),
    (0x0018, 0x03D8, "FLOAT"),
    (0x0018, 0x0418, "FLOAT"),
    (0x0018, 0x0458, "FLOAT"),
    (0x0018, 0x0498, "FLOAT"),
    (0x0018, 0x04D8, "FLOAT"),
    (0x0018, 0x0518, "FLOAT"),
    (0x0D28, 0x0068, "DOUBLE"),
    (0x0D28, 0x00D0, "DOUBLE"),
    (0x0D30, 0x0068, "DOUBLE"),
    (0x0D30, 0x00D0, "DOUBLE"),
    (0x12F8, 0x0034, "FLOAT"),
    (0x12F8, 0x0D84, "FLOAT"),
]

def calc_error_deg(v1, v2):
    m1 = math.sqrt(sum(x**2 for x in v1))
    m2 = math.sqrt(sum(x**2 for x in v2))
    if m1 < 1e-4 or m2 < 1e-4: return 999.0
    dot = max(-1.0, min(1.0, sum(a*b for a,b in zip(v1, v2)) / (m1 * m2)))
    return math.degrees(math.acos(dot))

def transform_body_to_world(vx, vy, vz, rot):
    # Dagor Basis Vectors
    fwd = (rot[0], rot[1], rot[2])
    up  = (rot[3], rot[4], rot[5])
    rgt = (rot[6], rot[7], rot[8])

    # Try common Body Frame mappings:
    # Mode 1: vz=Fwd, vy=Up, vx=Right
    w1 = (vz*fwd[0] + vy*up[0] + vx*rgt[0], vz*fwd[1] + vy*up[1] + vx*rgt[1], vz*fwd[2] + vy*up[2] + vx*rgt[2])
    # Mode 2: -vx=Fwd, vy=Up, vz=Right
    w2 = (-vx*fwd[0] + vy*up[0] + vz*rgt[0], -vx*fwd[1] + vy*up[1] + vz*rgt[1], -vx*fwd[2] + vy*up[2] + vz*rgt[2])
    # Mode 3: vx=Fwd, vy=Up, vz=Right
    w3 = (vx*fwd[0] + vy*up[0] + vz*rgt[0], vx*fwd[1] + vy*up[1] + vz*rgt[1], vx*fwd[2] + vy*up[2] + vz*rgt[2])
    
    return [("vz=Fwd", w1), ("-vx=Fwd", w2), ("vx=Fwd", w3)]

def main():
    pid = get_game_pid()
    if not pid:
        print("❌ War Thunder is not running!")
        return

    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)

    cgame_base = mul.get_cgame_base(scanner, base_addr)
    if not cgame_base:
        print("❌ Cannot find cgame_base!")
        return

    print("✅ Memory Scanner Ready. Watching 15 Candidate Velocities...")

    last_pos = None
    last_time = None

    while True:
        curr_t = time.time()
        my_unit, _ = mul.get_local_team(scanner, base_addr)

        if my_unit:
            pos = mul.get_unit_pos(scanner, my_unit)
            rot = mul.get_unit_rotation(scanner, my_unit)

            if pos and rot and last_pos and last_time:
                dt = curr_t - last_time
                if 0.02 <= dt <= 0.25:
                    # Ground Truth: Pos Delta Velocity in World Space
                    world_pos_vel = (
                        (pos[0] - last_pos[0]) / dt,
                        (pos[1] - last_pos[1]) / dt,
                        (pos[2] - last_pos[2]) / dt,
                    )
                    gt_speed_kmh = math.sqrt(sum(v**2 for v in world_pos_vel)) * 3.6

                    if gt_speed_kmh > 10.0:  # เมื่อเครื่องบินเคลื่อนที่
                        os.system("clear")
                        print("==========================================================================================")
                        print(f"📊 REAL-TIME VELOCITY CANDIDATE CLASSIFIER | Ground Truth Speed: {gt_speed_kmh:.1f} km/h")
                        print("==========================================================================================")
                        print(f"📍 GROUND TRUTH World Vel (Pos Delta) : ({world_pos_vel[0]:>6.1f}, {world_pos_vel[1]:>6.1f}, {world_pos_vel[2]:>6.1f})")
                        print("------------------------------------------------------------------------------------------")
                        print(f"{'#':<3} | {'Move Ptr':<8} | {'Vel Off':<7} | {'Type':<6} | {'Raw (vx, vy, vz)':<24} | {'Classification & Match':<28}")
                        print("-" * 90)

                        for idx, (p_off, v_off, dtype) in enumerate(CANDIDATES):
                            # Read candidate value
                            unit_raw = scanner.read_mem(my_unit + p_off, 8)
                            if not unit_raw:
                                print(f"#{idx+1:<2} | 0x{p_off:04X}   | 0x{v_off:04X}  | {dtype:<6} | N/A (Cannot read)")
                                continue
                            
                            move_ptr = struct.unpack("<Q", unit_raw)[0]
                            if not mul.is_valid_ptr(move_ptr):
                                print(f"#{idx+1:<2} | 0x{p_off:04X}   | 0x{v_off:04X}  | {dtype:<6} | N/A (Invalid Move Ptr)")
                                continue

                            vel_bytes = scanner.read_mem(move_ptr + v_off, 24 if dtype == "DOUBLE" else 12)
                            if not vel_bytes:
                                print(f"#{idx+1:<2} | 0x{p_off:04X}   | 0x{v_off:04X}  | {dtype:<6} | N/A (Null Bytes)")
                                continue

                            if dtype == "DOUBLE":
                                vx, vy, vz = struct.unpack("<ddd", vel_bytes)
                            else:
                                vx, vy, vz = struct.unpack("<fff", vel_bytes)

                            raw_vec = (vx, vy, vz)
                            raw_str = f"({vx:>6.1f}, {vy:>6.1f}, {vz:>6.1f})"

                            # 1. Check if candidate is Direct World Vel
                            direct_err = calc_error_deg(raw_vec, world_pos_vel)

                            # 2. Check if candidate is Body Vel (Transformed to World)
                            tf_modes = transform_body_to_world(vx, vy, vz, rot)
                            best_tf_err = 999.0
                            best_tf_mode = ""
                            for mode_name, tf_vec in tf_modes:
                                err = calc_error_deg(tf_vec, world_pos_vel)
                                if err < best_tf_err:
                                    best_tf_err = err
                                    best_tf_mode = mode_name

                            # Classification Status
                            status = "⚪ Unknown"
                            if direct_err <= 15.0:
                                status = f"🟢 WORLD VEL ({direct_err:.1f}° err)"
                            elif best_tf_err <= 15.0:
                                status = f"🔵 BODY VEL ({best_tf_mode}, {best_tf_err:.1f}° err)"
                            elif direct_err <= 30.0:
                                status = f"🟡 CLOSE WORLD ({direct_err:.1f}° err)"
                            elif best_tf_err <= 30.0:
                                status = f"🟡 CLOSE BODY ({best_tf_mode}, {best_tf_err:.1f}° err)"

                            print(f"#{idx+1:<2} | 0x{p_off:04X}   | 0x{v_off:04X}  | {dtype:<6} | {raw_str:<24} | {status}")

                        print("==========================================================================================")

            last_pos = pos
            last_time = curr_t

        time.sleep(0.04)

if __name__ == "__main__":
    main()
