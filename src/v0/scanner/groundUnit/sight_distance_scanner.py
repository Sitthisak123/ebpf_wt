import os
import sys
import struct
import math
import time
from main import MemoryScanner, get_game_pid, get_game_base_address

try:
    from src.utils.mul import get_cgame_base, get_local_team, is_valid_ptr
except ImportError:
    print("[-] Error: หาไฟล์ src/utils/mul.py ไม่เจอ")
    sys.exit(1)

def clear_screen(): os.system('clear')

OFF_WEAPON_PTR = 0x0408 

def main():
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    cgame_base = get_cgame_base(scanner, base_address)
    my_unit, _ = get_local_team(scanner, base_address)

    # 🚀 กวาดอ่านข้อมูลเบื้องต้น
    raw_weapon = scanner.read_mem(cgame_base + OFF_WEAPON_PTR, 8)
    weapon_ptr = struct.unpack("<Q", raw_weapon)[0] if raw_weapon else 0
    
    # เก็บ Snapshot ของ Memory ไว้เปรียบเทียบ
    memory_snapshot = {} # { (block_name, offset): last_value_as_float }
    candidates = [] # เก็บแบบ (block_name, offset)

    while True:
        clear_screen()
        print("==================================================")
        print("🔭 WTM TACTICAL: SIGHT TRACKER v5 (CHANGE DETECTOR)")
        print("==================================================")
        print(f"🎯 จำนวนผู้ต้องสงสัยที่เหลืออยู่ : {len(candidates)} รายการ")
        print(f"📍 WeaponPtr: {hex(weapon_ptr)} | Unit: {hex(my_unit)}")
        print("-" * 50)
        print("[1] 🏁 เริ่มต้นการดักจับ (First Scan - ดึงข้อมูลปัจจุบัน)")
        print("[2] ➕ คัดกรอง: ค่าที่ 'เพิ่มขึ้น' (Increased Value)")
        print("[3] ➖ คัดกรอง: ค่าที่ 'ลดลง' (Decreased Value)")
        print("[4] 📋 ดูพิกัดที่เหลือ (Dump Candidates)")
        print("[5] 🗑️ ล้างค่าทั้งหมด (Reset)")
        print("[0] EXIT")
        print("-" * 50)
        
        choice = input("👉 เลือกคำสั่ง (0-5): ").strip()
        
        if choice == '0': break
        elif choice == '5': 
            candidates = []
            memory_snapshot = {}
            continue

        # --- [1] สแกนครั้งแรก (เก็บข้อมูลเริ่มต้น) ---
        elif choice == '1':
            print("[*] กำลังบันทึกสถานะ Memory ปัจจุบัน...")
            candidates = []
            memory_snapshot = {}
            
            blocks = [
                ("WeaponPtr", weapon_ptr, 0x10000), 
                ("MyUnit", my_unit, 0x8000),
                ("CGame", cgame_base, 0x5000)
            ]

            for name, ptr, size in blocks:
                if not is_valid_ptr(ptr): continue
                data = scanner.read_mem(ptr, size)
                if not data: continue
                for off in range(0, size - 4, 4):
                    val = struct.unpack_from("<f", data, off)[0]
                    if math.isfinite(val):
                        memory_snapshot[(name, off)] = val
                        candidates.append((name, off))
            
            print(f"[+] บันทึกเสร็จสิ้น! เริ่มต้นด้วยผู้ต้องสงสัย {len(candidates)} รายการ")
            input("กด Enter เพื่อไปต่อ...")

        # --- [2] หรือ [3] คัดกรองความเปลี่ยนแปลง ---
        elif choice in ['2', '3']:
            if not candidates:
                print("[-] กรุณากด 1 เพื่อเริ่มต้นก่อนครับ")
                time.sleep(1); continue
                
            print(f"[*] กำลังวิเคราะห์หาค่าที่ {'เพิ่มขึ้น' if choice == '2' else 'ลดลง'}...")
            new_candidates = []
            
            # อ่านข้อมูลใหม่มาเทียบ
            current_data = {}
            blocks = [("WeaponPtr", weapon_ptr, 0x10000), ("MyUnit", my_unit, 0x8000), ("CGame", cgame_base, 0x5000)]
            for name, ptr, size in blocks:
                if is_valid_ptr(ptr): current_data[name] = scanner.read_mem(ptr, size)

            for name, off in candidates:
                if name not in current_data or not current_data[name]: continue
                try:
                    old_val = memory_snapshot[(name, off)]
                    new_val = struct.unpack_from("<f", current_data[name], off)[0]
                    
                    if not math.isfinite(new_val): continue
                    
                    # ตรรกะการคัดกรอง
                    is_match = False
                    if choice == '2' and new_val > old_val: is_match = True
                    if choice == '3' and new_val < old_val: is_match = True
                    
                    if is_match:
                        new_candidates.append((name, off))
                        memory_snapshot[(name, off)] = new_val # อัปเดตค่าล่าสุด
                except: pass
            
            candidates = new_candidates
            print(f"[+] คัดกรองเสร็จสิ้น! เหลือผู้ต้องสงสัย {len(candidates)} รายการ")
            input("กด Enter...")

        elif choice == '4':
            if candidates:
                print(f"\n🎯 [ รายชื่อพิกัดที่ขยับตามการเล็ง ]")
                for name, off in candidates[:20]: # โชว์แค่ 20 ตัวแรก
                    print(f" -> [{name}] Offset: 0x{off:04X} | Value: {memory_snapshot.get((name, off))}")
                if len(candidates) > 20: print(f"... และอีก {len(candidates)-20} รายการ")
            input("\nกด Enter เพื่อกลับไปเมนู...")

if __name__ == '__main__':
    main()