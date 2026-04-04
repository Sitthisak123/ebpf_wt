import math
import os
import re
import select
import struct
import sys
import threading

from PyQt5.QtCore import Qt, QTimer, QRectF
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QWidget

try:
    import keyboard
    HAS_KEYBOARD = True
except Exception:
    keyboard = None
    HAS_KEYBOARD = False

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.scanner import MemoryScanner, get_game_base_address, get_game_pid, init_dynamic_offsets
import src.utils.mul as mul

WINDOW_WIDTH = 760
WINDOW_HEIGHT = 760
FPS_MS = 50
DEFAULT_RANGE_METERS = 1200.0
MIN_RANGE_METERS = 150.0
MAX_RANGE_METERS = 12000.0
RANGE_STEP_RATIO = 1.25
LABEL_DISTANCE_METERS = 3500.0
MAX_UNITS_DRAW = 256
RING_COUNT = 4
GROUND_DOT_RADIUS = 4.0
AIR_DOT_RADIUS = 5.0
VIEW_SAMPLE_STEP_METERS = 10.0
VIEW_PROBE_SCREEN_W = 1920
VIEW_PROBE_SCREEN_H = 1080
VIEW_TARGET_ALIGNMENT_THRESHOLD = 0.98
VIEW_SCAN_DEGREES = (
    0.0, 30.0, 45.0, 60.0, 90.0, 120.0, 135.0, 150.0,
    180.0, 210.0, 225.0, 240.0, 270.0, 300.0, 315.0, 330.0,
)
GLOBAL_KEY_POLL_MS = 35
GLOBAL_HOTKEYS = {
    "f2": "prev_variant",
    "f3": "next_variant",
    "f6": "zoom_in",
    "f7": "zoom_out",
    "f8": "toggle_view",
    "f9": "toggle_labels",
    "pause": "toggle_freeze",
    "f10": "reset_zoom",
}
RAW_KEYBOARD_CODES = {
    60: "prev_variant",   # F2
    61: "next_variant",   # F3
    64: "zoom_in",        # F6
    65: "zoom_out",       # F7
    66: "toggle_view",    # F8
    67: "toggle_labels",  # F9
    68: "reset_zoom",     # F10
    119: "toggle_freeze", # Pause
}
INPUT_EVENT_STRUCT = struct.Struct("llHHI")

COLOR_BG = QColor(8, 10, 12, 235)
COLOR_GRID = QColor(70, 78, 88, 150)
COLOR_RING = QColor(120, 132, 146, 120)
COLOR_TEXT = QColor(220, 228, 236)
COLOR_SELF = QColor(80, 220, 120)
COLOR_FRIEND = QColor(90, 170, 255)
COLOR_ENEMY = QColor(255, 110, 110)
COLOR_NEUTRAL = QColor(255, 210, 90)
COLOR_AIR = QColor(180, 140, 255)
VIEWDIR_VARIANTS = (
    ("xz", QColor(255, 255, 255)),
    ("zx", QColor(255, 170, 60)),
    ("xy", QColor(255, 120, 120)),
    ("yx", QColor(255, 210, 120)),
    ("yz", QColor(180, 255, 120)),
    ("zy", QColor(120, 255, 180)),
    ("-xz", QColor(255, 90, 90)),
    ("x-z", QColor(255, 220, 90)),
    ("-x-z", QColor(120, 220, 120)),
    ("-zx", QColor(80, 220, 220)),
    ("z-x", QColor(120, 160, 255)),
    ("-z-x", QColor(220, 120, 255)),
    ("-xy", QColor(255, 80, 150)),
    ("x-y", QColor(255, 180, 180)),
    ("-x-y", QColor(255, 120, 210)),
    ("-yx", QColor(220, 255, 120)),
    ("y-x", QColor(180, 255, 80)),
    ("-y-x", QColor(120, 255, 120)),
    ("-yz", QColor(120, 255, 220)),
    ("y-z", QColor(80, 220, 255)),
    ("-y-z", QColor(120, 200, 255)),
    ("-zy", QColor(150, 150, 255)),
    ("z-y", QColor(200, 120, 255)),
    ("-z-y", QColor(255, 120, 220)),
)


def _read_team(scanner, unit_ptr):
    if not mul.is_valid_ptr(unit_ptr) or mul.OFF_UNIT_TEAM == 0:
        return -1
    raw = scanner.read_mem(unit_ptr + mul.OFF_UNIT_TEAM, 1)
    if not raw or len(raw) < 1:
        return -1
    return raw[0]


def _read_rotation(scanner, unit_ptr):
    raw = scanner.read_mem(unit_ptr + mul.OFF_UNIT_ROTATION, 36)
    if not raw or len(raw) < 36:
        return None
    values = struct.unpack("<9f", raw)
    if any(not math.isfinite(v) for v in values):
        return None
    return values


def _heading_vector_from_rotation(rot):
    if not rot:
        return (0.0, 1.0)
    ax, _, _ = mul.get_local_axes_from_rotation(rot, is_air=False)
    hx = float(ax[0])
    hz = float(ax[2])
    mag = math.hypot(hx, hz)
    if mag <= 1e-6:
        return (0.0, 1.0)
    return (hx / mag, hz / mag)


def _rotate_into_heading(dx, dz, heading_x, heading_z):
    right_x = heading_z
    right_z = -heading_x
    local_x = (dx * right_x) + (dz * right_z)
    local_y = (dx * heading_x) + (dz * heading_z)
    return local_x, local_y


def _view_axis_scores_from_projection(scanner, cgame_ptr, my_pos):
    matrix = mul.get_view_matrix(scanner, cgame_ptr)
    if not matrix or not my_pos:
        return None

    center = mul.world_to_screen(matrix, my_pos[0], my_pos[1], my_pos[2], VIEW_PROBE_SCREEN_W, VIEW_PROBE_SCREEN_H)
    if not center:
        return None

    cx, cy = center[0], center[1]
    axis_scores = {}
    for axis_name, probe_pos in (
        ("x", (my_pos[0] + VIEW_SAMPLE_STEP_METERS, my_pos[1], my_pos[2])),
        ("y", (my_pos[0], my_pos[1] + VIEW_SAMPLE_STEP_METERS, my_pos[2])),
        ("z", (my_pos[0], my_pos[1], my_pos[2] + VIEW_SAMPLE_STEP_METERS)),
    ):
        probe = mul.world_to_screen(matrix, probe_pos[0], probe_pos[1], probe_pos[2], VIEW_PROBE_SCREEN_W, VIEW_PROBE_SCREEN_H)
        if not probe:
            continue
        delta_x = probe[0] - cx
        delta_y = probe[1] - cy
        delta_len = math.hypot(delta_x, delta_y)
        if delta_len <= 1e-3:
            continue
        axis_scores[axis_name] = {
            "screen_dx": delta_x,
            "screen_dy": delta_y,
            "screen_len": delta_len,
            "up_score": (-delta_y * 1000.0) - abs(delta_x) - abs(delta_len - 40.0) * 0.25,
        }
    return axis_scores


def _viewdir_variants(axis_scores):
    if not axis_scores:
        return []
    base = {
        "x": float(axis_scores.get("x", {}).get("up_score", 0.0)),
        "y": float(axis_scores.get("y", {}).get("up_score", 0.0)),
        "z": float(axis_scores.get("z", {}).get("up_score", 0.0)),
    }
    raw = {
        "xz": (base["x"], base["z"]),
        "zx": (base["z"], base["x"]),
        "xy": (base["x"], base["y"]),
        "yx": (base["y"], base["x"]),
        "yz": (base["y"], base["z"]),
        "zy": (base["z"], base["y"]),
        "-xz": (-base["x"], base["z"]),
        "x-z": (base["x"], -base["z"]),
        "-x-z": (-base["x"], -base["z"]),
        "-zx": (-base["z"], base["x"]),
        "z-x": (base["z"], -base["x"]),
        "-z-x": (-base["z"], -base["x"]),
        "-xy": (-base["x"], base["y"]),
        "x-y": (base["x"], -base["y"]),
        "-x-y": (-base["x"], -base["y"]),
        "-yx": (-base["y"], base["x"]),
        "y-x": (base["y"], -base["x"]),
        "-y-x": (-base["y"], -base["x"]),
        "-yz": (-base["y"], base["z"]),
        "y-z": (base["y"], -base["z"]),
        "-y-z": (-base["y"], -base["z"]),
        "-zy": (-base["z"], base["y"]),
        "z-y": (base["z"], -base["y"]),
        "-z-y": (-base["z"], -base["y"]),
    }
    out = []
    for name, color in VIEWDIR_VARIANTS:
        vx, vz = raw[name]
        mag = math.hypot(vx, vz)
        if mag <= 1e-6:
            continue
        out.append({
            "name": name,
            "vec": (vx / mag, vz / mag),
            "color": color,
        })
    return out


def _safe_label(scanner, unit_ptr):
    dna = mul.get_unit_detailed_dna(scanner, unit_ptr) or {}
    short_name = (dna.get("short_name") or "").strip()
    name_key = (dna.get("name_key") or "").strip()
    family = (dna.get("family") or "").strip()
    if short_name and short_name != "None":
        return short_name
    if name_key and name_key != "None":
        return name_key
    if family and family != "None":
        return family
    return hex(unit_ptr)


class TopdownMap(QWidget):
    def __init__(self, scanner, base_addr):
        super().__init__()
        self.scanner = scanner
        self.base_addr = base_addr
        self.range_m = DEFAULT_RANGE_METERS
        self.follow_view = True
        self.show_labels = True
        self.freeze = False
        self.samples = []
        self.last_error = ""
        self.last_view_forward = (0.0, 1.0)
        self.follow_variant_name = "xz"
        self._hotkey_handles = []
        self._raw_input_thread = None
        self._raw_input_stop = False

        self.setWindowTitle("WTM 2D Map")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setMinimumSize(520, 520)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setStyleSheet("background-color: rgb(8, 10, 12);")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(FPS_MS)

        print("================================================================================")
        print("TOPDOWN 2D MAP")
        print("================================================================================")
        print("Keys:")
        print("  +/-      = zoom")
        print("  R        = toggle view-up")
        print("  L        = toggle labels")
        print("  Space    = freeze/unfreeze")
        print("  0        = reset zoom")
        print("  Esc      = quit")
        if HAS_KEYBOARD:
            print("Global keys:")
            print("  F2/F3    = prev/next viewDir")
            print("  F6/F7    = zoom in/out")
            print("  F8       = toggle view-up")
            print("  F9       = toggle labels")
            print("  Pause    = freeze/unfreeze")
            print("  F10      = reset zoom")
        print("--------------------------------------------------------------------------------")

        if HAS_KEYBOARD:
            self._register_global_hotkeys()
        self._start_raw_input_listener()

    def _tick(self):
        if not self.freeze:
            try:
                self.samples = self._collect_units()
                self.last_error = ""
            except Exception as exc:
                self.last_error = str(exc)
        self.update()

    def _apply_action(self, action):
        if action == "zoom_in":
            self.range_m = max(MIN_RANGE_METERS, self.range_m / RANGE_STEP_RATIO)
        elif action == "zoom_out":
            self.range_m = min(MAX_RANGE_METERS, self.range_m * RANGE_STEP_RATIO)
        elif action == "reset_zoom":
            self.range_m = DEFAULT_RANGE_METERS
        elif action == "toggle_view":
            self.follow_view = not self.follow_view
        elif action == "toggle_labels":
            self.show_labels = not self.show_labels
        elif action == "toggle_freeze":
            self.freeze = not self.freeze
        elif action == "prev_variant":
            self._cycle_follow_variant(-1)
        elif action == "next_variant":
            self._cycle_follow_variant(1)

    def _cycle_follow_variant(self, step):
        names = [name for name, _ in VIEWDIR_VARIANTS]
        if not names:
            return
        try:
            idx = names.index(self.follow_variant_name)
        except ValueError:
            idx = 0
        self.follow_variant_name = names[(idx + step) % len(names)]

    def _register_global_hotkeys(self):
        if not HAS_KEYBOARD:
            return
        self._unregister_global_hotkeys()
        for key_name, action in GLOBAL_HOTKEYS.items():
            try:
                handle = keyboard.add_hotkey(
                    key_name,
                    lambda act=action: self._apply_action(act),
                    suppress=False,
                    trigger_on_release=False,
                )
                self._hotkey_handles.append(handle)
            except Exception:
                pass

    def _unregister_global_hotkeys(self):
        if not HAS_KEYBOARD:
            return
        for handle in self._hotkey_handles:
            try:
                keyboard.remove_hotkey(handle)
            except Exception:
                pass
        self._hotkey_handles = []

    def _discover_keyboard_event_paths(self):
        paths = []
        try:
            with open("/proc/bus/input/devices", "r", encoding="utf-8", errors="ignore") as f:
                blocks = f.read().split("\n\n")
        except Exception:
            return paths

        for block in blocks:
            if "Handlers=" not in block or "kbd" not in block:
                continue
            name_match = re.search(r'^N: Name="([^"]+)"', block, re.M)
            handlers_match = re.search(r"^H: Handlers=(.+)$", block, re.M)
            if not handlers_match:
                continue
            name = (name_match.group(1).lower() if name_match else "")
            if any(x in name for x in ("power button", "sleep button")):
                continue
            handlers = handlers_match.group(1).split()
            for handler in handlers:
                if handler.startswith("event"):
                    path = f"/dev/input/{handler}"
                    if os.path.exists(path) and path not in paths:
                        paths.append(path)
        return paths

    def _start_raw_input_listener(self):
        self._raw_input_stop = False
        self._raw_input_thread = threading.Thread(target=self._raw_input_worker, daemon=True)
        self._raw_input_thread.start()

    def _raw_input_worker(self):
        event_paths = self._discover_keyboard_event_paths()
        fds = []
        for path in event_paths:
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except Exception:
                continue
            fds.append(fd)
        if not fds:
            return

        try:
            while not self._raw_input_stop:
                try:
                    readable, _, _ = select.select(fds, [], [], 0.1)
                except Exception:
                    continue
                for fd in readable:
                    while True:
                        try:
                            data = os.read(fd, INPUT_EVENT_STRUCT.size)
                        except BlockingIOError:
                            break
                        except Exception:
                            break
                        if not data or len(data) < INPUT_EVENT_STRUCT.size:
                            break
                        _sec, _usec, ev_type, ev_code, ev_value = INPUT_EVENT_STRUCT.unpack(data[:INPUT_EVENT_STRUCT.size])
                        if ev_type != 1 or ev_value != 1:
                            continue
                        action = RAW_KEYBOARD_CODES.get(ev_code)
                        if action:
                            self._apply_action(action)
        finally:
            for fd in fds:
                try:
                    os.close(fd)
                except Exception:
                    pass

    def _collect_units(self):
        my_unit, my_team = mul.get_local_team(self.scanner, self.base_addr)
        cgame = mul.get_cgame_base(self.scanner, self.base_addr)
        if not mul.is_valid_ptr(my_unit) or not mul.is_valid_ptr(cgame):
            return []

        my_pos = mul.get_unit_pos(self.scanner, my_unit)
        if not my_pos:
            return []

        heading = _heading_vector_from_rotation(_read_rotation(self.scanner, my_unit))
        axis_scores = _view_axis_scores_from_projection(self.scanner, cgame, my_pos)
        if axis_scores:
            self.last_view_forward = (
                float(axis_scores.get("x", {}).get("up_score", 0.0)),
                float(axis_scores.get("z", {}).get("up_score", 0.0)),
            )
        base_view_variants = _viewdir_variants(axis_scores or {
            "x": {"up_score": self.last_view_forward[0]},
            "z": {"up_score": self.last_view_forward[1]},
            "y": {"up_score": 0.0},
        })
        chosen_variant = next((row for row in base_view_variants if row["name"] == self.follow_variant_name), None)
        if not chosen_variant and base_view_variants:
            chosen_variant = base_view_variants[0]
            self.follow_variant_name = chosen_variant["name"]
        active_forward = chosen_variant["vec"] if (self.follow_view and chosen_variant) else heading
        view_variants = base_view_variants
        rows = [{
            "unit_ptr": my_unit,
            "is_self": True,
            "is_air": False,
            "team": my_team,
            "label": "MY",
            "distance": 0.0,
            "map_x": 0.0,
            "map_y": 0.0,
        }]

        for u_ptr, is_air in mul.get_all_units(self.scanner, cgame)[:MAX_UNITS_DRAW]:
            if not mul.is_valid_ptr(u_ptr) or u_ptr == my_unit:
                continue
            pos = mul.get_unit_pos(self.scanner, u_ptr)
            if not pos:
                continue
            dx = float(pos[0] - my_pos[0])
            dz = float(pos[2] - my_pos[2])
            dy = float(pos[1] - my_pos[1])
            planar = math.hypot(dx, dz)
            if planar > self.range_m:
                continue

            map_x = dx
            map_y = dz
            if self.follow_view:
                map_x, map_y = _rotate_into_heading(dx, dz, active_forward[0], active_forward[1])

            rows.append({
                "unit_ptr": u_ptr,
                "is_self": False,
                "is_air": bool(is_air),
                "team": _read_team(self.scanner, u_ptr),
                "label": _safe_label(self.scanner, u_ptr),
                "distance": planar,
                "height_delta": dy,
                "map_x": map_x,
                "map_y": map_y,
            })
        rows[0]["view_forward"] = [round(active_forward[0], 4), round(active_forward[1], 4)]
        rows[0]["vehicle_forward"] = [round(heading[0], 4), round(heading[1], 4)]
        rows[0]["view_variants"] = [
            {"name": row["name"], "vec": [round(row["vec"][0], 4), round(row["vec"][1], 4)]}
            for row in view_variants
        ]
        rows[0]["follow_variant_name"] = self.follow_variant_name
        rows[0]["view_axis_scores"] = {
            key: round(val.get("up_score", 0.0), 3)
            for key, val in (axis_scores or {}).items()
        }
        return rows

    def _world_to_map(self, dx, dz, map_radius_px):
        scale = map_radius_px / max(self.range_m, 1.0)
        sx = (dx * scale)
        sy = (-dz * scale)
        return sx, sy

    def _pick_color(self, row, my_team):
        if row["is_self"]:
            return COLOR_SELF
        if row["team"] > 0 and my_team > 0:
            return COLOR_FRIEND if row["team"] == my_team else COLOR_ENEMY
        return COLOR_AIR if row["is_air"] else COLOR_NEUTRAL

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), COLOR_BG)

        width = self.width()
        height = self.height()
        cx = width * 0.5
        cy = height * 0.5
        pad = 56.0
        map_radius = max(80.0, min(width, height) * 0.5 - pad)

        self._draw_grid(painter, cx, cy, map_radius)
        self._draw_units(painter, cx, cy, map_radius)
        self._draw_hud(painter, cx, cy, map_radius)
        painter.end()

    def _draw_grid(self, painter, cx, cy, map_radius):
        painter.setPen(QPen(COLOR_RING, 1))
        for idx in range(1, RING_COUNT + 1):
            r = map_radius * (idx / RING_COUNT)
            painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        painter.setPen(QPen(COLOR_GRID, 1))
        painter.drawLine(int(cx - map_radius), int(cy), int(cx + map_radius), int(cy))
        painter.drawLine(int(cx), int(cy - map_radius), int(cx), int(cy + map_radius))

        painter.setPen(QPen(COLOR_TEXT, 1))
        font = QFont("DejaVu Sans Mono", 9)
        painter.setFont(font)
        for idx in range(1, RING_COUNT + 1):
            meters = self.range_m * (idx / RING_COUNT)
            painter.drawText(int(cx + 6), int(cy - (map_radius * (idx / RING_COUNT)) - 4), f"{meters:.0f}m")

    def _draw_units(self, painter, cx, cy, map_radius):
        my_team = next((row["team"] for row in self.samples if row["is_self"]), -1)
        font = QFont("DejaVu Sans Mono", 8)
        painter.setFont(font)

        for row in self.samples:
            px, py = self._world_to_map(row["map_x"], row["map_y"], map_radius)
            sx = cx + px
            sy = cy + py
            if math.hypot(px, py) > map_radius + 4:
                continue

            color = self._pick_color(row, my_team)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)

            if row["is_self"]:
                self._draw_self_marker(painter, sx, sy, map_radius)
                continue

            radius = AIR_DOT_RADIUS if row["is_air"] else GROUND_DOT_RADIUS
            painter.drawEllipse(QRectF(sx - radius, sy - radius, radius * 2, radius * 2))

            if row["is_air"]:
                painter.setPen(QPen(color, 1.2))
                painter.drawLine(int(sx), int(sy - 9), int(sx), int(sy + 9))
                painter.drawLine(int(sx - 9), int(sy), int(sx + 9), int(sy))
                painter.setPen(Qt.NoPen)

            if self.show_labels and row["distance"] <= LABEL_DISTANCE_METERS:
                painter.setPen(QPen(COLOR_TEXT, 1))
                label = f"{row['label']} {row['distance']:.0f}m"
                if row["is_air"]:
                    label += f" Δh:{row.get('height_delta', 0.0):.0f}"
                painter.drawText(int(sx + 8), int(sy - 8), label)

    def _draw_self_marker(self, painter, sx, sy, map_radius):
        painter.setBrush(COLOR_SELF)
        painter.setPen(QPen(COLOR_SELF, 1.5))
        painter.drawEllipse(QRectF(sx - 6, sy - 6, 12, 12))
        painter.drawLine(int(sx), int(sy - 14), int(sx), int(sy + 14))
        painter.drawLine(int(sx - 14), int(sy), int(sx + 14), int(sy))
        view_variants = []
        follow_name = self.follow_variant_name
        variant_hits = {}
        for row in self.samples:
            if row.get("is_self"):
                for item in row.get("view_variants") or []:
                    vec = item.get("vec") or [0.0, 0.0]
                    if len(vec) != 2:
                        continue
                    color = next((c for n, c in VIEWDIR_VARIANTS if n == item.get("name")), COLOR_TEXT)
                    view_variants.append({
                        "name": item.get("name"),
                        "vec": (float(vec[0]), float(vec[1])),
                        "color": color,
                    })
                follow_name = row.get("follow_variant_name") or follow_name
                break
        if view_variants:
            base_len = 28.0
            for idx, variant in enumerate(view_variants):
                vx, vz = variant["vec"]
                right_x = vz
                right_y = -vx
                dir_x = vz
                dir_y = -vx
                dir_mag = math.hypot(dir_x, dir_y)
                if dir_mag <= 1e-6:
                    continue
                dir_x /= dir_mag
                dir_y /= dir_mag

                best_hit = None
                best_score = 0.0
                for row in self.samples:
                    if row.get("is_self"):
                        continue
                    px, py = self._world_to_map(row["map_x"], row["map_y"], map_radius)
                    target_len = math.hypot(px, py)
                    if target_len < 8.0:
                        continue
                    target_dx = px / target_len
                    target_dy = py / target_len
                    alignment = (dir_x * target_dx) + (dir_y * target_dy)
                    if alignment < VIEW_TARGET_ALIGNMENT_THRESHOLD:
                        continue
                    if alignment > best_score:
                        best_score = alignment
                        best_hit = {
                            "label": row.get("label", "?"),
                            "distance": row.get("distance", 0.0),
                            "screen_len": target_len,
                            "alignment": alignment,
                        }

                arrow_len = base_len - (idx * 1.5)
                if best_hit:
                    arrow_len = min(max(arrow_len, best_hit["screen_len"]), map_radius * 0.95)
                    variant_hits[variant["name"]] = best_hit
                end_x = sx + (vz * arrow_len)
                end_y = sy + (-vx * arrow_len)
                line_width = 2.6 if variant["name"] == follow_name else 1.2
                painter.setPen(QPen(variant["color"], line_width))
                painter.drawLine(int(sx), int(sy), int(end_x), int(end_y))
                painter.drawLine(int(end_x), int(end_y), int(end_x - 6 - right_x * 2), int(end_y + 6 - right_y * 2))
                painter.drawLine(int(end_x), int(end_y), int(end_x - 6 + right_x * 2), int(end_y + 6 + right_y * 2))
                if best_hit and variant["name"] == follow_name:
                    painter.setPen(QPen(variant["color"], 1))
                    painter.drawText(int(end_x + 8), int(end_y - 8), f"{best_hit['label']} {best_hit['distance']:.0f}m")

        self._last_variant_hits = variant_hits

    def _draw_hud(self, painter, cx, cy, map_radius):
        painter.setPen(QPen(COLOR_TEXT, 1))
        font = QFont("DejaVu Sans Mono", 9)
        painter.setFont(font)

        enemies = sum(1 for row in self.samples if not row["is_self"] and row["team"] > 0 and row["team"] != self.samples[0]["team"])
        friends = sum(1 for row in self.samples if not row["is_self"] and row["team"] > 0 and row["team"] == self.samples[0]["team"])
        air = sum(1 for row in self.samples if row.get("is_air") and not row["is_self"])
        ground = sum(1 for row in self.samples if (not row.get("is_air")) and not row["is_self"])

        lines = [
            f"Center: MY UNIT",
            f"Range: {self.range_m:.0f}m",
            f"Mode: {'view-up' if self.follow_view else 'north-up'}",
            f"Units: {max(0, len(self.samples) - 1)} | Friend:{friends} Enemy:{enemies} Air:{air} Ground:{ground}",
            "Keys: +/- zoom | R view-up | L labels | Space freeze | 0 reset | Esc quit",
            "Global: F2/F3 variant | F6/F7 zoom | F8 view | F9 labels | Pause freeze | F10 reset",
        ]
        if self.samples:
            self_row = self.samples[0]
            vf = self_row.get("view_forward")
            if vf:
                lines.append(f"ViewDir XZ: ({vf[0]:.3f}, {vf[1]:.3f})")
            axis_scores = self_row.get("view_axis_scores") or {}
            if axis_scores:
                lines.append(
                    f"AxisScore: X={axis_scores.get('x', 0.0):.1f} "
                    f"Y={axis_scores.get('y', 0.0):.1f} "
                    f"Z={axis_scores.get('z', 0.0):.1f}"
                )
            variants = self_row.get("view_variants") or []
            if variants:
                variant_chunks = []
                for item in variants[:4]:
                    vec = item.get("vec") or [0.0, 0.0]
                    variant_chunks.append(f"{item.get('name')}=({vec[0]:.2f},{vec[1]:.2f})")
                lines.append("VD A: " + " | ".join(variant_chunks))
                variant_chunks = []
                for item in variants[4:8]:
                    vec = item.get("vec") or [0.0, 0.0]
                    variant_chunks.append(f"{item.get('name')}=({vec[0]:.2f},{vec[1]:.2f})")
                lines.append("VD B: " + " | ".join(variant_chunks))
            follow_name = self_row.get("follow_variant_name") or self.follow_variant_name
            follow_color = COLOR_TEXT
            for name, color in VIEWDIR_VARIANTS:
                if name == follow_name:
                    follow_color = color
                    break
            y = 22
            for line in lines:
                painter.setPen(QPen(COLOR_TEXT, 1))
                painter.drawText(16, y, line)
                y += 18
            painter.setPen(QPen(follow_color, 1))
            painter.drawText(16, y, f"Following ViewDir: {follow_name}")
            y += 18
            hit = getattr(self, "_last_variant_hits", {}).get(follow_name)
            if hit:
                painter.drawText(16, y, f"Following points to: {hit['label']} {hit['distance']:.0f}m")
                y += 18
            painter.setPen(QPen(COLOR_TEXT, 1))
            painter.drawText(int(cx - 24), int(cy - map_radius - 10), "N" if not self.follow_view else "VIEW")
            return
        if self.last_error:
            lines.append(f"Err: {self.last_error}")

        y = 22
        for line in lines:
            painter.drawText(16, y, line)
            y += 18

        painter.drawText(int(cx - 24), int(cy - map_radius - 10), "N" if not self.follow_view else "VIEW")

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Equal, Qt.Key_Plus):
            self._apply_action("zoom_in")
        elif key in (Qt.Key_Minus, Qt.Key_Underscore):
            self._apply_action("zoom_out")
        elif key == Qt.Key_0:
            self._apply_action("reset_zoom")
        elif key == Qt.Key_R:
            self._apply_action("toggle_view")
        elif key == Qt.Key_L:
            self._apply_action("toggle_labels")
        elif key == Qt.Key_BracketLeft:
            self._apply_action("prev_variant")
        elif key == Qt.Key_BracketRight:
            self._apply_action("next_variant")
        elif key == Qt.Key_Space:
            self._apply_action("toggle_freeze")
        elif key == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self._raw_input_stop = True
        self._unregister_global_hotkeys()
        super().closeEvent(event)


def main():
    pid = get_game_pid()
    if not pid:
        print("[-] ไม่พบ process ของเกม 'aces'")
        return

    base_addr = get_game_base_address(pid)
    scanner = MemoryScanner(pid)
    init_dynamic_offsets(scanner, base_addr)

    app = QApplication(sys.argv)
    window = TopdownMap(scanner, base_addr)
    window.show()
    exit_code = app.exec_()
    scanner.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
