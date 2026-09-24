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

from src.utils.scanner import (
    MemoryScanner,
    get_game_pid,
    get_game_base_address,
    init_dynamic_offsets,
    _get_binary_fingerprint,
    _can_overwrite_persistence,
    BARREL_PERSISTENCE_PATH,
)
import src.utils.mul as mul

def _write_barrel_persistence(animchar_off, bone_tree_off, sub_off, wtm_off, bone_idx, bone_name, breech_idx=-1, muzzle_idx=-1, is_launcher=False, confidence=0.99):
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
        "breech_idx": int(breech_idx if breech_idx != -1 else bone_idx),
        "muzzle_idx": int(muzzle_idx if muzzle_idx != -1 else bone_idx),
        "is_launcher": bool(is_launcher),
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
    print(f"    animchar_off={hex(animchar_off)} wtm_off={hex(wtm_off)} breech={breech_idx} muzzle={muzzle_idx} (conf: {confidence:.2f})")
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

    my_unit, _ = mul.get_local_team(scanner, base)
    if not my_unit:
        print("[-] ไม่พบ My Unit ในหน่วยความจำ")
        return None

    print(f"[+] สแกน My Unit: {hex(my_unit)}")

    best_score = -1
    best_info = None

    # 1. 🎯 แม่นยำสูงสุด: Geometric Bind Pose (0x208) vs Animated Pose (0x250)
    raw_t208 = scanner.read_mem(my_unit + 0x208, 8)
    raw_t250 = scanner.read_mem(my_unit + 0x250, 8)
    t208 = struct.unpack("<Q", raw_t208)[0] if raw_t208 else 0
    t250 = struct.unpack("<Q", raw_t250)[0] if raw_t250 else 0
    if mul.is_valid_ptr(t208) and mul.is_valid_ptr(t250):
        cnt_raw = scanner.read_mem(t208 + 0x10, 2)
        cnt208 = struct.unpack("<H", cnt_raw)[0] if cnt_raw and len(cnt_raw) == 2 else 0
        if 0 < cnt208 < 1000:
            raw_mats = scanner.read_mem(t208 + 0x30, cnt208 * 64)
            if raw_mats and len(raw_mats) == cnt208 * 64:
                bmin_data = scanner.read_mem(my_unit + mul.OFF_UNIT_BBMIN, 12) if mul.OFF_UNIT_BBMIN else None
                bmax_data = scanner.read_mem(my_unit + mul.OFF_UNIT_BBMAX, 12) if mul.OFF_UNIT_BBMAX else None
                if bmin_data and bmax_data and len(bmin_data) == 12 and len(bmax_data) == 12:
                    bmin = struct.unpack("<fff", bmin_data)
                    bmax = struct.unpack("<fff", bmax_data)
                    y_turret_min = bmin[1] + (bmax[1] - bmin[1]) * 0.48
                    y_max = bmax[1] + 0.6
                    z_max = max(1.0, abs(bmax[2]) * 0.70)
                else:
                    y_turret_min, y_max = 1.0, 4.0
                    z_max = 1.4

                candidates = []
                for b in range(cnt208):
                    m_data = raw_mats[b*64:(b+1)*64]
                    r0 = struct.unpack_from("<ffff", m_data, 0x00)
                    r1 = struct.unpack_from("<ffff", m_data, 0x10)
                    r3 = struct.unpack_from("<ffff", m_data, 0x30)
                    bx, by, bz = r3[0], r3[1], r3[2]
                    d_fwd = (r0[0]-1.0)**2 + r0[1]**2 + r0[2]**2
                    if d_fwd < 0.04 and y_turret_min <= by <= y_max and abs(bz) <= z_max and bx > -0.6:
                        candidates.append((bx, by, bz, b))

                breech_idx = -1
                muzzle_idx = -1
                is_launcher = False

                if candidates:
                    candidates.sort(key=lambda x: x[0], reverse=True)

                    # 1a. ตรวจหา Cannon Barrel มาตรฐาน (ปลายกระบอกยื่นไปใกล้/เกินหน้ารถ และยาว >= 0.85m)
                    for cand in candidates:
                        mx_b, my_b, mz_b, m_idx = cand
                        front_limit = (bmax[0] - 0.6) if bmax_data else 1.5
                        if mx_b >= front_limit:
                            collinear = [c for c in candidates if abs(c[1] - my_b) < 0.08 and abs(c[2] - mz_b) < 0.08 and c[0] <= mx_b]
                            if len(collinear) < 2:
                                collinear = [c for c in candidates if abs(c[1] - my_b) < 0.12 and abs(c[2] - mz_b) < 0.12 and c[0] <= mx_b]
                            if collinear:
                                collinear.sort(key=lambda x: x[0])
                                b_cand = collinear[0]
                                c_len = math.sqrt((mx_b - b_cand[0])**2 + (my_b - b_cand[1])**2 + (mz_b - b_cand[2])**2)
                                if c_len >= 0.85:
                                    breech_idx = b_cand[3]
                                    muzzle_idx = m_idx
                                    is_launcher = False
                                    break

                    # 1b. ตรวจหา ATGM / Rocket Launcher สำหรับรถถังมิสไซล์ (เช่น IT-1, M901)
                    if breech_idx == -1 and bmin_data and bmax_data:
                        upper_turret_min = bmin[1] + (bmax[1] - bmin[1]) * 0.65
                        launcher_cands = [c for c in candidates if c[1] >= upper_turret_min and abs(c[2]) < abs(bmax[2]) * 0.70]
                        if launcher_cands:
                            launcher_cands.sort(key=lambda c: (c[1], c[0]), reverse=True)
                            for cand in launcher_cands:
                                mx_b, my_b, mz_b, m_idx = cand
                                collinear = [c for c in launcher_cands if abs(c[1] - my_b) < 0.10 and abs(c[2] - mz_b) < 0.10]
                                if len(collinear) >= 2:
                                    collinear.sort(key=lambda x: x[0])
                                    breech_idx = collinear[0][3]
                                    muzzle_idx = collinear[-1][3]
                                    is_launcher = True
                                    break
                            if breech_idx == -1:
                                top = launcher_cands[0]
                                breech_idx = top[3]
                                muzzle_idx = top[3]
                                is_launcher = True

                if breech_idx != -1 and muzzle_idx != -1:
                    anim_wtm = t250 + 0x30
                    b_bytes = scanner.read_mem(anim_wtm + breech_idx * 64, 64)
                    m_bytes = scanner.read_mem(anim_wtm + muzzle_idx * 64, 64)
                    if b_bytes and m_bytes and len(b_bytes) == 64 and len(m_bytes) == 64:
                        bx, by, bz = struct.unpack_from("<fff", b_bytes, 0x30)
                        mx, my, mz = struct.unpack_from("<fff", m_bytes, 0x30)
                        fx, fy, fz = struct.unpack_from("<fff", m_bytes, 0x00)
                        if is_launcher:
                            mx = bx + fx * 4.0
                            my = by + fy * 4.0
                            mz = bz + fz * 4.0
                            barrel_len = 4.0
                            bone_name_str = "geometric_atgm_launcher"
                        else:
                            barrel_len = math.sqrt((mx-bx)**2 + (my-by)**2 + (mz-bz)**2)
                            if breech_idx == muzzle_idx or barrel_len < 0.5:
                                bx, by, bz = mx - fx * 2.5, my - fy * 2.5, mz - fz * 2.5
                                barrel_len = 2.5
                            bone_name_str = "geometric_gun_barrel"
                        best_info = {
                            "animchar_off": 0x250,
                            "bone_tree_off": 0x208,
                            "sub_off": 0x30,
                            "wtm_off": 0x30,
                            "bone_idx": muzzle_idx,
                            "breech_idx": breech_idx,
                            "muzzle_idx": muzzle_idx,
                            "is_launcher": is_launcher,
                            "bone_name": bone_name_str,
                            "pos": (mx, my, mz),
                            "breech_pos": (bx, by, bz),
                            "forward": (fx, fy, fz),
                            "length": barrel_len,
                            "confidence": 0.99,
                        }

    # 2. ตรวจสอบ Fallback Dagor GeomNodeTree แบบ String Search
    if not best_info:
        for cand_off in [0x250, 0x208]:
            raw_cand = scanner.read_mem(my_unit + cand_off, 8)
            if not raw_cand: continue
            tree_cand = struct.unpack("<Q", raw_cand)[0]
            if not mul.is_valid_ptr(tree_cand): continue
            cnt_raw = scanner.read_mem(tree_cand + 0x10, 2)
            cnt = struct.unpack("<H", cnt_raw)[0] if cnt_raw and len(cnt_raw) == 2 else 0
            if not (0 < cnt < 1000): continue
            w_ptr_cand = tree_cand + 0x30
            min_off = 0x30 + cnt * 64
            block_size = min(0x18000, min_off + 0x8000)
            raw_tree = scanner.read_mem(tree_cand, block_size)
            if not raw_tree: continue
            s_idx_found = raw_tree.find(b"root\x00")
            if s_idx_found == -1:
                s_idx_found = raw_tree.find(b"\x00root\x00")
                if s_idx_found != -1:
                    s_idx_found += 1
            if s_idx_found != -1:
                strings = raw_tree[s_idx_found:].split(b"\x00")
                for s_idx in range(min(cnt, len(strings))):
                    try:
                        s_str = strings[s_idx].decode("utf-8", errors="ignore").lower().strip()
                        if not s_str: continue
                        score = -1
                        if "bone_gun_barrel" in s_str: score = 100
                        elif "gun_barrel" in s_str and not s_str.endswith("_dm"): score = 80
                        elif s_str == "bone_gun": score = 70
                        elif "bone_gun" in s_str: score = 60
                        elif "barrel" in s_str and not s_str.endswith("_dm"): score = 40
                        elif any(k in s_str for k in ["rocket_launcher", "launcher_dm", "missile_rail"]): score = 35
                        if any(b in s_str for b in ["mg", "machine", "smoke", "fuel", "water", "camera", "optic", "antenna", "suspension", "wheel", "track", "root", "roller", "drive", "ammo", "cls_"]):
                            score = -100
                        if score > best_score:
                            m_bytes = scanner.read_mem(w_ptr_cand + s_idx * 64, 64)
                            if m_bytes and len(m_bytes) == 64:
                                fx, fy, fz = struct.unpack_from("<fff", m_bytes, 0x00)
                                bx, by, bz = struct.unpack_from("<fff", m_bytes, 0x30)
                                fl = (fx*fx + fy*fy + fz*fz) ** 0.5
                                if 0.5 < fl < 2.0 and (abs(bx) > 0.05 or abs(by) > 0.05 or abs(bz) > 0.05):
                                    best_score = score
                                    best_info = {
                                        "animchar_off": cand_off,
                                        "bone_tree_off": cand_off,
                                        "sub_off": s_idx_found,
                                        "wtm_off": 0x30,
                                        "bone_idx": s_idx,
                                        "breech_idx": s_idx,
                                        "muzzle_idx": s_idx,
                                        "bone_name": s_str,
                                        "pos": (bx, by, bz),
                                        "breech_pos": (bx, by, bz),
                                        "forward": (fx, fy, fz),
                                        "length": 6.0,
                                        "confidence": 0.85,
                                    }
                    except Exception:
                        pass
                if best_info and cand_off == 0x250 and best_score >= 100:
                    break

    # 2. Fallback สแกนหา AnimChar / Bone Tree Offset แบบเดิม
    if not best_info:
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
                            for wtm_off in [0x00]:
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
        print(f"  Breech Node   : {best_info.get('breech_idx', best_info['bone_idx'])}")
        print(f"  Muzzle Node   : {best_info.get('muzzle_idx', best_info['bone_idx'])}")
        print(f"  AnimChar Off  : {hex(best_info['animchar_off'])}")
        print(f"  WTM Array Off : {hex(best_info['wtm_off'])}")
        print(f"  Barrel Length : {best_info.get('length', 0.0):.2f}m")
        print(f"  Local Muzzle  : {best_info['pos']}")
        print(f"  Local Breech  : {best_info.get('breech_pos', best_info['pos'])}")
        print(f"  Forward Vector: {best_info['forward']}")

        if write_persistence:
            _write_barrel_persistence(
                animchar_off=best_info["animchar_off"],
                bone_tree_off=best_info["bone_tree_off"],
                sub_off=best_info["sub_off"],
                wtm_off=best_info["wtm_off"],
                bone_idx=best_info["bone_idx"],
                bone_name=best_info["bone_name"],
                breech_idx=best_info.get("breech_idx", -1),
                muzzle_idx=best_info.get("muzzle_idx", -1),
                is_launcher=best_info.get("is_launcher", False),
                confidence=best_info.get("confidence", 0.99)
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
