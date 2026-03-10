import sys
import struct
import re
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.untils.mul import get_cgame_base, get_all_units

def is_valid_ptr(p): return 0x10000000000 < p < 0x7FFFFFFFFFFF

print("[*] 🧬 เริ่มปฏิบัติการชำแหละหาชื่อรถถัง (Deep Name Hunter)...")
pid = get_game_pid()
scanner = MemoryScanner(pid)
base_addr = get_game_base_address(pid)
cgame_base = get_cgame_base(scanner, base_addr)
units = get_all_units(scanner, cgame_base)

if not units:
    print("[-] ไม่พบ Unit (กรุณาเข้าโหมด Test Drive)")
    sys.exit()

# เอาตัวเราเองเป็นหนูทดลอง
DAT_CONTROLLED_UNIT = 0x09394248
controlled_unit_addr = base_addr + (DAT_CONTROLLED_UNIT - 0x400000)
my_unit_raw = scanner.read_mem(controlled_unit_addr, 8)
my_unit = struct.unpack("<Q", my_unit_raw)[0] if my_unit_raw else units[0]

print(f"[*] กำลังเอ็กซเรย์ Unit ของเรา: {hex(my_unit)}\n")
print("-" * 60)
print(f"{'Offset ที่เจอ':<25} | {'ข้อความที่ซ่อนอยู่'}")
print("-" * 60)

found_count = 0

# สแกน Pointer ชั้นที่ 1 และ 2
for off1 in range(0x0, 0x400, 8):
    ptr1_raw = scanner.read_mem(my_unit + off1, 8)
    if not ptr1_raw: continue
    ptr1 = struct.unpack("<Q", ptr1_raw)[0]
    
    if is_valid_ptr(ptr1):
        # ลองอ่านชั้นที่ 1
        data = scanner.read_mem(ptr1, 64)
        if data:
            # หาข้อความภาษาอังกฤษที่ยาว 5 ตัวอักษรขึ้นไป
            match = re.match(b'^[A-Za-z0-9_/-]{5,40}', data)
            if match:
                s = match.group(0).decode('utf-8', errors='ignore')
                # กรองเอาเฉพาะชื่อที่ดูเหมือนชื่อโมเดลรถถัง
                if any(x in s.lower() for x in ["us_", "germ_", "ussr_", "uk_", "jp_", "cn_", "it_", "fr_", "sw_", "il_", "dummy", "tank", "weapon"]):
                    print(f"ชั้น 1: [0x{off1:x}] {'':<11} | 🎯 '{s}'")
                    found_count += 1
        
        # ลองเจาะชั้นที่ 2 (Double Pointer)
        for off2 in range(0x0, 0x100, 8):
            ptr2_raw = scanner.read_mem(ptr1 + off2, 8)
            if not ptr2_raw: continue
            ptr2 = struct.unpack("<Q", ptr2_raw)[0]
            if is_valid_ptr(ptr2):
                data2 = scanner.read_mem(ptr2, 64)
                if data2:
                    match2 = re.match(b'^[A-Za-z0-9_/-]{5,40}', data2)
                    if match2:
                        s2 = match2.group(0).decode('utf-8', errors='ignore')
                        if any(x in s2.lower() for x in ["us_", "germ_", "ussr_", "uk_", "jp_", "cn_", "it_", "fr_", "sw_", "il_", "dummy", "tank", "weapon"]):
                            print(f"ชั้น 2: [0x{off1:x}] -> [0x{off2:x}] | 🎯 '{s2}'")
                            found_count += 1

if found_count == 0:
    print("[-] หาไม่เจอเลยครับ เอนจินอาจจะเข้ารหัส String ไว้ หรือซ่อนลึกกว่า 2 ชั้น!")
else:
    print("-" * 60)
    print("\n[💡 สำเร็จ!] ถ้าท่านเห็นชื่อรถถังของท่าน (เช่น us_m4a3_sherman หรือ germ_pzkpfw...)")
    print("ก๊อปปี้ Offset นั้นส่งมาให้ผมเลยครับ! นั่นแหละคือกุญแจในการคัดกรองเป้าหมาย!")