#!/usr/bin/env python3
"""
05_airmove_tickrate.py — War Thunder Air Movement 10-Second Tickrate Analyzer

เฝ้าดูและวัดอัตราการอัปเดต (Tick Rate / Hz) ของการเคลื่อนที่ของเครื่องบินเราเอง (My Unit)
ทั้งความเร็วเชิงเส้น (Velocity) และความเร็วเชิงมุม (Omega / Angular Velocity)
ด้วยการสังเกตการณ์จับเวลา 10 วินาที (10-Second Watch Session)
"""

import os
import sys
import time
import math
import struct

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
from src.utils.mul import (
    get_cgame_base, get_local_team, get_unit_status, is_valid_ptr,
    OFF_AIR_MOVEMENT, OFF_AIR_VEL, OFF_AIR_OMEGA,
    OFF_MY_AIR_MOVEMENT, OFF_MY_AIR_VEL, OFF_MY_AIR_OMEGA,
)

WATCH_DURATION = 10.0  # 10 วินาที
CHANGE_EPSILON = 0.001 # เกณฑ์ขั้นต่ำของความต่างที่นับเป็น 1 Tick


def read_vec3(scanner, base_ptr, offset, data_type):
    """อ่าน vec3 (FLOAT หรือ DOUBLE) จาก base_ptr + offset."""
    if not is_valid_ptr(base_ptr):
        return None
    try:
        size = 24 if data_type == "DOUBLE" else 12
        fmt = "<ddd" if data_type == "DOUBLE" else "<fff"
        raw = scanner.read_mem(base_ptr + offset, size)
        if not raw or len(raw) < size:
            return None
        v = struct.unpack(fmt, raw)
        if not all(math.isfinite(x) for x in v):
            return None
        return v
    except Exception:
        return None


def vec_mag(vec):
    """คำนวณ Magnitude ของเวกเตอร์ 3D."""
    if not vec:
        return 0.0
    return math.sqrt(vec[0]**2 + vec[1]**2 + vec[2]**2)


def resolve_move_pointer(scanner, u_ptr, offset_candidates):
    """ค้นหา Move Pointer ที่ถูกต้องจากรายการ Candidates."""
    if isinstance(offset_candidates, int):
        offset_candidates = [offset_candidates]
    for off in offset_candidates:
        try:
            raw = scanner.read_mem(u_ptr + off, 8)
            if raw and len(raw) == 8:
                ptr = struct.unpack("<Q", raw)[0]
                if is_valid_ptr(ptr):
                    return ptr, off
        except Exception:
            pass
    return 0, 0


def build_channel_list(scanner, my_unit_ptr):
    """สร้างรายการช่องทางข้อมูล (Channels) ที่ต้องการวัด Tickrate."""
    m_high, off_high = resolve_move_pointer(scanner, my_unit_ptr, (OFF_MY_AIR_MOVEMENT, 0x0D50, 0x0D28, 0x0D10))
    m_net, off_net   = resolve_move_pointer(scanner, my_unit_ptr, OFF_AIR_MOVEMENT)
    m_kin, off_kin   = resolve_move_pointer(scanner, my_unit_ptr, (0x24C0, 0x24C8))

    channels = [
        # --- VELOCITY CHANNELS ---
        {
            "category": "VELOCITY",
            "name": "My Vel (High-Tick)",
            "source": f"Move_{hex(off_high)}",
            "ptr": m_high,
            "off": OFF_MY_AIR_VEL, # 0x0068
            "type": "DOUBLE",
            "unit": "km/h",
            "scale": 3.6,
        },
        {
            "category": "VELOCITY",
            "name": "Net Vel (Standard)",
            "source": f"Move_{hex(off_net)}",
            "ptr": m_net,
            "off": OFF_AIR_VEL, # 0x0318
            "type": "FLOAT",
            "unit": "km/h",
            "scale": 3.6,
        },
        # --- OMEGA CHANNELS ---
        {
            "category": "OMEGA",
            "name": "My Omega (High-Tick)",
            "source": f"Move_{hex(off_high)}",
            "ptr": m_high,
            "off": OFF_MY_AIR_OMEGA, # 0x0098
            "type": "DOUBLE",
            "unit": "rad/s",
            "scale": 1.0,
        },
        {
            "category": "OMEGA",
            "name": "Net Omega (Updated)",
            "source": f"Move_{hex(off_net)}",
            "ptr": m_net,
            "off": OFF_AIR_OMEGA, # 0x0550
            "type": "FLOAT",
            "unit": "rad/s",
            "scale": 1.0,
        },
        {
            "category": "OMEGA",
            "name": "Net Omega (Historic)",
            "source": f"Move_{hex(off_net)}",
            "ptr": m_net,
            "off": 0x03F8,
            "type": "FLOAT",
            "unit": "rad/s",
            "scale": 1.0,
        },
    ]

    # เพิ่ม Kinematics ถ้ามี
    if m_kin:
        channels.append({
            "category": "VELOCITY",
            "name": "Air-Kin Vel (Alt)",
            "source": f"Move_{hex(off_kin)}",
            "ptr": m_kin,
            "off": 0x0E90,
            "type": "FLOAT",
            "unit": "km/h",
            "scale": 3.6,
        })

    return channels, (m_high, m_net, m_kin)


def run_10s_watch_session(scanner, my_unit_ptr, unit_name):
    """ดำเนินการเฝ้าดูและวัด Tickrate เป็นเวลา 10 วินาที พร้อม UI แบบสด."""
    channels, ptrs = build_channel_list(scanner, my_unit_ptr)

    # Initial state tracking
    for ch in channels:
        ch["ticks"] = 0
        ch["reads"] = 0
        ch["last_vec"] = None
        ch["peak_val"] = 0.0
        ch["latest_val"] = 0.0

    start_time = time.time()
    last_ui_update = 0.0
    loop_count = 0

    try:
        while True:
            curr_time = time.time()
            elapsed = curr_time - start_time
            if elapsed >= WATCH_DURATION:
                break

            loop_count += 1

            # อ่านและนับ Ticks ทุกช่องทาง
            for ch in channels:
                if not ch["ptr"]:
                    continue
                vec = read_vec3(scanner, ch["ptr"], ch["off"], ch["type"])
                if vec is not None:
                    ch["reads"] += 1
                    scaled_mag = vec_mag(vec) * ch["scale"]
                    ch["latest_val"] = scaled_mag
                    if scaled_mag > ch["peak_val"]:
                        ch["peak_val"] = scaled_mag

                    if ch["last_vec"] is not None:
                        diff = sum(abs(vec[i] - ch["last_vec"][i]) for i in range(3))
                        if diff > CHANGE_EPSILON:
                            ch["ticks"] += 1
                    ch["last_vec"] = vec

            # อัปเดตหน้าจอทุก ~50ms (20 FPS)
            if curr_time - last_ui_update >= 0.05:
                last_ui_update = curr_time
                progress = min(elapsed / WATCH_DURATION, 1.0)
                bar_len = 25
                filled = int(bar_len * progress)
                bar = "█" * filled + "░" * (bar_len - filled)
                loop_hz = loop_count / max(elapsed, 1e-6)

                os.system("clear")
                print("═══════════════════════════════════════════════════════════════════════════════════════")
                print("  ⏱️  AIR MOVEMENT 10-SECOND TICKRATE WATCHER")
                print(f"  Target: {unit_name} ({hex(my_unit_ptr)})  |  Session Time: [{bar}] {elapsed:4.1f}s / {WATCH_DURATION:.1f}s")
                print(f"  Internal Sampling Loop: {loop_hz:7.1f} Hz (High Precision Profiler)")
                print("═══════════════════════════════════════════════════════════════════════════════════════")
                print(f"{'Category':<9s} | {'Name':<22s} | {'Offset':<8s} | {'Type':<6s} | {'Ticks':>5s} | {'Tickrate':>8s} | {'Live Value'}")
                print("─" * 87)

                for ch in channels:
                    if not ch["ptr"]:
                        print(f"{ch['category']:<9s} | {ch['name']:<22s} | {hex(ch['off']):<8s} | {ch['type']:<6s} | {'-':>5s} | {'N/A':>8s} | (Pointer Not Available)")
                        continue

                    current_hz = ch["ticks"] / max(elapsed, 1e-6)
                    hz_badge = f"{current_hz:5.1f} Hz"
                    if current_hz >= 40.0:
                        status_tag = f"⚡ High-Tick ({ch['latest_val']:6.1f} {ch['unit']})"
                    elif current_hz >= 4.0:
                        status_tag = f"🟢 Normal-Tick ({ch['latest_val']:6.1f} {ch['unit']})"
                    elif ch["ticks"] > 0:
                        status_tag = f"🟡 Low-Tick ({ch['latest_val']:6.1f} {ch['unit']})"
                    else:
                        status_tag = f"⚪ Idle/Static ({ch['latest_val']:6.1f} {ch['unit']})"

                    print(f"{ch['category']:<9s} | {ch['name']:<22s} | {hex(ch['off']):<8s} | {ch['type']:<6s} | {ch['ticks']:5d} | {hz_badge:>8s} | {status_tag}")

                print("───────────────────────────────────────────────────────────────────────────────────────")
                print("💡 ทริค: ลองเร่งความเร็ว / ดึงเลี้ยว / ควงสว่าน (Roll) เพื่อสังเกตการณ์การอัปเดตแบบสดๆ")

            time.sleep(0.003) # ความเร็วแซมปลิ้ง ~300Hz

    except KeyboardInterrupt:
        print("\n\n⚠️ หยุดการจับเวลากลางคัน!")

    # ═══════════════════════════════════════════════════════════
    # FINAL 10-SECOND SUMMARY REPORT
    # ═══════════════════════════════════════════════════════════
    final_elapsed = max(time.time() - start_time, 1e-6)
    os.system("clear")
    print("═══════════════════════════════════════════════════════════════════════════════════════")
    print("  🏆 FINAL 10-SECOND WATCH SUMMARY REPORT")
    print(f"  Target: {unit_name} ({hex(my_unit_ptr)})  |  Total Elapsed Time: {final_elapsed:.2f} วินาที")
    print(f"  Total Loops: {loop_count}  |  Avg Loop Rate: {loop_count / final_elapsed:.1f} Hz")
    print("═══════════════════════════════════════════════════════════════════════════════════════")
    print(f"{'Category':<9s} | {'Channel Name':<22s} | {'Offset':<8s} | {'Ticks':>6s} | {'Avg Hz':>8s} | {'Peak Val':>12s} | {'Verdict'}")
    print("─" * 95)

    for ch in channels:
        if not ch["ptr"]:
            print(f"{ch['category']:<9s} | {ch['name']:<22s} | {hex(ch['off']):<8s} | {'-':>6s} | {'N/A':>8s} | {'-':>12s} | ❌ Pointer Missing")
            continue

        avg_hz = ch["ticks"] / final_elapsed
        peak_str = f"{ch['peak_val']:6.1f} {ch['unit']}"

        if avg_hz >= 40.0:
            verdict = "⚡ ULTRA SMOOTH (High-Tick 50Hz+) 🌟"
        elif avg_hz >= 15.0:
            verdict = "🟢 SMOOTH (Intermediate ~20-30Hz)"
        elif avg_hz >= 3.0:
            verdict = "🟡 NETWORK STANDARD (~5Hz)"
        elif ch["ticks"] > 0:
            verdict = "🟠 SLOW UPDATE (<3Hz)"
        else:
            verdict = "⚪ NO CHANGE DETECTED (0Hz / Static)"

        print(f"{ch['category']:<9s} | {ch['name']:<22s} | {hex(ch['off']):<8s} | {ch['ticks']:6d} | {avg_hz:6.1f} Hz | {peak_str:>12s} | {verdict}")

    print("═══════════════════════════════════════════════════════════════════════════════════════")
    print("📋 ข้อสังเกตและคำแนะนำ:")
    print("  • หาก High-Tick (0x0D48) มี Tickrate > 40Hz: เหมาะอย่างยิ่งสำหรับใช้เป็น Leadmark / CCIP")
    print("  • หาก Omega (0x0098 / 0x0550) แสดงค่า > 0 ตอนเลี้ยว: ยืนยันว่าระบบนำทางคำนวณการเลี้ยวถูกต้อง")
    print("───────────────────────────────────────────────────────────────────────────────────────")


def main():
    print("[*] กำลังเชื่อมต่อระบบและค้นหาเกม War Thunder...")
    pid = get_game_pid()
    base_address = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_address)

    while True:
        os.system("clear")
        print("══════════════════════════════════════════════════")
        print("  ✈️  AIR MOVEMENT 10-SEC TICKRATE ANALYZER")
        print("══════════════════════════════════════════════════")
        print(f"PID: {pid} | Base: {hex(base_address)}")

        my_unit_ptr, my_team = get_local_team(scanner, base_address)
        unit_name = "UNKNOWN"
        if my_unit_ptr:
            status = get_unit_status(scanner, my_unit_ptr, read_name=True)
            if status:
                if isinstance(status, tuple) and len(status) >= 3:
                    unit_name = status[2] or "AIRCRAFT"
                elif isinstance(status, dict):
                    unit_name = status.get("short_name", "AIRCRAFT")
            print(f"✈️ Unit: {unit_name} ({hex(my_unit_ptr)}) | Team: {my_team}")
        else:
            print("⚠️ ยังไม่พบยูนิตเครื่องบิน (กรุณาเข้าห้อง Test Flight หรือแมตช์จริง)")

        print("\n[1] 🚀 เริ่มจับเวลาเฝ้าดู 10 วินาที (Start 10s Watch Session)")
        print("[2] 🔄 โหมดวนซ้ำต่อเนื่อง (Continuous 10s Watch Loop)")
        print("[0] ❌ ออกจากโปรแกรม")
        print("──────────────────────────────────────────────────")

        choice = input("👉 เลือกคำสั่ง: ").strip()

        if choice == "0":
            break
        elif choice == "1":
            if not my_unit_ptr:
                input("[-] กรุณาเข้าห้องบินในเกมก่อน กด Enter...")
                continue
            run_10s_watch_session(scanner, my_unit_ptr, unit_name)
            input("\n👉 กด [Enter] เพื่อกลับสู่เมนูหลัก...")
        elif choice == "2":
            if not my_unit_ptr:
                input("[-] กรุณาเข้าห้องบินในเกมก่อน กด Enter...")
                continue
            try:
                while True:
                    run_10s_watch_session(scanner, my_unit_ptr, unit_name)
                    print("\n⏳ เตรียมเริ่มรอบใหม่ใน 2 วินาที (กด Ctrl+C เพื่อกลับเมนู)...")
                    time.sleep(2.0)
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
