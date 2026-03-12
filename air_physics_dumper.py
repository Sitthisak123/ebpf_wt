import os
import sys
import struct
import time
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.untils.mul import get_cgame_base, get_all_units, get_unit_status, is_valid_ptr

def clear_screen():
    os.system('clear' if os.name == 'posix' else 'cls')

def main():
    pid = get_game_pid()
    if not pid:
        print("[-] ไม่พบโปรเซสเกม!")
        sys.exit(1)
        
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    
    while True:
        try:
            clear_screen()
            print("===============================================================")
            print("✈️ WTM TACTICAL: AIR PHYSICS OFFSET DUMPER")
            print("===============================================================")
            
            cgame_base = get_cgame_base(scanner, base_addr)
            if cgame_base == 0:
                print("[-] รอเข้าสู่สนามรบ...")
                time.sleep(1)
                continue
                
            all_units = get_all_units(scanner, cgame_base)
            # กรองเอาเฉพาะเครื่องบิน (is_air == True)
            air_units = [u for u in all_units if u[1] == True]
            
            if not air_units:
                print("[-] กำลังรอเครื่องบินเกิด...")
            
            for u_ptr, is_air in air_units:
                status = get_unit_status(scanner, u_ptr)
                if not status: continue
                team, state, unit_name, _ = status
                if state >= 1: continue # ข้ามซากเครื่องบินตก
                
                mov_raw = scanner.read_mem(u_ptr + 0x18, 8) # OFF_AIR_MOVEMENT
                if not mov_raw: continue
                mov_ptr = struct.unpack("<Q", mov_raw)[0]
                if not is_valid_ptr(mov_ptr): continue
                
                # 🎯 อ่านก้อนข้อมูล 64 bytes (ตั้งแต่ 0x300 ถึง 0x33C)
                data = scanner.read_mem(mov_ptr + 0x300, 64)
                if data:
                    print(f"🎯 TARGET: {unit_name} | MOVEMENT PTR: {hex(mov_ptr)}")
                    # อ่านค่า Float ทีละ 3 ตัว (X, Y, Z = 12 Bytes)
                    for i in range(0, 60, 12): 
                        if i + 12 <= 64:
                            fx, fy, fz = struct.unpack_from("<fff", data, i)
                            offset = 0x300 + i
                            
                            marker = ""
                            if offset == 0x318: 
                                marker = "<-- ✈️ VELOCITY (ความเร็วเส้นตรง เรารู้แล้ว)"
                            elif offset == 0x324: 
                                marker = "<-- 🌪️ OMEGA (สมมติฐานปัจจุบัน)"
                            
                            # กรองค่าขยะทิ้งเพื่อให้อ่านง่าย
                            if abs(fx) < 1e-10: fx = 0.0
                            if abs(fy) < 1e-10: fy = 0.0
                            if abs(fz) < 1e-10: fz = 0.0
                            
                            print(f"   [0x{offset:03X}] : X={fx:10.2f} | Y={fy:10.2f} | Z={fz:10.2f} {marker}")
                    print("-" * 63)
            
            print("\n💡 ยุทธวิธีทดสอบ:")
            print("   1. เข้า Test Drive เลือกขับเครื่องบิน (Air)")
            print("   2. บินตรงๆ -> [0x318] VELOCITY ต้องมีค่า แต่ OMEGA ควรจะเป็น 0")
            print("   3. ลอง 'ตีลังกา/เลี้ยวแรงๆ' -> สังเกตว่า Offset บรรทัดไหน ตัวเลข X, Y, Z แกว่งขึ้นหลักสิบ!")
            time.sleep(0.1) # อัปเดตไวๆ ให้เห็นความต่าง
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(1)

if __name__ == '__main__':
    main()