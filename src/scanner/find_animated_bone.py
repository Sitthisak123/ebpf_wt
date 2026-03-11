import sys
import time
import struct
import math
from main import MemoryScanner, get_game_pid, get_game_base_address
from src.untils.mul import get_cgame_base, get_all_units

def is_valid_ptr(p): return 0x10000000000 < p < 0x7FFFFFFFFFFF

print("[*] 🕵️‍♂️ เริ่มปฏิบัติการ The Matrix Hunter V.2 (ค้นหาแบบยืดหยุ่น)...")
pid = get_game_pid()
scanner = MemoryScanner(pid)
cgame_base = get_cgame_base(scanner, get_game_base_address(pid))
units = get_all_units(scanner, cgame_base)

if not units:
    print("[-] ไม่พบรถถัง (กรุณาเข้าโหมด Test Drive)")
    sys.exit()

u_ptr = units[0]
print(f"[*] ตรวจสอบรถถัง: {hex(u_ptr)}")

target_idx = -1
target_name = ""

# 1. หา Index ของปืนแบบ "ยืดหยุ่นสุดๆ"
for offset in range(0x10, 0x1500, 8):
    raw_ptr = scanner.read_mem(u_ptr + offset, 8)
    if not raw_ptr: continue
    tree_ptr = struct.unpack("<Q", raw_ptr)[0]
    if not is_valid_ptr(tree_ptr): continue
    
    name_raw = scanner.read_mem(tree_ptr + 0x40, 8)
    if not name_raw: continue
    name_ptr = struct.unpack("<Q", name_raw)[0]
    
    if is_valid_ptr(name_ptr):
        names_block = scanner.read_mem(name_ptr, 0x4000)
        if names_block and b"barrel" in names_block.lower():
            for i in range(400):
                try:
                    str_offset = struct.unpack_from("<H", names_block, i * 2)[0]
                    if str_offset == 0 or str_offset >= len(names_block): continue
                    end_idx = names_block.find(b'\x00', str_offset)
                    if end_idx != -1:
                        bone_name = names_block[str_offset:end_idx].decode('utf-8', errors='ignore').strip().lower()
                        # กรองถังน้ำมันทิ้ง เอาแค่ปืน
                        bad_words = ["fuel", "water", "smoke", "mg", "machine", "camera", "optic", "antenna", "gunner", "track", "wheel", "suspension"]
                        if "barrel" in bone_name and not any(bad in bone_name for bad in bad_words):
                            target_idx = i
                            target_name = bone_name
                            print(f"[+] BINGO! เจอ Index ปืนแล้ว: {i} (ชื่อ '{bone_name}' ที่ Offset {hex(offset)})")
                            break
                except: pass
    if target_idx != -1: break

if target_idx == -1:
    print("[-] หา Index ปืนไม่เจอ! (ลองเปลี่ยนคันรถถังดูครับ เช่น รถถังหลักธรรมดา)")
    sys.exit()

print("\n[!] ห้ามขยับเมาส์! กำลังสแกนหา Matrix ทั้งหมดในตัวรถ...")
candidates = {}

# ดึง pointer ชั้นที่ 1 (ตัวรถ)
for off in range(0x10, 0x2000, 8):
    p_raw = scanner.read_mem(u_ptr + off, 8)
    if not p_raw: continue
    ptr = struct.unpack("<Q", p_raw)[0]
    if is_valid_ptr(ptr):
        mat_raw = scanner.read_mem(ptr + (target_idx * 64), 64)
        if mat_raw and len(mat_raw) == 64:
            candidates[f"Offset 1 ชั้น: {hex(off)}"] = {'ptr': ptr, 'mat': mat_raw}

# ดึง pointer ชั้นที่ 2 (AnimChar)
for off in range(0x10, 0x1500, 8):
    p_raw = scanner.read_mem(u_ptr + off, 8)
    if not p_raw: continue
    ptr1 = struct.unpack("<Q", p_raw)[0]
    if is_valid_ptr(ptr1):
        for sub_off in range(0x0, 0x100, 8):
            p2_raw = scanner.read_mem(ptr1 + sub_off, 8)
            if p2_raw:
                ptr2 = struct.unpack("<Q", p2_raw)[0]
                if is_valid_ptr(ptr2):
                    mat_raw = scanner.read_mem(ptr2 + (target_idx * 64), 64)
                    if mat_raw and len(mat_raw) == 64:
                        candidates[f"Offset 2 ชั้น: {hex(off)} -> {hex(sub_off)}"] = {'ptr': ptr2, 'mat': mat_raw}

time.sleep(1)
print(f"\n[🎯] >>> ขยับเมาส์หันป้อมปืน (ซ้าย-ขวา / ขึ้น-ลง) รัวๆ เลยครับ! <<< (มีเวลา 3 วินาที)")
time.sleep(3)

print("[!] กำลังตรวจสอบการขยับ...")
found_any = False
for name, data in candidates.items():
    new_mat = scanner.read_mem(data['ptr'] + (target_idx * 64), 64)
    if new_mat and len(new_mat) == 64:
        old_fx = struct.unpack_from("<f", data['mat'], 0x00)[0]
        new_fx = struct.unpack_from("<f", new_mat, 0x00)[0]
        
        if math.isfinite(old_fx) and math.isfinite(new_fx):
            if abs(old_fx - new_fx) > 0.01:
                print(f"  👉 [🔥 ขุมทรัพย์ WTM] เจอ Matrix ปืนขยับได้ที่: {name}")
                found_any = True

if not found_any:
    print("[-] ไม่เจอ Matrix ที่ขยับเลย (ลองขยับเมาส์ให้เยอะกว่าเดิมครับ)")