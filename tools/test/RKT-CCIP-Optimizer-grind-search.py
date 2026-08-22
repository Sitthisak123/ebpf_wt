"""
🚀 ROCKET CCIP PARAMETER OPTIMIZER V2 (with pitch offset)
Fits motor_accel, burn_time, drag_k_hi, drag_k_lo, pitch_deg
against sea-level telemetry data from dumps/2/ (0.1km to 0.1km).
"""
import math

TELEMETRY = [
    (0.00, 0,   0,    100),
    (0.16, 59,  5,    100),
    (0.33, 119, 20,   99),
    (0.49, 182, 44,   99),
    (0.66, 246, 80,   98),
    (0.82, 311, 125,  97),
    (0.99, 377, 182,  95),
    (1.15, 442, 250,  93),
    (1.32, 507, 328,  89),
    (1.48, 574, 417,  86),
    (1.65, 629, 517,  81),
    (1.81, 614, 619,  76),
    (1.98, 599, 719,  71),
    (2.14, 585, 817,  66),
    (2.31, 572, 912,  61),
    (2.47, 559, 1005, 56),
    (2.64, 546, 1096, 50),
    (2.80, 534, 1185, 45),
    (2.97, 522, 1272, 39),
    (3.13, 510, 1357, 33),
    (3.30, 498, 1440, 27),
    (3.46, 487, 1521, 21),
    (3.63, 477, 1600, 15),
    (3.79, 466, 1677, 9),
    (3.96, 456, 1753, 3),
    (4.04, 451, 1790, 0),
]

def smoothstep(edge0, edge1, x):
    if edge1 <= edge0:
        return 1.0 if x >= edge0 else 0.0
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)

def air_density_from_altitude(alt):
    alt = max(0.0, alt)
    return 1.225 * math.pow(max(1.0 - (2.25577e-5 * alt), 0.0), 4.2561)

def simulate(motor_accel, burn_time, drag_k_hi, drag_k_lo,
             drag_v_lo, drag_v_hi, pitch_deg=0.0,
             start_y=100.0, dt=0.005, max_time=5.0):
    x, y = 0.0, start_y
    vx, vy = 0.0, 0.0
    pitch_rad = math.radians(pitch_deg)
    fx = math.cos(pitch_rad)
    fy = math.sin(pitch_rad)  # negative pitch → downward
    g = 9.80665
    rho_sea = 1.225
    t = 0.0
    results = [(0.0, 0.0, 0.0, start_y)]
    while t < max_time and y > -10:
        speed = math.sqrt(vx*vx + vy*vy)
        blend = smoothstep(drag_v_lo, drag_v_hi, speed)
        drag_k = drag_k_lo + (drag_k_hi - drag_k_lo) * blend
        rho_ratio = air_density_from_altitude(y) / rho_sea
        drag_k_adj = drag_k * rho_ratio
        ax = -drag_k_adj * speed * vx
        ay = (-drag_k_adj * speed * vy) - g
        if t < burn_time:
            ax += motor_accel * fx
            ay += motor_accel * fy
        vx += ax * dt
        vy += ay * dt
        x += vx * dt
        y += vy * dt
        t += dt
        speed = math.sqrt(vx*vx + vy*vy)
        results.append((t, speed, x, y))
    return results

def evaluate(motor_accel, burn_time, drag_k_hi, drag_k_lo,
             drag_v_lo, drag_v_hi, pitch_deg):
    sim = simulate(motor_accel, burn_time, drag_k_hi, drag_k_lo,
                   drag_v_lo, drag_v_hi, pitch_deg)
    total_pos_err = 0.0
    total_speed_err = 0.0
    max_pos_err = 0.0
    count = 0
    for t_tel, spd_tel, x_tel, y_tel in TELEMETRY:
        best_idx = 0
        best_dt = abs(sim[0][0] - t_tel)
        for i, (t_sim, _, _, _) in enumerate(sim):
            dt_val = abs(t_sim - t_tel)
            if dt_val < best_dt:
                best_dt = dt_val
                best_idx = i
        t_sim, spd_sim, x_sim, y_sim = sim[best_idx]
        pos_err = math.sqrt((x_sim - x_tel)**2 + (y_sim - y_tel)**2)
        speed_err = abs(spd_sim - spd_tel)
        total_pos_err += pos_err
        total_speed_err += speed_err
        max_pos_err = max(max_pos_err, pos_err)
        count += 1
    return total_pos_err / count, total_speed_err / count, max_pos_err

def grid_search():
    best_score = float('inf')
    best_params = None
    best_errors = None

    motor_accels = [380, 385, 390, 395, 400]
    burn_times = [1.60, 1.65, 1.70, 1.75]
    drag_k_his = [0.000220, 0.000240, 0.000260]
    drag_k_los = [0.000060, 0.000080, 0.000100]
    pitch_degs = [-0.5, -0.8, -1.0, -1.2, -1.5, -1.8, -2.0, -2.5, -3.0]
    drag_v_lo = 320.0
    drag_v_hi = 500.0

    total = len(motor_accels) * len(burn_times) * len(drag_k_his) * len(drag_k_los) * len(pitch_degs)
    print(f"Grid search V2: {total} combinations...")
    checked = 0
    for ma in motor_accels:
        for bt in burn_times:
            for kh in drag_k_his:
                for kl in drag_k_los:
                    for pd in pitch_degs:
                        avg_pos, avg_spd, max_pos = evaluate(ma, bt, kh, kl, drag_v_lo, drag_v_hi, pd)
                        score = avg_pos + avg_spd * 0.5 + max_pos * 0.3
                        if score < best_score:
                            best_score = score
                            best_params = (ma, bt, kh, kl, drag_v_lo, drag_v_hi, pd)
                            best_errors = (avg_pos, avg_spd, max_pos)
                        checked += 1
                        if checked % 2000 == 0:
                            print(f"  [{checked}/{total}] best: score={best_score:.1f} pitch={best_params[6]:.1f}° pos_err={best_errors[0]:.1f}m")
    return best_params, best_errors, best_score

def print_comparison(ma, bt, kh, kl, vl, vh, pd):
    sim = simulate(ma, bt, kh, kl, vl, vh, pd)
    print(f"\n{'t(s)':<6} | {'Spd_Tel':<8} {'Spd_Sim':<8} {'Δspd':<6} | {'X_Tel':<8} {'X_Sim':<8} {'ΔX':<6} | {'Y_Tel':<8} {'Y_Sim':<8} {'ΔY':<6}")
    print("-" * 95)
    for t_tel, spd_tel, x_tel, y_tel in TELEMETRY:
        best_idx = 0
        best_dt = abs(sim[0][0] - t_tel)
        for i, (t_sim, _, _, _) in enumerate(sim):
            dt_val = abs(t_sim - t_tel)
            if dt_val < best_dt:
                best_dt = dt_val
                best_idx = i
        t_sim, spd_sim, x_sim, y_sim = sim[best_idx]
        print(f"{t_tel:<6.2f} | {spd_tel:<8} {spd_sim:<8.0f} {spd_sim-spd_tel:<+6.0f} | "
              f"{x_tel:<8} {x_sim:<8.0f} {x_sim-x_tel:<+6.0f} | "
              f"{y_tel:<8} {y_sim:<8.1f} {y_sim-y_tel:<+6.1f}")

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 ROCKET CCIP PARAMETER OPTIMIZER V2 (with pitch offset)")
    print("   Fitting to [0.1 km to 0.1 km] sea-level telemetry")
    print("=" * 60)
    params, errors, score = grid_search()
    ma, bt, kh, kl, vl, vh, pd = params
    avg_pos, avg_spd, max_pos = errors
    print(f"\n{'='*60}")
    print(f"✅ BEST FIT PARAMETERS:")
    print(f"{'='*60}")
    print(f"  MOTOR_ACCEL     = {ma:.1f}    # m/s²")
    print(f"  BURN_TIME       = {bt:.2f}    # s")
    print(f"  DRAG_K_HI       = {kh:.6f}   # sea-level high speed")
    print(f"  DRAG_K_LO       = {kl:.6f}   # sea-level low speed")
    print(f"  DRAG_V_LO       = {vl:.0f}")
    print(f"  DRAG_V_HI       = {vh:.0f}")
    print(f"  PITCH_OFFSET    = {pd:.1f}°   # launcher downward tilt")
    print(f"\n  Avg position error:  {avg_pos:.1f} m")
    print(f"  Avg speed error:     {avg_spd:.1f} m/s")
    print(f"  Max position error:  {max_pos:.1f} m")
    print_comparison(ma, bt, kh, kl, vl, vh, pd)

    print(f"\n{'='*60}")
    print(f"📋 READY-TO-PASTE CONSTANTS:")
    print(f"{'='*60}")
    print(f"""
# 🚁 HELICOPTER SPECIFIC ROCKET CCIP PARAMETERS (Fitted from dumps/2 telemetry [0.1km→0.1km])
HELI_ROCKET_LAUNCHER_PITCH_OFFSET_DEG = {pd}    # Launcher downward tilt (deg)
HELI_ROCKET_MOTOR_BURN_TIME           = {bt}    # Motor burn duration (s)
HELI_ROCKET_MOTOR_ACCEL               = {ma:.1f}   # Motor thrust accel (m/s²)
HELI_ROCKET_DRAG_K_HI                 = {kh:.6f} # Sea-level drag k (high speed >{vh:.0f} m/s)
HELI_ROCKET_DRAG_K_LO                 = {kl:.6f} # Sea-level drag k (low speed <{vl:.0f} m/s)
HELI_ROCKET_DRAG_V_LO                 = {vl:.0f}     # Speed threshold low
HELI_ROCKET_DRAG_V_HI                 = {vh:.0f}     # Speed threshold high
""")
