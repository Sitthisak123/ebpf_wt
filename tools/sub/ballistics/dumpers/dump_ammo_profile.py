#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🎯 War Thunder Ammo Classifier & Ballistics Profile Dumper
===========================================================
เครื่องมือสำหรับดัมพ์ข้อมูลขีปนวิถี (Ballistics Profile) และข้อมูลรถถัง/เครื่องบิน (Unit Info)
จาก Live Memory ของเกม War Thunder (aces) เพื่อตรวจสอบความแม่นยำของการจำแนกประเภทกระสุน
(Ammo Classifier: APFSDS, APDS, APHE, HESH, HEAT-FS, HE, ATGM) พร้อมบันทึกผลลง JSON Dataset
สำหรับการปรับแต่งและ Fine-tuning อัลกอริทึม
"""

import sys
import os
import time
import json
import struct
import math
import argparse
from datetime import datetime

# 🔍 ค้นหา Root Directory ของโปรเจกต์แบบ Dynamic
current_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = None
while current_dir and current_dir != "/":
    if os.path.exists(os.path.join(current_dir, "radar_overlay.py")):
        PROJECT_ROOT = current_dir
        break
    current_dir = os.path.dirname(current_dir)

if not PROJECT_ROOT:
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import (
    MemoryScanner,
    get_game_pid,
    get_game_base_address,
    init_dynamic_offsets,
)
import src.utils.mul as mul
from src.utils.ammo_family import (
    classify_weapon_caliber,
    extract_cannon_size,
    AMMO_FLAG_APFSDS,
    AMMO_FLAG_APDS,
    AMMO_FLAG_HEATFS,
    AMMO_FLAG_APHE,
    AMMO_FLAG_HE,
    AMMO_FLAG_HESH,
    AMMO_FLAG_ATGM,
    AMMO_FLAG_AUTOCANNON,
)
from radar_overlay import OFF_WEAPON_PTR

DEFAULT_DUMP_FILE = os.path.join(PROJECT_ROOT, "dumps", "ammo_classification_records.json")

AMMO_MENU = [
    ("APFSDS", "Armour-Piercing Fin-Stabilized Discarding Sabot (ลูกดอกเจาะเกราะสลัดครอบทรงตัวด้วยครีบ)"),
    ("APDS",   "Armour-Piercing Discarding Sabot (ลูกเจาะเกราะสลัดครอบแกนสั้น)"),
    ("APHE",   "Armour-Piercing High-Explosive / Solid AP (ลูกเจาะเกราะหัวระเบิด/หัวตัน)"),
    ("HESH",   "High-Explosive Squash Head / HEP (ลูกหัวบด)"),
    ("HEAT-FS","High-Explosive Anti-Tank (หัวระเบิดแรงสูงต่อสู้รถถังทรงตัวด้วยครีบ)"),
    ("HE",     "High-Explosive Fragmentation (ลูกระเบิดแรงสูงแตกสะเก็ด)"),
    ("ATGM",   "Anti-Tank Guided Missile (อาวุธปล่อยนำวิถีต่อสู้รถถัง)"),
    ("AUTO-AP","Autocannon Kinetic / AP / APDS (กระสุนปืนกลหนัก/ปืนกลลำกล้อง)"),
    ("OTHER",  "Other / Custom Type (ประเภทอื่นๆ หรือผสม)"),
]


def ensure_interactive_stdin():
    """
    หากรันผ่าน `echo password | sudo -S ...` ท่อ stdin จะถูกปิดหลัง sudo อ่านรหัสผ่าน
    ฟังก์ชันนี้จะเชื่อมต่อ stdin กลับไปยัง /dev/tty (แป้นพิมพ์ของผู้ใช้) เพื่อให้ input() รอรับค่าได้ตามปกติ
    """
    if not sys.stdin.isatty():
        try:
            sys.stdin = open("/dev/tty", "r")
            return True
        except Exception:
            return False
    return True


def read_float(scanner, addr):
    try:
        raw = scanner.read_mem(addr, 4)
        if raw and len(raw) == 4:
            val = struct.unpack("<f", raw)[0]
            return val if math.isfinite(val) else 0.0
    except Exception:
        pass
    return 0.0


def read_u32(scanner, addr):
    try:
        raw = scanner.read_mem(addr, 4)
        if raw and len(raw) == 4:
            return struct.unpack("<I", raw)[0]
    except Exception:
        pass
    return 0


def fetch_live_profile(scanner, base_addr, cgame_base):
    """
    ดึงข้อมูล Unit ปัจจุบัน และ Ballistics Profile ของกระสุนในรังเพลิงจาก Live Memory
    """
    my_unit, my_team = mul.get_local_team(scanner, base_addr)
    weapon_ptr = mul._read_ptr(scanner, cgame_base + OFF_WEAPON_PTR)

    # ดึงข้อมูล DNA ของรถถัง
    dna = mul.get_unit_detailed_dna(scanner, my_unit) if my_unit else {}
    short_name = dna.get("short_name", "") if dna else ""
    name_key = dna.get("name_key", "") if dna else ""
    family = dna.get("family", "") if dna else ""
    nation_id = dna.get("nation_id", -1) if dna else -1
    class_id = dna.get("class_id", -1) if dna else -1

    # ดึงค่าพารามิเตอร์ขีปนวิถีจาก weapon_ptr
    speed = read_float(scanner, weapon_ptr + 0x20E8)
    mass = read_float(scanner, weapon_ptr + 0x20F4)
    caliber = read_float(scanner, weapon_ptr + 0x20F8)
    length_cx = read_float(scanner, weapon_ptr + 0x20FC)
    max_dist = read_float(scanner, weapon_ptr + 0x2100)
    splinter_x = read_float(scanner, weapon_ptr + 0x210C)
    splinter_y = read_float(scanner, weapon_ptr + 0x2110)
    vel_range_x = read_float(scanner, weapon_ptr + 0x2114)
    vel_range_y = read_float(scanner, weapon_ptr + 0x2118)

    # Derived physics features
    raw_cal_mm = caliber * 1000.0
    aspect_ratio = (length_cx / caliber) if caliber > 0.0 else 0.0
    vol_density = (mass / (caliber ** 3)) if caliber > 0.0 else 0.0
    sec_density = (mass / (caliber ** 2)) if caliber > 0.0 else 0.0

    is_air = "air" in family.lower() or "plane" in family.lower()

    # ทำการจำแนกด้วย Classifier ปัจจุบัน
    predicted = classify_weapon_caliber(
        speed=speed,
        caliber=caliber,
        mass=mass,
        cx=length_cx,
        vehicle_name=short_name or name_key,
        is_air=is_air,
        length=length_cx,
    )

    return {
        "timestamp": datetime.now().isoformat(),
        "ptrs": {
            "cgame_base": hex(cgame_base),
            "my_unit": hex(my_unit),
            "weapon_ptr": hex(weapon_ptr),
        },
        "vehicle": {
            "short_name": short_name,
            "name_key": name_key,
            "family": family,
            "nation_id": nation_id,
            "class_id": class_id,
            "my_team": my_team,
            "is_air": is_air,
        },
        "raw_ballistics": {
            "speed": round(speed, 3),
            "mass": round(mass, 5),
            "caliber": round(caliber, 6),
            "length_cx": round(length_cx, 5),
            "max_distance": round(max_dist, 2),
            "splinter_mass_x": round(splinter_x, 5),
            "splinter_mass_y": round(splinter_y, 5),
            "vel_range_x": round(vel_range_x, 2),
            "vel_range_y": round(vel_range_y, 2),
        },
        "derived": {
            "raw_caliber_mm": round(raw_cal_mm, 2),
            "aspect_ratio_ld": round(aspect_ratio, 2),
            "volumetric_density": round(vol_density, 2),
            "sectional_density": round(sec_density, 2),
        },
        "predicted": predicted,
    }


def print_profile_dashboard(profile):
    v = profile["vehicle"]
    b = profile["raw_ballistics"]
    d = profile["derived"]
    p = profile["predicted"]
    ptrs = profile["ptrs"]

    print("\n" + "=" * 76)
    print("🎯  WAR THUNDER AMMO & BALLISTICS PROFILE DUMPER")
    print("=" * 76)
    print(f"🚗 ข้อมูลยูนิต (Vehicle Info):")
    print(f"   • Short Name     : \033[92m{v['short_name'] or 'UNKNOWN'}\033[0m")
    print(f"   • Name Key       : {v['name_key'] or 'UNKNOWN'}")
    print(f"   • Vehicle Family : {v['family']} | Team: {v['my_team']} | Is Air: {v['is_air']}")
    print(f"   • Pointers       : MyUnit={ptrs['my_unit']} | Weapon={ptrs['weapon_ptr']}")

    print(f"\n💥 ค่าขีปนวิถีในหน่วยความจำ (Raw Ballistics Profile):")
    print(f"   • ความเร็วต้น (Speed)      : \033[96m{b['speed']:.1f} m/s\033[0m")
    print(f"   • น้ำหนักหัวกระสุน (Mass)   : \033[96m{b['mass']:.4f} kg ({b['mass']*1000.0:.1f} g)\033[0m")
    print(f"   • คาลิเบอร์ในเกม (Caliber) : \033[96m{b['caliber']:.5f} m ({d['raw_caliber_mm']:.1f} mm)\033[0m")
    print(f"   • ความยาว/Cx (Length/Cx)   : {b['length_cx']:.4f} m")
    print(f"   • ระยะหวังผลสูงสุด (MaxDist): {b['max_distance']:.1f} m")
    print(f"   • สะเก็ด (Splinter Mass)  : X={b['splinter_mass_x']:.4f} kg | Y={b['splinter_mass_y']:.4f} kg")
    print(f"   • ย่านความเร็ว (Vel Range)  : X={b['vel_range_x']:.1f} m/s | Y={b['vel_range_y']:.1f} m/s")

    print(f"\n🔬 ตัวชี้วัดทางฟิสิกส์ (Derived Physical Features):")
    aspect_hint = " (>=8.0 Long-Rod APFSDS)" if d['aspect_ratio_ld'] >= 8.0 else (" (<=6.5 APDS)" if d['aspect_ratio_ld'] <= 6.5 else "")
    print(f"   • อัตราส่วนความยาว/แกน (L/D) : \033[93m{d['aspect_ratio_ld']:.2f}\033[0m{aspect_hint}")
    print(f"   • ความหนาแน่นมวล (Vol Density): \033[93m{d['volumetric_density']:.1f} kg/m³\033[0m")
    print(f"   • ความหนาแน่นหน้าตัด (Sec Dens): {d['sectional_density']:.2f} kg/m²")

    print(f"\n🤖 ผลลัพธ์การจำแนกของระบบ (AI Prediction):")
    print(f"   • กระสุนที่ทำนาย (Ammo Type) : \033[95m{p['ammo_type']}\033[0m")
    print(f"   • ลำกล้องที่ทำนาย (Cal Class) : {p['cal_class']}")
    print(f"   • ขนาดลำกล้องจริง (Bore Size) : {p['effective_bore_mm']:.0f} mm")
    if p.get('is_subcaliber'):
        print(f"   • แกนกระสุน (Dart Caliber)   : {p.get('dart_caliber_mm', 0):.1f} mm (Sub-Caliber)")
    print(f"   • Ammo Flag Bitmask          : {hex(p['ammo_flag'])}")
    print(f"   • HUD Overlay String         : \033[94m{p['hud_str']}\033[0m")
    print("=" * 76 + "\n")


def prompt_actual_info(profile, args):
    """
    ถามผู้ใช้หรือใช้ค่าจาก Arguments สำหรับ Actual Type
    รองรับตัวเลือก [0] INHERIT เพื่อยืนยันว่าผลทำนายถูกต้องทันที
    """
    predicted_type = profile["predicted"]["ammo_type"]
    predicted_bore = profile["predicted"]["effective_bore_mm"]

    # 1. เช็คว่ามีค่าส่งผ่าน CLI หรือไม่
    if getattr(args, "inherit", False) or args.auto:
        return {
            "actual_type": predicted_type,
            "nominal_bore_mm": float(predicted_bore),
            "is_correct": True,
            "note": args.note.strip() if args.note else "Inherited predicted",
        }
    elif args.actual:
        actual_type = args.actual.upper().strip()
        actual_bore = float(args.bore) if args.bore is not None else float(predicted_bore)
        note = args.note.strip() if args.note else ""
        return {
            "actual_type": actual_type,
            "nominal_bore_mm": actual_bore,
            "is_correct": (actual_type == predicted_type),
            "note": note,
        }
    else:
        # เชื่อมต่อ /dev/tty สำหรับรับอินพุตผ่านคีย์บอร์ดเมื่อถูก pipe ด้วย sudo -S
        ensure_interactive_stdin()

        print("📌 เลือกประเภทกระสุนที่แท้จริง (Actual Ammo Class):")
        print(f"  \033[92m[0] INHERIT  : ✅ ข้อมูลถูกต้องทั้งหมด (ใช้ค่าที่ AI ทำนาย: {predicted_type} | {predicted_bore:.0f}mm)\033[0m")
        for i, (code, desc) in enumerate(AMMO_MENU, 1):
            is_pred = "  \033[92m<-- [PREDICTED]\033[0m" if code == predicted_type else ""
            print(f"  [{i}] {code:<8} : {desc}{is_pred}")

        try:
            choice = input(
                f"\n👉 กรุณาเลือกข้อ [0-{len(AMMO_MENU)}], 'i' (Inherit), หรือกด Enter เพื่อยืนยันว่าถูกต้อง [{predicted_type}]: "
            ).strip()
        except EOFError:
            print("\n⚠️ Stdin ปิดอยู่และไม่พบ TTY Keyboard ให้รับค่า กรุณาใส่แฟล็ก --inherit, --auto หรือ --actual")
            return None
        except KeyboardInterrupt:
            print("\n👋 ยกเลิกการทำงาน")
            sys.exit(0)

        # ตรวจสอบว่าเลือก Inherit หรือไม่ (กด Enter, พิมพ์ 0, i, inherit, y, yes, c, correct)
        is_inherited = False
        if not choice or choice.lower() in ("0", "i", "inherit", "y", "yes", "c", "correct"):
            is_inherited = True
            actual_type = predicted_type
            actual_bore = float(predicted_bore)
            print(f"   ↳ \033[92m✅ เลือก INHERIT: ยืนยันว่าผลทำนายถูกต้อง ({predicted_type} {predicted_bore:.0f}mm)\033[0m")
        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(AMMO_MENU):
                    actual_type = AMMO_MENU[idx][0]
                else:
                    actual_type = choice.upper()
            except ValueError:
                actual_type = choice.upper()

        # 2. ขนาดลำกล้องจริง (Bore mm)
        if is_inherited:
            actual_bore = float(predicted_bore)
        elif args.bore is not None:
            actual_bore = float(args.bore)
        else:
            try:
                bore_input = input(f"👉 กรุณาระบุขนาดลำกล้องปืนจริง (mm) [Enter = Inherit {predicted_bore:.0f}mm]: ").strip()
            except (EOFError, KeyboardInterrupt):
                bore_input = ""
            actual_bore = float(bore_input) if bore_input else float(predicted_bore)

        # 3. บันทึกเพิ่มเติม (Note)
        if args.note:
            note = args.note.strip()
        else:
            try:
                prompt_msg = (
                    "👉 บันทึกชื่อกระสุน/หมายเหตุเพิ่มเติม (Optional) [Enter = ข้าม]: "
                    if is_inherited
                    else "👉 บันทึกชื่อกระสุน/หมายเหตุ (เช่น DM33, Type 87 APFSDS, 3BM42) [Enter = ไม่มี]: "
                )
                note = input(prompt_msg).strip()
            except (EOFError, KeyboardInterrupt):
                note = ""

        is_correct = (actual_type == predicted_type)

        return {
            "actual_type": actual_type,
            "nominal_bore_mm": actual_bore,
            "is_correct": is_correct,
            "note": note,
        }


def save_record_to_json(profile, actual_info, output_path):
    """
    บันทึก Record ลงในไฟล์ JSON แบบ Append
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    record = {
        "timestamp": profile["timestamp"],
        "vehicle": profile["vehicle"],
        "raw_ballistics": profile["raw_ballistics"],
        "derived": profile["derived"],
        "predicted": profile["predicted"],
        "actual": actual_info,
    }

    records = []
    if os.path.exists(output_path):
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                records = json.load(f)
                if not isinstance(records, list):
                    records = []
        except Exception:
            records = []

    records.append(record)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    total = len(records)
    status_tag = "\033[92m[CORRECT]\033[0m" if actual_info["is_correct"] else "\033[91m[MISCLASSIFIED]\033[0m"
    print(f"\n💾 \033[92mบันทึกข้อมูลเรียบร้อยแล้ว!\033[0m สถานะ: {status_tag}")
    print(f"📁 บันทึกไปยัง: {output_path}")
    print(f"📊 รายการทั้งหมดในฐานข้อมูล: {total} records\n")


def list_records(output_path):
    """
    แสดงรายการกระสุนที่เคยบันทึกไว้ในไฟล์ JSON
    """
    if not os.path.exists(output_path):
        print(f"❌ ไม่พบไฟล์ประวัติที่ {output_path}")
        return

    with open(output_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    print("\n" + "=" * 80)
    print(f"📋 รายการ Ballistics Profile ที่บันทึกไว้ ({len(records)} รายการ)")
    print("=" * 80)
    print(f"{'#':<3} | {'Vehicle':<18} | {'Speed':<8} | {'Pred':<8} | {'Actual':<8} | {'Match':<5} | {'Note'}")
    print("-" * 80)
    for i, r in enumerate(records, 1):
        v = r.get("vehicle", {}).get("short_name") or r.get("vehicle", {}).get("name_key") or "UNK"
        spd = f"{r.get('raw_ballistics', {}).get('speed', 0):.0f}m/s"
        pred = r.get("predicted", {}).get("ammo_type", "UNK")
        act = r.get("actual", {}).get("actual_type", "UNK")
        match = "✅" if r.get("actual", {}).get("is_correct") else "❌"
        note = r.get("actual", {}).get("note", "")
        print(f"{i:<3} | {v[:18]:<18} | {spd:<8} | {pred:<8} | {act:<8} | {match:<5} | {note}")
    print("=" * 80 + "\n")


def watch_mode(scanner, base_addr, cgame_base, args):
    """
    เฝ้าดูการเปลี่ยนแปลงของกระสุนแบบเรียลไทม์ (เมื่อผู้เล่นกด 1/2/3/4 เปลี่ยนกระสุนในเกม)
    """
    weapon_ptr = mul._read_ptr(scanner, cgame_base + OFF_WEAPON_PTR)
    print(f"\n👀 กำลังเข้าสู่โหมดเฝ้าดู (Watch Mode)...")
    print(f"🎮 สลับกระสุนในเกม (ปุ่ม 1, 2, 3, 4) เพื่อดูพารามิเตอร์ของกระสุนแต่ละแบบ")
    print(f"🛑 กด Ctrl+C เพื่อออกจากการเฝ้าดู\n")

    last_sig = None
    try:
        while True:
            speed = read_float(scanner, weapon_ptr + 0x20E8)
            mass = read_float(scanner, weapon_ptr + 0x20F4)
            caliber = read_float(scanner, weapon_ptr + 0x20F8)
            sig = (round(speed, 1), round(mass, 4), round(caliber, 5))

            if sig != last_sig and speed > 0.0:
                last_sig = sig
                profile = fetch_live_profile(scanner, base_addr, cgame_base)
                print_profile_dashboard(profile)

                if args.auto:
                    actual_info = prompt_actual_info(profile, args)
                    if actual_info:
                        save_record_to_json(profile, actual_info, args.file)
                else:
                    ensure_interactive_stdin()
                    try:
                        ans = input("❓ ต้องการบันทึกข้อมูลนัดนี้หรือไม่? [y/N]: ").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        ans = "n"
                    if ans == "y":
                        actual_info = prompt_actual_info(profile, args)
                        if actual_info:
                            save_record_to_json(profile, actual_info, args.file)

            time.sleep(0.5)
    except (KeyboardInterrupt, EOFError):
        print("\n👋 ออกจาก Watch Mode")


def main():
    parser = argparse.ArgumentParser(
        description="🎯 War Thunder Ammo Classifier & Ballistics Profile Dumper"
    )
    parser.add_argument("--actual", type=str, default=None,
                        help="ประเภทกระสุนจริง (เช่น APFSDS, APDS, APHE, HESH, HEAT-FS, HE, ATGM)")
    parser.add_argument("--bore", type=float, default=None,
                        help="ขนาดลำกล้องปืนจริงในหน่วย มม. (เช่น 120, 105, 88, 25)")
    parser.add_argument("--note", type=str, default=None,
                        help="บันทึกเพิ่มเติมหรือชื่อรุ่นกระสุน (เช่น DM33, Type 87 APFSDS)")
    parser.add_argument("--inherit", "-i", action="store_true",
                        help="ยืนยันว่าผลทำนายถูกต้องทั้งหมด (Inherit all predicted values: ammo type & bore)")
    parser.add_argument("--auto", action="store_true",
                        help="บันทึกอัตโนมัติโดยใช้ค่าที่ AI ทำนายทันที")
    parser.add_argument("--watch", "-w", action="store_true",
                        help="โหมดเฝ้าดูการเปลี่ยนกระสุนสดในเกม (Watch Mode)")
    parser.add_argument("--list", "-l", action="store_true",
                        help="แสดงรายการทั้งหมดที่เคยบันทึกไว้ใน JSON")
    parser.add_argument("--file", "-f", type=str, default=DEFAULT_DUMP_FILE,
                        help=f"ไฟล์ JSON ปลายทาง (ค่าเริ่มต้น: {DEFAULT_DUMP_FILE})")
    args = parser.parse_args()

    if args.list:
        list_records(args.file)
        return

    pid = get_game_pid()
    if not pid:
        print("❌ ไม่พบโปรเซสเกม War Thunder (aces) กรุณาเปิดเกมก่อนรันสคริปต์")
        sys.exit(1)

    scanner = MemoryScanner(pid)
    base_addr = get_game_base_address(pid)
    if not base_addr:
        print("❌ ไม่สามารถอ่าน Base Address ของเกมได้")
        sys.exit(1)

    init_dynamic_offsets(scanner, base_addr)
    cgame_base = mul.get_cgame_base(scanner, base_addr)
    if not cgame_base:
        print("❌ ไม่สามารถค้นหา CGame Base Address ได้")
        sys.exit(1)

    if args.watch:
        watch_mode(scanner, base_addr, cgame_base, args)
        return

    # Single-shot Dump
    profile = fetch_live_profile(scanner, base_addr, cgame_base)
    print_profile_dashboard(profile)

    actual_info = prompt_actual_info(profile, args)
    if actual_info is None:
        print("❌ ยกเลิกการบันทึก")
        return
    save_record_to_json(profile, actual_info, args.file)


if __name__ == "__main__":
    main()
