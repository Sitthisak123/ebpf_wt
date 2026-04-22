import math


def _as_float(value, default=0.0):
    try:
        value = float(value or 0.0)
    except Exception:
        return float(default)
    return value if math.isfinite(value) else float(default)


def _as_int(value, default=-1):
    try:
        return int(value)
    except Exception:
        return int(default)


def extract_cannon_size(doc):
    if not isinstance(doc, dict):
        return 0.0
    for key in ("cannon_size", "gun_caliber", "weapon_caliber", "bore_caliber"):
        value = _as_float(doc.get(key, 0.0), 0.0)
        if 0.001 <= value <= 0.5:
            return value
    return 0.0


def resolve_ammo_family(doc):
    doc = doc or {}
    speed = _as_float(doc.get("speed", 0.0), 0.0)
    caliber = _as_float(doc.get("caliber", 0.0), 0.0)
    mass = _as_float(doc.get("mass", 0.0), 0.0)
    bullet_type_idx = _as_int(doc.get("bullet_type_idx", -1), -1)
    cannon_size = extract_cannon_size(doc)

    bucket = "other"
    family = "other"
    reason = "fallback"

    subcaliber_by_size = (
        speed > 1000.0 and
        caliber > 0.0 and
        cannon_size > 0.0 and
        caliber < (cannon_size * 0.95)
    )
    subcaliber_by_shape = (
        speed > 1000.0 and
        caliber > 0.0 and
        caliber <= 0.05
    )
    subcaliber_like = subcaliber_by_size or subcaliber_by_shape

    if caliber >= 0.09:
        bucket = "he_fullcal_like"
        family = "he_fullcal_like"
        reason = "full_caliber_large_shell"
    elif subcaliber_like:
        if (
            speed >= 1350.0 or
            caliber <= 0.022 or
            (0.0 < mass <= 1.5 and caliber <= 0.03)
        ):
            bucket = "apfsds_like"
            family = "apfsds_like"
            reason = "high_speed_small_subcal"
        else:
            bucket = "apds_like"
            family = "apds_like"
            reason = "subcal_kinetic"
    elif speed >= 850.0 and caliber <= 0.06 and 0.0 < mass <= 3.0:
        bucket = "other"
        family = "kinetic_light_like"
        reason = "light_kinetic_but_not_subcal"

    signature = (
        f"bt={bullet_type_idx}|"
        f"s={speed:.3f}|c={caliber:.6f}|m={mass:.6f}|"
        f"cs={cannon_size:.6f}|fam={family}"
    )

    return {
        "bucket": bucket,
        "family": family,
        "reason": reason,
        "speed": speed,
        "caliber": caliber,
        "mass": mass,
        "bullet_type_idx": bullet_type_idx,
        "cannon_size": cannon_size,
        "signature": signature,
    }
