import os
import sys
import struct
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul

def clear_screen():
    os.system('clear' if os.name == 'posix' else 'cls')

def get_cgame_base(scanner, base_addr):
    return mul.get_cgame_base(scanner, base_addr)

def main():
    pid = get_game_pid()
    if not pid:
        print("[-] ห้ามพลาด: ไม่พบโปรเซสเกม!")
        sys.exit(1)
        
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)
    
    while True:
        try:
            clear_screen()
            print("===========================================================")
            print("⚖️ WTM TACTICAL: PROJECTILE MASS & BALLISTICS SCANNER")
            print("===========================================================")
            
            cgame_base = get_cgame_base(scanner, base_addr)
            if cgame_base == 0:
                print("[-] กำลังรอเข้าสู่สนามรบ (CGame Base ไม่ทำงาน)...")
                time.sleep(1)
                continue
                
            w_ptr_raw = scanner.read_mem(cgame_base + mul.OFF_WEAPON_PTR, 8)
            if not w_ptr_raw: 
                continue
            weapon_ptr = struct.unpack("<Q", w_ptr_raw)[0]
            
            if not mul.is_valid_ptr(weapon_ptr):
                print("[-] กรุณาเข้า Test Drive และเกิดรถถังให้เรียบร้อย...")
                time.sleep(1)
                continue

            # 🎯 กวาดข้อมูลแบบปูพรม 112 Bytes ตั้งแต่ 0x2030 ถึง 0x20A0
            start_off = 0x2030
            scan_size = 112 
            data = scanner.read_mem(weapon_ptr + start_off, scan_size)
            
            if data:
                print(f"[*] Weapon Structure: {hex(weapon_ptr)}")
                print("-----------------------------------------------------------")
                print(f"{'OFFSET':<10} | {'FLOAT VALUE':<15} | {'REMARKS'}")
                print("-----------------------------------------------------------")
                
                for i in range(0, scan_size, 4):
                    current_off = start_off + i
                    val = struct.unpack_from("<f", data, i)[0]
                    
                    remarks = ""
                    if current_off in (0x2048, 0x2050):
                        remarks = "⭐⭐ BULLET SPEED (มัซเซิล)"
                    elif current_off in (0x2054, 0x205C):
                        remarks = "<-- 🎯 อาจจะเป็น MASS"
                    elif current_off in (0x2058, 0x2060):
                        remarks = "<-- 📏 อาจจะเป็น CALIBER"
                    elif current_off in (0x205C, 0x2064):
                        remarks = "<-- 💨 อาจจะเป็น DRAG Cx"
                    elif 0.5 <= val <= 200.0:
                        remarks = "<-- 🎯 อาจจะเป็น MASS / WEIGHT"
                    elif 0.001 <= val <= 0.50:
                        remarks = "<-- 📏 อาจจะเป็น CALIBER / DIAMETER"
                    elif 0.01 <= val <= 3.0:
                        remarks = "<-- 💨 อาจจะเป็น DRAG Cx"
                        
                    print(f"0x{current_off:04X}     | {val:<15.4f} | {remarks}")

                    
            print("===========================================================")
            print("💡 ยุทธวิธีปฏิบัติการ:")
            print("   1. เอาเมาส์ชี้ดูกระสุนในเกม ดูน้ำหนักมัน (เช่น APFSDS = 4.1 kg)")
            print("   2. ดูว่าในตารางนี้ มีช่องไหนโชว์เลข 4.1000 ไหม?")
            print("   3. ลอง [กดยิง] หรือ [สลับกระสุนเป็น HE] (ซึ่งหนัก 20-30 kg)")
            print("   4. สังเกตว่าบรรทัดไหนตัวเลขเปลี่ยนไปตามน้ำหนักกระสุนเป๊ะๆ!")
            print("===========================================================")
            time.sleep(0.5) # อัปเดตทุกครึ่งวินาที
            
        except KeyboardInterrupt:
            print("\n[!] จบภารกิจสอดแนม")
            break
        except Exception as e:
            print(f"\n[-] Error: {e}")
            time.sleep(1)

if __name__ == '__main__':
    main()