import struct
import math
import time
import sys
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.utils.mul import *
from src.utils.scanner import init_dynamic_offsets

def main():
    print("="*70)
    print("🎯 VISUAL BONE FINDER - THE ULTIMATE TRUTH")
    print("="*70)
    
    try:
        pid = get_game_pid()
        scanner = MemoryScanner(pid)
        base_addr = get_game_base_address(pid)
        init_dynamic_offsets(scanner, base_addr)
        
        cgame_base = get_cgame_base(scanner, base_addr)
        view_matrix = get_view_matrix(scanner, cgame_base)
        
        # 1. หายูนิตเป้าหมาย (Locked Target หรือ ตัวเรา)
        my_unit, _ = get_local_team(scanner, base_addr)
        target = my_unit
        if not target:
            all_units = get_all_units(scanner, cgame_base)
            if all_units: target = all_units[0][0]
            
        if not target:
            print("[-] ไม่พบยูนิต")
            return

        print(f"[*] กำลังสแกนยูนิต: {hex(target)}")
        
        # 2. อ่านหน่วยความจำยูนิตช่วงกว้าง (0x0 - 0x3000)
        mem = scanner.read_mem(target, 0x3000)
        if not mem: return

        print("[*] กำลังค้นหา Vector3 ที่เมื่อแปลงแล้วปรากฏบนหน้าจอ...")
        found_count = 0
        
        # สแกนหา Float Triplets ทุกๆ 4 ไบต์
        for i in range(0, len(mem) - 12, 4):
            x, y, z = struct.unpack_from("<fff", mem, i)
            
            # กรองเฉพาะค่าที่ดูเป็นพิกัดโลก (ไม่ใช่ 0 หรือค่าเล็กๆ)
            if abs(x) > 10.0 and abs(z) > 10.0 and -500.0 < y < 10000.0:
                # ลองทำ World-to-Screen
                scr = world_to_screen(view_matrix, x, y, z, 1920, 1080)
                if scr and scr[2] > 0:
                    # ถ้าจุดนี้ปรากฏบนหน้าจอในช่วง 1920x1080
                    if 0 < scr[0] < 1920 and 0 < scr[1] < 1080:
                        # เช็คความซ้ำซ้อน
                        print(f"  [✨ FOUND] Offset {hex(i)} | World: ({x:.1f}, {y:.1f}, {z:.1f}) | Screen: ({int(scr[0])}, {int(scr[1])})")
                        found_count += 1
                        if found_count > 20: break

        # 3. สแกนผ่าน Pointer (Matrix Arrays)
        print("\n[*] กำลังสแกนผ่าน Pointer ภายในยูนิต (Deep Scan)...")
        for i in range(0, len(mem) - 8, 8):
            ptr = struct.unpack_from("<Q", mem, i)[0]
            if is_valid_ptr(ptr):
                # ลองอ่านข้อมูลที่ Pointer นี้ชี้ไป
                sub_mem = scanner.read_mem(ptr, 0x500)
                if sub_mem:
                    for j in range(0, len(sub_mem) - 12, 4):
                        x, y, z = struct.unpack_from("<fff", sub_mem, j)
                        if abs(x) > 10.0 and abs(z) > 10.0 and -500.0 < y < 10000.0:
                            scr = world_to_screen(view_matrix, x, y, z, 1920, 1080)
                            if scr and scr[2] > 0 and 0 < scr[0] < 1920 and 0 < scr[1] < 1080:
                                print(f"  [🔥 POINTER FOUND] Unit+{hex(i)} -> Pointer+{hex(j)} | Screen: ({int(scr[0])}, {int(scr[1])})")
                                break

    except Exception as e:
        print(f"[-] Error: {e}")

if __name__ == "__main__":
    main()
