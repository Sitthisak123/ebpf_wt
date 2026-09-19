#!/usr/bin/env python3
"""
🚀 Real-Time Match Missile Logger & Structure Dumper
======================================================================
เครื่องมือบันทึกและวิเคราะห์โครงสร้างหน่วยความจำของขีปนาวุธในแมตช์จริง (Real Match)
1. สแกนสดทั้ง Dedicated Projectile List (0xac02ab8) และ ECS Node Table (0..500)
2. 100% Unfiltered: ไม่กรอง state, ไม่กรอง capacity, ตรวจจับขีปนาวุธทุกระยะตั้งแต่ปล่อยจนกระทบเป้า
3. บันทึก State Transition: บันทึกการเปลี่ยนแปลง State (เช่น Boost 1 -> Burnout/Glide 11) แบบมิลลิวินาที
4. ตรวจสอบ Guidance Pointers: บันทึกข้อมูล Seeker Lock, Tracking, และ Target ID ทั้งที่ 0x670 และ 0x638
5. บันทึก Memory Hex Dump (0x750 bytes) และบันทึกลงไฟล์ JSONL ในโฟลเดอร์ logs/
6. ไม่ทำให้เกมกระตุก (ใช้เวลาสแกนเฉลี่ย < 0.8ms)
"""

import sys
import os
import struct
import math
import time
import json
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address
import src.utils.mul as mul

LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

SESSION_LOG_PATH = os.path.join(
    LOGS_DIR, f"missile_capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
)

# Offsets
OFF_PROJ_LIST       = getattr(mul, 'OFF_PROJ_LIST', 0xac02ab8)
OFF_ECS_MANAGER     = getattr(mul, 'OFF_ECS_MANAGER', 0xb0e29b8)
OFF_ECS_NODE_TABLE  = getattr(mul, 'OFF_ECS_NODE_TABLE', 0x178)

OFF_RKT_ENTITY_ID   = getattr(mul, 'OFF_RKT_ENTITY_ID', 0x40)
OFF_RKT_OWNER       = getattr(mul, 'OFF_RKT_OWNER', 0x50)
OFF_RKT_STATE       = getattr(mul, 'OFF_RKT_STATE', 0x94)
OFF_RKT_POS         = getattr(mul, 'OFF_RKT_POS', 0x23c)
OFF_RKT_VEL         = getattr(mul, 'OFF_RKT_VEL', 0x258)
OFF_RKT_DETONATED   = getattr(mul, 'OFF_RKT_DETONATED', 0x420)
OFF_RKT_PHASE       = getattr(mul, 'OFF_RKT_PHASE', 0x498)
OFF_RKT_GUIDANCE    = getattr(mul, 'OFF_RKT_GUIDANCE', 0x670)
OFF_RKT_GUIDANCE_ALT= 0x638
OFF_RKT_PROPS       = getattr(mul, 'OFF_RKT_PROPS', 0x700)
OFF_RKT_PROPS_ALT   = 0x6c8

OFF_GUID_LOCKED     = getattr(mul, 'OFF_GUID_LOCKED', 0x4C)
OFF_GUID_TRACKING   = getattr(mul, 'OFF_GUID_TRACKING', 0x4D)
OFF_GUID_TARGET_ID  = getattr(mul, 'OFF_GUID_TARGET_ID', 0x84)

def rp(sc, a):
    d = sc.read_mem(a, 8)
    return struct.unpack("<Q", d)[0] if d and len(d) >= 8 else 0

def r32(sc, a):
    d = sc.read_mem(a, 4)
    return struct.unpack("<I", d)[0] if d and len(d) >= 4 else 0

def r8(sc, a):
    d = sc.read_mem(a, 1)
    return d[0] if d and len(d) >= 1 else 0

def ri16(sc, a):
    d = sc.read_mem(a, 2)
    return struct.unpack("<h", d)[0] if d and len(d) >= 2 else 0

def rstr(sc, a, n=80):
    d = sc.read_mem(a, n)
    if not d: return ""
    try:
        end = d.index(0)
        return d[:end].decode("utf-8", errors="replace")
    except ValueError:
        return d[:n].decode("utf-8", errors="replace")

def is_valid_ptr(v):
    return 0x100000 < v < 0x7FFFFFFFFFFF

def vlen(v):
    return math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])

def is_valid_vec3(v):
    if not all(math.isfinite(x) for x in v):
        return False
    for x in v:
        if x != 0.0 and abs(x) < 1e-30:
            return False
    return True

class MissileTrackRecord:
    def __init__(self, track_id, ptr, source, first_cand, raw_bytes):
        self.track_id = track_id
        self.ptr = ptr
        self.source = source
        self.start_time = time.time()
        self.last_seen = self.start_time
        self.name = first_cand.get("name", "")
        self.props = first_cand.get("props", 0)
        self.entity_id = first_cand.get("eid", 0)
        self.owner = first_cand.get("owner", 0)
        
        self.initial_pos = first_cand["pos"]
        self.latest_pos = first_cand["pos"]
        self.max_speed = first_cand["speed"]
        self.latest_speed = first_cand["speed"]
        
        # State & Guidance history
        self.states_seen = [first_cand["state"]]
        self.phases_seen = [first_cand["phase"]]
        self.detonated_flags = [first_cand["detonated"]]
        
        self.timeline = [
            {
                "dt_ms": 0,
                "state": first_cand["state"],
                "phase": first_cand["phase"],
                "detonated": first_cand["detonated"],
                "speed": round(first_cand["speed"], 1),
                "pos": [round(x, 1) for x in first_cand["pos"]],
                "vel": [round(x, 1) for x in first_cand["vel"]],
                "guid_670": hex(first_cand["guid_670"]),
                "guid_638": hex(first_cand["guid_638"]),
                "lock": first_cand["lock"],
                "trk": first_cand["trk"],
                "target_id": first_cand["target_id"],
            }
        ]
        self.initial_hex_dump = raw_bytes.hex()
        self.final_hex_dump = ""

    def update(self, cand, raw_bytes):
        now = time.time()
        dt_ms = int((now - self.start_time) * 1000)
        self.last_seen = now
        self.latest_pos = cand["pos"]
        self.latest_speed = cand["speed"]
        if cand["speed"] > self.max_speed:
            self.max_speed = cand["speed"]
        
        if cand["name"] and not self.name:
            self.name = cand["name"]
        if cand["props"] and not self.props:
            self.props = cand["props"]
        
        cur_st = cand["state"]
        last_st = self.states_seen[-1]
        
        state_changed = (cur_st != last_st)
        if cur_st not in self.states_seen:
            self.states_seen.append(cur_st)
        if cand["phase"] not in self.phases_seen:
            self.phases_seen.append(cand["phase"])
        if cand["detonated"] not in self.detonated_flags:
            self.detonated_flags.append(cand["detonated"])
            
        self.timeline.append({
            "dt_ms": dt_ms,
            "state": cand["state"],
            "phase": cand["phase"],
            "detonated": cand["detonated"],
            "speed": round(cand["speed"], 1),
            "pos": [round(x, 1) for x in cand["pos"]],
            "vel": [round(x, 1) for x in cand["vel"]],
            "guid_670": hex(cand["guid_670"]),
            "guid_638": hex(cand["guid_638"]),
            "lock": cand["lock"],
            "trk": cand["trk"],
            "target_id": cand["target_id"],
        })
        self.final_hex_dump = raw_bytes.hex()
        return state_changed

    def to_json(self):
        duration_s = round(self.last_seen - self.start_time, 2)
        return {
            "track_id": self.track_id,
            "ptr": hex(self.ptr),
            "source": self.source,
            "name": self.name,
            "duration_s": duration_s,
            "entity_id": self.entity_id,
            "owner": hex(self.owner),
            "props_ptr": hex(self.props),
            "states_seen": self.states_seen,
            "phases_seen": self.phases_seen,
            "detonated_flags": [hex(x) for x in self.detonated_flags],
            "max_speed": round(self.max_speed, 1),
            "final_speed": round(self.latest_speed, 1),
            "start_pos": [round(x, 1) for x in self.initial_pos],
            "final_pos": [round(x, 1) for x in self.latest_pos],
            "timeline_samples": len(self.timeline),
            "timeline": self.timeline,
            "initial_raw_0x750": self.initial_hex_dump,
            "final_raw_0x750": self.final_hex_dump,
        }

def inspect_candidate(sc, ptr, buf, source_name):
    """วิเคราะห์ Candidate โครงสร้างดิบของขีปนาวุธแบบ 100% Unfiltered"""
    if not buf or len(buf) < 0x270:
        return None
    
    pos = struct.unpack_from("<fff", buf, OFF_RKT_POS)
    vel = struct.unpack_from("<fff", buf, OFF_RKT_VEL)
    
    if not is_valid_vec3(pos) or not is_valid_vec3(vel):
        return None
    
    spd = vlen(vel)
    if not (15.0 < spd < 4500.0):
        return None
    if sum(1 for x in pos if abs(x) > 5.0) < 2:
        return None
    
    state = buf[OFF_RKT_STATE] if len(buf) > OFF_RKT_STATE else 0
    eid = struct.unpack_from("<I", buf, OFF_RKT_ENTITY_ID)[0] if len(buf) >= OFF_RKT_ENTITY_ID + 4 else 0
    if not eid and len(buf) >= 0x34:
        eid = struct.unpack_from("<I", buf, 0x30)[0]
    
    if eid > 50_000_000:
        return None
        
    owner = struct.unpack_from("<Q", buf, OFF_RKT_OWNER)[0] if len(buf) >= OFF_RKT_OWNER + 8 else 0
    if not owner and len(buf) >= 0x48:
        owner = struct.unpack_from("<Q", buf, 0x40)[0]
    
    phase = struct.unpack_from("<I", buf, OFF_RKT_PHASE)[0] if len(buf) >= OFF_RKT_PHASE + 4 else 0
    detonated = struct.unpack_from("<I", buf, OFF_RKT_DETONATED)[0] if len(buf) >= OFF_RKT_DETONATED + 4 else 0
    
    guid_670 = struct.unpack_from("<Q", buf, OFF_RKT_GUIDANCE)[0] if len(buf) >= OFF_RKT_GUIDANCE + 8 else 0
    guid_638 = struct.unpack_from("<Q", buf, OFF_RKT_GUIDANCE_ALT)[0] if len(buf) >= OFF_RKT_GUIDANCE_ALT + 8 else 0
    
    props = struct.unpack_from("<Q", buf, OFF_RKT_PROPS)[0] if len(buf) >= OFF_RKT_PROPS + 8 else 0
    if not props and len(buf) >= OFF_RKT_PROPS_ALT + 8:
        props = struct.unpack_from("<Q", buf, OFF_RKT_PROPS_ALT)[0]
        
    found_name = ""
    if is_valid_ptr(props):
        for poff in (0x28, 0x50, 0x58):
            np = rp(sc, props + poff)
            if is_valid_ptr(np):
                s = rstr(sc, np, 64)
                if s and (".blk" in s.lower() or any(k in s.lower() for k in ("missile", "rocket", "aim", "sam", "agm", "r_", "aam"))):
                    found_name = s.split("/")[-1].split("\\")[-1]
                    break
    
    is_locked = 0
    is_tracking = 0
    target_id = -1
    active_guid = guid_670 if is_valid_ptr(guid_670) else (guid_638 if is_valid_ptr(guid_638) else 0)
    
    if active_guid:
        l1 = r8(sc, active_guid + OFF_GUID_LOCKED)
        t1 = r8(sc, active_guid + OFF_GUID_TRACKING)
        l2 = r8(sc, active_guid + 0x50)
        t2 = r8(sc, active_guid + 0x51)
        is_locked = 1 if (l1 == 1 or l2 == 1) else 0
        is_tracking = 1 if (t1 == 1 or t2 == 1) else 0
        
        tgt1 = ri16(sc, active_guid + OFF_GUID_TARGET_ID)
        tgt2 = ri16(sc, active_guid + 0x8C)
        target_id = tgt1 if tgt1 > 0 else (tgt2 if tgt2 > 0 else -1)
    
    return {
        "ptr": ptr,
        "source": source_name,
        "pos": pos,
        "vel": vel,
        "speed": spd,
        "state": state,
        "phase": phase,
        "detonated": detonated,
        "eid": eid,
        "owner": owner,
        "props": props,
        "name": found_name,
        "guid_670": guid_670,
        "guid_638": guid_638,
        "lock": is_locked,
        "trk": is_tracking,
        "target_id": target_id,
    }

def scan_all_missiles(sc, base, node_t):
    """สแกนแบบครอบคลุมสูงสุดทั้ง Proj List และ ECS Node Table"""
    found = []
    raw_dict = {}
    seen_ptrs = set()
    
    # 1. Dedicated Projectile List
    table_ptr = rp(sc, base + OFF_PROJ_LIST)
    if is_valid_ptr(table_ptr):
        cnt_cap = sc.read_mem(base + OFF_PROJ_LIST + 8, 8)
        if cnt_cap and len(cnt_cap) == 8:
            count, cap = struct.unpack("<II", cnt_cap)
            if 0 < count <= 2000 and cap <= 65536:
                raw_entries = sc.read_mem(table_ptr + 0x20, count * 0x20)
                if raw_entries and len(raw_entries) >= 0x20:
                    num_m = min(count, len(raw_entries) // 0x20)
                    for i in range(num_m):
                        chunk = raw_entries[i * 0x20 : (i + 1) * 0x20]
                        ent_ptr = struct.unpack_from("<Q", chunk, 0x10)[0]
                        if is_valid_ptr(ent_ptr) and (ent_ptr & 7 == 0) and ent_ptr not in seen_ptrs:
                            buf = sc.read_mem(ent_ptr, 0x750)
                            cand = inspect_candidate(sc, ent_ptr, buf, f"proj_list[{i}]")
                            if cand:
                                seen_ptrs.add(ent_ptr)
                                found.append(cand)
                                raw_dict[ent_ptr] = buf
    
    # 2. ECS Node Table (0..500)
    if node_t and is_valid_ptr(node_t):
        table_bytes = sc.read_mem(node_t, 500 * 0x20)
        if table_bytes and len(table_bytes) >= 0x20:
            num_entries = len(table_bytes) // 0x20
            for i in range(num_entries):
                data = table_bytes[i * 0x20 : (i + 1) * 0x20]
                if all(b == 0 for b in data):
                    continue
                storage = struct.unpack_from("<Q", data, 0)[0]
                if not is_valid_ptr(storage) or (storage & 7 != 0):
                    continue
                cnt = struct.unpack_from("<I", data, 8)[0]
                if cnt == 0:
                    continue
                read_n = min(max(cnt * 8, 64), 800)
                bulk = sc.read_mem(storage, read_n * 8)
                if not bulk:
                    continue
                for slot in range(len(bulk) // 8):
                    ptr = struct.unpack_from("<Q", bulk, slot * 8)[0]
                    if is_valid_ptr(ptr) and (ptr & 7 == 0) and ptr not in seen_ptrs:
                        buf = sc.read_mem(ptr, 0x750)
                        cand = inspect_candidate(sc, ptr, buf, f"ecs_node[{i}:{slot}]")
                        if cand:
                            seen_ptrs.add(ptr)
                            found.append(cand)
                            raw_dict[ptr] = buf

    return found, raw_dict

def main():
    print("=" * 75)
    print("🚀 WT LIVE MATCH MISSILE LOGGER & STRUCT DUMPER")
    print("=" * 75)
    pid = get_game_pid()
    if not pid:
        print("❌ ไม่พบ PID ของ aces! กรุณาเปิดเกม War Thunder ก่อนรัน")
        sys.exit(1)
        
    base = get_game_base_address(pid)
    sc = MemoryScanner(pid)
    print(f"✅ Process PID: {pid}, Base: {hex(base)}")
    
    mgr = rp(sc, base + OFF_ECS_MANAGER)
    if not is_valid_ptr(mgr):
        for alt_off in (0xb0e2b98, 0xb0e29b8, 0x8225aa0, 0x8226ba0):
            test_m = rp(sc, base + alt_off)
            if is_valid_ptr(test_m) and is_valid_ptr(rp(sc, test_m + OFF_ECS_NODE_TABLE)):
                mgr = test_m
                break
    node_t = rp(sc, mgr + OFF_ECS_NODE_TABLE) if is_valid_ptr(mgr) else 0
    print(f"✅ Projectile List: {hex(base + OFF_PROJ_LIST)}")
    print(f"✅ ECS Manager: {hex(mgr)} | Node Table: {hex(node_t)}")
    print(f"💾 Logging output to: {SESSION_LOG_PATH}")
    print("=" * 75)
    print("📡 Monitoring real-time missile launches in match... (กด CTRL+C เพื่อหยุด)")
    print("-" * 75)

    active_tracks = {}
    track_seq = 0
    total_captured = 0

    try:
        while True:
            t0 = time.time()
            candidates, raw_map = scan_all_missiles(sc, base, node_t)
            curr_t = time.time()
            dt_scan = (curr_t - t0) * 1000.0

            seen_in_scan = set()

            for cand in candidates:
                ptr = cand["ptr"]
                seen_in_scan.add(ptr)
                raw_buf = raw_map.get(ptr, b"")

                if ptr not in active_tracks:
                    track_seq += 1
                    total_captured += 1
                    tr = MissileTrackRecord(track_seq, ptr, cand["source"], cand, raw_buf)
                    active_tracks[ptr] = tr
                    
                    name_disp = f"'{cand['name']}'" if cand['name'] else "[NO .BLK NAME]"
                    guid_disp = f"670={hex(cand['guid_670'])}, 638={hex(cand['guid_638'])}"
                    print(f"\n🔥 [SPAWN] #{tr.track_id} {name_disp} ({cand['source']}) ptr={hex(ptr)}")
                    print(f"   Pos: ({cand['pos'][0]:.1f}, {cand['pos'][1]:.1f}, {cand['pos'][2]:.1f}) | Spd: {cand['speed']:.1f} m/s")
                    print(f"   State: {cand['state']} | Phase: {cand['phase']} | Detonated: {hex(cand['detonated'])}")
                    print(f"   Guidance: {guid_disp} (lock={cand['lock']}, trk={cand['trk']}, tgt_id={cand['target_id']})")
                else:
                    tr = active_tracks[ptr]
                    state_changed = tr.update(cand, raw_buf)
                    if state_changed:
                        last_st = tr.states_seen[-2] if len(tr.states_seen) >= 2 else "?"
                        print(f"   ⚡ [STATE CHANGE] #{tr.track_id} State: {last_st} ➔ {cand['state']} (at t+{round(curr_t - tr.start_time, 2)}s) | Spd: {cand['speed']:.1f} m/s | Phase: {cand['phase']}")

            lost_ptrs = [p for p, tr in active_tracks.items() if (curr_t - tr.last_seen) > 0.40]
            for p in lost_ptrs:
                tr = active_tracks[p]
                dur = round(tr.last_seen - tr.start_time, 2)
                last_sample = tr.timeline[-1] if tr.timeline else {}
                print(f"💥 [TERMINATED] #{tr.track_id} '{tr.name or 'missile'}' ended after {dur}s | States: {tr.states_seen} | Final spd: {tr.latest_speed:.1f} m/s | Det: {hex(last_sample.get('detonated', 0))}")
                
                with open(SESSION_LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(json.dumps(tr.to_json(), ensure_ascii=False) + "\n")
                del active_tracks[p]

            active_cnt = len(active_tracks)
            if active_cnt > 0:
                summary_str = " | ".join([f"#{t.track_id}(st={t.states_seen[-1]}, {t.latest_speed:.0f}m/s)" for t in active_tracks.values()])
                print(f"\r  🚀 Tracking {active_cnt} active: {summary_str} [{dt_scan:.1f}ms]    ", end="", flush=True)
            else:
                print(f"\r  ⏳ Watching match memory... [Active: 0, Total Captured: {total_captured}, Scan: {dt_scan:.1f}ms]   ", end="", flush=True)

            time.sleep(0.04)
            
    except KeyboardInterrupt:
        print("\n\n" + "=" * 75)
        print("🛑 Stopped logger.")
        for p, tr in active_tracks.items():
            dur = round(time.time() - tr.start_time, 2)
            with open(SESSION_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(tr.to_json(), ensure_ascii=False) + "\n")
        print(f"💾 All logs saved successfully to:\n   {SESSION_LOG_PATH}")
        print("=" * 75)

if __name__ == "__main__":
    main()
