import argparse
import json
import math
import os
import struct
import sys
import time
from collections import Counter
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul

WATCH_POLL_SECONDS = 0.40
SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
MAX_UNITS = 24


def build_candidate_offsets():
    offsets = set()
    for off in range(0xCC0, 0xD41, 0x10):
        offsets.add(off)
    for off in range(0xCF0, 0xD21, 0x04):
        offsets.add(off)
    offsets.update({0xCD0, 0xCE0, 0xCF0, 0xD00, 0xD04, 0xD08, 0xD10, 0xD18, 0xD20})
    return sorted(offsets)


CANDIDATE_OFFSETS = build_candidate_offsets()
AXIS_VARIANTS = {
    "xyz": (0, 1, 2),
    "xzy": (0, 2, 1),
    "yxz": (1, 0, 2),
    "yzx": (1, 2, 0),
    "zxy": (2, 0, 1),
    "zyx": (2, 1, 0),
}


def read_vec3(scanner, base_ptr, offset):
    if not mul.is_valid_ptr(base_ptr):
        return None
    raw = scanner.read_mem(base_ptr + offset, 12)
    if not raw or len(raw) < 12:
        return None
    vals = struct.unpack("<fff", raw)
    if not all(math.isfinite(v) for v in vals):
        return None
    if any(abs(v) > 1e7 for v in vals):
        return None
    return tuple(float(v) for v in vals)


def project_pos(matrix, pos):
    if matrix is None or pos is None:
        return None
    projected = mul.world_to_screen(matrix, pos[0], pos[1], pos[2], SCREEN_WIDTH, SCREEN_HEIGHT)
    if not projected:
        return None
    sx, sy, w = projected
    return {
        "sx": round(float(sx), 2),
        "sy": round(float(sy), 2),
        "w": round(float(w), 4),
        "on_screen": 0.0 <= sx <= SCREEN_WIDTH and 0.0 <= sy <= SCREEN_HEIGHT,
    }


def permute_vec3(pos, order):
    if pos is None:
        return None
    return (pos[order[0]], pos[order[1]], pos[order[2]])


def vec_mag(pos):
    if pos is None:
        return 0.0
    return math.sqrt(pos[0] * pos[0] + pos[1] * pos[1] + pos[2] * pos[2])


def score_candidate(sample_rows):
    valid = [row for row in sample_rows if row.get("pos") is not None]
    if len(valid) < 3:
        return -9999.0
    on_screen = [row for row in valid if (row.get("projection") or {}).get("on_screen")]
    xs = [row["projection"]["sx"] for row in on_screen]
    ys = [row["projection"]["sy"] for row in on_screen]
    world_x = [row["pos"][0] for row in valid]
    world_y = [row["pos"][1] for row in valid]
    world_z = [row["pos"][2] for row in valid]
    x_span = (max(xs) - min(xs)) if len(xs) >= 2 else 0.0
    y_span = (max(ys) - min(ys)) if len(ys) >= 2 else 0.0
    wx_span = max(world_x) - min(world_x)
    wy_span = max(world_y) - min(world_y)
    wz_span = max(world_z) - min(world_z)
    mags = [vec_mag(row["pos"]) for row in valid]
    avg_mag = sum(mags) / len(mags)
    max_mag = max(mags)
    score = 0.0
    score += len(valid) * 3.0
    score += len(on_screen) * 6.0
    score += min(x_span, 2500.0) * 0.015
    score += min(y_span, 1800.0) * 0.015
    score += min(wx_span, 5000.0) * 0.001
    score += min(wy_span, 2000.0) * 0.001
    score += min(wz_span, 5000.0) * 0.001
    if len(on_screen) >= 3 and x_span < 90.0:
        score -= 25.0
    if len(on_screen) >= 3 and y_span < 40.0:
        score -= 15.0
    if len(on_screen) == 0:
        score -= 40.0
    # Reject local basis / normalized direction vectors that happen to project well.
    if avg_mag < 5.0:
        score -= 120.0
    elif avg_mag < 25.0:
        score -= 60.0
    if max_mag < 50.0:
        score -= 25.0
    return round(score, 3)


def label_for_unit(scanner, unit_ptr):
    dna = mul.get_unit_detailed_dna(scanner, unit_ptr) or {}
    profile = mul.get_unit_filter_profile(scanner, unit_ptr) or {}
    return {
        "short_name": dna.get("short_name") or "",
        "name_key": dna.get("name_key") or "",
        "display_name": profile.get("display_name") or "",
        "family": profile.get("family") or dna.get("family") or "",
    }


def compare_offsets(scanner, matrix, units, my_unit):
    compared = []
    for off in CANDIDATE_OFFSETS:
        rows = []
        for u_ptr, is_air in units[:MAX_UNITS]:
            pos = read_vec3(scanner, u_ptr, off)
            proj = project_pos(matrix, pos)
            rows.append({
                "unit_ptr": hex(u_ptr),
                "is_air": bool(is_air),
                "is_my_unit": u_ptr == my_unit,
                "pos": [round(v, 3) for v in pos] if pos else None,
                "projection": proj,
            })
        my_row = next((row for row in rows if row["is_my_unit"]), None)
        valid_count = sum(1 for row in rows if row["pos"] is not None)
        on_screen_count = sum(1 for row in rows if (row.get("projection") or {}).get("on_screen"))
        compared.append({
            "offset": off,
            "offset_hex": hex(off),
            "score": score_candidate(rows),
            "valid_count": valid_count,
            "on_screen_count": on_screen_count,
            "my_pos": my_row["pos"] if my_row else None,
            "my_projection": my_row["projection"] if my_row else None,
            "sample_rows": rows,
        })
    compared.sort(key=lambda item: item["score"], reverse=True)
    return compared


def compare_axis_mappings(scanner, matrix, units, my_unit, base_offset):
    results = []
    for name, order in AXIS_VARIANTS.items():
        rows = []
        for u_ptr, is_air in units[:MAX_UNITS]:
            base_pos = read_vec3(scanner, u_ptr, base_offset)
            pos = permute_vec3(base_pos, order)
            proj = project_pos(matrix, pos)
            rows.append({
                "unit_ptr": hex(u_ptr),
                "is_air": bool(is_air),
                "is_my_unit": u_ptr == my_unit,
                "pos": [round(v, 3) for v in pos] if pos else None,
                "projection": proj,
            })
        my_row = next((row for row in rows if row["is_my_unit"]), None)
        on_screen_count = sum(1 for row in rows if (row.get("projection") or {}).get("on_screen"))
        results.append({
            "axis": name,
            "score": score_candidate(rows),
            "on_screen_count": on_screen_count,
            "my_pos": my_row["pos"] if my_row else None,
            "my_projection": my_row["projection"] if my_row else None,
        })
    results.sort(key=lambda item: item["score"], reverse=True)
    return results


def build_payload(scanner, base_addr):
    my_unit, my_team = mul.get_local_team(scanner, base_addr)
    cgame_ptr = mul.get_cgame_base(scanner, base_addr)
    matrix = mul.get_view_matrix(scanner, cgame_ptr)
    camera_ptr = 0
    if mul.is_valid_ptr(cgame_ptr):
        raw = scanner.read_mem(cgame_ptr + mul.OFF_CAMERA_PTR, 8)
        if raw and len(raw) == 8:
            camera_ptr = struct.unpack("<Q", raw)[0]
    units = mul.get_all_units(scanner, cgame_ptr) if mul.is_valid_ptr(cgame_ptr) else []
    compared = compare_offsets(scanner, matrix, units, my_unit) if matrix and units else []
    axis_compare = compare_axis_mappings(scanner, matrix, units, my_unit, mul.OFF_UNIT_X) if matrix and units else []
    top = compared[:8]
    payload = {
        "timestamp": datetime.now().isoformat(),
        "pid": getattr(scanner, "pid", 0),
        "image_base": hex(base_addr),
        "chosen": {
            "my_unit": hex(my_unit) if my_unit else "0x0",
            "my_team": my_team,
            "cgame_ptr": hex(cgame_ptr) if cgame_ptr else "0x0",
            "camera_ptr": hex(camera_ptr) if camera_ptr else "0x0",
            "camera_off": hex(mul.LAST_VIEW_MATRIX_CAMERA_OFF) if getattr(mul, "LAST_VIEW_MATRIX_CAMERA_OFF", 0) else "0x0",
            "matrix_off": hex(mul.LAST_VIEW_MATRIX_OFF) if getattr(mul, "LAST_VIEW_MATRIX_OFF", 0) else "0x0",
            "projection_mode": (getattr(mul, "LAST_VIEW_PROJECTION_MODE", None) or {}).get("name"),
            "units_total": len(units),
            "baseline_unit_x": hex(mul.OFF_UNIT_X),
        },
        "top_candidates": [
            {
                "offset": row["offset_hex"],
                "score": row["score"],
                "valid_count": row["valid_count"],
                "on_screen_count": row["on_screen_count"],
                "my_pos": row["my_pos"],
                "my_projection": row["my_projection"],
            }
            for row in top
        ],
        "axis_candidates": axis_compare,
        "baseline": next((row for row in compared if row["offset"] == mul.OFF_UNIT_X), None),
        "sampled_labels": [
            {
                "unit_ptr": hex(u_ptr),
                "is_air": bool(is_air),
                "label": label_for_unit(scanner, u_ptr),
            }
            for u_ptr, is_air in units[:MAX_UNITS]
        ],
        "all_candidates": [
            {
                "offset": row["offset_hex"],
                "score": row["score"],
                "valid_count": row["valid_count"],
                "on_screen_count": row["on_screen_count"],
                "my_pos": row["my_pos"],
                "my_projection": row["my_projection"],
            }
            for row in compared
        ],
    }
    return payload


def payload_signature(payload):
    chosen = payload.get("chosen") or {}
    top = payload.get("top_candidates") or []
    best = top[0] if top else {}
    axis = (payload.get("axis_candidates") or [{}])[0]
    return {
        "my_unit": chosen.get("my_unit"),
        "matrix_off": chosen.get("matrix_off"),
        "projection_mode": chosen.get("projection_mode"),
        "best_offset": best.get("offset"),
        "best_my_pos": best.get("my_pos"),
        "best_my_projection": best.get("my_projection"),
        "best_axis": axis.get("axis"),
    }


def write_dump(payload, prefix):
    os.makedirs("dumps", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join("dumps", f"{prefix}_{stamp}.json")
    txt_path = os.path.join("dumps", f"{prefix}_{stamp}.txt")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    if isinstance(payload, list):
        offset_counter = Counter()
        mode_counter = Counter()
        axis_counter = Counter()
        lines = [
            "UNIT POSITION WATCH",
            "=" * 80,
            f"Snapshots: {len(payload)}",
            "",
        ]
        for snap in payload:
            top = (snap.get("top_candidates") or [{}])[0]
            chosen = snap.get("chosen") or {}
            if top.get("offset"):
                offset_counter[top["offset"]] += 1
            if chosen.get("projection_mode"):
                mode_counter[chosen["projection_mode"]] += 1
            axis = (snap.get("axis_candidates") or [{}])[0]
            if axis.get("axis"):
                axis_counter[axis["axis"]] += 1
            lines.append(
                f"{snap.get('timestamp')} | matrix={chosen.get('matrix_off')} mode={chosen.get('projection_mode')} "
                f"best={top.get('offset')} score={top.get('score')} axis={axis.get('axis')} "
                f"axis_score={axis.get('score')} my_pos={top.get('my_pos')} my_proj={top.get('my_projection')}"
            )
        lines.extend([
            "",
            "BEST OFFSET COUNTS",
            json.dumps(offset_counter, indent=2, ensure_ascii=False),
            "",
            "PROJECTION MODE COUNTS",
            json.dumps(mode_counter, indent=2, ensure_ascii=False),
            "",
            "AXIS COUNTS",
            json.dumps(axis_counter, indent=2, ensure_ascii=False),
            "",
            "FULL JSON",
            json.dumps(payload, indent=2, ensure_ascii=False),
        ])
    else:
        lines = [
            "UNIT POSITION COMPARE DUMPER",
            "=" * 80,
            f"Timestamp: {payload.get('timestamp')}",
            "",
            "CHOSEN",
            json.dumps(payload.get("chosen", {}), indent=2, ensure_ascii=False),
            "",
            "TOP CANDIDATES",
            json.dumps(payload.get("top_candidates", []), indent=2, ensure_ascii=False),
            "",
            "AXIS CANDIDATES",
            json.dumps(payload.get("axis_candidates", []), indent=2, ensure_ascii=False),
            "",
            "BASELINE",
            json.dumps(payload.get("baseline", {}), indent=2, ensure_ascii=False),
            "",
            "SAMPLED LABELS",
            json.dumps(payload.get("sampled_labels", []), indent=2, ensure_ascii=False),
            "",
            "ALL CANDIDATES",
            json.dumps(payload.get("all_candidates", []), indent=2, ensure_ascii=False),
        ]
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return json_path, txt_path


def run_single(scanner, base_addr):
    payload = build_payload(scanner, base_addr)
    json_path, txt_path = write_dump(payload, "unit_position_compare")
    print(f"[+] JSON: {json_path}")
    print(f"[+] TEXT: {txt_path}")


def run_watch(scanner, base_addr):
    print("[*] Watch mode active. state เปลี่ยนเมื่อไรจะจับ snapshot ใหม่")
    print("[*] กด Ctrl+C เพื่อหยุดและเขียน session log")
    history = []
    last_sig = None
    try:
        while True:
            payload = build_payload(scanner, base_addr)
            sig = payload_signature(payload)
            if sig != last_sig:
                history.append(payload)
                top = (payload.get("top_candidates") or [{}])[0]
                print(
                    f"[+] Snapshot #{len(history)}: matrix={payload['chosen'].get('matrix_off')} "
                    f"mode={payload['chosen'].get('projection_mode')} best={top.get('offset')} "
                    f"score={top.get('score')} my_pos={top.get('my_pos')} my_proj={top.get('my_projection')}"
                )
                last_sig = sig
            time.sleep(WATCH_POLL_SECONDS)
    except KeyboardInterrupt:
        print("[*] Watch stopped by user.")
    json_path, txt_path = write_dump(history, "unit_position_compare_watch")
    print(f"[+] WATCH JSON: {json_path}")
    print(f"[+] WATCH TEXT: {txt_path}")


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()

    print("=" * 80)
    print("UNIT POSITION COMPARE DUMPER")
    print("=" * 80)
    print("Usage:")
    print("  sudo venv/bin/python tools/unit_position_compare_dumper.py")
    print("  sudo venv/bin/python tools/unit_position_compare_dumper.py --watch")
    print("-" * 80)
    print("")

    pid = get_game_pid()
    if not pid:
        print("[-] ไม่พบ process ของเกม 'aces'")
        return
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    try:
        init_dynamic_offsets(scanner, base_addr)
        if args.watch:
            run_watch(scanner, base_addr)
        else:
            run_single(scanner, base_addr)
    finally:
        scanner.close()


if __name__ == "__main__":
    main()
