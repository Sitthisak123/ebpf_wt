import os
import sys
import json
import math
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul


DUMPS_DIR = os.path.join(PROJECT_ROOT, "dumps")


def _safe_round_tuple(values, ndigits=3):
    return [round(float(v), ndigits) for v in values]


def _build_record(scanner, unit_ptr):
    pos = mul.get_unit_pos(scanner, unit_ptr)
    bbox = mul.get_unit_3d_box_data(scanner, unit_ptr, is_air=False)
    dna = mul.get_unit_detailed_dna(scanner, unit_ptr) or {}
    if not pos or not bbox:
        return None

    _, bmin, bmax, rot = bbox
    dims = (
        float(bmax[0] - bmin[0]),
        float(bmax[1] - bmin[1]),
        float(bmax[2] - bmin[2]),
    )

    # Raw local extents: useful to see whether the front side looks inflated,
    # which often indicates cannon length is included in the bbox.
    front_extent = float(max(bmax[0], 0.0))
    back_extent = float(max(-bmin[0], 0.0))
    right_extent = float(max(bmax[2], 0.0))
    left_extent = float(max(-bmin[2], 0.0))
    top_extent = float(max(bmax[1], 0.0))
    bottom_extent = float(max(-bmin[1], 0.0))

    front_ratio = front_extent / max(front_extent + back_extent, 1e-6)
    side_ratio = right_extent / max(right_extent + left_extent, 1e-6)

    return {
        "ptr": hex(unit_ptr),
        "short_name": dna.get("short_name") or "Unknown",
        "name_key": dna.get("name_key") or "",
        "family": dna.get("family") or "",
        "class_id": dna.get("class_id"),
        "state": dna.get("state"),
        "world_pos": _safe_round_tuple(pos),
        "bbox": {
            "bmin": _safe_round_tuple(bmin),
            "bmax": _safe_round_tuple(bmax),
            "dims": _safe_round_tuple(dims),
            "front_extent_x+": round(front_extent, 3),
            "back_extent_x-": round(back_extent, 3),
            "right_extent_z+": round(right_extent, 3),
            "left_extent_z-": round(left_extent, 3),
            "top_extent_y+": round(top_extent, 3),
            "bottom_extent_y-": round(bottom_extent, 3),
            "front_ratio_x": round(front_ratio, 3),
            "side_ratio_z": round(side_ratio, 3),
        },
        "rotation": _safe_round_tuple(rot, 4),
    }


def _write_outputs(records, meta):
    os.makedirs(DUMPS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(DUMPS_DIR, f"ground_bbox_fleet_dump_{stamp}.json")
    txt_path = os.path.join(DUMPS_DIR, f"ground_bbox_fleet_dump_{stamp}.txt")

    payload = {
        "meta": meta,
        "ground_units": records,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    lines = []
    lines.append("==================================================")
    lines.append(" GROUND BBOX FLEET DUMPER")
    lines.append("==================================================")
    lines.append(f"CGame     : {meta['cgame_ptr']}")
    lines.append(f"My Unit   : {meta['my_unit_ptr']}")
    lines.append(f"BBMin/Max : {meta['bbmin_off']} / {meta['bbmax_off']}")
    lines.append(f"Count     : {len(records)}")
    lines.append("")

    for i, rec in enumerate(records, 1):
        bbox = rec["bbox"]
        lines.append(f"[{i}] {rec['short_name']} | {rec['name_key']}")
        lines.append(f"    ptr        : {rec['ptr']}")
        lines.append(f"    family     : {rec['family']} | class={rec['class_id']} | state={rec['state']}")
        lines.append(f"    world_pos   : {rec['world_pos']}")
        lines.append(f"    bmin        : {bbox['bmin']}")
        lines.append(f"    bmax        : {bbox['bmax']}")
        lines.append(f"    dims xyz    : {bbox['dims']}")
        lines.append(
            "    extents     : "
            f"front_x+={bbox['front_extent_x+']:.3f} | back_x-={bbox['back_extent_x-']:.3f} | "
            f"right_z+={bbox['right_extent_z+']:.3f} | left_z-={bbox['left_extent_z-']:.3f}"
        )
        lines.append(
            "    ratios      : "
            f"front_ratio_x={bbox['front_ratio_x']:.3f} | side_ratio_z={bbox['side_ratio_z']:.3f}"
        )
        lines.append("")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return json_path, txt_path


def main():
    pid = get_game_pid()
    if not pid:
        print("[-] War Thunder process not found")
        return 1

    base = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base)

    cgame = mul.get_cgame_base(scanner, base)
    if not cgame:
        print("[-] Failed to resolve cgame")
        return 1

    units = mul.get_all_units(scanner, cgame)
    my_unit, _ = mul.get_local_team(scanner, base)

    records = []
    for unit_ptr, is_air in units:
        if is_air:
            continue
        rec = _build_record(scanner, unit_ptr)
        if rec:
            records.append(rec)

    records.sort(key=lambda r: (r["family"], r["short_name"], r["ptr"]))

    meta = {
        "pid": pid,
        "base_addr": hex(base),
        "cgame_ptr": hex(cgame),
        "my_unit_ptr": hex(my_unit) if my_unit else "0x0",
        "bbmin_off": hex(mul.OFF_UNIT_BBMIN),
        "bbmax_off": hex(mul.OFF_UNIT_BBMAX),
    }

    json_path, txt_path = _write_outputs(records, meta)

    print("==================================================")
    print(" GROUND BBOX FLEET DUMPER")
    print("==================================================")
    print(f"[+] Ground units dumped: {len(records)}")
    print(f"[+] JSON: {json_path}")
    print(f"[+] TEXT: {txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
