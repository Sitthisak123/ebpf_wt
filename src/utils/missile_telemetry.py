#!/usr/bin/env python3
"""
🚀 WT Missile Telemetry Core & ESP Bridge (v4.0)
======================================================================
ระบบดักจับ, เชื่อมต่อ (Bind) กับ ESP Overlay และบันทึกข้อมูล Telemetry:
1. RawECSScanner: สแกน Entity ขีปนาวุธทุกตัวใน ECS Node Table (0..500) และ Proj List (1024 slots)
   แบบ 100% Unfiltered ไม่ตัดตัวกรองทิ้ง เพื่อดึงข้อมูลดิบทั้งหมด
2. Diagnostic Filter Evaluator: ประเมินว่า Entity แต่ละตัวผ่านเกณฑ์ของ ESP หรือไม่ พร้อมระบุ reject_reason ชัดเจน
3. MissileTelemetryBridge: IPC ความเร็วสูงผ่าน /dev/shm ส่งต่อสถานะสดระหว่าง ESP Overlay กับ Dumper
4. TelemetrySessionRecorder: บันทึกข้อมูลลง SQLite (telemetry.db), JSONL, CSV Trajectories, และ Summary Markdown
"""

import sys
import os
import time
import math
import struct
import json
import sqlite3
import hashlib
import csv
import threading
import queue
from typing import Dict, List, Any, Optional, Tuple

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import src.utils.mul as mul

# Shared IPC Path in RAM (/dev/shm is lightning fast < 0.02ms)
SHM_DIR = "/dev/shm" if os.path.exists("/dev/shm") and os.access("/dev/shm", os.W_OK) else os.path.join(PROJECT_ROOT, "dumps")
SHM_FILE_PATH = os.path.join(SHM_DIR, "ebpf_wt_missile_telemetry.json")
SHM_TEMP_PATH = os.path.join(SHM_DIR, ".ebpf_wt_missile_telemetry.tmp")

COUNTERMEASURE_KEYWORDS = (
    "flare", "chaff", "countermeasure", "decoy", "dispenser",
    "cm_", "cartridge", "split_launcher", "bullet_flare",
    "flares", "bol_pod", "anti_radar", "infrared_decoy",
)


def _rp(sc, a: int) -> int:
    d = sc.read_mem(a, 8)
    return struct.unpack("<Q", d)[0] if d and len(d) >= 8 else 0


def _rstr(sc, a: int, n: int = 80) -> str:
    d = sc.read_mem(a, n)
    if not d:
        return ""
    try:
        end = d.index(0)
        return d[:end].decode("utf-8", errors="replace")
    except ValueError:
        return d[:n].decode("utf-8", errors="replace")


def _vlen(v) -> float:
    return math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])


def calculate_mach(speed_ms: float, alt_m: float) -> float:
    """คำนวณ Mach number ตามโมเดลบรรยากาศมาตรฐาน (ISA)"""
    T = max(216.65, 288.15 - 0.0065 * max(0.0, alt_m))
    sos = math.sqrt(1.4 * 287.05 * T)
    return speed_ms / sos if sos > 0 else 0.0


def calculate_heading_pitch(vel: Tuple[float, float, float]) -> Tuple[float, float]:
    """คำนวณมุมหัวเรือ (Heading 0-360) และมุมยก (Pitch -90 ถึง +90)"""
    vx, vy, vz = vel
    spd = _vlen(vel)
    if spd < 1e-2:
        return 0.0, 0.0
    heading = (math.degrees(math.atan2(vx, vz)) + 360.0) % 360.0
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, vy / spd))))
    return round(heading, 1), round(pitch, 1)


def classify_seeker_type(wep_name: str) -> str:
    """ระบุชนิดหัวค้นหาเป้าหมายจากชื่ออาวุธ"""
    w = (wep_name or "").lower()
    if any(k in w for k in ("aim_7", "r_27r", "r_27er", "r_23r", "r_24r", "super_530", "aspide", "skyflash")):
        return "SARH (Radar Semi-Active)"
    if any(k in w for k in ("aim_120", "r_77", "mica", "aam_4", "pl_12", "derby", "phoenix", "aim_54")):
        return "ARH (Active Radar)"
    if any(k in w for k in ("aim_9", "r_60", "r_73", "magic", "pl_5", "pl_7", "sraam", "strela", "mistral", "ty_90", "stinger", "igla", "9m39", "9m38")):
        return "IR (Heat-Seeking)"
    if any(k in w for k in ("roland", "adats", "9m311", "vt_1", "vt1", "starstreak", "hellfire", "vikhr", "mim146", "mim-146", "pantsir", "tor", "9m331")):
        return "SACLOS / Beam-Rider"
    if any(k in w for k in ("agm_65", "kh_29", "pars", "spike", "q-5")):
        return "Optical / TV / IIR"
    return "Guided Missile"


# ====================================================================
# 1. Raw ECS Scanner (100% Completely Unfiltered)
# ====================================================================
class RawECSScanner:
    """
    สแกนหน่วยความจำสดทั้ง ECS Node Table และ Projectile List แบบ 100% Unfiltered
    เก็บ Entity ดิบทุกตัวโดยไม่ตัดทิ้ง แม้จะยังไม่ติดเครื่องยนต์ หรือเป็น Flare/Chaff
    พร้อมวิเคราะห์หาเหตุผล (Diagnostic Verdict) ว่าทำไม ESP ถึงรับหรือไม่รับ Entity นั้น
    """

    def __init__(self):
        self._props_cache: Dict[int, str] = {}

    def scan_all_raw_entities(self, sc, base: int, max_entries: int = 500) -> List[Dict[str, Any]]:
        raw_candidates = []
        seen_ptrs = set()

        # 1. Scan Proj List (up to 1024 slots)
        proj_list_off = getattr(mul, "OFF_PROJ_LIST", 0xac02ab8)
        table_ptr = _rp(sc, base + proj_list_off)
        if mul.is_valid_ptr(table_ptr):
            cnt_cap = sc.read_mem(base + proj_list_off + 8, 8)
            if cnt_cap and len(cnt_cap) == 8:
                count, cap = struct.unpack("<II", cnt_cap)
                scan_slots = min(max(cap, count, 128), 1024)
                raw_entries = sc.read_mem(table_ptr + 0x20, scan_slots * 0x20)
                if raw_entries and len(raw_entries) >= 0x20:
                    num_m = len(raw_entries) // 0x20
                    for slot_i in range(num_m):
                        chunk = raw_entries[slot_i * 0x20 : (slot_i + 1) * 0x20]
                        ent_ptr = struct.unpack_from("<Q", chunk, 0x10)[0]
                        if mul.is_valid_ptr(ent_ptr) and (ent_ptr & 7 == 0) and ent_ptr not in seen_ptrs:
                            item = self._parse_unfiltered_struct(sc, ent_ptr, f"proj_list[{slot_i}]", slot_i)
                            if item:
                                seen_ptrs.add(ent_ptr)
                                raw_candidates.append(item)

        # 2. Scan ECS Node Table (entries 0..max_entries)
        ecs_mgr_off = getattr(mul, "OFF_ECS_MANAGER", 0x8ccd918)
        ecs_node_off = getattr(mul, "OFF_ECS_NODE_TABLE", 0x178)
        mgr = _rp(sc, base + ecs_mgr_off)
        node_t = _rp(sc, mgr + ecs_node_off) if mul.is_valid_ptr(mgr) else 0

        if not mul.is_valid_ptr(node_t):
            for cand_off in (0x8ccd918, 0xb0e29b8, 0xb0e2b98, 0x8225aa0, 0x8226ba0):
                test_m = _rp(sc, base + cand_off)
                if mul.is_valid_ptr(test_m):
                    test_node = _rp(sc, test_m + ecs_node_off)
                    if mul.is_valid_ptr(test_node):
                        mgr = test_m
                        node_t = test_node
                        break

        if mul.is_valid_ptr(mgr) and mul.is_valid_ptr(node_t):
            table_bytes = sc.read_mem(node_t, max_entries * 0x20)
            if table_bytes and len(table_bytes) >= 0x20:
                num_entries = len(table_bytes) // 0x20
                for entry_idx in range(num_entries):
                    data = table_bytes[entry_idx * 0x20 : (entry_idx + 1) * 0x20]
                    if all(b == 0 for b in data):
                        continue
                    storage = struct.unpack_from("<Q", data, 0)[0]
                    if not mul.is_valid_ptr(storage) or (storage & 7 != 0):
                        continue
                    count = struct.unpack_from("<I", data, 8)[0]
                    capacity = struct.unpack_from("<I", data, 0x14)[0]
                    if count == 0 or capacity == 0 or count > capacity or capacity > 8192:
                        continue

                    read_bytes = min(max(capacity * 64, 2048), 65536)
                    bulk = sc.read_mem(storage, read_bytes)
                    if not bulk or len(bulk) < 8:
                        continue

                    num_ptrs = len(bulk) // 8
                    for slot_idx in range(num_ptrs):
                        try:
                            ptr = struct.unpack_from("<Q", bulk, slot_idx * 8)[0]
                            if mul.is_valid_ptr(ptr) and (ptr & 7 == 0) and ptr not in seen_ptrs:
                                item = self._parse_unfiltered_struct(sc, ptr, f"node_table[{entry_idx}][{slot_idx}]", slot_idx, entry_idx)
                                if item:
                                    seen_ptrs.add(ptr)
                                    raw_candidates.append(item)
                        except Exception:
                            continue

        return raw_candidates

    def _parse_unfiltered_struct(self, sc, ptr: int, source_str: str, slot_idx: int, entry_idx: int = -1) -> Optional[Dict[str, Any]]:
        header = sc.read_mem(ptr, 0x750)
        if not header or len(header) < 0x2c0:
            return None

        # 1. Raw Position & Velocity (Pure starned layout: 0x23c, 0x258)
        pos_off = getattr(mul, 'OFF_RKT_POS', 0x23c)
        vel_off = getattr(mul, 'OFF_RKT_VEL', 0x258)
        pos = struct.unpack_from("<fff", header, pos_off) if len(header) >= pos_off + 12 else (0.0, 0.0, 0.0)
        vel = struct.unpack_from("<fff", header, vel_off) if len(header) >= vel_off + 12 else (0.0, 0.0, 0.0)
        spd = _vlen(vel) if all(math.isfinite(x) for x in vel) else 0.0

        # 2. Raw State, Phase, Detonated, Entity ID, Owner
        state_off = getattr(mul, 'OFF_RKT_STATE', 0x94)
        state = header[state_off] if len(header) > state_off else 0
        eid_off = getattr(mul, 'OFF_RKT_ENTITY_ID', 0x40)
        eid = struct.unpack_from("<I", header, eid_off)[0] if len(header) >= eid_off + 4 else 0
        if not eid and len(header) >= 0x34:
            eid = struct.unpack_from("<I", header, 0x30)[0]
        phase_off = getattr(mul, 'OFF_RKT_PHASE', 0x498)
        phase = struct.unpack_from("<I", header, phase_off)[0] if len(header) >= phase_off + 4 else 0
        det_off = getattr(mul, 'OFF_RKT_DETONATED', 0x420)
        detonated = struct.unpack_from("<I", header, det_off)[0] if len(header) >= det_off + 4 else 0

        own_off = getattr(mul, 'OFF_RKT_OWNER', 0x50)
        owner = struct.unpack_from("<Q", header, own_off)[0] if len(header) >= own_off + 8 else 0
        if not owner and len(header) >= 0x48:
            owner = struct.unpack_from("<Q", header, 0x40)[0]
        owner_unit = (owner & ~1) if owner else 0

        # 3. Raw Guidance pointer & Seeker internals
        guid = 0
        for goff in (getattr(mul, 'OFF_RKT_GUIDANCE', 0x680), 0x680, 0x670, 0x638, 0x648, 0x6C8, 0x698):
            if len(header) >= goff + 8:
                g_cand = struct.unpack_from("<Q", header, goff)[0]
                if mul.is_valid_ptr(g_cand) and (g_cand & 7 == 0):
                    guid = g_cand
                    break

        g_locked = 0
        g_tracking = 0
        g_target_id = 0
        if mul.is_valid_ptr(guid):
            l_b = sc.read_mem(guid + getattr(mul, 'OFF_GUID_LOCKED', 0x4C), 1)
            t_b = sc.read_mem(guid + getattr(mul, 'OFF_GUID_TRACKING', 0x4D), 1)
            g_locked = l_b[0] if l_b else 0
            g_tracking = t_b[0] if t_b else 0
            raw_tgt = sc.read_mem(guid + getattr(mul, 'OFF_GUID_TARGET_ID', 0x84), 2)
            if raw_tgt and len(raw_tgt) == 2:
                g_target_id = struct.unpack("<H", raw_tgt)[0]
                if g_target_id >= 20000 and g_target_id != 65280:
                    g_target_id = 0

        # 4. Raw Weapon Name String extraction
        found_wep = ""
        props_ptr = 0
        for off in (getattr(mul, 'OFF_RKT_PROPS', 0x710), 0x710, 0x700, 0x6c8, 0x690, 0x6a0):
            if len(header) >= off + 8:
                prp = struct.unpack_from("<Q", header, off)[0]
                if mul.is_valid_ptr(prp):
                    props_ptr = prp
                    if prp in self._props_cache:
                        found_wep = self._props_cache[prp]
                        break
                    for poff in (0x28, 0x10, 0x50, 0x58):
                        np = _rp(sc, prp + poff)
                        if mul.is_valid_ptr(np):
                            s = _rstr(sc, np, 64)
                            if s and (".blk" in s.lower() or any(k in s.lower() for k in ("missile", "rocket", "aim", "sam", "agm", "r_", "aam"))):
                                found_wep = s.split("/")[-1].split("\\")[-1]
                                self._props_cache[prp] = found_wep
                                break
                    if found_wep:
                        break

        if not found_wep:
            for off in (0x420, 0x440):
                if len(header) >= off + 8:
                    comp_p = struct.unpack_from("<Q", header, off)[0]
                    if mul.is_valid_ptr(comp_p):
                        s = sc.read_mem(comp_p + 0x08, 48)
                        if s and any(k in s.lower() for k in (b"missile", b"rocket", b"sam", b"aim", b"r_")):
                            raw_s = s.split(b"\x00")[0].split(b"*")[0].decode("utf-8", errors="ignore").strip()
                            if raw_s:
                                found_wep = raw_s + ".blk"
                                break

        is_cm = any(ign in (found_wep or "").lower() for ign in COUNTERMEASURE_KEYWORDS)

        # 5. Hex snippet of header (first 64 bytes)
        hex_preview = header[:64].hex()

        # 6. Diagnostic Filter Verdict (เทียบกับเกณฑ์มาตรฐานของ ESP)
        verdict, reject_reason = self._evaluate_esp_verdict(
            pos, vel, spd, state, phase, detonated, eid, found_wep, is_cm
        )

        heading, pitch = calculate_heading_pitch(vel)
        mach = calculate_mach(spd, pos[1])

        return {
            "ptr": ptr,
            "source": source_str,
            "entry_idx": entry_idx,
            "slot_idx": slot_idx,
            "name": found_wep,
            "is_countermeasure": is_cm,
            "pos": [round(x, 2) for x in pos],
            "vel": [round(x, 2) for x in vel],
            "speed": round(spd, 1),
            "mach": round(mach, 2),
            "alt": round(pos[1], 1),
            "heading": heading,
            "pitch": pitch,
            "owner": owner,
            "owner_unit": owner_unit,
            "state": state,
            "phase": phase,
            "detonated": detonated,
            "eid": eid,
            "guid": guid,
            "g_locked": g_locked,
            "g_tracking": g_tracking,
            "g_target_id": g_target_id,
            "is_guided": bool(g_locked or g_tracking or g_target_id > 0 or "sam" in (found_wep or "").lower()),
            "seeker_type": classify_seeker_type(found_wep),
            "props_ptr": props_ptr,
            "hex_preview": hex_preview,
            "esp_verdict": verdict,
            "reject_reason": reject_reason,
        }

    @staticmethod
    def _evaluate_esp_verdict(pos, vel, spd, state, phase, detonated, eid, name, is_cm) -> Tuple[str, str]:
        """ประเมินว่า Entity นี้จะผ่านตัวกรองของ ESP หรือถูกคัดทิ้งด้วยสาเหตุใด"""
        if is_cm:
            return "REJECTED", "COUNTERMEASURE_FLARE_OR_CHAFF"
        if not all(math.isfinite(x) for x in pos) or not all(math.isfinite(x) for x in vel):
            return "REJECTED", "NON_FINITE_COORDS"
        if (pos[0]*pos[0] + pos[1]*pos[1] + pos[2]*pos[2]) < 2500.0:
            return "REJECTED", "ORIGIN_ZERO_COORDS"
        if spd < 10.0:
            return "REJECTED", "SPEED_TOO_LOW_BELOW_10MS"
        if spd > 4500.0:
            return "REJECTED", "SPEED_EXCESSIVE_OVER_4500MS"
        # Note: 0x420 is flight timer/component pointer and 0x498 is component pointer.
        # Valid flight motion is already checked by speed >= 10.0 and coordinates.
        if state > 32:
            return "REJECTED", "STATE_OVER_32"
        if eid == 0 or eid > 50_000_000:
            return "REJECTED", "EID_OUT_OF_RANGE"
        if not name:
            return "REJECTED", "NO_BLK_WEAPON_NAME"

        return "ACCEPTED", "OK"


# ====================================================================
# 2. Real-Time Telemetry Bridge (Fast IPC via /dev/shm)
# ====================================================================
class MissileTelemetryBridge:
    """
    ตัวกลางเชื่อมโยงข้อมูลระหว่าง radar_overlay.py (ESP) กับ Live Dumper แบบ Real-Time
    ทำงานบนหน่วยความจำ RAM (/dev/shm) ความเร็วระดับไมโครวินาที (Zero latency impact)
    """

    def __init__(self, is_publisher: bool = False):
        self.is_publisher = is_publisher
        os.makedirs(SHM_DIR, exist_ok=True)

    def publish(self, frame_data: Dict[str, Any]) -> bool:
        """ส่งออกสถานะขีปนาวุธจาก radar_overlay.py (ESP) ไปยัง SHM (Atomic Replace)"""
        try:
            frame_data["_timestamp"] = time.time()
            data_bytes = json.dumps(frame_data).encode("utf-8")
            with open(SHM_TEMP_PATH, "wb") as f:
                f.write(data_bytes)
            os.replace(SHM_TEMP_PATH, SHM_FILE_PATH)
            return True
        except Exception:
            return False

    def read_latest(self, max_age: float = 2.0) -> Optional[Dict[str, Any]]:
        """อ่านสถานะล่าสุดที่ ESP ส่งออกมา (สำหรับ Dumper)"""
        try:
            if not os.path.exists(SHM_FILE_PATH):
                return None
            mtime = os.path.getmtime(SHM_FILE_PATH)
            now = time.time()
            if (now - mtime) > max_age:
                return None
            with open(SHM_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception:
            return None

    def is_esp_connected(self, max_age: float = 1.5) -> bool:
        """ตรวจสอบว่ามี radar_overlay.py กำลังทำงานและอัปเดตข้อมูลอยู่หรือไม่"""
        try:
            if not os.path.exists(SHM_FILE_PATH):
                return False
            return (time.time() - os.path.getmtime(SHM_FILE_PATH)) <= max_age
        except Exception:
            return False


# ====================================================================
# 3. SQLite Database & Session Recorder
# ====================================================================
class TelemetryDatabase:
    """จัดการฐานข้อมูล SQLite (telemetry.db) สำหรับเก็บข้อมูล Telemetry และ Raw ECS"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_schema()

    def _init_schema(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    start_time REAL,
                    end_time REAL,
                    game_pid INTEGER,
                    player_unit TEXT,
                    player_team INTEGER,
                    aircraft_name TEXT,
                    total_raw_entities INTEGER,
                    total_esp_missiles INTEGER,
                    summary_json TEXT
                );
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS raw_ecs_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    frame INTEGER,
                    ptr TEXT,
                    source TEXT,
                    name TEXT,
                    pos_x REAL, pos_y REAL, pos_z REAL,
                    vel_x REAL, vel_y REAL, vel_z REAL,
                    speed REAL, mach REAL, alt REAL,
                    heading REAL, pitch REAL,
                    state INTEGER, phase INTEGER, detonated INTEGER, eid INTEGER,
                    guid_ptr TEXT, g_locked INTEGER, g_tracking INTEGER, g_target_id INTEGER,
                    owner_ptr TEXT,
                    esp_verdict TEXT,
                    reject_reason TEXT
                );
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS esp_tracks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    frame INTEGER,
                    ptr TEXT,
                    name TEXT,
                    pos_x REAL, pos_y REAL, pos_z REAL,
                    speed REAL, dist REAL,
                    is_my INTEGER, is_friendly INTEGER,
                    is_guided_me INTEGER, is_sam INTEGER, is_incoming INTEGER,
                    w2s_x REAL, w2s_y REAL, on_screen INTEGER,
                    target_id INTEGER, threat_level TEXT
                );
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_ptr ON raw_ecs_samples(ptr);")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_verdict ON raw_ecs_samples(esp_verdict);")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_esp_ptr ON esp_tracks(ptr);")

    def insert_raw_samples(self, frame_num: int, timestamp: float, samples: List[Dict[str, Any]]):
        if not samples:
            return
        rows = [
            (
                timestamp, frame_num, hex(s["ptr"]), s["source"], s["name"],
                s["pos"][0], s["pos"][1], s["pos"][2],
                s["vel"][0], s["vel"][1], s["vel"][2],
                s["speed"], s["mach"], s["alt"],
                s["heading"], s["pitch"],
                s["state"], s["phase"], s["detonated"], s["eid"],
                hex(s["guid"]) if s["guid"] else "0x0",
                s["g_locked"], s["g_tracking"], s["g_target_id"],
                hex(s["owner_unit"]) if s["owner_unit"] else "0x0",
                s["esp_verdict"], s["reject_reason"]
            )
            for s in samples
        ]
        with self.conn:
            self.conn.executemany("""
                INSERT INTO raw_ecs_samples (
                    timestamp, frame, ptr, source, name,
                    pos_x, pos_y, pos_z, vel_x, vel_y, vel_z,
                    speed, mach, alt, heading, pitch,
                    state, phase, detonated, eid,
                    guid_ptr, g_locked, g_tracking, g_target_id,
                    owner_ptr, esp_verdict, reject_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, rows)

    def insert_esp_tracks(self, frame_num: int, timestamp: float, tracks: List[Dict[str, Any]]):
        if not tracks:
            return
        rows = [
            (
                timestamp, frame_num, hex(t.get("ptr", 0)), t.get("name", ""),
                t.get("pos", [0, 0, 0])[0], t.get("pos", [0, 0, 0])[1], t.get("pos", [0, 0, 0])[2],
                t.get("speed", 0.0), t.get("dist", 0.0),
                1 if t.get("is_my") else 0,
                1 if t.get("is_friendly") else 0,
                1 if t.get("is_guided_me") else 0,
                1 if t.get("is_sam") else 0,
                1 if t.get("is_incoming") else 0,
                t.get("w2s", (None, None))[0] if t.get("w2s") else None,
                t.get("w2s", (None, None))[1] if t.get("w2s") else None,
                1 if t.get("on_screen") else 0,
                t.get("target_id", 0),
                t.get("threat_level", "NORMAL")
            )
            for t in tracks
        ]
        with self.conn:
            self.conn.executemany("""
                INSERT INTO esp_tracks (
                    timestamp, frame, ptr, name,
                    pos_x, pos_y, pos_z, speed, dist,
                    is_my, is_friendly, is_guided_me, is_sam, is_incoming,
                    w2s_x, w2s_y, on_screen, target_id, threat_level
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, rows)

    def close(self):
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except Exception:
            pass
        try:
            self.conn.close()
        except Exception:
            pass


class TelemetrySessionRecorder:
    """
    บันทึก Session Telemetry แบบมัลติเธรด (Non-blocking I/O)
    บันทึกทั้ง SQLite, JSONL streams, CSV รายลูก และ Markdown summary
    """

    def __init__(self, session_id: str, output_base_dir: str = None):
        self.session_id = session_id
        dumps_root = output_base_dir or os.path.join(PROJECT_ROOT, "logs", "missile_dumps")
        self.dir = os.path.join(dumps_root, session_id)
        self.tracks_dir = os.path.join(self.dir, "tracks")
        os.makedirs(self.tracks_dir, exist_ok=True)

        self.db = TelemetryDatabase(os.path.join(self.dir, "telemetry.db"))
        self.raw_jsonl = open(os.path.join(self.dir, "raw_ecs_stream.jsonl"), "w", encoding="utf-8")
        self.esp_jsonl = open(os.path.join(self.dir, "esp_stream.jsonl"), "w", encoding="utf-8")

        self.csv_files: Dict[str, Any] = {}
        self.csv_writers: Dict[str, Any] = {}

        self.queue: queue.Queue = queue.Queue(maxsize=2000)
        self.running = True
        self.worker = threading.Thread(target=self._writer_loop, daemon=True)
        self.worker.start()

        self.total_raw_captured = 0
        self.total_esp_captured = 0
        self.tracked_entities_summary: Dict[str, Dict[str, Any]] = {}

    def log_tick(self, frame_num: int, timestamp: float, raw_ecs: List[Dict[str, Any]], esp_tracks: List[Dict[str, Any]]):
        """ส่งข้อมูลเข้ารันคิวเขียนไฟล์ (0ms impact บนเธรดหลัก)"""
        try:
            self.queue.put_nowait({
                "frame": frame_num,
                "t": timestamp,
                "raw_ecs": raw_ecs,
                "esp_tracks": esp_tracks,
            })
        except queue.Full:
            pass

    def _writer_loop(self):
        while self.running or not self.queue.empty():
            try:
                item = self.queue.get(timeout=0.1)
            except queue.Empty:
                continue

            frame_num = item["frame"]
            t = item["t"]
            raw_ecs = item["raw_ecs"]
            esp_tracks = item["esp_tracks"]

            # 1. Write SQLite
            try:
                self.db.insert_raw_samples(frame_num, t, raw_ecs)
                self.db.insert_esp_tracks(frame_num, t, esp_tracks)
            except Exception:
                pass

            # 2. Write JSONL streams
            for s in raw_ecs:
                s_copy = dict(s)
                s_copy["_frame"] = frame_num
                s_copy["_t"] = t
                self.raw_jsonl.write(json.dumps(s_copy) + "\n")
                self.total_raw_captured += 1

                # Update summary tracking
                ptr_hex = hex(s["ptr"])
                if ptr_hex not in self.tracked_entities_summary:
                    self.tracked_entities_summary[ptr_hex] = {
                        "ptr": ptr_hex,
                        "name": s["name"] or "Unknown",
                        "source": s["source"],
                        "esp_verdict": s["esp_verdict"],
                        "reject_reason": s["reject_reason"],
                        "first_seen": t,
                        "last_seen": t,
                        "peak_speed": s["speed"],
                        "frames": 1,
                        "is_guided": s["is_guided"],
                    }
                else:
                    rec = self.tracked_entities_summary[ptr_hex]
                    rec["last_seen"] = t
                    rec["frames"] += 1
                    rec["peak_speed"] = max(rec["peak_speed"], s["speed"])
                    if s["esp_verdict"] == "ACCEPTED":
                        rec["esp_verdict"] = "ACCEPTED"
                        rec["reject_reason"] = "OK"

            self.raw_jsonl.flush()

            for tr in esp_tracks:
                tr_copy = dict(tr)
                tr_copy["_frame"] = frame_num
                tr_copy["_t"] = t
                self.esp_jsonl.write(json.dumps(tr_copy) + "\n")
                self.total_esp_captured += 1

                # 3. Write CSV Tracks per missile
                ptr_hex = hex(tr.get("ptr", 0))
                self._record_csv_row(ptr_hex, tr, frame_num, t)

            self.esp_jsonl.flush()
            self.queue.task_done()

    def _record_csv_row(self, ptr_hex: str, tr: Dict[str, Any], frame_num: int, t: float):
        if ptr_hex not in self.csv_writers:
            safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in tr.get("name", "missile"))
            path = os.path.join(self.tracks_dir, f"track_{ptr_hex}_{safe_name}.csv")
            f = open(path, "w", newline="", encoding="utf-8")
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "frame", "ptr", "name",
                "pos_x", "pos_y", "pos_z", "speed", "dist",
                "is_my", "is_friendly", "is_guided_me", "is_sam", "is_incoming",
                "w2s_x", "w2s_y", "on_screen", "target_id", "threat_level"
            ])
            self.csv_files[ptr_hex] = f
            self.csv_writers[ptr_hex] = writer

        w2s = tr.get("w2s") or (None, None)
        pos = tr.get("pos", [0, 0, 0])
        self.csv_writers[ptr_hex].writerow([
            round(t, 3), frame_num, ptr_hex, tr.get("name", ""),
            pos[0], pos[1], pos[2], tr.get("speed", 0.0), round(tr.get("dist", 0.0), 1),
            1 if tr.get("is_my") else 0,
            1 if tr.get("is_friendly") else 0,
            1 if tr.get("is_guided_me") else 0,
            1 if tr.get("is_sam") else 0,
            1 if tr.get("is_incoming") else 0,
            round(w2s[0], 1) if w2s[0] is not None else "",
            round(w2s[1], 1) if w2s[1] is not None else "",
            1 if tr.get("on_screen") else 0,
            tr.get("target_id", 0),
            tr.get("threat_level", "NORMAL")
        ])

    def close(self, meta_info: Dict[str, Any] = None):
        """ปิด Session และสร้างสรุปรายงาน Markdown และ JSON"""
        self.running = False
        if self.worker.is_alive():
            self.worker.join(timeout=2.0)

        for f in self.csv_files.values():
            try:
                f.close()
            except Exception:
                pass
        try:
            self.raw_jsonl.close()
            self.esp_jsonl.close()
        except Exception:
            pass

        self._generate_summary_report(meta_info or {})
        self.db.close()

        # Fix permissions so regular user can read/analyze session files without sudo
        try:
            for root, dirs, files in os.walk(self.dir):
                for d in dirs:
                    os.chmod(os.path.join(root, d), 0o777)
                for f in files:
                    os.chmod(os.path.join(root, f), 0o666)
        except Exception:
            pass

    def _generate_summary_report(self, meta_info: Dict[str, Any]):
        summary_md_path = os.path.join(self.dir, "summary.md")
        summary_json_path = os.path.join(self.dir, "summary.json")

        summary_data = {
            "session_id": self.session_id,
            "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "meta": meta_info,
            "total_raw_captured_events": self.total_raw_captured,
            "total_esp_captured_events": self.total_esp_captured,
            "entities": list(self.tracked_entities_summary.values()),
        }

        with open(summary_json_path, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2, ensure_ascii=False)

        accepted_count = sum(1 for e in self.tracked_entities_summary.values() if e["esp_verdict"] == "ACCEPTED")
        rejected_count = sum(1 for e in self.tracked_entities_summary.values() if e["esp_verdict"] != "ACCEPTED")

        with open(summary_md_path, "w", encoding="utf-8") as f:
            f.write(f"# 🎯 War Thunder Live Missile & Raw ECS Telemetry Report\n\n")
            f.write(f"- **Session ID:** `{self.session_id}`\n")
            f.write(f"- **Recorded At:** {summary_data['recorded_at']}\n")
            f.write(f"- **Local Aircraft:** {meta_info.get('aircraft_name', 'Unknown')}\n")
            f.write(f"- **Total Raw ECS Entities Found:** {len(self.tracked_entities_summary)}\n")
            f.write(f"- **ESP Accepted (Drawn on Screen):** {accepted_count}\n")
            f.write(f"- **ESP Filtered Out (Rejected):** {rejected_count}\n\n")

            f.write("## 📋 Raw ECS Candidates vs ESP Detection Verdict\n\n")
            f.write("| Entity Pointer | Source | Weapon Name | Peak Speed | Guided | ESP Verdict | Diagnosis / Reject Reason |\n")
            f.write("|---|---|---|---|---|---|---|\n")

            for e in self.tracked_entities_summary.values():
                verdict_badge = "✅ ACCEPTED" if e["esp_verdict"] == "ACCEPTED" else f"🚫 {e['esp_verdict']}"
                guided_mark = "🎯 Yes" if e["is_guided"] else "No"
                f.write(f"| `{e['ptr']}` | {e['source']} | `{e['name']}` | {e['peak_speed']:.1f} m/s | {guided_mark} | {verdict_badge} | `{e['reject_reason']}` |\n")

            f.write("\n\n## 🗄️ Database & CSV Files Reference\n")
            f.write(f"- **SQLite Database:** `{os.path.join(self.dir, 'telemetry.db')}`\n")
            f.write(f"- **Raw ECS Stream:** `{os.path.join(self.dir, 'raw_ecs_stream.jsonl')}`\n")
            f.write(f"- **ESP Track Stream:** `{os.path.join(self.dir, 'esp_stream.jsonl')}`\n")
            f.write(f"- **Per-missile CSV Tracks:** `{self.tracks_dir}/`\n")
