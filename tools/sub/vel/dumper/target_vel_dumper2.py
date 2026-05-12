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
        # 🚀 อัปเกรด: ถ้า move_off เป็น 0 ให้อ่านตรงจาก Unit Pointer เลย!
        if move_off == 0:
            vel_raw = scanner.read_mem(unit_ptr + vel_off, 12)
        else:
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
        if move_off == 0:
            vel_raw = scanner.read_mem(unit_ptr + vel_off, 24)
        else:
            move_raw = scanner.read_mem(unit_ptr + move_off, 8)
            if not move_raw: return None
            move_ptr = struct.unpack("<Q", move_raw)[0]
            if not move_ptr or move_ptr < 0x10000: return None
            vel_raw = scanner.read_mem(move_ptr + vel_off, 24)
            
        if not vel_raw: return None
        return struct.unpack("<ddd", vel_raw)
    except: return None

def main():
    print("[*] Velocity Dumper (Crosshair Targeting Mode - 60Hz Edition)")
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_address)
    
    # 🎯 รวมมิตร Candidate จากผลการล่า 60Hz ล่าสุด!
    candidates = [
        {"name": "⭐BASE⭐", "move": 0x0018, "vel": 0x318, "type": "FLOAT"},

        # --- ⭐ THE HOLY GRAIL: HIGH-TICK OFFSETS (SMOOTH 60Hz) ⭐ ---
        {"name": "FLT_UNIT_3A58", "move": 0x0000, "vel": 0x3A58, "type": "FLOAT"},
        {"name": "FLT_UNIT_3F48", "move": 0x0000, "vel": 0x3F48, "type": "FLOAT"},
        {"name": "FLT_MOVE_137C", "move": 0x0018, "vel": 0x137C, "type": "FLOAT"},

        # --- กลุ่ม Network 5Hz (เอาไว้เทียบความตรง) ---
        {"name": "FLT_018_318", "move": 0x0018, "vel": 0x0318, "type": "FLOAT"},
        {"name": "FLT_018_358", "move": 0x0018, "vel": 0x0358, "type": "FLOAT"},
        {"name": "FLT_018_398", "move": 0x0018, "vel": 0x0398, "type": "FLOAT"},
        {"name": "FLT_018_3D8", "move": 0x0018, "vel": 0x03D8, "type": "FLOAT"},
        
        # --- กลุ่ม DOUBLE (ตัวหลอก) เอาไว้เผื่อเช็ค ---
        {"name": "DBL_0D10_068", "move": 0x0D10, "vel": 0x0068, "type": "DOUBLE"},
        {"name": "DBL_0D18_068", "move": 0x0D18, "vel": 0x0068, "type": "DOUBLE"},
    ]

    while True:
        os.system('clear')
        print("=== 🎯 CROSSHAIR VELOCITY DUMPER (60Hz VERIFIED) ===")
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
                        # ไฮไลต์ให้เห็นชัดๆ ว่าตัวไหนคือ 60Hz
                        marker = "⚡" if "3A58" in cand["name"] or "3F48" in cand["name"] or "137C" in cand["name"] else " "
                        print(f"{marker}[{cand['name']:<13}] {status} -> X:{vel[0]:>8.1f} Y:{vel[1]:>8.1f} Z:{vel[2]:>8.1f}")
                    else:
                        print(f" [{cand['name']:<13}] ❌ FAIL")
                        
        print("\n[Ctrl+C] to Exit")
        time.sleep(0.1) 

if __name__ == '__main__':
    main()