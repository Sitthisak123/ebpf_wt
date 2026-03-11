import struct
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.untils.mul import get_cgame_base

def find_death_offset():
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    cgame_base = get_cgame_base(scanner, base_addr)
    
    # หา Unit ของเรา
    control_addr = base_addr + (0x09394248 - 0x400000)
    my_unit_raw = scanner.read_mem(control_addr, 8)
    if not my_unit_raw: return
    my_unit = struct.unpack("<Q", my_unit_raw)[0]

    print(f"[*] พบรถถังของเรา: {hex(my_unit)}")
    print("[*] กรุณาอยู่ในสถานะ 'มีชีวิต' (รอดชีวิตอยู่)")
    input(">>> กด Enter เพื่อบันทึกข้อมูลตอนมีชีวิต...")
    
    # อ่าน Memory ก้อนใหญ่ช่วง 0xD00 - 0xE00 (ที่ซ่อน State ของ Linux)
    alive_data = scanner.read_mem(my_unit + 0xD00, 0x150)
    
    print("\n[!] บันทึกสำเร็จ!")
    print("[*] ทีนี้กลับเข้าเกมไป กดปุ่ม J ค้างไว้เพื่อทำลายรถตัวเอง (หรือให้ศัตรูยิงให้พัง)")
    input(">>> พอรถถังระเบิดพังแล้ว ให้กด Enter อีกครั้ง!...")

    dead_data = scanner.read_mem(my_unit + 0xD00, 0x150)

    print("\n--- 🔍 วิเคราะห์หา OFFSET ความตาย ---")
    found = False
    for i in range(0x150):
        a_val = alive_data[i]
        d_val = dead_data[i]
        # โดยปกติ: รอดชีวิต = 0, ตาย/ระเบิด = 1 หรือ 2 หรือ 3
        if a_val == 0 and d_val in [1, 2, 3]:
            print(f"✅ BINGO! เจอสถานะการตายที่ Offset: {hex(0xD00 + i)} (ค่าเปลี่ยนจาก 0 -> {d_val})")
            found = True

    if not found:
        print("[-] ไม่เจอความเปลี่ยนแปลงแบบ 0 -> 1 เลย ลองเช็คใหม่หรือขยายขอบเขตการค้นหาครับ")

if __name__ == "__main__":
    find_death_offset()