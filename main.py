import os
import sys
import time

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import get_cgame_base, get_view_matrix, world_to_screen
import src.utils.validator

screen_w = 2560
screen_h = 1440

def main():
    print("[*] กำลังเตรียมระบบ Matrix Radar และ W2S...")
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    
    try:
        scanner = MemoryScanner(pid)
    except PermissionError:
        print("[-] Error: สิทธิ์ไม่พอ! อย่าลืมรันด้วย sudo นะครับ")
        sys.exit(1)
        
    print(f"[+] เจอ War Thunder (PID: {pid})")
    print(f"[+] Base Address ของ aces : {hex(base_address)}")
    
    # 🚀 อัปเดต Offset สดๆ ตรงนี้เลย
    init_dynamic_offsets(scanner, base_address)
    
    validator = src.utils.validator.OffsetValidator(scanner, base_address)
    if not validator.run_diagnostics():
        print("🚨 [CRITICAL] Offsets พัง! แต่ยังจะฝืนทำงานต่อไป...")

    print("[*] กำลังเชื่อมต่อกับ CGame...\n")
    time.sleep(1)
    
    try:
        while True:
            os.system('clear')
            print("🎯 [War Thunder - Matrix & W2S Radar]")
            print("-" * 60)
            
            cgame_base = get_cgame_base(scanner, base_address)
            if cgame_base != 0:
                print(f"✅ CGame Base ของจริง: {hex(cgame_base)}")
                view_matrix = get_view_matrix(scanner, cgame_base)
                if view_matrix:
                    enemy_x, enemy_y, enemy_z = 1680.0, -130.0, 5.0
                    screen_pos = world_to_screen(view_matrix, enemy_x, enemy_y, enemy_z, screen_w, screen_h)
                    print("\n[จำลองพิกัดศัตรู: X=1680, Y=-130, Z=5]")
                    if screen_pos:
                        print(f"🎯 แปลงพิกัดสำเร็จ! วาดกรอบที่หน้าจอ: [ X: {screen_pos[0]} , Y: {screen_pos[1]} ]")
                else: print("❌ ไม่สามารถดึง View Matrix ได้")
            else: print("❌ ไม่สามารถดึง CGame Base ได้")
            
            time.sleep(0.05) 
            
    except KeyboardInterrupt:
        print("\n[!] ปิดระบบเรียบร้อยแล้ว")

if __name__ == "__main__":
    main()