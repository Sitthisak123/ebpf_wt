import math
import struct
import sys
from collections import Counter, defaultdict

from main import MemoryScanner, get_game_pid, get_game_base_address
import src.utils.mul as mul
from src.utils.scanner import init_dynamic_offsets


STRING_HINTS = (
    "air", "plane", "helicopter", "heli", "jet",
    "tank", "ground", "ship", "boat",
    "fighter", "bomber", "attacker",
    "exp_", "ussr_", "germ_", "us_", "uk_", "jp_", "cn_", "it_", "fr_", "sw_", "il_",
)

UNIT_FLAG_SCAN_RANGES = [
    (0x00, 0x200, 1, "byte"),
    (0x200, 0x400, 1, "byte"),
    (0x900, 0x1100, 1, "byte"),
]

INFO_STRING_OFFSETS = list(range(0x00, 0x100, 8))
MAX_CANDIDATES_PER_GROUP = 20
SUSPICIOUS_HINTS = ("air_defence", "structures", "dummy", "windmill", "fortification", "exp_aaa", "exp_structure", "exp_zero")


def safe_read_c_string(scanner, ptr, max_len=96):
    if not mul.is_valid_ptr(ptr):
        return None
    data = scanner.read_mem(ptr, max_len)
    if not data:
        return None
    raw = data.split(b"\x00")[0]
    if len(raw) < 3:
        return None
    try:
        text = raw.decode("utf-8", errors="ignore").strip()
    except Exception:
        return None
    if len(text) < 3:
        return None
    if not any(ch.isalnum() for ch in text):
        return None
    return text


def get_unit_name_and_info(scanner, u_ptr):
    unit_name = "UNKNOWN"
    info_ptr = 0
    try:
        info_raw = scanner.read_mem(u_ptr + mul.OFF_UNIT_INFO, 8)
        if info_raw and len(info_raw) == 8:
            info_ptr = struct.unpack("<Q", info_raw)[0]
            if mul.is_valid_ptr(info_ptr):
                name_ptr_raw = scanner.read_mem(info_ptr + mul.OFF_UNIT_NAME_PTR, 8)
                if name_ptr_raw and len(name_ptr_raw) == 8:
                    name_ptr = struct.unpack("<Q", name_ptr_raw)[0]
                    text = safe_read_c_string(scanner, name_ptr, 64)
                    if text:
                        unit_name = "".join(c for c in text if c.isalnum() or c in "-_")
    except Exception:
        pass
    return unit_name, info_ptr


def get_local_label(u_ptr, my_unit, provisional_is_air):
    if u_ptr == my_unit:
        return "MY_AIR" if provisional_is_air else "MY_GROUND"
    return "AIR" if provisional_is_air else "GROUND"


def collect_units(scanner, base_addr):
    cgame_base = mul.get_cgame_base(scanner, base_addr)
    if cgame_base == 0:
        print("[-] ไม่พบ CGame")
        sys.exit(1)

    all_units = mul.get_all_units(scanner, cgame_base)
    my_unit, my_team = mul.get_local_team(scanner, base_addr)

    rows = []
    for u_ptr, provisional_is_air in all_units:
        status = mul.get_unit_status(scanner, u_ptr)
        if not status:
            continue
        team, state, unit_name, reload_val = status
        if state >= 1:
            continue

        if unit_name == "UNKNOWN":
            unit_name, info_ptr = get_unit_name_and_info(scanner, u_ptr)
        else:
            _, info_ptr = get_unit_name_and_info(scanner, u_ptr)

        profile = mul.get_unit_filter_profile(scanner, u_ptr)
        pos = mul.get_unit_pos(scanner, u_ptr)
        rows.append({
            "u_ptr": u_ptr,
            "is_air": provisional_is_air,
            "label": get_local_label(u_ptr, my_unit, provisional_is_air),
            "team": team,
            "state": state,
            "reload": reload_val,
            "name": unit_name,
            "info_ptr": info_ptr,
            "pos": pos,
            "kind": profile.get("kind"),
            "skip": profile.get("skip"),
            "reason": profile.get("reason"),
            "tag": profile.get("tag"),
        })
    return cgame_base, my_unit, my_team, rows


def print_unit_table(rows):
    print("=" * 120)
    print("🧬 UNIT KIND DUMPER")
    print("=" * 120)
    print(f"{'Label':<10} | {'Kind':<6} | {'Skip':<4} | {'Why':<14} | {'Unit Ptr':<12} | {'Info Ptr':<12} | {'Team':<4} | {'Name'}")
    print("-" * 120)
    for row in rows:
        why = row.get("reason") or row.get("tag") or "-"
        print(
            f"{row['label']:<10} | {str(row.get('kind') or '-'):<6} | {('Y' if row.get('skip') else 'N'):<4} | {why[:14]:<14} | "
            f"{hex(row['u_ptr']):<12} | {hex(row['info_ptr']) if row['info_ptr'] else '-':<12} | "
            f"{row['team']:<4} | {row['name']}"
        )
    print("-" * 120)


def print_non_skipped_suspicious(rows):
    suspicious = []
    for row in rows:
        if row.get("skip"):
            continue
        name_l = (row.get("name") or "").lower()
        tag_l = (row.get("tag") or "").lower()
        if any(h in name_l for h in SUSPICIOUS_HINTS) or any(h in tag_l for h in SUSPICIOUS_HINTS):
            suspicious.append(row)

    if not suspicious:
        return

    print("\n⚠ Non-skipped suspicious units")
    print("-" * 120)
    for row in suspicious:
        print(
            f"{row['label']:<10} | ptr={hex(row['u_ptr'])} | team={row['team']} | "
            f"tag='{row.get('tag') or ''}' | name='{row.get('name') or ''}'"
        )
    print("-" * 120)


def analyze_flag_offsets(scanner, rows):
    air_rows = [r for r in rows if r["is_air"]]
    ground_rows = [r for r in rows if not r["is_air"]]
    if not air_rows or not ground_rows:
        print("[!] ต้องมีทั้ง air และ ground อย่างน้อยฝั่งละ 1 ตัว ถึงจะเทียบ flag ได้")
        return

    print("\n📌 Candidate Flag Offsets (เทียบจากกลุ่มที่ unit array บอกว่าเป็น air/ground)")
    print("-" * 120)
    print(f"{'Offset':<10} | {'Type':<6} | {'Air Values':<24} | {'Ground Values':<24} | {'Note'}")
    print("-" * 120)

    candidates = []
    for start, end, step, kind in UNIT_FLAG_SCAN_RANGES:
        for off in range(start, end, step):
            air_vals = []
            ground_vals = []
            for row in air_rows:
                data = scanner.read_mem(row["u_ptr"] + off, 1)
                if data:
                    air_vals.append(data[0])
            for row in ground_rows:
                data = scanner.read_mem(row["u_ptr"] + off, 1)
                if data:
                    ground_vals.append(data[0])

            if len(air_vals) < 2 or len(ground_vals) < 2:
                continue

            air_set = sorted(set(air_vals))
            ground_set = sorted(set(ground_vals))
            overlap = set(air_set) & set(ground_set)
            if overlap:
                continue

            air_common, air_count = Counter(air_vals).most_common(1)[0]
            ground_common, ground_count = Counter(ground_vals).most_common(1)[0]
            score = air_count + ground_count
            note = "stable split" if len(air_set) == 1 and len(ground_set) == 1 else "disjoint split"
            candidates.append((score, off, kind, air_set, ground_set, note))

    for _, off, kind, air_set, ground_set, note in sorted(candidates, reverse=True)[:MAX_CANDIDATES_PER_GROUP]:
        air_text = ", ".join(hex(v) for v in air_set[:6])
        ground_text = ", ".join(hex(v) for v in ground_set[:6])
        print(f"{hex(off):<10} | {kind:<6} | {air_text:<24} | {ground_text:<24} | {note}")
    if not candidates:
        print("[-] ยังไม่เจอ byte flag ที่แยก air/ground ได้แบบชัดเจนใน range ที่สแกน")


def scan_info_strings(scanner, rows):
    print("\n📝 Candidate Strings จาก info_ptr")
    print("-" * 120)
    printed = 0
    seen = set()

    for row in rows:
        info_ptr = row["info_ptr"]
        if not mul.is_valid_ptr(info_ptr):
            continue
        for off in INFO_STRING_OFFSETS:
            raw = scanner.read_mem(info_ptr + off, 8)
            if not raw or len(raw) < 8:
                continue
            ptr = struct.unpack("<Q", raw)[0]
            text = safe_read_c_string(scanner, ptr, 96)
            if not text:
                continue
            lowered = text.lower()
            if not any(hint in lowered for hint in STRING_HINTS):
                continue
            key = (row["u_ptr"], off, text)
            if key in seen:
                continue
            seen.add(key)
            printed += 1
            print(
                f"{row['label']:<10} | unit={hex(row['u_ptr'])} | info_off={hex(off):<6} | "
                f"text='{text}' | name='{row['name']}'"
            )

    if printed == 0:
        print("[-] ยังไม่เจอ string class/type ที่เข้าข่ายใน info_ptr + 0x00..0xF8")


def dump_selected_units(scanner, rows):
    interesting = []
    my_rows = [r for r in rows if r["label"].startswith("MY_")]
    if my_rows:
        interesting.extend(my_rows[:1])

    air_rows = [r for r in rows if r["is_air"] and not r["label"].startswith("MY_")]
    ground_rows = [r for r in rows if (not r["is_air"]) and not r["label"].startswith("MY_")]
    if air_rows:
        interesting.append(air_rows[0])
    if ground_rows:
        interesting.append(ground_rows[0])

    print("\n🔬 Detailed Dump (my unit + first air + first ground)")
    print("-" * 120)
    for row in interesting:
        print(f"\n[{row['label']}] unit={hex(row['u_ptr'])} | info={hex(row['info_ptr']) if row['info_ptr'] else '-'} | name='{row['name']}'")

        for off in [0x18, 0x1C, 0x20, 0x340, 0x358, 0xD10, 0xD18, mul.OFF_UNIT_STATE, mul.OFF_UNIT_TEAM, mul.OFF_UNIT_INFO]:
            size = 8 if off in (0x18, 0x20, 0x340, 0x358, 0xD10, 0xD18, mul.OFF_UNIT_INFO) else 4
            data = scanner.read_mem(row["u_ptr"] + off, size)
            if not data or len(data) < size:
                continue
            if size == 8:
                val = struct.unpack("<Q", data)[0]
                val_text = hex(val)
            elif size == 4:
                val = struct.unpack("<I", data)[0]
                val_text = hex(val)
            else:
                val_text = data.hex()
            print(f" unit+{hex(off):<6} = {val_text}")

        if mul.is_valid_ptr(row["info_ptr"]):
            for off in INFO_STRING_OFFSETS:
                raw = scanner.read_mem(row["info_ptr"] + off, 8)
                if not raw or len(raw) < 8:
                    continue
                ptr = struct.unpack("<Q", raw)[0]
                text = safe_read_c_string(scanner, ptr, 96)
                if text and any(hint in text.lower() for hint in STRING_HINTS):
                    print(f" info+{hex(off):<6} -> '{text}'")


def main():
    print("[*] 🚀 เริ่ม UNIT KIND DUMPER...")
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)

    init_dynamic_offsets(scanner, base_addr)
    _, my_unit, my_team, rows = collect_units(scanner, base_addr)

    if not rows:
        print("[-] ไม่พบยูนิตให้วิเคราะห์")
        return

    print(f"[*] MY_UNIT = {hex(my_unit) if my_unit else '0x0'} | MY_TEAM = {my_team}")
    print_unit_table(rows)
    print_non_skipped_suspicious(rows)
    analyze_flag_offsets(scanner, rows)
    scan_info_strings(scanner, rows)
    dump_selected_units(scanner, rows)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[*] Exit")
