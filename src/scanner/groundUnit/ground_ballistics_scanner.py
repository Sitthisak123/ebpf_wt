import os
import sys
import struct
import time
from main import MemoryScanner, get_game_pid, get_game_base_address

def clear_screen():
    os.system('clear' if os.name == 'posix' else 'cls')

def get_cgame_base(scanner, base_addr):
    # DAT_MANAGER Offset: 0x093924e0 - 0x400000 = 0x8F924E0
    raw = scanner.read_mem(base_addr + 0x8F924E0, 8)
    if raw: return struct.unpack("<Q", raw)[0]
    return 0

def main():
    pid = get_game_pid()
    if not pid:
        print("[-] ห้ามพลาด: ไม่พบโปรเซสเกม!")
        sys.exit(1)
        
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    
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
                
            w_ptr_raw = scanner.read_mem(cgame_base + 0x0408, 8)
            if not w_ptr_raw: 
                continue
            weapon_ptr = struct.unpack("<Q", w_ptr_raw)[0]
            
            if weapon_ptr < 0x10000:
                print("[-] กรุณาเข้า Test Drive และเกิดรถถังให้เรียบร้อย...")
                time.sleep(1)
                continue

            # 🎯 กวาดข้อมูลแบบปูพรม 80 Bytes ตั้งแต่ 0x1F00 ถึง 0x1F50
            start_off = 0x1F00
            scan_size = 80 
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
                    # มาร์คจุดที่เรารู้แล้ว
                    if current_off == 0x1F20:
                        remarks = "⭐⭐ BULLET SPEED (มัซเซิล 100%!)"
                    # คัดกรองตัวเลขที่น่าจะเป็น Mass (ปกติ 0.5kg ถึง 50.0kg)
                    elif 0.5 <= val <= 50.0:
                        remarks = "<-- 🎯 อาจจะเป็น MASS (ลองเปลี่ยนกระสุนดู!)"
                    # คัดกรอง Caliber (ปกติ 0.05m ถึง 0.15m)
                    elif 0.02 <= val <= 0.20:
                        remarks = "<-- 📏 อาจจะเป็น CALIBER/DIAMETER"
                        
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