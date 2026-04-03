import os
import sys
import struct
import math
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul

SCREEN_WIDTH = 2560
SCREEN_HEIGHT = 1440
CENTER_X = SCREEN_WIDTH / 2
CENTER_Y = SCREEN_HEIGHT / 2

def get_best_target(scanner, cgame, view_matrix, my_unit):
    units = mul.get_all_units(scanner, cgame)
    best_ptr = 0
    best_dist = 999999.0
    best_name = "Unknown"
    
    for u_ptr, is_air in units:
        if u_ptr == my_unit: continue
        pos = mul.get_unit_pos(scanner, u_ptr)
        if not pos: continue
        if abs(pos[0]) < 0.001 and abs(pos[1]) < 0.001 and abs(pos[2]) < 0.001: continue
            
        scr = mul.world_to_screen(view_matrix, pos[0], pos[1], pos[2], SCREEN_WIDTH, SCREEN_HEIGHT)
        if scr and scr[2] > 0:
            dist = math.hypot(scr[0] - CENTER_X, scr[1] - CENTER_Y)
            if dist < best_dist:
                best_dist = dist
                best_ptr = u_ptr
                dna = mul.get_unit_detailed_dna(scanner, u_ptr) or {}
                best_name = dna.get("short_name") or dna.get("name_key") or "Unknown_Tank"
                
    return best_ptr, best_dist, best_name

def main():
    pid = get_game_pid()
    if not pid: return
        
    base = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base)
    
    cgame = mul.get_cgame_base(scanner, base)
    view_matrix = mul.get_view_matrix(scanner, cgame)
    my_unit, _ = mul.get_local_team(scanner, base)
    
    print("\n==================================================")
    print(" 🛠️ 3D BOX RENDER DEBUGGER (X-RAY MODE)")
    print("==================================================")
    
    print(f"[*] ออฟเซ็ตปัจจุบันในระบบ:")
    print(f"    - OFF_UNIT_X        = {hex(mul.OFF_UNIT_X)}")
    print(f"    - OFF_UNIT_ROTATION = {hex(mul.OFF_UNIT_ROTATION)}")
    print(f"    - OFF_UNIT_BBMIN    = {hex(mul.OFF_UNIT_BBMIN)}")
    print(f"    - OFF_UNIT_BBMAX    = {hex(mul.OFF_UNIT_BBMAX)}")
    print("-" * 50)

    target_ptr, dist, target_name = get_best_target(scanner, cgame, view_matrix, my_unit)
    if target_ptr == 0:
        print("[-] ❌ ไม่พบเป้าหมายกลางจอ")
        return
        
    print(f"[+] 🎯 ล็อคเป้าหมาย: {target_name.upper()} (Ptr: {hex(target_ptr)})")
    
    # 1. ดึงพิกัด (Position)
    pos = mul.get_unit_pos(scanner, target_ptr)
    print(f"\n[1] 📍 พิกัดรถถัง (World Pos):")
    print(f"    X: {pos[0]:.2f}, Y: {pos[1]:.2f}, Z: {pos[2]:.2f}")
    
    # 2. ดึง Bounding Box
    bbmin_raw = scanner.read_mem(target_ptr + mul.OFF_UNIT_BBMIN, 12)
    bbmax_raw = scanner.read_mem(target_ptr + mul.OFF_UNIT_BBMAX, 12)
    
    if not bbmin_raw or not bbmax_raw:
        print("\n[2] ❌ อ่าน Bounding Box ไม่สำเร็จ!")
        return
        
    bmin = struct.unpack("<fff", bbmin_raw)
    bmax = struct.unpack("<fff", bbmax_raw)
    print(f"\n[2] 📦 Bounding Box (Local):")
    print(f"    Min : ({bmin[0]:.2f}, {bmin[1]:.2f}, {bmin[2]:.2f})")
    print(f"    Max : ({bmax[0]:.2f}, {bmax[1]:.2f}, {bmax[2]:.2f})")
    print(f"    Size: ยาว {bmax[0]-bmin[0]:.1f}m, สูง {bmax[1]-bmin[1]:.1f}m, กว้าง {bmax[2]-bmin[2]:.1f}m")
    
    # 3. ดึง Rotation Matrix
    rot_raw = scanner.read_mem(target_ptr + mul.OFF_UNIT_ROTATION, 36)
    if not rot_raw:
        print("\n[3] ❌ อ่าน Rotation Matrix ไม่สำเร็จ!")
        return
        
    rot = struct.unpack("<9f", rot_raw)
    print(f"\n[3] 🔄 Rotation Matrix (3x3):")
    print(f"    [{rot[0]:>5.2f}, {rot[1]:>5.2f}, {rot[2]:>5.2f}]")
    print(f"    [{rot[3]:>5.2f}, {rot[4]:>5.2f}, {rot[5]:>5.2f}]")
    print(f"    [{rot[6]:>5.2f}, {rot[7]:>5.2f}, {rot[8]:>5.2f}]")
    
    # 4. คำนวณมุมกล่อง
    corners = [
        (bmin[0], bmin[1], bmin[2]), (bmin[0], bmin[1], bmax[2]),
        (bmin[0], bmax[1], bmin[2]), (bmin[0], bmax[1], bmax[2]),
        (bmax[0], bmin[1], bmin[2]), (bmax[0], bmin[1], bmax[2]),
        (bmax[0], bmax[1], bmin[2]), (bmax[0], bmax[1], bmax[2])
    ]
    
    print("\n[4] 🖥️ การวาด 3D Box ลงหน้าจอ (W2S Projection):")
    valid_corners = 0
    for i, c in enumerate(corners):
        # Apply Rotation Matrix
        world_x = pos[0] + (c[0]*rot[0] + c[1]*rot[3] + c[2]*rot[6])
        world_y = pos[1] + (c[0]*rot[1] + c[1]*rot[4] + c[2]*rot[7])
        world_z = pos[2] + (c[0]*rot[2] + c[1]*rot[5] + c[2]*rot[8])
        
        scr = mul.world_to_screen(view_matrix, world_x, world_y, world_z, SCREEN_WIDTH, SCREEN_HEIGHT)
        if scr and scr[2] > 0:
            print(f"    มุมที่ {i+1} : {scr[0]:>6.1f}px, {scr[1]:>6.1f}px (W={scr[2]:.1f}) ✅")
            valid_corners += 1
        else:
            print(f"    มุมที่ {i+1} : ข้อมูลผิดพลาด หรืออยู่หลังกล้อง ❌")
            
    print("-" * 50)
    if valid_corners == 8:
        print("[*] 🌟 ระบบฟิสิกส์สมบูรณ์แบบ 100%! กล่องควรจะวาดขึ้นปกติครับ!")
    else:
        print(f"[*] ⚠️ ตรวจพบข้อผิดพลาด! วาดได้เพียง {valid_corners}/8 มุม")

if __name__ == '__main__':
    main()