import os
import sys
import struct
import math
import time

# 📍 ชี้พิกัดกลับไปหา Root Folder
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul

# ตั้งค่าหน้าจอตาม main.py ของท่าน
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
        
        # กรองยูนิตผีที่อยู่ 0,0,0
        if abs(pos[0]) < 0.001 and abs(pos[1]) < 0.001 and abs(pos[2]) < 0.001:
            continue
            
        scr = mul.world_to_screen(view_matrix, pos[0], pos[1], pos[2], SCREEN_WIDTH, SCREEN_HEIGHT)
        if scr and scr[2] > 0:
            dist = math.hypot(scr[0] - CENTER_X, scr[1] - CENTER_Y)
            if dist < best_dist:
                best_dist = dist
                best_ptr = u_ptr
                
                # พยายามดึงชื่อ
                dna = mul.get_unit_detailed_dna(scanner, u_ptr) or {}
                best_name = dna.get("short_name") or dna.get("name_key") or "Unknown_Tank"
                
    return best_ptr, best_dist, best_name

def scan_bbox(scanner, target_ptr):
    # ขยายพื้นที่สแกนให้ลึกขึ้นเผื่อซ่อนอยู่ไกล
    START_OFF = 0x100
    SCAN_SIZE = 0x400 
    
    data = scanner.read_mem(target_ptr + START_OFF, SCAN_SIZE)
    if not data:
        return []
        
    candidates = []
    
    # สแกนทีละ 4 bytes
    for off in range(0, SCAN_SIZE - 32, 4):
        try:
            bmin = struct.unpack_from("<fff", data, off)
            
            # BMax มักจะอยู่ห่างจาก BMin ไป 0x0C, 0x10, 0x14, 0x18, 0x20
            for gap in [0x0C, 0x10, 0x14, 0x18, 0x20]:
                bmax = struct.unpack_from("<fff", data, off + gap)
                
                # 🎯 กฎเหล็กข้อเดียวของ BBox: ค่า Max ต้องมากกว่า Min เสมอในทุกแกน!
                if bmin[0] < bmax[0] and bmin[1] < bmax[1] and bmin[2] < bmax[2]:
                    dx = bmax[0] - bmin[0] # ยาว
                    dy = bmax[1] - bmin[1] # สูง
                    dz = bmax[2] - bmin[2] # กว้าง
                    
                    # กรองขนาดให้หลวมขึ้น (รถบรรทุกอาจจะทรงสูงหรือแคบ)
                    if (1.5 < dx < 15.0) and (0.5 < dy < 8.0) and (1.0 < dz < 8.0):
                        # ไม่สนใจแล้วว่า BMin ต้องติดลบ ขอแค่ขนาดกล่องสมเหตุสมผล
                        real_off = START_OFF + off
                        
                        # กรองตัวเลขแปลกๆ ที่ใหญ่เกินไปทิ้ง
                        if all(abs(v) < 100.0 for v in bmin + bmax):
                            candidates.append({
                                "bbmin_off": real_off,
                                "bbmax_off": real_off + gap,
                                "gap": gap,
                                "dim": (dx, dy, dz),
                                "bmin": bmin,
                                "bmax": bmax
                            })
        except:
            pass
            
    return candidates

def main():
    pid = get_game_pid()
    if not pid:
        print("[-] ไม่พบเกม War Thunder")
        return
        
    base = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base)
    
    print("\n==================================================")
    print(" 📦 THE TARGET BBOX DUMPER (LIVE SCANNER)")
    print("==================================================")
    
    cgame = mul.get_cgame_base(scanner, base)
    view_matrix = mul.get_view_matrix(scanner, cgame)
    
    if not view_matrix:
        print("[-] ❌ ดึง View Matrix ไม่สำเร็จ! (กรุณาให้ชัวร์ว่า Matrix แม่นยำแล้ว)")
        return
        
    # หากลุ่มรถถังฝ่ายเรา (เพื่อไม่ให้มันสแกนรถตัวเอง)
    my_unit, _ = mul.get_local_team(scanner, base)
    
    target_ptr, dist, target_name = get_best_target(scanner, cgame, view_matrix, my_unit)
    
    if target_ptr == 0:
        print("[-] ❌ ไม่พบเป้าหมายแถวกลางหน้าจอเลยครับ! (หันเป้าไปที่ศัตรูก่อนรัน)")
        return
        
    print(f"[+] 🎯 ล็อคเป้าหมาย: {target_name.upper()} (ห่างกลางจอ {dist:.1f} px)")
    print(f"[+] 🧷 Ptr: {hex(target_ptr)}")
    print("-" * 50)
    
    candidates = scan_bbox(scanner, target_ptr)
    
    if not candidates:
        print("[-] ❌ ไม่พบ BBox ที่ขนาดสมเหตุสมผลในระยะ 0x100 - 0x300 เลยครับ")
        return
        
    print("[*] 🔍 ผลการสแกนหา 3D Bounding Box ที่เข้าข่าย:\n")
    
    for i, c in enumerate(candidates):
        dx, dy, dz = c['dim']
        gap = c['gap']
        
        # ไฮไลต์ให้ถ้าระยะห่างเป็น 0x10 (มาตรฐานสุด)
        color = "\033[92m" if gap == 0x10 else "\033[0m"
        
        print(f"{color}[Candidate {i+1}]")
        print(f"  👉 BBMIN Offset : 0x{c['bbmin_off']:X}")
        print(f"  👉 BBMAX Offset : 0x{c['bbmax_off']:X} (ห่าง 0x{gap:X} bytes)")
        print(f"  📐 ขนาดรถถัง     : ยาว {dx:.1f}m | สูง {dy:.1f}m | กว้าง {dz:.1f}m")
        print(f"  🔻 Min (X,Y,Z) : ({c['bmin'][0]:.1f}, {c['bmin'][1]:.1f}, {c['bmin'][2]:.1f})")
        print(f"  🔺 Max (X,Y,Z) : ({c['bmax'][0]:.1f}, {c['bmax'][1]:.1f}, {c['bmax'][2]:.1f})\033[0m")
        print()
        
    print("💡 คำแนะนำ: เลือก Offset ที่ขนาดกว้าง/ยาว/สูง ตรงกับความจริงที่สุด (เช่น รถถังทั่วไปยาว ~6-8m)")

if __name__ == '__main__':
    main()