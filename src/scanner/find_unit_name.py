import sys
import struct
import re
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.utils.mul import get_cgame_base, get_all_units, get_local_team

# 🛡️ อัปเดตตัวกรอง Pointer ให้ครอบคลุม 64-bit Memory ใน Linux
def is_valid_ptr(p): 
    return 0x10000 < p < 0xFFFFFFFFFFFFFFFF

print("[*] 🧬 เริ่มปฏิบัติการชำแหละหาชื่อรถถัง (Deep Name Hunter v2)...")
pid = get_game_pid()
scanner = MemoryScanner(pid)
base_addr = get_game_base_address(pid)
cgame_base = get_cgame_base(scanner, base_addr)
units = get_all_units(scanner, cgame_base)

if not units:
    print("[-] ไม่พบ Unit (กรุณาเข้าโหมด Test Drive)")
    sys.exit()

# เอาตัวเราเองเป็นหนูทดลอง โดยใช้ฟังก์ชันจาก mul.py
my_unit, my_team = get_local_team(scanner, base_addr)

# ถ้าหา Local Player ไม่เจอ ให้ดึงเป้าหมายแรกในแมปมาสแกนแทน
if not my_unit or not is_valid_ptr(my_unit):
    print("[-] หา Local Player ไม่เจอ ขอสุ่ม Unit ในแมปมาทดสอบแทน...")
    my_unit = units[0][0]

print(f"[*] กำลังเอ็กซเรย์ Unit ที่ Address: {hex(my_unit)}\n")
print("-" * 70)
print(f"{'Offset ชั้น 1':<15} | {'Offset ชั้น 2':<15} | {'ข้อความที่เจอ (String)'}")
print("-" * 70)

found_count = 0

# 🎯 ขยายระยะสแกนจาก 0x400 เป็น 0x1500 (เพราะใน v2 Pointer ซ่อนอยู่ลึกมาก)
for off1 in range(0x0, 0x1500, 8):
    ptr1_raw = scanner.read_mem(my_unit + off1, 8)
    if not ptr1_raw: continue
    ptr1 = struct.unpack("<Q", ptr1_raw)[0]
    
    if is_valid_ptr(ptr1):
        # ลองอ่านชั้นที่ 1
        data = scanner.read_mem(ptr1, 64)
        if data:
            try:
                # แปลง Memory Byte เป็น String โดยตัดที่ \x00
                raw_str = data.split(b'\x00')[0].decode('utf-8', errors='ignore')
                # กรองคำให้ตรงกับหมวดหมู่ยานพาหนะ
                if len(raw_str) >= 4 and any(x in raw_str.lower() for x in ["us_", "germ_", "ussr_", "uk_", "jp_", "cn_", "it_", "fr_", "sw_", "il_", "dummy", "tank", "weapon"]):
                    print(f"[0x{off1:x}] {'':<9} | {'(ฝังอยู่ในชั้นแรก)':<15} | 🎯 '{raw_str}'")
                    found_count += 1
            except: pass
        
        # ลองเจาะชั้นที่ 2 (Double Pointer) ค้นหา String
        for off2 in range(0x0, 0x100, 8):
            ptr2_raw = scanner.read_mem(ptr1 + off2, 8)
            if not ptr2_raw: continue
            ptr2 = struct.unpack("<Q", ptr2_raw)[0]
            
            if is_valid_ptr(ptr2):
                data2 = scanner.read_mem(ptr2, 64)
                if data2:
                    try:
                        raw_str2 = data2.split(b'\x00')[0].decode('utf-8', errors='ignore')
                        if len(raw_str2) >= 4 and any(x in raw_str2.lower() for x in ["us_", "germ_", "ussr_", "uk_", "jp_", "cn_", "it_", "fr_", "sw_", "il_", "dummy", "tank", "weapon"]):
                            print(f"[0x{off1:x}] {'':<9} | [0x{off2:x}] {'':<9} | 🎯 '{raw_str2}'")
                            found_count += 1
                    except: pass

if found_count == 0:
    print("[-] หาไม่เจอเลยครับ เอนจินอาจจะเข้ารหัส String ไว้ หรือซ่อนลึกกว่า 2 ชั้น!")
else:
    print("-" * 70)
    print("\n[💡 สำเร็จ!] ถ้าท่านเห็นชื่อรถถังของท่าน (เช่น us_m4a3_sherman หรือ germ_pzkpfw...)")
    print("👉 Offset ชั้น 1 ที่เจอ คือค่าของ OFF_UNIT_INFO (เช่น 0xfc8)")
    print("👉 Offset ชั้น 2 ที่เจอ คือค่าของ OFF_UNIT_NAME_PTR (เช่น 0x20 หรือ 0x28)")