import os
import sys
import struct
import math
import time
from main import MemoryScanner, get_game_pid, get_game_base_address

# ดึงฟังก์ชันพื้นฐานจาก mul.py ของท่าน
try:
    from src.untils.mul import get_cgame_base, get_local_team, is_valid_ptr
except ImportError:
    print("[-] Error: ไม่สามารถ import src.untils.mul ได้")
    sys.exit(1)

def scan_all_floats(scanner, unit_ptr):
    """
    ฟังก์ชันสแกนหา Pointer ทั้งหมดในตัวรถถัง และอ่านค่า Float ข้างใน Pointer นั้น
    คืนค่ากลับมาเป็น Dictionary: {(Pointer_Offset, Float_Offset): Float_Value}
    """
    results = {}
    # อ่าน Memory ก้อนใหญ่ของรถถัง (ขนาด 0x3000 bytes)
    unit_data = scanner.read_mem(unit_ptr, 0x3000)
    if not unit_data or len(unit_data) < 0x3000:
        return results

    # สแกนหา Pointer ทุกๆ 8 bytes
    for ptr_off in range(0, 0x3000, 8):
        ptr_val = struct.unpack_from("<Q", unit_data, ptr_off)[0]
        
        # ถ้าค่านี้เป็น Pointer ที่ชี้ไปยัง Memory อื่น (is_valid_ptr)
        if is_valid_ptr(ptr_val):
            # เข้าไปอ่านข้อมูลใน Pointer นั้น (ขนาด 0x200 bytes)
            comp_data = scanner.read_mem(ptr_val, 0x200)
            if comp_data and len(comp_data) == 0x200:
                # สแกนหาค่า Float (ทศนิยม) ทุกๆ 4 bytes
                for float_off in range(0, 0x200, 4):
                    f_val = struct.unpack_from("<f", comp_data, float_off)[0]
                    # กรองเฉพาะตัวเลข Float ที่สมเหตุสมผล ไม่ใช่ค่าขยะหรือ Infinity
                    if math.isfinite(f_val) and abs(f_val) < 100000.0:
                        results[(ptr_off, float_off)] = f_val
                        
    return results

def main():
    print("==================================================")
    print("🟢 WTM TACTICAL SCANNER: VELOCITY FINDER")
    print("==================================================")
    
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    
    if base_address == 0:
        print("[-] ไม่พบเกม War Thunder")
        sys.exit(1)
        
    scanner = MemoryScanner(pid)
    cgame_base = get_cgame_base(scanner, base_address)
    
    if cgame_base == 0:
        print("[-] เข้าเกมและลงสนาม (Test Drive) ก่อนครับ")
        sys.exit(1)

    my_unit, my_team = get_local_team(scanner, base_address)
    if my_unit == 0:
        print("[-] ค้นหารถถังของคุณไม่พบ")
        sys.exit(1)
        
    print(f"[+] พบรถถังของคุณที่ Address: {hex(my_unit)}")
    print("[*] ดึงข้อมูล Pointer สำเร็จ... พร้อมเริ่มสแกน!")
    print("-" * 50)

    candidates = {}
    scan_count = 0

    while True:
        print("\n[ คำสั่งสแกน ]")
        print("พิมพ์ '0' = สแกนตอนรถถัง จอดนิ่งสนิท (ความเร็ว = 0)")
        print("พิมพ์ '1' = สแกนตอนรถถัง กำลังวิ่ง (ความเร็ว > 0 หรือ < 0)")
        print("พิมพ์ 'r' = รีเซ็ตการสแกนใหม่")
        print("พิมพ์ 'q' = ออกจากโปรแกรม")
        
        cmd = input("👉 ใส่คำสั่ง: ").strip().lower()
        
        if cmd == 'q':
            break
        elif cmd == 'r':
            candidates = {}
            scan_count = 0
            print("[!] รีเซ็ตข้อมูลแล้ว")
            continue
            
        if cmd not in ['0', '1']:
            print("[-] คำสั่งไม่ถูกต้อง")
            continue

        # ดึงค่า Memory สดๆ ณ ตอนที่กด Enter
        current_data = scan_all_floats(scanner, my_unit)
        if not current_data:
            print("[-] อ่าน Memory ล้มเหลว")
            continue

        if scan_count == 0:
            # การสแกนครั้งแรก (First Scan)
            for key, val in current_data.items():
                if cmd == '0' and abs(val) < 0.001: # ถ้านิ่ง ค่าต้องใกล้ 0
                    candidates[key] = val
                elif cmd == '1' and abs(val) > 0.1: # ถ้าวิ่ง ค่าต้องมากกว่า 0
                    candidates[key] = val
            print(f"[+] สแกนครั้งแรกพบค่าที่ตรงเงื่อนไข: {len(candidates)} รายการ")
        else:
            # การสแกนคัดกรอง (Next Scan)
            new_candidates = {}
            for key in candidates:
                if key in current_data:
                    val = current_data[key]
                    if cmd == '0' and abs(val) < 0.001:
                        new_candidates[key] = val
                    elif cmd == '1' and abs(val) > 0.1:
                        new_candidates[key] = val
            candidates = new_candidates
            print(f"[+] กรองเหลือ: {len(candidates)} รายการ")

        scan_count += 1

        # ถ้าเหลือน้อยกว่า 15 รายการ ให้ปริ้นท์โชว์เลย!
        if 0 < len(candidates) <= 25:
            print("\n🎯 [ พบผู้ต้องสงสัย (Candidates) ]")
            for (ptr_off, float_off), val in candidates.items():
                print(f" -> Movement Pointer: 0x{ptr_off:03X} | Velocity Offset: 0x{float_off:03X} | ค่าปัจจุบัน: {val:.3f}")
        elif len(candidates) == 0:
            print("[-] ไม่เหลือรายการที่ตรงเงื่อนไข กรุณากด 'r' เพื่อเริ่มใหม่")

if __name__ == "__main__":
    main()