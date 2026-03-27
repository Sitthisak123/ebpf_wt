import os
import sys
import struct
import math
import time
from main import MemoryScanner, get_game_pid, get_game_base_address

try:
    from src.utils.mul import get_cgame_base, get_all_units, is_valid_ptr
except ImportError:
    print("[-] Error: ไม่สามารถ import src.utils.mul ได้")
    sys.exit(1)

def clear_screen(): os.system('clear')

def print_header(candidates_count):
    clear_screen()
    print("==================================================")
    print("🚙 WTM TACTICAL: OMNI-SCANNER & BALLISTIC HUNTER")
    print("==================================================")
    print(f"🎯 ผู้ต้องสงสัยที่เหลืออยู่: {candidates_count} รายการ")
    print("==================================================")

def main():
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    cgame_base = get_cgame_base(scanner, base_address)
    
    if cgame_base == 0:
        print("[-] ไม่พบ CGame Base"); sys.exit(1)

    all_units = get_all_units(scanner, cgame_base)
    candidates = []
    tolerance = 2.0

    while True:
        print_header(len(candidates))
        print(f"[+] 📡 เชื่อมต่อยูนิตในแมป: {len(all_units)} คัน | CGame: {hex(cgame_base)}")
        print("-" * 50)
        print("[1] 🔍 สแกนความเร็ว (First Scan)")
        print("[2] 🎯 คัดกรองความเร็ว (Next Scan)")
        print("[6] 🔫 เจาะข้อมูลขีปนาวุธ (Ballistic Data Hunter) 🌟")
        print("[0] ❌ ออกจากโปรแกรม")
        print("-" * 50)
        
        choice = input("👉 เลือกคำสั่ง: ").strip()
        
        if choice == '0': break

        # ==========================================
        # 🔫 NEW FEATURE: BALLISTIC DATA HUNTER (DEEP SCAN)
        # ==========================================
        elif choice == '6':
            print("\n[*] --- ปฏิบัติการเจาะลึกข้อมูลขีปนาวุธ (Deep Scan) ---")
            val = input("   > ใส่ความเร็วกระสุน (Muzzle Velocity) จากในเกม (m/s): ").strip()
            try: target_v = float(val)
            except: continue

            print(f"[*] กำลังปูพรมสแกน Weapon Pointer ใน CGame...")
            # ขยายวงสแกน Pointer ใน CGame ให้กว้างขึ้นเป็น 0x4000
            for weapon_off in range(0x0, 0x4000, 8):
                raw_ptr = scanner.read_mem(cgame_base + weapon_off, 8)
                if not raw_ptr: continue
                w_ptr = struct.unpack("<Q", raw_ptr)[0]
                
                if is_valid_ptr(w_ptr):
                    # อ่านข้อมูล Weapon Object ยาวขึ้นเป็น 0x3500 bytes
                    w_data = scanner.read_mem(w_ptr, 0x3500)
                    if not w_data: continue
                    
                    for v_off in range(0, len(w_data)-4, 4):
                        curr_v = struct.unpack_from("<f", w_data, v_off)[0]
                        # ยืดหยุ่นค่าความเร็วเล็กน้อย (+- 0.5)
                        if abs(curr_v - target_v) < 0.5:
                            print(f"\n" + "="*40)
                            print(f"✨ [เจอเป้าหมาย!] Ballistic Structure Found!")
                            print(f"👉 OFF_WEAPON_PTR   : {hex(weapon_off)}")
                            print(f"👉 OFF_BULLET_SPEED : {hex(v_off)}")
                            print(f"📍 Muzzle Velocity  : {curr_v:.2f} m/s")
                            print("="*40)
                            
                            print(f"{'Relative Off':<15} | {'Absolute Off':<15} | {'Float Value':<15}")
                            print("-" * 50)
                            
                            # 🎯 ขยายการ Dump ข้อมูลรอบข้างเป็น -128 ถึง +128 bytes
                            for adj in range(-128, 128, 4):
                                check_addr = v_off + adj
                                if 0 <= check_addr < len(w_data) - 4:
                                    adj_v = struct.unpack_from("<f", w_data, check_addr)[0]
                                    
                                    # กรองเฉพาะค่าที่มีนัยสำคัญ (ไม่ใช่ 0 หรือค่ามหาศาล)
                                    if 0.001 < abs(adj_v) < 5000.0:
                                        rel_hex = f"{adj:+x}"
                                        abs_hex = hex(check_addr)
                                        marker = "⭐ SPEED" if adj == 0 else ""
                                        
                                        # พิมพ์ค่าออกมาเพื่อวิเคราะห์
                                        print(f"{rel_hex:<15} | {abs_hex:<15} | {adj_v:<15.6f} {marker}")
                                        
            input("\nกด Enter เพื่อกลับเมนู...")
            input("\nกด Enter เพื่อกลับเมนู...")

        # (โค้ด Scan 1 และ 2 เหมือนเดิม...)
        elif choice == '1':
            # ... โค้ดส่วนสแกนความเร็วรถเดิม ...
            pass 

if __name__ == '__main__':
    main()