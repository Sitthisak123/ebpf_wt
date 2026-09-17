#!/usr/bin/env python3
"""
air_logger.py — Air Leadmark Flight & Kinematics Debug Logger
เก็บบันทึกข้อมูลดิบทุกเฟรม (Frame-by-Frame) ของเป้าหมายทางอากาศที่กำลังล็อก/ติดตาม
เพื่อใช้วิเคราะห์และแก้ไขปัญหา Leadmark Jitter:
- Raw AIRmove offsets ทั้งหมดในเฟรมเดียวกัน (0x20F0, 0x24C0, 0x14B8, 0x0018, Pos-delta)
- Offsets in use (VEL & OMEGA)
- Raw Omega (Net 0x0550, RotMatrix 0x0D14)
- Kinematics & Kalman Filter (pos, vel, acc)
- Centripetal acceleration (ac = ω × v)
- Leadmark world & screen coordinates
- Non-blocking I/O ผ่าน background thread ไม่กระทบ FPS
"""

import os
import sys
import time
import math
import csv
import json
import queue
import threading
from typing import Dict, Any, Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _vec_mag(v):
    if not v:
        return 0.0
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


CSV_COLUMNS = [
    # ⏱️ Timing & Performance
    "frame_idx", "timestamp", "dt", "fps",
    # 🎯 Target Metadata
    "unit_ptr", "unit_name", "dist_m",
    # 🔧 Offsets in Use
    "active_vel_source", "active_move_off", "active_vel_off", "active_move_ptr",
    "active_omg_source", "active_omg_off",
    # 🚀 Active Velocity in Use
    "v_used_vx", "v_used_vy", "v_used_vz", "v_used_kmh",
    # ✈️ Raw AIRmove Candidates
    "raw_20f0_07c0_vx", "raw_20f0_07c0_vy", "raw_20f0_07c0_vz", "raw_20f0_07c0_kmh",
    "raw_20f0_0cf0_vx", "raw_20f0_0cf0_vy", "raw_20f0_0cf0_vz", "raw_20f0_0cf0_kmh",
    "raw_20f0_0ea4_vx", "raw_20f0_0ea4_vy", "raw_20f0_0ea4_vz", "raw_20f0_0ea4_kmh",
    "raw_24c0_0e90_vx", "raw_24c0_0e90_vy", "raw_24c0_0e90_vz", "raw_24c0_0e90_kmh",
    "raw_14b8_0f48_vx", "raw_14b8_0f48_vy", "raw_14b8_0f48_vz", "raw_14b8_0f48_kmh",
    "raw_0018_0318_vx", "raw_0018_0318_vy", "raw_0018_0318_vz", "raw_0018_0318_kmh",
    "pos_delta_vx", "pos_delta_vy", "pos_delta_vz", "pos_delta_kmh",
    # 🌪️ Omega (Angular Velocity)
    "omg_net_0550_wx", "omg_net_0550_wy", "omg_net_0550_wz", "omg_net_0550_mag",
    "omg_rot_0d14_wx", "omg_rot_0d14_wy", "omg_rot_0d14_wz", "omg_rot_0d14_mag",
    "used_omg_wx", "used_omg_wy", "used_omg_wz", "used_omg_mag",
    # ⚡ Accelerations
    "ac_omega_ax", "ac_omega_ay", "ac_omega_az", "ac_omega_mag",
    "kalman_acc_ax", "kalman_acc_ay", "kalman_acc_az", "kalman_acc_mag",
    "final_acc_ax", "final_acc_ay", "final_acc_az", "final_acc_mag",
    # 📍 Position & Kalman
    "raw_pos_x", "raw_pos_y", "raw_pos_z",
    "kalman_pos_x", "kalman_pos_y", "kalman_pos_z",
    "kalman_vel_vx", "kalman_vel_vy", "kalman_vel_vz", "kalman_vel_kmh",
    # 🎯 Leadmark Ballistics
    "tof_s",
    "lead_world_x", "lead_world_y", "lead_world_z",
    "target_screen_px", "target_screen_py",
    "lead_screen_px", "lead_screen_py",
    "screen_lead_dx", "screen_lead_dy",
    # 🟢 My Unit State
    "my_pos_x", "my_pos_y", "my_pos_z",
    "my_vel_vx", "my_vel_vy", "my_vel_vz", "my_vel_kmh",
    "bullet_speed_ms"
]


class AirLeadmarkFlightLogger:
    """
    ระบบบันทึก Log การบินและการคำนวณ Leadmark ของเป้าหมายทางอากาศ
    ทำงานแยกเธรด (Non-blocking) เพื่อไม่ให้รบกวนเฟรมเรตหลักของการวาด Overlay
    """

    def __init__(self, dumps_dir=None):
        self.dumps_dir = dumps_dir or os.path.join(PROJECT_ROOT, "dumps")
        os.makedirs(self.dumps_dir, exist_ok=True)

        self._queue = queue.Queue(maxsize=15000)
        self._stop_event = threading.Event()
        self._current_csv_path = None
        self._current_file = None
        self._current_writer = None
        self._record_count = 0
        self._session_active = False
        self._current_target_ptr = 0
        self._latest_sample = {}

        self._worker_thread = threading.Thread(
            target=self._worker_loop, name="AirLeadmarkLoggerWorker", daemon=True
        )
        self._worker_thread.start()

    @property
    def current_csv_path(self):
        return self._current_csv_path

    @property
    def record_count(self):
        return self._record_count

    @property
    def is_session_active(self):
        return self._session_active

    def start_session(self, target_ptr: int, target_name: str = "UNKNOWN"):
        """เริ่มเปิดไฟล์บันทึก session ใหม่สำหรับเป้าหมายที่ระบุ."""
        if self._session_active and self._current_target_ptr == target_ptr:
            return

        self.stop_session()

        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if (c.isalnum() or c in "_-") else "_" for c in target_name)
        filename = f"08_air_leadmark_debug_{safe_name}_{timestamp_str}.csv"
        filepath = os.path.join(self.dumps_dir, filename)

        try:
            f = open(filepath, "w", newline="", encoding="utf-8", buffering=65536)
            writer = csv.writer(f)
            writer.writerow(CSV_COLUMNS)
            f.flush()

            self._current_csv_path = filepath
            self._current_file = f
            self._current_writer = writer
            self._record_count = 0
            self._session_active = True
            self._current_target_ptr = target_ptr
        except Exception as e:
            print(f"[!] AirLogger: Failed to open CSV file {filepath}: {e}")

    def log_frame(self, data: Dict[str, Any]):
        """บันทึกข้อมูล 1 เฟรมลง queue แบบ Non-blocking."""
        if not self._session_active:
            target_ptr = data.get("unit_ptr_int", 0)
            target_name = data.get("unit_name", "AIR")
            self.start_session(target_ptr, target_name)

        try:
            self._queue.put_nowait(data)
            self._latest_sample = data
        except queue.Full:
            # Drop frame หาก buffer ล้น เพื่อไม่ให้กระทบ FPS
            pass

    def stop_session(self):
        """ปิด session ปัจจุบันและ flush ข้อมูลทั้งหมดลงดิสก์."""
        if not self._session_active:
            return

        self._session_active = False
        self._current_target_ptr = 0

        # ส่งสัญญาณ flush ให้ worker
        self._queue.put({"__CMD__": "FLUSH"})

        # บันทึก Latest JSON สรุป
        try:
            latest_path = os.path.join(self.dumps_dir, "08_air_leadmark_debug_latest.json")
            summary = {
                "latest_csv": self._current_csv_path,
                "record_count": self._record_count,
                "timestamp": time.time(),
                "time_str": time.strftime("%Y-%m-%d %H:%M:%S"),
                "latest_sample": self._latest_sample,
            }
            with open(latest_path, "w", encoding="utf-8") as jf:
                json.dump(summary, jf, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _worker_loop(self):
        """Worker thread สำหรับดึงข้อมูลจาก queue และเขียนลงไฟล์ CSV แบบ chunk."""
        batch = []
        last_flush_time = time.time()

        while not self._stop_event.is_set():
            try:
                try:
                    item = self._queue.get(timeout=0.25)
                except queue.Empty:
                    item = None

                if item is not None:
                    if isinstance(item, dict) and item.get("__CMD__") == "FLUSH":
                        if batch and self._current_writer:
                            self._write_batch(batch)
                            batch.clear()
                        if self._current_file:
                            try:
                                self._current_file.flush()
                                self._current_file.close()
                            except Exception:
                                pass
                            self._current_file = None
                            self._current_writer = None
                        continue

                    batch.append(item)

                now = time.time()
                if (len(batch) >= 50) or (batch and (now - last_flush_time >= 0.5)):
                    if self._current_writer:
                        self._write_batch(batch)
                        batch.clear()
                        last_flush_time = now
                        if self._current_file:
                            self._current_file.flush()
            except Exception as e:
                time.sleep(0.05)

        # Final cleanup
        if batch and self._current_writer:
            self._write_batch(batch)
        if self._current_file:
            try:
                self._current_file.flush()
                self._current_file.close()
            except Exception:
                pass

    def _write_batch(self, batch):
        """แปลงรายการข้อมูลและเขียนลง CSV writer."""
        for item in batch:
            row = self._format_row(item)
            self._current_writer.writerow(row)
            self._record_count += 1

    def _format_row(self, d: Dict[str, Any]):
        """แปลง dictionary เป็น tuple ตรงตามลำดับ CSV_COLUMNS."""
        def spd(v):
            return round(_vec_mag(v) * 3.6, 2)

        def mag(v):
            return round(_vec_mag(v), 4)

        v_used = d.get("v_used") or (0, 0, 0)
        v_20f0_07c0 = d.get("raw_20f0_07c0") or (0, 0, 0)
        v_20f0_0cf0 = d.get("raw_20f0_0cf0") or (0, 0, 0)
        v_20f0_0ea4 = d.get("raw_20f0_0ea4") or (0, 0, 0)
        v_24c0_0e90 = d.get("raw_24c0_0e90") or (0, 0, 0)
        v_14b8_0f48 = d.get("raw_14b8_0f48") or (0, 0, 0)
        v_0018_0318 = d.get("raw_0018_0318") or (0, 0, 0)
        v_pos_delta = d.get("pos_delta_vel") or (0, 0, 0)

        omg_0550 = d.get("raw_omg_0550") or (0, 0, 0)
        omg_0d14 = d.get("raw_omg_0d14") or (0, 0, 0)
        omg_used = d.get("used_omega") or (0, 0, 0)

        ac_omg = d.get("omega_centripetal_acc") or (0, 0, 0)
        k_acc = d.get("kalman_acc") or (0, 0, 0)
        f_acc = d.get("final_acc") or (0, 0, 0)

        raw_pos = d.get("raw_pos") or (0, 0, 0)
        k_pos = d.get("kalman_pos") or (0, 0, 0)
        k_vel = d.get("kalman_vel") or (0, 0, 0)

        lead_w = d.get("lead_world") or (0, 0, 0)
        t_scr = d.get("target_screen") or (0, 0)
        l_scr = d.get("lead_screen") or (0, 0)

        my_pos = d.get("my_pos") or (0, 0, 0)
        my_vel = d.get("my_vel") or (0, 0, 0)

        return [
            d.get("frame_idx", 0),
            round(d.get("timestamp", 0.0), 4),
            round(d.get("dt", 0.0), 5),
            round(d.get("fps", 0.0), 1),
            d.get("unit_ptr", "0x0"),
            d.get("unit_name", ""),
            round(d.get("dist_m", 0.0), 2),
            d.get("active_vel_source", ""),
            d.get("active_move_off", ""),
            d.get("active_vel_off", ""),
            d.get("active_move_ptr", ""),
            d.get("active_omg_source", ""),
            d.get("active_omg_off", ""),
            # v_used
            round(v_used[0], 3), round(v_used[1], 3), round(v_used[2], 3), spd(v_used),
            # raw candidates
            round(v_20f0_07c0[0], 3), round(v_20f0_07c0[1], 3), round(v_20f0_07c0[2], 3), spd(v_20f0_07c0),
            round(v_20f0_0cf0[0], 3), round(v_20f0_0cf0[1], 3), round(v_20f0_0cf0[2], 3), spd(v_20f0_0cf0),
            round(v_20f0_0ea4[0], 3), round(v_20f0_0ea4[1], 3), round(v_20f0_0ea4[2], 3), spd(v_20f0_0ea4),
            round(v_24c0_0e90[0], 3), round(v_24c0_0e90[1], 3), round(v_24c0_0e90[2], 3), spd(v_24c0_0e90),
            round(v_14b8_0f48[0], 3), round(v_14b8_0f48[1], 3), round(v_14b8_0f48[2], 3), spd(v_14b8_0f48),
            round(v_0018_0318[0], 3), round(v_0018_0318[1], 3), round(v_0018_0318[2], 3), spd(v_0018_0318),
            round(v_pos_delta[0], 3), round(v_pos_delta[1], 3), round(v_pos_delta[2], 3), spd(v_pos_delta),
            # omega
            round(omg_0550[0], 4), round(omg_0550[1], 4), round(omg_0550[2], 4), mag(omg_0550),
            round(omg_0d14[0], 4), round(omg_0d14[1], 4), round(omg_0d14[2], 4), mag(omg_0d14),
            round(omg_used[0], 4), round(omg_used[1], 4), round(omg_used[2], 4), mag(omg_used),
            # accels
            round(ac_omg[0], 3), round(ac_omg[1], 3), round(ac_omg[2], 3), mag(ac_omg),
            round(k_acc[0], 3), round(k_acc[1], 3), round(k_acc[2], 3), mag(k_acc),
            round(f_acc[0], 3), round(f_acc[1], 3), round(f_acc[2], 3), mag(f_acc),
            # positions & kalman
            round(raw_pos[0], 3), round(raw_pos[1], 3), round(raw_pos[2], 3),
            round(k_pos[0], 3), round(k_pos[1], 3), round(k_pos[2], 3),
            round(k_vel[0], 3), round(k_vel[1], 3), round(k_vel[2], 3), spd(k_vel),
            # leadmark
            round(d.get("tof", 0.0), 4),
            round(lead_w[0], 3), round(lead_w[1], 3), round(lead_w[2], 3),
            round(t_scr[0], 1), round(t_scr[1], 1),
            round(l_scr[0], 1), round(l_scr[1], 1),
            round(l_scr[0] - t_scr[0], 1), round(l_scr[1] - t_scr[1], 1),
            # my unit
            round(my_pos[0], 3), round(my_pos[1], 3), round(my_pos[2], 3),
            round(my_vel[0], 3), round(my_vel[1], 3), round(my_vel[2], 3), spd(my_vel),
            round(d.get("bullet_speed", 0.0), 1),
        ]

    def close(self):
        """ปิด worker thread เมื่อปิดโปรแกรม."""
        self.stop_session()
        self._stop_event.set()
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
