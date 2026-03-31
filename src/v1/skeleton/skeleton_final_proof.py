import struct
import math
import time
import sys
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.utils.mul import *
from src.utils.scanner import init_dynamic_offsets

def main():
    print("="*70)
    print("🎯 TANK SHAPE FINAL PROVER - DIRECT WORLD OFFSETS")
    print("="*70)
    
    try:
        pid = get_game_pid()
        scanner = MemoryScanner(pid)
        base_addr = get_game_base_address(pid)
        init_dynamic_offsets(scanner, base_addr)
        
        cgame_base = get_cgame_base(scanner, base_addr)
        view_matrix = get_view_matrix(scanner, cgame_base)
        my_unit, _ = get_local_team(scanner, base_addr)
        
        target_unit = my_unit if my_unit != 0 else 0
        if not target_unit:
            all_units = get_all_units(scanner, cgame_base)
            if all_units: target_unit = all_units[0][0]
            
        if not target_unit:
            print("[-] ไม่พบยูนิต")
            return

        print(f"[*] ตรวจสอบยูนิต: {hex(target_unit)}")
        
        # 1. อ่านพิกัดจาก Offset ที่เราสแกนเจอ (Direct World Position)
        # Body (0xd00), Turret (0x1e6c), Gun (0x2638)
        
        def read_vec3(off):
            raw = scanner.read_mem(target_unit + off, 12)
            if raw: return struct.unpack("<fff", raw)
            return None

        body = read_vec3(0xd00)
        turret = read_vec3(0x1e6c)
        gun = read_vec3(0x2638)

        print("\n[📊 DATA REPORT]")
        print("-" * 75)
        print(f"{'Part':<10} | {'Offset':<8} | {'World Position (X, Y, Z)':<30} | {'Screen'}")
        print("-" * 75)

        for name, off, pos in [("BODY", 0xd00, body), ("TURRET", 0x1e6c, turret), ("GUN", 0x2638, gun)]:
            if pos:
                scr = world_to_screen(view_matrix, *pos, 1920, 1080)
                scr_str = f"({int(scr[0]):>4}, {int(scr[1]):>4})" if scr and scr[2] > 0 else "OFF-SCREEN"
                print(f"{name:<10} | {hex(off):<8} | {pos[0]:7.1f}, {pos[1]:5.1f}, {pos[2]:7.1f} | {scr_str}")
            else:
                print(f"{name:<10} | {hex(off):<8} | {'FAILED TO READ':<30} | -")

        print("-" * 75)
        
        if body and turret and gun:
            print("[✅] ข้อมูลครบถ้วน! หากพิกัด Screen อยู่ในช่วง (0-1920, 0-1080) แสดงว่าวาดติดแน่นอน")
            print("[💡] คำแนะนำถัดไป: ผมจะใช้พิกัดเหล่านี้สร้างเส้นเชื่อม Body -> Turret -> Gun")

    except Exception as e:
        print(f"[-] Error: {e}")

if __name__ == "__main__":
    main()
