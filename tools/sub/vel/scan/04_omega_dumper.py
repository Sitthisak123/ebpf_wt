#!/usr/bin/env python3
"""
04_omega_dumper.py — War Thunder Angular Velocity (Omega) Finder & Live Dumper

เครื่องมือสำหรับวิเคราะห์และค้นหา Offset ของ Angular Velocity (Omega / ω)
รองรับทั้ง:
  1. การตรวจสอบ Candidates ที่ทำนายจากโครงสร้าง Memory (0x0018, 0x0D48, 0x24C0)
  2. Live Watcher: เฝ้าดูค่าแบบ Realtime พร้อมเช็คการหมุน (Roll / Pitch / Yaw)
  3. Differential Calibration Scanner: สแกนเปรียบเทียบตอน "บินตรง" vs "ควงสว่าน (Roll)"
     เพื่อตรวจจับ Offset ของ Omega ที่แท้จริงแบบ 100%
"""

import os
import sys
import struct
import time
import math

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import (
    get_cgame_base, get_local_team, get_unit_pos,
    is_valid_ptr, OFF_AIR_MOVEMENT, OFF_AIR_VEL, OFF_AIR_OMEGA
)

# ═══════════════════════════════════════════════════════════
# 🎯 PREDICTED OMEGA CANDIDATES (จากการวิเคราะห์โครงสร้าง Stride)
# ═══════════════════════════════════════════════════════════
# 1. Primary Move Ptr (u_ptr + 0x0018) — Float Vec3 (12 bytes)
#    ข้อมูล Vel ในแพตช์ปัจจุบันเรียงทุกๆ 0x40 bytes:
#    0x318, 0x358, 0x398, 0x3D8, 0x418, 0x458, 0x498, 0x4D8, 0x518
#    สังเกตว่า 0x03F8 ในอดีต คือ 0x03D8 + 0x20
#    ดังนั้น Omega ประจำแต่ละ Frame จะอยู่ที่ Vel + 0x20
PREDICTED_0018_CANDIDATES = [
    {"name": "FLT_018_550 (⭐ VERIFIED 2026-09)", "move": 0x0018, "off": 0x0550, "type": "FLOAT"},
    {"name": "FLT_018_3F8 (Historic 03/2026)", "move": 0x0018, "off": 0x03F8, "type": "FLOAT"},
    {"name": "FLT_018_338 (0x318+0x20)", "move": 0x0018, "off": 0x0338, "type": "FLOAT"},
    {"name": "FLT_018_378 (0x358+0x20)", "move": 0x0018, "off": 0x0378, "type": "FLOAT"},
    {"name": "FLT_018_3B8 (0x398+0x20)", "move": 0x0018, "off": 0x03B8, "type": "FLOAT"},
    {"name": "FLT_018_438 (0x418+0x20)", "move": 0x0018, "off": 0x0438, "type": "FLOAT"},
    {"name": "FLT_018_478 (0x458+0x20)", "move": 0x0018, "off": 0x0478, "type": "FLOAT"},
    {"name": "FLT_018_4B8 (0x498+0x20)", "move": 0x0018, "off": 0x04B8, "type": "FLOAT"},
    {"name": "FLT_018_4F8 (0x4D8+0x20)", "move": 0x0018, "off": 0x04F8, "type": "FLOAT"},
    {"name": "FLT_018_538 (0x518+0x20)", "move": 0x0018, "off": 0x0538, "type": "FLOAT"},
]

# 2. High-Tick Player Move Ptr (u_ptr + 0x0D48 / 0x0D50) — Double/Float Vec3
#    Vel อยู่ที่ 0x0068, 0x00C0, 0x00C8, 0x00D0
PREDICTED_0D48_CANDIDATES = [
    {"name": "DBL_0D48_098 (⭐ VERIFIED 2026-09)", "move": 0x0D48, "off": 0x0098, "type": "DOUBLE"},
    {"name": "DBL_0D48_080 (Post-Vel)", "move": 0x0D48, "off": 0x0080, "type": "DOUBLE"},
    {"name": "DBL_0D48_0E0 (Post-0xD0)", "move": 0x0D48, "off": 0x00E0, "type": "DOUBLE"},
    {"name": "DBL_0D48_0F8 (Block End)", "move": 0x0D48, "off": 0x00F8, "type": "DOUBLE"},
    {"name": "FLT_0D48_080", "move": 0x0D48, "off": 0x0080, "type": "FLOAT"},
    {"name": "FLT_0D48_098", "move": 0x0D48, "off": 0x0098, "type": "FLOAT"},
    {"name": "FLT_0D48_0E0", "move": 0x0D48, "off": 0x00E0, "type": "FLOAT"},
]

# 3. High-Tick Air Move Ptr (u_ptr + 0x24C0 / 0x24C8) — Float Vec3
#    Vel อยู่ที่ 0x0E90 และ 0x0DB8
PREDICTED_24C0_CANDIDATES = [
    {"name": "FLT_24C0_EB0 (0xE90+0x20)", "move": 0x24C0, "off": 0x0EB0, "type": "FLOAT"},
    {"name": "FLT_24C0_E70 (0xE90-0x20)", "move": 0x24C0, "off": 0x0E70, "type": "FLOAT"},
    {"name": "FLT_24C8_DD8 (0xDB8+0x20)", "move": 0x24C8, "off": 0x0DD8, "type": "FLOAT"},
    {"name": "FLT_24C8_D98 (0xDB8-0x20)", "move": 0x24C8, "off": 0x0D98, "type": "FLOAT"},
]

ALL_PREDICTED = PREDICTED_0018_CANDIDATES + PREDICTED_0D48_CANDIDATES + PREDICTED_24C0_CANDIDATES


def read_vec(scanner, base_ptr, offset, data_type):
    """อ่าน vec3 (FLOAT หรือ DOUBLE) จาก base_ptr + offset."""
    if not is_valid_ptr(base_ptr):
        return None
    try:
        size = 24 if data_type == "DOUBLE" else 12
        fmt = "<ddd" if data_type == "DOUBLE" else "<fff"
        raw = scanner.read_mem(base_ptr + offset, size)
        if not raw or len(raw) < size:
            return None
        vec = struct.unpack(fmt, raw)
        if not all(math.isfinite(v) for v in vec):
            return None
        return vec
    except Exception:
        return None


def vec_mag(vec):
    """คำนวณ Magnitude ของเวกเตอร์ 3D."""
    if not vec:
        return 0.0
    return math.sqrt(vec[0]**2 + vec[1]**2 + vec[2]**2)


def get_move_pointer(scanner, u_ptr, move_off):
    """อ่าน Move Pointer จาก u_ptr + move_off."""
    try:
        raw = scanner.read_mem(u_ptr + move_off, 8)
        if not raw or len(raw) < 8:
            return 0
        ptr = struct.unpack("<Q", raw)[0]
        return ptr if is_valid_ptr(ptr) else 0
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════
# MODE 1: LIVE WATCHER (ดูค่าแบบ Realtime)
# ═══════════════════════════════════════════════════════════
def run_live_watcher(scanner, my_unit_ptr):
    print("\n[*] เข้าสู่โหมด Live Watcher (กด Ctrl+C เพื่อออก)...")
    time.sleep(1)

    move_cache = {}
    last_vals = {}
    tick_counts = {c["name"]: 0 for c in ALL_PREDICTED}
    last_tick_time = time.time()

    try:
        while True:
            os.system("clear")
            curr_t = time.time()
            dt = max(curr_t - last_tick_time, 1e-6)

            print("═══════════════════════════════════════════════════════════════════════════════════════")
            print("  🌪️ LIVE OMEGA CANDIDATES MONITOR (Angular Velocity in rad/s)")
            print(f"  Unit: {hex(my_unit_ptr)}  |  Update Loop: ~144Hz")
            print("  คำแนะนำ: ลองกด Roll (A/D) หรือ Pitch (W/S) เพื่อดูว่าตัวไหนพุ่งขึ้นมาช่วง 1.0 - 5.0")
            print("═══════════════════════════════════════════════════════════════════════════════════════")
            print(f"{'Name':<28s} | {'MovePtr':<10s} | {'Offset':<8s} | {'X (rad/s)':>9s} {'Y':>9s} {'Z':>9s} | {'|ω|':>6s} | {'Activity'}")
            print("─" * 95)

            for cand in ALL_PREDICTED:
                move_off = cand["move"]
                if move_off not in move_cache:
                    move_cache[move_off] = get_move_pointer(scanner, my_unit_ptr, move_off)
                m_ptr = move_cache[move_off]

                if not m_ptr:
                    print(f"{cand['name']:<28s} | {'NULL':<10s} | {hex(cand['off']):<8s} | (Move Pointer Unreadable)")
                    continue

                vec = read_vec(scanner, m_ptr, cand["off"], cand["type"])
                if not vec:
                    print(f"{cand['name']:<28s} | {hex(m_ptr):<10s} | {hex(cand['off']):<8s} | (Invalid Float/Double)")
                    continue

                mag = vec_mag(vec)
                
                # เช็คการเปลี่ยนแปลงของค่า (Tick)
                prev = last_vals.get(cand["name"])
                if prev:
                    diff = sum(abs(vec[i] - prev[i]) for i in range(3))
                    if diff > 0.005:
                        tick_counts[cand["name"]] += 1
                last_vals[cand["name"]] = vec

                # ประเมินสถานะการหมุน
                activity = "⚪ IDLE (~0)"
                if 0.5 <= mag <= 8.0:
                    activity = "⚡ ACTIVE ROTATING! 🌪️"
                elif mag > 8.0:
                    activity = "⚠️ UNLIKELY (Too High for rad/s)"

                print(f"{cand['name']:<28s} | {hex(m_ptr):<10s} | {hex(cand['off']):<8s} | {vec[0]:9.3f} {vec[1]:9.3f} {vec[2]:9.3f} | {mag:6.2f} | {activity}")

            time.sleep(0.08)

    except KeyboardInterrupt:
        print("\n↩️ ออกจาก Live Watcher")


# ═══════════════════════════════════════════════════════════
# MODE 2: DIFFERENTIAL CALIBRATION SCANNER (หา Offset แบบเปรียบเทียบ)
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
# MODE 2: DIFFERENTIAL CALIBRATION SCANNER (หา Offset แบบเปรียบเทียบ)
# ═══════════════════════════════════════════════════════════
def run_differential_calibration(scanner, my_unit_ptr):
    """
    กวาด Memory Block ในย่านที่น่าสงสัย (0x0018, 0x0D48, 0x24C0)
    โดยเปรียบเทียบ:
      1. กด [Enter] -> บันทึก Baseline ตอนบินตรง (ω ≈ 0)
      2. นับถอยหลัง 3 วินาที (3... 2... 1...)
      3. ผู้เล่นกด Roll (A/D ค้าง) -> ระบบสแกนจับค่าอัตโนมัติ
      4. คำนวณและแสดงตาราง Offset ที่มีพฤติกรรม Omega ทันที
    """
    os.system("clear")
    print("═══════════════════════════════════════════════════════════════════════════════════════")
    print("  🧪 DIFFERENTIAL OMEGA SCANNER — 4-STAGE CALIBRATION PIPELINE")
    print("═══════════════════════════════════════════════════════════════════════════════════════")
    print("  [STAGE 1/4] บันทึก Baseline (บินตรงนิ่งๆ ω ≈ 0)")
    print("  [STAGE 2/4] นับถอยหลังเตรียมพร้อม (Countdown 3 วินาที)")
    print("  [STAGE 3/4] สแกนจับตัวอย่างขณะควงสว่าน (Active Roll Sampling)")
    print("  [STAGE 4/4] ประมวลผลคัดกรองและสรุปผล (Offset Analysis)")
    print("───────────────────────────────────────────────────────────────────────────────────────")
    input("\n👉 กด [Enter] เมื่อเครื่องบินบินตรงรักษาระดับปีกนิ่งๆ เพื่อเริ่ม STAGE 1...")

    # ─────────────────────────────────────────────────────────────
    # STAGE 1: BASELINE CAPTURE
    # ─────────────────────────────────────────────────────────────
    os.system("clear")
    print("═══════════════════════════════════════════════════════════════════════════════════════")
    print("  📌 [STAGE 1/4] BASELINE CAPTURE (บินตรงนิ่งๆ ω ≈ 0)")
    print("═══════════════════════════════════════════════════════════════════════════════════════")
    print("[*] กำลังเชื่อมต่อ Move Pointers...")
    m0018 = get_move_pointer(scanner, my_unit_ptr, 0x0018)
    m0D48 = get_move_pointer(scanner, my_unit_ptr, 0x0D48)
    m24C0 = get_move_pointer(scanner, my_unit_ptr, 0x24C0)

    print(f"    ├─ Move Ptr 0x0018 (Primary):   {hex(m0018) if m0018 else 'NOT FOUND'}")
    print(f"    ├─ Move Ptr 0x0D48 (High-Tick): {hex(m0D48) if m0D48 else 'NOT FOUND'}")
    print(f"    └─ Move Ptr 0x24C0 (Air-Kin):   {hex(m24C0) if m24C0 else 'NOT FOUND'}")
    print("\n[*] กำลังบันทึก Baseline Memory Snapshot (กรุณารักษาทิศทางบินตรง)...")

    time.sleep(0.4)
    buf_0018_straight = scanner.read_mem(m0018 + 0x300, 0x300) if m0018 else None
    buf_0D48_straight = scanner.read_mem(m0D48, 0x300) if m0D48 else None
    buf_24C0_straight = scanner.read_mem(m24C0 + 0x0D00, 0x300) if m24C0 else None

    print("✅ [STAGE 1/4 COMPLETED] บันทึกค่า Baseline สำเร็จ!")

    # ─────────────────────────────────────────────────────────────
    # STAGE 2: PREPARATION COUNTDOWN
    # ─────────────────────────────────────────────────────────────
    print("\n═══════════════════════════════════════════════════════════════════════════════════════")
    print("  ⏳ [STAGE 2/4] PREPARATION COUNTDOWN (เตรียมพร้อมกด Roll A/D)")
    print("═══════════════════════════════════════════════════════════════════════════════════════")
    print("คำแนะนำ: วางนิ้วบนปุ่มหมุนควงสว่าน (A หรือ D) เมื่อครบ 3 วินาทีให้กดค้างทันที!")

    for count in range(3, 0, -1):
        print(f"   ⏱️  นับถอยหลัง: {count}...")
        time.sleep(1.0)

    # ─────────────────────────────────────────────────────────────
    # STAGE 3: ACTIVE ROLL SAMPLING
    # ─────────────────────────────────────────────────────────────
    os.system("clear")
    print("═══════════════════════════════════════════════════════════════════════════════════════")
    print("  🌪️ [STAGE 3/4] ACTIVE ROLL SAMPLING (กำลังกดหมุนตัวค้างไว้!)")
    print("═══════════════════════════════════════════════════════════════════════════════════════")
    print(">>>>> 🔥 HOLD ROLL KEY (A หรือ D ค้างไว้) ระบบกำลังสแกนอัตโนมัติ... <<<<<")
    print("───────────────────────────────────────────────────────────────────────────────────────")

    time.sleep(0.3)  # รอให้เครื่องเริ่มหมุนได้อัตราเร็ว

    roll_samples_0018 = []
    roll_samples_0D48 = []
    roll_samples_24C0 = []
    total_samples = 8

    for step in range(1, total_samples + 1):
        if m0018:
            b = scanner.read_mem(m0018 + 0x300, 0x300)
            if b: roll_samples_0018.append(b)
        if m0D48:
            b = scanner.read_mem(m0D48, 0x300)
            if b: roll_samples_0D48.append(b)
        if m24C0:
            b = scanner.read_mem(m24C0 + 0x0D00, 0x300)
            if b: roll_samples_24C0.append(b)

        # Progress bar animation
        bar = "█" * (step * 3) + "░" * ((total_samples - step) * 3)
        print(f"\r   📊 Sampling: [{bar}] {step}/{total_samples} samples captured (Keep Holding Roll!)...", end="", flush=True)
        time.sleep(0.2)

    print("\n\n✅ [STAGE 3/4 COMPLETED] จับตัวอย่างการหมุนครบ 100%! ปล่อยปุ่มได้เลย")
    time.sleep(0.6)

    # ─────────────────────────────────────────────────────────────
    # STAGE 4: ANALYSIS & RESULTS
    # ─────────────────────────────────────────────────────────────
    print("\n═══════════════════════════════════════════════════════════════════════════════════════")
    print("  ⚙️  [STAGE 4/4] ANALYSIS & OFFSET IDENTIFICATION")
    print("═══════════════════════════════════════════════════════════════════════════════════════")
    print("[*] กำลังวิเคราะห์เปรียบเทียบ Baseline (ω ≈ 0) vs Peak Roll (1.0 - 8.0 rad/s)...")

    candidates_found = []

    # 1. ตรวจสอบย่าน Move 0x0018 (FLOAT Vec3)
    if buf_0018_straight and roll_samples_0018:
        for off in range(0, len(buf_0018_straight) - 12, 4):
            real_off = 0x300 + off
            v_s = struct.unpack_from("<fff", buf_0018_straight, off)
            if not all(math.isfinite(v) for v in v_s):
                continue
            mag_s = vec_mag(v_s)
            if mag_s >= 0.25:
                continue

            # หา Peak Roll Magnitude ในบรรดา Samples
            best_mag_r = 0.0
            best_v_r = None
            for s_buf in roll_samples_0018:
                if len(s_buf) > off + 12:
                    v_r = struct.unpack_from("<fff", s_buf, off)
                    if all(math.isfinite(v) for v in v_r):
                        m_r = vec_mag(v_r)
                        if m_r > best_mag_r:
                            best_mag_r = m_r
                            best_v_r = v_r

            if best_v_r and 0.8 <= best_mag_r <= 8.0:
                candidates_found.append({
                    "source": "Move_0x0018",
                    "move_ptr": m0018,
                    "offset": real_off,
                    "type": "FLOAT",
                    "straight_mag": mag_s,
                    "roll_mag": best_mag_r,
                    "straight_vec": v_s,
                    "roll_vec": best_v_r,
                })

    # 2. ตรวจสอบย่าน Move 0x0D48 (DOUBLE & FLOAT)
    if buf_0D48_straight and roll_samples_0D48:
        # 2.1 Double (24 bytes)
        for off in range(0, len(buf_0D48_straight) - 24, 8):
            v_s = struct.unpack_from("<ddd", buf_0D48_straight, off)
            if not all(math.isfinite(v) for v in v_s):
                continue
            mag_s = vec_mag(v_s)
            if mag_s >= 0.25:
                continue

            best_mag_r = 0.0
            best_v_r = None
            for s_buf in roll_samples_0D48:
                if len(s_buf) > off + 24:
                    v_r = struct.unpack_from("<ddd", s_buf, off)
                    if all(math.isfinite(v) for v in v_r):
                        m_r = vec_mag(v_r)
                        if m_r > best_mag_r:
                            best_mag_r = m_r
                            best_v_r = v_r

            if best_v_r and 0.8 <= best_mag_r <= 8.0:
                candidates_found.append({
                    "source": "Move_0x0D48",
                    "move_ptr": m0D48,
                    "offset": off,
                    "type": "DOUBLE",
                    "straight_mag": mag_s,
                    "roll_mag": best_mag_r,
                    "straight_vec": v_s,
                    "roll_vec": best_v_r,
                })

        # 2.2 Float (12 bytes)
        for off in range(0, len(buf_0D48_straight) - 12, 4):
            v_s = struct.unpack_from("<fff", buf_0D48_straight, off)
            if not all(math.isfinite(v) for v in v_s):
                continue
            mag_s = vec_mag(v_s)
            if mag_s >= 0.25:
                continue

            best_mag_r = 0.0
            best_v_r = None
            for s_buf in roll_samples_0D48:
                if len(s_buf) > off + 12:
                    v_r = struct.unpack_from("<fff", s_buf, off)
                    if all(math.isfinite(v) for v in v_r):
                        m_r = vec_mag(v_r)
                        if m_r > best_mag_r:
                            best_mag_r = m_r
                            best_v_r = v_r

            if best_v_r and 0.8 <= best_mag_r <= 8.0:
                candidates_found.append({
                    "source": "Move_0x0D48",
                    "move_ptr": m0D48,
                    "offset": off,
                    "type": "FLOAT",
                    "straight_mag": mag_s,
                    "roll_mag": best_mag_r,
                    "straight_vec": v_s,
                    "roll_vec": best_v_r,
                })

    # 3. ตรวจสอบย่าน Move 0x24C0 (FLOAT)
    if buf_24C0_straight and roll_samples_24C0:
        for off in range(0, len(buf_24C0_straight) - 12, 4):
            real_off = 0x0D00 + off
            v_s = struct.unpack_from("<fff", buf_24C0_straight, off)
            if not all(math.isfinite(v) for v in v_s):
                continue
            mag_s = vec_mag(v_s)
            if mag_s >= 0.25:
                continue

            best_mag_r = 0.0
            best_v_r = None
            for s_buf in roll_samples_24C0:
                if len(s_buf) > off + 12:
                    v_r = struct.unpack_from("<fff", s_buf, off)
                    if all(math.isfinite(v) for v in v_r):
                        m_r = vec_mag(v_r)
                        if m_r > best_mag_r:
                            best_mag_r = m_r
                            best_v_r = v_r

            if best_v_r and 0.8 <= best_mag_r <= 8.0:
                candidates_found.append({
                    "source": "Move_0x24C0",
                    "move_ptr": m24C0,
                    "offset": real_off,
                    "type": "FLOAT",
                    "straight_mag": mag_s,
                    "roll_mag": best_mag_r,
                    "straight_vec": v_s,
                    "roll_vec": best_v_r,
                })

    os.system("clear")
    print("═══════════════════════════════════════════════════════════════════════════════════════")
    print(f"  🏆 [STAGE 4/4 RESULTS] ผลการสแกนหา OMEGA OFFSET (พบ {len(candidates_found)} รายการที่ผ่านเกณฑ์)")
    print("═══════════════════════════════════════════════════════════════════════════════════════")

    if not candidates_found:
        print("[-] ไม่พบ Offset ที่ตรงตามพฤติกรรม Omega")
        print("    คำแนะนำ: ลองทดสอบใหม่โดยกดปุ่ม Roll ให้สุดและเริ่มหมุนทันทีที่เลขนับถอยหลังหมด")
    else:
        # เรียงตามความต่างของการหมุน (Roll Ratio สูงสุด)
        candidates_found.sort(key=lambda c: (c["roll_mag"] - c["straight_mag"]), reverse=True)

        print(f"{'Source':<12s} | {'Offset':<8s} | {'Type':<6s} | {'Straight |ω|':>12s} | {'Roll |ω|':>10s} | {'Roll Vector (X, Y, Z)'}")
        print("─" * 90)
        for c in candidates_found[:15]:
            rx, ry, rz = c["roll_vec"]
            is_match_old = " ⭐ (ตรงกับ 0x3F8 เดิม!)" if (c["offset"] == 0x3F8 and c["source"] == "Move_0x0018") else ""
            print(f"{c['source']:<12s} | {hex(c['offset']):<8s} | {c['type']:<6s} | {c['straight_mag']:12.3f} | {c['roll_mag']:10.3f} | ({rx:6.2f}, {ry:6.2f}, {rz:6.2f}){is_match_old}")

    input("\nกด [Enter] เพื่อกลับสู่เมนู...")


# ═══════════════════════════════════════════════════════════
# MAIN MENU
# ═══════════════════════════════════════════════════════════
def main():
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_address)

    while True:
        os.system("clear")
        print("══════════════════════════════════════════════════")
        print("  🌪️ WAR THUNDER OMEGA (ANGULAR VELOCITY) TOOL")
        print("══════════════════════════════════════════════════")
        print("PID:", pid, "| Base:", hex(base_address))

        my_unit_ptr, my_team = get_local_team(scanner, base_address)
        if not my_unit_ptr:
            print("⚠️ ไม่พบเครื่องบินตนเอง (My Unit) — กรุณาเข้าห้องทดสอบบิน (Test Flight) หรือแมตช์จริง")
        else:
            print(f"✈️ My Unit Pointer: {hex(my_unit_ptr)} (Team {my_team})")

        print("\n[1] 🧪 Differential Calibration Scanner (หา Offset อัตโนมัติ: บินตรง vs Roll)")
        print("[2] 👁️ Live Watcher (มอนิเตอร์ดูค่า Candidates แบบ Realtime)")
        print("[0] ❌ ออกจากโปรแกรม")
        print("──────────────────────────────────────────────────")

        choice = input("👉 เลือกคำสั่ง: ").strip()

        if choice == "0":
            break
        elif choice == "1":
            if not my_unit_ptr:
                input("[-] ต้องเข้าเกมและมียูนิตเครื่องบินก่อน กด Enter...")
                continue
            run_differential_calibration(scanner, my_unit_ptr)
        elif choice == "2":
            if not my_unit_ptr:
                input("[-] ต้องเข้าเกมและมียูนิตเครื่องบินก่อน กด Enter...")
                continue
            run_live_watcher(scanner, my_unit_ptr)


if __name__ == "__main__":
    main()
