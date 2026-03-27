import os
import sys
import struct
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.untils.mul import get_cgame_base

def hunt_v2():
    pid = get_game_pid()
    base = get_game_base_address(pid)
    
    try:
        scanner = MemoryScanner(pid)
    except PermissionError:
        print("[-] สิทธิ์ไม่พอ! รันด้วย sudo นะครับ")
        return

    cgame = get_cgame_base(scanner, base)
    if cgame == 0:
        print("[-] หา CGame ไม่เจอ")
        return

    print(f"[*] CGame ของจริงอยู่ที่: {hex(cgame)}")
    print("[*] กำลังกวาดหาโครงสร้าง Array ทั้งหมด (ช่วง 0x100 ถึง 0x2000)...")
    print("-" * 60)

    # ขยายช่วงค้นหาเป็น 0x2000
    for offset in range(0x100, 0x2000, 8):
        # 🚨 ข้ามตัวหลอกที่เราเจอแล้ว
        if offset == 0x498:
            continue
            
        # 🎯 แบบที่ 1: Direct Array
        raw_data = scanner.read_mem(cgame + offset, 8)
        raw_count = scanner.read_mem(cgame + offset + 8, 4)
        
        if raw_data and raw_count:
            data_ptr = struct.unpack("<Q", raw_data)[0]
            count = struct.unpack("<I", raw_count)[0]
            
            # โชว์เฉพาะ Array ที่มีขนาด 0 - 200
            if 0 <= count <= 200 and data_ptr > 0x10000000000:
                print(f"🔍 [Direct] Offset: {hex(offset):<6} | จำนวน: {count:<3} | DataPtr: {hex(data_ptr)}")

        # 🎯 แบบที่ 2: Pointer to Array
        raw_ptr = scanner.read_mem(cgame + offset, 8)
        if raw_ptr:
            ptr = struct.unpack("<Q", raw_ptr)[0]
            if ptr > 0x10000000000:
                raw_data2 = scanner.read_mem(ptr, 8)
                raw_count2 = scanner.read_mem(ptr + 8, 4)
                
                if raw_data2 and raw_count2:
                    data_ptr2 = struct.unpack("<Q", raw_data2)[0]
                    count2 = struct.unpack("<I", raw_count2)[0]
                    
                    if 0 <= count2 <= 200 and data_ptr2 > 0x10000000000:
                        print(f"🔍 [Pointer] Offset: {hex(offset):<6} | จำนวน: {count2:<3} | DataPtr: {hex(data_ptr2)}")

    print("-" * 60)
    print("[*] เสร็จสิ้นการสแกน!")

if __name__ == "__main__":
    hunt_v2()