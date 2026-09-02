"""
🚀 Missile/Rocket Reader Module
อ่าน missile/rocket จาก ECS system ของ Dagor Engine

Confirmed offsets (starned - Linux):
  ECS Manager:  base + 0x8225aa0
  node_table:   manager + 0x178
  Rocket entry: node_table[i] → direct pointer array (stride 8)
  
  pos=0x23c, vel=0x258, owner=0x40, state=0x94
  guidance=0x638, props=0x6c8, name=props+0x50
  guidance: locked=+0x50, tracking=+0x51, target_id=+0x8C
"""

import struct
import math
import time

try:
    from src.utils.debug import dprint
except Exception:
    def dprint(msg, force=False): return

# ====================================================================
# Confirmed Offsets (starned - Linux, verified 2026-09)
# ====================================================================
OFF_ECS_MANAGER    = 0x8225aa0   # base + this → ptr to ECS manager
OFF_ECS_NODE_TABLE = 0x178       # manager + this → node_table ptr
OFF_ECS_CLASS_TABLE= 0x5E8       # manager + this → class_table ptr

# Rocket struct internals
OFF_RKT_ENTITY_ID  = 0x30
OFF_RKT_OWNER      = 0x40
OFF_RKT_STATE      = 0x94
OFF_RKT_POS        = 0x23c
OFF_RKT_VEL        = 0x258
OFF_RKT_GUIDANCE   = 0x638
OFF_RKT_PROPS      = 0x6c8

# Guidance struct internals
OFF_GUID_LOCKED    = 0x50
OFF_GUID_TRACKING  = 0x51
OFF_GUID_TARGET_ID = 0x8C

# Scan config
MAX_NODE_ENTRIES   = 5000        # สแกนทั้งตาราง
MAX_PTRS_PER_ENTRY = 500         # max pointers per storage array
SCAN_INTERVAL_MS   = 100         # minimum ms between full scans

# ====================================================================
# Helpers (inline for performance)
# ====================================================================
def _rp(sc, a):
    d = sc.read_mem(a, 8)
    return struct.unpack("<Q", d)[0] if d and len(d) >= 8 else 0

def _r32(sc, a):
    d = sc.read_mem(a, 4)
    return struct.unpack("<I", d)[0] if d and len(d) >= 4 else 0

def _r16(sc, a):
    d = sc.read_mem(a, 2)
    return struct.unpack("<H", d)[0] if d and len(d) >= 2 else 0

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


# ====================================================================
# MissileInfo - lightweight missile data container
# ====================================================================
class MissileInfo:
    __slots__ = (
        'ptr', 'pos', 'vel', 'speed', 'owner', 'state',
        'entity_id', 'guidance_ptr', 'name',
        'is_locked', 'is_tracking', 'target_id',
        'entry_idx',
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
    
    def __repr__(self):
        return (f"<Missile '{self.name}' pos=({self.pos[0]:.0f},{self.pos[1]:.0f},{self.pos[2]:.0f}) "
                f"spd={self.speed:.0f} lock={self.is_locked} trk={self.is_tracking} tgt={self.target_id}>")


# ====================================================================
# MissileScanner - persistent scanner with entry caching
# ====================================================================
class MissileScanner:
    """
    Scans ECS node_table for active missiles/rockets.
    Caches which entries contain rockets for fast re-scans.
    """
    
    def __init__(self):
        self._node_table = 0
        self._class_table = 0
        self._mgr_ptr = 0
        self._known_entries = set()      # entries ที่เคยเจอ rocket
        self._last_full_scan = 0.0
        self._full_scan_interval = 5.0   # full scan ทุก 5 วินาที
        self._last_scan_time = 0.0
        self._initialized = False
    
    def _init_ecs(self, scanner, base):
        """Initialize ECS manager pointers"""
        mgr = _rp(scanner, base + OFF_ECS_MANAGER)
        if not _is_valid_ptr(mgr):
            return False
        
        node_t = _rp(scanner, mgr + OFF_ECS_NODE_TABLE)
        class_t = _rp(scanner, mgr + OFF_ECS_CLASS_TABLE)
        
        if not (_is_valid_ptr(node_t) and _is_valid_ptr(class_t)):
            return False
        
        self._mgr_ptr = mgr
        self._node_table = node_t
        self._class_table = class_t
        self._initialized = True
        return True
    
    def scan(self, scanner, base):
        """
        Scan for active missiles. Returns list of MissileInfo.
        Uses cached entries for fast re-scan, does full scan periodically.
        """
        now = time.time()
        
        # Throttle: minimum 50ms between scans
        if now - self._last_scan_time < 0.05:
            return None  # ส่ง None = ใช้ cache เดิม
        self._last_scan_time = now
        
        # Re-init ECS pointers (they can change between matches)
        if not self._initialized or now - self._last_full_scan > 30.0:
            if not self._init_ecs(scanner, base):
                self._initialized = False
                return []
        
        # Decide: full scan or fast re-scan
        do_full = (now - self._last_full_scan > self._full_scan_interval) or not self._known_entries
        
        missiles = []
        
        if do_full:
            # Full scan: iterate ALL entries
            self._last_full_scan = now
            new_known = set()
            
            for entry_idx in range(MAX_NODE_ENTRIES):
                entry_addr = self._node_table + entry_idx * 0x20
                data = scanner.read_mem(entry_addr, 0x20)
                if not data or len(data) < 0x20:
                    break
                if all(b == 0 for b in data):
                    continue
                
                # Extract storage pointer (first 8 bytes = q0)
                storage = struct.unpack_from("<Q", data, 0)[0]
                if not _is_valid_ptr(storage):
                    continue
                
                # Try count from various offsets
                found = self._scan_entry(scanner, storage, entry_idx, data)
                if found:
                    missiles.extend(found)
                    new_known.add(entry_idx)
            
            self._known_entries = new_known
        else:
            # Fast re-scan: only check known entries + neighbors
            entries_to_check = set(self._known_entries)
            # Also check neighbors (±3) in case new rockets appear nearby
            for e in list(self._known_entries):
                for delta in range(-3, 4):
                    if 0 <= e + delta < MAX_NODE_ENTRIES:
                        entries_to_check.add(e + delta)
            
            new_known = set()
            for entry_idx in sorted(entries_to_check):
                entry_addr = self._node_table + entry_idx * 0x20
                data = scanner.read_mem(entry_addr, 0x20)
                if not data or len(data) < 0x20:
                    continue
                if all(b == 0 for b in data):
                    continue
                
                storage = struct.unpack_from("<Q", data, 0)[0]
                if not _is_valid_ptr(storage):
                    continue
                
                found = self._scan_entry(scanner, storage, entry_idx, data)
                if found:
                    missiles.extend(found)
                    new_known.add(entry_idx)
            
            self._known_entries = new_known
        
        return missiles
    
    def _scan_entry(self, scanner, storage, entry_idx, entry_data):
        """Scan a single node_table entry for rockets"""
        missiles = []
        
        # Get count from entry data - try multiple offsets
        counts = []
        for co in [0x14, 0x10, 0x1C, 0x0C]:
            cv = struct.unpack_from("<I", entry_data, co)[0]
            if 0 < cv < MAX_PTRS_PER_ENTRY:
                counts.append(cv)
        
        if not counts:
            return missiles
        
        # Use largest reasonable count
        count = max(counts)
        
        # Layout A: Direct pointer array (stride=8) - confirmed working
        bulk = scanner.read_mem(storage, min(count, MAX_PTRS_PER_ENTRY) * 8)
        if not bulk or len(bulk) < 8:
            return missiles
        
        num_ptrs = min(count, len(bulk) // 8)
        for i in range(num_ptrs):
            ptr = struct.unpack_from("<Q", bulk, i * 8)[0]
            if not _is_valid_ptr(ptr):
                continue
            
            info = self._check_rocket(scanner, ptr, entry_idx)
            if info:
                missiles.append(info)
        
        return missiles
    
    def _check_rocket(self, scanner, ptr, entry_idx):
        """Check if pointer is a valid rocket and return MissileInfo"""
        # Read position (starned offset 0x23c)
        pos = _rv3(scanner, ptr + OFF_RKT_POS)
        if not pos:
            return None
        
        # Position validation: ≥2 axes > 5m, all < 200km
        if not all(math.isfinite(x) for x in pos):
            return None
        nonzero_pos = sum(1 for x in pos if abs(x) > 5.0)
        if nonzero_pos < 2 or any(abs(x) > 200000 for x in pos):
            return None
        
        # Read velocity (starned offset 0x258)
        vel = _rv3(scanner, ptr + OFF_RKT_VEL)
        if not vel:
            return None
        if not all(math.isfinite(x) for x in vel):
            return None
        speed = _vlen(vel)
        nonzero_vel = sum(1 for x in vel if abs(x) > 1.0)
        if not (50.0 < speed < 3500.0 and nonzero_vel >= 2):
            return None
        
        # Secondary validation
        owner = _rp(scanner, ptr + OFF_RKT_OWNER)
        state = _r8(scanner, ptr + OFF_RKT_STATE)
        eid = _r32(scanner, ptr + OFF_RKT_ENTITY_ID)
        
        if state > 10:
            return None
        if owner > 0xFFFFFFFF:
            return None
        if eid == 0 or eid > 10_000_000:
            return None
        
        guid = _rp(scanner, ptr + OFF_RKT_GUIDANCE)
        if guid != 0 and not _is_valid_ptr(guid):
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
        m.entry_idx = entry_idx
        
        # Read guidance details
        if _is_valid_ptr(guid):
            m.is_locked = _r8(scanner, guid + OFF_GUID_LOCKED) == 1
            m.is_tracking = _r8(scanner, guid + OFF_GUID_TRACKING) == 1
            m.target_id = _ri16(scanner, guid + OFF_GUID_TARGET_ID)
        
        # Read name via props
        props = _rp(scanner, ptr + OFF_RKT_PROPS)
        if _is_valid_ptr(props):
            name_ptr = _rp(scanner, props + 0x50)
            if _is_valid_ptr(name_ptr):
                m.name = _rstr(scanner, name_ptr)
        
        return m


# ====================================================================
# Module-level convenience functions
# ====================================================================
_global_scanner = MissileScanner()


def get_all_missiles(scanner, base):
    """
    Get all active missiles/rockets.
    Returns list of MissileInfo or None (if throttled, use previous cache).
    
    Usage:
        missiles = get_all_missiles(scanner, base_address)
        if missiles is not None:
            for m in missiles:
                print(f"Missile at {m.pos} speed={m.speed}")
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
