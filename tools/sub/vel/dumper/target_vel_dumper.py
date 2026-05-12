import os
import sys
import struct
import time
import math

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import get_cgame_base, get_all_units, get_local_team, get_unit_pos, get_view_matrix, world_to_screen

# 🖥️ การตั้งค่าหน้าจอ (แก้ให้ตรงกับจอของท่าน)
SCREEN_WIDTH = 2560
SCREEN_HEIGHT = 1440
CENTER_X = SCREEN_WIDTH / 2.0
CENTER_Y = SCREEN_HEIGHT / 2.0

def read_vel_float(scanner, unit_ptr, move_off, vel_off):
    try:
        move_raw = scanner.read_mem(unit_ptr + move_off, 8)
        if not move_raw: return None
        move_ptr = struct.unpack("<Q", move_raw)[0]
        if not move_ptr or move_ptr < 0x10000: return None
        
        vel_raw = scanner.read_mem(move_ptr + vel_off, 12)
        if not vel_raw: return None
        return struct.unpack("<fff", vel_raw)
    except: return None

def read_vel_double(scanner, unit_ptr, move_off, vel_off):
    try:
        move_raw = scanner.read_mem(unit_ptr + move_off, 8)
        if not move_raw: return None
        move_ptr = struct.unpack("<Q", move_raw)[0]
        if not move_ptr or move_ptr < 0x10000: return None
        
        vel_raw = scanner.read_mem(move_ptr + vel_off, 24)
        if not vel_raw: return None
        return struct.unpack("<ddd", vel_raw)
    except: return None

def main():
    print("[*] Velocity Dumper (Crosshair Targeting Mode)")
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_address)
    
    # 🎯 รวมมิตร Candidate จาก WTM Scan ล่าสุด (2026-05-12) + ของเดิม
    candidates = [
        # --- กลุ่ม FLOAT 0x0018 (ตัวเดิมและตัวใหม่) ---
        {"name": "FLT_018_318", "move": 0x0018, "vel": 0x0318, "type": "FLOAT"},
        {"name": "FLT_018_358", "move": 0x0018, "vel": 0x0358, "type": "FLOAT"},
        {"name": "FLT_018_398", "move": 0x0018, "vel": 0x0398, "type": "FLOAT"},
        {"name": "FLT_018_3D8", "move": 0x0018, "vel": 0x03D8, "type": "FLOAT"},
        
        # --- กลุ่ม FLOAT ใหม่ล่าสุด (0x22xx, 0x23xx) ---
        {"name": "FLT_22B8_E50", "move": 0x22B8, "vel": 0x0E50, "type": "FLOAT"},
        {"name": "FLT_22C0_D78", "move": 0x22C0, "vel": 0x0D78, "type": "FLOAT"},
        {"name": "FLT_22C8_D78", "move": 0x22C8, "vel": 0x0D78, "type": "FLOAT"},
        {"name": "FLT_23A8_E50", "move": 0x23A8, "vel": 0x0E50, "type": "FLOAT"},
        {"name": "FLT_23B0_E50", "move": 0x23B0, "vel": 0x0E50, "type": "FLOAT"},

        # --- กลุ่ม DOUBLE (0x0D10, 0x0D18) ---
        {"name": "DBL_0D10_068", "move": 0x0D10, "vel": 0x0068, "type": "DOUBLE"},
        {"name": "DBL_0D10_0C8", "move": 0x0D10, "vel": 0x00C8, "type": "DOUBLE"},
        {"name": "DBL_0D10_0D0", "move": 0x0D10, "vel": 0x00D0, "type": "DOUBLE"},
        {"name": "DBL_0D18_068", "move": 0x0D18, "vel": 0x0068, "type": "DOUBLE"},
        {"name": "DBL_0D18_0C8", "move": 0x0D18, "vel": 0x00C8, "type": "DOUBLE"},
        {"name": "DBL_0D18_0D0", "move": 0x0D18, "vel": 0x00D0, "type": "DOUBLE"},

        # --- กลุ่ม DOUBLE เก่าที่เผื่อไว้ ---
        {"name": "DBL_01E0_F48", "move": 0x01E0, "vel": 0x0F48, "type": "DOUBLE"},
        {"name": "DBL_1FD0_1C8", "move": 0x1FD0, "vel": 0x01C8, "type": "DOUBLE"},
        {"name": "DBL_1458_058", "move": 0x1458, "vel": 0x0058, "type": "DOUBLE"},
    ]

    while True:
        os.system('clear')
        print("=== 🎯 CROSSHAIR VELOCITY DUMPER ===")
        print(f"🖥️ จอ: {SCREEN_WIDTH}x{SCREEN_HEIGHT} | กึ่งกลาง: ({CENTER_X}, {CENTER_Y})")
        
        cgame_base = get_cgame_base(scanner, base_address)
        
        if cgame_base:
            my_unit_ptr, _ = get_local_team(scanner, cgame_base)
            all_units = get_all_units(scanner, cgame_base)
            
            view_matrix = get_view_matrix(scanner, cgame_base)
            
            if not all_units or not view_matrix:
                print("⏳ รอข้อมูลเกม...")
                time.sleep(0.5)
                continue

            # 🚀 ระบบเล็งเป้ากากบาท (FOV Targeting)
            enemies_on_screen = []
            
            for u_ptr, is_air in all_units:
                if u_ptr == my_unit_ptr: 
                    continue
                    
                u_pos = get_unit_pos(scanner, u_ptr)
                if not u_pos:
                    continue
                    
                scr_pos = world_to_screen(view_matrix, u_pos[0], u_pos[1], u_pos[2], SCREEN_WIDTH, SCREEN_HEIGHT)
                
                if scr_pos and scr_pos[2] > 0:
                    ex, ey = scr_pos[0], scr_pos[1]
                    dist_to_crosshair = math.hypot(ex - CENTER_X, ey - CENTER_Y)
                    enemies_on_screen.append((dist_to_crosshair, u_ptr, is_air))
            
            if not enemies_on_screen:
                print("\n👀 ไม่พบศัตรูในระยะสายตา (หน้าจอว่างเปล่า)")
            else:
                enemies_on_screen.sort(key=lambda x: x[0])
                best_dist, target_ptr, is_air = enemies_on_screen[0]
                
                print(f"\n--- 🔴 [CROSSHAIR LOCK] PTR: {hex(target_ptr)} | Air: {is_air} ---")
                print(f"📏 ห่างจากจุดเล็ง: {best_dist:.1f} pixels")
                
                for cand in candidates:
                    if cand["type"] == "FLOAT":
                        vel = read_vel_float(scanner, target_ptr, cand["move"], cand["vel"])
                    else:
                        vel = read_vel_double(scanner, target_ptr, cand["move"], cand["vel"])
                    
                    if vel:
                        if any(abs(v) > 0.01 and abs(v) < 2000.0 for v in vel):
                            status = "✅ VALID"
                        else:
                            status = "❓ EMPTY"
                        print(f" [{cand['name']:<12}] {status} -> X:{vel[0]:>8.1f} Y:{vel[1]:>8.1f} Z:{vel[2]:>8.1f}")
                    else:
                        print(f" [{cand['name']:<12}] ❌ FAIL")
                        
        print("\n[Ctrl+C] to Exit")
        time.sleep(0.1) 

if __name__ == '__main__':
    main()