import json
import math
import os
import struct
import sys
import time
from collections import Counter
from datetime import datetime

try:
    import keyboard
    HAS_KEYBOARD = True
except Exception:
    keyboard = None
    HAS_KEYBOARD = False

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul

SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
SAMPLES_PER_PHASE = 8
SAMPLE_DELAY = 0.10
MAX_UNITS = 16
PHASES = [
    ("still", "อย่าขยับกล้อง"),
    ("left", "หมุนกล้องไปทางซ้าย"),
    ("right", "หมุนกล้องไปทางขวา"),
    ("up", "เงยกล้องขึ้น"),
    ("down", "กดกล้องลง"),
]


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
    return sum(1 for v in values if abs(v) > 1e-6) >= 6


def read_matrix(scanner, cgame_ptr, cam_off, matrix_off):
    camera_ptr = read_u64(scanner, cgame_ptr + cam_off)
    if not mul.is_valid_ptr(camera_ptr):
        return 0, None
    raw = scanner.read_mem(camera_ptr + matrix_off, 64)
    if not raw or len(raw) < 64:
        return camera_ptr, None
    values = struct.unpack("<16f", raw[:64])
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


def sample_units(scanner, cgame_ptr, matrix, my_unit):
    rows = []
    for idx, (u_ptr, is_air) in enumerate(mul.get_all_units(scanner, cgame_ptr)[:MAX_UNITS]):
        pos = mul.get_unit_pos(scanner, u_ptr)
        rows.append({
            "idx": idx,
            "unit_ptr": hex(u_ptr),
            "is_air": bool(is_air),
            "is_my_unit": u_ptr == my_unit,
            "pos": [round(float(v), 3) for v in pos] if pos else None,
            "projection": project_pos(matrix, pos) if matrix and pos else None,
        })
    return rows


def candidate_details(scanner, base_addr, my_unit):
    rows = []
    my_pos = mul.get_unit_pos(scanner, my_unit) if mul.is_valid_ptr(my_unit) else None
    for idx, offset in enumerate(mul._manager_offsets()):
        cgame_ptr = read_u64(scanner, base_addr + offset)
        if not mul.is_valid_ptr(cgame_ptr):
            continue
        live_score, total_units = mul._score_cgame_live(scanner, cgame_ptr)
        contains_my_unit = mul._cgame_contains_unit(scanner, cgame_ptr, my_unit)
        for matrix_off in (0x130, 0x140, 0x1B0, 0x1C0, 0x210):
            camera_ptr, matrix = read_matrix(scanner, cgame_ptr, mul.OFF_CAMERA_PTR, matrix_off)
            my_projection = project_pos(matrix, my_pos) if matrix and my_pos else None
            rows.append({
                "manager_offset": hex(offset),
                "cgame_ptr": hex(cgame_ptr),
                "contains_my_unit": contains_my_unit,
                "live_score": live_score,
                "total_units": total_units,
                "camera_ptr": hex(camera_ptr) if camera_ptr else "0x0",
                "camera_off": hex(mul.OFF_CAMERA_PTR),
                "matrix_off": hex(matrix_off),
                "matrix_ok": matrix is not None,
                "matrix_signature": matrix_signature(matrix),
                "my_projection": my_projection,
            })
    return rows


def build_payload(scanner, base_addr, phase_name):
    my_unit, my_team = mul.get_local_team(scanner, base_addr)
    chosen_cgame = mul.get_cgame_base(scanner, base_addr)
    chosen_matrix = mul.get_view_matrix(scanner, chosen_cgame)
    chosen_camera_ptr = read_u64(scanner, chosen_cgame + mul.OFF_CAMERA_PTR) if mul.is_valid_ptr(chosen_cgame) else 0
    my_pos = mul.get_unit_pos(scanner, my_unit) if mul.is_valid_ptr(my_unit) else None
    return {
        "timestamp": datetime.now().isoformat(),
        "phase": phase_name,
        "chosen": {
            "my_unit": hex(my_unit) if my_unit else "0x0",
            "my_team": my_team,
            "my_pos": [round(float(v), 3) for v in my_pos] if my_pos else None,
            "my_projection": project_pos(chosen_matrix, my_pos) if chosen_matrix and my_pos else None,
            "cgame_ptr": hex(chosen_cgame) if chosen_cgame else "0x0",
            "camera_ptr": hex(chosen_camera_ptr) if chosen_camera_ptr else "0x0",
            "camera_off": hex(mul.LAST_VIEW_MATRIX_CAMERA_OFF) if getattr(mul, "LAST_VIEW_MATRIX_CAMERA_OFF", 0) else "0x0",
            "matrix_off": hex(mul.LAST_VIEW_MATRIX_OFF) if getattr(mul, "LAST_VIEW_MATRIX_OFF", 0) else "0x0",
            "projection_mode": (getattr(mul, "LAST_VIEW_PROJECTION_MODE", None) or {}).get("name"),
            "matrix_signature": matrix_signature(chosen_matrix),
        },
        "manager_candidates": candidate_details(scanner, base_addr, my_unit),
        "sampled_units": sample_units(scanner, chosen_cgame, chosen_matrix, my_unit) if mul.is_valid_ptr(chosen_cgame) else [],
    }


def summarize_phase(samples):
    chosen_counter = Counter()
    mode_counter = Counter()
    projs = []
    for payload in samples:
        chosen = payload.get("chosen") or {}
        chosen_counter[(chosen.get("cgame_ptr"), chosen.get("camera_ptr"), chosen.get("matrix_off"))] += 1
        if chosen.get("projection_mode"):
            mode_counter[chosen["projection_mode"]] += 1
        if chosen.get("my_projection"):
            projs.append(chosen["my_projection"])
    best_triplet, best_count = (None, 0)
    if chosen_counter:
        best_triplet, best_count = chosen_counter.most_common(1)[0]
    return {
        "samples": len(samples),
        "chosen_counter": {f"{k[0]}|{k[1]}|{k[2]}": v for k, v in chosen_counter.items()},
        "projection_mode_counter": dict(mode_counter),
        "best_triplet": {
            "cgame_ptr": best_triplet[0] if best_triplet else None,
            "camera_ptr": best_triplet[1] if best_triplet else None,
            "matrix_off": best_triplet[2] if best_triplet else None,
            "count": best_count,
        },
        "my_projection_series": projs,
    }


def write_dump(payload):
    os.makedirs("dumps", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join("dumps", f"view_matrix_phase_dump_{stamp}.json")
    txt_path = os.path.join("dumps", f"view_matrix_phase_dump_{stamp}.txt")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    lines = [
        "VIEW MATRIX PHASE DUMPER",
        "=" * 80,
        f"Timestamp: {payload.get('timestamp')}",
        "",
        "PHASE SUMMARY",
        json.dumps(payload.get("phase_summary", {}), indent=2, ensure_ascii=False),
        "",
        "FULL JSON",
        json.dumps(payload, indent=2, ensure_ascii=False),
    ]
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return json_path, txt_path


def capture_phase(scanner, base_addr, phase_name):
    samples = []
    for _ in range(SAMPLES_PER_PHASE):
        samples.append(build_payload(scanner, base_addr, phase_name))
        time.sleep(SAMPLE_DELAY)
    return samples


def main():
    print("=" * 80)
    print("VIEW MATRIX PHASE DUMPER")
    print("=" * 80)
    print("Phases:")
    print("  still -> left -> right -> up -> down")
    print("Keys:")
    print("  F6 = capture current phase")
    print("  F10 = abort")
    print("-" * 80)
    print("")

    if not HAS_KEYBOARD:
        print("[-] keyboard module not available. install with: pip install keyboard")
        return

    pid = get_game_pid()
    if not pid:
        print("[-] ไม่พบ process ของเกม 'aces'")
        return
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    try:
        init_dynamic_offsets(scanner, base_addr)
        all_samples = []
        phase_summary = {}
        for phase_name, prompt in PHASES:
            print(f"[*] Phase {phase_name}: {prompt}")
            print("[*] จัดกล้องในเกมแล้วกด F6 เพื่อ capture phase นี้")
            print("[*] กด F10 เพื่อยกเลิก")
            while True:
                if keyboard.is_pressed("f10"):
                    print("[-] Aborted by user.")
                    return
                if keyboard.is_pressed("f6"):
                    while keyboard.is_pressed("f6"):
                        time.sleep(0.05)
                    break
                time.sleep(0.05)
            samples = capture_phase(scanner, base_addr, phase_name)
            all_samples.extend(samples)
            phase_summary[phase_name] = summarize_phase(samples)
            print(f"[+] Captured {len(samples)} samples for phase={phase_name}")
        payload = {
            "timestamp": datetime.now().isoformat(),
            "phase_order": [name for name, _ in PHASES],
            "phase_summary": phase_summary,
            "samples": all_samples,
        }
        json_path, txt_path = write_dump(payload)
        print(f"[+] JSON: {json_path}")
        print(f"[+] TEXT: {txt_path}")
    finally:
        scanner.close()


if __name__ == "__main__":
    main()
