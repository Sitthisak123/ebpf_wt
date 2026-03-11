import sys
import time
import struct
import math
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.untils.mul import get_cgame_base, get_all_units

def is_valid_ptr(p):
    return 0x10000000000 < p < 0x7FFFFFFFFFFF

print("[*] 🕵️‍♂️ เริ่มปฏิบัติการ The Hitbox Hunter V.2 (Double Pointer Scan)...")
pid = get_game_pid()
scanner = MemoryScanner(pid)
cgame_base = get_cgame_base(scanner, get_game_base_address(pid))
units = get_all_units(scanner, cgame_base)

if not units:
    print("[-] ไม่พบรถถังในแมพ (กรุณาเข้าโหมด Test Drive หรือ Custom Battle)")
    sys.exit()

u_ptr = units[0]
print(f"[*] ตรวจสอบ Unit: {hex(u_ptr)}")

found_part_base = 0

# ==========================================
# 1. 🔍 สแกนหาอ็อบเจกต์ชิ้นส่วน (Damage Part) แบบเจาะลึก 2 ชั้น
# ==========================================
for off1 in range(0x10, 0x1500, 8):
    arr_ptr_raw = scanner.read_mem(u_ptr + off1, 8)
    if not arr_ptr_raw: continue
    arr_ptr = struct.unpack("<Q", arr_ptr_raw)[0]
    if not is_valid_ptr(arr_ptr): continue
    
    # อ่านข้อมูลทั้งบล็อกมาเช็ค (เผื่อเป็น Array ของ Struct)
    arr_data = scanner.read_mem(arr_ptr, 0x4000)
    if arr_data:
        for j in range(0, len(arr_data) - 8, 8):
            ptr1 = struct.unpack_from("<Q", arr_data, j)[0]
            if is_valid_ptr(ptr1):
                # 🚨 ตามรอย Assembly: MOV RAX, [RAX] (กระโดดชั้นที่ 2)
                ptr2_raw = scanner.read_mem(ptr1, 8)
                if ptr2_raw:
                    ptr2 = struct.unpack("<Q", ptr2_raw)[0]
                    if is_valid_ptr(ptr2):
                        # โหลด String ออกมาเช็ค
                        str_data = scanner.read_mem(ptr2, 16)
                        if str_data and b"BARREL" in str_data:
                            # เจอแล้ว! ถอยกลับไปหาฐานของอ็อบเจกต์ (RDI)
                            # เนื่องจาก j คือตำแหน่งของ 0xE0, ฐานของมันคือ j - 0xE0
                            if j >= 0xE0:
                                found_part_base = arr_ptr + j - 0xE0
                                print(f"\n[+] 🎯 BINGO! เจอกล่องดาเมจ 'BARREL' แล้ว!")
                                print(f"    - Part Base (RDI): {hex(found_part_base)}")
                                break
        if found_part_base != 0: break

if found_part_base == 0:
    print("[-] ยังหากล่อง BARREL ไม่เจอ (อาจจะเป็น Pointer แยกส่วน)")
    sys.exit()

# ==========================================
# 2. 🕵️‍♂️ จับผิดการเคลื่อนไหวเพื่อหา Matrix ปืน!
# ==========================================
print("\n[!] ห้ามขยับเมาส์! กำลังบันทึกสถานะ...")
old_data = scanner.read_mem(found_part_base, 0x200) # อ่านรอบอ็อบเจกต์ 512 bytes
time.sleep(1)

print("[🎯] >>> ขยับเมาส์หันปืนรัวๆ เลยครับ! (มีเวลา 3 วินาที) <<<")
time.sleep(3)

print("[!] กำลังเปรียบเทียบข้อมูล Matrix...")
new_data = scanner.read_mem(found_part_base, 0x200)

print("\n--- 🕵️‍♂️ ผลการจับผิด Matrix ภายในกล่องดาเมจ BARREL ---")
found_diff = False
for i in range(0, 0x200, 4):
    old_f = struct.unpack_from("<f", old_data, i)[0]
    new_f = struct.unpack_from("<f", new_data, i)[0]
    
    # กรองเฉพาะ Float ที่ขยับจริงๆ
    if math.isfinite(old_f) and math.isfinite(new_f):
        if abs(old_f - new_f) > 0.01:
            print(f"  👉 [FOUND] Offset {hex(i):>4} ขยับ! : {old_f:.3f} -> {new_f:.3f}")
            found_diff = True

if not found_diff:
    print("[-] ไม่มีการเคลื่อนไหว (ค่าเท่าเดิมเป๊ะ)")