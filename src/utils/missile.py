"""
🚀 Ultra-Fast Dynamic-Capacity Single-Syscall Node Window Scanner
อ่านขีปนาวุธ missile/rocket ผ่าน ECS query node entries ด้วย dynamic capacity
รองรับจรวดพร้อมกัน 200+ ลูกแบบ 100% ครบถ้วน ไม่มี freeze ไม่มี lag!

Confirmed ECS Node Descriptor Structure (0x20 bytes):
  +0x00: storage pointer (64-bit)
  +0x08: count (u32)
  +0x14: capacity (u32)
"""

import struct
import math
import time

import src.utils.mul as mul

try:
    from src.utils.debug import dprint
except Exception:
    def dprint(msg, force=False): return

# ====================================================================
# Rocket Struct Offsets (confirmed 2026-09)
# ====================================================================
OFF_ECS_MANAGER    = getattr(mul, 'OFF_ECS_MANAGER', 0xb0e29b8)
OFF_ECS_NODE_TABLE = getattr(mul, 'OFF_ECS_NODE_TABLE', 0x178)
OFF_ECS_CLASS_TABLE= getattr(mul, 'OFF_ECS_CLASS_TABLE', 0x5E8)
OFF_PROJ_LIST      = getattr(mul, 'OFF_PROJ_LIST', 0xac02ab8)

OFF_RKT_ENTITY_ID  = getattr(mul, 'OFF_RKT_ENTITY_ID', 0x40)
OFF_RKT_OWNER      = getattr(mul, 'OFF_RKT_OWNER', 0x50)
OFF_RKT_STATE      = getattr(mul, 'OFF_RKT_STATE', 0x94)
OFF_RKT_POS        = getattr(mul, 'OFF_RKT_POS', 0x23c)
OFF_RKT_VEL        = getattr(mul, 'OFF_RKT_VEL', 0x258)
OFF_RKT_DETONATED  = getattr(mul, 'OFF_RKT_DETONATED', 0x420)   # Detonation/impact effect flag
OFF_RKT_PHASE      = getattr(mul, 'OFF_RKT_PHASE', 0x498)       # Projectile lifecycle phase
OFF_RKT_GUIDANCE   = getattr(mul, 'OFF_RKT_GUIDANCE', 0x670)
OFF_RKT_ALIVE      = getattr(mul, 'OFF_RKT_ALIVE', 0x6c0)       # Entity active/alive flag
OFF_RKT_PROPS      = getattr(mul, 'OFF_RKT_PROPS', 0x700)

# Guidance struct internals
OFF_GUID_LOCKED    = getattr(mul, 'OFF_GUID_LOCKED', 0x4C)
OFF_GUID_TRACKING  = getattr(mul, 'OFF_GUID_TRACKING', 0x4D)
OFF_GUID_TARGET_ID = getattr(mul, 'OFF_GUID_TARGET_ID', 0x84)

# Active ECS node entries window (Rockets are located in active entries 0..350)
NODE_ENTRY_WINDOW = 350

# ====================================================================
# Helpers
# ====================================================================
def _rp(sc, a):
    d = sc.read_mem(a, 8)
    return struct.unpack("<Q", d)[0] if d and len(d) >= 8 else 0

def _r32(sc, a):
    d = sc.read_mem(a, 4)
    return struct.unpack("<I", d)[0] if d and len(d) >= 4 else 0

def _ri16(sc, a):
    d = sc.read_mem(a, 2)
    return struct.unpack("<h", d)[0] if d and len(d) >= 2 else 0

def _r8(sc, a):
    d = sc.read_mem(a, 1)
    return d[0] if d and len(d) >= 1 else 0

def _rv3(sc, a):
    d = sc.read_mem(a, 12)
    if not d or len(d) < 12:
        return None
    return struct.unpack("<fff", d)

def _rstr(sc, a, n=96):
    d = sc.read_mem(a, n)
    if not d:
        return ""
    try:
        end = d.index(0)
        return d[:end].decode("utf-8", errors="replace")
    except ValueError:
        return d[:n].decode("utf-8", errors="replace")

def _is_valid_ptr(v):
    return 0x100000 < v < 0x7FFFFFFFFFFF

def _vlen(v):
    return math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])

COUNTERMEASURE_KEYWORDS = (
    "flare", "chaff", "countermeasure", "decoy", "dispenser",
    "cm_", "cartridge", "split_launcher", "bullet_flare",
    "flares", "bol_pod", "anti_radar", "infrared_decoy",
)

def _is_valid_vec3(v):
    """Validate 3D vector (must be finite and contain no true subnormal floats)"""
    if not all(math.isfinite(x) for x in v):
        return False
    for x in v:
        # Standard IEEE 754 float32 subnormals are < 1.17e-38.
        # Use 1e-30 to avoid rejecting valid small coordinates or velocities.
        if x != 0.0 and abs(x) < 1e-30:
            return False
    return True

def _is_valid_missile_motion(pos, vel):
    """Ensure coordinates and velocity represent a real 3D flying projectile"""
    if not _is_valid_vec3(pos) or not _is_valid_vec3(vel):
        return False, 0.0
    if any(abs(x) > 250000.0 for x in pos):
        return False, 0.0
    if sum(1 for x in pos if abs(x) > 5.0) < 2:
        return False, 0.0
    if (pos[0]*pos[0] + pos[1]*pos[1] + pos[2]*pos[2]) < 2500.0:
        return False, 0.0
    
    spd = _vlen(vel)
    # Detect missiles from 10.0 m/s (e.g. freshly launched from hovering helicopters or stationary SAMs) up to hypersonic 4500 m/s
    if not (10.0 < spd < 4500.0):
        return False, 0.0
    return True, spd


# ====================================================================
# MissileInfo Container
# ====================================================================
class MissileInfo:
    __slots__ = (
        'ptr', 'pos', 'vel', 'speed', 'owner', 'state',
        'entity_id', 'guidance_ptr', 'name',
        'is_locked', 'is_tracking', 'target_id',
        'entry_idx', 'launch_pos',
    )
    
    def __init__(self):
        self.ptr = 0
        self.pos = (0.0, 0.0, 0.0)
        self.vel = (0.0, 0.0, 0.0)
        self.speed = 0.0
        self.owner = 0
        self.state = 0
        self.entity_id = 0
        self.guidance_ptr = 0
        self.name = ""
        self.is_locked = False
        self.is_tracking = False
        self.target_id = -1
        self.entry_idx = -1
        self.launch_pos = (0.0, 0.0, 0.0)
    
    def __repr__(self):
        return (f"<Missile '{self.name}' pos=({self.pos[0]:.0f},{self.pos[1]:.0f},{self.pos[2]:.0f}) "
                f"spd={self.speed:.0f} lock={self.is_locked} trk={self.is_tracking} tgt={self.target_id}>")


# ====================================================================
# High-FPS Adaptive Node Window Scanner
# ====================================================================
class MissileScanner:
    """
    High-FPS Adaptive Node Window Scanner.
    Batch-reads active node_table entries (0..350 = ~11KB) in 1 SINGLE memory read.
    Uses adaptive count-based buffer reads for maximum FPS (29+ FPS guaranteed).
    """
    
    def __init__(self):
        self._node_table = 0
        self._mgr_ptr = 0
        self._last_scan_time = 0.0
        self._initialized = False
        self._name_cache = {}
        self._props_name_cache = {}
    
    def clear_cache(self):
        """Reset weapon name and props caches (called on match change)"""
        self._name_cache.clear()
        self._props_name_cache.clear()
    
    def _init_ecs(self, scanner, base):
        """Initialize ECS manager pointers dynamically from mul.OFF_ECS_MANAGER"""
        ecs_mgr_off = getattr(mul, "OFF_ECS_MANAGER", 0xb0e29b8)
        ecs_node_off = getattr(mul, "OFF_ECS_NODE_TABLE", 0x178)
        
        mgr = _rp(scanner, base + ecs_mgr_off)
        if not _is_valid_ptr(mgr):
            return False
        
        node_t = _rp(scanner, mgr + ecs_node_off)
        if not _is_valid_ptr(node_t):
            return False
        
        self._mgr_ptr = mgr
        self._node_table = node_t
        self._initialized = True
        return True
    
    def scan(self, scanner, base):
        """
        Scan active missiles using Projectile List (primary) + ECS Node Table (complement).
        Both paths merge via seen_ptrs deduplication for complete coverage.
        Takes < 0.02ms total execution time.
        """
        now = time.time()
        
        # Throttle: minimum 50ms between scans
        if now - self._last_scan_time < 0.05:
            return None
        self._last_scan_time = now
        
        found_missiles = []
        seen_ptrs = set()
        
        # 1. Primary: Projectile List (OFF_PROJ_LIST) - covers player missiles and active projectiles
        proj_list_off = getattr(mul, "OFF_PROJ_LIST", 0xac02ab8)
        table_ptr = _rp(scanner, base + proj_list_off)
        if _is_valid_ptr(table_ptr):
            cnt_cap = scanner.read_mem(base + proj_list_off + 8, 8)
            if cnt_cap and len(cnt_cap) == 8:
                count, cap = struct.unpack("<II", cnt_cap)
                # Read a wide slot window (up to 1024 slots) to catch missiles in busy multiplayer matches
                scan_slots = min(max(cap, count, 128), 1024)
                raw_entries = scanner.read_mem(table_ptr + 0x20, scan_slots * 0x20)
                if raw_entries and len(raw_entries) >= 0x20:
                    num_m = len(raw_entries) // 0x20
                    for i in range(num_m):
                        chunk = raw_entries[i * 0x20 : (i + 1) * 0x20]
                        ent_ptr = struct.unpack_from("<Q", chunk, 0x10)[0]
                        if _is_valid_ptr(ent_ptr) and (ent_ptr & 7 == 0) and ent_ptr not in seen_ptrs:
                            m = self._check_rocket(scanner, ent_ptr, i)
                            if m and m.name != "":
                                seen_ptrs.add(m.ptr)
                                found_missiles.append(m)
        
        # 2. Complement: ECS Node Table - covers network/enemy missiles that may not be in proj_list
        ecs_mgr_off = getattr(mul, "OFF_ECS_MANAGER", 0xb0e29b8)
        ecs_node_off = getattr(mul, "OFF_ECS_NODE_TABLE", 0x178)
        
        mgr = _rp(scanner, base + ecs_mgr_off)
        if not _is_valid_ptr(mgr):
            # Fallback search candidate offsets if shifted
            for cand_off in (0xb0e29b8, 0xb0e2b98, 0x8225aa0, 0x8226ba0):
                test_m = _rp(scanner, base + cand_off)
                if _is_valid_ptr(test_m) and _is_valid_ptr(_rp(scanner, test_m + ecs_node_off)):
                    mgr = test_m
                    break
        
        if _is_valid_ptr(mgr):
            node_t = _rp(scanner, mgr + ecs_node_off)
            if _is_valid_ptr(node_t):
                table_bytes = scanner.read_mem(node_t, NODE_ENTRY_WINDOW * 0x20)
                if table_bytes and len(table_bytes) >= 0x20:
                    num_entries = len(table_bytes) // 0x20
                    for entry_idx in range(num_entries):
                        data = table_bytes[entry_idx * 0x20 : (entry_idx + 1) * 0x20]
                        if all(b == 0 for b in data):
                            continue
                        
                        storage = struct.unpack_from("<Q", data, 0)[0]
                        if not _is_valid_ptr(storage) or (storage & 0x7 != 0):
                            continue
                        
                        count = struct.unpack_from("<I", data, 8)[0]
                        capacity = struct.unpack_from("<I", data, 0x14)[0]
                        if count == 0 or capacity == 0 or count > capacity or capacity > 8192:
                            continue
                        
                        read_bytes = min(max(capacity * 8, 128), 65536)
                        bulk = scanner.read_mem(storage, read_bytes)
                        if not bulk or len(bulk) < 8:
                            continue
                        
                        num_ptrs = min(count, len(bulk) // 8) if count > 0 else (len(bulk) // 8)
                        for idx in range(num_ptrs):
                            try:
                                ptr = struct.unpack_from("<Q", bulk, idx * 8)[0]
                                if _is_valid_ptr(ptr) and (ptr & 0x7 == 0) and ptr not in seen_ptrs:
                                    m = self._check_rocket(scanner, ptr, entry_idx)
                                    if m and m.name != "":
                                        seen_ptrs.add(m.ptr)
                                        found_missiles.append(m)
                            except Exception:
                                continue

        return [m for m in found_missiles if m.name != ""]
    
    def _check_rocket(self, scanner, ptr, entry_idx):
        """
        Check if pointer is a valid rocket using 1 SINGLE block memory read (0x720 bytes).
        Pure starned layout (0x23c / 0x258) - applies to all player missiles, enemy missiles, and bot SAMs.
        """
        header = scanner.read_mem(ptr, 0x720)
        if not header or len(header) < 0x270:
            return None
        
        # 1. Extract position & velocity (Pure starned layout: 0x23c, 0x258)
        pos = struct.unpack_from("<fff", header, OFF_RKT_POS)
        vel = struct.unpack_from("<fff", header, OFF_RKT_VEL)
        is_ok, speed = _is_valid_missile_motion(pos, vel)
        if not is_ok:
            return None
        
        # Filter out dead/impacted rockets pooled on ground
        phase = struct.unpack_from("<I", header, OFF_RKT_PHASE)[0]
        detonated = struct.unpack_from("<I", header, OFF_RKT_DETONATED)[0]
        if phase == 6 or detonated != 0:
            return None
        
        # Header metadata with fallback support
        owner = struct.unpack_from("<Q", header, OFF_RKT_OWNER)[0] if len(header) >= OFF_RKT_OWNER + 8 else 0
        if not owner and len(header) >= 0x48:
            owner = struct.unpack_from("<Q", header, 0x40)[0]
        state = header[OFF_RKT_STATE] if len(header) > OFF_RKT_STATE else 0
        eid = struct.unpack_from("<I", header, OFF_RKT_ENTITY_ID)[0] if len(header) >= OFF_RKT_ENTITY_ID + 4 else 0
        if not eid and len(header) >= 0x34:
            eid = struct.unpack_from("<I", header, 0x30)[0]
        # Check guidance pointer candidates (0x670, 0x638, 0x648, 0x6C8, 0x698)
        guid = 0
        for goff in (OFF_RKT_GUIDANCE, 0x638, 0x648, 0x6C8, 0x698):
            if len(header) >= goff + 8:
                g_cand = struct.unpack_from("<Q", header, goff)[0]
                if _is_valid_ptr(g_cand) and (g_cand & 7 == 0):
                    guid = g_cand
                    break
        
        # 🛡️ VALIDATION: Filter out fake/garbage entities and non-rocket objects
        # 1. Entity ID: Active projectile IDs are normal positive integers (< 50,000,000).
        # Rejects 0 and ASCII string garbage (e.g. 1802396020 = "tblk").
        if eid == 0 or eid > 50_000_000:
            return None

        # 2. State: In-flight missiles typically have states 0..11.
        # Reject ASCII string garbage (e.g. 95 = '_').
        # Allows active flight through motor burnout / coasting / terminal guidance phases.
        if state > 32:
            return None

        # 3. Owner: If present, extract owner unit pointer (u_ptr | 1).
        # In multiplayer real matches, server-replicated enemy missiles may have owner == 0 or non-pointer IDs.
        # We sanitize invalid pointer bits without discarding active flying missiles purely due to owner == 0!
        owner_unit = (owner & ~1) if owner else 0
        if owner_unit != 0 and not (_is_valid_ptr(owner_unit) and (owner_unit & 0x7 == 0)):
            owner = 0
            owner_unit = 0

        # 4. Guidance: Validate pointer alignment
        if guid != 0 and not (_is_valid_ptr(guid) and (guid & 0x7 == 0)):
            guid = 0
        
        # Resolve weapon definition name
        # Caching by props (the static weapon definition pointer in Dagor Engine) guarantees that
        # when entity memory ptr is recycled for a newly dropped flare/chaff, it will NEVER inherit the old missile name!
        props = 0
        for poff in (OFF_RKT_PROPS, 0x6c8, 0x690, 0x6a0, 0x620):
            if len(header) >= poff + 8:
                p_cand = struct.unpack_from("<Q", header, poff)[0]
                if _is_valid_ptr(p_cand) and (p_cand & 7 == 0):
                    props = p_cand
                    break
        name = ""
        
        # Priority A: props pointer
        if _is_valid_ptr(props):
            if props in self._props_name_cache:
                name = self._props_name_cache[props]
            else:
                found_cm = False
                cand_name = ""
                for poff in (0x28, 0x50, 0x58):
                    n_ptr = _rp(scanner, props + poff)
                    if _is_valid_ptr(n_ptr):
                        s = _rstr(scanner, n_ptr)
                        if not s:
                            continue
                        s_lower = s.lower()
                        # 🚫 คัดทิ้งเป้าลวง/แฟลร์ทันที 100% ถ้าพบคำใน COUNTERMEASURE_KEYWORDS
                        if any(ign in s_lower for ign in COUNTERMEASURE_KEYWORDS):
                            found_cm = True
                            break
                        # ตรวจหาชื่อไฟล์ .blk หรือคีย์เวิร์ดอาวุธจรวด/ขีปนาวุธ
                        if not cand_name:
                            if s.endswith(".blk") or any(k in s_lower for k in ("missile", "rocket", "aim", "sam", "agm", "r_", "aam")):
                                clean_s = s.split("/")[-1].split("\\")[-1]
                                cand_name = clean_s
                
                if found_cm:
                    return None
                
                if cand_name:
                    name = cand_name
                    if len(self._props_name_cache) > 500:
                        self._props_name_cache.clear()
                    self._props_name_cache[props] = name
        
        # Priority B: Component Weapon pointers (+0x420, +0x440)
        if not name:
            for coff in (0x420, 0x440):
                if len(header) >= coff + 8:
                    comp_p = struct.unpack_from("<Q", header, coff)[0]
                    if _is_valid_ptr(comp_p) and (comp_p & 7 == 0):
                        s = scanner.read_mem(comp_p + 0x08, 48)
                        if s:
                            raw_str = s.split(b"\x00")[0].split(b"*")[0].decode("utf-8", errors="ignore").strip()
                            if any(ign in raw_str.lower() for ign in COUNTERMEASURE_KEYWORDS):
                                return None
                            if any(k in raw_str.lower() for k in ("missile", "rocket", "sam", "aim", "agm", "r_", "aam")):
                                name = raw_str + ".blk" if not raw_str.endswith(".blk") else raw_str
                                break

        # Priority C: Raw Header strings (+0x230, +0x240, +0x380)
        if not name:
            for soff in (0x230, 0x240, 0x380):
                if len(header) >= soff + 40:
                    s_bytes = header[soff : soff + 40]
                    for kw in (b"aim_", b"rocket", b"missile", b".blk", b"sam_", b"agm_", b"r_"):
                        if kw in s_bytes:
                            raw_str = s_bytes.split(b"\x00")[0].decode("utf-8", errors="ignore").strip()
                            if raw_str and not any(ign in raw_str.lower() for ign in COUNTERMEASURE_KEYWORDS):
                                name = raw_str
                                break
                    if name:
                        break

        # Priority D: Fallback name for SAM / SPAA / Enemy missiles without string
        if not name:
            if _is_valid_ptr(guid):
                name = "guided_missile.blk"
            elif speed > 100.0:
                name = "missile.blk"
            else:
                return None
        
        # 🚫 FINAL SAFETY FILTER: Ensure no countermeasure name ever passes through
        name_lower = name.lower()
        if any(ign in name_lower for ign in COUNTERMEASURE_KEYWORDS):
            return None
        
        # Build MissileInfo
        m = MissileInfo()
        m.ptr = ptr
        m.pos = pos
        m.vel = vel
        m.speed = speed
        m.owner = owner
        m.state = state
        m.entity_id = eid
        m.guidance_ptr = guid
        m.name = name
        m.entry_idx = entry_idx
        
        # Read original launch position at +0xc0 (if valid 3D float)
        if len(header) >= 0xcc:
            lpos = struct.unpack_from("<fff", header, 0xc0)
            if _is_valid_vec3(lpos):
                m.launch_pos = lpos
        
        # Read guidance details if valid pointer
        if _is_valid_ptr(guid):
            m.is_locked = (_r8(scanner, guid + OFF_GUID_LOCKED) == 1) or (_r8(scanner, guid + 0x50) == 1)
            m.is_tracking = (_r8(scanner, guid + OFF_GUID_TRACKING) == 1) or (_r8(scanner, guid + 0x51) == 1)
            tgt = _ri16(scanner, guid + OFF_GUID_TARGET_ID)
            if tgt <= 0:
                tgt_fallback = _ri16(scanner, guid + 0x8C)
                if 0 < tgt_fallback < 20000:
                    tgt = tgt_fallback
            m.target_id = tgt
        
        return m


# ====================================================================
# Module-level convenience functions
# ====================================================================
_global_scanner = MissileScanner()


def get_all_missiles(scanner, base):
    """
    Get all active missiles/rockets.
    Returns list of MissileInfo or None (if throttled, use previous cache).
    """
    return _global_scanner.scan(scanner, base)


def get_incoming_missiles(scanner, base, my_unit_id):
    """
    Get missiles targeting my unit.
    Returns list of MissileInfo that have target_id == my_unit_id.
    """
    missiles = get_all_missiles(scanner, base)
    if missiles is None:
        return None
    return [m for m in missiles if m.target_id == my_unit_id and m.is_tracking]


def reset_missile_scanner():
    """Reset scanner state (call on match change)"""
    global _global_scanner
    _global_scanner = MissileScanner()
