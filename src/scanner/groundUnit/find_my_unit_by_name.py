import struct
import time
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.utils.mul import (
    get_cgame_base, get_all_units, is_valid_ptr, 
    OFF_UNIT_INFO, OFF_UNIT_NAME_PTR
)

def main():
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    cgame_base = get_cgame_base(scanner, base_addr)
    
    print(f"[*] 📡 กำลังค้นหารถถังที่มีชื่อรหัส: 'ussr_2s38'...")
    
    all_units = [u[0] for u in get_all_units(scanner, cgame_base)]
    my_real_unit_ptr = 0
    
    # 1. ค้นหาหาตัวรถถังจากชื่อ
    for u_ptr in all_units:
        try:
            info_raw = scanner.read_mem(u_ptr + OFF_UNIT_INFO, 8)
            if not info_raw: continue
            info_ptr = struct.unpack("<Q", info_raw)[0]
            
            if is_valid_ptr(info_ptr):
                name_ptr_raw = scanner.read_mem(info_ptr + OFF_UNIT_NAME_PTR, 8)
                if not name_ptr_raw: continue
                name_ptr = struct.unpack("<Q", name_ptr_raw)[0]
                
                if is_valid_ptr(name_ptr):
                    name_str = scanner.read_mem(name_ptr, 32).split(b'\x00')[0].decode('utf-8', errors='ignore')
                    if "2s38" in name_str.lower():
                        print(f"✅ เจอแล้ว! รถถัง 2S38 อยู่ที่ Address: {hex(u_ptr)} (ชื่อในเครื่อง: {name_str})")
                        my_real_unit_ptr = u_ptr
                        break
        except: continue

    if not my_real_unit_ptr:
        print("[-] ไม่พบรถถังที่ชื่อ ussr_2s38 ในแมปนี้เลยครับ!")
        return

    # 2. ย้อนรอยหาตำแหน่ง DAT_CONTROLLED_UNIT
    print(f"🔍 กำลังย้อนรอยหาพิกัดควบคุมจาก Data Segment...")
    search_start = base_addr + 0x9000000
    search_end = base_addr + 0xA000000
    
    found = False
    for addr in range(search_start, search_end, 8):
        raw = scanner.read_mem(addr, 8)
        if not raw: continue
        ptr_val = struct.unpack("<Q", raw)[0]
        
        if ptr_val == my_real_unit_ptr:
            offset_to_use = addr - base_addr + 0x400000
            print(f"\n🎯 [แจ็คพอต!] พบตำแหน่ง DAT_CONTROLLED_UNIT")
            print(f"👉 สำหรับ mul.py: DAT_CONTROLLED_UNIT = {hex(offset_to_use)}")
            found = True
            # ไม่หยุด เพื่อหาเผื่อมี Pointer ตัวอื่นที่เสถียรกว่า
            
    if not found:
        print("[-] เจอตัวรถถังแต่หา Pointer ที่ชี้มายังตัวเราใน Data Segment ไม่เจอครับ")

if __name__ == "__main__":
    main()