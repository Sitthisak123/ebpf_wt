import os
import sys
import struct
import time
from main import MemoryScanner, get_game_pid, get_game_base_address

try:
    from src.untils.mul import get_cgame_base, is_valid_ptr, get_all_units, get_unit_status
except ImportError:
    print("[-] Error: ไม่สามารถ import src.untils.mul ได้")
    sys.exit(1)

def main():
    print("==================================================")
    print("✈️  F-20A UNIT FINDER & MEMORY ANALYZER")
    print("==================================================")
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    cgame_base = get_cgame_base(scanner, base_address)
    if cgame_base == 0:
        print("[-] เข้าสนามรบก่อนครับท่านนายพล!")
        sys.exit(1)
    print("[*] กำลังกวาดหาเครื่องบิน F-20A ใน Memory...")
    while True:
        os.system("clear")
        print("🎯 [ รายชื่ออากาศยานที่ตรวจพบในปัจจุบัน ]")
        print("-" * 60)
        print(f"{"ADDRESS":<15} | {"TEAM":<5} | {"STATE":<6} | {"UNIT NAME"}")
        print("-" * 60)
        all_units = get_all_units(scanner, cgame_base)
        found_f20 = False
        for u_ptr, is_air in all_units:
            status = get_unit_status(scanner, u_ptr)
            if status:
                u_team, u_state, u_name, _ = status
                if "F-20A" in u_name.upper() or "F20" in u_name.upper():
                    found_f20 = True
                    print(f"\033[92m{hex(u_ptr):<15} | {u_team:<5} | {u_state:<6} | {u_name}\033[0m")
                else:
                    print(f"{hex(u_ptr):<15} | {u_team:<5} | {u_state:<6} | {u_name}")
        if not found_f20: print("\n[-] ยังไม่เจอ F-20A ในรายชื่อ...")
        print("-" * 60)
        print("[*] กด Ctrl+C เพื่อหยุด")
        time.sleep(1)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\n[!] หยุดการสแกน")