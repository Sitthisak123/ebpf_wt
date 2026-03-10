import sys
import struct
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.untils.mul import get_cgame_base, get_all_units, MANAGER_OFFSET

def is_valid_ptr(p): return 0x10000000000 < p < 0x7FFFFFFFFFFF

print("[*] 🧬 เริ่มปฏิบัติการ The Entity DNA Scanner...")
pid = get_game_pid()
scanner = MemoryScanner(pid)
base_addr = get_game_base_address(pid)
cgame_base = get_cgame_base(scanner, base_addr)
units = get_all_units(scanner, cgame_base)

if not units:
    print("[-] ไม่พบ Unit ในแมพเลย")
    sys.exit()

# 🎯 ดึงตัวเราเอง (Local Player -> Controlled Unit)
# จาก Offset ที่คุณเคยหาไว้ใน mul.py (DAT_CONTROLLED_UNIT)
controlled_unit_addr = base_addr + (0x09394248 - 0x400000)
my_unit_raw = scanner.read_mem(controlled_unit_addr, 8)
my_unit = struct.unpack("<Q", my_unit_raw)[0] if my_unit_raw else 0

print(f"[*] รถถังของเรา (My Unit): {hex(my_unit)}")
print(f"[*] พบ Unit ในแมพทั้งหมด: {len(units)} ตัว\n")

print("-" * 60)
print(f"{'Unit Ptr':<18} | {'Unit Name (รุ่นรถถัง)':<30}")
print("-" * 60)

for u_ptr in units:
    # ---------------------------------------------------------
    # 1. 🏷️ ค้นหาชื่อรุ่นรถถัง (Unit ID / Family)
    # ---------------------------------------------------------
    unit_name = "UNKNOWN"
    
    # ปกติชื่อรุ่นจะอยู่ใน UnitInfo ซึ่งมักจะโดนชี้ไปจาก Offset ช่วง 0x0 ถึง 0x200
    for off in range(0x0, 0x200, 8):
        ptr_raw = scanner.read_mem(u_ptr + off, 8)
        if not ptr_raw: continue
        info_ptr = struct.unpack("<Q", ptr_raw)[0]
        
        if is_valid_ptr(info_ptr):
            # ลองอ่าน String ภายใน UnitInfo
            str_data = scanner.read_mem(info_ptr, 64)
            if str_data:
                try:
                    # เกมมักจะขึ้นต้นชื่อด้วยหมวดหมู่ เช่น uk_, us_, germ_, ussr_, tank_, aircraft_
                    decoded = str_data.decode('utf-8', errors='ignore')
                    if any(prefix in decoded for prefix in ["us_", "germ_", "ussr_", "uk_", "jp_", "cn_", "it_", "fr_", "sw_", "il_", "dummy"]):
                        # ตัดเอาเฉพาะคำแรกก่อนเจออักขระขยะ
                        unit_name = decoded.split('\x00')[0]
                        break
                except: pass
                
    # ---------------------------------------------------------
    # 2. 🕵️‍♂️ สแกนหาความแตกต่างของ Team / Status
    # ---------------------------------------------------------
    # เราจะอ่าน Memory 1024 bytes แรกของรถแต่ละคันมาเปรียบเทียบ
    # (แนะนำให้ท่านดูด้วยตาว่า Offset ไหนที่มีค่าเป็น 1 (ทีมเรา) และ 2 (ทีมศัตรู))
    marker = "🟢 [ME]  " if u_ptr == my_unit else "🔴 [ENEMY?]"
    print(f"{marker} {hex(u_ptr):<10} | {unit_name}")

print("-" * 60)
print("\n[💡 ทริคสำหรับการแยกทีมและสถานะ]")
print("1. ถ้าชื่อขึ้นต้นด้วย 'dummy' หรือ 'structures' แปลว่ามันคือเป้าซ้อมยิงโง่ๆ หรือสิ่งปลูกสร้าง")
print("2. ถ้าชื่อเป็น 'f_16' หรือ 'bf_109' แปลว่าเป็นเครื่องบิน")