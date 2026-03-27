import os
import sys
import struct
import time
from main import MemoryScanner, get_game_pid

def clear_screen():
    os.system('clear' if os.name == 'posix' else 'cls')

def main():
    pid = get_game_pid()
    if not pid:
        print("[-] ห้ามพลาด: ไม่พบโปรเซสเกม!")
        sys.exit(1)
        
    scanner = MemoryScanner(pid)
    
    print("==================================================")
    print("🎯 WTM TACTICAL: PINCE ABSOLUTE ADDRESS LOGGER")
    print("==================================================")
    # ใส่ Address ที่ท่านได้จาก PINCE (เช่น 0x7c4fd88ad828)
    target_addr_str = input("👉 ใส่พิกัด Memory (Hex) : ").strip()
    
    try:
        target_addr = int(target_addr_str, 16)
    except ValueError:
        print("[-] Error: รูปแบบ Hex ไม่ถูกต้อง")
        sys.exit(1)

    print(f"[*] กำลังล็อกเป้าไปที่: {hex(target_addr)}")
    time.sleep(1)
    
    while True:
        try:
            # อ่านข้อมูล 8 Bytes จากพิกัดที่กำหนด
            data = scanner.read_mem(target_addr, 8)
            if data:
                # แปลงค่าเป็นหลายๆ รูปแบบเพื่อวิเคราะห์
                val_float = struct.unpack("<f", data[:4])[0]
                val_int = struct.unpack("<i", data[:4])[0]
                val_double = struct.unpack("<d", data)[0]
                raw_hex = data.hex().upper()
                
                clear_screen()
                print("==================================================")
                print(f"📡 ล็อกเป้าหมายพิกัด : {hex(target_addr)}")
                print("==================================================")
                print(f"➡️ FLOAT (32-bit)  : {val_float:.4f}")
                print(f"➡️ INT   (32-bit)  : {val_int}")
                print(f"➡️ DOUBLE(64-bit)  : {val_double:.4f}")
                print(f"➡️ RAW HEX         : {raw_hex[:8]} | {raw_hex[8:]}")
                print("==================================================")
                print("💡 หมุนลูกกลิ้งตั้งศูนย์เล็งในเกม แล้วสังเกตค่าที่เปลี่ยนไป")
                print("กด Ctrl+C เพื่อหยุดการสอดแนม")
                
            time.sleep(0.05) # Refresh rate 20 FPS
        except KeyboardInterrupt:
            print("\n[!] ยกเลิกภารกิจสอดแนม")
            break
        except Exception as e:
            print(f"\n[-] Error: {e}")
            break

if __name__ == '__main__':
    main()