#!/usr/bin/env python3
"""
02_vel_hunter_scanner.py — SMART Velocity Hunter Scanner (±Tolerance Mode)

สแกน Memory ของศัตรูที่อยู่ใกล้ Crosshair ที่สุด เพื่อหา Offset ที่มี
ค่าคล้ายความเร็ว (Velocity) โดยเปรียบเทียบกับ Baseline ที่อ่านจาก
OFF_AIR_MOVEMENT (0x0018) → OFF_AIR_VEL (0x0318)

ขั้นตอน:
  1. หา Baseline Velocity จาก Offset ที่รู้อยู่แล้ว (Network 5Hz)
  2. กวาด Memory แบบ ±Tolerance หา Offset ที่มีค่าใกล้เคียง
  3. Monitor Tick-Rate เพื่อหาตัว Interpolated (สมูท) ที่อัปเดตเร็วกว่า 5Hz
"""

import os
import sys
import struct
import time
import math
import json

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import (
    get_cgame_base, get_all_units, get_local_team,
    get_unit_pos, get_view_matrix, world_to_screen,
    get_unit_status,
    is_valid_ptr,
    OFF_AIR_MOVEMENT, OFF_AIR_VEL,
)

# ─── ค่าเริ่มต้น ─────────────────────────────────────────
SCREEN_WIDTH  = 2560
SCREEN_HEIGHT = 1440
CENTER_X      = SCREEN_WIDTH  / 2.0
CENTER_Y      = SCREEN_HEIGHT / 2.0

DEFAULT_TOLERANCE  = 5.0     # ±5 m/s ต่อแกน
DEFAULT_SCAN_SIZE  = 0x4000  # 16 KB
MONITOR_DURATION   = 1.0     # วินาที
MONITOR_SLEEP      = 1 / 144.0
CHANGE_THRESHOLD   = 0.001   # ค่าต่ำสุดที่ถือว่า "เปลี่ยน"
TOP_N              = 10      # โชว์ผลกี่อันดับ
HIGH_TICK_THRESHOLD = 20     # Ticks ≥ นี้ถือว่า High-Tick


# ═══════════════════════════════════════════════════════════
# 1. อ่าน Baseline Velocity (Network 5Hz)
# ═══════════════════════════════════════════════════════════
def read_baseline_velocity(scanner, target_ptr):
    """อ่าน Velocity จาก Move Pointer ที่รู้อยู่แล้ว (0x0018 → 0x0318 Float).

    Returns:
        (velocity_tuple, move_ptr) หรือ (None, 0) ถ้าอ่านไม่ได้
    """
    try:
        move_raw = scanner.read_mem(target_ptr + OFF_AIR_MOVEMENT, 8)
        if not move_raw:
            return None, 0
        move_ptr = struct.unpack("<Q", move_raw)[0]
        if not is_valid_ptr(move_ptr):
            return None, 0

        vel_raw = scanner.read_mem(move_ptr + OFF_AIR_VEL, 12)
        if not vel_raw or len(vel_raw) < 12:
            return None, move_ptr
        vx, vy, vz = struct.unpack("<fff", vel_raw)

        # กรองค่าที่ไม่ใช่ตัวเลข หรือ หยุดนิ่ง
        if not all(math.isfinite(v) for v in (vx, vy, vz)):
            return None, move_ptr
        if all(abs(v) <= 0.1 for v in (vx, vy, vz)):
            return None, move_ptr

        return (vx, vy, vz), move_ptr
    except Exception:
        return None, 0


# ═══════════════════════════════════════════════════════════
# 2. สแกน Memory หา Candidate Offsets
# ═══════════════════════════════════════════════════════════
def _scan_buffer_float(buffer, baseline, tolerance, buf_size):
    """สแกนหา vec3 float (12 bytes) ที่ค่าใกล้เคียง baseline ±tolerance."""
    results = []
    bx, by, bz = baseline
    for offset in range(0, buf_size - 11, 4):
        x, y, z = struct.unpack_from("<fff", buffer, offset)
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
            continue
        if abs(x - bx) > tolerance or abs(y - by) > tolerance or abs(z - bz) > tolerance:
            continue
        if all(abs(v) <= 0.1 for v in (x, y, z)):
            continue
        results.append({
            "offset": offset, "type": "FLOAT",
            "last_val": (x, y, z), "ticks": 0,
        })
    return results


def _scan_buffer_double(buffer, baseline, tolerance, buf_size):
    """สแกนหา vec3 double (24 bytes) ที่ค่าใกล้เคียง baseline ±tolerance."""
    results = []
    bx, by, bz = baseline
    for offset in range(0, buf_size - 23, 8):
        x, y, z = struct.unpack_from("<ddd", buffer, offset)
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
            continue
        if abs(x - bx) > tolerance or abs(y - by) > tolerance or abs(z - bz) > tolerance:
            continue
        if all(abs(v) <= 0.1 for v in (x, y, z)):
            continue
        results.append({
            "offset": offset, "type": "DOUBLE",
            "last_val": (x, y, z), "ticks": 0,
        })
    return results


def sweep_memory(scanner, base_ptr, baseline_vel, size=DEFAULT_SCAN_SIZE, tolerance=DEFAULT_TOLERANCE):
    """กวาด memory block ขนาด `size` bytes จาก `base_ptr` หา offset ที่คล้าย baseline."""
    buffer = scanner.read_mem(base_ptr, size)
    if not buffer:
        return []
    buf_size = len(buffer)
    candidates  = _scan_buffer_float(buffer, baseline_vel, tolerance, buf_size)
    candidates += _scan_buffer_double(buffer, baseline_vel, tolerance, buf_size)
    return candidates


# ═══════════════════════════════════════════════════════════
# 3. Monitor Tick-Rate
# ═══════════════════════════════════════════════════════════
def monitor_tick_rates(scanner, base_ptr, candidates, duration=MONITOR_DURATION):
    """เฝ้าดู candidates เป็นเวลา `duration` วินาที นับจำนวนครั้งที่ค่าเปลี่ยน."""
    if not candidates:
        return 0, duration

    start = time.time()
    loops = 0

    while time.time() - start < duration:
        loops += 1
        for cand in candidates:
            try:
                addr = base_ptr + cand["offset"]
                if cand["type"] == "FLOAT":
                    raw = scanner.read_mem(addr, 12)
                    if not raw or len(raw) < 12:
                        continue
                    val = struct.unpack("<fff", raw)
                else:
                    raw = scanner.read_mem(addr, 24)
                    if not raw or len(raw) < 24:
                        continue
                    val = struct.unpack("<ddd", raw)

                diff = sum(abs(val[i] - cand["last_val"][i]) for i in range(3))
                if diff > CHANGE_THRESHOLD:
                    cand["ticks"] += 1
                    cand["last_val"] = val
            except Exception:
                pass

        time.sleep(MONITOR_SLEEP)

    elapsed = max(time.time() - start, 1e-6)
    return loops, elapsed


# ═══════════════════════════════════════════════════════════
# 4. Target Lock — ล็อกเป้าด้วย 3D Distance ใกล้สุด
# ═══════════════════════════════════════════════════════════
def calc_3d_distance(pos_a, pos_b):
    """คำนวณระยะ 3D (เมตร) ระหว่างสองตำแหน่ง."""
    return math.sqrt(
        (pos_a[0] - pos_b[0]) ** 2 +
        (pos_a[1] - pos_b[1]) ** 2 +
        (pos_a[2] - pos_b[2]) ** 2
    )


def find_closest_enemy_by_distance(scanner, cgame_base, my_unit_ptr):
    """หา unit pointer ของศัตรูที่อยู่ใกล้ที่สุด.

    ลำดับ:
      1. ลองหาด้วย 3D world distance (ต้องมี my_pos)
      2. Fallback: หาด้วย screen-space distance (crosshair ใกล้สุด)
      3. Last resort: เอาตัวแรกที่อ่าน position ได้

    Returns:
        (unit_ptr, distance_m, unit_name) หรือ (None, 0, "")
    """
    all_units = get_all_units(scanner, cgame_base)
    if not all_units:
        print(f"   [DBG] get_all_units → empty")
        return None, 0, ""

    print(f"   [DBG] Units found: {len(all_units)}")

    my_pos = get_unit_pos(scanner, my_unit_ptr) if my_unit_ptr else None

    # ── Strategy 1: 3D World Distance ──
    if my_pos:
        best_dist = float("inf")
        best_ptr  = None
        for u_ptr, _is_air in all_units:
            if my_unit_ptr and u_ptr == my_unit_ptr:
                continue
            u_pos = get_unit_pos(scanner, u_ptr)
            if not u_pos:
                continue
            dist = calc_3d_distance(my_pos, u_pos)
            if dist < best_dist:
                best_dist = dist
                best_ptr  = u_ptr
        if best_ptr:
            name = _get_unit_name(scanner, best_ptr)
            print(f"   [DBG] Locked by 3D distance: {hex(best_ptr)} ({best_dist:.0f}m) {name}")
            return best_ptr, best_dist, name

    # ── Strategy 2: Screen-Space (Crosshair) Distance ──
    print(f"   [DBG] my_pos unavailable, fallback to screen-space")
    view_matrix = get_view_matrix(scanner, cgame_base)
    if view_matrix:
        best_dist = float("inf")
        best_ptr  = None
        for u_ptr, _is_air in all_units:
            if my_unit_ptr and u_ptr == my_unit_ptr:
                continue
            u_pos = get_unit_pos(scanner, u_ptr)
            if not u_pos:
                continue
            scr = world_to_screen(view_matrix, u_pos[0], u_pos[1], u_pos[2], SCREEN_WIDTH, SCREEN_HEIGHT)
            if not scr or scr[2] <= 0:
                continue
            dist = math.hypot(scr[0] - CENTER_X, scr[1] - CENTER_Y)
            if dist < best_dist:
                best_dist = dist
                best_ptr  = u_ptr
        if best_ptr:
            name = _get_unit_name(scanner, best_ptr)
            print(f"   [DBG] Locked by crosshair: {hex(best_ptr)} (screen {best_dist:.0f}px) {name}")
            return best_ptr, best_dist, name

    # ── Strategy 3: Last Resort — เอาตัวแรกที่มี position ──
    print(f"   [DBG] crosshair fallback failed, trying first valid unit")
    for u_ptr, _is_air in all_units:
        if my_unit_ptr and u_ptr == my_unit_ptr:
            continue
        u_pos = get_unit_pos(scanner, u_ptr)
        if u_pos:
            name = _get_unit_name(scanner, u_ptr)
            print(f"   [DBG] Locked first valid: {hex(u_ptr)} {name}")
            return u_ptr, 0, name

    print(f"   [DBG] no valid unit found at all")
    return None, 0, ""


def _get_unit_name(scanner, u_ptr):
    """ดึงชื่อ unit แบบ safe."""
    try:
        status = get_unit_status(scanner, u_ptr, read_name=True)
        return status.get("short_name", "") if status else ""
    except Exception:
        return ""


def validate_locked_target(scanner, locked_ptr, my_unit_ptr):
    """ตรวจสอบว่า locked target ยังมีชีวิตและอ่านได้อยู่.

    Returns:
        (is_valid, distance_m, unit_pos)
    """
    try:
        u_pos = get_unit_pos(scanner, locked_ptr)
        if not u_pos:
            return False, 0, None

        my_pos = get_unit_pos(scanner, my_unit_ptr) if my_unit_ptr else None
        dist = calc_3d_distance(my_pos, u_pos) if my_pos else 0

        # ตรวจสอบว่า unit ยังอยู่
        status = get_unit_status(scanner, locked_ptr, read_name=False)
        if status:
            state = status.get("state", 0)
            if state >= 2:  # dead
                return False, dist, u_pos

        return True, dist, u_pos
    except Exception:
        return False, 0, None


# ═══════════════════════════════════════════════════════════
# 5. แสดงผล
# ═══════════════════════════════════════════════════════════
def _hz_label(ticks):
    if ticks >= HIGH_TICK_THRESHOLD:
        return f"⚡ High Tick ({ticks}Hz สมูท)!"
    return f"Low ({ticks}Hz)"


def print_candidates(title, candidates, known_offset=None):
    """พิมพ์ตาราง candidates เรียงตาม ticks สูงสุด."""
    print(f"\n📁 {title}:")
    if not candidates:
        print("   (ไม่พบ Offset ที่เข้าข่าย)")
        return

    candidates.sort(key=lambda c: c["ticks"], reverse=True)
    for c in candidates[:TOP_N]:
        label = _hz_label(c["ticks"])
        extra = ""
        if known_offset is not None and c["offset"] == known_offset:
            extra = " ← (ตัว Network 5Hz)"
        vx, vy, vz = c["last_val"]
        print(f"   [{hex(c['offset']):>8s}] | {c['type']:6s} | Ticks: {c['ticks']:3d} | {label}{extra}")
        print(f"            ค่าล่าสุด: X:{vx:>8.2f}  Y:{vy:>8.2f}  Z:{vz:>8.2f}")


# ═══════════════════════════════════════════════════════════
# 6. บันทึกผล
# ═══════════════════════════════════════════════════════════
def save_results(cand_unit, cand_move, baseline_vel, tolerance, scan_size):
    """บันทึก candidates ลง JSON ไฟล์."""
    os.makedirs(os.path.join(PROJECT_ROOT, "dumps"), exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    payload = {
        "captured_at": time.time(),
        "captured_at_text": time.strftime("%Y-%m-%d %H:%M:%S"),
        "baseline_vel": list(baseline_vel),
        "tolerance": tolerance,
        "scan_size_hex": hex(scan_size),
        "unit_candidates": [
            {"offset": hex(c["offset"]), "type": c["type"],
             "ticks": c["ticks"], "last_val": list(c["last_val"])}
            for c in sorted(cand_unit, key=lambda x: x["ticks"], reverse=True)[:TOP_N]
        ],
        "move_candidates": [
            {"offset": hex(c["offset"]), "type": c["type"],
             "ticks": c["ticks"], "last_val": list(c["last_val"])}
            for c in sorted(cand_move, key=lambda x: x["ticks"], reverse=True)[:TOP_N]
        ],
    }
    filename = os.path.join(PROJECT_ROOT, "dumps", f"02_vel_hunter_{timestamp}.json")
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return filename


# ═══════════════════════════════════════════════════════════
# 7. Interactive Menu
# ═══════════════════════════════════════════════════════════
def print_settings(tolerance, scan_size, monitor_dur):
    print(f"   ⚙️  Tolerance: ±{tolerance:.1f} m/s  |  Scan: {hex(scan_size)}  |  Monitor: {monitor_dur:.1f}s")


def settings_menu(tolerance, scan_size, monitor_dur):
    """เมนูย่อยสำหรับปรับ settings."""
    while True:
        os.system("clear")
        print("=== ⚙️  SETTINGS ===")
        print_settings(tolerance, scan_size, monitor_dur)
        print("\n[1] เปลี่ยน Tolerance (±m/s)")
        print("[2] เปลี่ยน Scan Size (bytes)")
        print("[3] เปลี่ยน Monitor Duration (วินาที)")
        print("[0] กลับเมนูหลัก")
        choice = input("\n👉 เลือก: ").strip()

        if choice == "0":
            break
        elif choice == "1":
            try:
                tolerance = float(input("   > Tolerance ใหม่: ").strip())
            except ValueError:
                pass
        elif choice == "2":
            try:
                val = input("   > Scan Size ใหม่ (hex, เช่น 0x4000): ").strip()
                scan_size = int(val, 0)
            except ValueError:
                pass
        elif choice == "3":
            try:
                monitor_dur = float(input("   > Monitor Duration (วินาที): ").strip())
            except ValueError:
                pass

    return tolerance, scan_size, monitor_dur


# ═══════════════════════════════════════════════════════════
# 8. Main Loop — Target Lock Mode
# ═══════════════════════════════════════════════════════════
def main():
    print("[*] Starting Velocity Hunter Scanner...")
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_address)

    tolerance   = DEFAULT_TOLERANCE
    scan_size   = DEFAULT_SCAN_SIZE
    monitor_dur = MONITOR_DURATION

    while True:
        os.system("clear")
        print("══════════════════════════════════════════════════")
        print("  🧠 VELOCITY HUNTER SCANNER (Target Lock Mode)")
        print("══════════════════════════════════════════════════")
        print_settings(tolerance, scan_size, monitor_dur)
        print("\n[1] 🔒 สแกน + ล็อกเป้าใกล้สุด (3D Distance)")
        print("[2] ⚙️  Settings")
        print("[0] ❌ ออก")
        choice = input("\n👉 เลือก: ").strip()

        if choice == "0":
            break
        elif choice == "2":
            tolerance, scan_size, monitor_dur = settings_menu(tolerance, scan_size, monitor_dur)
            continue
        elif choice == "1":
            _run_locked_scan(scanner, base_address, tolerance, scan_size, monitor_dur)


def _run_locked_scan(scanner, base_address, tolerance, scan_size, monitor_dur):
    """Target Lock Scan: ล็อกเป้าที่ใกล้ที่สุด แล้วสแกนซ้ำต่อเนื่อง
    จนกว่าเป้าจะตาย/หายไป จึง auto-relock ตัวใหม่"""

    locked_ptr  = None
    locked_name = ""
    locked_dist = 0
    scan_round  = 0

    try:
        while True:
            os.system("clear")
            cgame_base = get_cgame_base(scanner, base_address)
            if not cgame_base:
                print("⏳ รอ CGame Base...")
                time.sleep(0.5)
                continue

            my_unit_ptr, _ = get_local_team(scanner, cgame_base)

            # ── ตรวจสอบ Lock ──
            if locked_ptr:
                is_valid, dist, _u_pos = validate_locked_target(scanner, locked_ptr, my_unit_ptr)
                if not is_valid:
                    print(f"💀 เป้า {locked_name or hex(locked_ptr)} ตาย/หายไป → Auto-Relock...")
                    locked_ptr = None
                    locked_name = ""
                    scan_round = 0
                    time.sleep(0.3)
                else:
                    locked_dist = dist

            # ── หาเป้าใหม่ (ถ้ายังไม่ Lock) ──
            if not locked_ptr:
                target_ptr, dist, name = find_closest_enemy_by_distance(scanner, cgame_base, my_unit_ptr)
                if not target_ptr:
                    print("👀 ไม่พบศัตรู...")
                    time.sleep(0.2)
                    continue
                locked_ptr  = target_ptr
                locked_dist = dist
                locked_name = name
                scan_round  = 0
                print(f"🔒 LOCKED → {name or hex(locked_ptr)}  ({dist:.0f}m)")
                time.sleep(0.3)

            scan_round += 1

            # ── แสดง Header ──
            print("══════════════════════════════════════════════════")
            print(f"  🔒 TARGET LOCKED: {locked_name or hex(locked_ptr)}")
            print(f"     Ptr: {hex(locked_ptr)}  |  Distance: {locked_dist:.0f}m  |  Scan #{scan_round}")
            print("══════════════════════════════════════════════════")
            print_settings(tolerance, scan_size, monitor_dur)

            # ── อ่าน Baseline ──
            baseline_vel, move_ptr = read_baseline_velocity(scanner, locked_ptr)
            if not baseline_vel:
                print("🔴 เป้ายังไม่เคลื่อนที่ (รอ Baseline 5Hz)...")
                time.sleep(0.2)
                continue

            bx, by, bz = baseline_vel
            speed_ms = math.sqrt(bx**2 + by**2 + bz**2)
            print(f"\n✅ Baseline: X:{bx:.2f}  Y:{by:.2f}  Z:{bz:.2f}  ({speed_ms:.1f} m/s = {speed_ms*3.6:.1f} km/h)")
            print(f"   Move Ptr: {hex(move_ptr)}")
            print(f"🔍 กวาด Memory ±{tolerance:.1f} ... (กำลังสแกน)")

            # ── Sweep ──
            cand_unit = sweep_memory(scanner, locked_ptr, baseline_vel, scan_size, tolerance)
            cand_move = sweep_memory(scanner, move_ptr, baseline_vel, scan_size, tolerance) if is_valid_ptr(move_ptr) else []

            # ── Monitor Tick-Rate ──
            loops_u, elapsed_u = monitor_tick_rates(scanner, locked_ptr, cand_unit, monitor_dur)
            loops_m, elapsed_m = monitor_tick_rates(scanner, move_ptr, cand_move, monitor_dur) if cand_move else (0, 0)

            # ── แสดงผลลัพธ์ ──
            os.system("clear")
            print("══════════════════════════════════════════════════")
            print(f"  🏆 RESULTS — Scan #{scan_round}")
            print(f"  🔒 {locked_name or hex(locked_ptr)}  |  {locked_dist:.0f}m")
            print("══════════════════════════════════════════════════")
            print(f"   Baseline: X:{bx:.2f}  Y:{by:.2f}  Z:{bz:.2f}  ({speed_ms*3.6:.1f} km/h)")
            if elapsed_m:
                print(f"   Loop: Unit={loops_u}/{elapsed_u:.1f}s  Move={loops_m}/{elapsed_m:.1f}s")
            else:
                print(f"   Loop: Unit={loops_u}/{elapsed_u:.1f}s")

            print_candidates("กลุ่ม UNIT POINTER (Base)", cand_unit)
            print_candidates("กลุ่ม MOVE POINTER (0x018)", cand_move, known_offset=OFF_AIR_VEL)

            # ── Auto-save ──
            has_high_tick = any(c["ticks"] >= HIGH_TICK_THRESHOLD for c in cand_unit + cand_move)
            if has_high_tick:
                saved = save_results(cand_unit, cand_move, baseline_vel, tolerance, scan_size)
                print(f"\n💾 Auto-saved (High Tick found): {saved}")

            print(f"\n[Enter] สแกนรอบ #{scan_round+1} (เป้าเดิม)  |  [r] Relock เป้าใหม่  |  [Ctrl+C] กลับเมนู")
            cmd = input("👉 ").strip().lower()
            if cmd == "r":
                locked_ptr = None
                locked_name = ""
                scan_round = 0
                print("🔓 ปลดล็อก → หาเป้าใหม่...")
                time.sleep(0.3)

    except KeyboardInterrupt:
        print("\n↩️  กลับเมนูหลัก...")
        time.sleep(0.3)


if __name__ == "__main__":
    main()