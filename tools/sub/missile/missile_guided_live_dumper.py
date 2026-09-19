#!/usr/bin/env python3
"""
🎯 WT Guided Missile Live Dumper & Telemetry Analyzer (v4.0)
======================================================================
เครื่องมือดักจับ Struct และบันทึก Telemetry ของ Guided Missile แบบ Real-Time
ผูก (Bind) เข้ากับ ESP Overlay แบบ Real-time พร้อมเก็บ Raw ECS แบบ 100% Unfiltered:

Features:
  1. 🔗 ESP Overlay IPC Binding:
     - เชื่อมต่อผ่าน RAM (/dev/shm) ความเร็วสูงระดับไมโครวินาที (< 0.02ms)
     - แสดงผลสถานะความปลอดภัย, พิกัดบนจอ (w2s X, Y), และระดับภัยคุกคาม (Threat Level) ที่ ESP คำนวณได้
  2. 🔬 100% Complete Unfiltered Raw ECS Capture:
     - สแกน OFF_PROJ_LIST (1024 slots) และ OFF_ECS_NODE_TABLE (0..500 entries) ดิบทั้งหมด
     - ไม่ตัดตัวกรองใดๆ ทิ้งแม้แต่น้อย (เก็บแม้จะเป็น Flare/Chaff, Phase 6, Detonated, หรือ Speed ต่ำ)
     - ระบบ Diagnostic Filter Evaluator ระบุสาเหตุที่ ESP ปฏิเสธ (reject_reason) รายตัว
  3. 🗄️ Dual-Store High Performance Recording:
     - SQLite Database (`telemetry.db`): รองรับการรันคำสั่ง SQL Query วิเคราะห์ข้อมูลย้อนหลังทันที
     - Raw ECS Stream (`raw_ecs_stream.jsonl`): สแน็ปช็อตข้อมูลดิบและ Hex Preview ทุกเฟรม
     - ESP Track Stream (`esp_stream.jsonl`): ข้อมูลขีปนาวุธที่ผ่านตัวกรองของ ESP
     - CSV Trajectories (`tracks/track_*.csv`): พิกัดวิถีและความเร็วรายลูก สำหรับ Excel / Pandas
     - Comprehensive Summary (`summary.md` / `summary.json`): รายงานสรุปผลเมื่อจบ Session
  4. 🖥️ Live Terminal Dashboard (Dual Table):
     - ตารางบน: ESP DETECTED MISSILES (แสดงสถานะขีปนาวุธที่ ESP ตรวจจับและแจ้งเตือนบนจอ)
     - ตารางล่าง: RAW UNFILTERED ECS ENTITIES (แสดง Entity ทั้งหมดใน Memory พร้อมคำวินิจฉัย Verdict)
  5. 🔍 Built-in Analyzer & SQL Query Mode:
     - `python3 missile_guided_live_dumper.py --analyze [dir]`
     - `python3 missile_guided_live_dumper.py --sql "SELECT ..."`

Usage:
  - บันทึกสด:   echo awd25125 | sudo -S .venv/bin/python3 tools/sub/missile/missile_guided_live_dumper.py
  - วิเคราะห์:   python3 tools/sub/missile/missile_guided_live_dumper.py --analyze
  - รันคำสั่ง SQL: python3 tools/sub/missile/missile_guided_live_dumper.py --sql "SELECT ptr, name, speed, esp_verdict, reject_reason FROM raw_ecs_samples WHERE esp_verdict != 'ACCEPTED' LIMIT 10"
"""

import sys
import os
import struct
import math
import time
import json
import sqlite3
import argparse
from typing import Dict, List, Any, Optional, Tuple

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul
from src.utils.missile_telemetry import (
    RawECSScanner,
    MissileTelemetryBridge,
    TelemetrySessionRecorder,
    classify_seeker_type,
    calculate_mach,
    calculate_heading_pitch,
)


# ====================================================================
# Unit & Target Resolution Helper
# ====================================================================
def refresh_unit_map(sc, base: int, my_unit_ptr: int = 0, my_team: int = 0) -> Dict[Any, Dict[str, Any]]:
    """สร้างตารางจับคู่หน่วยรบ เพื่อทราบชื่อเครื่อง, ฝ่าย (YOU/FRIENDLY/ENEMY) และพิกัด"""
    unit_map = {}
    try:
        cgame_base = mul.get_cgame_base(sc, base)
        all_u = mul.get_all_units(sc, cgame_base)
        for u_ptr, is_air in all_u:
            raw = sc.read_mem(u_ptr + 0x08, 2)
            uid = struct.unpack("<H", raw)[0] if raw and len(raw) == 2 else -1
            prof = mul.get_unit_filter_profile(sc, u_ptr)
            dna = mul.get_unit_detailed_dna(sc, u_ptr) or {}
            uname = dna.get("short_name") or prof.get("short_name") or prof.get("display_name") or "Aircraft"

            status = mul.get_unit_status(sc, u_ptr)
            team_val = status[1] if status else 0
            if u_ptr == my_unit_ptr:
                relation = "YOU"
            elif team_val == my_team:
                relation = "FRIENDLY"
            else:
                relation = "ENEMY"

            pos = mul.get_unit_pos(sc, u_ptr) if hasattr(mul, "get_unit_pos") else (0.0, 0.0, 0.0)

            record = {
                "ptr": u_ptr,
                "uid": uid,
                "name": uname,
                "relation": relation,
                "team": team_val,
                "pos": pos,
                "is_air": is_air,
            }
            unit_map[u_ptr] = record
            if uid > 0:
                unit_map[uid] = record
    except Exception:
        pass
    return unit_map


# ====================================================================
# Terminal UI Dashboard (Dual-Table Display)
# ====================================================================
class LiveDashboardRenderer:
    """แสดงผล Live Terminal Dashboard แบบ Dual-Table แสดงทั้ง ESP Tracks และ Raw ECS"""

    def __init__(self):
        self.last_render_t = 0.0

    def render(
        self,
        frame_num: int,
        fps: float,
        session_id: str,
        my_plane: str,
        esp_connected: bool,
        esp_frame_info: Optional[Dict[str, Any]],
        esp_tracks: List[Dict[str, Any]],
        raw_candidates: List[Dict[str, Any]],
        total_raw_captured: int,
        unfiltered_only: bool = False,
    ):
        now = time.time()
        if (now - self.last_render_t) < 0.09:
            return
        self.last_render_t = now

        lines = []
        lines.append("\033[2J\033[H")  # Clear screen ANSI

        # Header Box
        w = 118
        lines.append("╔" + "═" * w + "╗")
        esp_status_badge = "\033[92;1m🟢 BOUND TO ESP (Live Sync via SHM)\033[0m" if esp_connected else "\033[90m⚪ ESP STANDALONE (Overlay Not Active)\033[0m"
        lines.append(f"║ 🎯 WT MISSILE TELEMETRY & RAW ECS ANALYZER v4.0 {' ':25} {esp_status_badge:<45} ║")
        
        esp_warn_text = ""
        if esp_frame_info and esp_frame_info.get("warning_active"):
            stage = esp_frame_info.get("auto_cm_stage", 0)
            esp_warn_text = f"\033[91;1m🚨 ESP WARNING ACTIVE (Stage {stage})\033[0m"
        else:
            esp_warn_text = "\033[92m🛡️ ALL CLEAR\033[0m"

        lines.append(
            f"║ Session: \033[96m{session_id}\033[0m | Plane: \033[93m{my_plane[:22]:<22}\033[0m | Frame: {frame_num:<6} | FPS: {fps:4.1f} | Status: {esp_warn_text:<32} ║"
        )
        lines.append("╠" + "═" * w + "╣")

        # Table 1: ESP Detected Missiles (Active on Screen)
        if not unfiltered_only:
            lines.append(f"║ 🖥️  TABLE 1: ESP DETECTED MISSILES (Active in ESP Radar & Screen Overlay: {len(esp_tracks)} Tracks){' ':37} ║")
            lines.append("╟" + "─" * w + "╢")
            lines.append(
                f"║ {'ID':<4} {'WEAPON':<20} {'DIST':<9} {'SPEED':<11} {'SEEKER/LOCK':<13} {'SHOOTER ──► TARGET':<27} {'SCREEN POS':<14} {'THREAT':<14} ║"
            )
            lines.append("╟" + "─" * w + "╢")

            if not esp_tracks:
                lines.append(f"║ {'⏳ ไม่พบขีปนาวุธที่ ESP กำลังวาดบนจอ (0 Active ESP Tracks)':^{w}} ║")
            else:
                for idx, tr in enumerate(esp_tracks[:8]):
                    mid = f"#{idx+1}"
                    wname = tr.get("name", "Unknown")[:19]
                    dist_v = tr.get("dist", 0.0)
                    dist_s = f"{dist_v/1000.0:.1f}km" if dist_v >= 1000 else f"{dist_v:.0f}m"
                    spd_s = f"{tr.get('speed', 0.0):.0f}m/s"

                    # Seeker
                    if tr.get("is_guided_me"):
                        sk_str = "\033[91;1m🚨LOCKED YOU\033[0m"
                    elif tr.get("is_sam"):
                        sk_str = "\033[93m⚡SAM/BEAM\033[0m"
                    elif tr.get("target_id", 0) > 0:
                        sk_str = f"🎯#{tr.get('target_id')}"
                    else:
                        sk_str = "UNGUIDED"

                    sh_name = tr.get("shooter_name") or "Unknown"
                    tg_name = tr.get("target_name") or "None"
                    sh_tg = f"{sh_name[:11]} ─► {tg_name[:11]}"

                    w2s = tr.get("w2s")
                    if w2s:
                        scr_s = f"\033[92m{int(w2s[0])},{int(w2s[1])}\033[0m"
                    else:
                        scr_s = "\033[90mOFFSCREEN\033[0m"

                    th = tr.get("threat_level", "NORMAL")
                    if th == "CRITICAL":
                        th_str = "\033[91;1mCRITICAL\033[0m"
                    elif th == "HIGH":
                        th_str = "\033[93;1mHIGH\033[0m"
                    elif th == "WARNING":
                        th_str = "\033[93mWARNING\033[0m"
                    else:
                        th_str = "\033[90mNORMAL\033[0m"

                    lines.append(
                        f"║ {mid:<4} {wname:<20} {dist_s:<9} {spd_s:<11} {sk_str:<22} {sh_tg:<27} {scr_s:<23} {th_str:<23} ║"
                    )

            lines.append("╠" + "═" * w + "╣")

        # Table 2: 100% Unfiltered Raw ECS Entities
        accepted_cnt = sum(1 for c in raw_candidates if c["esp_verdict"] == "ACCEPTED")
        rejected_cnt = len(raw_candidates) - accepted_cnt
        lines.append(
            f"║ 🔬 TABLE 2: RAW UNFILTERED ECS ENTITIES (100% Memory Scan: {len(raw_candidates)} Found | ✅ {accepted_cnt} Accepted | 🚫 {rejected_cnt} Filtered Out){' ':8} ║"
        )
        lines.append("╟" + "─" * w + "╢")
        lines.append(
            f"║ {'PTR':<18} {'SOURCE':<20} {'WEAPON/BLK':<20} {'SPEED':<11} {'ST/PH/DET':<11} {'GUID':<6} {'ESP VERDICT & DIAGNOSIS':<26} ║"
        )
        lines.append("╟" + "─" * w + "╢")

        if not raw_candidates:
            lines.append(f"║ {'🔍 กำลังสแกนหน่วยความจำ ECS Node Table และ Proj List...':^{w}} ║")
        else:
            # Display up to 12 raw candidates, prioritizing accepted or notable ones
            sorted_cands = sorted(
                raw_candidates,
                key=lambda x: (0 if x["esp_verdict"] == "ACCEPTED" else 1, -x["speed"]),
            )
            for c in sorted_cands[:12]:
                ptr_s = hex(c["ptr"])
                src_s = c["source"][:19]
                wname = (c["name"] or "<Unknown>")[:19]
                spd_s = f"{c['speed']:.0f}m/s"
                st_ph = f"{c['state']}/{c['phase']}/{c['detonated']}"
                guid_s = "YES" if c["is_guided"] else "-"

                if c["esp_verdict"] == "ACCEPTED":
                    verdict_s = "\033[92;1m✅ ACCEPTED\033[0m"
                else:
                    reason_abbr = c["reject_reason"].replace("SPEED_", "SPD_").replace("COUNTERMEASURE_", "CM_")[:17]
                    verdict_s = f"\033[91m🚫 {reason_abbr}\033[0m"

                lines.append(
                    f"║ {ptr_s:<18} {src_s:<20} {wname:<20} {spd_s:<11} {st_ph:<11} {guid_s:<6} {verdict_s:<35} ║"
                )

        lines.append("╚" + "═" * w + "╝")
        lines.append(
            f"💡 บันทึกอัตโนมัติ: \033[96mtelemetry.db\033[0m (SQLite) | \033[96mraw_ecs_stream.jsonl\033[0m | \033[96mtracks/*.csv\033[0m | กด \033[93mCtrl+C\033[0m เพื่อสร้างสรุป"
        )
        print("\n".join(lines), flush=True)


# ====================================================================
# Offline Analyzer & SQL Query Modes
# ====================================================================
def run_analyzer(target_dir: Optional[str] = None):
    """วิเคราะห์ผลลัพธ์จากโฟลเดอร์ Dump ที่เลือกหรือโฟลเดอร์ล่าสุด"""
    dumps_base = os.path.join(PROJECT_ROOT, "logs", "missile_dumps")
    if not target_dir or target_dir == "latest":
        if not os.path.exists(dumps_base):
            print(f"❌ ไม่พบโฟลเดอร์ {dumps_base}!")
            return
        sessions = sorted([s for s in os.listdir(dumps_base) if os.path.isdir(os.path.join(dumps_base, s))])
        if not sessions:
            print("❌ ยังไม่มีประวัติ Session ข้อมูลขีปนาวุธ!")
            return
        target_dir = os.path.join(dumps_base, sessions[-1])
    else:
        target_dir = os.path.abspath(target_dir)

    summary_md = os.path.join(target_dir, "summary.md")
    if os.path.exists(summary_md):
        print(f"\n📄 [SESSION REPORT] {os.path.basename(target_dir)}")
        print("=" * 80)
        with open(summary_md, "r", encoding="utf-8") as f:
            print(f.read())
        print("=" * 80)
    else:
        print(f"❌ ไม่พบ {summary_md} ใน {target_dir}!")


def run_sql_query(query: str, target_dir: Optional[str] = None):
    """รันคำสั่ง SQL Query บน telemetry.db เพื่อตรวจสอบข้อมูลเชิงลึก"""
    dumps_base = os.path.join(PROJECT_ROOT, "logs", "missile_dumps")
    if not target_dir or target_dir == "latest":
        sessions = sorted([s for s in os.listdir(dumps_base) if os.path.isdir(os.path.join(dumps_base, s))])
        if not sessions:
            print("❌ ไม่พบ Session ฐานข้อมูล!")
            return
        target_dir = os.path.join(dumps_base, sessions[-1])

    db_path = os.path.join(target_dir, "telemetry.db")
    if not os.path.exists(db_path):
        print(f"❌ ไม่พบฐานข้อมูล SQLite: {db_path}")
        return

    print(f"\n🔍 [SQL QUERY] Executing on: {db_path}")
    print(f"   Query: {query}\n" + "-" * 80)

    try:
        try:
            conn = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
        except Exception:
            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            except Exception:
                conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(query)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []

        if not rows:
            print("⚪ ไม่พบข้อมูลที่ตรงกับเงื่อนไข (0 rows returned)")
        else:
            # Print table
            header = " | ".join(f"{c:<18}" for c in cols)
            print(header)
            print("-" * len(header))
            for r in rows:
                print(" | ".join(f"{str(v):<18}" for v in r))
            print(f"\n✅ Total Rows: {len(rows)}")
        conn.close()
    except Exception as e:
        print(f"❌ SQL Error: {e}")


# ====================================================================
# Main Application Loop
# ====================================================================
def main():
    parser = argparse.ArgumentParser(description="War Thunder Missile Live Dumper & ESP Telemetry Analyzer v4.0")
    parser.add_argument("--analyze", nargs="?", const="latest", help="เปิดดูรายงานสรุป (ระบุโฟลเดอร์หรือเว้นว่างเพื่อดูรอบล่าสุด)")
    parser.add_argument("--sql", type=str, help="รันคำสั่ง SQL Query บน telemetry.db ของ Session ล่าสุด")
    parser.add_argument("--session", type=str, help="ระบุโฟลเดอร์ Session เฉพาะเจาะจงสำหรับ --analyze หรือ --sql")
    parser.add_argument("--interval", type=float, default=0.05, help="อัตราการสแกนต่อวินาที (ค่าเริ่มต้น 0.05s = 20 FPS)")
    parser.add_argument("--unfiltered-only", action="store_true", help="แสดงเฉพาะตาราง Raw ECS Unfiltered เท่านั้น")
    args = parser.parse_args()

    if args.sql:
        run_sql_query(args.sql, args.session)
        return

    if args.analyze:
        target = args.session or args.analyze
        run_analyzer(target)
        return

    print("🚀 [BOOT] กำลังเชื่อมต่อกระบวนการเกม War Thunder (aces)...")
    pid = get_game_pid()
    if not pid:
        print("❌ ไม่พบ Game PID ของ War Thunder! กรุณาเปิดเกมก่อนรันสคริปต์")
        return

    base = get_game_base_address(pid)
    sc = MemoryScanner(pid)
    init_dynamic_offsets(sc, base)

    # 1. Initialize Core Components
    raw_scanner = RawECSScanner()
    bridge = MissileTelemetryBridge(is_publisher=False)

    # 2. Session Directory & Recorder
    session_id = time.strftime("%Y%m%d_%H%M%S")
    recorder = TelemetrySessionRecorder(session_id)

    print(f"[+] PID: {pid}, Base: {hex(base)}")
    print(f"[+] Database & Logs: {recorder.dir}/")

    my_unit, my_team = mul.get_local_team(sc, base)
    unit_map = refresh_unit_map(sc, base, my_unit, my_team)
    my_plane_name = unit_map.get(my_unit, {}).get("name", "Unknown Aircraft")
    print(f"[+] Local Unit: {hex(my_unit)} | Aircraft: {my_plane_name} | Team: {my_team}")

    dashboard = LiveDashboardRenderer()
    frame_count = 0
    start_time = time.time()
    last_unit_refresh = 0.0

    print("🟢 เริ่มต้นการดักจับข้อมูลแบบ Real-Time (กด Ctrl+C เพื่อหยุดและสร้างสรุป)...")
    time.sleep(0.5)

    running = True

    def _sig_handler(signum, frame):
        nonlocal running
        running = False

    import signal
    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT, _sig_handler)

    try:
        while running:
            now = time.time()
            frame_count += 1

            # Refresh Unit Map every 2.0s
            if (now - last_unit_refresh) > 2.0:
                unit_map = refresh_unit_map(sc, base, my_unit, my_team)
                last_unit_refresh = now

            # 1. Read Latest ESP Broadcast (if radar_overlay.py is running)
            esp_connected = bridge.is_esp_connected(max_age=1.5)
            esp_frame_data = bridge.read_latest(max_age=2.0) if esp_connected else None
            esp_tracks = esp_frame_data.get("tracks", []) if esp_frame_data else []

            # 2. Complete 100% Unfiltered Scan of ECS Node Table & Proj List
            raw_candidates = raw_scanner.scan_all_raw_entities(sc, base, max_entries=500)

            # 3. Log to SQLite, JSONL, and CSV Tracks via non-blocking worker thread
            recorder.log_tick(frame_count, now, raw_candidates, esp_tracks)

            # 4. Render Live Dual-Table Terminal Dashboard
            elapsed = max(0.1, now - start_time)
            fps = frame_count / elapsed
            dashboard.render(
                frame_count,
                fps,
                session_id,
                my_plane_name,
                esp_connected,
                esp_frame_data,
                esp_tracks,
                raw_candidates,
                recorder.total_raw_captured,
                unfiltered_only=args.unfiltered_only,
            )

            time.sleep(args.interval)

    except KeyboardInterrupt:
        pass
    finally:
        print("\n\n" + "=" * 80)
        print("💾 กำลังบันทึกข้อมูลและสร้างรายงานสรุป (Closing Session)...")
        meta_info = {
            "game_pid": pid,
            "player_unit": hex(my_unit),
            "player_team": my_team,
            "aircraft_name": my_plane_name,
            "total_frames": frame_count,
            "duration_s": round(time.time() - start_time, 2),
        }
        recorder.close(meta_info)
        print("✅ ปิด Session และบันทึกข้อมูลสมบูรณ์แบบ!")
        print(f"📂 โฟลเดอร์ Session: {recorder.dir}/")
        print(f"   - 📄 summary.md (ตารางสรุป Entity และผลการวินิจฉัย)")
        print(f"   - 🗄️ telemetry.db (ฐานข้อมูล SQLite สำหรับสืบค้น)")
        print(f"   - 📜 raw_ecs_stream.jsonl (ข้อมูลดิบ 100% ทั้งหมดใน ECS)")
        print(f"   - 📜 esp_stream.jsonl (ข้อมูลการตรวจจับของ ESP)")
        print(f"   - 📊 tracks/*.csv (ไฟล์วิถีและความเร็วรายลูก)")
        print("=" * 80)
        print(f"💡 คำสั่งวิเคราะห์ย้อนหลัง:")
        print(f"   python3 tools/sub/missile/missile_guided_live_dumper.py --analyze {recorder.dir}")
        print(f"   python3 tools/sub/missile/missile_guided_live_dumper.py --session {recorder.dir} --sql \"SELECT ptr, name, speed, esp_verdict, reject_reason FROM raw_ecs_samples WHERE esp_verdict != 'ACCEPTED' LIMIT 15\"\n")


if __name__ == "__main__":
    main()
