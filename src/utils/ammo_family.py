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


# ==============================================================================
# 🎯 CALIBER & AMMUNITION BITFLAGS & ENUMS
# ==============================================================================
# Caliber Size Classes
CAL_FLAG_UNKNOWN      = 0
CAL_FLAG_AUTOCANNON   = 1 << 0  # 20mm - 40mm (or 57mm)
CAL_FLAG_LIGHT_GUN    = 1 << 1  # 57mm - 90mm
CAL_FLAG_MBT_CANNON   = 1 << 2  # 100mm - 125mm
CAL_FLAG_HOWITZER     = 1 << 3  # >= 130mm
CAL_FLAG_AIR_GUN      = 1 << 4  # Aircraft gun/cannon
CAL_FLAG_SUB_CALIBER  = 1 << 5  # Sub-caliber penetrator (APFSDS / APDS)

# Ammo Type Families
AMMO_FLAG_UNKNOWN     = 0
AMMO_FLAG_APFSDS      = 1 << 8  # Sub-caliber fin-stabilized dart
AMMO_FLAG_APDS        = 1 << 9  # Sub-caliber discarding sabot
AMMO_FLAG_HEATFS      = 1 << 10 # High-explosive anti-tank (shaped charge)
AMMO_FLAG_APHE        = 1 << 11 # Armor-piercing high-explosive / kinetic solid shot
AMMO_FLAG_HE_HESH     = 1 << 12 # High-explosive / squash head
AMMO_FLAG_ATGM        = 1 << 13 # Anti-tank guided missile
AMMO_FLAG_AUTOCANNON  = 1 << 14 # Rapid-fire autocannon shell


def classify_weapon_caliber(speed, caliber, mass=0.0, cx=0.0, vehicle_name="", is_air=False):
    """
    Classifies weapon caliber and ammunition type with Flags and String labels.
    Handles sub-caliber sabot darts (APFSDS/APDS), chemical shells (HEAT-FS),
    explosive shells (HE/HESH), kinetic rounds, autocannons, and aircraft cannons.
    """
    speed = _as_float(speed, 0.0)
    caliber = _as_float(caliber, 0.0)
    mass = _as_float(mass, 0.0)
    cx = _as_float(cx, 0.0)
    vname = (vehicle_name or "").lower()

    raw_cal_mm = caliber * 1000.0

    # ✈️ Aircraft Gun Classification
    if is_air:
        if raw_cal_mm < 15.0:
            cal_class = "AIR MG"
            cal_flag = CAL_FLAG_AIR_GUN
            ammo_type = "MG"
            ammo_flag = AMMO_FLAG_UNKNOWN
            hud_str = f"🔫 Gun : {raw_cal_mm:.1f}mm MG ({speed:.0f} m/s) [{cal_class}]"
        else:
            cal_class = "AIR CANNON"
            cal_flag = CAL_FLAG_AIR_GUN
            ammo_type = "CANNON"
            ammo_flag = AMMO_FLAG_AUTOCANNON
            hud_str = f"🔫 Gun : {raw_cal_mm:.0f}mm CANNON ({speed:.0f} m/s) [{cal_class}]"
        return {
            "ammo_type": ammo_type,
            "ammo_flag": ammo_flag,
            "cal_class": cal_class,
            "cal_flag": cal_flag,
            "effective_bore_mm": raw_cal_mm,
            "dart_caliber_mm": 0.0,
            "is_subcaliber": False,
            "hud_str": hud_str,
        }

    # 🛡️ Tank Vehicle Bore Lookup (Nominal Gun Caliber)
    known_bore = 0.0
    if any(k in vname for k in ("t_64", "t_72", "t_80", "t_90", "type_96", "type_99", "wz", "zsr", "ztz")):
        known_bore = 125.0
    elif any(k in vname for k in ("type_90", "type_10", "leopard_2", "m1a1", "m1a2", "leclerc", "ariete", "challenger_2", "challenger_3", "strv_121", "strv_122")):
        known_bore = 120.0
    elif any(k in vname for k in ("t_62",)):
        known_bore = 115.0
    elif any(k in vname for k in ("type_16", "type_74", "m60", "centurion_mk_10", "leopard_1", "strv_103", "m1_abrams", "ipm1", "vickers", "tam", "radkampfwagen")):
        known_bore = 105.0
    elif any(k in vname for k in ("t_54", "t_55", "su_100", "bmp_3")):
        known_bore = 100.0
    elif any(k in vname for k in ("m46", "m47", "m48", "type_61", "amx_13_90")):
        known_bore = 90.0
    elif any(k in vname for k in ("tiger", "ferdinand", "jagpanther", "nashorn")):
        known_bore = 88.0
    elif any(k in vname for k in ("t_34_85", "su_85")):
        known_bore = 85.0
    elif any(k in vname for k in ("is_2", "is_3", "is_4", "t_10", "2s1")):
        known_bore = 122.0
    elif any(k in vname for k in ("2s3", "isu_152", "kv_2", "object_268", "mbt_70", "kpf_70")):
        known_bore = 152.0
    elif any(k in vname for k in ("vidar", "m109", "bkan", "type_75", "g6", "palmaria", "au_f1")):
        known_bore = 155.0
    elif any(k in vname for k in ("fv4005", "fv215b")):
        known_bore = 183.0
    elif any(k in vname for k in ("2s38", "zsu_57", "t_34_57", "begleitpanzer")):
        known_bore = 57.0
    elif any(k in vname for k in ("strf_9040", "cv9040", "m42", "amx_13_dca")):
        known_bore = 40.0
    elif any(k in vname for k in ("gepard", "type_87", "marksman", "pgz_09")):
        known_bore = 35.0
    elif any(k in vname for k in ("bmp_2", "bmd_4", "tunguska", "pantsir", "freccia", "dardo", "vbc", "btr_80", "btr_82")):
        known_bore = 30.0
    elif any(k in vname for k in ("m3_bradley", "m2_bradley", "lav_25")):
        known_bore = 25.0

    # 🔬 Ammunition Type Identification
    is_subcaliber = (speed >= 1100.0 and caliber <= 0.045 and mass <= 9.0)

    if 50.0 < speed < 400.0:
        ammo_type = "ATGM"
        ammo_flag = AMMO_FLAG_ATGM
    elif is_subcaliber:
        if speed >= 1300.0 or caliber <= 0.025:
            ammo_type = "APFSDS"
            ammo_flag = AMMO_FLAG_APFSDS | CAL_FLAG_SUB_CALIBER
        else:
            ammo_type = "APDS"
            ammo_flag = AMMO_FLAG_APDS | CAL_FLAG_SUB_CALIBER
    elif caliber >= 0.065:
        if speed >= 850.0 and cx >= 0.18:
            ammo_type = "HEAT-FS"
            ammo_flag = AMMO_FLAG_HEATFS
        elif speed < 750.0 or mass >= 16.0:
            ammo_type = "HE/HESH"
            ammo_flag = AMMO_FLAG_HE_HESH
        else:
            ammo_type = "APHE"
            ammo_flag = AMMO_FLAG_APHE
    elif 0.015 <= caliber <= 0.057:
        if speed >= 1150.0:
            ammo_type = "APFSDS"
            ammo_flag = AMMO_FLAG_APFSDS | CAL_FLAG_AUTOCANNON
        else:
            ammo_type = "AUTO-AP"
            ammo_flag = AMMO_FLAG_AUTOCANNON | CAL_FLAG_AUTOCANNON
    else:
        ammo_type = "KINETIC"
        ammo_flag = AMMO_FLAG_UNKNOWN

    # 📐 Effective Bore & Caliber Class
    effective_bore = known_bore if known_bore > 0.0 else (raw_cal_mm if not is_subcaliber else 0.0)

    if effective_bore >= 130.0:
        cal_class = "HOWITZER"
        cal_flag = CAL_FLAG_HOWITZER
    elif effective_bore >= 95.0 or (is_subcaliber and mass >= 3.0):
        cal_class = "MBT CANNON"
        cal_flag = CAL_FLAG_MBT_CANNON
    elif effective_bore >= 55.0:
        cal_class = "MEDIUM GUN"
        cal_flag = CAL_FLAG_LIGHT_GUN
    elif effective_bore >= 18.0 or (is_subcaliber and mass < 3.0):
        cal_class = "AUTOCANNON"
        cal_flag = CAL_FLAG_AUTOCANNON
    else:
        cal_class = "CANNON"
        cal_flag = CAL_FLAG_UNKNOWN

    # 🎨 Build Clean HUD String
    bore_prefix = f"{int(effective_bore)}mm " if effective_bore > 0.0 else ""
    if is_subcaliber:
        hud_str = f"🔫 Gun : {bore_prefix}{ammo_type} (Dart: {raw_cal_mm:.0f}mm | {speed:.0f} m/s) [{cal_class}]"
    else:
        hud_str = f"🔫 Gun : {bore_prefix}{ammo_type} ({speed:.0f} m/s) [{cal_class}]"

    return {
        "ammo_type": ammo_type,
        "ammo_flag": ammo_flag,
        "cal_class": cal_class,
        "cal_flag": cal_flag,
        "effective_bore_mm": effective_bore,
        "dart_caliber_mm": raw_cal_mm if is_subcaliber else 0.0,
        "is_subcaliber": is_subcaliber,
        "hud_str": hud_str,
    }

