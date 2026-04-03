import json
import math
import os
import struct
import sys
import time
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul

WATCH_POLL_SECONDS = 0.40
MAX_UNITS_TO_DUMP = 24
SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080


def read_u64(scanner, addr):
    raw = scanner.read_mem(addr, 8)
    if not raw or len(raw) < 8:
        return 0
    return struct.unpack("<Q", raw)[0]


def matrix_signature(values):
    if not values or len(values) != 16:
        return "none"
    trimmed = []
    for v in values:
        if not math.isfinite(v):
            trimmed.append("nan")
        else:
            trimmed.append(round(float(v), 4))
    return json.dumps(trimmed, ensure_ascii=False)


def values_matrix_ok(values):
    if not values or len(values) != 16:
        return False
    if not all(math.isfinite(v) for v in values):
        return False
    if any(abs(v) > 1e6 for v in values):
        return False
    non_zero = sum(1 for v in values if abs(v) > 1e-6)
    return non_zero >= 6


def read_direct_matrix(scanner, cgame_ptr):
    if not mul.is_valid_ptr(cgame_ptr):
        return 0, None
    camera_ptr = read_u64(scanner, cgame_ptr + mul.OFF_CAMERA_PTR)
    if not mul.is_valid_ptr(camera_ptr):
        return 0, None
    matrix_data = scanner.read_mem(camera_ptr + mul.OFF_VIEW_MATRIX, 64)
    if not matrix_data or len(matrix_data) < 64:
        return camera_ptr, None
    values = struct.unpack("<16f", matrix_data[:64])
    if not values_matrix_ok(values):
        return camera_ptr, None
    return camera_ptr, values


def project_pos(matrix, pos):
    if not matrix or pos is None:
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


def projection_permutations(matrix, pos):
    if pos is None or matrix is None:
        return {}
    x, y, z = pos
    variants = {
        "xyz": (x, y, z),
        "xzy": (x, z, y),
        "yxz": (y, x, z),
        "yzx": (y, z, x),
        "zxy": (z, x, y),
        "zyx": (z, y, x),
    }
    out = {}
    for key, value in variants.items():
        out[key] = project_pos(matrix, value)
    return out


def candidate_details(scanner, base_addr, my_unit):
    rows = []
    for idx, offset in enumerate(mul._manager_offsets()):
        cgame_ptr = read_u64(scanner, base_addr + offset)
        if not mul.is_valid_ptr(cgame_ptr):
            continue
        live_score, total_units = mul._score_cgame_live(scanner, cgame_ptr)
        contains_my_unit = mul._cgame_contains_unit(scanner, cgame_ptr, my_unit)
        camera_ptr, matrix = read_direct_matrix(scanner, cgame_ptr)
        my_pos = mul.get_unit_pos(scanner, my_unit) if mul.is_valid_ptr(my_unit) else None
        my_projection = project_pos(matrix, my_pos) if matrix and my_pos else None
        rows.append({
            "offset": hex(offset),
            "cgame_ptr": hex(cgame_ptr),
            "contains_my_unit": contains_my_unit,
            "live_score": live_score,
            "total_units": total_units,
            "camera_ptr": hex(camera_ptr) if camera_ptr else "0x0",
            "matrix_ok": matrix is not None,
            "matrix_signature": matrix_signature(matrix),
            "my_projection": my_projection,
        })
    return rows


def unit_label(scanner, unit_ptr):
    dna = mul.get_unit_detailed_dna(scanner, unit_ptr) or {}
    profile = mul.get_unit_filter_profile(scanner, unit_ptr) or {}
    return {
        "short_name": dna.get("short_name") or "",
        "name_key": dna.get("name_key") or "",
        "family": dna.get("family") or "",
        "display_name": profile.get("display_name") or "",
        "tag": profile.get("tag") or "",
        "kind": profile.get("kind"),
    }


def sample_units(scanner, cgame_ptr, matrix, my_unit):
    sampled = []
    all_units = mul.get_all_units(scanner, cgame_ptr)
    for idx, (u_ptr, is_air) in enumerate(all_units[:MAX_UNITS_TO_DUMP]):
        pos = mul.get_unit_pos(scanner, u_ptr)
        projection = project_pos(matrix, pos) if matrix and pos else None
        sampled.append({
            "idx": idx,
            "unit_ptr": hex(u_ptr),
            "is_air": bool(is_air),
            "is_my_unit": u_ptr == my_unit,
            "pos": [round(float(v), 3) for v in pos] if pos else None,
            "projection": projection,
            "label": unit_label(scanner, u_ptr),
        })
    return all_units, sampled


def build_payload(scanner, base_addr):
    my_unit, my_team = mul.get_local_team(scanner, base_addr)
    chosen_cgame = mul.get_cgame_base(scanner, base_addr)
    chosen_matrix = mul.get_view_matrix(scanner, chosen_cgame)
    chosen_camera_ptr = 0
    if mul.is_valid_ptr(chosen_cgame):
        chosen_camera_ptr = read_u64(scanner, chosen_cgame + mul.OFF_CAMERA_PTR)

    my_pos = mul.get_unit_pos(scanner, my_unit) if mul.is_valid_ptr(my_unit) else None
    my_projection = project_pos(chosen_matrix, my_pos) if chosen_matrix and my_pos else None
    my_projection_perms = projection_permutations(chosen_matrix, my_pos) if chosen_matrix and my_pos else {}
    all_units, sampled_units = sample_units(scanner, chosen_cgame, chosen_matrix, my_unit) if mul.is_valid_ptr(chosen_cgame) else ([], [])

    payload = {
        "timestamp": datetime.now().isoformat(),
        "pid": getattr(scanner, "pid", 0),
        "image_base": hex(base_addr),
        "scanner_last_error": getattr(scanner, "last_error", ""),
        "offsets": {
            "manager_offset": hex(mul.MANAGER_OFFSET),
            "camera_ptr": hex(mul.OFF_CAMERA_PTR),
            "view_matrix": hex(mul.OFF_VIEW_MATRIX),
            "chosen_matrix_off": hex(mul.LAST_VIEW_MATRIX_OFF) if getattr(mul, "LAST_VIEW_MATRIX_OFF", 0) else "0x0",
            "unit_x": hex(mul.OFF_UNIT_X),
            "ground_units": hex(mul.OFF_GROUND_UNITS[0]),
            "air_units": hex(mul.OFF_AIR_UNITS[0]),
        },
        "chosen": {
            "my_unit": hex(my_unit) if my_unit else "0x0",
            "my_team": my_team,
            "my_pos": [round(float(v), 3) for v in my_pos] if my_pos else None,
            "my_projection": my_projection,
            "my_projection_permutations": my_projection_perms,
            "cgame_ptr": hex(chosen_cgame) if chosen_cgame else "0x0",
            "camera_ptr": hex(chosen_camera_ptr) if chosen_camera_ptr else "0x0",
            "camera_off": hex(mul.LAST_VIEW_MATRIX_CAMERA_OFF) if getattr(mul, "LAST_VIEW_MATRIX_CAMERA_OFF", 0) else "0x0",
            "matrix_off": hex(mul.LAST_VIEW_MATRIX_OFF) if getattr(mul, "LAST_VIEW_MATRIX_OFF", 0) else "0x0",
            "projection_mode": (getattr(mul, "LAST_VIEW_PROJECTION_MODE", None) or {}).get("name"),
            "matrix_ok": chosen_matrix is not None,
            "matrix_signature": matrix_signature(chosen_matrix),
            "units_total": len(all_units),
        },
        "manager_candidates": candidate_details(scanner, base_addr, my_unit),
        "sampled_units": sampled_units,
    }
    return payload


def payload_signature(payload):
    chosen = payload.get("chosen") or {}
    return {
        "my_unit": chosen.get("my_unit"),
        "cgame_ptr": chosen.get("cgame_ptr"),
        "camera_ptr": chosen.get("camera_ptr"),
        "matrix_signature": chosen.get("matrix_signature"),
        "units_total": chosen.get("units_total"),
        "my_projection": chosen.get("my_projection"),
    }


def write_dump(payload, prefix):
    os.makedirs("dumps", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join("dumps", f"{prefix}_{stamp}.json")
    txt_path = os.path.join("dumps", f"{prefix}_{stamp}.txt")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    if isinstance(payload, list):
        lines = [
            "ESP RUNTIME WATCH",
            "=" * 80,
            json.dumps(payload, indent=2, ensure_ascii=False),
            "",
        ]
    else:
        lines = [
            "ESP RUNTIME SNAPSHOT DUMPER",
            "=" * 80,
            f"Timestamp: {payload.get('timestamp')}",
            f"PID: {payload.get('pid')}",
            f"Image Base: {payload.get('image_base')}",
            f"ScannerErr: {payload.get('scanner_last_error')}",
            "",
            "CHOSEN",
            json.dumps(payload.get("chosen", {}), indent=2, ensure_ascii=False),
            "",
            "MANAGER CANDIDATES",
            json.dumps(payload.get("manager_candidates", []), indent=2, ensure_ascii=False),
            "",
            "SAMPLED UNITS",
            json.dumps(payload.get("sampled_units", []), indent=2, ensure_ascii=False),
            "",
        ]
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return json_path, txt_path


def run_single(scanner, base_addr):
    payload = build_payload(scanner, base_addr)
    json_path, txt_path = write_dump(payload, "esp_runtime_snapshot")
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
            if json.dumps(sig, sort_keys=True, ensure_ascii=False) != json.dumps(last_sig, sort_keys=True, ensure_ascii=False):
                history.append(payload)
                idx = len(history)
                chosen = payload.get("chosen") or {}
                print(
                    f"[+] Snapshot #{idx}: my={chosen.get('my_unit')} cgame={chosen.get('cgame_ptr')} "
                    f"cam={chosen.get('camera_ptr')} units={chosen.get('units_total')} "
                    f"my_proj={chosen.get('my_projection')}"
                )
                last_sig = sig
            time.sleep(WATCH_POLL_SECONDS)
    except KeyboardInterrupt:
        print("[*] Watch stopped by user.")

    if history:
        json_path, txt_path = write_dump(history, "esp_runtime_watch")
        print(f"[+] WATCH JSON: {json_path}")
        print(f"[+] WATCH TEXT: {txt_path}")


def main():
    print("=" * 80)
    print("ESP RUNTIME SNAPSHOT DUMPER")
    print("=" * 80)
    print("Usage:")
    print("  sudo venv/bin/python tools/esp_runtime_snapshot_dumper.py")
    print("  sudo venv/bin/python tools/esp_runtime_snapshot_dumper.py --watch")
    print("-" * 80)
    print()

    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)

    if "--watch" in sys.argv[1:]:
        run_watch(scanner, base_addr)
    else:
        run_single(scanner, base_addr)


if __name__ == "__main__":
    main()
