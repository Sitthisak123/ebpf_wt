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


def build_offsets():
    values = set()
    for off in range(0x1b0, 0x231, 0x10):
        values.add(off)
    for off in range(0x1d0, 0x211, 0x04):
        values.add(off)
    values.update({0x1d8, 0x1e0, 0x1e4, 0x1e8, 0x1ec, 0x1f0, 0x1f4, 0x1f8, 0x1fc, 0x200})
    return sorted(values)


BB_OFFSETS = build_offsets()
BMAX_DELTAS = (0x0C, 0x10, 0x14, 0x18, 0x20)


def read_vec3(scanner, base_ptr, offset):
    if not mul.is_valid_ptr(base_ptr):
        return None
    raw = scanner.read_mem(base_ptr + offset, 12)
    if not raw or len(raw) < 12:
        return None
    vals = struct.unpack("<fff", raw)
    if not all(math.isfinite(v) for v in vals):
        return None
    if any(abs(v) > 10000.0 for v in vals):
        return None
    return tuple(float(v) for v in vals)


def valid_bbox(bmin, bmax):
    if bmin is None or bmax is None:
        return False
    dx = bmax[0] - bmin[0]
    dy = bmax[1] - bmin[1]
    dz = bmax[2] - bmin[2]
    return 0.5 < dx < 100.0 and 0.2 < dy < 40.0 and 0.5 < dz < 100.0


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


def label_for_unit(scanner, unit_ptr):
    dna = mul.get_unit_detailed_dna(scanner, unit_ptr) or {}
    profile = mul.get_unit_filter_profile(scanner, unit_ptr) or {}
    return {
        "short_name": dna.get("short_name") or "",
        "name_key": dna.get("name_key") or "",
        "display_name": profile.get("display_name") or "",
        "family": profile.get("family") or dna.get("family") or "",
    }


def score_pair(rows):
    valid = [row for row in rows if row.get("is_valid")]
    if not valid:
        return -9999.0
    on = [row for row in valid if (row.get("projection") or {}).get("on_screen")]
    score = len(valid) * 10.0 + len(on) * 5.0
    dims = [row["dims"] for row in valid]
    dxs = [d[0] for d in dims]
    dys = [d[1] for d in dims]
    dzs = [d[2] for d in dims]
    score -= abs((sum(dys) / len(dys)) - 2.0) * 2.0
    score -= abs((sum(dxs) / len(dxs)) - 3.5) * 1.0
    score -= abs((sum(dzs) / len(dzs)) - 6.0) * 1.0
    return round(score, 3)


def compare_bbox_pairs(scanner, matrix, units):
    compared = []
    for bmin_off in BB_OFFSETS:
        for delta in BMAX_DELTAS:
            bmax_off = bmin_off + delta
            rows = []
            for u_ptr, is_air in units[:MAX_UNITS]:
                pos = mul.get_unit_pos(scanner, u_ptr)
                bmin = read_vec3(scanner, u_ptr, bmin_off)
                bmax = read_vec3(scanner, u_ptr, bmax_off)
                ok = valid_bbox(bmin, bmax)
                dims = None
                proj = None
                if ok and pos:
                    dims = [round(bmax[i] - bmin[i], 3) for i in range(3)]
                    center = (
                        pos[0] + ((bmin[0] + bmax[0]) * 0.5),
                        pos[1] + ((bmin[1] + bmax[1]) * 0.5),
                        pos[2] + ((bmin[2] + bmax[2]) * 0.5),
                    )
                    proj = project_pos(matrix, center)
                rows.append({
                    "unit_ptr": hex(u_ptr),
                    "is_air": bool(is_air),
                    "label": label_for_unit(scanner, u_ptr),
                    "bmin": [round(v, 3) for v in bmin] if bmin else None,
                    "bmax": [round(v, 3) for v in bmax] if bmax else None,
                    "is_valid": ok,
                    "dims": dims,
                    "projection": proj,
                })
            valid_count = sum(1 for row in rows if row["is_valid"])
            on_screen_count = sum(1 for row in rows if (row.get("projection") or {}).get("on_screen"))
            compared.append({
                "bmin_off": bmin_off,
                "bmax_off": bmax_off,
                "bmin_hex": hex(bmin_off),
                "bmax_hex": hex(bmax_off),
                "score": score_pair(rows),
                "valid_count": valid_count,
                "on_screen_count": on_screen_count,
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
    compared = compare_bbox_pairs(scanner, matrix, units) if matrix and units else []
    top = compared[:10]
    baseline = next((row for row in compared if row["bmin_off"] == mul.OFF_UNIT_BBMIN and row["bmax_off"] == mul.OFF_UNIT_BBMAX), None)
    return {
        "timestamp": datetime.now().isoformat(),
        "chosen": {
            "my_unit": hex(my_unit) if my_unit else "0x0",
            "my_team": my_team,
            "cgame_ptr": hex(cgame_ptr) if cgame_ptr else "0x0",
            "camera_ptr": hex(camera_ptr) if camera_ptr else "0x0",
            "camera_off": hex(mul.LAST_VIEW_MATRIX_CAMERA_OFF) if getattr(mul, "LAST_VIEW_MATRIX_CAMERA_OFF", 0) else "0x0",
            "matrix_off": hex(mul.LAST_VIEW_MATRIX_OFF) if getattr(mul, "LAST_VIEW_MATRIX_OFF", 0) else "0x0",
            "projection_mode": (getattr(mul, "LAST_VIEW_PROJECTION_MODE", None) or {}).get("name"),
            "units_total": len(units),
            "baseline_bbmin": hex(mul.OFF_UNIT_BBMIN),
            "baseline_bbmax": hex(mul.OFF_UNIT_BBMAX),
        },
        "top_pairs": [
            {
                "bmin_off": row["bmin_hex"],
                "bmax_off": row["bmax_hex"],
                "score": row["score"],
                "valid_count": row["valid_count"],
                "on_screen_count": row["on_screen_count"],
            }
            for row in top
        ],
        "baseline": {
            "bmin_off": baseline["bmin_hex"],
            "bmax_off": baseline["bmax_hex"],
            "score": baseline["score"],
            "valid_count": baseline["valid_count"],
            "on_screen_count": baseline["on_screen_count"],
        } if baseline else None,
        "top_pair_full": top[0] if top else None,
    }


def payload_signature(payload):
    chosen = payload.get("chosen") or {}
    top = (payload.get("top_pairs") or [{}])[0]
    return {
        "matrix_off": chosen.get("matrix_off"),
        "projection_mode": chosen.get("projection_mode"),
        "bmin": top.get("bmin_off"),
        "bmax": top.get("bmax_off"),
        "score": top.get("score"),
    }


def write_dump(payload, prefix):
    os.makedirs("dumps", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join("dumps", f"{prefix}_{stamp}.json")
    txt_path = os.path.join("dumps", f"{prefix}_{stamp}.txt")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    if isinstance(payload, list):
        pair_counter = Counter()
        lines = ["UNIT BBOX WATCH", "=" * 80, f"Snapshots: {len(payload)}", ""]
        for snap in payload:
            top = (snap.get("top_pairs") or [{}])[0]
            if top.get("bmin_off") and top.get("bmax_off"):
                pair_counter[f"{top['bmin_off']}->{top['bmax_off']}"] += 1
            chosen = snap.get("chosen") or {}
            lines.append(
                f"{snap.get('timestamp')} | matrix={chosen.get('matrix_off')} mode={chosen.get('projection_mode')} "
                f"best={top.get('bmin_off')}->{top.get('bmax_off')} score={top.get('score')}"
            )
        lines.extend(["", "PAIR COUNTS", json.dumps(pair_counter, indent=2, ensure_ascii=False), "", "FULL JSON", json.dumps(payload, indent=2, ensure_ascii=False)])
    else:
        lines = [
            "UNIT BBOX COMPARE DUMPER",
            "=" * 80,
            f"Timestamp: {payload.get('timestamp')}",
            "",
            "CHOSEN",
            json.dumps(payload.get("chosen", {}), indent=2, ensure_ascii=False),
            "",
            "TOP PAIRS",
            json.dumps(payload.get("top_pairs", []), indent=2, ensure_ascii=False),
            "",
            "BASELINE",
            json.dumps(payload.get("baseline", {}), indent=2, ensure_ascii=False),
            "",
            "TOP PAIR FULL",
            json.dumps(payload.get("top_pair_full", {}), indent=2, ensure_ascii=False),
        ]
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return json_path, txt_path


def run_single(scanner, base_addr):
    payload = build_payload(scanner, base_addr)
    json_path, txt_path = write_dump(payload, "unit_bbox_compare")
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
                top = (payload.get("top_pairs") or [{}])[0]
                print(
                    f"[+] Snapshot #{len(history)}: matrix={payload['chosen'].get('matrix_off')} "
                    f"mode={payload['chosen'].get('projection_mode')} best={top.get('bmin_off')}->{top.get('bmax_off')} "
                    f"score={top.get('score')}"
                )
                last_sig = sig
            time.sleep(WATCH_POLL_SECONDS)
    except KeyboardInterrupt:
        print("[*] Watch stopped by user.")
    json_path, txt_path = write_dump(history, "unit_bbox_compare_watch")
    print(f"[+] WATCH JSON: {json_path}")
    print(f"[+] WATCH TEXT: {txt_path}")


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()

    print("=" * 80)
    print("UNIT BBOX COMPARE DUMPER")
    print("=" * 80)
    print("Usage:")
    print("  sudo venv/bin/python tools/unit_bbox_compare_dumper.py")
    print("  sudo venv/bin/python tools/unit_bbox_compare_dumper.py --watch")
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
