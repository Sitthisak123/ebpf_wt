# ======================================================================
# 🚀 Missile Dumper v2 (Pure Direct Offset 0 Scanner)
# ======================================================================
# สแกนตรงจาก storage offset 0 (0..350 entries)
# ตรวจจับขีปนาวุธเฉพาะเลย์เอาต์ starned (0x23c, 0x258) 100%
# ======================================================================

import sys
import os
import struct
import math
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_pid, get_game_base_address, init_dynamic_offsets
import src.utils.mul as mul

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
        getattr(mul, 'OFF_RKT_GUIDANCE', 0x680),
        getattr(mul, 'OFF_RKT_ENTITY_ID', 0x40),
        getattr(mul, 'OFF_RKT_PROPS', 0x710),
    ),
]


def rp(sc, a):
    d = sc.read_mem(a, 8)
    return struct.unpack("<Q", d)[0] if d and len(d) >= 8 else 0

def r8(sc, a):
    d = sc.read_mem(a, 1)
    return d[0] if d and len(d) >= 1 else 0

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


def check_ptr_is_rocket(sc, ptr):
    """ตรวจสอบว่า ptr นี้เป็นจรวด/ขีปนาวุธจริงที่กำลังบินอยู่หรือไม่"""
    try:
        header = sc.read_mem(ptr, 0x750)
        if not header or len(header) < 0x2c0:
            return None
        
        # 1. ตรวจสอบชื่อ Blk ของอาวุธจาก Props pointers (+0x700 / +0x6c8 -> +0x50, +0x28, +0x58)
        found_wep = ""
        for off in [getattr(mul, 'OFF_RKT_PROPS', 0x710), 0x710, 0x700, 0x6c8, 0x690, 0x6a0, 0x620]:
            if len(header) >= off + 8:
                prp = struct.unpack_from("<Q", header, off)[0]
                if is_valid_ptr(prp):
                    for poff in (0x28, 0x50, 0x58, 0x10):
                        raw_np = sc.read_mem(prp + poff, 8)
                        if raw_np and len(raw_np) == 8:
                            np = struct.unpack("<Q", raw_np)[0]
                            if is_valid_ptr(np):
                                s = sc.read_mem(np, 64)
                                if s:
                                    raw_str = s.split(b"\x00")[0].decode("utf-8", errors="ignore").strip()
                                    # 🚫 ตรวจพบว่าเป็น Flare / Chaff ให้คัดทิ้งทันที
                                    if any(ign in raw_str.lower() for ign in ("flare", "chaff")):
                                        return None
                                    if raw_str and (".blk" in raw_str.lower() or any(k in raw_str.lower() for k in ("missile", "rocket", "aim", "sam", "agm", "r_", "aam"))):
                                        found_wep = raw_str.split("/")[-1].split("\\")[-1]
                                        break
                    if found_wep:
                        break
        
        # ตรวจสอบ Component Weapon pointers (+0x420, +0x440)
        if not found_wep:
            for off in (0x420, 0x440):
                if len(header) >= off + 8:
                    comp_p = struct.unpack_from("<Q", header, off)[0]
                    if is_valid_ptr(comp_p):
                        s = sc.read_mem(comp_p + 0x08, 48)
                        if s:
                            raw_str = s.split(b"\x00")[0].split(b"*")[0].decode("utf-8", errors="ignore").strip()
                            if any(ign in raw_str.lower() for ign in ("flare", "chaff")):
                                return None
                            if any(k in s for k in (b"missile", b"rocket", b"sam", b"aim", b"agm", b"r_")):
                                if raw_str:
                                    found_wep = raw_str + ".blk"
                                    break
        
        # ตรวจสอบ Raw Header strings ถ้ายังไม่เจอ
        if not found_wep:
            for off in [0x230, 0x240, 0x380]:
                if len(header) >= off + 40:
                    s = header[off:off+40]
                    if b"aim_" in s or b"rocket" in s or b"missile" in s or b".blk" in s:
                        found_wep = s.split(b"\x00")[0].decode("utf-8", errors="ignore")
                        break
        
        # 2. ตรวจสอบพิกัดและความเร็วตาม Layout Sets
        for set_name, pos_off, vel_off, own_off, st_off, guid_off, eid_off, props_off in OFFSET_SETS:
            if len(header) < pos_off + 12 or len(header) < vel_off + 12:
                continue
            pos = struct.unpack_from("<fff", header, pos_off)
            vel = struct.unpack_from("<fff", header, vel_off)
            
            is_ok, speed = is_valid_missile_motion(pos, vel)
            if not is_ok:
                continue
            
            # Note: 0x420 is flight timer/component pointer, NOT a detonation boolean flag.
            if set_name == "starned":
                phase = struct.unpack_from("<I", header, getattr(mul, 'OFF_RKT_PHASE', 0x498))[0] if len(header) >= 0x498 + 4 else 0
                detonated = struct.unpack_from("<I", header, getattr(mul, 'OFF_RKT_DETONATED', 0x420))[0] if len(header) >= 0x420 + 4 else 0
            
            # กรอง flares / chaff
            if found_wep and any(ign in found_wep.lower() for ign in ["flare", "chaff"]):
                return None
            
            owner = struct.unpack_from("<Q", header, own_off)[0] if len(header) >= own_off + 8 else 0
            if not owner and len(header) >= 0x48:
                owner = struct.unpack_from("<Q", header, 0x40)[0]
            state = header[st_off] if len(header) > st_off else 0
            guid  = struct.unpack_from("<Q", header, guid_off)[0] if len(header) >= guid_off + 8 else 0
            if not guid:
                for goff in (0x680, 0x670, 0x638, 0x648, 0x6C8, 0x698):
                    if len(header) >= goff + 8:
                        g_cand = struct.unpack_from("<Q", header, goff)[0]
                        if is_valid_ptr(g_cand) and (g_cand & 7 == 0):
                            guid = g_cand
                            break
            eid   = struct.unpack_from("<I", header, eid_off)[0] if len(header) >= eid_off + 4 else 0
            if not eid and len(header) >= 0x34:
                eid = struct.unpack_from("<I", header, 0x30)[0]

            # 🛡️ VALIDATION: Filter out fake/garbage entities and non-rocket objects
            # 1. State: Allow in-flight states (0..32, including post-burnout coast/terminal guidance state 11)
            if state > 32:
                continue

            # 2. Entity ID: Active projectile IDs are normal positive integers (< 50,000,000).
            if eid == 0 or eid > 50_000_000:
                continue

            # 3. Owner: If valid pointer, mask out tag bit (u_ptr | 1)
            owner_unit = (owner & ~1) if owner else 0
            if owner_unit != 0 and not (is_valid_ptr(owner_unit) and (owner_unit & 0x7 == 0)):
                owner = 0
                owner_unit = 0

            # 4. Guidance: Validate pointer alignment
            if guid != 0 and not (is_valid_ptr(guid) and (guid & 0x7 == 0)):
                guid = 0

            # ถ้ายังไม่มีชื่อ blk ให้ fallback เป็น sam_missile.blk หรือ missile.blk
            if not found_wep:
                if is_valid_ptr(guid):
                    found_wep = "sam_missile.blk"
                elif speed > 250.0:
                    found_wep = "missile.blk"
                else:
                    continue
            
            return {
                "ptr": ptr,
                "set": set_name,
                "pos": pos,
                "vel": vel,
                "speed": speed,
                "owner": owner,
                "state": state,
                "eid": eid,
                "guid": guid,
                "name": found_wep,
            }
    except Exception:
        pass
    return None


def brute_force_entries(sc, node_table, max_entries=350, base=0):
    """
    Scans active missiles from both OFF_PROJ_LIST (if base provided) and ECS node_table (0..max_entries).
    """
    all_rockets = []
    seen_ptrs = set()

    # 1. Check OFF_PROJ_LIST if base address is provided
    if base:
        proj_list_off = getattr(mul, "OFF_PROJ_LIST", 0xac02ab8)
        table_ptr = rp(sc, base + proj_list_off)
        if is_valid_ptr(table_ptr):
            cnt_cap = sc.read_mem(base + proj_list_off + 8, 8)
            if cnt_cap and len(cnt_cap) == 8:
                count, cap = struct.unpack("<II", cnt_cap)
                scan_slots = min(max(cap, count, 128), 256)
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
                                info["entry"] = i
                                seen_ptrs.add(ent_ptr)
                                all_rockets.append(info)

    # 2. Check ECS node_table
    if node_table and is_valid_ptr(node_table):
        table_bytes = sc.read_mem(node_table, max_entries * 0x20)
        if table_bytes and len(table_bytes) >= 0x20:
            num_entries = len(table_bytes) // 0x20
            for i in range(num_entries):
                data = table_bytes[i * 0x20 : (i + 1) * 0x20]
                if all(b == 0 for b in data):
                    continue
                
                storage = struct.unpack_from("<Q", data, 0)[0]
                if not is_valid_ptr(storage) or (storage & 0x7 != 0):
                    continue
                
                count = struct.unpack_from("<I", data, 8)[0]
                capacity = struct.unpack_from("<I", data, 0x14)[0]
                if count == 0 or capacity == 0 or count > capacity or capacity > 8192:
                    continue
                
                read_n = min(max(capacity * 8, 200), 16384)
                bulk0 = sc.read_mem(storage, read_n * 8)
                if bulk0 and len(bulk0) >= 8:
                    for idx in range(len(bulk0) // 8):
                        ptr = struct.unpack_from("<Q", bulk0, idx * 8)[0]
                        if is_valid_ptr(ptr) and (ptr & 0x7 == 0) and ptr not in seen_ptrs:
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
    init_dynamic_offsets(sc, base)
    
    # Read ECS Manager
    ecs_mgr_off = getattr(mul, 'OFF_ECS_MANAGER', 0xb0e29b8)
    ecs_mgr = rp(sc, base + ecs_mgr_off)
    if not is_valid_ptr(ecs_mgr):
        for alt_off in (0xb0e2b98, 0xb0e29b8, 0x8225aa0):
            test_m = rp(sc, base + alt_off)
            if is_valid_ptr(test_m) and is_valid_ptr(rp(sc, test_m + getattr(mul, 'OFF_ECS_NODE_TABLE', 0x178))):
                ecs_mgr = test_m
                ecs_mgr_off = alt_off
                break
    
    if not is_valid_ptr(ecs_mgr):
        print(f"⚠️ อ่าน ECS Manager ล้มเหลวที่ {hex(base + ecs_mgr_off)}, จะสแกนผ่าน Projectile Table เป็นหลัก")
        node_t = 0
        class_t = 0
    else:
        node_t = rp(sc, ecs_mgr + getattr(mul, 'OFF_ECS_NODE_TABLE', 0x178))
        class_t = rp(sc, ecs_mgr + getattr(mul, 'OFF_ECS_CLASS_TABLE', 0x5E8))
        print(f"✅ ECS Manager: {hex(ecs_mgr)}")
        print(f"   node_table:  {hex(node_t)}")
        print(f"   class_table: {hex(class_t)}")
    
    # Build unit_map to resolve target_id and owner
    unit_map = {}
    try:
        cgame_base = mul.get_cgame_base(sc, base)
        my_unit, _ = mul.get_local_team(sc, base)
        all_u = mul.get_all_units(sc, cgame_base)
        for u_ptr, is_air in all_u:
            raw = sc.read_mem(u_ptr + 0x08, 2)
            uid = struct.unpack("<H", raw)[0] if raw and len(raw) == 2 else -1
            prof = mul.get_unit_filter_profile(sc, u_ptr)
            dna = mul.get_unit_detailed_dna(sc, u_ptr) or {}
            uname = dna.get("short_name") or prof.get("short_name") or prof.get("display_name") or "Unit"
            if u_ptr == my_unit:
                uname += " (YOU)"
            if uid > 0:
                unit_map[uid] = (u_ptr, uname)
            unit_map[u_ptr] = (u_ptr, uname)
    except Exception:
        pass

    # Run Pure Direct Offset 0 Batch Entry Scanner
    t0 = time.time()
    unique = brute_force_entries(sc, node_t, 350, base=base)
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
    else:
        for idx, r in enumerate(unique):
            owner_u = r['owner'] & ~1
            owner_info = f" [{unit_map[owner_u][1]}]" if owner_u in unit_map else ""
            owner_str = f"{hex(r['owner'])} ✅{owner_info}" if 0 < r['owner'] <= 0xFFFFFFFFFFFFFFFF else f"{hex(r['owner'])} ❌"
            guid_str = f"{hex(r['guid'])}" if r['guid'] != 0 else "none (unguided)"
            if r['guid'] != 0 and is_valid_ptr(r['guid']):
                g_lock = r8(sc, r['guid'] + getattr(mul, 'OFF_GUID_LOCKED', 0x4C))
                g_trk = r8(sc, r['guid'] + getattr(mul, 'OFF_GUID_TRACKING', 0x4D))
                g_tgt_raw = sc.read_mem(r['guid'] + getattr(mul, 'OFF_GUID_TARGET_ID', 0x84), 2)
                g_tgt = struct.unpack("<H", g_tgt_raw)[0] if g_tgt_raw and len(g_tgt_raw) == 2 else 0
                if g_tgt == 0xFFFF:
                    g_tgt = 0
                elif g_tgt not in (65280,):
                    if g_tgt <= 0 or g_tgt >= 20000:
                        fb_raw = sc.read_mem(r['guid'] + 0x8C, 2)
                        fb = struct.unpack("<H", fb_raw)[0] if fb_raw and len(fb_raw) == 2 else 0
                        g_tgt = fb if (0 < fb < 20000 and fb != 65280) else 0

                is_sam_wep = any(k in (r['name'] or '').lower() for k in ("sam", "mim146", "mim-146", "roland", "vt1", "vt-1", "pantsir", "9m311", "9m331", "tor", "strela", "tunguska", "adats"))
                if g_tgt == 65280 or (is_sam_wep and g_tgt == 0):
                    tgt_info = " (📡 SACLOS / Beam-Riding SAM - No Seeker Head)"
                elif g_tgt in unit_map:
                    tgt_info = f" (🎯 {unit_map[g_tgt][1]})"
                elif 0 < g_tgt < 20000:
                    tgt_info = f" (id={g_tgt})"
                else:
                    tgt_info = " (no target / beam-rider)" if is_sam_wep else ""
                guid_str += f" locked={g_lock} tracking={g_trk} target_id={g_tgt}{tgt_info}"
            
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
            fresh = brute_force_entries(sc, node_t, 350, base=base)
            if fresh:
                parts = []
                for r in fresh[:10]:
                    parts.append(f"({r['pos'][0]:.0f},{r['pos'][1]:.0f},{r['pos'][2]:.0f}) {r['speed']:.0f}m/s")
                print(f"\r  🚀 Total Active: {len(fresh)} | " + " | ".join(parts[:5]) + "    ", end="", flush=True)
            else:
                print(f"\r  ⏳ Watching live memory... [Active: 0]    ", end="", flush=True)
    except KeyboardInterrupt:
        print("\n\n👋 Stopped live monitor.")


if __name__ == "__main__":
    main()

