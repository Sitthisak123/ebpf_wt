import os
import sys
import struct
import math
import time
from main import MemoryScanner, get_game_pid, get_game_base_address

try:
    from src.untils.mul import get_cgame_base, is_valid_ptr
except ImportError:
    print("[-] Error: ไม่สามารถ import src.untils.mul ได้")
    sys.exit(1)

def clear_screen(): os.system('clear')

def main():
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    
    cgame_base = get_cgame_base(scanner, base_address)
    if cgame_base == 0:
        print("[-] ไม่พบเกม War Thunder")
        sys.exit(1)

    tolerance = 1.0 
    candidates = [] 

    while True:
        clear_screen()
        print("==================================================")
        print("🔥 WTM TACTICAL: BALLISTICS (MUZZLE VELOCITY) SCANNER")
        print("==================================================")
        print(f"🎯 ผู้ต้องสงสัย (Candidates) : {len(candidates)} รายการ")
        print(f"[+] CGame Base Address : {hex(cgame_base)}")
        print("-" * 50)
        print("[1] 🔍 สแกนครั้งแรก (First Scan - หากระสุนปืนปัจจุบัน)")
        print("[2] 🎯 สแกนคัดกรอง (Next Scan - เปลี่ยนกระสุนแล้วหาซ้ำ)")
        print("[3] 📋 ดูข้อมูลผู้ต้องสงสัย (Dump Log)") # 🌟 เพิ่มเมนูนี้เข้ามา!
        print("[5] 🗑️ ล้างค่าผู้ต้องสงสัย (Reset)")
        print("[0] ❌ ออกจากโปรแกรม")
        print("-" * 50)
        
        choice = input("👉 เลือกคำสั่ง (0-5): ").strip()
        
        if choice == '0': break
        elif choice == '5':
            candidates = []
            print("[!] ล้างข้อมูลเรียบร้อย!")
            time.sleep(1)

        # ==========================================
        # 3️⃣ DUMP LOG (ดูข้อมูลปัจจุบัน)
        # ==========================================
        elif choice == '3':
            if not candidates:
                print("[-] ยังไม่มีผู้ต้องสงสัยอยู่ในระบบครับ!")
            else:
                print(f"\n🎯 [ รายชื่อ Offset กระสุนที่รอดชีวิต ({len(candidates)} รายการ) ]")
                for p_off, v_off in candidates:
                    marker = "⭐" if p_off == 0x400 else "->"
                    print(f" {marker} Ballistic Ptr (CGame + 0x{p_off:04X}) | Round Velocity: 0x{v_off:04X}")
            input("\nกด Enter เพื่อกลับไปเมนู...")

        # ==========================================
        # 1️⃣ FIRST SCAN (ควานหาโครงสร้าง Ballistics ทั้งหมด)
        # ==========================================
        elif choice == '1':
            val = input("   > ใส่ความเร็วกระสุน (m/s) จากหน้าต่างเกม (เช่น 1000): ").strip()
            try: target_speed = float(val)
            except ValueError: continue
            
            min_s, max_s = target_speed - tolerance, target_speed + tolerance
            print(f"\n[*] 📡 กำลังเจาะระบบ CGame หาความเร็วกระสุน {target_speed} m/s ...")
            
            candidates = []
            cgame_data = scanner.read_mem(cgame_base, 0x1000) 
            if not cgame_data: continue
                
            for ptr_off in range(0, 0x1000, 8):
                ptr_val = struct.unpack_from("<Q", cgame_data, ptr_off)[0]
                if is_valid_ptr(ptr_val):
                    mem_block = scanner.read_mem(ptr_val, 0x3000)
                    if not mem_block: continue
                        
                    for off in range(0, 0x3000, 4):
                        try:
                            bullet_spd = struct.unpack_from("<f", mem_block, off)[0]
                            if math.isfinite(bullet_spd) and min_s <= bullet_spd <= max_s:
                                candidates.append((ptr_off, off))
                        except: pass
            
            print(f"[+] สแกนครั้งแรกสำเร็จ! พบ {len(candidates)} รายการ")
            input("กด Enter เพื่อกลับไปเมนู...")

        # ==========================================
        # 2️⃣ NEXT SCAN (เปลี่ยนกระสุนเพื่อคัดกรอง)
        # ==========================================
        elif choice == '2':
            if not candidates:
                print("[-] ยังไม่มีผู้ต้องสงสัย! กรุณาสแกนครั้งแรกก่อน")
                time.sleep(1.5); continue
                
            val = input("   > ใส่ความเร็วกระสุน นัดใหม่ (m/s): ").strip()
            try: target_speed = float(val)
            except ValueError: continue
                
            min_s, max_s = target_speed - tolerance, target_speed + tolerance
            new_candidates = []
            cgame_data = scanner.read_mem(cgame_base, 0x1000)
            
            if cgame_data:
                for ptr_off, vel_off in candidates:
                    ptr_val = struct.unpack_from("<Q", cgame_data, ptr_off)[0]
                    if is_valid_ptr(ptr_val):
                        vel_data = scanner.read_mem(ptr_val + vel_off, 4)
                        if vel_data:
                            try:
                                bullet_spd = struct.unpack("<f", vel_data)[0]
                                if math.isfinite(bullet_spd) and min_s <= bullet_spd <= max_s:
                                    new_candidates.append((ptr_off, vel_off))
                            except: pass
                            
            candidates = new_candidates
            print(f"[+] คัดกรองเสร็จสิ้น! เหลือผู้ต้องสงสัย {len(candidates)} รายการ")
            
            if 0 < len(candidates) <= 20:
                print("\n🎯 [ แจ็คพอต! โครงสร้าง Ballistics ที่รอดชีวิต ]")
                for p_off, v_off in candidates:
                    marker = "⭐" if p_off == 0x400 else "->"
                    print(f" {marker} Ballistic Ptr (CGame + 0x{p_off:04X}) | Round Velocity: 0x{v_off:04X}")
            elif len(candidates) == 0:
                print("[-] ร่วงหมดเลย! ลองเปลี่ยนรถถังแล้วเริ่ม First Scan ใหม่ครับ")
            
            input("\nกด Enter เพื่อกลับไปเมนู...")

if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: sys.exit(0)