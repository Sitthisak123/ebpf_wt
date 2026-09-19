#!/usr/bin/env python3
"""
🎯 WT Guided Missile Live Dumper & Telemetry Analyzer (v3.0)
======================================================================
เครื่องมือดักจับ Struct และบันทึก Telemetry ของ Guided Missile แบบ Real-Time
พร้อมระบบวิเคราะห์อัตโนมัติ (CSV Track ต่อลูก, Summary Markdown, CLI Dashboard)

Features:
  1. 📊 Ez-to-Analyze Output:
     - `tracks/track_XX_<weapon>.csv`: ไฟล์ CSV รายลูก เปิดใน Excel/Plotly กราฟดูวิถีและความเร็วได้ทันที
     - `summary.md` & `summary.json`: รายงานสรุปภาพรวมของทุกขีปนาวุธในรอบนั้น
     - `events.jsonl`: บันทึกเหตุการณ์และ Raw Memory Snapshots รวมในไฟล์เดียว
  2. 📡 More Data & Rich Telemetry:
     - Shooter info (ชื่อเครื่อง, ทีม YOU/FRIENDLY/ENEMY, พิกัด, ระยะยิงตอนปล่อย)
     - Target info (ชื่อเป้าหมาย, ทีม, ระยะประชิด, Closure Rate)
     - Seeker details (ชนิด Seeker: IR/SARH/ARH/SACLOS, Lock/Track flag, Lock duration)
     - Aerodynamics (Mach number ตามความสูง ISA, G-Force, Heading/Pitch, Flight distance)
     - Termination Cause (💥 ระเบิด, 🎯 โดนเป้า, ⛰️ ชนพื้น, 💨 หลุดจาก Slot)
  3. 🖥️ Live Terminal Dashboard:
     - แสดงตารางข้อมูลสถานะจรวดที่กำลังบินอยู่แบบ Real-time
     - มีเสียงและข้อความเตือนพิเศษเมื่อมีจรวดเล็งมาที่ตัวคุณ (🚨 TARGETING YOU!)
  4. 🔍 Built-in Analyzer Mode:
     - รัน `python3 missile_guided_live_dumper.py --analyze [dir]` เพื่อเปิดดูรายงานย้อนหลัง

Usage:
  - บันทึกสด:   echo awd25125 | sudo -S python3 tools/sub/missile/missile_guided_live_dumper.py
  - วิเคราะห์:   python3 tools/sub/missile/missile_guided_live_dumper.py --analyze
"""

import sys, os, struct, math, time, json, hashlib, csv, argparse
from collections import defaultdict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul


# ====================================================================
# Configuration & Offsets
# ====================================================================
OFF_ECS_MANAGER    = getattr(mul, 'OFF_ECS_MANAGER', 0xb0e29b8)
OFF_ECS_NODE_TABLE = getattr(mul, 'OFF_ECS_NODE_TABLE', 0x178)
OFF_ECS_CLASS_TABLE= getattr(mul, 'OFF_ECS_CLASS_TABLE', 0x5E8)
OFF_PROJ_LIST      = getattr(mul, 'OFF_PROJ_LIST', 0xac02ab8)

OFFSET_SETS = [
    (
        "starned",
        getattr(mul, 'OFF_RKT_POS', 0x23c),
        getattr(mul, 'OFF_RKT_VEL', 0x258),
        getattr(mul, 'OFF_RKT_OWNER', 0x50),
        getattr(mul, 'OFF_RKT_STATE', 0x94),
        getattr(mul, 'OFF_RKT_GUIDANCE', 0x670),
        getattr(mul, 'OFF_RKT_ENTITY_ID', 0x40),
        getattr(mul, 'OFF_RKT_PROPS', 0x700),
    ),
]

COUNTERMEASURE_KEYWORDS = (
    "flare", "chaff", "countermeasure", "decoy", "dispenser"
)


# ====================================================================
# Memory & Math Helpers
# ====================================================================
def rp(sc, a):
    d = sc.read_mem(a, 8)
    return struct.unpack("<Q", d)[0] if d and len(d) >= 8 else 0

def r8(sc, a):
    d = sc.read_mem(a, 1)
    return d[0] if d and len(d) >= 1 else 0

def r16(sc, a):
    d = sc.read_mem(a, 2)
    return struct.unpack("<h", d)[0] if d and len(d) >= 2 else 0

def is_valid_ptr(v):
    return 0x100000 < v < 0x7FFFFFFFFFFF

def vlen(v):
    return math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])

def vdist(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)

def is_valid_vec3(v):
    if not all(math.isfinite(x) for x in v):
        return False
    for x in v:
        if x != 0.0 and abs(x) < 1e-3:
            return False
    return True

def is_valid_missile_motion(pos, vel):
    if not is_valid_vec3(pos) or not is_valid_vec3(vel):
        return False, 0.0
    if any(abs(x) > 250000.0 for x in pos):
        return False, 0.0
    if sum(1 for x in pos if abs(x) > 5.0) < 2:
        return False, 0.0
    if (pos[0]*pos[0] + pos[1]*pos[1] + pos[2]*pos[2]) < 2500.0:
        return False, 0.0
    spd = vlen(vel)
    if not (25.0 < spd < 4500.0):
        return False, 0.0
    if sum(1 for x in vel if abs(x) > 0.05) < 2:
        return False, 0.0
    return True, spd

def calculate_mach(speed_ms, alt_m):
    """คำนวณ Mach number ตามโมเดลบรรยากาศมาตรฐาน (ISA)"""
    T = max(216.65, 288.15 - 0.0065 * max(0.0, alt_m))
    sos = math.sqrt(1.4 * 287.05 * T)
    return speed_ms / sos if sos > 0 else 0.0

def calculate_heading_pitch(vel):
    """คำนวณมุมหัวเรือ (Heading 0-360) และมุมยก (Pitch -90 ถึง +90)"""
    vx, vy, vz = vel
    spd = vlen(vel)
    if spd < 1e-2:
        return 0.0, 0.0
    heading = (math.degrees(math.atan2(vx, vz)) + 360.0) % 360.0
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, vy / spd))))
    return round(heading, 1), round(pitch, 1)

def classify_seeker_type(wep_name):
    """ระบุชนิดหัวค้นหาเป้าหมายจากชื่ออาวุธ"""
    w = wep_name.lower()
    if any(k in w for k in ("aim_7", "r_27r", "r_27er", "r_23r", "r_24r", "super_530", "aspide", "skyflash")):
        return "SARH (Radar Semi-Active)"
    if any(k in w for k in ("aim_120", "r_77", "mica", "aam_4", "pl_12", "derby", "phoenix", "aim_54")):
        return "ARH (Active Radar)"
    if any(k in w for k in ("aim_9", "r_60", "r_73", "magic", "pl_5", "pl_7", "sraam", "strela", "mistral", "ty_90", "stinger", "igla")):
        return "IR (Heat-Seeking)"
    if any(k in w for k in ("roland", "adats", "9m311", "vt_1", "starstreak", "hellfire", "vikhr")):
        return "SACLOS / Beam-Rider"
    if any(k in w for k in ("agm_65", "kh_29", "pars", "spike")):
        return "Optical / TV / IIR"
    return "Guided Missile"


# ====================================================================
# Core Rocket Struct Parser
# ====================================================================
def check_ptr_is_rocket(sc, ptr):
    """ตรวจสอบความถูกต้องของ struct ขีปนาวุธ พร้อมดึงข้อมูล Telemetry ครบถ้วน"""
    try:
        header = sc.read_mem(ptr, 0x750)
        if not header or len(header) < 0x2c0:
            return None

        # 1. ค้นหาชื่อ Blk อาวุธ
        found_wep = ""
        for off in [0x700, 0x6c8, 0x690, 0x6a0, 0x620]:
            if len(header) >= off + 8:
                prp = struct.unpack_from("<Q", header, off)[0]
                if is_valid_ptr(prp):
                    for poff in (0x28, 0x50, 0x58):
                        raw_np = sc.read_mem(prp + poff, 8)
                        if raw_np and len(raw_np) == 8:
                            np = struct.unpack("<Q", raw_np)[0]
                            if is_valid_ptr(np):
                                s = sc.read_mem(np, 64)
                                if s:
                                    raw_str = s.split(b"\x00")[0].decode("utf-8", errors="ignore").strip()
                                    if any(ign in raw_str.lower() for ign in COUNTERMEASURE_KEYWORDS):
                                        return None
                                    if raw_str and (".blk" in raw_str.lower() or any(k in raw_str.lower() for k in ("missile", "rocket", "aim", "sam", "agm", "r_", "aam"))):
                                        found_wep = raw_str.split("/")[-1].split("\\")[-1]
                                        break
                    if found_wep:
                        break

        if not found_wep:
            for off in (0x420, 0x440):
                if len(header) >= off + 8:
                    comp_p = struct.unpack_from("<Q", header, off)[0]
                    if is_valid_ptr(comp_p):
                        s = sc.read_mem(comp_p + 0x08, 48)
                        if s:
                            raw_str = s.split(b"\x00")[0].split(b"*")[0].decode("utf-8", errors="ignore").strip()
                            if any(ign in raw_str.lower() for ign in COUNTERMEASURE_KEYWORDS):
                                return None
                            if any(k in s for k in (b"missile", b"rocket", b"sam", b"aim", b"agm", b"r_")):
                                if raw_str:
                                    found_wep = raw_str + ".blk"
                                    break

        if not found_wep:
            for off in [0x230, 0x240, 0x380]:
                if len(header) >= off + 40:
                    s = header[off:off+40]
                    if b"aim_" in s or b"rocket" in s or b"missile" in s or b".blk" in s:
                        found_wep = s.split(b"\x00")[0].decode("utf-8", errors="ignore")
                        break

        # 2. ตรวจสอบพิกัดและความเร็ว
        for set_name, pos_off, vel_off, own_off, st_off, guid_off, eid_off, props_off in OFFSET_SETS:
            if len(header) < pos_off + 12 or len(header) < vel_off + 12:
                continue
            pos = struct.unpack_from("<fff", header, pos_off)
            vel = struct.unpack_from("<fff", header, vel_off)

            is_ok, speed = is_valid_missile_motion(pos, vel)
            if not is_ok:
                continue

            phase = struct.unpack_from("<I", header, getattr(mul, 'OFF_RKT_PHASE', 0x498))[0] if len(header) >= 0x498 + 4 else 0
            detonated = struct.unpack_from("<I", header, getattr(mul, 'OFF_RKT_DETONATED', 0x420))[0] if len(header) >= 0x420 + 4 else 0
            if phase == 6 or detonated != 0:
                continue

            owner = struct.unpack_from("<Q", header, own_off)[0] if len(header) >= own_off + 8 else 0
            if not owner and len(header) >= 0x48:
                owner = struct.unpack_from("<Q", header, 0x40)[0]
            state = header[st_off] if len(header) > st_off else 0
            guid  = struct.unpack_from("<Q", header, guid_off)[0] if len(header) >= guid_off + 8 else 0
            if not guid and len(header) >= 0x640:
                guid = struct.unpack_from("<Q", header, 0x638)[0]
            eid   = struct.unpack_from("<I", header, eid_off)[0] if len(header) >= eid_off + 4 else 0
            if not eid and len(header) >= 0x34:
                eid = struct.unpack_from("<I", header, 0x30)[0]

            if state > 32 or eid == 0 or eid > 50_000_000:
                continue

            owner_unit = (owner & ~1) if owner else 0
            if owner_unit != 0 and not (is_valid_ptr(owner_unit) and (owner_unit & 0x7 == 0)):
                owner = 0
                owner_unit = 0

            if guid != 0 and not (is_valid_ptr(guid) and (guid & 0x7 == 0)):
                guid = 0

            if not found_wep:
                if is_valid_ptr(guid):
                    found_wep = "sam_missile.blk"
                elif speed > 250.0:
                    found_wep = "missile.blk"
                else:
                    continue

            alive = header[getattr(mul, 'OFF_RKT_ALIVE', 0x6c0)] if len(header) > 0x6c0 else 0

            # Guidance internals
            g_locked = 0
            g_tracking = 0
            g_target = -1
            is_guided = False
            if is_valid_ptr(guid):
                g_locked = r8(sc, guid + getattr(mul, 'OFF_GUID_LOCKED', 0x4C))
                g_tracking = r8(sc, guid + getattr(mul, 'OFF_GUID_TRACKING', 0x4D))
                g_tgt_raw = sc.read_mem(guid + getattr(mul, 'OFF_GUID_TARGET_ID', 0x84), 2)
                g_target = struct.unpack("<H", g_tgt_raw)[0] if g_tgt_raw and len(g_tgt_raw) == 2 else 0
                if g_target == 0xFFFF:
                    g_target = 0
                if g_locked not in (0, 1):
                    g_locked = r8(sc, guid + 0x50)
                if g_tracking not in (0, 1):
                    g_tracking = r8(sc, guid + 0x51)
                if g_target <= 0:
                    alt_tgt = sc.read_mem(guid + 0x8C, 2)
                    if alt_tgt and len(alt_tgt) == 2:
                        at = struct.unpack("<H", alt_tgt)[0]
                        if 0 < at < 20000:
                            g_target = at
                is_guided = (g_locked == 1 or g_tracking == 1 or g_target > 0)

            # Hex dump of key regions
            hex_regions = {}
            for r_name, start, length in [
                ("header", 0x00, 0x60),
                ("state", 0x90, 0x10),
                ("pos_vel", 0x230, 0x40),
                ("detonated", 0x418, 0x10),
                ("phase", 0x490, 0x10),
                ("guidance", 0x630, 0x50),
            ]:
                if len(header) >= start + length:
                    hex_regions[r_name] = header[start:start+length].hex()

            content_hash = hashlib.md5(header[:0x270]).hexdigest()[:12]
            heading, pitch = calculate_heading_pitch(vel)
            mach = calculate_mach(speed, pos[1])

            return {
                "ptr": ptr,
                "set": set_name,
                "pos": [round(x, 2) for x in pos],
                "vel": [round(x, 2) for x in vel],
                "speed": round(speed, 1),
                "mach": round(mach, 2),
                "alt": round(pos[1], 1),
                "heading": heading,
                "pitch": pitch,
                "owner": owner,
                "owner_unit": owner_unit,
                "state": state,
                "eid": eid,
                "guid": guid,
                "name": found_wep,
                "seeker_type": classify_seeker_type(found_wep),
                "phase": phase,
                "detonated": detonated,
                "alive": alive,
                "g_locked": g_locked,
                "g_tracking": g_tracking,
                "g_target_id": g_target,
                "is_guided": is_guided,
                "content_hash": content_hash,
                "hex": hex_regions,
            }
    except Exception:
        pass
    return None


# ====================================================================
# Scanner Engine (256-Slot Proj List + Dynamic Verification)
# ====================================================================
def scan_projectiles_wide(sc, base, max_slots=256):
    """สแกนขีปนาวุธจาก proj_list เต็ม Window 256 slots ป้องกัน missile ตกหล่น"""
    all_rockets = []
    seen_ptrs = set()

    proj_list_off = getattr(mul, "OFF_PROJ_LIST", 0xac02ab8)
    table_ptr = rp(sc, base + proj_list_off)
    if is_valid_ptr(table_ptr):
        cnt_cap = sc.read_mem(base + proj_list_off + 8, 8)
        if cnt_cap and len(cnt_cap) == 8:
            count, cap = struct.unpack("<II", cnt_cap)
            scan_slots = min(max(cap, count, 128), max_slots)
            raw_entries = sc.read_mem(table_ptr + 0x20, scan_slots * 0x20)
            if raw_entries and len(raw_entries) >= 0x20:
                num_m = len(raw_entries) // 0x20
                for i in range(num_m):
                    chunk = raw_entries[i * 0x20 : (i + 1) * 0x20]
                    ent_ptr = struct.unpack_from("<Q", chunk, 0x10)[0]
                    if is_valid_ptr(ent_ptr) and (ent_ptr & 7 == 0) and ent_ptr not in seen_ptrs:
                        info = check_ptr_is_rocket(sc, ent_ptr)
                        if info:
                            info["layout"] = "proj_list"
                            info["slot"] = i
                            seen_ptrs.add(ent_ptr)
                            all_rockets.append(info)
    return all_rockets


# ====================================================================
# Unit & Target Resolution Helper
# ====================================================================
def refresh_unit_map(sc, base, my_unit_ptr=0, my_team=0):
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

            pos = mul.get_unit_pos(sc, u_ptr) if hasattr(mul, 'get_unit_pos') else (0.0, 0.0, 0.0)

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
# Terminal UI Dashboard
# ====================================================================
class TerminalDashboard:
    def __init__(self):
        self.last_render_t = 0.0

    def render(self, frame_num, fps, my_plane, active_missiles, total_captured):
        # Throttle render to ~10 FPS
        now = time.time()
        if now - self.last_render_t < 0.1:
            return
        self.last_render_t = now

        # Clear screen ANSI
        lines = []
        lines.append("\033[2J\033[H")
        lines.append("╔" + "═"*98 + "╗")
        lines.append(f"║ 🎯 WT GUIDED MISSILE LIVE DUMPER v3.0 {' ':35} FPS: {fps:4.1f} ║")
        lines.append(f"║ Local Plane: {my_plane:<25} Frame: {frame_num:<8} Total Tracked: {total_captured:<6} ║")
        lines.append("╠" + "═"*98 + "╣")
        lines.append("║ ID   WEAPON             SPEED     ALT     G-FORCE  SEEKER       SHOOTER ──► TARGET      STATUS    ║")
        lines.append("╟" + "─"*98 + "╢")

        if not active_missiles:
            lines.append(f"║ {'⏳ สแกนหาขีปนาวุธที่กำลังบินอยู่ในแมตช์... (0 Active)':^96} ║")
        else:
            for idx, m in enumerate(active_missiles):
                mid = f"#{idx+1}"
                wname = (m["name"][:18] if len(m["name"]) > 18 else m["name"])
                spd_str = f"{m['speed']:.0f}m/s M{m['mach']:.1f}"
                alt_str = f"{m['alt']:.0f}m"
                g_str = f"{m.get('g_force', 0.0):.1f}G"

                # Seeker badge
                if m.get("is_guided"):
                    if m.get("g_tracking"):
                        seeker_str = "\033[92m🔒TRACK\033[0m"
                    elif m.get("g_locked"):
                        seeker_str = "\033[93m👁️LOCK\033[0m"
                    else:
                        seeker_str = "🎯GUID"
                else:
                    seeker_str = "UNGU"

                # Shooter -> Target
                sh_name = m.get("shooter_name") or "Unknown"
                sh_tag = f"[{m.get('shooter_rel', '?')[:3]}]"
                tgt_name = m.get("target_name") or "None"
                tgt_tag = f"[{m.get('target_rel', '?')[:3]}]" if tgt_name != "None" else ""
                sh_tgt = f"{sh_name[:8]}{sh_tag}─►{tgt_name[:8]}{tgt_tag}"

                # Status
                if m.get("target_rel") == "YOU":
                    status_badge = "\033[91;1m🚨INCOMING!\033[0m"
                elif m.get("is_guided"):
                    status_badge = "\033[96mGUIDED\033[0m"
                else:
                    status_badge = "FLYING"

                row = f"║ {mid:<4} {wname:<18} {spd_str:<9} {alt_str:<7} {g_str:<8} {seeker_str:<12} {sh_tgt:<23} {status_badge:<9} ║"
                lines.append(row)

        lines.append("╚" + "═"*98 + "╝")
        lines.append("💡 กด Ctrl+C เมื่อจบเกม เพื่อบันทึก CSV Tracks รายลูก และสร้าง Summary รายงานสมบูรณ์แบบ")
        print("\n".join(lines), flush=True)


# ====================================================================
# Track Exporter & Summary Generator
# ====================================================================
class SessionExporter:
    def __init__(self, output_dir):
        self.dir = output_dir
        self.tracks_dir = os.path.join(output_dir, "tracks")
        os.makedirs(self.tracks_dir, exist_ok=True)
        self.events_file = open(os.path.join(output_dir, "events.jsonl"), "w")
        self.csv_writers = {}
        self.csv_files = {}

    def log_event(self, event_type, data):
        data["_event"] = event_type
        data["_time"] = time.time()
        self.events_file.write(json.dumps(data) + "\n")
        self.events_file.flush()

    def record_track_point(self, m_uid, m_data):
        """บันทึกพิกัด Telemetry ลง CSV ของลูกนั้นๆ"""
        if m_uid not in self.csv_writers:
            safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in m_data["name"])
            csv_path = os.path.join(self.tracks_dir, f"track_{m_uid}_{safe_name}.csv")
            f = open(csv_path, "w", newline="")
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "frame", "age_s", "pos_x", "pos_y", "pos_z",
                "vel_x", "vel_y", "vel_z", "speed_ms", "mach", "accel_g",
                "alt_m", "heading", "pitch", "dist_shooter_m", "dist_target_m", "dist_you_m",
                "seeker_locked", "seeker_tracking", "target_id", "target_name", "target_rel",
                "shooter_name", "shooter_rel", "state", "phase", "detonated", "slot"
            ])
            self.csv_files[m_uid] = f
            self.csv_writers[m_uid] = writer

        writer = self.csv_writers[m_uid]
        writer.writerow([
            round(m_data["t"], 3),
            m_data["frame"],
            round(m_data["age_s"], 3),
            m_data["pos"][0], m_data["pos"][1], m_data["pos"][2],
            m_data["vel"][0], m_data["vel"][1], m_data["vel"][2],
            m_data["speed"],
            m_data["mach"],
            round(m_data.get("g_force", 0.0), 2),
            m_data["alt"],
            m_data["heading"],
            m_data["pitch"],
            round(m_data.get("dist_shooter", 0.0), 1),
            round(m_data.get("dist_target", 0.0), 1),
            round(m_data.get("dist_you", 0.0), 1),
            m_data["g_locked"],
            m_data["g_tracking"],
            m_data["g_target_id"],
            m_data.get("target_name", ""),
            m_data.get("target_rel", ""),
            m_data.get("shooter_name", ""),
            m_data.get("shooter_rel", ""),
            m_data["state"],
            m_data["phase"],
            m_data["detonated"],
            m_data.get("slot", -1)
        ])

    def close(self, all_tracked_records):
        """ปิดไฟล์และสร้าง Summary Reports"""
        for f in self.csv_files.values():
            try: f.close()
            except: pass
        try: self.events_file.close()
        except: pass

        # Generate Summary Markdown & JSON
        self._write_summary(all_tracked_records)

    def _write_summary(self, all_missiles):
        summary_md_path = os.path.join(self.dir, "summary.md")
        summary_json_path = os.path.join(self.dir, "summary.json")

        summary_data = []
        for uid, tr in all_missiles.items():
            pts = tr["points"]
            if not pts: continue
            first = pts[0]
            last = pts[-1]
            speeds = [p["speed"] for p in pts]
            g_forces = [p.get("g_force", 0.0) for p in pts]
            alts = [p["alt"] for p in pts]

            rec = {
                "uid": uid,
                "name": tr["name"],
                "seeker_type": tr["seeker_type"],
                "is_guided": tr["is_guided"],
                "shooter": tr.get("shooter_name") or "Unknown",
                "shooter_relation": tr.get("shooter_rel") or "Unknown",
                "target": tr.get("target_name") or "None",
                "target_relation": tr.get("target_rel") or "None",
                "frames": len(pts),
                "duration_s": round(last["age_s"], 2),
                "speed_start_ms": speeds[0],
                "speed_peak_ms": max(speeds),
                "speed_end_ms": speeds[-1],
                "max_g_force": round(max(g_forces), 1) if g_forces else 0.0,
                "alt_min_m": min(alts),
                "alt_max_m": max(alts),
                "distance_traveled_m": round(vdist(first["pos"], last["pos"]), 1),
                "final_status": tr.get("termination_reason", "IN_FLIGHT"),
                "csv_file": f"tracks/track_{uid}_{tr['name']}.csv"
            }
            summary_data.append(rec)

        # Write JSON
        with open(summary_json_path, "w") as f:
            json.dump(summary_data, f, indent=2)

        # Write Markdown
        with open(summary_md_path, "w") as f:
            f.write("# 🎯 War Thunder Guided Missile Telemetry Summary\n\n")
            f.write(f"- **Total Missiles Tracked:** {len(summary_data)}\n")
            f.write(f"- **Guided Missiles:** {sum(1 for m in summary_data if m['is_guided'])}\n")
            f.write(f"- **Targeting YOU:** {sum(1 for m in summary_data if m['target_relation'] == 'YOU')}\n\n")

            f.write("## 📋 Missile Flight Log Table\n\n")
            f.write("| # | Weapon | Type | Shooter | Target | Dur (s) | Peak Spd | Max G | Traveled | End Reason |\n")
            f.write("|---|---|---|---|---|---|---|---|---|---|\n")
            for m in summary_data:
                guided_mark = "🎯 " if m["is_guided"] else ""
                sh = f"{m['shooter']} ({m['shooter_relation'][:3]})"
                tg = f"{m['target']} ({m['target_relation'][:3]})" if m['target'] != "None" else "-"
                f.write(f"| {m['uid']} | {guided_mark}{m['name']} | {m['seeker_type'].split()[0]} | {sh} | {tg} | {m['duration_s']}s | {m['speed_peak_ms']}m/s | {m['max_g_force']}G | {m['distance_traveled_m']}m | {m['final_status']} |\n")

            f.write("\n\n## 💡 Tips for Analysis\n")
            f.write("- ไฟล์ CSV ละเอียดแต่ละลูกถูกบันทึกอยู่ในโฟลเดอร์ `tracks/`\n")
            f.write("- นำไฟล์ CSV ไปเปิดใน Microsoft Excel, Google Sheets, หรือ Python Pandas เพื่อพล็อตกราฟ Speed Curve หรือ G-Force ได้ทันที!\n")


# ====================================================================
# Offline Analyzer Mode (`--analyze`)
# ====================================================================
def run_analyzer(target_dir=None):
    """วิเคราะห์ผลลัพธ์จากโฟลเดอร์ Dump ที่เลือกหรือโฟลเดอร์ล่าสุด"""
    dumps_base = os.path.join(PROJECT_ROOT, "logs", "missile_dumps")
    if not target_dir:
        # Pick latest session
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

    summary_json = os.path.join(target_dir, "summary.json")
    if not os.path.exists(summary_json):
        print(f"❌ ไม่พบ {summary_json} ใน {target_dir}!")
        return

    with open(summary_json) as f:
        data = json.load(f)

    print(f"\n📊 [ANALYZER] Session Report: {os.path.basename(target_dir)}")
    print("=" * 80)
    print(f"🎯 Total Missiles: {len(data)} | Guided: {sum(1 for m in data if m['is_guided'])}")
    print("=" * 80)

    for m in data:
        guided_tag = "🎯 GUIDED" if m["is_guided"] else "🚀 ROCKET"
        print(f"\n[{m['uid']}] {m['name']} ({guided_tag})")
        print(f"   Shooter: {m['shooter']} [{m['shooter_relation']}]  ──►  Target: {m['target']} [{m['target_relation']}]")
        print(f"   Duration: {m['duration_s']}s ({m['frames']} frames) | Status: {m['final_status']}")
        print(f"   Speed: {m['speed_start_ms']} ➔ Peak: {m['speed_peak_ms']} ➔ End: {m['speed_end_ms']} m/s")
        print(f"   Max G-Force: {m['max_g_force']}G | Distance Traveled: {m['distance_traveled_m']}m | Alt: {m['alt_min_m']:.0f}..{m['alt_max_m']:.0f}m")
        print(f"   📁 Track CSV: {os.path.join(target_dir, m['csv_file'])}")

    print("\n" + "=" * 80)
    print(f"✅ ดูตารางสรุปเต็มได้ที่: {os.path.join(target_dir, 'summary.md')}\n")


# ====================================================================
# MAIN APPLICATION LOOP
# ====================================================================
def main():
    parser = argparse.ArgumentParser(description="War Thunder Guided Missile Live Dumper v3")
    parser.add_argument("--analyze", nargs="?", const="latest", help="เปิดโหมดวิเคราะห์ผลลัพธ์ (ระบุ path หรือเว้นว่างเพื่อดูรอบล่าสุด)")
    args = parser.parse_args()

    if args.analyze:
        target = None if args.analyze == "latest" else args.analyze
        run_analyzer(target)
        return

    print("🎯 WT Guided Missile Live Dumper & Telemetry Analyzer (v3.0)")
    print("=" * 70)

    pid = get_game_pid()
    if not pid:
        print("❌ ไม่พบ Game PID ของ War Thunder (aces)!")
        return

    base = get_game_base_address(pid)
    sc = MemoryScanner(pid)
    init_dynamic_offsets(sc, base)

    # Session directory
    session_id = time.strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(PROJECT_ROOT, "logs", "missile_dumps", session_id)
    os.makedirs(out_dir, exist_ok=True)
    exporter = SessionExporter(out_dir)

    print(f"[+] PID: {pid}, Base: {hex(base)}")
    print(f"[+] Output Session: {out_dir}/")

    # Local player & team resolution
    my_unit, my_team = mul.get_local_team(sc, base)
    unit_map = refresh_unit_map(sc, base, my_unit, my_team)
    my_plane_name = unit_map.get(my_unit, {}).get("name", "Unknown Aircraft")
    print(f"[+] Local Unit: {hex(my_unit)} | Aircraft: {my_plane_name} | Team: {my_team}")
    print("=" * 70)
    time.sleep(1.0)

    dashboard = TerminalDashboard()

    # Track management
    # tracked_missiles: uid -> {first_seen, last_seen, name, points: [pts], ...}
    tracked_missiles = {}
    next_uid = 1
    ptr_to_uid = {}
    frame_count = 0
    start_time = time.time()
    last_unit_refresh = 0.0

    try:
        while True:
            now = time.time()
            frame_count += 1

            # Refresh unit map every 2.0s
            if now - last_unit_refresh > 2.0:
                unit_map = refresh_unit_map(sc, base, my_unit, my_team)
                last_unit_refresh = now

            # Scan 256 slots
            active_list = scan_projectiles_wide(sc, base, max_slots=256)
            current_ptrs = set()

            live_dashboard_missiles = []

            for m in active_list:
                ptr = m["ptr"]
                current_ptrs.add(ptr)

                # Resolve shooter info
                owner_u = m.get("owner_unit", 0)
                sh_info = unit_map.get(owner_u, {})
                m["shooter_name"] = sh_info.get("name", "Unknown")
                m["shooter_rel"] = sh_info.get("relation", "Unknown")
                if sh_info.get("pos"):
                    m["dist_shooter"] = vdist(m["pos"], sh_info["pos"])
                else:
                    m["dist_shooter"] = 0.0

                # Resolve target info
                tgt_id = m.get("g_target_id", 0)
                tg_info = unit_map.get(tgt_id, {})
                m["target_name"] = tg_info.get("name", "None")
                m["target_rel"] = tg_info.get("relation", "None")
                if tg_info.get("pos"):
                    m["dist_target"] = vdist(m["pos"], tg_info["pos"])
                else:
                    m["dist_target"] = 0.0

                # Distance to local player
                my_info = unit_map.get(my_unit, {})
                if my_info.get("pos"):
                    m["dist_you"] = vdist(m["pos"], my_info["pos"])
                else:
                    m["dist_you"] = 0.0

                # Audio alarm if targeting local player!
                if m.get("target_rel") == "YOU" and (m.get("g_tracking") or m.get("g_locked")):
                    sys.stdout.write("\a") # terminal bell

                # Assign or reuse UID
                if ptr not in ptr_to_uid:
                    uid = next_uid
                    next_uid += 1
                    ptr_to_uid[ptr] = uid
                    tracked_missiles[uid] = {
                        "uid": uid,
                        "ptr": hex(ptr),
                        "name": m["name"],
                        "seeker_type": m["seeker_type"],
                        "is_guided": m["is_guided"],
                        "shooter_name": m["shooter_name"],
                        "shooter_rel": m["shooter_rel"],
                        "target_name": m["target_name"],
                        "target_rel": m["target_rel"],
                        "first_seen_t": now,
                        "last_seen_t": now,
                        "points": [],
                        "termination_reason": "FLYING",
                    }
                    exporter.log_event("MISSILE_SPAWN", {
                        "uid": uid,
                        "ptr": hex(ptr),
                        "name": m["name"],
                        "shooter": m["shooter_name"],
                        "target": m["target_name"],
                    })

                uid = ptr_to_uid[ptr]
                tr = tracked_missiles[uid]
                tr["last_seen_t"] = now

                # Calculate G-Force
                prev_pts = tr["points"]
                g_force = 0.0
                if prev_pts:
                    prev_p = prev_pts[-1]
                    dt = now - prev_p["t"]
                    if dt > 0.005:
                        d_vx = m["vel"][0] - prev_p["vel"][0]
                        d_vy = m["vel"][1] - prev_p["vel"][1]
                        d_vz = m["vel"][2] - prev_p["vel"][2]
                        accel = math.sqrt(d_vx**2 + d_vy**2 + d_vz**2) / dt
                        g_force = accel / 9.80665
                m["g_force"] = round(g_force, 1)

                m["age_s"] = now - tr["first_seen_t"]
                m["frame"] = frame_count
                m["t"] = now

                if m.get("target_name") not in ("None", "Unknown", None) and tr.get("target_name") in ("None", "Unknown", None):
                    tr["target_name"] = m["target_name"]
                    tr["target_rel"] = m["target_rel"]

                # Record point in history & CSV
                tr["points"].append(m)
                exporter.record_track_point(uid, m)

                live_dashboard_missiles.append(m)

            # Detect despawned missiles
            for ptr, uid in list(ptr_to_uid.items()):
                if ptr not in current_ptrs:
                    tr = tracked_missiles[uid]
                    # If not seen for 0.4s, finalize termination reason
                    if now - tr["last_seen_t"] > 0.4:
                        last_pt = tr["points"][-1] if tr["points"] else None
                        reason = "LOST / EVICTED"
                        if last_pt:
                            if last_pt.get("detonated", 0) != 0:
                                reason = "💥 DETONATED"
                            elif last_pt.get("dist_target", 999.0) < 18.0 and last_pt.get("target_name") not in ("None", "Unknown"):
                                reason = "🎯 TARGET HIT"
                            elif last_pt.get("dist_you", 999.0) < 25.0:
                                reason = "💥 PROXIMITY/HIT YOU"
                            elif last_pt.get("alt", 999.0) < 25.0:
                                reason = "⛰️ GROUND IMPACT"
                            elif last_pt["age_s"] > 25.0:
                                reason = "⏱️ TIMEOUT"
                        tr["termination_reason"] = reason

                        exporter.log_event("MISSILE_DESPAWN", {
                            "uid": uid,
                            "name": tr["name"],
                            "reason": reason,
                            "duration_s": round(now - tr["first_seen_t"], 2),
                        })
                        del ptr_to_uid[ptr]

            # Update live dashboard
            elapsed = max(0.1, now - start_time)
            fps = frame_count / elapsed
            dashboard.render(frame_count, fps, my_plane_name, live_dashboard_missiles, len(tracked_missiles))

            time.sleep(0.06)  # ~16 FPS sampling rate

    except KeyboardInterrupt:
        print("\n\n" + "="*70)
        print("💾 กำลังบันทึก CSV Tracks รายลูก และสรุปผลรายงาน...")
        exporter.close(tracked_missiles)
        print(f"✅ บันทึกเสร็จสมบูรณ์!")
        print(f"📂 โฟลเดอร์ผลลัพธ์: {out_dir}/")
        print(f"   - 📄 summary.md (ตารางสรุปผล)")
        print(f"   - 📊 tracks/*.csv (ไฟล์วิถีและความเร็วรายลูก สำหรับเปิดใน Excel/Plotly)")
        print(f"   - 📜 events.jsonl (Event logs ทั้งหมด)")
        print("="*70)
        print(f"💡 วิเคราะห์รอบนี้ซ้ำเมื่อไรก็ได้ด้วยคำสั่ง:\n   python3 tools/sub/missile/missile_guided_live_dumper.py --analyze {out_dir}\n")


if __name__ == "__main__":
    main()
