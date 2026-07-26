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
        is_boat_like_fn=None,
        is_recon_drone_fn=None,
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
        self._is_boat_like = is_boat_like_fn
        self._is_recon_drone = is_recon_drone_fn
        self._filter_constants = filter_constants or {}

        # ----- Worker-owned caches -----
        self.profile_cache: Dict[int, dict] = {}
        self.dead_unit_latch: Dict[int, dict] = {}
        self.last_my_unit: int = 0
        self.last_my_team: int = 0
        self.last_cgame_base: int = 0
        self.my_unit_spawn_grace_until: float = 0.0

        # Worker FPS tracking
        self._last_frame_time = time.time()
        self._worker_fps = 0.0

    def request_stop(self):
        self._stop_flag = True

    def run(self):
        """Main worker loop — runs on background QThread."""
        sleep_s = 1.0 / max(self.target_fps, 1.0)

        while not self._stop_flag:
            try:
                snapshot = self._gather_frame()
                self.new_frame.emit(snapshot)
            except Exception as e:
                dprint(f"DataPumpWorker error: {e}", force=True)
                # Emit empty snapshot so paintGL knows we're alive
                self.new_frame.emit(FrameSnapshot(
                    timestamp=time.time(),
                    is_valid=False,
                ))

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
            reset_runtime_caches(clear_view=True)
            self.last_cgame_base = cgame_base
        snap.cgame_base = cgame_base

        # --- 2. View Matrix ---
        view_matrix = get_view_matrix(self.scanner, cgame_base)
        if not view_matrix:
            return snap
        snap.view_matrix = view_matrix

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

        # Clean dead_unit_latch
        if self.dead_unit_latch:
            self.dead_unit_latch = {
                ptr: meta
                for ptr, meta in self.dead_unit_latch.items()
                if ptr in snap.all_unit_ptrs
            }

        # --- 5. My Unit ---
        my_unit, my_team = get_local_team(self.scanner, self.base_address)
        if my_team:
            self.last_my_team = my_team
        effective_my_team = my_team or self.last_my_team
        snap.my_unit = my_unit
        snap.my_team = effective_my_team

        my_pos = get_unit_pos(self.scanner, my_unit) if my_unit else None
        snap.my_pos = my_pos

        # Cache reset on my_unit change
        if my_unit != self.last_my_unit:
            reset_runtime_caches(clear_view=True)
            self.profile_cache = {}
            self.dead_unit_latch = {}
            self.last_my_unit = my_unit
            self.my_unit_spawn_grace_until = now + 0.40

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

        # My velocity
        my_spawn_in_grace = now < self.my_unit_spawn_grace_until
        if my_spawn_in_grace:
            snap.my_vel = (0.0, 0.0, 0.0)
        elif my_unit:
            if my_is_air:
                snap.my_vel = get_my_air_velocity(self.scanner, my_unit) or (0.0, 0.0, 0.0)
            elif self._stabilize_velocity:
                snap.my_vel = self._stabilize_velocity(my_unit, False, my_pos, now) or (0.0, 0.0, 0.0)
            else:
                snap.my_vel = (0.0, 0.0, 0.0)

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

            # Read status
            info_ptr_raw = self.scanner.read_mem(u_ptr + OFF_UNIT_INFO, 8)
            info_ptr_now = struct.unpack("<Q", info_ptr_raw)[0] if (info_ptr_raw and len(info_ptr_raw) == 8) else 0

            status = get_unit_status(self.scanner, u_ptr)
            if not status:
                continue

            profile = get_unit_filter_profile(self.scanner, u_ptr)
            dna = get_unit_detailed_dna(self.scanner, u_ptr) or {}
            self.profile_cache[u_ptr] = {
                "status": status,
                "profile": profile,
                "dna": dna,
                "is_air_resolved": is_air,
                "info_ptr": info_ptr_now,
            }

            u_team, u_state, unit_name, reload_val = status

            # Dead unit latch
            latch_meta = self.dead_unit_latch.get(u_ptr)
            if u_state >= 1:
                self.dead_unit_latch[u_ptr] = {
                    "info_ptr": info_ptr_now if is_valid_ptr(info_ptr_now) else 0,
                    "latched_at": now,
                }
                continue
            if latch_meta:
                latched_info_ptr = int(latch_meta.get("info_ptr") or 0)
                info_ptr_changed = (
                    is_valid_ptr(info_ptr_now)
                    and is_valid_ptr(latched_info_ptr)
                    and info_ptr_now != latched_info_ptr
                )
                info_ptr_reborn = (
                    is_valid_ptr(info_ptr_now) and not is_valid_ptr(latched_info_ptr)
                )
                if info_ptr_changed or info_ptr_reborn:
                    del self.dead_unit_latch[u_ptr]
                else:
                    continue

            # Team filter
            if u_team == 0 or (effective_my_team != 0 and u_team == effective_my_team):
                continue

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

            # Resolve name
            resolved_name = short_name
            if (not resolved_name) or (resolved_name.lower() in ("none", "unknown", "c")):
                resolved_name = unit_name
            if (not resolved_name) or (len(resolved_name) < 2) or (resolved_name.lower() in ("unknown", "c", "none")):
                resolved_name = profile.get("display_name") or "unknown"

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

            # Pre-stabilize velocity for ground targets
            pre_vel = None
            if not resolved_is_air and self._stabilize_velocity:
                pre_vel = self._stabilize_velocity(u_ptr, False, pos, now)

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
            )

            # Pre-fetch box data (heavy memory read)
            try:
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

                # Update pos from box_data if available
                if t_snap.box_data:
                    t_snap.pos = t_snap.box_data[0] or t_snap.pos
            except Exception:
                pass

            # Pre-fetch bbox & rotation
            try:
                t_snap.bmin, t_snap.bmax = get_unit_bbox(self.scanner, u_ptr)
                t_snap.rot = get_unit_rotation(self.scanner, u_ptr)
            except Exception:
                pass

            # Pre-fetch barrel data
            try:
                if t_snap.box_data:
                    t_snap.barrel_data = get_weapon_barrel(
                        self.scanner, u_ptr,
                        t_snap.pos, t_snap.box_data[3],
                        should_log=True,
                    )
            except Exception:
                pass

            valid_targets.append(t_snap)

        # Clean profile cache
        for ptr in list(self.profile_cache.keys()):
            if ptr not in current_seen_ptrs:
                del self.profile_cache[ptr]

        snap.valid_targets = valid_targets
        snap.is_valid = True
        return snap
