import os
import sys
import json
import time
import math
import glob
import struct

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets


LATEST_JSON = os.path.join(PROJECT_ROOT, "dumps", "01_my_unit_velocity_scan_latest.json")
JSON_GLOB = os.path.join(PROJECT_ROOT, "dumps", "01_my_unit_velocity_scan_*.json")


def load_scan_json():
    if os.path.exists(LATEST_JSON):
        with open(LATEST_JSON, "r", encoding="utf-8") as f:
            return json.load(f), LATEST_JSON

    files = sorted(
        (
            p
            for p in glob.glob(JSON_GLOB)
            if not p.endswith("_latest.json")
        ),
        key=os.path.getmtime,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError("ไม่พบไฟล์ scan json ใน dumps/")
    with open(files[0], "r", encoding="utf-8") as f:
        return json.load(f), files[0]


def clear_screen():
    os.system("clear")


def read_vec(scanner, base_ptr, vel_off, data_type):
    if base_ptr < 0x10000:
        return None
    try:
        if data_type == "DOUBLE":
            raw = scanner.read_mem(base_ptr + vel_off, 24)
            if not raw:
                return None
            vec = struct.unpack("<ddd", raw)
        else:
            raw = scanner.read_mem(base_ptr + vel_off, 12)
            if not raw:
                return None
            vec = struct.unpack("<fff", raw)
        if not all(math.isfinite(v) for v in vec):
            return None
        return vec
    except Exception:
        return None


def speed_kmh(vec):
    return math.sqrt(vec[0] * vec[0] + vec[1] * vec[1] + vec[2] * vec[2]) * 3.6


def build_monitors(scanner, seed_candidates):
    monitors = []
    for cand in seed_candidates:
        unit_ptr = int(cand["unit_ptr"])
        move_ptr_off = int(cand["move_ptr_offset"])
        vel_off = int(cand["vel_offset"])
        data_type = cand["data_type"]

        move_raw = scanner.read_mem(unit_ptr + move_ptr_off, 8)
        if not move_raw:
            continue
        move_ptr = struct.unpack("<Q", move_raw)[0]
        if move_ptr < 0x10000:
            continue

        unit_vec = read_vec(scanner, unit_ptr, vel_off, data_type)
        move_vec = read_vec(scanner, move_ptr, vel_off, data_type)

        monitors.append(
            {
                "unit_ptr": unit_ptr,
                "move_ptr_off": move_ptr_off,
                "move_ptr": move_ptr,
                "vel_off": vel_off,
                "data_type": data_type,
                "unit_last": unit_vec,
                "move_last": move_vec,
                "unit_ticks": 0,
                "move_ticks": 0,
                "unit_reads": 0,
                "move_reads": 0,
            }
        )
    return monitors


def monitor_candidates(monitors, scanner, duration=2.0, sleep_s=0.0):
    if not monitors:
        return monitors, 0, duration

    start = time.time()
    loops = 0
    while time.time() - start < duration:
        loops += 1
        for item in monitors:
            unit_vec = read_vec(scanner, item["unit_ptr"], item["vel_off"], item["data_type"])
            move_vec = read_vec(scanner, item["move_ptr"], item["vel_off"], item["data_type"])

            if unit_vec is not None:
                item["unit_reads"] += 1
                if item["unit_last"] is not None:
                    diff = (
                        abs(unit_vec[0] - item["unit_last"][0])
                        + abs(unit_vec[1] - item["unit_last"][1])
                        + abs(unit_vec[2] - item["unit_last"][2])
                    )
                    if diff > 0.001:
                        item["unit_ticks"] += 1
                item["unit_last"] = unit_vec

            if move_vec is not None:
                item["move_reads"] += 1
                if item["move_last"] is not None:
                    diff = (
                        abs(move_vec[0] - item["move_last"][0])
                        + abs(move_vec[1] - item["move_last"][1])
                        + abs(move_vec[2] - item["move_last"][2])
                    )
                    if diff > 0.001:
                        item["move_ticks"] += 1
                item["move_last"] = move_vec

        if sleep_s > 0.0:
            time.sleep(sleep_s)

    elapsed = max(time.time() - start, 1e-6)
    for item in monitors:
        item["unit_hz"] = item["unit_ticks"] / elapsed
        item["move_hz"] = item["move_ticks"] / elapsed
    return monitors, loops, elapsed


def print_report(monitors, loops, elapsed, source_path, scan_payload):
    clear_screen()
    print("==================================================")
    print("📈 WTM JSON TICK RATE SCANNER")
    print("==================================================")
    print(f"JSON: {source_path}")
    print(f"Captured: {scan_payload.get('captured_at_text', '-')}")
    print(f"Candidates: {scan_payload.get('candidate_count', 0)}")
    print(f"Monitor Time: {elapsed:.2f}s | Loop Rate: {loops / elapsed:.1f} Hz")
    print("==================================================")

    if not monitors:
        print("[-] ไม่มี candidate ที่อ่านได้จาก JSON นี้")
        return

    by_move = sorted(monitors, key=lambda x: x["move_hz"], reverse=True)
    by_unit = sorted(monitors, key=lambda x: x["unit_hz"], reverse=True)

    print("\n🏆 TOP MOVE_PTR TICK RATE")
    for idx, item in enumerate(by_move[:10], 1):
        vec = item["move_last"]
        spd = speed_kmh(vec) if vec else 0.0
        print(
            f"{idx:02d}. unit={hex(item['unit_ptr'])} move_off=0x{item['move_ptr_off']:04X} "
            f"move_ptr={hex(item['move_ptr'])} vel=0x{item['vel_off']:04X} {item['data_type']} "
            f"| Hz:{item['move_hz']:.1f} ticks:{item['move_ticks']} speed:{spd:.1f}"
        )

    print("\n🏆 TOP UNIT_PTR TICK RATE")
    for idx, item in enumerate(by_unit[:10], 1):
        vec = item["unit_last"]
        spd = speed_kmh(vec) if vec else 0.0
        print(
            f"{idx:02d}. unit={hex(item['unit_ptr'])} move_off=0x{item['move_ptr_off']:04X} "
            f"vel=0x{item['vel_off']:04X} {item['data_type']} "
            f"| Hz:{item['unit_hz']:.1f} ticks:{item['unit_ticks']} speed:{spd:.1f}"
        )


def main():
    payload, source_path = load_scan_json()
    candidates = payload.get("candidates", [])
    if not candidates:
        print("[-] JSON ไม่มี candidates")
        return

    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)

    monitors = build_monitors(scanner, candidates)
    if not monitors:
        print("[-] ไม่มี candidate ที่อ่านได้จาก JSON นี้")
        return

    try:
        while True:
            for item in monitors:
                item["unit_ticks"] = 0
                item["move_ticks"] = 0
                item["unit_reads"] = 0
                item["move_reads"] = 0
            monitors, loops, elapsed = monitor_candidates(monitors, scanner, duration=2.0)
            print_report(monitors, loops, elapsed, source_path, payload)
            print("\n[Ctrl+C] ออก")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
