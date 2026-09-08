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

OFF_ECS_MANAGER    = 0x8225aa0
OFF_ECS_NODE_TABLE = 0x178
OFF_ECS_CLASS_TABLE= 0x5E8

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

def scan_hunter(sc, node_t, max_entries=1000):
    table_bytes = sc.read_mem(node_t, max_entries * 0x20)
    if not table_bytes or len(table_bytes) < 0x20:
        return []
    
    candidates = []
    seen = set()
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
        
        # Read storage directly (up to 300 pointers)
        read_n = min(max(count, 32), 300)
        bulk = sc.read_mem(storage, read_n * 8)
        if not bulk:
            continue
        
        for idx in range(len(bulk) // 8):
            ptr = struct.unpack_from("<Q", bulk, idx * 8)[0]
            if not is_valid_ptr(ptr) or (ptr & 7 != 0) or ptr in seen:
                continue
            
            # Read 0x750 bytes of entity memory
            buf = sc.read_mem(ptr, 0x750)
            if not buf or len(buf) < 0x300:
                continue
            
            # 1. Search for .blk or weapon strings in this struct
            found_name = ""
            name_offset = None
            props_ptr = struct.unpack_from("<Q", buf, 0x6c8)[0] if len(buf) >= 0x6d0 else 0
            if is_valid_ptr(props_ptr):
                n_ptr = rp(sc, props_ptr + 0x50)
                if is_valid_ptr(n_ptr):
                    s = rstr(sc, n_ptr, 64)
                    if ".blk" in s:
                        found_name = s
                        name_offset = "props+0x50 (0x6c8)"
            
            if not found_name:
                # Scan internal pointers
                for off in range(0x400, len(buf) - 8, 8):
                    p = struct.unpack_from("<Q", buf, off)[0]
                    if is_valid_ptr(p):
                        p_name = rp(sc, p + 0x50)
                        if is_valid_ptr(p_name):
                            s = rstr(sc, p_name, 64)
                            if ".blk" in s:
                                found_name = s
                                name_offset = f"ptr@{hex(off)}+0x50"
                                props_ptr = p
                                break
                        s2 = rstr(sc, p, 64)
                        if ".blk" in s2:
                            found_name = s2
                            name_offset = f"ptr@{hex(off)}"
                            props_ptr = p
                            break
            
            # 2. Check position & velocity at standard offset (0x23c, 0x258)
            pos_23c = struct.unpack_from("<fff", buf, 0x23c)
            vel_258 = struct.unpack_from("<fff", buf, 0x258)
            spd_258 = vlen(vel_258) if all(math.isfinite(x) for x in vel_258) else 0.0
            
            # Check alt offset (0x298, 0x2b4)
            pos_298 = struct.unpack_from("<fff", buf, 0x298)
            vel_2b4 = struct.unpack_from("<fff", buf, 0x2b4)
            spd_2b4 = vlen(vel_2b4) if all(math.isfinite(x) for x in vel_2b4) else 0.0
            
            # Is this a candidate?
            # A) Found a .blk name (regardless of speed - could be on launcher or in flight!)
            # B) Or has speed > 15 m/s with plausible map coordinates
            is_missile = False
            best_pos = pos_23c
            best_vel = vel_258
            best_spd = spd_258
            best_set = "0x23c"
            
            if found_name:
                is_missile = True
                if spd_2b4 > spd_258 and spd_2b4 > 10.0:
                    best_pos = pos_298
                    best_vel = vel_2b4
                    best_spd = spd_2b4
                    best_set = "0x298"
            elif (spd_258 > 15.0 and spd_258 < 5000.0 and sum(1 for x in pos_23c if abs(x) > 5.0) >= 2):
                is_missile = True
            elif (spd_2b4 > 15.0 and spd_2b4 < 5000.0 and sum(1 for x in pos_298 if abs(x) > 5.0) >= 2):
                is_missile = True
                best_pos = pos_298
                best_vel = vel_2b4
                best_spd = spd_2b4
                best_set = "0x298"
            
            if is_missile:
                seen.add(ptr)
                owner = struct.unpack_from("<Q", buf, 0x40)[0]
                state = buf[0x94]
                eid = struct.unpack_from("<I", buf, 0x30)[0]
                phase = struct.unpack_from("<I", buf, 0x498)[0]
                detonated = struct.unpack_from("<Q", buf, 0x420)[0]
                guid = struct.unpack_from("<Q", buf, 0x638)[0]
                
                candidates.append({
                    "entry": i,
                    "idx": idx,
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
                })
    return candidates

def main():
    print("🎯 SPAA Bot & Missile Real-Time Hunter (Unfiltered)")
    print("=" * 70)
    pid = get_game_pid()
    if not pid:
        print("❌ ไม่พบ PID ของ aces!")
        return
    
    base = get_game_base_address(pid)
    sc = MemoryScanner(pid)
    ecs_mgr = rp(sc, base + OFF_ECS_MANAGER)
    node_t = rp(sc, ecs_mgr + OFF_ECS_NODE_TABLE)
    
    print(f"[+] PID: {pid}, Base: {hex(base)}")
    print(f"[+] ECS Manager: {hex(ecs_mgr)}, node_table: {hex(node_t)}")
    print("=" * 70)
    print("📡 Watching for missiles/SPAA launches in real time (CTRL+C to stop)...")
    print("   ยิงหรือให้บอท SPAA ยิง missile ตอนนี้ได้เลย!")
    print("=" * 70)
    
    try:
        while True:
            t0 = time.time()
            results = scan_hunter(sc, node_t, 1000)
            elapsed_ms = (time.time() - t0) * 1000
            
            if results:
                print(f"\n\n🚨 [{time.strftime('%H:%M:%S')}] FOUND {len(results)} CANDIDATES ({elapsed_ms:.1f}ms):")
                print("-" * 70)
                for idx, r in enumerate(results):
                    name_str = f'"{r["name"]}" ({r["name_off"]})' if r["name"] else "[NO .BLK NAME FOUND]"
                    guid_info = f"{hex(r['guid'])}"
                    if is_valid_ptr(r['guid']):
                        glock = sc.read_mem(r['guid'] + 0x50, 1)[0] if sc.read_mem(r['guid'] + 0x50, 1) else 0
                        gtrk = sc.read_mem(r['guid'] + 0x51, 1)[0] if sc.read_mem(r['guid'] + 0x51, 1) else 0
                        gtgt_raw = sc.read_mem(r['guid'] + 0x8c, 2)
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
