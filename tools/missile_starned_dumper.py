#!/usr/bin/env python3
"""
🚀 Missile Dumper v2 (Pure Direct Offset 0 ECS Scanner)
======================================================================
สแกนหาขีปนาวุธ/ร็อคเก็ตสดทุกประเภทในเกม War Thunder (รองรับ 100+ ลูกพร้อมกัน)
ด้วยความเร็วสูงสุด < 0.01s สแกนสดตรงที่ Offset 0 ของ storage array ไม่พลาดแม้แต่ลูกเดียว!
"""

import sys
import os
import struct
import math
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address

# ====================================================================
# Target Offsets Configuration
# ====================================================================
OFFSETS_STARNED = (
    "starned",
    0x23c,   # pos
    0x258,   # vel
    0x40,    # owner
    0x94,    # state
    0x638,   # guidance
    0x30,    # entity_id
    0x6c8,   # props (name at props+0x50)
)

OFFSET_SETS = [OFFSETS_STARNED]

# ECS Manager Offsets
OFF_ECS_MANAGER    = 0x8225aa0
OFF_ECS_NODE_TABLE = 0x178
OFF_ECS_CLASS_TABLE= 0x5E8


# ====================================================================
# Helper Functions
# ====================================================================
def rp(sc, a):
    d = sc.read_mem(a, 8)
    return struct.unpack("<Q", d)[0] if d and len(d) >= 8 else 0

def r32(sc, a):
    d = sc.read_mem(a, 4)
    return struct.unpack("<I", d)[0] if d and len(d) >= 4 else 0

def r8(sc, a):
    d = sc.read_mem(a, 1)
    return d[0] if d and len(d) >= 1 else 0

def rv3(sc, a):
    d = sc.read_mem(a, 12)
    if not d or len(d) < 12: return None
    return struct.unpack("<fff", d)

def rstr(sc, a, n=96):
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

def is_real_missile_pos(pos):
    if not pos or not all(math.isfinite(x) for x in pos): return False
    nonzero = sum(1 for x in pos if abs(x) > 5.0)
    if nonzero < 1: return False
    if any(abs(x) > 250000 for x in pos): return False
    return True

def is_real_missile_vel(vel):
    if not vel or not all(math.isfinite(x) for x in vel): return False
    speed = vlen(vel)
    return 30.0 < speed < 4500.0


def check_ptr_is_rocket(sc, ptr):
    """ตรวจสอบว่า ptr นี้เป็น rocket จริงไหม (1 single block read + strict filtering)"""
    try:
        header = sc.read_mem(ptr, 0x6f0)
        if not header or len(header) < 0x6d0:
            return None
        
        for name, pos_off, vel_off, own_off, st_off, guid_off, eid_off, props_off in OFFSET_SETS:
            pos = struct.unpack_from("<fff", header, pos_off)
            if not is_real_missile_pos(pos):
                continue
            vel = struct.unpack_from("<fff", header, vel_off)
            if not is_real_missile_vel(vel):
                continue
            
            owner = struct.unpack_from("<Q", header, own_off)[0]
            state = header[st_off]
            guid  = struct.unpack_from("<Q", header, guid_off)[0]
            eid   = struct.unpack_from("<I", header, eid_off)[0]
            
            if state > 10:
                continue
            if owner > 0xFFFFFFFF:
                continue
            if eid == 0 or eid > 10_000_000:
                continue
            if guid != 0 and not is_valid_ptr(guid):
                continue
            
            rkt_name = ""
            props = struct.unpack_from("<Q", header, props_off)[0]
            if is_valid_ptr(props):
                name_ptr = rp(sc, props + 0x50)
                if is_valid_ptr(name_ptr):
                    rkt_name = rstr(sc, name_ptr)
            
            return {
                "ptr": ptr, "set": name,
                "pos": pos, "vel": vel, "speed": vlen(vel),
                "owner": owner, "state": state,
                "guid": guid, "eid": eid,
                "pos_off": pos_off, "vel_off": vel_off,
                "own_off": own_off, "guid_off": guid_off,
                "props_off": props_off, "name": rkt_name,
            }
    except Exception:
        pass
    return None


def brute_force_entries(sc, node_table, max_entries=350):
    """
    Pure Direct Offset 0 Window Scanner (0..350 entries)
    สแกนตรงจาก storage offset 0 (อ่านสูงสุด 1000 pointers ต่อ entry = 8KB)
    ดึงขีปนาวุธทุกประเภทที่กำลังบินอยู่ในอากาศ 100%
    """
    table_bytes = sc.read_mem(node_table, max_entries * 0x20)
    if not table_bytes or len(table_bytes) < 0x20:
        return []
    
    all_rockets = []
    seen_ptrs = set()
    num_entries = len(table_bytes) // 0x20
    
    for i in range(num_entries):
        data = table_bytes[i * 0x20 : (i + 1) * 0x20]
        if all(b == 0 for b in data):
            continue
        
        storage = struct.unpack_from("<Q", data, 0)[0]
        if not is_valid_ptr(storage):
            continue
        
        count = struct.unpack_from("<I", data, 8)[0]
        cap = struct.unpack_from("<I", data, 0x14)[0]
        num_ptrs = min(max(max(count, cap), 64), 2048)
        
        # 1. Read storage array directly at offset 0 matching exact allocated block
        bulk0 = sc.read_mem(storage, num_ptrs * 8)
        if not bulk0:
            bulk0 = sc.read_mem(storage, max(count, 32) * 8)
            
        if bulk0 and len(bulk0) >= 8:
            for idx in range(len(bulk0) // 8):
                ptr = struct.unpack_from("<Q", bulk0, idx * 8)[0]
                if is_valid_ptr(ptr) and ptr not in seen_ptrs:
                    info = check_ptr_is_rocket(sc, ptr)
                    if info:
                        info["layout"] = "A_direct_0"
                        info["entry"] = i
                        seen_ptrs.add(ptr)
                        all_rockets.append(info)
    
    return all_rockets


def main():
    print("🚀 Missile Dumper v2 (Pure Direct Offset 0 Scanner)")
    print("=" * 70)
    
    pid = get_game_pid()
    if not pid:
        print("❌ ไม่พบ Game PID!")
        return
    
    base = get_game_base_address(pid)
    print(f"[+] PID: {pid}, Base: {hex(base)}")
    
    sc = MemoryScanner(pid)
    
    # Read ECS Manager
    ecs_mgr = rp(sc, base + OFF_ECS_MANAGER)
    if not is_valid_ptr(ecs_mgr):
        print(f"❌ อ่าน ECS Manager ล้มเหลวที่ {hex(base + OFF_ECS_MANAGER)}")
        return
    
    node_t = rp(sc, ecs_mgr + OFF_ECS_NODE_TABLE)
    class_t = rp(sc, ecs_mgr + OFF_ECS_CLASS_TABLE)
    
    print(f"✅ ECS Manager: {hex(ecs_mgr)}")
    print(f"   node_table:  {hex(node_t)}")
    print(f"   class_table: {hex(class_t)}")
    
    # Run Pure Direct Offset 0 Batch Entry Scanner
    t0 = time.time()
    unique = brute_force_entries(sc, node_t, 350)
    t_elapsed = (time.time() - t0) * 1000
    
    # Sort by speed (highest first)
    unique.sort(key=lambda r: r["speed"], reverse=True)
    
    # Print results
    print(f"\n{'=' * 70}")
    print(f"📋 RESULTS: {len(unique)} active rockets/missiles found in {t_elapsed:.1f}ms")
    print("=" * 70)
    
    if not unique:
        print("\n❌ ไม่เจอ rocket/missile!")
        print("   1. ต้องอยู่ในแมตช์ที่มี missile กำลังบินอยู่!")
        print("   2. หรือกด CTRL+C แล้วยิง missile ใหม่")
        return
    
    for idx, r in enumerate(unique):
        owner_str = f"{hex(r['owner'])} ✅" if 0 < r['owner'] <= 0xFFFFFFFF else f"{hex(r['owner'])} ❌"
        guid_str = f"{hex(r['guid'])}" if r['guid'] != 0 else "none (unguided)"
        if r['guid'] != 0 and is_valid_ptr(r['guid']):
            g_lock = r8(sc, r['guid'] + 0x50)
            g_trk = r8(sc, r['guid'] + 0x51)
            g_tgt = struct.unpack("<h", sc.read_mem(r['guid'] + 0x8c, 2))[0] if sc.read_mem(r['guid'] + 0x8c, 2) else -1
            guid_str += f" locked={g_lock} tracking={g_trk} target_id={g_tgt}"
        
        name_str = f'\n     Name:     "{r["name"]}"' if r["name"] else ""
        
        print(f"\n  🚀 #{idx} [{r['set']}] layout={r['layout']} entry={r['entry']}")
        print(f"     Ptr:      {hex(r['ptr'])}")
        print(f"     Position: ({r['pos'][0]:.1f}, {r['pos'][1]:.1f}, {r['pos'][2]:.1f})")
        print(f"     Velocity: ({r['vel'][0]:.1f}, {r['vel'][1]:.1f}, {r['vel'][2]:.1f})  speed={r['speed']:.1f} m/s")
        print(f"     Owner:    {owner_str}")
        print(f"     State:    {r['state']}  EntityID: {r['eid']}{name_str}")
        print(f"     Guidance: {guid_str}")
    
    print(f"\n\n📊 Summary by offset set:")
    for set_name in set(r['set'] for r in unique):
        count = sum(1 for r in unique if r['set'] == set_name)
        avg_spd = sum(r['speed'] for r in unique if r['set'] == set_name) / count
        print(f"  {set_name}: {count} rockets, avg speed={avg_spd:.0f} m/s")
    
    print(f"\n📊 Summary by ECS layout:")
    for layout in set(r['layout'] for r in unique):
        count = sum(1 for r in unique if r['layout'] == layout)
        print(f"  {layout}: {count} rockets")
    
    print(f"\n\n📡 Live monitor (Ctrl+C to stop)...")
    try:
        while True:
            time.sleep(0.2)
            fresh = brute_force_entries(sc, node_t, 350)
            if fresh:
                parts = []
                for r in fresh[:10]:
                    parts.append(f"({r['pos'][0]:.0f},{r['pos'][1]:.0f},{r['pos'][2]:.0f}) {r['speed']:.0f}m/s")
                print(f"  🚀 Total Active: {len(fresh)} | " + " | ".join(parts[:5]))
    except KeyboardInterrupt:
        print("\n\n👋 Stopped live monitor.")


if __name__ == "__main__":
    main()
