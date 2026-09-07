"""
DataPumpWorker — Background thread that pre-fetches game memory and
pre-computes frame data so paintGL() only needs to draw.

Architecture:
    Worker Thread (this)                    Main GUI Thread (paintGL)
    ┌──────────────────────┐  snapshot     ┌──────────────────────┐
    │  read_mem + compute  │ ───────────→  │  read snapshot       │
    │  ~50+ syscalls/frame │   pyqtSignal  │  project + draw      │
    └──────────────────────┘               └──────────────────────┘

The worker owns ALL mutable caches (profile_cache, vel_window, etc.)
so there are no shared-state race conditions.
"""

import math
import time
import struct
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import QThread, pyqtSignal

from src.utils.scanner import MemoryScanner
import src.utils.mul as mul
from src.utils.mul import (
    get_cgame_base,
    get_view_matrix,
    get_all_units,
    get_local_team,
    get_unit_pos,
    get_unit_status,
    get_unit_filter_profile,
    get_unit_detailed_dna,
    get_unit_3d_box_data,
    get_unit_bbox,
    get_unit_rotation,
    get_weapon_barrel,
    get_local_axes_from_rotation,
    get_my_air_velocity,
    get_sight_compensation_factor,
    world_to_screen,
    is_valid_ptr,
    reset_runtime_caches,
    OFF_UNIT_INFO,
    OFF_UNIT_TEAM,
    OFF_UNIT_STATE,
    MANAGER_OFFSET,
    OFF_CAMERA_PTR,
    OFF_VIEW_MATRIX,
)
from src.utils.debug import dprint
from src.utils.missile import MissileScanner


# ---------------------------------------------------------------------------
# Data Transfer Objects (snapshot)
# ---------------------------------------------------------------------------
@dataclass
class TargetSnapshot:
    """Pre-fetched data for a single enemy unit."""
    u_ptr: int = 0
    raw_name: str = ""
    short_name: str = ""
    family_name: str = ""
    name_key: str = ""
    profile_tag: str = ""
    profile_path: str = ""
    profile_unit_key: str = ""
    reload_val: int = 0
    is_air: bool = False
    pos: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    dist: float = 0.0
    vel: Optional[Tuple[float, float, float]] = None
    is_recon_drone: bool = False

    # Pre-fetched per-target heavy data (avoids re-reading in paintGL)
    box_data: Any = None              # (pos, bmin, bmax, rot) or None
    dynamic_box_source: str = ""
    bmin: Any = None                  # (x,y,z) or None
    bmax: Any = None                  # (x,y,z) or None
    rot: Any = None                   # 9-float tuple or None
    barrel_data: Any = None           # (start, end) or None
    unit_family: Any = None           # pre-calculated unit_family enum

    def __iter__(self):
        """Allows unpacking as a 14-element tuple identical to the legacy target tuple."""
        yield self.u_ptr
        yield self.raw_name
        yield self.reload_val
        yield self.is_air
        yield self.pos
        yield self.dist
        yield self.short_name
        yield self.family_name
        yield self.name_key
        yield self.profile_tag
        yield self.profile_path
        yield self.profile_unit_key
        yield self.vel
        yield self.is_recon_drone

    def __getitem__(self, index):
        return tuple(self)[index]


@dataclass
class FrameSnapshot:
    """All data that paintGL needs for one render frame."""
    timestamp: float = 0.0
    is_valid: bool = False

    # Core engine state
    cgame_base: int = 0
    view_matrix: Any = None

    # My unit
    my_unit: int = 0
    my_team: int = 0
    my_pos: Optional[Tuple[float, float, float]] = None
    my_vel: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    my_is_air: bool = False
    my_name: str = ""
    my_name_key: str = ""
    my_box_data: Any = None
    my_barrel_data: Any = None
    my_dynamic_geometry: Any = None
    my_rot: Any = None

    # Ballistic profile
    ballistic_profile: Dict = field(default_factory=dict)
    current_zeroing: float = 0.0

    # All valid enemy targets (pre-filtered, pre-fetched)
    valid_targets: List[TargetSnapshot] = field(default_factory=list)

    # Active missiles pre-scanned in background thread (0ms overhead in paintGL!)
    missiles: List[Any] = field(default_factory=list)

    # Active target selection
    active_target_ptr: int = 0

    # Unit list metadata
    all_unit_ptrs: set = field(default_factory=set)

    # Worker performance
    worker_fps: float = 0.0
    worker_dt: float = 0.0


# ---------------------------------------------------------------------------
# Worker Thread
# ---------------------------------------------------------------------------
class DataPumpWorker(QThread):
    """
    Background thread that continuously reads game memory and produces
    FrameSnapshot objects for the GUI thread to render.
    """

    # Signal emitted when a new snapshot is ready
    new_frame = pyqtSignal(object)  # FrameSnapshot

    def __init__(
        self,
        scanner: MemoryScanner,
        base_address: int,
        target_fps: float = 80.0,
        # Pass references to overlay helper functions that are defined
        # in radar_overlay.py (to avoid circular imports)
        read_ballistic_profile_fn=None,
        get_dynamic_target_box_data_fn=None,
        get_dynamic_my_geometry_fn=None,
        stabilize_velocity_fn=None,
        resolve_is_air_fn=None,
        resolve_unit_family_fn=None,
        is_boat_like_fn=None,
        is_recon_drone_fn=None,
        is_fixed_recon_ghost_fn=None,
        is_recon_alert_ready_fn=None,
        filter_constants=None,
    ):
        super().__init__()
        self.scanner = scanner
        self.base_address = base_address
        self.target_fps = target_fps
        self._stop_flag = False

        # External function references (injected from radar_overlay)
        self._read_ballistic_profile = read_ballistic_profile_fn
        self._get_dynamic_target_box_data = get_dynamic_target_box_data_fn
        self._get_dynamic_my_geometry = get_dynamic_my_geometry_fn
        self._stabilize_velocity = stabilize_velocity_fn
        self._resolve_is_air = resolve_is_air_fn
        self._resolve_unit_family = resolve_unit_family_fn
        self._is_boat_like = is_boat_like_fn
        self._is_recon_drone = is_recon_drone_fn
        self._is_fixed_recon_ghost = is_fixed_recon_ghost_fn
        self._is_recon_alert_ready = is_recon_alert_ready_fn
        self._filter_constants = filter_constants or {}

        # ----- Worker-owned caches -----
        self.profile_cache: Dict[int, dict] = {}
        self.active_targets: Dict[int, dict] = {}  # u_ptr -> {"snapshot": t_snap, "last_seen": now}

        self.last_my_unit: int = 0
        self.last_my_team: int = 0
        self.last_cgame_base: int = 0
        self.my_unit_spawn_grace_until: float = 0.0

        # Worker FPS tracking
        self._last_frame_time = time.time()
        self._worker_fps = 0.0

        # Background missile scanner (removes all missile scan overhead from paintGL)
        self.missile_scanner = MissileScanner()
        self.latest_missiles: List[Any] = []
        self.last_missile_scan_t: float = 0.0
        self.missile_scan_interval: float = 0.08

        # Thread-safe snapshot buffer
        self._latest_snapshot = FrameSnapshot()
        self._snapshot_lock = threading.Lock()

    def get_latest_snapshot(self) -> FrameSnapshot:
        with self._snapshot_lock:
            return self._latest_snapshot

    def request_stop(self):
        self._stop_flag = True

    def run(self):
        """Main worker loop — runs on background QThread."""
        sleep_s = 1.0 / max(self.target_fps, 1.0)

        while not self._stop_flag:
            try:
                snapshot = self._gather_frame()
                with self._snapshot_lock:
                    self._latest_snapshot = snapshot
                self.new_frame.emit(snapshot)
            except Exception as e:
                dprint(f"DataPumpWorker error: {e}", force=True)
                empty_snap = FrameSnapshot(
                    timestamp=time.time(),
                    is_valid=False,
                )
                with self._snapshot_lock:
                    self._latest_snapshot = empty_snap
                self.new_frame.emit(empty_snap)

            # Adaptive sleep to hit target FPS
            elapsed = time.time() - self._last_frame_time
            remaining = sleep_s - elapsed
            if remaining > 0.001:
                time.sleep(remaining)

        dprint("DataPumpWorker stopped.", force=True)

    # ------------------------------------------------------------------
    # Core data gathering (was previously inside paintGL L3150-L3650)
    # ------------------------------------------------------------------
    def _gather_frame(self) -> FrameSnapshot:
        now = time.time()
        dt = now - self._last_frame_time
        self._last_frame_time = now
        if dt > 0:
            self._worker_fps = (self._worker_fps * 0.9) + ((1.0 / dt) * 0.1)

        snap = FrameSnapshot(
            timestamp=now,
            worker_fps=self._worker_fps,
            worker_dt=dt,
        )

        if not self.scanner.is_alive():
            return snap

        # --- 1. CGame Base ---
        cgame_base = get_cgame_base(self.scanner, self.base_address)
        if cgame_base == 0:
            return snap

        if cgame_base != self.last_cgame_base:
            self.last_cgame_base = cgame_base
            self.profile_cache = {}
            self.active_targets = {}
        snap.cgame_base = cgame_base

        # --- 2. View Matrix ---
        try:
            view_matrix = get_view_matrix(self.scanner, cgame_base)
            snap.view_matrix = view_matrix
        except Exception:
            pass

        # --- 3. Ballistic Profile ---
        if self._read_ballistic_profile:
            snap.ballistic_profile = self._read_ballistic_profile(
                self.scanner, cgame_base
            )
        snap.current_zeroing = get_sight_compensation_factor(
            self.scanner, self.base_address
        )

        # --- 4. All Units ---
        all_units_data = get_all_units(self.scanner, cgame_base)
        snap.all_unit_ptrs = {u_ptr for u_ptr, _ in all_units_data}

        # --- 5. My Unit ---
        my_unit, my_team = get_local_team(self.scanner, self.base_address)
        if my_team:
            self.last_my_team = my_team
        effective_my_team = my_team or self.last_my_team
        snap.my_unit = my_unit
        snap.my_team = effective_my_team

        my_pos = get_unit_pos(self.scanner, my_unit) if my_unit else None
        snap.my_pos = my_pos

        # Cache reset only when my_unit changes between two non-zero units
        if my_unit and self.last_my_unit and my_unit != self.last_my_unit:
            self.profile_cache = {}
            self.active_targets = {}

            self.last_my_unit = my_unit
            self.my_unit_spawn_grace_until = now + 0.40
        elif my_unit and not self.last_my_unit:
            self.last_my_unit = my_unit

        # Determine my_is_air
        my_is_air = False
        for u_ptr, is_air in all_units_data:
            if u_ptr == my_unit:
                my_is_air = is_air
                break
        if my_unit:
            my_profile = get_unit_filter_profile(self.scanner, my_unit)
            snap.my_name = my_profile.get("short_name") or ""
            snap.my_name_key = my_profile.get("unit_key") or ""
            if my_profile.get("kind") == "air":
                my_is_air = True
            elif my_profile.get("kind") == "ground":
                my_is_air = False
        snap.my_is_air = my_is_air

        # My velocity:
        # AIR uses get_my_air_velocity (double precision 24 bytes).
        # GROUND my_vel is owned and stabilized exclusively by GUI thread at steady 60Hz to prevent cache collisions and jitter!
        my_spawn_in_grace = now < self.my_unit_spawn_grace_until
        if my_spawn_in_grace:
            snap.my_vel = (0.0, 0.0, 0.0)
        elif my_unit:
            if my_is_air:
                snap.my_vel = get_my_air_velocity(self.scanner, my_unit) or (0.0, 0.0, 0.0)
            else:
                snap.my_vel = None

        # My box data & barrel (heavy reads)
        if my_unit and my_pos and not my_is_air:
            try:
                snap.my_box_data = get_unit_3d_box_data(self.scanner, my_unit, False)
                if snap.my_box_data:
                    snap.my_barrel_data = get_weapon_barrel(
                        self.scanner, my_unit,
                        snap.my_box_data[0], snap.my_box_data[3],
                        should_log=False,
                    )
                    if self._get_dynamic_my_geometry:
                        snap.my_dynamic_geometry = self._get_dynamic_my_geometry(
                            self.scanner, cgame_base, my_unit, snap.my_box_data,
                        )
            except Exception:
                pass

        snap.my_rot = get_unit_rotation(self.scanner, my_unit) if my_unit else None

        # --- 6. Valid Targets ---
        fc = self._filter_constants
        NON_PLAYABLE_HINTS = fc.get("NON_PLAYABLE_RUNTIME_HINTS", ())
        MAX_GROUND_DIST = fc.get("MAX_GROUND_TARGET_DISTANCE", 20000.0)
        MAX_AIR_DIST = fc.get("MAX_AIR_TARGET_DISTANCE", 28000.0)
        ORIGIN_GHOST_RADIUS = fc.get("ORIGIN_GHOST_RADIUS", 35.0)
        ORIGIN_GHOST_MY_MIN = fc.get("ORIGIN_GHOST_MY_DIST_MIN", 250.0)
        IGNORE_ALL_BOATS = fc.get("IGNORE_ALL_BOATS", False)
        NAME_PREFIXES = fc.get("NAME_PREFIXES", [])

        valid_targets = []
        current_seen_ptrs = set()

        for u_ptr, is_air in all_units_data:
            if u_ptr == my_unit:
                continue
            current_seen_ptrs.add(u_ptr)

            # Check cached profile to determine if name is already resolved
            cached_prof = self.profile_cache.get(u_ptr)
            cached_name = cached_prof.get("resolved_name") if cached_prof else None
            need_read_name = not (cached_name and cached_name.lower() not in ("none", "unknown", "c", ""))

            # Read status
            info_ptr_raw = self.scanner.read_mem(u_ptr + mul.OFF_UNIT_INFO, 8)
            info_ptr_now = struct.unpack("<Q", info_ptr_raw)[0] if (info_ptr_raw and len(info_ptr_raw) == 8) else 0

            status = get_unit_status(self.scanner, u_ptr, read_name=need_read_name)
            if not status:
                continue

            u_team, u_state, unit_name, reload_val = status

            if u_state >= 1:
                continue

            # Team filter
            if u_team == 0 or (effective_my_team != 0 and u_team == effective_my_team):
                continue

            # Cache immutable Profile & DNA to eliminate 6+ syscalls per unit
            if cached_prof and (cached_prof.get("info_ptr") == info_ptr_now or not is_valid_ptr(info_ptr_now)):
                profile = cached_prof["profile"]
                dna = cached_prof["dna"]
                cached_prof["last_seen"] = now
            else:
                profile = get_unit_filter_profile(self.scanner, u_ptr)
                dna = get_unit_detailed_dna(self.scanner, u_ptr) or {}
                if is_valid_ptr(info_ptr_now):
                    self.profile_cache[u_ptr] = {
                        "profile": profile,
                        "dna": dna,
                        "info_ptr": info_ptr_now,
                        "last_seen": now,
                    }
                    cached_prof = self.profile_cache[u_ptr]

            # Profile-based filtering
            if profile.get("skip"):
                continue
            profile_tag = (profile.get("tag") or "").lower()
            profile_path = (profile.get("path") or "").lower()
            if profile_tag in ("exp_aaa", "exp_fortification", "exp_structure", "exp_zero"):
                continue
            if ("air_defence/" in profile_path) or ("structures/" in profile_path) or ("dummy_plane" in profile_path):
                continue

            short_name = (dna.get("short_name") or "").strip()
            family_name = (dna.get("family") or "").strip()
            name_key = (dna.get("name_key") or "").strip()
            profile_unit_key = profile.get("unit_key") or ""

            # Resolve is_air
            resolved_is_air = is_air
            if self._resolve_is_air:
                resolved_is_air = self._resolve_is_air(
                    is_air, family_name, profile_tag, profile_path,
                )

            # Resolve name with sticky caching (never degrades into UNKNOWN or another name)
            cached_name = cached_prof.get("resolved_name") if cached_prof else None
            if cached_name and cached_name.lower() not in ("none", "unknown", "c", ""):
                resolved_name = cached_name
            else:
                resolved_name = short_name
                if (not resolved_name) or (resolved_name.lower() in ("none", "unknown", "c")):
                    resolved_name = unit_name
                if (not resolved_name) or (len(resolved_name) < 2) or (resolved_name.lower() in ("unknown", "c", "none")):
                    resolved_name = profile.get("display_name") or "unknown"
                if resolved_name and resolved_name.lower() not in ("none", "unknown", "c", "") and cached_prof:
                    cached_prof["resolved_name"] = resolved_name

            # Runtime filter
            runtime_filter_blob = " ".join((
                (resolved_name or ""),
                short_name, family_name, name_key,
                (profile.get("display_name") or ""),
                profile_unit_key, profile_path, profile_tag,
            )).lower()
            if any(h in runtime_filter_blob for h in NON_PLAYABLE_HINTS):
                continue

            # Boat filter
            if self._is_boat_like and self._is_boat_like(
                family_name, profile_tag, profile_path,
                profile_unit_key, name_key, short_name,
            ):
                if IGNORE_ALL_BOATS or (not my_is_air):
                    continue

            is_recon_drone = False
            if self._is_recon_drone:
                is_recon_drone = self._is_recon_drone(runtime_filter_blob)

            # Position
            pos = get_unit_pos(self.scanner, u_ptr)
            if not pos:
                continue

            # Recon ghost drone filter (synced with radar_overlay)
            if is_recon_drone and self._is_fixed_recon_ghost and self._is_fixed_recon_ghost(u_ptr, pos, now):
                continue
            if is_recon_drone and self._is_recon_alert_ready and not self._is_recon_alert_ready(u_ptr, now):
                continue

            # Origin ghost
            pos_origin_dist = math.sqrt(pos[0] ** 2 + pos[1] ** 2 + pos[2] ** 2)
            if pos_origin_dist <= ORIGIN_GHOST_RADIUS:
                if my_pos and math.sqrt(my_pos[0] ** 2 + my_pos[1] ** 2 + my_pos[2] ** 2) >= ORIGIN_GHOST_MY_MIN:
                    continue

            # Distance
            dist_to_me = 0.0
            if my_pos:
                dx = pos[0] - my_pos[0]
                dy = pos[1] - my_pos[1]
                dz = pos[2] - my_pos[2]
                dist_to_me = math.sqrt(dx * dx + dy * dy + dz * dz)
                if dist_to_me > (MAX_AIR_DIST if resolved_is_air else MAX_GROUND_DIST):
                    continue

            # Ground and Air velocity stabilization is owned 100% by GUI thread at 60Hz
            pre_vel = None

            # Pre-resolve unit family (cached permanently per unit)
            unit_family = cached_prof.get("unit_family") if cached_prof else None
            if unit_family is None and self._resolve_unit_family:
                try:
                    unit_family = self._resolve_unit_family(
                        family_name,
                        profile_tag,
                        profile_path,
                        profile_unit_key,
                        name_key,
                        short_name,
                        resolved_is_air,
                        self.scanner,
                        u_ptr,
                    )
                    if cached_prof:
                        cached_prof["unit_family"] = unit_family
                except Exception:
                    pass

            # ===== PRE-FETCH HEAVY DATA (bbox, barrel) =====
            t_snap = TargetSnapshot(
                u_ptr=u_ptr,
                raw_name=resolved_name,
                short_name=short_name,
                family_name=family_name,
                name_key=name_key,
                profile_tag=profile_tag,
                profile_path=profile_path,
                profile_unit_key=profile_unit_key,
                reload_val=reload_val,
                is_air=resolved_is_air,
                pos=pos,
                dist=dist_to_me,
                vel=pre_vel,
                is_recon_drone=is_recon_drone,
                unit_family=unit_family,
            )

            # Pre-fetch box data (heavy memory read optimized with bbox cache)
            try:
                cached_bbox = cached_prof.get("bbox") if cached_prof else None
                if cached_bbox:
                    bmin, bmax, dyn_src = cached_bbox
                    rot = get_unit_rotation(self.scanner, u_ptr)
                    t_snap.box_data = (pos, bmin, bmax, rot) if rot else None
                    t_snap.dynamic_box_source = dyn_src
                    t_snap.bmin = bmin
                    t_snap.bmax = bmax
                    t_snap.rot = rot
                else:
                    if self._get_dynamic_target_box_data:
                        box_result = self._get_dynamic_target_box_data(
                            self.scanner, u_ptr, resolved_is_air,
                        )
                        if box_result:
                            t_snap.box_data = box_result[0]
                            t_snap.dynamic_box_source = box_result[1] if len(box_result) > 1 else ""
                    else:
                        t_snap.box_data = get_unit_3d_box_data(
                            self.scanner, u_ptr, resolved_is_air,
                        )

                    # Extract pos, bmin, bmax, rot directly from box_data without redundant syscalls!
                    if t_snap.box_data:
                        t_snap.pos = t_snap.box_data[0] or t_snap.pos
                        t_snap.bmin = t_snap.box_data[1]
                        t_snap.bmax = t_snap.box_data[2]
                        t_snap.rot = t_snap.box_data[3]
                        if cached_prof and t_snap.bmin and t_snap.bmax:
                            cached_prof["bbox"] = (t_snap.bmin, t_snap.bmax, t_snap.dynamic_box_source)
                    else:
                        t_snap.bmin, t_snap.bmax = get_unit_bbox(self.scanner, u_ptr)
                        t_snap.rot = get_unit_rotation(self.scanner, u_ptr)
                        if cached_prof and t_snap.bmin and t_snap.bmax:
                            cached_prof["bbox"] = (t_snap.bmin, t_snap.bmax, "")
            except Exception:
                pass

            # Pre-fetch barrel data (ground targets only within 3500m combat distance, no log spam)
            if t_snap.box_data and (not resolved_is_air) and dist_to_me <= 3500.0:
                try:
                    t_snap.barrel_data = get_weapon_barrel(
                        self.scanner, u_ptr,
                        t_snap.pos, t_snap.box_data[3],
                        should_log=False,
                    )
                except Exception:
                    pass

            valid_targets.append(t_snap)

        # Anti-blink tracking: preserve targets across momentary frame dropouts (250ms grace)
        now_valid_ptrs = {t.u_ptr for t in valid_targets}
        for t in valid_targets:
            self.active_targets[t.u_ptr] = {"snapshot": t, "last_seen": now}

        for u_ptr, trk in list(self.active_targets.items()):
            if u_ptr not in now_valid_ptrs:
                if (now - trk["last_seen"]) <= 0.25:
                    valid_targets.append(trk["snapshot"])
                else:
                    del self.active_targets[u_ptr]

        # Clean profile cache (5-second grace period)
        for ptr in list(self.profile_cache.keys()):
            if ptr not in current_seen_ptrs:
                last_seen = self.profile_cache[ptr].get("last_seen", 0.0)
                if (now - last_seen) > 5.0:
                    del self.profile_cache[ptr]

        # Scan for missiles periodically in background thread (0ms in paintGL)
        if (now - self.last_missile_scan_t) >= self.missile_scan_interval:
            self.last_missile_scan_t = now
            try:
                m_res = self.missile_scanner.scan(self.scanner, self.base_address)
                if m_res is not None:
                    self.latest_missiles = m_res
            except Exception:
                pass

        snap.missiles = list(self.latest_missiles)
        snap.valid_targets = valid_targets
        snap.is_valid = True
        return snap
