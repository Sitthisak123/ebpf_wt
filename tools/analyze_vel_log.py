#!/usr/bin/env python3
"""
Ground Velocity Telemetry Log Analyzer
เครื่องมือวิเคราะห์ Log ความเร็วภาคพื้นดินจากไฟล์ CSV
เพื่อหาสาเหตุของ Jitter (Spike, Staircase, Source Flapping)
"""

import os
import sys
import csv
import math

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ground_vel_log.csv")

def analyze(csv_file_path=None):
    path = csv_file_path or CSV_PATH
    if not os.path.isfile(path):
        print(f"❌ ไม่พบไฟล์ log: {path}")
        print("กรุณารัน 'tools/ground_vel_debugger.py' ก่อนเพื่อบันทึกข้อมูล")
        return

    print("=" * 70)
    print(f"📈 กำลังวิเคราะห์ข้อมูล TELEMETRY จาก: {os.path.basename(path)}")
    print("=" * 70)

    rows = []
    with open(path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    total_frames = len(rows)
    if total_frames == 0:
        print("❌ ไฟล์ log ว่างเปล่า")
        return

    moving_frames = []
    for r in rows:
        ch_kmh = float(r.get("my_chosen_kmh", 0.0))
        raw_kmh = float(r.get("my_raw_kmh", 0.0))
        pos_kmh = float(r.get("my_pos_kmh", 0.0))
        if ch_kmh > 2.0 or raw_kmh > 2.0 or pos_kmh > 2.0:
            moving_frames.append(r)

    n_move = len(moving_frames)
    print(f"  • จำนวนเฟรมทั้งหมด: {total_frames} เฟรม")
    print(f"  • เฟรมขณะเคลื่อนที่ (>2 km/h): {n_move} เฟรม ({(n_move/total_frames)*100.0:.1f}%)")

    if n_move < 5:
        print("\n⚠️ มีเฟรมขณะเคลื่อนที่น้อยเกินไป กรุณาขับรถถังวิ่งสัก 10-20 วินาทีแล้วลองใหม่อีกครั้ง")
        return

    staircase_count = sum(1 for r in moving_frames if int(r.get("my_is_staircase", 0)) == 1)
    spikes_3kmh = sum(1 for r in moving_frames if float(r.get("my_speed_delta_kmh", 0.0)) > 3.0)
    spikes_5kmh = sum(1 for r in moving_frames if float(r.get("my_speed_delta_kmh", 0.0)) > 5.0)

    # สถิติ Source
    sources = {}
    for r in moving_frames:
        s = r.get("my_source", "unknown")
        sources[s] = sources.get(s, 0) + 1

    # วิเคราะห์ Delta
    raw_speeds = [float(r["my_raw_kmh"]) for r in moving_frames]
    pos_speeds = [float(r["my_pos_kmh"]) for r in moving_frames]
    ch_speeds = [float(r["my_chosen_kmh"]) for r in moving_frames]

    avg_raw = sum(raw_speeds) / n_move
    avg_pos = sum(pos_speeds) / n_move
    avg_ch = sum(ch_speeds) / n_move

    # ความต่างระหว่าง Raw กับ Pos
    raw_pos_diffs = [abs(float(r["my_raw_kmh"]) - float(r["my_pos_kmh"])) for r in moving_frames]
    avg_diff = sum(raw_pos_diffs) / n_move

    print("\n📊 สถิติความเร็วเฉลี่ยขณะเคลื่อนที่:")
    print(f"  • Memory Raw Avg:    {avg_raw:.1f} km/h")
    print(f"  • Position Delta Avg: {avg_pos:.1f} km/h")
    print(f"  • Final Chosen Avg:   {avg_ch:.1f} km/h")
    print(f"  • Raw vs Pos ต่างกันเฉลี่ย: {avg_diff:.1f} km/h")

    print("\n🔍 การตรวจจับ Jitter Artifacts:")
    print(f"  • Staircase Freeze (พิกัดไม่ขยับใน 1 เฟรม): {staircase_count} ครั้ง ({(staircase_count/n_move)*100.0:.1f}%)")
    print(f"  • Speed Spike > 3 km/h ใน 16ms:            {spikes_3kmh} ครั้ง ({(spikes_3kmh/n_move)*100.0:.1f}%)")
    print(f"  • Speed Spike > 5 km/h ใน 16ms:            {spikes_5kmh} ครั้ง ({(spikes_5kmh/n_move)*100.0:.1f}%)")

    print("\n🏷️ การเลือกใช้ Velocity Source:")
    for s, cnt in sorted(sources.items(), key=lambda x: x[1], reverse=True):
        print(f"  • {s:<25}: {cnt:4d} เฟรม ({(cnt/n_move)*100.0:5.1f}%)")

    print("\n💡 การวินิจฉัยสาเหตุ (Root Cause Diagnosis):")
    if staircase_count > n_move * 0.15:
        print("  ❌ ตรวจพบ 'Staircase Tick Aliasing' ในระดับสูง!")
        print("     -> เกมไม่ได้อัปเดตพิกัดทุก 16ms (แต่อาจเป็น 30Hz หรือ 20Hz Tick)")
        print("     -> ส่งผลให้การคำนวณ pos_vel = dx/dt กลายเป็น 0 ในบางเฟรม และพุ่งสูงในเฟรมถัดไป")
        print("     -> แนวทางแก้ไข: ใช้ Raw Memory Velocity เป็นหลัก หรือใช้ Filter กรองรอบ Tick")
    elif len(sources) > 3:
        print("  ⚠️ ตรวจพบ 'Source Flapping' (การสลับไปมาระหว่าง Raw กับ Pos)")
        print("     -> ระบบสลับการคำนวณบ่อยเกินไป ทำให้ความเร็วกระตุก")
        print("     -> แนวทางแก้ไข: ล็อค Source หรือเพิ่ม Hysteresis Deadband")
    elif spikes_3kmh == 0:
        print("  ✅ ไม่พบ Speed Spike! ความเร็วนิ่งเรียบดีมาก")
    else:
        print("  ⚠️ พบการกระตุกเล็กน้อยเป็นจังหวะ")

    print("=" * 70)


if __name__ == "__main__":
    path_arg = sys.argv[1] if len(sys.argv) > 1 else None
    analyze(path_arg)
