# Runtime Geometry Checklist

Purpose:
- Turn resolved game geometry into a full-dynamic runtime aim path.

## Inputs

- [ ] `my_pos`
- [ ] `my_rot`
- [ ] `my_local_axes`
- [ ] `my_gun_origin`
- [ ] `my_sight_origin`
- [ ] `target_pos`
- [ ] `target_rot`
- [ ] `target_body_bbox`
- [ ] `target_turret_bbox`
- [ ] optional `target_hit_bone`
- [ ] projectile profile
- [ ] active view matrix

## Phase 1: My Vehicle Geometry

- [ ] Compute `my_parallax_local = my_sight_origin - my_gun_origin`
- [ ] Split local delta into:
  - [ ] forward
  - [ ] up
  - [ ] lateral
- [ ] Verify signs in untilted and tilted states.

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

- [ ] If `my_sight_origin` missing:
  - [ ] fallback to first-person camera estimate
- [ ] If target body/turret geometry missing:
  - [ ] fallback to bbox-derived center
- [ ] If dynamic path invalid:
  - [ ] fallback to `vertical_baseline_table.json`

## Config / Flags

- [ ] Add `DYNAMIC_GEOMETRY_ENABLE`
- [ ] Add `DYNAMIC_GEOMETRY_COMPARE_FALLBACK`
- [ ] Add debug draw for:
  - [ ] target geometry point
  - [ ] ballistic world impact
  - [ ] parallax-adjusted impact

## Validation

- [ ] Test first-person untilted.
- [ ] Test first-person tilted-left.
- [ ] Test first-person tilted-right.
- [ ] Test near / mid / far distance.
- [ ] Test APFSDS first before HE/full-cal.

## Success Criteria

- [ ] No per-vehicle baseline required for primary path.
- [ ] Small residual correction only.
- [ ] Tilt no longer forces manual retune.
