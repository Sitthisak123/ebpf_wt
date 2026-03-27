import sys
import struct
from main import MemoryScanner, get_game_pid, get_game_base_address

# 🎯 ดึงฟังก์ชันและ Offsets ล่าสุดที่เราเพิ่งทำเสร็จมาจาก mul.py
from src.utils.mul import (
    get_cgame_base, get_all_units, is_valid_ptr, get_local_team,
    OFF_UNIT_STATE, OFF_UNIT_TEAM, OFF_UNIT_INFO, OFF_UNIT_NAME_PTR
)

def main():
    print("[*] 🧬 เริ่มปฏิบัติการ The Entity DNA Scanner (V.2 - Precision Build)...")
    
    pid = get_game_pid()
    scanner = MemoryScanner(pid)
    base_addr = get_game_base_address(pid)
    cgame_base = get_cgame_base(scanner, base_addr)

    units = get_all_units(scanner, cgame_base)

    if not units:
        print("[-] ไม่พบ Unit ในแมพเลย (กรุณาเข้าโหมดรบหรือ Test Drive)")
        sys.exit()

    # 🎯 1. ดึงตัวเราเอง (Local Player) และทีมของเรา ผ่านฟังก์ชันที่เชื่อถือได้
    my_unit, my_team = get_local_team(scanner, base_addr)

    print(f"[*] 🎯 รถถังของเรา (My Unit): {hex(my_unit)} | ทีมของเรา: {my_team}")
    print(f"[*] 📡 พบ Unit ในแมพทั้งหมด: {len(units)} ตัว\n")

    print("-" * 85)
    print(f"{'Status':<14} | {'Unit Ptr':<12} | {'Team':<4} | {'State':<5} | {'Unit Name (รุ่นรถถัง)':<30}")
    print("-" * 85)

    for u_ptr, is_air in units:
        unit_name = "UNKNOWN"
        team = -1
        state = -1
        
        # ---------------------------------------------------------
        # 2. 🕵️‍♂️ อ่านสถานะและทีมของยูนิต (State & Team)
        # ---------------------------------------------------------
        # อ่าน Buffer ยาว 512 bytes เพื่อให้คลุมตั้งแต่ 0xF30 ถึง 0xFB8
        status_data = scanner.read_mem(u_ptr + OFF_UNIT_STATE, 512)
        if status_data:
            state = struct.unpack_from("<H", status_data, 0)[0]
            team_offset = OFF_UNIT_TEAM - OFF_UNIT_STATE 
            team = struct.unpack_from("<B", status_data, team_offset)[0]

        # ---------------------------------------------------------
        # 3. 🏷️ อ่านชื่อรุ่นรถถัง (Unit Name) แบบยิงตรงด้วย Offset ใหม่
        # ---------------------------------------------------------
        info_raw = scanner.read_mem(u_ptr + OFF_UNIT_INFO, 8)
        if info_raw:
            info_ptr = struct.unpack("<Q", info_raw)[0]
            if is_valid_ptr(info_ptr):
                name_ptr_raw = scanner.read_mem(info_ptr + OFF_UNIT_NAME_PTR, 8)
                if name_ptr_raw:
                    name_ptr = struct.unpack("<Q", name_ptr_raw)[0]
                    if is_valid_ptr(name_ptr):
                        str_data = scanner.read_mem(name_ptr, 64)
                        if str_data:
                            try:
                                raw_str = str_data.split(b'\x00')[0].decode('utf-8', errors='ignore')
                                # กรองเอาแต่อักขระที่อ่านได้
                                unit_name = "".join([c for c in raw_str if c.isalnum() or c in '-_'])
                            except: pass

        # ---------------------------------------------------------
        # 4. 🎯 ประเมินผลและแยกหมวดหมู่
        # ---------------------------------------------------------
        if u_ptr == my_unit:
            marker = "🟢 [ME]"
        elif state >= 1: # State 1, 2, 3 มักจะแปลว่าพัง/ตายแล้ว
            marker = "💀 [DEAD]"
        elif my_team != 0 and team == my_team:
            marker = "🔵 [TEAM]"
        else:
            marker = "🔴 [ENEMY]"
            
        # สัญลักษณ์แยกรถถังกับเครื่องบิน
        type_icon = "✈️" if is_air else "🚙"

        print(f"{marker:<14} | {hex(u_ptr):<12} | {team:<4} | {state:<5} | {type_icon} {unit_name}")

    print("-" * 85)
    print("\n[💡 สรุปการตรวจสอบ Offsets]")
    print(f"OFF_UNIT_STATE ({hex(OFF_UNIT_STATE)}) -> ใช้ระบุความตาย (0=รอด, >0=ตาย)")
    print(f"OFF_UNIT_TEAM  ({hex(OFF_UNIT_TEAM)}) -> ใช้แบ่งฝ่าย (มักจะเป็น 1 หรือ 2)")
    print(f"OFF_UNIT_INFO  ({hex(OFF_UNIT_INFO)}) -> ชี้ไปหาชื่อรถถัง")

if __name__ == "__main__":
    main()