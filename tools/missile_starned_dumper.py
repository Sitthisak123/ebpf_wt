#!/usr/bin/env python3
"""
🚀 Missile Dumper v2 - Exhaustive ECS row parsing
ลองทุก interpretation ของ node_table entry layout

starned: "Rows span a 16-bit start at callback record +0x2 
          to a 32-bit end at +0x4. The list pointer is at +0x8.
          Comp 0 is the rocket pointer, comp 1 is an alive byte"

วิธีใช้: sudo python3 tools/missile_starned_dumper.py
ต้องอยู่ในเกมที่มี missile/rocket กำลังบินอยู่!
"""

import struct, sys, os, math, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address
from src.utils.mul import is_valid_ptr, GHIDRA_BASE

# ====================================================================
# Rocket internal offsets (all candidate sets)
# ====================================================================
OFFSET_SETS = [
    # (name, pos, vel, owner, state, guidance, entity_id, props_ptr)
    ("starned",  0x23c, 0x258, 0x40,  0x94, 0x638, 0x30, 0x6c8),
]

# ECS internal offsets (stable)
ECS_NODE_TABLE  = 0x178
ECS_CLASS_TABLE = 0x5E8
OUR_ALLLISTDATA = 0x8225aa0

# ====================================================================
# Helpers
# ====================================================================
def rp(sc, a):
    d = sc.read_mem(a, 8)
    return struct.unpack("<Q", d)[0] if d and len(d) >= 8 else 0

def r32(sc, a):
    d = sc.read_mem(a, 4)
    return struct.unpack("<I", d)[0] if d and len(d) >= 4 else 0

def r16(sc, a):
    d = sc.read_mem(a, 2)
    return struct.unpack("<H", d)[0] if d and len(d) >= 2 else 0

def r8(sc, a):
    d = sc.read_mem(a, 1)
    return d[0] if d and len(d) >= 1 else 0

def rv3(sc, a):
    d = sc.read_mem(a, 12)
    if not d or len(d) < 12: return None
    return struct.unpack("<fff", d)

def rstr(sc, a, n=64):
    d = sc.read_mem(a, n)
    if not d: return ""
    try: end = d.index(0); return d[:end].decode("utf-8", errors="replace")
    except ValueError: return d[:n].decode("utf-8", errors="replace")

def vlen(v): return math.sqrt(sum(x*x for x in v))

def is_real_missile_pos(v):
    """Missile ต้องมีพิกัดที่สมจริง - อย่างน้อย 2 แกนไม่เป็น 0 และสมเหตุสมผล"""
    if not v: return False
    if not all(math.isfinite(x) for x in v): return False
    nonzero = sum(1 for x in v if abs(x) > 5.0)  # ต้องมากกว่า 5m
    return nonzero >= 2 and all(abs(x) < 200000 for x in v)

def is_real_missile_vel(v):
    """Missile speed 50-3500 m/s, ต้องมีอย่างน้อย 2 แกนที่ไม่ใช่ 0"""
    if not v: return False
    if not all(math.isfinite(x) for x in v): return False
    speed = vlen(v)
    nonzero_vel = sum(1 for x in v if abs(x) > 1.0)
    return 50.0 < speed < 3500.0 and nonzero_vel >= 2

def check_ptr_is_rocket(sc, ptr):
    """ลองทุก offset set ดูว่า ptr นี้เป็น rocket จริงไหม (strict filtering)"""
    for name, pos_off, vel_off, own_off, st_off, guid_off, eid_off, props_off in OFFSET_SETS:
        pos = rv3(sc, ptr + pos_off)
        if not is_real_missile_pos(pos):
            continue
        vel = rv3(sc, ptr + vel_off)
        if not is_real_missile_vel(vel):
            continue
        
        # pos+vel ผ่าน → เช็ค secondary fields
        owner = rp(sc, ptr + own_off)
        state = r8(sc, ptr + st_off)
        guid  = rp(sc, ptr + guid_off)
        eid   = r32(sc, ptr + eid_off)
        
        # STRICT FILTERS based on confirmed real rockets:
        # 1. State ต้อง <= 10 (real rockets มี state=0)
        if state > 10:
            continue
        # 2. Owner ต้องพอดี 32-bit (confirmed: 0x5f1c3f21)
        #    garbage owners จะเป็น 64-bit full (0x439628b4c5691b5c)
        if owner > 0xFFFFFFFF:
            continue
        # 3. EntityID ต้อง > 0 และ < 10M (confirmed: 402446-408590)
        if eid == 0 or eid > 10_000_000:
            continue
        # 4. Guidance ptr ถ้ามีต้อง valid (confirmed: 0x5a11d1f0)
        #    ถ้า guid=0 ก็ได้ (unguided rocket)
        if guid != 0 and not is_valid_ptr(guid):
            continue
        # 5. ลองหาชื่อ rocket ผ่าน props_ptr
        rkt_name = ""
        props = rp(sc, ptr + props_off)
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
    return None

# ====================================================================
# Phase 1: Dump raw node_table entries for analysis
# ====================================================================
def dump_raw_entries(sc, node_table, count=50):
    """Dump raw bytes ของ node_table entries เพื่อวิเคราะห์ layout"""
    print("\n📋 Raw node_table entries (first interesting ones):")
    printed = 0
    for i in range(count):
        addr = node_table + i * 0x20
        data = sc.read_mem(addr, 0x20)
        if not data or len(data) < 0x20: break
        # Skip all-zero entries
        if all(b == 0 for b in data): continue
        
        vals = struct.unpack("<IIHHI QQ", data[:0x20])  # try various unpacking
        # Actually let's just unpack as raw values
        q0 = struct.unpack_from("<Q", data, 0)[0]
        q1 = struct.unpack_from("<Q", data, 8)[0]
        q2 = struct.unpack_from("<Q", data, 16)[0]
        q3 = struct.unpack_from("<Q", data, 24)[0]
        
        # starned's interpretation
        start_s = struct.unpack_from("<H", data, 2)[0]
        end_s = struct.unpack_from("<I", data, 4)[0]
        list_ptr_s = struct.unpack_from("<Q", data, 8)[0]
        
        if printed < 15:
            hex_str = " ".join(f"{b:02x}" for b in data)
            print(f"  [{i:3d}] {hex_str}")
            print(f"        q0={hex(q0):>18s} q1={hex(q1):>18s} q2={hex(q2):>18s} q3={hex(q3):>18s}")
            print(f"        starned: start={start_s} end={end_s} list_ptr={hex(list_ptr_s)}")
            printed += 1

# ====================================================================
# Phase 2: Try ALL possible interpretations of entries
# ====================================================================
def brute_force_entries(sc, node_table, max_entries=500):
    """
    สำหรับแต่ละ entry ลองทุก interpretation:
    - storage pointer ที่ offset 0, 8, 16, 24
    - count จาก (end-start) หรือ u32 ที่ offset ต่างๆ
    - component layout: direct pointer array vs column-pointer-array
    """
    print("\n" + "=" * 70)
    print("🔬 Phase 2: Brute-force all entry interpretations")
    print("=" * 70)
    
    all_rockets = []
    
    for i in range(max_entries):
        addr = node_table + i * 0x20
        data = sc.read_mem(addr, 0x20)
        if not data or len(data) < 0x20: break
        if all(b == 0 for b in data): continue
        
        # Extract all possible pointers and counts from this entry
        ptrs_in_entry = []
        for off in [0, 8, 16, 24]:
            v = struct.unpack_from("<Q", data, off)[0]
            if is_valid_ptr(v):
                ptrs_in_entry.append((off, v))
        
        counts_in_entry = []
        # starned: start=+0x2(u16), end=+0x4(u32) → count=end-start
        start_s = struct.unpack_from("<H", data, 2)[0]
        end_s = struct.unpack_from("<I", data, 4)[0]
        if end_s > start_s and (end_s - start_s) < 10000:
            counts_in_entry.append(("starned", end_s - start_s, start_s))
        # u32 at various offsets
        for co in [0x10, 0x14, 0x18, 0x1C, 0x0C]:
            cv = struct.unpack_from("<I", data, co)[0]
            if 0 < cv < 10000:
                counts_in_entry.append((f"u32@{hex(co)}", cv, 0))
        # u16 at various offsets
        for co in [0x10, 0x12, 0x14, 0x16, 0x18, 0x1A, 0x02]:
            cv = struct.unpack_from("<H", data, co)[0]
            if 0 < cv < 10000:
                counts_in_entry.append((f"u16@{hex(co)}", cv, 0))
        
        if not ptrs_in_entry or not counts_in_entry:
            continue
        
        # Try each (ptr, count) combination
        for ptr_off, storage_ptr in ptrs_in_entry:
            for cnt_name, count, start_idx in counts_in_entry:
                rockets = try_read_rockets_from_storage(
                    sc, storage_ptr, count, start_idx, i, ptr_off, cnt_name
                )
                if rockets:
                    all_rockets.extend(rockets)
    
    return all_rockets


def try_read_rockets_from_storage(sc, storage, count, start_idx, entry_idx, ptr_off, cnt_name):
    """
    ลองอ่าน rockets จาก storage ด้วยหลาย layout:
    
    Layout A: storage เป็น pointer array โดยตรง
      rocket_ptr = *(storage + idx * 8)
      
    Layout B: storage เป็น column-pointer array (starned's interpretation)
      col0_ptr = *(storage + 0)  → rocket pointer column
      col1_ptr = *(storage + 8)  → alive byte column
      rocket_ptr = *(col0_ptr + idx * 8)
      alive = *(col1_ptr + idx)
      
    Layout C: storage + componentOffset << shift
      (from BOYU808)
    """
    rockets = []
    limit = min(count, 300)
    
    # === Layout A: Direct pointer array ===
    bulk = sc.read_mem(storage + start_idx * 8, limit * 8)
    if bulk and len(bulk) >= 8:
        for idx in range(min(limit, len(bulk) // 8)):
            ptr = struct.unpack_from("<Q", bulk, idx * 8)[0]
            if is_valid_ptr(ptr):
                info = check_ptr_is_rocket(sc, ptr)
                if info:
                    info["layout"] = "A_direct"
                    info["entry"] = entry_idx
                    info["ptr_off"] = ptr_off
                    info["cnt_src"] = cnt_name
                    rockets.append(info)
                    if len(rockets) >= 100: return rockets  # cap สูงไม่ให้หนัก
    
    # === Layout A2: stride=16 ===
    bulk16 = sc.read_mem(storage + start_idx * 16, limit * 16)
    if bulk16 and len(bulk16) >= 16:
        for idx in range(min(limit, len(bulk16) // 16)):
            ptr = struct.unpack_from("<Q", bulk16, idx * 16)[0]
            if is_valid_ptr(ptr):
                info = check_ptr_is_rocket(sc, ptr)
                if info:
                    info["layout"] = "A_stride16"
                    info["entry"] = entry_idx
                    rockets.append(info)
                    if len(rockets) >= 100: return rockets
    
    # === Layout B: Column pointer array ===
    col0 = rp(sc, storage)
    col1 = rp(sc, storage + 8)
    if is_valid_ptr(col0):
        col_bulk = sc.read_mem(col0 + start_idx * 8, limit * 8)
        if col_bulk and len(col_bulk) >= 8:
            for idx in range(min(limit, len(col_bulk) // 8)):
                # Check alive if col1 is valid
                if is_valid_ptr(col1):
                    alive = r8(sc, col1 + start_idx + idx)
                    if alive != 1:
                        continue
                
                ptr = struct.unpack_from("<Q", col_bulk, idx * 8)[0]
                if is_valid_ptr(ptr):
                    info = check_ptr_is_rocket(sc, ptr)
                    if info:
                        info["layout"] = "B_col_ptrs"
                        info["entry"] = entry_idx
                        rockets.append(info)
                        if len(rockets) >= 100: return rockets
    
    # === Layout C: Column pointer array with 16-byte stride ===
    if is_valid_ptr(col0):
        col_bulk16 = sc.read_mem(col0 + start_idx * 16, limit * 16)
        if col_bulk16 and len(col_bulk16) >= 16:
            for idx in range(min(limit, len(col_bulk16) // 16)):
                ptr = struct.unpack_from("<Q", col_bulk16, idx * 16)[0]
                if is_valid_ptr(ptr):
                    info = check_ptr_is_rocket(sc, ptr)
                    if info:
                        info["layout"] = "C_col16"
                        info["entry"] = entry_idx
                        rockets.append(info)
                        if len(rockets) >= 100: return rockets
    
    # === Layout D: storage IS the rocket (single entity per entry) ===
    info = check_ptr_is_rocket(sc, storage)
    if info:
        info["layout"] = "D_single"
        info["entry"] = entry_idx
        rockets.append(info)
    
    return rockets


# ====================================================================
# Phase 3: Scan heap for rocket-like objects (fallback)
# ====================================================================
def heap_scan_for_rockets(sc, base, sample_ptrs=None):
    """
    ถ้า ECS parsing ไม่ได้ผล ลอง scan heap โดยตรง
    หา pattern: valid pos + valid vel ที่ starned's offsets
    """
    print("\n" + "=" * 70)
    print("🔍 Phase 3: Heap scan for rocket-like objects")
    print("=" * 70)
    
    # ถ้ามี sample pointers จาก Phase 2 ให้ลอง scan รอบๆ
    rockets = []
    
    if sample_ptrs:
        print(f"  Scanning around {len(sample_ptrs)} known heap regions...")
        for base_ptr in sample_ptrs:
            # Scan ±1MB around the known pointer
            region_start = (base_ptr & ~0xFFF) - 0x100000
            region_end = region_start + 0x200000
            
            found = scan_region_for_rockets(sc, region_start, region_end, step=0x100)
            rockets.extend(found)
            if len(rockets) >= 20:
                break
    
    # Also try scanning from node_table pointers
    mgr = rp(sc, base + OUR_ALLLISTDATA)
    if is_valid_ptr(mgr):
        node_t = rp(sc, mgr + ECS_NODE_TABLE)
        if is_valid_ptr(node_t):
            # Read first few valid pointers from node_table entries
            for i in range(100):
                entry_addr = node_t + i * 0x20
                for off in [0, 8, 16]:
                    ptr = rp(sc, entry_addr + off)
                    if is_valid_ptr(ptr) and ptr > 0x1000000:
                        # Quick check: scan first 50 entries from this ptr
                        for j in range(50):
                            rkt_ptr = rp(sc, ptr + j * 8)
                            if is_valid_ptr(rkt_ptr):
                                info = check_ptr_is_rocket(sc, rkt_ptr)
                                if info:
                                    info["heap_source"] = f"entry{i}+{hex(off)}[{j}]"
                                    rockets.append(info)
    
    return rockets


def scan_region_for_rockets(sc, start, end, step=0x100):
    """Scan a memory region for rocket-like objects"""
    rockets = []
    for addr in range(start, end, step):
        info = check_ptr_is_rocket(sc, addr)
        if info:
            info["heap_scan"] = True
            rockets.append(info)
    return rockets


# ====================================================================
# Print
# ====================================================================
def print_rocket(sc, info, idx):
    pos, vel = info["pos"], info["vel"]
    icon = "🚀" if info["speed"] > 200 else "🎯"
    print(f"\n  {icon} #{idx} [{info['set']}] layout={info.get('layout','?')} entry={info.get('entry','?')}")
    print(f"     Ptr:      {hex(info['ptr'])}")
    print(f"     Position: ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})")
    print(f"     Velocity: ({vel[0]:.1f}, {vel[1]:.1f}, {vel[2]:.1f})  speed={info['speed']:.1f} m/s")
    print(f"     Owner:    {hex(info['owner'])} {'✅' if is_valid_ptr(info['owner']) else '❌'}")
    print(f"     State:    {info['state']}  EntityID: {info['eid']}")
    
    # Name (pre-fetched)
    name = info.get("name", "")
    if name and len(name) > 3:
        print(f"     Name:     \"{name}\"")
    
    # Guidance details
    guid = info.get("guid", 0)
    if is_valid_ptr(guid):
        locked = r8(sc, guid + 0x50)
        tracking = r8(sc, guid + 0x51)
        target_data = sc.read_mem(guid + 0x8C, 2)
        target = struct.unpack("<h", target_data)[0] if target_data and len(target_data) >= 2 else -1
        print(f"     Guidance: {hex(guid)} locked={locked} tracking={tracking} target_id={target}")
    else:
        print(f"     Guidance: none (unguided)")


# ====================================================================
# Main
# ====================================================================
def main():
    print("🚀 Missile Dumper v2 (exhaustive ECS parsing)")
    print("=" * 70)
    
    pid = get_game_pid()
    base = get_game_base_address(pid)
    sc = MemoryScanner(pid)
    print(f"[+] PID: {pid}, Base: {hex(base)}")
    
    # Get ECS Manager
    mgr = rp(sc, base + OUR_ALLLISTDATA)
    if not is_valid_ptr(mgr):
        print(f"❌ ECS Manager invalid at base+{hex(OUR_ALLLISTDATA)}")
        return
    
    node_t = rp(sc, mgr + ECS_NODE_TABLE)
    class_t = rp(sc, mgr + ECS_CLASS_TABLE)
    print(f"✅ ECS Manager: {hex(mgr)}")
    print(f"   node_table:  {hex(node_t)}")
    print(f"   class_table: {hex(class_t)}")
    
    if not (is_valid_ptr(node_t) and is_valid_ptr(class_t)):
        print("❌ Invalid ECS tables")
        return
    
    # Phase 1: Dump raw entries
    dump_raw_entries(sc, node_t, 50)
    
    # Phase 2: Brute-force (expanded to 5000 entries)
    rockets = brute_force_entries(sc, node_t, 5000)
    
    # Deduplicate
    seen = set()
    unique = []
    for r in rockets:
        if r["ptr"] not in seen:
            seen.add(r["ptr"])
            unique.append(r)
    
    # Phase 3: Heap scan if needed
    if len(unique) < 4:
        print(f"\n  ⚠️  Only {len(unique)} rockets from ECS, trying heap scan...")
        sample_ptrs = [r["ptr"] for r in unique] if unique else []
        heap_rockets = heap_scan_for_rockets(sc, base, sample_ptrs)
        for r in heap_rockets:
            if r["ptr"] not in seen:
                seen.add(r["ptr"])
                unique.append(r)
    
    # Sort by speed (highest first)
    unique.sort(key=lambda r: r["speed"], reverse=True)
    
    # Print results
    print(f"\n\n{'=' * 70}")
    print(f"📋 RESULTS: {len(unique)} rockets/missiles found")
    print("=" * 70)
    
    if not unique:
        print("\n❌ ไม่เจอ rocket/missile!")
        print("   1. ต้องอยู่ในแมตช์ที่มี missile กำลังบินอยู่!")
        print("   2. ลอง Test Flight → ยิง missile → รัน script ทันที")
        print("   3. ECS Manager offset อาจต้อง scan ใหม่")
        return
    
    for i, r in enumerate(unique[:20]):
        print_rocket(sc, r, i)
    
    # Per-offset-set summary
    by_set = {}
    for r in unique:
        by_set.setdefault(r["set"], []).append(r)
    print(f"\n\n📊 Summary by offset set:")
    for name, items in sorted(by_set.items(), key=lambda x: -len(x[1])):
        avg_speed = sum(r["speed"] for r in items) / len(items)
        print(f"  {name}: {len(items)} rockets, avg speed={avg_speed:.0f} m/s")
    
    # Per-layout summary
    by_layout = {}
    for r in unique:
        by_layout.setdefault(r.get("layout", "?"), []).append(r)
    print(f"\n📊 Summary by ECS layout:")
    for name, items in sorted(by_layout.items(), key=lambda x: -len(x[1])):
        print(f"  {name}: {len(items)} rockets")
    
    # Output offsets
    if unique:
        best = unique[0]
        print(f"\n\n{'=' * 70}")
        print(f"📋 BEST OFFSETS (from {best['set']}, layout={best.get('layout','?')}):")
        print(f"{'=' * 70}")
        print(f"OFF_ROCKET_POS       = {hex(best['pos_off'])}")
        print(f"OFF_ROCKET_VEL       = {hex(best['vel_off'])}")
        print(f"OFF_ROCKET_OWNER     = {hex(best['own_off'])}")
        print(f"OFF_ROCKET_GUIDANCE  = {hex(best['guid_off'])}")
    
    # Live monitor
    print(f"\n📡 Live monitor (Ctrl+C to stop)...")
    try:
        while True:
            time.sleep(0.3)
            lines = []
            for r in unique[:5]:
                pos = rv3(sc, r["ptr"] + r["pos_off"])
                vel = rv3(sc, r["ptr"] + r["vel_off"])
                if pos and vel and is_real_missile_pos(pos) and is_real_missile_vel(vel):
                    spd = vlen(vel)
                    lines.append(f"({pos[0]:.0f},{pos[1]:.0f},{pos[2]:.0f}) {spd:.0f}m/s")
            
            if lines:
                print(f"\r  🚀 {' | '.join(lines)}", end="", flush=True)
            else:
                print(f"\r  ⏸️  No active missiles...                    ", end="", flush=True)
    except KeyboardInterrupt:
        print("\n👋 Done.")


if __name__ == "__main__":
    main()
