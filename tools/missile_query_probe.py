#!/usr/bin/env python3
"""
🎯 Targeted ECS Missile Query Probe
ใช้ข้อมูลจาก scan แรกเพื่อลงลึก:
  - AllListData candidate: base+0x8225aa0 (Ghidra: 0x8625aa0)
  - Manager ptr: 0xa470c40
  - node_table: 0x37f77f80 
  - class_table: 0x3e0b8270

Rocket query shape: req=3, opt=0, sublists=35
ลอง selector 128, 257, 258 ที่ validate ผ่าน

วิธีใช้:
  sudo python3 tools/missile_query_probe.py
"""

import struct
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address
from src.utils.mul import is_valid_ptr, GHIDRA_BASE

# ====================================================================
# Helpers
# ====================================================================
def read_ptr(scanner, addr):
    data = scanner.read_mem(addr, 8)
    if not data or len(data) < 8: return 0
    return struct.unpack("<Q", data)[0]

def read_u32(scanner, addr):
    data = scanner.read_mem(addr, 4)
    if not data or len(data) < 4: return 0
    return struct.unpack("<I", data)[0]

def read_u16(scanner, addr):
    data = scanner.read_mem(addr, 2)
    if not data or len(data) < 2: return 0
    return struct.unpack("<H", data)[0]

def read_u8(scanner, addr):
    data = scanner.read_mem(addr, 1)
    if not data or len(data) < 1: return 0
    return data[0]

def read_vec3(scanner, addr):
    data = scanner.read_mem(addr, 12)
    if not data or len(data) < 12: return None
    return struct.unpack("<fff", data)

def read_string(scanner, addr, max_len=64):
    data = scanner.read_mem(addr, max_len)
    if not data: return ""
    try:
        end = data.index(0)
        return data[:end].decode("utf-8", errors="replace")
    except ValueError:
        return data.decode("utf-8", errors="replace")

# ====================================================================
# Known ECS Manager from scan
# ====================================================================
ALLLISTDATA_OFFSET = 0x8225aa0  # base + this = pointer to ECS manager

# Known candidate selectors that produced sublists=35, req=3
ROCKET_SELECTORS_TO_TRY = [128, 257, 258, 229, 1079, 1090, 1120, 1263, 1344, 1345]

# Starned's rocket offsets (Linux) - try these first
ROCKET_POS_CANDIDATES   = [0x23c, 0x298, 0x2C8, 0x190, 0x1D0]
ROCKET_VEL_CANDIDATES   = [0x258, 0x2B4, 0x2E4, 0x1AC, 0x1EC]
ROCKET_OWNER_CANDIDATES = [0x40, 0x48, 0x480]
ROCKET_STATE_CANDIDATES = [0x94]
ROCKET_GUID_CANDIDATES  = [0x638, 0x648, 0x6C8, 0x698]


def dump_ecs_query(scanner, class_table, node_table, selector, verbose=True):
    """Parse an ECS query and return component data."""
    index_data_addr = class_table + (selector << 6)
    
    meta = scanner.read_mem(index_data_addr, 64)
    if not meta:
        return None
    
    num_required = meta[0]
    num_optional = meta[1]
    num_sublists = struct.unpack_from("<H", meta, 2)[0]
    total_comps = num_required + num_optional
    
    if verbose:
        print(f"\n  📊 Query sel={selector}: req={num_required}, opt={num_optional}, sublists={num_sublists}")
    
    # Get sublist offsets
    if num_sublists <= 9:
        sublist_offsets_ptr = index_data_addr + 0x04
    else:
        sublist_offsets_ptr = read_ptr(scanner, index_data_addr + 0x08)
        if not is_valid_ptr(sublist_offsets_ptr):
            if verbose: print("    ❌ Invalid sublist offsets pointer")
            return None
    
    # Get component offset matrix
    if total_comps <= 16:
        comp_matrix_ptr = index_data_addr + 0x18
    else:
        comp_matrix_ptr = read_ptr(scanner, index_data_addr + 0x18)
        if not is_valid_ptr(comp_matrix_ptr):
            if verbose: print("    ❌ Invalid comp matrix pointer")
            return None
    
    all_entities = []
    
    for sl in range(num_sublists):
        sl_offset = read_u32(scanner, sublist_offsets_ptr + sl * 4)
        list_data_addr = node_table + sl_offset * 0x20
        
        # Read list descriptor (try multiple count positions)
        desc = scanner.read_mem(list_data_addr, 0x20)
        if not desc:
            continue
        
        # The descriptor layout from BOYU808:
        # Appears to be: storage_ptr, then later count
        storage = struct.unpack_from("<Q", desc, 0)[0]
        
        # Try count at different offsets in the descriptor
        count = 0
        for count_off in [0x10, 0x14, 0x08, 0x0C, 0x18]:
            c = struct.unpack_from("<I", desc, count_off)[0]
            if 0 < c < 5000:
                count = c
                break
        
        if count == 0 or not is_valid_ptr(storage):
            continue
        
        # Read per-sublist component offsets  
        # The comp offset matrix may be organized differently
        # Try: comp_matrix + (sublist_index * total_comps * 2)
        comp_off_data = scanner.read_mem(
            comp_matrix_ptr + sl * total_comps * 2, total_comps * 2
        )
        if not comp_off_data or len(comp_off_data) < total_comps * 2:
            continue
        
        comp_offsets = []
        for ci in range(total_comps):
            comp_offsets.append(struct.unpack_from("<H", comp_off_data, ci * 2)[0])
        
        if verbose and sl < 3:
            print(f"    Sublist {sl}: storage={hex(storage)} count={count} "
                  f"comp_offs={[hex(c) for c in comp_offsets]}")
        
        # Try to read entities
        for i in range(min(count, 200)):
            # comp[0] should be the entity pointer column
            # comp[1] should be the alive byte column
            # Try different shift values (3 = 8-byte stride, 0 = raw offset)
            entity_ptr = 0
            alive = 0
            
            for shift in [3, 0, 4]:
                try_ptr = read_ptr(scanner, storage + (comp_offsets[0] << shift) + i * 8)
                if is_valid_ptr(try_ptr):
                    entity_ptr = try_ptr
                    if num_required >= 2:
                        # Read alive byte
                        alive = read_u8(scanner, storage + (comp_offsets[1] << shift) + i)
                    else:
                        alive = 1
                    break
            
            if is_valid_ptr(entity_ptr):
                all_entities.append({
                    "ptr": entity_ptr,
                    "alive": alive,
                    "sublist": sl,
                    "index": i,
                })
    
    if verbose:
        alive_count = sum(1 for e in all_entities if e["alive"] == 1)
        print(f"    📦 Total entities: {len(all_entities)}, alive: {alive_count}")
    
    return all_entities


def probe_rocket_offsets(scanner, entities):
    """Try different offsets on the entity pointers to find position, velocity, etc."""
    print("\n" + "=" * 70)
    print("🔬 Probing Rocket Internal Offsets")
    print("=" * 70)
    
    # Only probe alive entities
    alive_entities = [e for e in entities if e["alive"] == 1]
    if not alive_entities:
        print("  ⚠️  No alive entities found, probing all entities instead")
        alive_entities = entities[:20]
    
    print(f"  Testing {len(alive_entities)} entities...")
    
    # For each candidate position offset, check if it gives plausible coordinates
    for pos_off in ROCKET_POS_CANDIDATES:
        valid_count = 0
        sample_pos = None
        for e in alive_entities[:10]:
            pos = read_vec3(scanner, e["ptr"] + pos_off)
            if pos and all(abs(v) < 100000 and abs(v) > 0.001 for v in pos):
                valid_count += 1
                if not sample_pos:
                    sample_pos = pos
        
        if valid_count > 0:
            print(f"\n  📍 Position at +{hex(pos_off)}: {valid_count}/min(10,{len(alive_entities)}) valid")
            if sample_pos:
                print(f"     Sample: ({sample_pos[0]:.1f}, {sample_pos[1]:.1f}, {sample_pos[2]:.1f})")
    
    # Velocity
    for vel_off in ROCKET_VEL_CANDIDATES:
        valid_count = 0
        sample_vel = None
        for e in alive_entities[:10]:
            vel = read_vec3(scanner, e["ptr"] + vel_off)
            if vel and all(abs(v) < 5000 for v in vel) and any(abs(v) > 0.1 for v in vel):
                valid_count += 1
                if not sample_vel:
                    sample_vel = vel
        
        if valid_count > 0:
            print(f"\n  🚀 Velocity at +{hex(vel_off)}: {valid_count}/min(10,{len(alive_entities)}) valid")
            if sample_vel:
                speed = (sample_vel[0]**2 + sample_vel[1]**2 + sample_vel[2]**2)**0.5
                print(f"     Sample: ({sample_vel[0]:.1f}, {sample_vel[1]:.1f}, {sample_vel[2]:.1f}) speed={speed:.1f}")
    
    # Owner unit ptr
    for own_off in ROCKET_OWNER_CANDIDATES:
        valid_count = 0
        sample_owner = 0
        for e in alive_entities[:10]:
            owner = read_ptr(scanner, e["ptr"] + own_off)
            if is_valid_ptr(owner):
                valid_count += 1
                if not sample_owner:
                    sample_owner = owner
        
        if valid_count > 0:
            print(f"\n  👤 Owner at +{hex(own_off)}: {valid_count}/min(10,{len(alive_entities)}) valid")
            if sample_owner:
                print(f"     Sample: {hex(sample_owner)}")
    
    # Guidance ptr 
    for guid_off in ROCKET_GUID_CANDIDATES:
        valid_count = 0
        sample_guid = 0
        for e in alive_entities[:10]:
            guid = read_ptr(scanner, e["ptr"] + guid_off)
            if is_valid_ptr(guid):
                valid_count += 1
                if not sample_guid:
                    sample_guid = guid
        
        if valid_count > 0:
            print(f"\n  🎯 Guidance at +{hex(guid_off)}: {valid_count}/min(10,{len(alive_entities)}) valid")
            if sample_guid:
                print(f"     Sample: {hex(sample_guid)}")
                # Try reading guidance struct
                is_locked = read_u8(scanner, sample_guid + 0x50)
                is_tracking = read_u8(scanner, sample_guid + 0x51)
                target_id = read_u16(scanner, sample_guid + 0x8C)
                print(f"     isLocked={is_locked} isTracking={is_tracking} targetId={target_id}")
    
    # State byte  
    for state_off in ROCKET_STATE_CANDIDATES:
        states = {}
        for e in alive_entities[:10]:
            state = read_u8(scanner, e["ptr"] + state_off)
            states[state] = states.get(state, 0) + 1
        
        if states:
            print(f"\n  📋 State at +{hex(state_off)}: {states}")
    
    # Brute-force scan for entity name (string pointer)
    print("\n  🔍 Scanning for name pointers...")
    for e in alive_entities[:3]:
        for off in range(0x600, 0x750, 8):
            name_cont = read_ptr(scanner, e["ptr"] + off)
            if is_valid_ptr(name_cont):
                # Try reading string at name_cont + 0x50 (missile name)
                for str_off in [0x0, 0x10, 0x50]:
                    name_ptr = read_ptr(scanner, name_cont + str_off)
                    if is_valid_ptr(name_ptr):
                        name = read_string(scanner, name_ptr)
                        if name and len(name) > 3 and name.isprintable():
                            print(f"    Entity {hex(e['ptr'])} +{hex(off)} -> cont+{hex(str_off)}: \"{name}\"")
                    # Also try direct string
                    name = read_string(scanner, name_cont + str_off)
                    if name and len(name) > 3 and name.isprintable() and "/" in name or "_" in name:
                        print(f"    Entity {hex(e['ptr'])} +{hex(off)} direct+{hex(str_off)}: \"{name}\"")


def main():
    print("🎯 Targeted ECS Missile Query Probe")
    print("=" * 70)
    
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    
    print(f"[+] PID: {pid}, Base: {hex(base_addr)}")
    
    # Step 1: Read ECS Manager
    manager_ptr = read_ptr(scanner, base_addr + ALLLISTDATA_OFFSET)
    if not is_valid_ptr(manager_ptr):
        print(f"❌ AllListData at base+{hex(ALLLISTDATA_OFFSET)} = {hex(manager_ptr)} - INVALID!")
        print("   This offset may have changed. Re-run missile_global_scanner.py")
        return
    
    node_table = read_ptr(scanner, manager_ptr + 0x178)
    class_table = read_ptr(scanner, manager_ptr + 0x5E8)
    
    print(f"\n✅ ECS Manager: {hex(manager_ptr)}")
    print(f"   node_table:  {hex(node_table)}")
    print(f"   class_table: {hex(class_table)}")
    
    if not (is_valid_ptr(node_table) and is_valid_ptr(class_table)):
        print("❌ Invalid tables!")
        return
    
    # Step 2: Try each rocket selector candidate
    best_entities = None
    best_selector = 0
    
    for sel in ROCKET_SELECTORS_TO_TRY:
        entities = dump_ecs_query(scanner, class_table, node_table, sel)
        if entities:
            alive = sum(1 for e in entities if e["alive"] == 1)
            print(f"  → sel={sel}: {len(entities)} total, {alive} alive")
            if best_entities is None or len(entities) > len(best_entities):
                best_entities = entities
                best_selector = sel
    
    if not best_entities:
        print("\n❌ ไม่เจอ entities จาก selector ที่ลอง!")
        print("   ลองรันในเกมที่มี missile/rocket กำลังบินอยู่")
        return
    
    print(f"\n🏆 Best selector: {best_selector} ({len(best_entities)} entities)")
    
    # Step 3: Probe internal offsets  
    probe_rocket_offsets(scanner, best_entities)
    
    # Step 4: Full hex dump of first alive entity
    alive_list = [e for e in best_entities if e["alive"] == 1]
    if alive_list:
        e = alive_list[0]
        print(f"\n\n{'=' * 70}")
        print(f"📋 Hex dump of first alive entity at {hex(e['ptr'])}")
        print(f"{'=' * 70}")
        
        for chunk_start in range(0, 0x300, 0x40):
            data = scanner.read_mem(e["ptr"] + chunk_start, 0x40)
            if not data:
                continue
            hex_str = " ".join(f"{b:02x}" for b in data)
            # Also interpret as floats
            floats = []
            for fi in range(0, len(data) - 3, 4):
                f_val = struct.unpack_from("<f", data, fi)[0]
                if abs(f_val) > 0.001 and abs(f_val) < 100000 and not (abs(f_val) > 1e10):
                    floats.append(f"+{hex(chunk_start + fi)}={f_val:.2f}")
            
            print(f"  +{hex(chunk_start):>6s}: {hex_str}")
            if floats:
                print(f"          floats: {', '.join(floats[:6])}")
    
    # Summary
    print(f"\n\n{'=' * 70}")
    print("📋 SUMMARY - Add to mul.py:")
    print(f"{'=' * 70}")
    print(f"DAT_ALLLISTDATA = {hex(ALLLISTDATA_OFFSET + GHIDRA_BASE)}")
    print(f"ALLLISTDATA_OFFSET = {hex(ALLLISTDATA_OFFSET)}")
    print(f"# Rocket query selector: {best_selector}")


if __name__ == "__main__":
    main()
