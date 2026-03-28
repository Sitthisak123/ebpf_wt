import os
import sys
import struct
import math
import time
from main import MemoryScanner, get_game_pid, get_game_base_address

try:
    from src.utils.mul import *
    from src.utils.scanner import *
except ImportError:
    print("[-] Error: ไม่สามารถ import src.utils.mul ได้")
    sys.exit(1)

def clear_screen():
    os.system('clear')

def print_header(candidates_count):
    clear_screen()
    print("==================================================")
    print("🚙 WTM TACTICAL: OMNI-UNIT VELOCITY SCANNER")
    print("==================================================")
    print(f"🎯 ผู้ต้องสงสัย (Candidates) ที่เหลืออยู่: {candidates_count} รายการ")
    print("==================================================")

def save_candidates_to_log(candidates):
    if not candidates:
        print("[-] ไม่มีข้อมูลให้บันทึก")
        return
    
    filename = "scan_results.txt"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"=== WTM SCAN RESULTS ({time.strftime('%Y-%m-%d %H:%M:%S')}) ===\n")
            f.write(f"Total Candidates: {len(candidates)}\n")
            f.write("-" * 50 + "\n")
            for u_ptr, p_off, v_off, dt in candidates:
                line = f"Unit: {hex(u_ptr)} | Move Ptr: 0x{p_off:04X} | Vel Offset: 0x{v_off:04X} | Type: {dt}\n"
                f.write(line)
        print(f"\n[✅] บันทึกรายชื่อผู้ต้องสงสัยทั้งหมดลงใน '{filename}' เรียบร้อยแล้ว!")
    except Exception as e:
        print(f"[-] ไม่สามารถบันทึกไฟล์ได้: {e}")

def main():
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    
    cgame_base = get_cgame_base(scanner, base_address)
    if cgame_base == 0:
        print("[-] ไม่พบเกม War Thunder")
        sys.exit(1)

    all_units = get_all_units(scanner, cgame_base)
    target_units = [u[0] for u in all_units]

    tolerance = 2.0
    candidates = []

    while True:
        print_header(len(candidates))
        print(f"[+] 📡 ยูนิตในแมป: {len(target_units)} คัน | Tolerance: +- {tolerance}")
        print("-" * 50)
        print("[1] 🔍 สแกนครั้งแรก (First Scan)")
        print("[2] 🎯 สแกนคัดกรอง (Next Scan)")
        print("[3] 👀 เฝ้าระวังสด (Watch Live)")
        print("[4] ⚙️ ตั้งค่า Tolerance")
        print("[5] 🗑️ ล้างค่า (Reset)")
        print("[6] 💾 บันทึกผลลงไฟล์ (Log All Candidates)")
        print("[0] ❌ ออกจากโปรแกรม")
        print("-" * 50)
        
        choice = input("👉 เลือกคำสั่ง: ").strip()
        
        if choice == '0': break
            
        elif choice == '4':
            val = input("   > ระยะบวกลบ (km/h): ").strip()
            try: tolerance = float(val)
            except: pass

        elif choice == '5':
            candidates = []
            print("[!] Reset เรียบร้อย")
            time.sleep(0.5)

        elif choice == '6':
            save_candidates_to_log(candidates)
            input("\nกด Enter เพื่อกลับไปเมนู...")

        elif choice == '1':
            val = input("   > ความเร็วปัจจุบัน (km/h): ").strip()
            try: target_speed = float(val)
            except: continue
            
            min_s, max_s = target_speed - tolerance, target_speed + tolerance
            print(f"[*] กำลังสแกนหาช่วง {min_s:.1f} - {max_s:.1f}...")
            
            candidates = []
            for u_ptr in target_units:
                unit_data = scanner.read_mem(u_ptr, 0x2500)
                if not unit_data: continue
                for ptr_off in range(0, len(unit_data) - 8, 8):
                    ptr_val = struct.unpack_from("<Q", unit_data, ptr_off)[0]
                    if is_valid_ptr(ptr_val):
                        mem_block = scanner.read_mem(ptr_val, 0x1000)
                        if not mem_block: continue
                        # FLOAT
                        for off in range(0, len(mem_block) - 12, 4):
                            try:
                                vx, vy, vz = struct.unpack_from("<fff", mem_block, off)
                                speed = math.sqrt(vx**2 + vy**2 + vz**2) * 3.6
                                if min_s <= speed <= max_s:
                                    candidates.append((u_ptr, ptr_off, off, "FLOAT"))
                            except: pass
                        # DOUBLE
                        for off in range(0, len(mem_block) - 24, 8):
                            try:
                                vx, vy, vz = struct.unpack_from("<ddd", mem_block, off)
                                speed = math.sqrt(vx**2 + vy**2 + vz**2) * 3.6
                                if min_s <= speed <= max_s:
                                    candidates.append((u_ptr, ptr_off, off, "DOUBLE"))
                            except: pass
            print(f"[+] พบ {len(candidates)} รายการ")
            input("Enter...")

        elif choice == '2':
            if not candidates: continue
            val = input("   > ความเร็วใหม่ (km/h): ").strip()
            try: target_speed = float(val)
            except: continue
                
            min_s, max_s = target_speed - tolerance, target_speed + tolerance
            new_candidates = []
            for u_ptr, ptr_off, vel_off, dtype in candidates:
                unit_data = scanner.read_mem(u_ptr, 0x2500)
                if unit_data:
                    ptr_val = struct.unpack_from("<Q", unit_data, ptr_off)[0]
                    vel_data = scanner.read_mem(ptr_val + vel_off, 24 if dtype == "DOUBLE" else 12)
                    if vel_data:
                        try:
                            if dtype == "FLOAT": vx, vy, vz = struct.unpack("<fff", vel_data)
                            else: vx, vy, vz = struct.unpack("<ddd", vel_data)
                            speed = math.sqrt(vx**2 + vy**2 + vz**2) * 3.6
                            if min_s <= speed <= max_s:
                                new_candidates.append((u_ptr, ptr_off, vel_off, dtype))
                        except: pass
            candidates = new_candidates
            print(f"[+] เหลือ {len(candidates)} รายการ")
            if 0 < len(candidates) <= 20:
                for u, p, v, d in candidates:
                    print(f" -> Ptr: 0x{p:X} | Vel: 0x{v:X} ({d})")
            input("Enter...")

        elif choice == '3':
            if not candidates: continue
            try:
                while True:
                    print(f"\n--- MONITORING ({len(candidates)}) ---")
                    for u_ptr, p_off, v_off, dt in candidates[:10]: # โชว์แค่ 10 อันแรกกันรกจอ
                        unit_data = scanner.read_mem(u_ptr, 0x2500)
                        ptr_val = struct.unpack_from("<Q", unit_data, p_off)[0]
                        vel_data = scanner.read_mem(ptr_val + v_off, 24 if dt == "DOUBLE" else 12)
                        if dt == "FLOAT": vx, vy, vz = struct.unpack("<fff", vel_data)
                        else: vx, vy, vz = struct.unpack("<ddd", vel_data)
                        print(f"Ptr: 0x{p_off:04X} | Vel: 0x{v_off:04X} | Speed: {math.sqrt(vx**2+vy**2+vz**2)*3.6:.1f}")
                    time.sleep(0.5)
            except KeyboardInterrupt: pass

if __name__ == '__main__':
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)
    main()