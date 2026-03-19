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

def clear_screen():
    os.system('clear')

def print_header(candidates_count):
    clear_screen()
    print("==================================================")
    print("🚙 WTM TACTICAL: OMNI-UNIT VELOCITY SCANNER")
    print("==================================================")
    print(f"🎯 ผู้ต้องสงสัย (Candidates) ที่เหลืออยู่: {candidates_count} รายการ")
    print("==================================================")

def main():
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    
    cgame_base = get_cgame_base(scanner, base_address)
    if cgame_base == 0:
        print("[-] ไม่พบเกม War Thunder")
        sys.exit(1)

    # 🚨 ยุทธวิธีใหม่: ดึงมัน "ทุกคัน" ทั้งเครื่องบิน ฮอ รถถัง บอท
    all_units = get_all_units(scanner, cgame_base)
    print(f"[*] 📡 พบยูนิตในระบบทั้งหมด: {len(all_units)} คัน")

    if not all_units:
        print("[-] ไม่พบยูนิตในแมปเลย! (ท่านอยู่ในหน้า Hangar หรือเปล่า? กรุณากดเข้า Test Drive ก่อนรัน)")
        sys.exit(1)

    target_units = [u[0] for u in all_units] # ไม่กรองอะไรทิ้งทั้งนั้น เอามาหมด!

    # ตัวแปรระบบ
    tolerance = 2.0
    candidates = [] # เก็บข้อมูล: (u_ptr, ptr_offset, vel_offset, data_type)

    while True:
        print_header(len(candidates))
        print(f"[+] 📡 พร้อมสแกนยูนิตทั้งหมด: {len(target_units)} คัน")
        print(f"[*] ⚙️ ระยะการกรอง (Filter Tolerance): +- {tolerance} km/h")
        print("-" * 50)
        print("[1] 🔍 สแกนครั้งแรก (First Scan - หาค่าทั้งหมด)")
        print("[2] 🎯 สแกนคัดกรอง (Next Scan - ตัดค่าที่ไม่ตรงทิ้ง)")
        print("[3] 👀 เฝ้าระวังผู้ต้องสงสัย (Watch Candidates Live)")
        print("[4] ⚙️ ตั้งค่าระยะบวกลบ (Set Filter Tolerance)")
        print("[5] 🗑️ ล้างค่าผู้ต้องสงสัย (Reset Candidates)")
        print("[0] ❌ ออกจากโปรแกรม (Exit)")
        print("-" * 50)
        
        choice = input("👉 เลือกคำสั่ง (0-5): ").strip()
        
        if choice == '0':
            print("\n[!] ปิดศูนย์บัญชาการเรียบร้อย")
            break
            
        elif choice == '4':
            val = input("   > ใส่ระยะบวกลบ (เช่น 1.0, 2.0): ").strip()
            try: tolerance = float(val)
            except: pass

        elif choice == '5':
            candidates = []
            print("[!] ล้างข้อมูล (Reset) เรียบร้อย!")
            time.sleep(1)

        # ==========================================
        # 1️⃣ FIRST SCAN (กวาดหาทั้งหมด)
        # ==========================================
        elif choice == '1':
            val = input("   > ใส่ความเร็ว ปัจจุบัน บนหน้าปัด (km/h): ").strip()
            try: target_speed = float(val)
            except ValueError: continue
            
            min_s, max_s = target_speed - tolerance, target_speed + tolerance
            print(f"\n[*] 📡 กำลังสแกนปูพรมทุกยูนิต หาช่วง {min_s:.1f} - {max_s:.1f} km/h ...")
            
            candidates = []
            
            for u_ptr in target_units:
                unit_data = scanner.read_mem(u_ptr, 0x2500)
                if not unit_data: continue
                    
                for ptr_off in range(0, len(unit_data) - 8, 8):
                    ptr_val = struct.unpack_from("<Q", unit_data, ptr_off)[0]
                    if is_valid_ptr(ptr_val):
                        mem_block = scanner.read_mem(ptr_val, 0x1000)
                        if not mem_block or len(mem_block) < 0x1000: continue
                            
                        # สแกนหา Float (32-bit)
                        for off in range(0, len(mem_block) - 12, 4):
                            try:
                                vx, vy, vz = struct.unpack_from("<fff", mem_block, off)
                                if math.isfinite(vx) and math.isfinite(vy) and math.isfinite(vz):
                                    if abs(vx) < 500 and abs(vy) < 500 and abs(vz) < 500:
                                        speed_kmh = math.sqrt(vx**2 + vy**2 + vz**2) * 3.6
                                        if min_s <= speed_kmh <= max_s:
                                            candidates.append((u_ptr, ptr_off, off, "FLOAT"))
                            except: pass
                            
                        # สแกนหา Double (64-bit)
                        for off in range(0, len(mem_block) - 24, 8):
                            try:
                                vx, vy, vz = struct.unpack_from("<ddd", mem_block, off)
                                if math.isfinite(vx) and math.isfinite(vy) and math.isfinite(vz):
                                    if abs(vx) < 500 and abs(vy) < 500 and abs(vz) < 500:
                                        speed_kmh = math.sqrt(vx**2 + vy**2 + vz**2) * 3.6
                                        if min_s <= speed_kmh <= max_s:
                                            candidates.append((u_ptr, ptr_off, off, "DOUBLE"))
                            except: pass
            
            print(f"[+] สแกนครั้งแรกสำเร็จ! พบ {len(candidates)} รายการ ถูกบันทึกไว้ใน Candidates แล้ว")
            input("กด Enter เพื่อกลับไปเมนู...")

        # ==========================================
        # 2️⃣ NEXT SCAN (คัดกรองตัวเลขที่ไม่ตรงออกไป)
        # ==========================================
        elif choice == '2':
            if not candidates:
                print("[-] ยังไม่มีผู้ต้องสงสัย! กรุณากด 1 ทำ 'สแกนครั้งแรก' ก่อนครับ")
                time.sleep(1.5)
                continue
                
            val = input("   > ใส่ความเร็ว ใหม่ล่าสุด บนหน้าปัด (km/h): ").strip()
            try: target_speed = float(val)
            except ValueError: continue
                
            min_s, max_s = target_speed - tolerance, target_speed + tolerance
            print(f"\n[*] 🎯 กำลังคัดกรอง {len(candidates)} รายการ ที่ความเร็ว {min_s:.1f} - {max_s:.1f} km/h ...")
            
            new_candidates = []
            
            for u_ptr, ptr_off, vel_off, dtype in candidates:
                unit_data = scanner.read_mem(u_ptr, 0x2500)
                if unit_data and ptr_off + 8 <= len(unit_data):
                    ptr_val = struct.unpack_from("<Q", unit_data, ptr_off)[0]
                    if is_valid_ptr(ptr_val):
                        vel_data = scanner.read_mem(ptr_val + vel_off, 24 if dtype == "DOUBLE" else 12)
                        if vel_data:
                            try:
                                if dtype == "FLOAT":
                                    vx, vy, vz = struct.unpack("<fff", vel_data)
                                else:
                                    vx, vy, vz = struct.unpack("<ddd", vel_data)
                                    
                                if math.isfinite(vx) and math.isfinite(vy) and math.isfinite(vz):
                                    speed_kmh = math.sqrt(vx**2 + vy**2 + vz**2) * 3.6
                                    if min_s <= speed_kmh <= max_s:
                                        new_candidates.append((u_ptr, ptr_off, vel_off, dtype))
                            except: pass
                            
            candidates = new_candidates
            print(f"[+] คัดกรองเสร็จสิ้น! ผู้ต้องสงสัยร่วงลงไปเหลือ {len(candidates)} รายการ")
            
            if 0 < len(candidates) <= 20:
                print("\n🎯 [ แจ็คพอต! รายชื่อ Offset ที่รอดชีวิต ]")
                for u_ptr, p_off, v_off, dt in candidates:
                    print(f" -> Move Ptr: 0x{p_off:04X} | Vel Offset: 0x{v_off:04X} ({dt}) | ยูนิต: {hex(u_ptr)}")
            elif len(candidates) == 0:
                print("[-] ร่วงหมดเลยครับท่าน! กรุณากด 5 Reset แล้วเริ่มสแกน 1 ใหม่อีกครั้ง")
            
            input("\nกด Enter เพื่อกลับไปเมนู...")

        # ==========================================
        # 3️⃣ WATCH LIVE (โชว์ข้อมูลสดๆ ของผู้ต้องสงสัยที่เหลือ)
        # ==========================================
        elif choice == '3':
            if not candidates:
                print("[-] ไม่มีรายการให้เฝ้าระวัง")
                time.sleep(1.5)
                continue
                
            print("\n[*] 👀 เปิดเรดาร์ดักฟังผู้ต้องสงสัย (ขับรถแล้วดูว่าค่าไหนวิ่งตรงกับหน้าปัด)")
            print("[!] (กด Ctrl+C เพื่อหยุดเฝ้าระวัง)")
            print("-" * 60)
            try:
                while True:
                    print(f"\n[{time.strftime('%H:%M:%S')}] --- LIVE MONITORING ({len(candidates)} items) ---")
                    for u_ptr, p_off, v_off, dt in candidates:
                        unit_data = scanner.read_mem(u_ptr, 0x2500)
                        if unit_data and p_off + 8 <= len(unit_data):
                            ptr_val = struct.unpack_from("<Q", unit_data, p_off)[0]
                            if is_valid_ptr(ptr_val):
                                vel_data = scanner.read_mem(ptr_val + v_off, 24 if dt == "DOUBLE" else 12)
                                if vel_data:
                                    try:
                                        if dt == "FLOAT":
                                            vx, vy, vz = struct.unpack("<fff", vel_data)
                                        else:
                                            vx, vy, vz = struct.unpack("<ddd", vel_data)
                                        speed_kmh = math.sqrt(vx**2 + vy**2 + vz**2) * 3.6
                                        print(f"🔸 Ptr: 0x{p_off:04X} -> Vel: 0x{v_off:04X} | SPEED: {speed_kmh:6.1f} km/h")
                                    except: pass
                    time.sleep(0.5) 
            except KeyboardInterrupt:
                print("\n[!] หยุดเฝ้าระวัง กลับสู่เมนู...")
                time.sleep(1)

        else:
            print("[-] คำสั่งไม่ถูกต้อง!")
            time.sleep(1)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] ปิดโปรแกรมฉุกเฉิน")
        sys.exit(0)