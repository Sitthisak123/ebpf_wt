import sys
import time

# ==========================================
# Debug control
# ==========================================
DEBUG_MODE = True
DEBUG_THROTTLE = 1.0

# Sticky dashboard mode: avoid printing large periodic debug blocks
# to keep terminal output readable.
DASHBOARD_MODE = False

_last_print_time = 0.0


def set_dashboard_mode(enabled: bool):
    global DASHBOARD_MODE
    DASHBOARD_MODE = bool(enabled)


def _emit(line: str):
    stream = sys.stderr if DASHBOARD_MODE else sys.stdout
    stream.write(line + "\n")
    stream.flush()


def dprint(msg, force=False):
    """Print debug message when DEBUG_MODE is enabled."""
    global _last_print_time
    if not DEBUG_MODE:
        return

    current_time = time.time()
    if force or (current_time - _last_print_time >= DEBUG_THROTTLE):
        _emit(f"[DEBUG] {msg}")
        if not force:
            _last_print_time = current_time


def dprint_frame_stats(fps, cgame_base, matrix_ok, total_units, valid_targets, my_unit_ok):
    """
    Print periodic frame stats.
    Disabled in DASHBOARD_MODE to prevent mixed/garbled terminal output.
    """
    global _last_print_time
    if not DEBUG_MODE or DASHBOARD_MODE:
        return

    current_time = time.time()
    if current_time - _last_print_time >= DEBUG_THROTTLE:
        _emit("\n" + "=" * 45)
        _emit(f"FPS          : {fps:.1f}")
        _emit(f"CGame Base   : {hex(cgame_base) if cgame_base else 'NOT FOUND'}")
        _emit(f"View Matrix  : {'OK' if matrix_ok else 'FAILED (OFF_CAMERA_PTR/OFF_VIEW_MATRIX)'}")
        _emit(f"My Unit      : {'FOUND' if my_unit_ok else 'NOT FOUND (DAT_CONTROLLED_UNIT?)'}")
        _emit(f"Total Units  : {total_units}")
        _emit(f"Valid Targets: {valid_targets}")
        if total_units > 0 and valid_targets == 0:
            _emit("WARNING: units found but all filtered out")
        _emit("=" * 45)
        _last_print_time = current_time
