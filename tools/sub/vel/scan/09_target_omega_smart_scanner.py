#!/usr/bin/env python3
"""
09_target_omega_smart_scanner.py — Smart Target Omega & Turning Prediction Hunter

เครื่องมือสแกนหา Offset ความเร็วเชิงมุม (Omega / Angular Velocity) และ Rotation Matrix
บนเครื่องบินเป้าหมาย (Target Air Unit) โดยเปรียบเทียบความแม่นยำในการทำนายการเลี้ยว (Predict Turning)
กับอัตราการเปลี่ยนความเร่งและทิศทางจริงจากการเคลื่อนที่ของพิกัด Position:

ฟังก์ชันการทำงาน:
  1. ติดตามเครื่องบินเป้าหมาย และวัด Ground-Truth Turning:
     - v(t) = d(pos)/dt
     - a_turn(t) = d(v)/dt (ความเร่งหนีศูนย์กลางจริง)
     - omega_true = (v x a) / |v|^2 (เวกเตอร์ความเร็วเชิงมุมจริง rad/s)
  2. สแกน Memory Pointer ทั้งหมดในตัว Target (0x0000 - 0x3000)
  3. สแกนหา Float Vec3 (wx, wy, wz) ในทุก Sub-Block ที่ขนาดใกล้เคียง omega_true
  4. ทดสอบความถูกต้องในการทำนายการเลี้ยว:
     - คำนวณ a_pred = omega x v
     - คำนวณ Cosine Similarity (cos theta) เทียบกับ a_turn จริง
     - ทดสอบทั้ง (+omega x v) และ (-omega x v) เพื่อตรวจจับการสลับเครื่องหมาย (Transposed Matrix)
  5. วัด Tick Rate (Hz) ของแต่ละ Candidate
  6. บันทึกผลลัพธ์ลง dumps/ ทั้งไฟล์ JSON และ TXT สรุปอัตโนมัติ
"""

import os
import sys
import time
import json
import math
import struct
from collections import deque
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import (
    MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
)
from src.utils.mul import (
    get_cgame_base, get_all_units, get_local_team,
    get_unit_pos, get_unit_status, is_valid_ptr,
    OFF_AIR_MOVEMENT, OFF_AIR_VEL, OFF_UNIT_ROTATION,
    OFF_AIR_HIGH_TICK_MOVEMENT, OFF_AIR_HIGH_TICK_VEL
)

# -------------------------------------------------------------
# Configuration
# -------------------------------------------------------------
MAX_SCAN_DISTANCE    = 15000.0   # ระยะค้นหาเป้าหมายสูงสุด (15 กม.)
MIN_TURNING_SPEED_KMH= 150.0     # ความเร็วขั้นต่ำของเป้าหมาย (กม./ชม.)
MIN_TURNING_ACC_MS2  = 2.0       # ความเร่งการเลี้ยวขั้นต่ำที่เริ่มเก็บสถิติ (m/s^2)
SAMPLE_DURATION_SEC  = 5.0       # ระยะเวลาในการสแกนวิเคราะห์ต่อรอบ (วินาที)
DUMP_DIR             = os.path.join(PROJECT_ROOT, "dumps")


def vec3_len(v):
    return math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)


def vec3_cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0]
    )


def vec3_dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def vec3_cosine(a, b):
    la = vec3_len(a)
    lb = vec3_len(b)
    if la < 1e-5 or lb < 1e-5:
        return 0.0
    return max(-1.0, min(1.0, vec3_dot(a, b) / (la * lb)))


class TargetOmegaHunter:
    def __init__(self, scanner, cgame_base, my_unit_ptr, my_team):
        self.scanner = scanner
        self.cgame_base = cgame_base
        self.my_unit_ptr = my_unit_ptr
        self.my_team = my_team
        
        # Candidate Tracker: {(ptr, off, type): [samples]}
        self.candidate_stats = {}
        self.kinematic_rot_samples = []

    def get_air_targets(self, my_pos):
        """ค้นหาเป้าหมายทางอากาศที่กำลังเคลื่อนที่และเลี้ยว."""
        all_units = get_all_units(self.scanner, self.cgame_base)
        if not all_units:
            return []

        targets = []
        for u_ptr, is_air in all_units:
            if u_ptr == self.my_unit_ptr or not is_air:
                continue

            st = get_unit_status(self.scanner, u_ptr, read_name=True)
            if not st:
                continue

            team = st[0] if isinstance(st, tuple) else st.get("team", 0)
            state = st[1] if isinstance(st, tuple) else st.get("state", 0)
            name = st[2] if (isinstance(st, tuple) and len(st) >= 3 and st[2]) else "AIR"

            if state >= 2:  # ยูนิตตาย
                continue

            pos = get_unit_pos(self.scanner, u_ptr)
            if not pos or all(abs(p) < 0.1 for p in pos):
                continue

            dist = vec3_len((pos[0]-my_pos[0], pos[1]-my_pos[1], pos[2]-my_pos[2])) if my_pos else 0.0
            if dist <= MAX_SCAN_DISTANCE:
                targets.append({
                    "ptr": u_ptr,
                    "name": name,
                    "team": team,
                    "is_friendly": (team == self.my_team and self.my_team > 0),
                    "dist": dist,
                    "pos": pos,
                })

        targets.sort(key=lambda x: x["dist"])
        return targets

    def scan_unit_pointers(self, unit_ptr):
        """ค้นหาพอยน์เตอร์ที่เป็นไปได้ทั้งหมดในโครงสร้างของ Target."""
        pointers = []
        raw = self.scanner.read_mem(unit_ptr, 0x3000)
        if not raw or len(raw) < 0x3000:
            return pointers

        for off in range(0, 0x3000, 8):
            val = struct.unpack_from("<Q", raw, off)[0]
            if is_valid_ptr(val):
                pointers.append((off, val))

        return pointers

    def scan_omega_in_block(self, mem_ptr, size=0x1500):
        """สแกนหาเวกเตอร์ Float Vec3 ภายใน Memory Block ที่มีลักษณะเป็นความเร็วเชิงมุม."""
        raw = self.scanner.read_mem(mem_ptr, size)
        if not raw or len(raw) < size:
            return []

        candidates = []
        for off in range(0, size - 12, 4):
            x, y, z = struct.unpack_from("<fff", raw, off)
            if math.isfinite(x) and math.isfinite(y) and math.isfinite(z):
                mag = math.sqrt(x*x + y*y + z*z)
                # ความเร็วเชิงมุมของเครื่องบินรบมักอยู่ในช่วง 0.02 ถึง 6.0 rad/s
                if 0.02 <= mag <= 6.0:
                    candidates.append((off, (x, y, z), mag))

        return candidates

    def run_hunt_session(self, target_info):
        """รันรอบการสแกนและวัดผลกับเป้าหมายเป็นเวลา SAMPLE_DURATION_SEC."""
        u_ptr = target_info["ptr"]
        t_name = target_info["name"]
        print(f"\n" + "="*72)
        print(f"🎯 LOCKED TARGET: {t_name} [0x{u_ptr:X}] ({target_info['dist']:.0f}m)")
        print(f"🔍 สแกนหาพอยน์เตอร์ทั้งหมดในโครงสร้าง Unit...")

        ptrs = self.scan_unit_pointers(u_ptr)
        print(f"   พบพอยน์เตอร์ที่ถูกต้อง: {len(ptrs)} ตำแหน่ง")

        scan_blocks = [(0x0000, u_ptr, "UNIT_BASE")] + [(off, p, f"PTR_0x{off:04X}") for off, p in ptrs]

        print(f"⚡ เริ่มดักจับการเลี้ยว (Ground-Truth Turning) เป็นเวลา {SAMPLE_DURATION_SEC:.1f} วินาที...")
        print(f"   กรุณาจับตาดูเป้าหมายที่กำลังเลี้ยวหรือบินเปลี่ยนทิศทาง...")

        pos_history = deque(maxlen=300)
        start_t = time.time()
        last_t = start_t

        turning_frames = 0
        candidate_records = {}

        last_r_matrix = None
        last_r_time = 0.0

        sample_count = 0
        v_spd = 0.0
        while time.time() - start_t < SAMPLE_DURATION_SEC:
            curr_t = time.time()
            dt = curr_t - last_t
            if dt < 0.015:  # ~60Hz
                time.sleep(0.005)
                continue
            last_t = curr_t

            cur_pos = get_unit_pos(self.scanner, u_ptr)
            if not cur_pos or all(abs(p) < 0.1 for p in cur_pos):
                continue

            pos_history.append((curr_t, cur_pos))
            if len(pos_history) < 5:
                continue

            t_prev, p_prev = pos_history[-4]
            dt_pos = curr_t - t_prev
            if dt_pos < 0.01:
                continue

            vx = (cur_pos[0] - p_prev[0]) / dt_pos
            vy = (cur_pos[1] - p_prev[1]) / dt_pos
            vz = (cur_pos[2] - p_prev[2]) / dt_pos
            v_vec = (vx, vy, vz)
            v_spd = vec3_len(v_vec)

            if (v_spd * 3.6) < MIN_TURNING_SPEED_KMH:
                continue

            if len(pos_history) >= 9:
                t_old, p_old = pos_history[-8]
                dt_half = (t_prev - t_old)
                if dt_half > 0.01:
                    vx_old = (p_prev[0] - p_old[0]) / dt_half
                    vy_old = (p_prev[1] - p_old[1]) / dt_half
                    vz_old = (p_prev[2] - p_old[2]) / dt_half
                    v_old = (vx_old, vy_old, vz_old)
                    
                    dt_acc = curr_t - t_prev
                    ax = (vx - vx_old) / dt_acc
                    ay = (vy - vy_old) / dt_acc
                    az = (vz - vz_old) / dt_acc
                    a_vec = (ax, ay, az)
                    a_mag = vec3_len(a_vec)

                    v_cross_a = vec3_cross(v_vec, a_vec)
                    omg_true_vec = (
                        v_cross_a[0] / (v_spd**2),
                        v_cross_a[1] / (v_spd**2),
                        v_cross_a[2] / (v_spd**2)
                    )
                    omg_true_mag = vec3_len(omg_true_vec)

                    if a_mag >= MIN_TURNING_ACC_MS2 and omg_true_mag >= 0.03:
                        turning_frames += 1

                        rot_raw = self.scanner.read_mem(u_ptr + OFF_UNIT_ROTATION, 36)
                        if rot_raw and len(rot_raw) == 36:
                            r_curr = struct.unpack("<9f", rot_raw)
                            if all(math.isfinite(x) for x in r_curr) and last_r_matrix:
                                dt_r = curr_t - last_r_time
                                if 0.01 <= dt_r <= 0.2:
                                    r_prev = last_r_matrix
                                    r_rel_std = [0.0]*9
                                    for i in range(3):
                                        for j in range(3):
                                            r_rel_std[i*3 + j] = sum(r_curr[i*3 + k] * r_prev[j*3 + k] for k in range(3))
                                    trace_s = r_rel_std[0] + r_rel_std[4] + r_rel_std[8]
                                    val_s = max(-1.0, min(1.0, (trace_s - 1.0) * 0.5))
                                    ang_s = math.acos(val_s)
                                    if ang_s > 1e-4:
                                        scale_s = ang_s / (2.0 * math.sin(ang_s) * dt_r)
                                        w_std = (
                                            (r_rel_std[7] - r_rel_std[5]) * scale_s,
                                            (r_rel_std[2] - r_rel_std[6]) * scale_s,
                                            (r_rel_std[3] - r_rel_std[1]) * scale_s
                                        )
                                        ac_std = vec3_cross(w_std, v_vec)
                                        ac_std_neg = (-ac_std[0], -ac_std[1], -ac_std[2])
                                        cos_std = vec3_cosine(ac_std, a_vec)
                                        cos_std_neg = vec3_cosine(ac_std_neg, a_vec)
                                        self.kinematic_rot_samples.append({
                                            "cos_std": cos_std,
                                            "cos_std_neg": cos_std_neg,
                                            "w_mag": vec3_len(w_std),
                                            "true_mag": omg_true_mag
                                        })
                            last_r_matrix = r_curr
                            last_r_time = curr_t

                        sample_blocks = scan_blocks[sample_count % len(scan_blocks): (sample_count % len(scan_blocks)) + 8]
                        for m_off, m_ptr, desc in sample_blocks:
                            vec_candidates = self.scan_omega_in_block(m_ptr, size=0x1200)
                            for v_off, cand_vec, cand_mag in vec_candidates:
                                key = (desc, m_off, v_off)
                                if key not in candidate_records:
                                    candidate_records[key] = {
                                        "desc": desc,
                                        "move_off": m_off,
                                        "vec_off": v_off,
                                        "samples": 0,
                                        "cos_pos": 0.0,
                                        "cos_neg": 0.0,
                                        "avg_mag": 0.0,
                                        "ticks": 0,
                                        "last_vec": None
                                    }

                                rec = candidate_records[key]
                                rec["samples"] += 1
                                rec["avg_mag"] += cand_mag

                                if rec["last_vec"]:
                                    diff = sum(abs(cand_vec[k] - rec["last_vec"][k]) for k in range(3))
                                    if diff > 0.005:
                                        rec["ticks"] += 1
                                rec["last_vec"] = cand_vec

                                a_pred_pos = vec3_cross(cand_vec, v_vec)
                                a_pred_neg = (-a_pred_pos[0], -a_pred_pos[1], -a_pred_pos[2])

                                rec["cos_pos"] += vec3_cosine(a_pred_pos, a_vec)
                                rec["cos_neg"] += vec3_cosine(a_pred_neg, a_vec)

            sample_count += 1
            elapsed = curr_t - start_t
            sys.stdout.write(f"\r⏳ กำลังสแกน... {elapsed:3.1f}/{SAMPLE_DURATION_SEC:.0f}s | บันทึกการเลี้ยว: {turning_frames} เฟรม | ความเร็วเป้าหมาย: {v_spd*3.6:4.0f} km/h")
            sys.stdout.flush()

        print(f"\n\n✅ เสร็จสิ้นการสแกนรอบนี้! (วิเคราะห์เฟรมเลี้ยวรวม {turning_frames} เฟรม)")
        return self._process_results(target_info, turning_frames, candidate_records)

    def _process_results(self, target_info, turning_frames, candidate_records):
        """ประมวลผลและเรียงลำดับ Candidate ที่ทำนายการเลี้ยวได้แม่นยำที่สุด."""
        print("\n" + "="*78)
        print(f"📊 สรุปผลการวิเคราะห์ OMEGA & PREDICT TURNING บนเป้าหมาย: {target_info['name']}")
        print("="*78)

        if self.kinematic_rot_samples:
            avg_cos_std = sum(s["cos_std"] for s in self.kinematic_rot_samples) / len(self.kinematic_rot_samples)
            avg_cos_neg = sum(s["cos_std_neg"] for s in self.kinematic_rot_samples) / len(self.kinematic_rot_samples)
            avg_w_mag   = sum(s["w_mag"] for s in self.kinematic_rot_samples) / len(self.kinematic_rot_samples)
            avg_t_mag   = sum(s["true_mag"] for s in self.kinematic_rot_samples) / len(self.kinematic_rot_samples)

            print(f"📐 [1] 0x0D14 ROTATION MATRIX EVALUATION ({len(self.kinematic_rot_samples)} samples):")
            print(f"   • ขนาดความเร็วเชิงมุมเฉลี่ย : {avg_w_mag:.3f} rad/s (Ground-Truth: {avg_t_mag:.3f} rad/s)")
            print(f"   • Standard (+Omega x V)      : Cosine = {avg_cos_std:+.3f}  ({'🟢ทิศทางถูก' if avg_cos_std > 0.4 else '🔴กลับทิศ/ผิดทาง'})")
            print(f"   • Inverted Sign (-Omega x V) : Cosine = {avg_cos_neg:+.3f}  ({'🟢ทิศทางถูก 100%' if avg_cos_neg > 0.6 else '⚪ไม่ตรง'})")
            if avg_cos_neg > 0.5 and avg_cos_std < 0.0:
                print(f"   ⭐ ยืนยัน 100%: 0x0D14 มี Matrix Transposition Bug! การใช้ (-Omega x V หรือ V x Omega) จะทำนายการเลี้ยวได้อย่างแม่นยำสูงสุด!")
            print()

        ranked_candidates = []
        for key, rec in candidate_records.items():
            if rec["samples"] < 5:
                continue
            cos_p = rec["cos_pos"] / rec["samples"]
            cos_n = rec["cos_neg"] / rec["samples"]
            best_cos = max(cos_p, cos_n)
            best_mode = "+Omega x V" if cos_p >= cos_n else "-Omega x V (Inverted)"
            avg_mag = rec["avg_mag"] / rec["samples"]
            est_hz = (rec["ticks"] / SAMPLE_DURATION_SEC) if SAMPLE_DURATION_SEC > 0 else 0

            if best_cos >= 0.30:
                ranked_candidates.append({
                    "desc": rec["desc"],
                    "move_off": rec["move_off"],
                    "vec_off": rec["vec_off"],
                    "best_cos": best_cos,
                    "mode": best_mode,
                    "avg_mag": avg_mag,
                    "est_hz": est_hz,
                    "samples": rec["samples"],
                })

        ranked_candidates.sort(key=lambda x: x["best_cos"], reverse=True)

        print(f"🎯 [2] TOP MEMORY CANDIDATES FOR OMEGA VECTOR (พบ {len(ranked_candidates)} รายการที่สอดคล้อง):")
        print(f"   {'OFFSET / PATH':<32} | {'ALIGNMENT (COS)':<16} | {'FORMULA':<22} | {'EST HZ':<8}")
        print("   " + "-"*76)

        for c in ranked_candidates[:12]:
            off_str = f"{c['desc']} + 0x{c['vec_off']:04X}"
            cos_str = f"{c['best_cos']:+.3f} ({c['best_cos']*100:.1f}%)"
            print(f"   {off_str:<32} | {cos_str:<16} | {c['mode']:<22} | {c['est_hz']:4.1f} Hz")

        self._save_dump(target_info, ranked_candidates)
        return ranked_candidates

    def _save_dump(self, target_info, ranked_candidates):
        os.makedirs(DUMP_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if (c.isalnum() or c in "_-") else "_" for c in target_info['name'])
        json_path = os.path.join(DUMP_DIR, f"09_target_omega_scan_{safe_name}_{ts}.json")
        txt_path  = os.path.join(DUMP_DIR, f"09_target_omega_scan_{safe_name}_{ts}.txt")

        data = {
            "timestamp": ts,
            "target_name": target_info["name"],
            "target_ptr": hex(target_info["ptr"]),
            "kinematic_rot_evaluation": self.kinematic_rot_samples,
            "ranked_candidates": ranked_candidates
        }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"TARGET OMEGA SCAN REPORT: {target_info['name']}\n")
            f.write(f"Date: {ts}\n")
            f.write("="*72 + "\n\n")
            for c in ranked_candidates[:20]:
                f.write(f"Offset: {c['desc']} + 0x{c['vec_off']:04X}\n")
                f.write(f"  Alignment: {c['best_cos']:+.4f}\n")
                f.write(f"  Formula  : {c['mode']}\n")
                f.write(f"  Est Hz   : {c['est_hz']:.1f} Hz\n")
                f.write(f"  Avg Mag  : {c['avg_mag']:.3f} rad/s\n\n")

        print(f"\n💾 บันทึกผลการสแกนเรียบร้อย:")
        print(f"   • JSON : {json_path}")
        print(f"   • TXT  : {txt_path}")


def main():
    print("=" * 78)
    print("🛸 SMART TARGET OMEGA & TURNING PREDICTION HUNTER")
    print("   เครื่องมือสแกนหา Offset ความเร็วเชิงมุม (Omega) และตรวจสอบความแม่นยำในการทำนายการเลี้ยว")
    print("=" * 78)

    pid = get_game_pid()
    if not pid:
        print("[!] ไม่พบ Process ของเกม War Thunder กรุณาเปิดเกมและเข้าสู่สนามบินก่อน!")
        return

    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)

    cgame_base = get_cgame_base(scanner, base_addr)
    my_unit, my_team = get_local_team(scanner, base_addr)
    my_pos = get_unit_pos(scanner, my_unit) if my_unit else (0.0, 0.0, 0.0)

    print(f"[*] Base Address: 0x{base_addr:X} | cgame: 0x{cgame_base:X} | My Unit: 0x{my_unit:X}")

    hunter = TargetOmegaHunter(scanner, cgame_base, my_unit, my_team)

    while True:
        targets = hunter.get_air_targets(my_pos)
        if not targets:
            print("\r[?] กำลังค้นหาเป้าหมายทางอากาศในสนามรบ...", end="", flush=True)
            time.sleep(1.0)
            continue

        print(f"\n\n📋 พบเครื่องบินเป้าหมาย {len(targets)} ลำ:")
        for idx, t in enumerate(targets[:8]):
            team_str = "FRIENDLY" if t["is_friendly"] else "ENEMY"
            print(f"  [{idx+1}] {t['name']:<20} | {team_str:<8} | Dist: {t['dist']:5.0f}m | PTR: 0x{t['ptr']:X}")

        print("\nกดเลือกหมายเลขเป้าหมาย [1-8] หรือ [A] เพื่อสแกนเป้าหมายที่ใกล้ที่สุดอัตโนมัติ (หรือ [Q] ออก):")
        choice = input(">> ").strip().lower()

        if choice == 'q':
            break
        elif choice in ('a', ''):
            selected = targets[0]
        else:
            try:
                sel_idx = int(choice) - 1
                if 0 <= sel_idx < len(targets):
                    selected = targets[sel_idx]
                else:
                    selected = targets[0]
            except ValueError:
                selected = targets[0]

        hunter.run_hunt_session(selected)
        print("\nต้องการสแกนต่อหรือไม่? [Y/n]:")
        ans = input(">> ").strip().lower()
        if ans == 'n':
            break


if __name__ == "__main__":
    main()
