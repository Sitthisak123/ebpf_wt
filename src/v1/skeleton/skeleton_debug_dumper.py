import struct
import math
import time
import sys
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.utils.mul import *
from src.utils.scanner import init_dynamic_offsets

def _read_ptr_fast(scanner, addr):
    try:
        raw = scanner.read_mem(addr, 8)
        if not raw or len(raw) < 8: return 0
        return struct.unpack("<Q", raw)[0]
    except: return 0

def main():
    print("="*70)
    print("🕵️‍♂️ SKELETON DEEP PROBER (V.3) - FINDING THE TRUTH")
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
            print("[-] ไม่พบยูนิตเป้าหมาย")
            return

        print(f"[*] ตรวจสอบยูนิต: {hex(target_unit)}")
        
        # 1. พิกัดอ้างอิง (World Ref)
        u_pos_raw = scanner.read_mem(target_unit + 0xd00, 12)
        ux, uy, uz = struct.unpack("<fff", u_pos_raw)
        print(f"[*] พิกัดโลกอ้างอิง (0xd00): X={ux:.2f}, Y={uy:.2f}, Z={uz:.2f}")

        # 2. เข้าถึง AnimChar
        anim_ptr = _read_ptr_fast(scanner, target_unit + 0x1648)
        print(f"[*] AnimChar Component (0x1648): {hex(anim_ptr)}")
        
        if not is_valid_ptr(anim_ptr):
            print("[-] Pointer 0x1648 ไม่ถูกต้อง!")
            return

        # 3. เจาะลึกหา Matrix Array ภายใน AnimChar
        print("\n[*] กำลัง Probing หา World Matrix Pointer ภายใน AnimChar...")
        print("-" * 85)
        print(f"{'Offset':<8} | {'Pointer Value':<16} | {'Bone 0 World (X, Y, Z)':<30} | {'Dist to Ref'}")
        print("-" * 85)

        # Probing ช่วง 0x0 ถึง 0x80 ของ AnimChar Component
        for test_off in range(0, 0x200, 8):
            prob_ptr = _read_ptr_fast(scanner, anim_ptr + test_off)
            if is_valid_ptr(prob_ptr):
                # ลองอ่านกระดูกเบอร์ 0 (พิกัดอยู่ที่ +0x30)
                mat_raw = scanner.read_mem(prob_ptr + 0x30, 12)
                if mat_raw:
                    mx, my, mz = struct.unpack("<fff", mat_raw)
                    dist = math.sqrt((mx-ux)**2 + (my-uy)**2 + (mz-uz)**2)
                    
                    # ถ้าพิกัดกระดูกอยู่ใกล้รถถังจริงๆ (ไม่เกิน 10 เมตร)
                    status = "🎯 MATCH!" if dist < 10.0 else ""
                    print(f"Anim+{test_off:02x} | {hex(prob_ptr):<16} | {mx:8.1f}, {my:6.1f}, {mz:8.1f} | {dist:6.2f}m {status}")
                    
                    if dist < 10.0:
                        # ลองวาดพิกัดที่ Screen
                        scr = world_to_screen(view_matrix, mx, my, mz, 1920, 1080)
                        if scr and scr[2] > 0:
                            print(f"         >>> 📺 ปรากฏบนหน้าจอที่: ({int(scr[0])}, {int(scr[1])})")

        print("-" * 85)
        print("[💡] หากเจอคำว่า 🎯 MATCH! แสดงว่าเราเจอ Offset ของ World Matrices ที่ถูกต้องแล้ว")

    except Exception as e:
        print(f"[-] Error: {e}")

if __name__ == "__main__":
    main()
