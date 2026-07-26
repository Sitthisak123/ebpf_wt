import os
import sys
import struct
import math
import json
import argparse
import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets, _get_binary_fingerprint, _can_overwrite_persistence

def _write_barrel_persistence(animchar_off, bone_tree_off, sub_off, wtm_off, bone_idx, bone_name, confidence=0.95):
    """บันทึกค่า Barrel Offset ลง persistence พร้อม build fingerprint และนโยบาย Rate Overwrite ตาม Confidence"""
    if not _can_overwrite_persistence(BARREL_PERSISTENCE_PATH, confidence):
        print(f"  [*] ข้ามการบันทึก Barrel Persistence: ไฟล์เดิมมีค่า confidence สูงกว่า {confidence:.2f}")
        return None

    payload = {
        "updated_at": datetime.datetime.now().isoformat(),
        "animchar_off": int(animchar_off),
        "bone_tree_off": int(bone_tree_off),
        "sub_off": int(sub_off),
        "wtm_off": int(wtm_off),
        "bone_idx": int(bone_idx),
        "bone_name": str(bone_name),
        "row0_forward_offset": 0x00,
        "row3_position_offset": 0x30,
        "source": "barrel_offset_dumper",
        "updated_by_tool": "tools/barrel_offset_dumper.py",
        "confidence": float(confidence),
        "build_fingerprint": _get_binary_fingerprint(),
    }
    os.makedirs(os.path.dirname(BARREL_PERSISTENCE_PATH), exist_ok=True)
    with open(BARREL_PERSISTENCE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"\n[+] บันทึก Barrel Persistence สำเร็จ: {BARREL_PERSISTENCE_PATH}")
    print(f"    animchar_off={hex(animchar_off)} sub_off={hex(sub_off)} wtm_off={hex(wtm_off)} idx={bone_idx} name='{bone_name}' (conf: {confidence:.2f})")
    return BARREL_PERSISTENCE_PATH



def dump_barrel_offset(write_persistence=True):
    """สแกนและยืนยัน Offset สำหรับ Barrel และ AnimChar Matrix"""
    pid = get_game_pid()
    if not pid:
        print("[-] ไม่พบโปรเซสเกม War Thunder")
        return None

    base = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base)

    cgame = mul.get_cgame_base(scanner, base)
    if not cgame:
        print("[-] ไม่สามารถดึง CGame Base ได้")
        return None

    my_unit = mul.get_my_unit(scanner, base)
    if not my_unit:
        print("[-] ไม่พบ My Unit ในหน่วยความจำ")
        return None

    print(f"[+] สแกน My Unit: {hex(my_unit)}")

    best_score = -1
    best_info = None

    # สแกนหา AnimChar / Bone Tree Offset จาก My Unit
    for off in [0x238, 0x1F0, 0x1FD8, 0x2E20, 0x2F38, 0x1E8, 0x1E0, 0x1D8, 0x200, 0x210, 0x228, 0x1C8, 0x3E8, 0x400, 0x13B0]:
        raw_ptr = scanner.read_mem(my_unit + off, 8)
        if not raw_ptr: continue
        tree_ptr = struct.unpack("<Q", raw_ptr)[0]
        if not mul.is_valid_ptr(tree_ptr): continue

        for sub_off in [0x40, 0x20, 0xB0]:
            raw_name = scanner.read_mem(tree_ptr + sub_off, 8)
            if not raw_name: continue
            name_ptr = struct.unpack("<Q", raw_name)[0]
            if not mul.is_valid_ptr(name_ptr): continue
            names_block = scanner.read_mem(name_ptr, 0x4000)
            if not names_block: continue

            for i in range(400):
                try:
                    str_offset = struct.unpack_from("<H", names_block, i * 2)[0]
                    if str_offset == 0 or str_offset >= len(names_block): continue
                    end_idx = names_block.find(b'\x00', str_offset)
                    if end_idx == -1: continue
                    bone_name = names_block[str_offset:end_idx].decode('utf-8', errors='ignore').lower().strip()
                    
                    score = -1
                    if "bone_gun_barrel" in bone_name: score = 100
                    elif "gun_barrel" in bone_name: score = 80
                    elif "bone_gun" in bone_name and bone_name == "bone_gun": score = 70
                    elif "bone_gun" in bone_name: score = 60
                    elif "barrel" in bone_name: score = 40
                    if any(b in bone_name for b in ["mg", "machine", "smoke", "fuel", "water", "camera", "optic", "antenna", "suspension", "wheel", "track", "root"]):
                        score = -100

                    if score > best_score:
                        for wtm_off in [0x00, 0x10]:
                            wtm_base_raw = scanner.read_mem(tree_ptr + wtm_off, 8)
                            if not wtm_base_raw: continue
                            w_ptr = struct.unpack("<Q", wtm_base_raw)[0]
                            if not mul.is_valid_ptr(w_ptr): continue
                            
                            matrix_data = scanner.read_mem(w_ptr + (i * 64), 64)
                            if matrix_data and len(matrix_data) == 64:
                                fx, fy, fz = struct.unpack_from("<fff", matrix_data, 0x00)
                                bx, by, bz = struct.unpack_from("<fff", matrix_data, 0x30)
                                f_len = (fx*fx + fy*fy + fz*fz) ** 0.5
                                if math.isfinite(bx) and math.isfinite(fx) and (0.5 < f_len < 2.0):
                                    best_score = score
                                    best_info = {
                                        "animchar_off": off,
                                        "bone_tree_off": off,
                                        "sub_off": sub_off,
                                        "wtm_off": wtm_off,
                                        "bone_idx": i,
                                        "bone_name": bone_name,
                                        "pos": (bx, by, bz),
                                        "forward": (fx, fy, fz),
                                    }
                except:
                    pass

    if best_info:
        print("\n==================================================")
        print(" 🎯 BARREL OFFSET & ANIMCHAR MATRIX DUMP")
        print("==================================================")
        print(f"  Bone Name     : {best_info['bone_name']}")
        print(f"  Bone Index    : {best_info['bone_idx']}")
        print(f"  AnimChar Off  : {hex(best_info['animchar_off'])}")
        print(f"  Sub Name Off  : {hex(best_info['sub_off'])}")
        print(f"  WTM Array Off : {hex(best_info['wtm_off'])}")
        print(f"  Local Pos     : {best_info['pos']}")
        print(f"  Forward Vector: {best_info['forward']}")

        if write_persistence:
            _write_barrel_persistence(
                animchar_off=best_info["animchar_off"],
                bone_tree_off=best_info["bone_tree_off"],
                sub_off=best_info["sub_off"],
                wtm_off=best_info["wtm_off"],
                bone_idx=best_info["bone_idx"],
                bone_name=best_info["bone_name"],
                confidence=0.95
            )
        return best_info
    else:
        print("[-] ไม่สามารถระบุ Barrel Bone Matrix ได้")
        return None


def main():
    parser = argparse.ArgumentParser(description="War Thunder Barrel Offset & Matrix Dumper")
    parser.add_argument("--write-persistence", action="store_true", default=True, help="บันทึกผลลัพธ์ลง config/barrel_offset_persistence.json")
    parser.add_argument("--no-write", action="store_false", dest="write_persistence", help="ไม่ต้องบันทึกผลลัพธ์ลงไฟล์ persistence")
    args = parser.parse_args()

    dump_barrel_offset(write_persistence=args.write_persistence)


if __name__ == "__main__":
    main()
