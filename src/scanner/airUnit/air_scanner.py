import os
import sys
import struct
import math
import time
from main import MemoryScanner, get_game_pid, get_game_base_address

try:
    from src.untils.mul import get_cgame_base, is_valid_ptr, get_local_team
except ImportError:
    print("[-] Error: ไม่สามารถ import src.untils.mul ได้")
    sys.exit(1)

def main():
    print("==================================================")
    print("🕵️‍♂️ WTM DELTA HUNTER (SHOW ONLY CHANGING VALUES)")
    print("==================================================")
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    my_unit, _ = get_local_team(scanner, base_address)
    if my_unit == 0:
        print("[-] ไม่พบเครื่องบินของคุณ!")
        sys.exit(1)

    print(f"[+] กำลังติดตามเครื่องบินที่: {hex(my_unit)}")
    last_values = {}

    while True:
        os.system("clear")
        print(f"🎯 [ DELTA MONITORING ] - บินเลี้ยวไปมาเพื่อหาความเร็วที่ขยับ")
        print("-" * 75)
        print(f"{"MV (Movement)":<15} | {"VL (Velocity)":<15} | {"SPEED (km/h)":<15} | {"DELTA (การขยับ)"}")
        print("-" * 75)
        
        unit_data = scanner.read_mem(my_unit, 0x800)
        if not unit_data: continue

        found_count = 0
        for ptr_off in range(0, 0x600, 8):
            ptr_val = struct.unpack_from("<Q", unit_data, ptr_off)[0]
            if is_valid_ptr(ptr_val):
                comp_data = scanner.read_mem(ptr_val, 0x300)
                if comp_data:
                    for f_off in range(0, 0x200, 4):
                        v = struct.unpack_from("<fff", comp_data, f_off)
                        if math.isfinite(v[0]) and math.isfinite(v[1]) and math.isfinite(v[2]):
                            speed_kmh = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2) * 3.6
                            
                            # กรองความเร็วเครื่องบิน
                            if 100.0 < speed_kmh < 2500.0:
                                key = (ptr_off, f_off)
                                delta = 0
                                if key in last_values:
                                    delta = abs(speed_kmh - last_values[key])
                                
                                # 🚀 แจ็คพอต! โชว์เฉพาะตัวที่ "ขยับ" (Delta > 0.1)
                                if delta > 0.1:
                                    found_count += 1
                                    print(f"MV: {hex(ptr_off):<9} | VL: {hex(f_off):<9} | {speed_kmh:>10.1f} | ขยับ: {delta:>6.2f}")
                                
                                last_values[key] = speed_kmh
        
        if found_count == 0:
            print("[-] กำลังดักรอพิกัดที่มีการขยับ... (ลองเลี้ยวเครื่องบินด่วน!)")
        
        print("-" * 75)
        print("[*] กด Ctrl+C เพื่อหยุด")
        time.sleep(0.2)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\n[!] หยุดการทำงาน")