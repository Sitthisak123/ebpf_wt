import sys
import time
import struct
import math
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.untils.mul import get_cgame_base, get_all_units

pid = get_game_pid()
scanner = MemoryScanner(pid)
cgame_base = get_cgame_base(scanner, get_game_base_address(pid))
all_units = get_all_units(scanner, cgame_base)

if not all_units:
    print("[-] ไม่พบรถถัง")
    sys.exit()

u_ptr = all_units[0] # รถถังเรา
print(f"[*] ตรวจสอบ Unit: {hex(u_ptr)}")

# ถ่ายรูป Memory รอบ Unit ในระยะกว้าง (0x0 - 0xC00)
print("[!] บันทึกสถานะนิ่ง...")
old_block = scanner.read_mem(u_ptr, 0xC00)
time.sleep(1)

print("[🎯] >>> ขยับรถถัง และ หันป้อมปืน รัวๆ เลยครับ! <<<")
time.sleep(3)

print("[!] บันทึกสถานะเคลื่อนไหว...")
new_block = scanner.read_mem(u_ptr, 0xC00)

print("\n--- 🕵️‍♂️ ผลการจับผิดพิกัด/มุมหมุน ---")
for i in range(0, 0xC00, 4):
    old_f = struct.unpack_from("<f", old_block, i)[0]
    new_f = struct.unpack_from("<f", new_block, i)[0]
    
    if math.isfinite(old_f) and math.isfinite(new_f):
        if abs(old_f - new_f) > 0.01: # ถ้าค่าเปลี่ยนมากกว่า 0.01
            print(f"  [FOUND] Offset {hex(i)} : {old_f:.3f} -> {new_f:.3f}")