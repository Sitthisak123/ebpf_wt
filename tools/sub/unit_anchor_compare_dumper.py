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
import radar_overlay as overlay

WATCH_POLL_SECONDS = 0.40
SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
MAX_UNITS = 24


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


def _world_from_local(origin, ax, ay, az, lx, ly, lz):
    return (
        origin[0] + (ax[0] * lx) + (ay[0] * ly) + (az[0] * lz),
        origin[1] + (ax[1] * lx) + (ay[1] * ly) + (az[1] * lz),
        origin[2] + (ax[2] * lx) + (ay[2] * ly) + (az[2] * lz),
    )


def compute_anchor_candidates(box_data, fallback_pos, distance_to_target, is_air):
    candidates = {}
    if fallback_pos:
        candidates["unit_pos"] = tuple(float(v) for v in fallback_pos)
    if not box_data:
        return candidates

    pos, bmin, bmax, rot = box_data
    ax, ay, az = mul.get_local_axes_from_rotation(rot, is_air)

    local_x = (bmin[0] + bmax[0]) * 0.5
    local_y = (bmin[1] + bmax[1]) * 0.5
    local_z = (bmin[2] + bmax[2]) * 0.5
    top_y = bmax[1]
    bottom_y = bmin[1]

    candidates["bbox_center_raw"] = _world_from_local(pos, ax, ay, az, local_x, local_y, local_z)
    candidates["bbox_top_center"] = _world_from_local(pos, ax, ay, az, local_x, top_y, local_z)
    candidates["bbox_bottom_center"] = _world_from_local(pos, ax, ay, az, local_x, bottom_y, local_z)

    # Mirror the current overlay box center behavior for ground units.
    forced_center_y = ((bmax[1] - bmin[1]) * 0.5) if not is_air else local_y
    candidates["bbox_center_overlay"] = _world_from_local(pos, ax, ay, az, local_x, forced_center_y, local_z)

    aim_point = overlay._get_ground_target_aim_point(box_data, fallback_pos, distance_to_target) if not is_air else None
    if aim_point:
        candidates["ground_aim_point"] = tuple(float(v) for v in aim_point)

    return candidates


def label_for_unit(scanner, unit_ptr):
    dna = mul.get_unit_detailed_dna(scanner, unit_ptr) or {}
    profile = mul.get_unit_filter_profile(scanner, unit_ptr) or {}
    return {
        "short_name": dna.get("short_name") or "",
        "name_key": dna.get("name_key") or "",
        "display_name": profile.get("display_name") or "",
        "family": profile.get("family") or dna.get("family") or "",
    }


def score_anchor(rows):
    valid = [row for row in rows if row.get("projection")]
    if len(valid) < 3:
        return -9999.0
    on = [row for row in valid if row["projection"]["on_screen"]]
    xs = [row["projection"]["sx"] for row in on]
    ys = [row["projection"]["sy"] for row in on]
    score = len(valid) * 4.0 + len(on) * 8.0
    if len(xs) >= 2:
        score += min(max(xs) - min(xs), 2500.0) * 0.012
    if len(ys) >= 2:
        score += min(max(ys) - min(ys), 1800.0) * 0.012
    if len(on) >= 3 and (max(xs) - min(xs) if len(xs) >= 2 else 0) < 90:
        score -= 20.0
    if len(on) >= 3 and (max(ys) - min(ys) if len(ys) >= 2 else 0) < 40:
        score -= 12.0
    return round(score, 3)


def compare_anchors(scanner, matrix, units, my_unit, my_pos):
    per_anchor = {}
    for u_ptr, is_air in units[:MAX_UNITS]:
        pos = mul.get_unit_pos(scanner, u_ptr)
        if not pos:
            continue
        box_data = mul.get_unit_3d_box_data(scanner, u_ptr, is_air)
        dist = 0.0
        if my_pos:
            dx = pos[0] - my_pos[0]
            dy = pos[1] - my_pos[1]
            dz = pos[2] - my_pos[2]
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        anchors = compute_anchor_candidates(box_data, pos, dist, is_air)
        for anchor_name, anchor_pos in anchors.items():
            per_anchor.setdefault(anchor_name, [])
            per_anchor[anchor_name].append({
                "unit_ptr": hex(u_ptr),
                "is_air": bool(is_air),
                "is_my_unit": u_ptr == my_unit,
                "pos": [round(v, 3) for v in anchor_pos],
                "projection": project_pos(matrix, anchor_pos),
                "label": label_for_unit(scanner, u_ptr),
            })

    compared = []
    for name, rows in per_anchor.items():
        my_row = next((row for row in rows if row["is_my_unit"]), None)
        on_screen_count = sum(1 for row in rows if (row.get("projection") or {}).get("on_screen"))
        compared.append({
            "anchor": name,
            "score": score_anchor(rows),
            "valid_count": len(rows),
            "on_screen_count": on_screen_count,
            "my_pos": my_row["pos"] if my_row else None,
            "my_projection": my_row["projection"] if my_row else None,
            "sample_rows": rows,
        })
    compared.sort(key=lambda item: item["score"], reverse=True)
    return compared


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
    my_pos = mul.get_unit_pos(scanner, my_unit) if my_unit else None
    anchors = compare_anchors(scanner, matrix, units, my_unit, my_pos) if matrix and units else []
    return {
        "timestamp": datetime.now().isoformat(),
        "chosen": {
            "my_unit": hex(my_unit) if my_unit else "0x0",
            "my_team": my_team,
            "my_pos": [round(v, 3) for v in my_pos] if my_pos else None,
            "cgame_ptr": hex(cgame_ptr) if cgame_ptr else "0x0",
            "camera_ptr": hex(camera_ptr) if camera_ptr else "0x0",
            "camera_off": hex(mul.LAST_VIEW_MATRIX_CAMERA_OFF) if getattr(mul, "LAST_VIEW_MATRIX_CAMERA_OFF", 0) else "0x0",
            "matrix_off": hex(mul.LAST_VIEW_MATRIX_OFF) if getattr(mul, "LAST_VIEW_MATRIX_OFF", 0) else "0x0",
            "projection_mode": (getattr(mul, "LAST_VIEW_PROJECTION_MODE", None) or {}).get("name"),
            "units_total": len(units),
        },
        "anchors": [
            {
                "anchor": row["anchor"],
                "score": row["score"],
                "valid_count": row["valid_count"],
                "on_screen_count": row["on_screen_count"],
                "my_pos": row["my_pos"],
                "my_projection": row["my_projection"],
            }
            for row in anchors
        ],
        "top_anchor_full": anchors[0] if anchors else None,
    }


def payload_signature(payload):
    chosen = payload.get("chosen") or {}
    top = (payload.get("anchors") or [{}])[0]
    return {
        "matrix_off": chosen.get("matrix_off"),
        "projection_mode": chosen.get("projection_mode"),
        "anchor": top.get("anchor"),
        "my_projection": top.get("my_projection"),
    }


def write_dump(payload, prefix):
    os.makedirs("dumps", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join("dumps", f"{prefix}_{stamp}.json")
    txt_path = os.path.join("dumps", f"{prefix}_{stamp}.txt")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    if isinstance(payload, list):
        anchor_counter = Counter()
        lines = ["UNIT ANCHOR WATCH", "=" * 80, f"Snapshots: {len(payload)}", ""]
        for snap in payload:
            top = (snap.get("anchors") or [{}])[0]
            chosen = snap.get("chosen") or {}
            if top.get("anchor"):
                anchor_counter[top["anchor"]] += 1
            lines.append(
                f"{snap.get('timestamp')} | matrix={chosen.get('matrix_off')} mode={chosen.get('projection_mode')} "
                f"best_anchor={top.get('anchor')} score={top.get('score')} my_proj={top.get('my_projection')}"
            )
        lines.extend(["", "ANCHOR COUNTS", json.dumps(anchor_counter, indent=2, ensure_ascii=False), "", "FULL JSON", json.dumps(payload, indent=2, ensure_ascii=False)])
    else:
        lines = [
            "UNIT ANCHOR COMPARE DUMPER",
            "=" * 80,
            f"Timestamp: {payload.get('timestamp')}",
            "",
            "CHOSEN",
            json.dumps(payload.get("chosen", {}), indent=2, ensure_ascii=False),
            "",
            "ANCHORS",
            json.dumps(payload.get("anchors", []), indent=2, ensure_ascii=False),
            "",
            "TOP ANCHOR FULL",
            json.dumps(payload.get("top_anchor_full", {}), indent=2, ensure_ascii=False),
        ]
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return json_path, txt_path


def run_single(scanner, base_addr):
    payload = build_payload(scanner, base_addr)
    json_path, txt_path = write_dump(payload, "unit_anchor_compare")
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
                top = (payload.get("anchors") or [{}])[0]
                print(
                    f"[+] Snapshot #{len(history)}: matrix={payload['chosen'].get('matrix_off')} "
                    f"mode={payload['chosen'].get('projection_mode')} best_anchor={top.get('anchor')} "
                    f"score={top.get('score')} my_proj={top.get('my_projection')}"
                )
                last_sig = sig
            time.sleep(WATCH_POLL_SECONDS)
    except KeyboardInterrupt:
        print("[*] Watch stopped by user.")
    json_path, txt_path = write_dump(history, "unit_anchor_compare_watch")
    print(f"[+] WATCH JSON: {json_path}")
    print(f"[+] WATCH TEXT: {txt_path}")


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()

    print("=" * 80)
    print("UNIT ANCHOR COMPARE DUMPER")
    print("=" * 80)
    print("Usage:")
    print("  sudo venv/bin/python tools/unit_anchor_compare_dumper.py")
    print("  sudo venv/bin/python tools/unit_anchor_compare_dumper.py --watch")
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
