import os
import sys
import struct
import math
import time
from main import MemoryScanner, get_game_pid, get_game_base_address

# ดึงฟังก์ชันที่จำเป็น
try:
    from src.untils.mul import get_cgame_base, get_local_team, is_valid_ptr
except ImportError:
    print("[-] Error: ไม่สามารถ import src.untils.mul ได้")
    sys.exit(1)

def main():
    os.system('clear')
    print("==================================================")
    print("✈️ WTM TACTICAL: INTERACTIVE VELOCITY SCANNER (+- 2 km/h)")
    print("==================================================")
    
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    
    cgame_base = get_cgame_base(scanner, base_address)
    if cgame_base == 0:
        print("[-] ไม่พบเกม War Thunder")
        sys.exit(1)

    my_unit, my_team = get_local_team(scanner, base_address)
    if my_unit == 0:
        print("[-] ไม่พบเครื่องบินของคุณ! (กรุณากดเข้าสนาม Test Drive ก่อนสแกน)")
        sys.exit(1)
        
    print(f"[+] พบเครื่องบินของคุณที่: {hex(my_unit)}")
    print("[!] ยุทธวิธี: บินให้นิ่งๆ ดูเลขบนหน้าปัด แล้วนำมาพิมพ์ใส่สคริปต์นี้")
    print("-" * 60)

    try:
        while True:
            # 🎯 รอรับค่าจากผู้ใช้ (Interactive Mode)
            user_input = input("\n👉 ใส่ความเร็วบนหน้าปัด (km/h) หรือพิมพ์ 'q' เพื่อออก: ").strip()
            
            if user_input.lower() == 'q':
                break
                
            try:
                target_speed = float(user_input)
            except ValueError:
                print("[-] กรุณาใส่ตัวเลขเท่านั้น!")
                continue

            # คำนวณระยะสแกน +- 2 km/h
            min_speed = target_speed - 2.0
            max_speed = target_speed + 2.0

            print(f"[*] กำลังสแกนหา Memory ที่มีความเร็วระหว่าง {min_speed:.1f} - {max_speed:.1f} km/h ...")

            # อ่านโครงสร้างเครื่องบินของเรา
            unit_data = scanner.read_mem(my_unit, 0x200)
            if not unit_data:
                print("[-] อ่าน Memory ล้มเหลว")
                continue
                
            found_count = 0
            
            # กวาดหา Pointer ทุกตัวในตัวเรา
            for ptr_off in range(0, 0x200, 8):
                ptr_val = struct.unpack_from("<Q", unit_data, ptr_off)[0]
                
                if is_valid_ptr(ptr_val):
                    mem_block = scanner.read_mem(ptr_val, 0x2000)
                    if not mem_block or len(mem_block) < 0x2000:
                        continue
                        
                    # 🔍 สแกนหาฟิสิกส์แบบ Double (64-bit) 
                    for off in range(0, 0x2000 - 24, 8):
                        try:
                            vx, vy, vz = struct.unpack_from("<ddd", mem_block, off)
                            if math.isfinite(vx) and math.isfinite(vy) and math.isfinite(vz):
                                if abs(vx) < 3000 and abs(vy) < 3000 and abs(vz) < 3000:
                                    speed_ms = math.sqrt(vx**2 + vy**2 + vz**2)
                                    speed_kmh = speed_ms * 3.6
                                    
                                    # 🎯 FILTER: กรองเฉพาะ Target +- 2 km/h
                                    if min_speed <= speed_kmh <= max_speed:
                                        print(f"[⭐ DOUBLE] Move Ptr: 0x{ptr_off:02X} -> Vel Offset: 0x{off:04X} | SPEED: {speed_kmh:6.1f} km/h")
                                        found_count += 1
                        except: pass
                        
                    # 🔍 สแกนหาฟิสิกส์แบบ Float (32-bit)
                    for off in range(0, 0x2000 - 12, 4):
                        try:
                            vx, vy, vz = struct.unpack_from("<fff", mem_block, off)
                            if math.isfinite(vx) and math.isfinite(vy) and math.isfinite(vz):
                                if abs(vx) < 3000 and abs(vy) < 3000 and abs(vz) < 3000:
                                    speed_ms = math.sqrt(vx**2 + vy**2 + vz**2)
                                    speed_kmh = speed_ms * 3.6
                                    
                                    # 🎯 FILTER: กรองเฉพาะ Target +- 2 km/h
                                    if min_speed <= speed_kmh <= max_speed:
                                        print(f"[🔸 FLOAT ] Move Ptr: 0x{ptr_off:02X} -> Vel Offset: 0x{off:04X} | SPEED: {speed_kmh:6.1f} km/h")
                                        found_count += 1
                        except: pass
                        
            if found_count == 0:
                print(f"[-] ไม่พบค่าความเร็วในช่วง {min_speed:.1f} - {max_speed:.1f} km/h")
            else:
                print(f"[+] สแกนเสร็จสิ้น! พบผู้ต้องสงสัยทั้งหมด {found_count} รายการ")
            
    except KeyboardInterrupt:
        print("\n[!] ปิดระบบสแกนเนอร์เรียบร้อย")

if __name__ == '__main__':
    main()