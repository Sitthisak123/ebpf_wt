#!/usr/bin/env python3
"""
🚀 Missile System Global Address Scanner
หา global addresses สำหรับ ECS Query System (missile/rocket/bomb)

วิธีใช้:
  sudo python3 tools/missile_global_scanner.py

ต้องเปิดเกม War Thunder ก่อนรัน
"""

import struct
import sys
import os
import subprocess
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address
from src.utils.mul import is_valid_ptr, GHIDRA_BASE

# ====================================================================
# Configuration
# ====================================================================
BINARY_PATH = "/home/xda-7/MyGames/WarThunder/linux64/aces"

# Known offsets INSIDE the ECS manager (stable across versions)
ECS_NODE_TABLE_OFF  = 0x178   # dataTable
ECS_CLASS_TABLE_OFF = 0x5E8   # indexTable

# Scan range inside the binary's .bss / .data sections 
# (global pointers are typically at high offsets from base)
SCAN_RANGE_START = 0x0800_0000  # ~134 MB from base
SCAN_RANGE_END   = 0x0C00_0000  # ~201 MB from base
SCAN_STEP        = 8            # 8-byte aligned

# ====================================================================
# Helpers
# ====================================================================
def read_ptr(scanner, addr):
    data = scanner.read_mem(addr, 8)
    if not data or len(data) < 8:
        return 0
    return struct.unpack("<Q", data)[0]

def read_u32(scanner, addr):
    data = scanner.read_mem(addr, 4)
    if not data or len(data) < 4:
        return 0
    return struct.unpack("<I", data)[0]

def read_u16(scanner, addr):
    data = scanner.read_mem(addr, 2)
    if not data or len(data) < 2:
        return 0
    return struct.unpack("<H", data)[0]

def read_u8(scanner, addr):
    data = scanner.read_mem(addr, 1)
    if not data or len(data) < 1:
        return 0
    return data[0]

# ====================================================================
# Phase 1: Find g_AllListData (Entity Manager / ECS Manager)
# ====================================================================
def scan_for_alllistdata(scanner, base_addr):
    """
    Scan the binary's global data section for a pointer that,
    when dereferenced, contains valid sub-pointers at +0x178 and +0x5E8.
    
    Logic:
    - g_AllListData is a global pointer to the ECS manager
    - manager + 0x178 = node_table (dataTable) -> valid pointer
    - manager + 0x5E8 = class_table (indexTable) -> valid pointer
    """
    print("\n" + "=" * 70)
    print("🔍 Phase 1: Scanning for g_AllListData (ECS Manager)")
    print("=" * 70)
    
    candidates = []
    total = (SCAN_RANGE_END - SCAN_RANGE_START) // SCAN_STEP
    checked = 0
    
    for off in range(SCAN_RANGE_START, SCAN_RANGE_END, SCAN_STEP):
        checked += 1
        if checked % 100000 == 0:
            pct = (checked / total) * 100
            print(f"  [{pct:.1f}%] Checked {checked}/{total} addresses...", end="\r")
        
        addr = base_addr + off
        ptr = read_ptr(scanner, addr)
        if not is_valid_ptr(ptr):
            continue
        
        # Check if ptr + 0x178 and ptr + 0x5E8 are valid pointers
        node_table = read_ptr(scanner, ptr + ECS_NODE_TABLE_OFF)
        class_table = read_ptr(scanner, ptr + ECS_CLASS_TABLE_OFF)
        
        if not (is_valid_ptr(node_table) and is_valid_ptr(class_table)):
            continue
        
        # node_table and class_table MUST be different (they're separate arrays)
        if node_table == class_table:
            continue
        
        # Both should be heap addresses (large values, > 1MB typically)
        if node_table < 0x100000 or class_table < 0x100000:
            continue
        
        # The manager itself should be a reasonable heap object
        # Check that there's more than just these two valid pointers
        # by also checking an intermediate offset
        test_ptr1 = read_ptr(scanner, ptr + 0x100)
        test_ptr2 = read_ptr(scanner, ptr + 0x200)
        if not (is_valid_ptr(test_ptr1) or is_valid_ptr(test_ptr2)):
            continue
        
        # Extra validation: class_table should have reasonable data
        # Try reading a chunk of the class table - it should contain structured data
        test_data = scanner.read_mem(class_table, 256)
        if not test_data:
            continue
        
        # Also check that node_table has reasonable data
        test_data2 = scanner.read_mem(node_table, 256)
        if not test_data2:
            continue
        
        # Validate class table: entries are 64 bytes each (1 << 6)
        # First few entries might have small num_required/num_optional values
        valid_entries = 0
        for entry_idx in range(4):
            entry_off = entry_idx * 64
            if entry_off + 4 > len(test_data):
                break
            nr = test_data[entry_off]
            no = test_data[entry_off + 1]
            ns = struct.unpack_from("<H", test_data, entry_off + 2)[0]
            if 0 <= nr <= 16 and 0 <= no <= 16 and ns <= 500:
                valid_entries += 1
        
        if valid_entries < 2:
            continue
        
        ghidra_addr = off + GHIDRA_BASE
        print(f"\n  🎯 Candidate: base+{hex(off)} (Ghidra: {hex(ghidra_addr)})")
        print(f"     Manager ptr:   {hex(ptr)}")
        print(f"     node_table:    {hex(node_table)}")
        print(f"     class_table:   {hex(class_table)}")
        candidates.append((off, ptr, node_table, class_table))
    
    print(f"\n\n  ✅ Found {len(candidates)} candidates for g_AllListData")
    return candidates


# ====================================================================
# Phase 2: Find rocket/bomb query IDs
# ====================================================================
def scan_for_query_ids(scanner, base_addr, manager_ptr, class_table):
    """
    Scan for small uint32 values that, when used as ECS query selectors:
      selector = value & 0xFFFFFF
      indexData = class_table + (selector << 6)
    
    ...produce valid ECS query metadata.
    
    Valid query metadata has:
    - byte[0] = num_required_components (1-8)
    - byte[1] = num_optional_components (0-8)  
    - short[1] = num_sublists (1-100)
    """
    print("\n" + "=" * 70)
    print("🔍 Phase 2: Scanning for Query IDs (rocket/bomb/bullet)")
    print("=" * 70)
    
    candidates = []
    total = (SCAN_RANGE_END - SCAN_RANGE_START) // SCAN_STEP
    checked = 0
    
    for off in range(SCAN_RANGE_START, SCAN_RANGE_END, SCAN_STEP):
        checked += 1
        if checked % 100000 == 0:
            pct = (checked / total) * 100
            print(f"  [{pct:.1f}%] Checked {checked}/{total} addresses...", end="\r")
        
        addr = base_addr + off
        raw_val = read_u32(scanner, addr)
        
        # Query IDs are small positive integers masked with 0xFFFFFF
        selector = raw_val & 0xFFFFFF
        if selector == 0 or selector > 0xFFFF:
            continue
        
        # Try to use this as a query selector
        index_data_addr = class_table + (selector << 6)
        
        # Read the query metadata
        meta = scanner.read_mem(index_data_addr, 32)
        if not meta or len(meta) < 32:
            continue
        
        num_required = meta[0]
        num_optional = meta[1]
        num_sublists = struct.unpack_from("<H", meta, 2)[0]
        
        # Validate: reasonable component counts
        if not (1 <= num_required <= 8):
            continue
        if not (0 <= num_optional <= 8):
            continue
        if not (1 <= num_sublists <= 200):
            continue
        
        total_comps = num_required + num_optional
        
        # Further validate: check sublist offsets
        if num_sublists <= 9:
            sublist_base = index_data_addr + 0x04
        else:
            sublist_base = read_ptr(scanner, index_data_addr + 0x08)
            if not is_valid_ptr(sublist_base):
                continue
        
        # Read first sublist offset
        first_sublist_off = read_u32(scanner, sublist_base)
        if first_sublist_off > 0x100000:  # Reasonable range
            continue
        
        ghidra_addr = off + GHIDRA_BASE
        
        # Check if the adjacent 4 bytes are 0 (typical for query id globals)
        next_val = read_u32(scanner, addr + 4)
        
        candidates.append({
            "offset": off,
            "ghidra": ghidra_addr,
            "raw_val": raw_val,
            "selector": selector,
            "num_required": num_required,
            "num_optional": num_optional, 
            "num_sublists": num_sublists,
            "total_comps": total_comps,
            "next_val": next_val,
        })
    
    print(f"\n\n  ✅ Found {len(candidates)} query ID candidates")
    
    # Group by (num_required, num_optional, num_sublists)
    groups = {}
    for c in candidates:
        key = (c["num_required"], c["num_optional"], c["num_sublists"])
        groups.setdefault(key, []).append(c)
    
    print(f"\n  📊 Grouped into {len(groups)} distinct query shapes:")
    for key, items in sorted(groups.items(), key=lambda x: x[1][0]["num_sublists"], reverse=True):
        print(f"\n  Shape: req={key[0]}, opt={key[1]}, sublists={key[2]} ({len(items)} candidates)")
        # Rockets typically have many sublists (30+), bombs fewer
        for item in items[:5]:
            print(f"    base+{hex(item['offset'])} (Ghidra: {hex(item['ghidra'])}) "
                  f"sel={item['selector']} raw={hex(item['raw_val'])} "
                  f"next={hex(item['next_val'])}")
    
    return candidates, groups


# ====================================================================
# Phase 3: Validate a candidate by trying to read actual rockets
# ====================================================================
def validate_rocket_query(scanner, base_addr, manager_ptr, manager_off,
                          query_off, class_table, node_table):
    """
    Try to use a query ID candidate to actually enumerate rockets.
    """
    raw_val = read_u32(scanner, base_addr + query_off)
    selector = raw_val & 0xFFFFFF
    
    index_data_addr = class_table + (selector << 6)
    meta = scanner.read_mem(index_data_addr, 32)
    if not meta:
        return False, 0
    
    num_required = meta[0]
    num_optional = meta[1]
    num_sublists = struct.unpack_from("<H", meta, 2)[0]
    total_comps = num_required + num_optional
    
    # Get sublist offsets
    if num_sublists <= 9:
        sublist_base = index_data_addr + 0x04
    else:
        sublist_base = read_ptr(scanner, index_data_addr + 0x08)
        if not is_valid_ptr(sublist_base):
            return False, 0
    
    # Get component offset matrix
    if total_comps <= 16:
        comp_offsets_base = index_data_addr + 0x18
    else:
        comp_offsets_base = read_ptr(scanner, index_data_addr + 0x18)
        if not is_valid_ptr(comp_offsets_base):
            return False, 0
    
    total_entities = 0
    valid_entities = 0
    
    for sl in range(min(num_sublists, 100)):
        list_offset = read_u32(scanner, sublist_base + sl * 4)
        list_data_addr = node_table + list_offset * 0x20
        
        # Read list descriptor
        desc = scanner.read_mem(list_data_addr, 0x20)
        if not desc:
            continue
        
        # Try to find count and storage from the descriptor
        # Typical layout: [storage_ptr(8)] [???] [count(4)]
        storage = struct.unpack_from("<Q", desc, 0)[0]
        count = struct.unpack_from("<I", desc, 0x10)[0]
        
        if count == 0 or count > 10000 or not is_valid_ptr(storage):
            continue
        
        total_entities += count
        
        # Read component offsets (uint16 each)
        comp_off_data = scanner.read_mem(comp_offsets_base + sl * total_comps * 2, 
                                          total_comps * 2)
        if not comp_off_data or len(comp_off_data) < total_comps * 2:
            continue
        
        # comp[0] = rocket pointer column, comp[1] = alive byte column
        rocket_col_off = struct.unpack_from("<H", comp_off_data, 0)[0]
        alive_col_off = struct.unpack_from("<H", comp_off_data, 2)[0] if num_required >= 2 else 0
        
        # Try reading a few entities
        for i in range(min(count, 10)):
            rocket_ptr = read_ptr(scanner, storage + (rocket_col_off << 3) + i * 8)
            if is_valid_ptr(rocket_ptr):
                valid_entities += 1
    
    return valid_entities > 0, total_entities


# ====================================================================
# Main
# ====================================================================
def main():
    print("🚀 Missile System Global Address Scanner")
    print("=" * 70)
    
    # Connect to game
    pid = get_game_pid()
    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    
    print(f"[+] War Thunder PID: {pid}")
    print(f"[+] Base Address: {hex(base_addr)}")
    print(f"[+] GHIDRA_BASE: {hex(GHIDRA_BASE)}")
    
    # Phase 1: Find g_AllListData
    alllistdata_candidates = scan_for_alllistdata(scanner, base_addr)
    
    if not alllistdata_candidates:
        print("\n❌ ไม่เจอ g_AllListData เลย! ลองขยาย SCAN_RANGE")
        return
    
    # Phase 2: For each alllistdata candidate, scan for query IDs
    for i, (manager_off, manager_ptr, node_table, class_table) in enumerate(alllistdata_candidates):
        print(f"\n\n{'=' * 70}")
        print(f"📌 Testing AllListData candidate #{i}: base+{hex(manager_off)}")
        print(f"{'=' * 70}")
        
        query_candidates, groups = scan_for_query_ids(
            scanner, base_addr, manager_ptr, class_table
        )
        
        # Look for rocket-like queries (many sublists, 2+ required components)
        rocket_candidates = []
        for key, items in groups.items():
            if key[2] >= 20 and key[0] >= 2:  # sublists >= 20, required >= 2
                rocket_candidates.extend(items)
        
        if rocket_candidates:
            print(f"\n\n🎯 Likely ROCKET query candidates ({len(rocket_candidates)}):")
            for c in rocket_candidates[:10]:
                print(f"  base+{hex(c['offset'])} (Ghidra: {hex(c['ghidra'])}) "
                      f"sublists={c['num_sublists']} req={c['num_required']}")
                
                # Try to validate
                ok, total = validate_rocket_query(
                    scanner, base_addr, manager_ptr, manager_off,
                    c["offset"], class_table, node_table
                )
                if ok:
                    print(f"    ✅ VALIDATED! Found entities (total_slots={total})")
                else:
                    print(f"    ⚠️  Not validated (total_slots={total})")
    
    # Summary
    print("\n\n" + "=" * 70)
    print("📋 SUMMARY")
    print("=" * 70)
    print("\nPaste these into mul.py:")
    for i, (off, ptr, nt, ct) in enumerate(alllistdata_candidates[:5]):
        ghidra = off + GHIDRA_BASE
        print(f"\n# Candidate #{i}:")
        print(f"DAT_ALLLISTDATA = {hex(ghidra)}  # base+{hex(off)}")
        print(f"ALLLISTDATA_OFFSET = DAT_ALLLISTDATA - GHIDRA_BASE  # = {hex(off)}")


if __name__ == "__main__":
    main()
