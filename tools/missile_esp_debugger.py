#!/usr/bin/env python3
"""
🔍 Missile ESP Debugger & Inspector
Diagnostic tool to verify why missile.py or radar_overlay.py is missing rockets.
Compares:
  1. missile_starned_dumper logic
  2. src/utils/missile.py (MissileScanner) logic
  3. Overlay W2S projection for found rockets

Usage:
  sudo python3 tools/missile_esp_debugger.py
"""

import sys
import os
import time
import struct
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address
from src.utils.mul import (
    get_cgame_base, get_view_matrix, get_local_team, get_unit_pos,
    world_to_screen, GHIDRA_BASE
)
from tools.missile_starned_dumper import brute_force_entries as dumper_brute_force, rp

def main():
    print("🔍 MISSILE ESP DEBUGGER & DIAGNOSTIC TOOL")
    print("=" * 70)
    
    pid = get_game_pid()
    base = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    print(f"[+] Game PID: {pid}, Base: {hex(base)}")
    
    cgame_base = get_cgame_base(scanner, base)
    print(f"[+] CGame Base: {hex(cgame_base)}")
    
    view_matrix = get_view_matrix(scanner, cgame_base) if cgame_base else None
    print(f"[+] View Matrix: {'✅ OK' if view_matrix else '❌ Unreadable'}")
    
    my_unit, my_team = get_local_team(scanner, base)
    my_pos = get_unit_pos(scanner, my_unit) if my_unit else None
    print(f"[+] My Unit: {hex(my_unit)} Pos: {my_pos}")
    
    # ----------------------------------------------------------------
    # TEST 1: Run dumper brute-force logic
    # ----------------------------------------------------------------
    print("\n" + "=" * 70)
    print("📊 TEST 1: dumper brute-force scan (reference)")
    print("=" * 70)
    from src.utils.missile import MissileScanner
    from tools.missile_starned_dumper import OFF_ECS_MANAGER, OFF_ECS_NODE_TABLE
    mgr = rp(scanner, base + OFF_ECS_MANAGER)
    node_t = rp(scanner, mgr + OFF_ECS_NODE_TABLE) if mgr else 0
    
    dumper_rockets = []
    if node_t:
        dumper_rockets = dumper_brute_force(scanner, node_t, max_entries=5000)
    print(f"👉 Dumper found: {len(dumper_rockets)} rockets")
    for idx, r in enumerate(dumper_rockets):
        print(f"   [{idx}] ptr={hex(r['ptr'])} pos={r['pos']} vel={r['vel']} spd={r['speed']:.1f}m/s entry={r.get('entry')} layout={r.get('layout')}")
    
    # ----------------------------------------------------------------
    # TEST 2: Run src/utils/missile.py (MissileScanner)
    # ----------------------------------------------------------------
    print("\n" + "=" * 70)
    print("📊 TEST 2: src/utils/missile.py (MissileScanner module)")
    print("=" * 70)
    ms = MissileScanner()
    missile_module_rockets = ms.scan(scanner, base)
    if missile_module_rockets is None:
        time.sleep(0.06)
        missile_module_rockets = ms.scan(scanner, base)
    
    print(f"👉 MissileScanner found: {len(missile_module_rockets or [])} rockets")
    if missile_module_rockets:
        for idx, m in enumerate(missile_module_rockets):
            print(f"   [{idx}] ptr={hex(m.ptr)} pos={m.pos} vel={m.vel} spd={m.speed:.1f}m/s entry={m.entry_idx} name='{m.name}'")
    
    # ----------------------------------------------------------------
    # TEST 3: World-to-Screen Projection Check
    # ----------------------------------------------------------------
    print("\n" + "=" * 70)
    print("📊 TEST 3: Screen Projection (W2S) & Overlay Filters")
    print("=" * 70)
    screen_w, screen_h = 1920, 1080
    
    target_rockets = missile_module_rockets if missile_module_rockets else [
        type('M', (), {'ptr': r['ptr'], 'pos': r['pos'], 'vel': r['vel'], 'speed': r['speed'], 'name': r.get('name','')})() for r in dumper_rockets
    ]
    
    if not target_rockets:
        print("⚠️  No rockets available to project!")
    else:
        for idx, m in enumerate(target_rockets):
            pos = m.pos
            w2s = world_to_screen(view_matrix, pos[0], pos[1], pos[2], screen_w, screen_h) if view_matrix else None
            
            dist = math.sqrt(sum((pos[i] - (my_pos[i] if my_pos else 0))**2 for i in range(3))) if my_pos else 0
            
            print(f"🚀 Rocket #{idx} at {pos}:")
            print(f"   Dist to me: {dist:.1f}m ({dist/1000.0:.2f}km)")
            if w2s:
                sx, sy, sw = w2s
                in_screen = (0 <= sx <= screen_w and 0 <= sy <= screen_h)
                print(f"   Screen coords: ({sx:.1f}, {sy:.1f}), w={sw:.2f} -> {'📺 ON SCREEN' if in_screen else '📱 OFF SCREEN'}")
            else:
                print("   Screen coords: ❌ BEHIND CAMERA / UNPROJECTABLE")

if __name__ == "__main__":
    main()
