# Runtime Geometry Checklist

Purpose:
- Turn resolved game geometry into a full-dynamic runtime aim path.

## Inputs

- [x] `my_pos`
- [x] `my_rot`
- [x] `my_local_axes`
- [x] `my_gun_origin`
- [x] `my_sight_origin`
- [x] `target_pos`
- [x] `target_rot`
- [ ] `target_body_bbox`
- [x] `target_turret_bbox`
- [ ] optional `target_hit_bone`
- [x] projectile profile
- [x] active view matrix

## Phase 1: My Vehicle Geometry

- [x] Compute `my_parallax_local = my_sight_origin - my_gun_origin`
- [ ] Split local delta into:
  - [x] forward
  - [x] up
  - [x] lateral
- [x] Verify signs in untilted and tilted states.

## Phase 2: Target Aim Geometry

- [ ] Choose body/turret aimpoint in target-local space.
- [ ] Convert target-local aimpoint to world-space.
- [ ] Keep current bbox-center path as fallback.

## Phase 3: Ballistic Solve

- [ ] Solve impact time from projectile profile.
- [ ] Apply gravity / drag.
- [ ] Apply my-velocity compensation.
- [ ] Apply target-velocity compensation.

## Phase 4: Parallax Solve

- [ ] Convert `my_parallax_local` to world offset using my local axes.
- [ ] Apply parallax world offset after ballistic solve.
- [ ] Verify sign behavior when tilted left/right.

## Phase 5: Projection / Rendering

- [ ] Project final world impact to screen.
- [ ] Use same point for leadmark and hitpoint when appropriate.
- [ ] Keep `vertical_correction` as residual override only.

## Fallback Strategy

- [x] If `my_sight_origin` missing:
  - [x] fallback to first-person camera estimate
- [ ] If target body/turret geometry missing:
  - [x] fallback to bbox-derived center
- [x] If dynamic path invalid:
  - [x] fallback to `vertical_baseline_table.json`

## Config / Flags

- [ ] Add `DYNAMIC_GEOMETRY_ENABLE`
- [ ] Add `DYNAMIC_GEOMETRY_COMPARE_FALLBACK`
- [ ] Add debug draw for:
  - [ ] target geometry point
  - [ ] ballistic world impact
  - [ ] parallax-adjusted impact

## Validation

- [x] Test first-person untilted.
- [x] Test first-person tilted-left.
- [x] Test first-person tilted-right.
- [x] Test near / mid / far distance.
- [x] Test APFSDS first before HE/full-cal.

## Success Criteria

- [ ] No per-vehicle baseline required for primary path.
- [ ] Small residual correction only.
- [ ] Tilt no longer forces manual retune.

## Current Runtime Notes

- `my_sight_origin`
  - current runtime fallback is first-person active camera position
  - next candidate from Ghidra: `gunnerOpticFps[].pos`
- `target_turret_bbox`
  - current runtime candidate winner is `0x1f90 / 0x1f9c`
  - secondary candidate is `0x1f78 / 0x1f84`
  - `0x1f80 / 0x1f8c` is currently rejected
- current stable production fallback remains `vertical_baseline_table.json`
- optics runtime note:
  - first-person `camera_local - barrel_base_local` was stable on tested vehicle
  - third-person should not be trusted unless separately validated
