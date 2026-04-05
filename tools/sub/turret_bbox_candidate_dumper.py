import argparse
import json
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

CANDIDATE_BBOX_PAIRS = [
    ("unit_bbox", None, None),
    ("body_bb_1f80", 0x1F80, 0x1F8C),
    ("turret_bb_1f78", 0x1F78, 0x1F84),
    ("turret_bb_1f90", 0x1F90, 0x1F9C),
]


def _read_vec3(scanner, addr):
    raw = scanner.read_mem(addr, 12)
    if not raw or len(raw) != 12:
        return None
    vals = struct.unpack("<fff", raw)
    if not all(abs(v) < 10000 for v in vals):
        return None
    return vals


def _round_vec(values, ndigits=3):
    return [round(float(v), ndigits) for v in values]


def _valid_bbox(bmin, bmax):
    if not bmin or not bmax:
        return False
    dx = float(bmax[0] - bmin[0])
    dy = float(bmax[1] - bmin[1])
    dz = float(bmax[2] - bmin[2])
    return 0.05 < dx < 100.0 and 0.05 < dy < 50.0 and 0.05 < dz < 100.0


def _bbox_payload(bmin, bmax):
    dims = (
        float(bmax[0] - bmin[0]),
        float(bmax[1] - bmin[1]),
        float(bmax[2] - bmin[2]),
    )
    return {
        "bmin": _round_vec(bmin),
        "bmax": _round_vec(bmax),
        "dims": _round_vec(dims),
    }


def _build_record(scanner, unit_ptr):
    dna = mul.get_unit_detailed_dna(scanner, unit_ptr) or {}
    box = mul.get_unit_3d_box_data(scanner, unit_ptr, False)
    if not box:
        return None

    unit_pos, curr_bmin, curr_bmax, rot = box
    candidates = {}
    for name, min_off, max_off in CANDIDATE_BBOX_PAIRS:
        if min_off is None:
            candidates[name] = {
                "valid": True,
                "source": "current_runtime_bbox",
                **_bbox_payload(curr_bmin, curr_bmax),
            }
            continue
        bmin = _read_vec3(scanner, unit_ptr + min_off)
        bmax = _read_vec3(scanner, unit_ptr + max_off)
        valid = _valid_bbox(bmin, bmax)
        candidates[name] = {
            "valid": bool(valid),
            "min_offset": hex(min_off),
            "max_offset": hex(max_off),
            "bmin": _round_vec(bmin) if bmin else None,
            "bmax": _round_vec(bmax) if bmax else None,
            "dims": _round_vec((bmax[0] - bmin[0], bmax[1] - bmin[1], bmax[2] - bmin[2])) if valid else None,
        }

    return {
        "ptr": hex(unit_ptr),
        "short_name": dna.get("short_name") or "Unknown",
        "name_key": dna.get("name_key") or "",
        "family": dna.get("family") or "",
        "class_id": dna.get("class_id"),
        "world_pos": _round_vec(unit_pos),
        "candidates": candidates,
    }


def _write_outputs(records, meta):
    os.makedirs(DUMPS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(DUMPS_DIR, f"turret_bbox_candidate_dump_{stamp}.json")
    txt_path = os.path.join(DUMPS_DIR, f"turret_bbox_candidate_dump_{stamp}.txt")

    payload = {"meta": meta, "ground_units": records}
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    lines = []
    lines.append("==================================================")
    lines.append(" TURRET BBOX CANDIDATE DUMPER")
    lines.append("==================================================")
    lines.append(f"CGame   : {meta['cgame_ptr']}")
    lines.append(f"My Unit : {meta['my_unit_ptr']}")
    lines.append(f"Count   : {len(records)}")
    lines.append("")

    for i, rec in enumerate(records, 1):
        lines.append(f"[{i}] {rec['short_name']} | {rec['name_key']} | family={rec['family']}")
        lines.append(f"    ptr      : {rec['ptr']}")
        lines.append(f"    world_pos: {rec['world_pos']}")
        for name, cand in rec["candidates"].items():
            status = "OK" if cand.get("valid") else "BAD"
            lines.append(f"    - {name} [{status}]")
            if "min_offset" in cand:
                lines.append(f"      offs : {cand['min_offset']} / {cand['max_offset']}")
            lines.append(f"      bmin : {cand['bmin']}")
            lines.append(f"      bmax : {cand['bmax']}")
            lines.append(f"      dims : {cand['dims']}")
        lines.append("")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return json_path, txt_path


def main():
    parser = argparse.ArgumentParser(description="Dump body/turret bbox candidate offsets for all ground units.")
    parser.add_argument("--only-my-unit", action="store_true", help="Dump my unit only")
    args = parser.parse_args()

    pid = get_game_pid()
    if not pid:
        print("[-] War Thunder process not found")
        return 1

    base = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base)

    cgame = mul.get_cgame_base(scanner, base)
    my_unit, _ = mul.get_local_team(scanner, base)
    units = mul.get_all_units(scanner, cgame) if cgame else []

    records = []
    if args.only_my_unit and my_unit:
        rec = _build_record(scanner, my_unit)
        if rec:
            records.append(rec)
    else:
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
        "cgame_ptr": hex(cgame) if cgame else "0x0",
        "my_unit_ptr": hex(my_unit) if my_unit else "0x0",
    }
    json_path, txt_path = _write_outputs(records, meta)

    print("==================================================")
    print(" TURRET BBOX CANDIDATE DUMPER")
    print("==================================================")
    print(f"[+] Ground units dumped: {len(records)}")
    print(f"[+] JSON: {json_path}")
    print(f"[+] TEXT: {txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
