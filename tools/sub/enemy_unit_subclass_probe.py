import json
import math
import os
import struct
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul


DUMPS_DIR = os.path.join(PROJECT_ROOT, "dumps")
SCREEN_WIDTH = 2560
SCREEN_HEIGHT = 1440
CENTER_X = SCREEN_WIDTH / 2
CENTER_Y = SCREEN_HEIGHT / 2


def read_u64(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def read_i32(scanner, addr, default=0):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return default
    return struct.unpack("<i", raw)[0]


def read_u32(scanner, addr, default=0):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return default
    return struct.unpack("<I", raw)[0]


def read_f32(scanner, addr, default=0.0):
    raw = scanner.read_mem(addr, 4)
    if not raw or len(raw) < 4:
        return default
    return struct.unpack("<f", raw)[0]


def get_best_target(scanner, cgame, view_matrix, my_unit):
    units = mul.get_all_units(scanner, cgame)
    best_ptr = 0
    best_dist = 999999.0
    best_name = "Unknown"

    for u_ptr, is_air in units:
        if u_ptr == my_unit:
            continue
        pos = mul.get_unit_pos(scanner, u_ptr)
        if not pos:
            continue
        if abs(pos[0]) < 0.001 and abs(pos[1]) < 0.001 and abs(pos[2]) < 0.001:
            continue
        scr = mul.world_to_screen(view_matrix, pos[0], pos[1], pos[2], SCREEN_WIDTH, SCREEN_HEIGHT)
        if scr and scr[2] > 0:
            dist = math.hypot(scr[0] - CENTER_X, scr[1] - CENTER_Y)
            if dist < best_dist:
                best_dist = dist
                best_ptr = u_ptr
                dna = mul.get_unit_detailed_dna(scanner, u_ptr) or {}
                best_name = dna.get("short_name") or dna.get("name_key") or "Unknown"

    return best_ptr, best_dist, best_name


def scan_region(scanner, base_ptr, size, label):
    records = []
    for off in range(0, size, 8):
        records.append(
            {
                "region": label,
                "offset": hex(off),
                "addr": hex(base_ptr + off),
                "u64": hex(read_u64(scanner, base_ptr + off)),
                "i32": read_i32(scanner, base_ptr + off, 0),
                "u32": read_u32(scanner, base_ptr + off, 0),
                "f32": round(read_f32(scanner, base_ptr + off, 0.0), 6),
            }
        )
    return records


def write_outputs(payload):
    os.makedirs(DUMPS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(DUMPS_DIR, f"enemy_unit_subclass_probe_{stamp}.json")
    txt_path = os.path.join(DUMPS_DIR, f"enemy_unit_subclass_probe_{stamp}.txt")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    meta = payload["meta"]
    dna = payload["dna"]
    lines = []
    lines.append("==========================================================")
    lines.append(" ENEMY UNIT SUBCLASS PROBE")
    lines.append("==========================================================")
    lines.append(f"PID          : {meta['pid']}")
    lines.append(f"Base         : {meta['base_addr']}")
    lines.append(f"CGame        : {meta['cgame_ptr']}")
    lines.append(f"My Unit      : {meta['my_unit_ptr']}")
    lines.append(f"Target Ptr   : {meta['target_ptr']}")
    lines.append(f"Info Ptr     : {meta['info_ptr']}")
    lines.append(f"Crosshair Px : {meta['crosshair_dist_px']}")
    lines.append(f"Short Name   : {dna.get('short_name')}")
    lines.append(f"Name Key     : {dna.get('name_key')}")
    lines.append(f"Family       : {dna.get('family')}")
    lines.append(f"Class ID     : {dna.get('class_id')}")
    lines.append("")
    lines.append("[focus-offsets]")
    for item in payload["focus_offsets"]:
        lines.append(
            f"- {item['region']} + {item['offset']} | addr={item['addr']} "
            f"| u64={item['u64']} | i32={item['i32']} | u32={item['u32']} | f32={item['f32']}"
        )
    lines.append("")
    lines.append("[raw-fields]")
    for rec in payload["fields"]:
        lines.append(
            f"- {rec['region']} + {rec['offset']} | addr={rec['addr']} "
            f"| u64={rec['u64']} | i32={rec['i32']} | u32={rec['u32']} | f32={rec['f32']}"
        )

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return json_path, txt_path


def main():
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)

    cgame_ptr = mul.get_cgame_base(scanner, base_addr)
    my_unit, _my_team = mul.get_local_team(scanner, base_addr)
    view_matrix = mul.get_view_matrix(scanner, cgame_ptr)
    if not cgame_ptr or not my_unit or view_matrix is None:
        print("[-] missing base objects")
        return

    target_ptr, center_dist, _target_name = get_best_target(scanner, cgame_ptr, view_matrix, my_unit)
    if not target_ptr:
        print("[-] no target near crosshair")
        return

    dna = mul.get_unit_detailed_dna(scanner, target_ptr) or {}
    info_ptr = read_u64(scanner, target_ptr + mul.OFF_UNIT_INFO)

    focus_keys = [
        ("my_unit", 0x98),
        ("my_unit", 0xC8),
        ("my_unit", 0x198),
        ("my_unit", 0x200),
        ("my_unit", 0x2D0),
        ("my_unit", 0x330),
        ("my_unit", 0x458),
        ("my_unit", 0x580),
        ("my_unit", 0x6A8),
        ("my_unit", 0xF30),
        ("my_unit", 0xF48),
        ("my_unit", 0xF60),

        ("info_ptr", 0x60),
        ("info_ptr", 0xF0),
        ("info_ptr", 0x290),
    ]

    fields = []
    fields.extend(scan_region(scanner, target_ptr, 0x1200, "my_unit"))
    if mul.is_valid_ptr(info_ptr):
        fields.extend(scan_region(scanner, info_ptr, 0x320, "info_ptr"))

    field_map = {(rec["region"], int(rec["offset"], 16)): rec for rec in fields}
    focus_offsets = []
    for region, off in focus_keys:
        rec = field_map.get((region, off))
        if rec:
            focus_offsets.append(rec)

    payload = {
        "meta": {
            "pid": pid,
            "base_addr": hex(base_addr) if base_addr else "0x0",
            "cgame_ptr": hex(cgame_ptr) if cgame_ptr else "0x0",
            "my_unit_ptr": hex(my_unit) if my_unit else "0x0",
            "target_ptr": hex(target_ptr) if target_ptr else "0x0",
            "info_ptr": hex(info_ptr) if info_ptr else "0x0",
            "crosshair_dist_px": round(center_dist, 3),
        },
        "dna": dna,
        "focus_offsets": focus_offsets,
        "fields": fields,
    }

    json_path, txt_path = write_outputs(payload)
    print("==========================================================")
    print(" ENEMY UNIT SUBCLASS PROBE")
    print("==========================================================")
    print(f"[+] JSON: {json_path}")
    print(f"[+] TEXT: {txt_path}")


if __name__ == "__main__":
    main()
