#!/usr/bin/env python3
"""
🚀 Real-Time SPAA & Bot Missile Hunter (Completely Unfiltered)
======================================================================
ค้นหาขีปนาวุธของบอท SPAA และจรวดทุกประเภทในหน่วยความจำสด
1. ปลดล็อคตัวกรองทั้งหมด (Unfiltered 100%)
2. สแกนทุก Entry ใน node_table (0..1000)
3. ค้นหาชื่อ .blk และ string ขีปนาวุธทุกชนิดใน struct
4. แสดงข้อมูลดิบ (Hex dump, Offsets, Velocity, Position, Owner, State, Phase, Detonated)
5. ทำงานแบบ Real-Time Loop รอการยิงอย่างต่อเนื่อง (กด CTRL+C เพื่อหยุด)
"""

import sys
import os
import struct
import math
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address
import src.utils.mul as mul

OFF_ECS_MANAGER    = getattr(mul, 'OFF_ECS_MANAGER', 0xb0e29b8)
OFF_ECS_NODE_TABLE = getattr(mul, 'OFF_ECS_NODE_TABLE', 0x178)
OFF_ECS_CLASS_TABLE= getattr(mul, 'OFF_ECS_CLASS_TABLE', 0x5E8)
OFF_PROJ_LIST      = getattr(mul, 'OFF_PROJ_LIST', 0xac02ab8)

def rp(sc, a):
    d = sc.read_mem(a, 8)
    return struct.unpack("<Q", d)[0] if d and len(d) >= 8 else 0

def r32(sc, a):
    d = sc.read_mem(a, 4)
    return struct.unpack("<I", d)[0] if d and len(d) >= 4 else 0

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

def scan_hunter(sc, node_t, max_entries=1000, base=0):
    candidates = []
    seen = set()

    # 1. Projectile list check (if base provided)
    if base:
        proj_list_off = getattr(mul, "OFF_PROJ_LIST", 0xac02ab8)
        table_ptr = rp(sc, base + proj_list_off)
        if is_valid_ptr(table_ptr):
            cnt_cap = sc.read_mem(base + proj_list_off + 8, 8)
            if cnt_cap and len(cnt_cap) == 8:
                count, cap = struct.unpack("<II", cnt_cap)
                if 0 < count <= 2000 and cap <= 65536:
                    raw_entries = sc.read_mem(table_ptr + 0x20, count * 0x20)
                    if raw_entries and len(raw_entries) >= 0x20:
                        num_m = min(count, len(raw_entries) // 0x20)
                        for idx in range(num_m):
                            chunk = raw_entries[idx * 0x20 : (idx + 1) * 0x20]
                            ent_ptr = struct.unpack_from("<Q", chunk, 0x10)[0]
                            if is_valid_ptr(ent_ptr) and (ent_ptr & 7 == 0) and ent_ptr not in seen:
                                buf = sc.read_mem(ent_ptr, 0x750)
                                if buf and len(buf) >= 0x2c0:
                                    # Process entity buffer
                                    cand = _parse_hunter_candidate(sc, ent_ptr, buf, -1, idx, "proj_list")
                                    if cand:
                                        seen.add(ent_ptr)
                                        candidates.append(cand)
    
    # 2. ECS Node table check
    if node_t and is_valid_ptr(node_t):
        table_bytes = sc.read_mem(node_t, max_entries * 0x20)
        if table_bytes and len(table_bytes) >= 0x20:
            num_entries = len(table_bytes) // 0x20
            for i in range(num_entries):
                data = table_bytes[i * 0x20 : (i + 1) * 0x20]
                if all(b == 0 for b in data):
                    continue
                
                storage = struct.unpack_from("<Q", data, 0)[0]
                if not is_valid_ptr(storage):
                    continue
                
                count = struct.unpack_from("<I", data, 8)[0]
                if count == 0:
                    continue
                
                read_n = min(max(count, 32), 300)
                bulk = sc.read_mem(storage, read_n * 8)
                if not bulk:
                    continue
                
                for idx in range(len(bulk) // 8):
                    ptr = struct.unpack_from("<Q", bulk, idx * 8)[0]
                    if not is_valid_ptr(ptr) or (ptr & 7 != 0) or ptr in seen:
                        continue
                    
                    buf = sc.read_mem(ptr, 0x750)
                    if not buf or len(buf) < 0x2c0:
                        continue
                    
                    cand = _parse_hunter_candidate(sc, ptr, buf, i, idx, "node_table")
                    if cand:
                        seen.add(ptr)
                        candidates.append(cand)

    return candidates
            
def _parse_hunter_candidate(sc, ptr, buf, entry_idx, slot_idx, layout_name):
    # 1. Search for .blk or weapon strings in this struct
    found_name = ""
    name_offset = None
    props_ptr = 0
    
    # Check primary props pointers (0x700, 0x6c8)
    for off in (getattr(mul, 'OFF_RKT_PROPS', 0x700), 0x6c8, 0x690, 0x6a0):
        if len(buf) >= off + 8:
            p = struct.unpack_from("<Q", buf, off)[0]
            if is_valid_ptr(p):
                for poff in (0x28, 0x50, 0x58):
                    n_ptr = rp(sc, p + poff)
                    if is_valid_ptr(n_ptr):
                        s = rstr(sc, n_ptr, 64)
                        if ".blk" in s.lower() or any(k in s.lower() for k in ("missile", "rocket", "aim", "sam", "agm", "r_", "aam")):
                            found_name = s.split("/")[-1].split("\\")[-1]
                            name_offset = f"props@{hex(off)}+{hex(poff)}"
                            props_ptr = p
                            break
            if found_name:
                break
    
    # 2. Check position & velocity
    pos_23c = struct.unpack_from("<fff", buf, getattr(mul, 'OFF_RKT_POS', 0x23c))
    vel_258 = struct.unpack_from("<fff", buf, getattr(mul, 'OFF_RKT_VEL', 0x258))
    spd_258 = vlen(vel_258) if all(math.isfinite(x) for x in vel_258) else 0.0

    is_missile = False
    best_pos = pos_23c
    best_vel = vel_258
    best_spd = spd_258
    best_set = "0x23c"

    if found_name:
        is_missile = True
    elif (spd_258 > 15.0 and spd_258 < 5000.0 and sum(1 for x in pos_23c if abs(x) > 5.0) >= 2):
        is_missile = True

    if is_missile:
        owner = struct.unpack_from("<Q", buf, getattr(mul, 'OFF_RKT_OWNER', 0x50))[0] if len(buf) >= 0x58 else 0
        if not owner and len(buf) >= 0x48:
            owner = struct.unpack_from("<Q", buf, 0x40)[0]
        state = buf[getattr(mul, 'OFF_RKT_STATE', 0x94)] if len(buf) > 0x94 else 0
        eid = struct.unpack_from("<I", buf, getattr(mul, 'OFF_RKT_ENTITY_ID', 0x40))[0] if len(buf) >= 0x44 else 0
        if not eid and len(buf) >= 0x34:
            eid = struct.unpack_from("<I", buf, 0x30)[0]
        phase = struct.unpack_from("<I", buf, getattr(mul, 'OFF_RKT_PHASE', 0x498))[0] if len(buf) >= 0x49c else 0
        detonated = struct.unpack_from("<I", buf, getattr(mul, 'OFF_RKT_DETONATED', 0x420))[0] if len(buf) >= 0x424 else 0
        guid = struct.unpack_from("<Q", buf, getattr(mul, 'OFF_RKT_GUIDANCE', 0x670))[0] if len(buf) >= 0x678 else 0
        if not guid and len(buf) >= 0x640:
            guid = struct.unpack_from("<Q", buf, 0x638)[0]
        
        return {
            "entry": entry_idx,
            "idx": slot_idx,
            "ptr": ptr,
            "name": found_name,
            "name_off": name_offset,
            "pos": best_pos,
            "vel": best_vel,
            "speed": best_spd,
            "offset_set": best_set,
            "owner": owner,
            "state": state,
            "eid": eid,
            "phase": phase,
            "detonated": detonated,
            "guid": guid,
            "props": props_ptr,
        }
    return None

def main():
    print("🎯 SPAA Bot & Missile Real-Time Hunter (Unfiltered)")
    print("=" * 70)
    pid = get_game_pid()
    if not pid:
        print("❌ ไม่พบ PID ของ aces!")
        return
    
    base = get_game_base_address(pid)
    sc = MemoryScanner(pid)
    
    ecs_mgr_off = getattr(mul, 'OFF_ECS_MANAGER', 0xb0e29b8)
    ecs_mgr = rp(sc, base + ecs_mgr_off)
    if not is_valid_ptr(ecs_mgr):
        for alt_off in (0xb0e2b98, 0xb0e29b8, 0x8225aa0):
            test_m = rp(sc, base + alt_off)
            if is_valid_ptr(test_m) and is_valid_ptr(rp(sc, test_m + getattr(mul, 'OFF_ECS_NODE_TABLE', 0x178))):
                ecs_mgr = test_m
                ecs_mgr_off = alt_off
                break
    
    node_t = rp(sc, ecs_mgr + getattr(mul, 'OFF_ECS_NODE_TABLE', 0x178)) if is_valid_ptr(ecs_mgr) else 0
    
    print(f"[+] PID: {pid}, Base: {hex(base)}")
    print(f"[+] ECS Manager: {hex(ecs_mgr)}, node_table: {hex(node_t)}")
    print("=" * 70)
    print("📡 Watching for missiles/SPAA launches in real time (CTRL+C to stop)...")
    print("   ยิงหรือให้บอท SPAA ยิง missile ตอนนี้ได้เลย!")
    print("=" * 70)
    
    try:
        while True:
            t0 = time.time()
            results = scan_hunter(sc, node_t, 1000, base=base)
            elapsed_ms = (time.time() - t0) * 1000
            
            if results:
                print(f"\n\n🚨 [{time.strftime('%H:%M:%S')}] FOUND {len(results)} CANDIDATES ({elapsed_ms:.1f}ms):")
                print("-" * 70)
                for idx, r in enumerate(results):
                    name_str = f'"{r["name"]}" ({r["name_off"]})' if r["name"] else "[NO .BLK NAME FOUND]"
                    guid_info = f"{hex(r['guid'])}"
                    if is_valid_ptr(r['guid']):
                        glock = sc.read_mem(r['guid'] + getattr(mul, 'OFF_GUID_LOCKED', 0x4C), 1)[0] if sc.read_mem(r['guid'] + getattr(mul, 'OFF_GUID_LOCKED', 0x4C), 1) else 0
                        gtrk = sc.read_mem(r['guid'] + getattr(mul, 'OFF_GUID_TRACKING', 0x4D), 1)[0] if sc.read_mem(r['guid'] + getattr(mul, 'OFF_GUID_TRACKING', 0x4D), 1) else 0
                        gtgt_raw = sc.read_mem(r['guid'] + getattr(mul, 'OFF_GUID_TARGET_ID', 0x84), 2)
                        gtgt = struct.unpack("<h", gtgt_raw)[0] if gtgt_raw else -1
                        guid_info += f" (lock={glock}, trk={gtrk}, tgt_id={gtgt})"
                    
                    print(f"  🚀 #{idx} entry={r['entry']} set={r['offset_set']} ptr={hex(r['ptr'])}")
                    print(f"     Name:      {name_str}")
                    print(f"     Pos:       ({r['pos'][0]:.1f}, {r['pos'][1]:.1f}, {r['pos'][2]:.1f})")
                    print(f"     Vel:       ({r['vel'][0]:.1f}, {r['vel'][1]:.1f}, {r['vel'][2]:.1f}) -> Speed: {r['speed']:.1f} m/s")
                    print(f"     Owner:     {hex(r['owner'])} | State: {r['state']} | EID: {r['eid']}")
                    print(f"     Phase:     {r['phase']} | Detonated: {hex(r['detonated'])}")
                    print(f"     Guidance:  {guid_info}")
            else:
                print(f"\r  ⏳ Watching live memory (0..1000 in {elapsed_ms:.1f}ms)... [0 active]   ", end="", flush=True)
            
            time.sleep(0.08)
    except KeyboardInterrupt:
        print("\n\n👋 Stopped hunter.")

if __name__ == "__main__":
    main()
