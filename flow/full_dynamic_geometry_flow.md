# Full Dynamic Geometry Flow

Purpose:
- Replace per-vehicle vertical baseline lookup with geometry-driven calculation from game data.
- Reduce manual calibration to residual fine-tune only.

## Goal

Compute final hitpoint from:
- `my gun origin`
- `my sight origin`
- `my local axes`
- `target body/turret bbox or target hit bone`
- `projectile profile`
- `camera/view projection`

Target result:
1. Build a world-space aimpoint from target geometry.
2. Apply projectile ballistics.
3. Apply sight-to-gun parallax from my vehicle geometry.
4. Project final point to screen.

## Required Data

### My Vehicle
- `my_pos`
- `my_rot`
- `my local axes`
- `my gun origin`
- `my sight origin`
- optional:
  - `my body bbox`
  - `my turret bbox`
  - `my barrel base / tip`

### Target Vehicle
- `target_pos`
- `target_rot`
- `target body-only bbox`
- `target turret-only bbox`
- or:
  - preferred hit bone / weakspot transform

### Ballistics
- projectile speed
- caliber
- mass
- drag / cx
- zeroing state

### Projection
- active camera position
- active view matrix
- world-to-screen

## Current Gaps

Still missing for true full-dynamic:
- confirmed `gunner sight / optics mount` as vehicle-local transform
- target body/turret-only geometry that excludes cannon inflation
- target weakspot/preferred hitpoint geometry

## Current Best Candidate Sources

### My Gun Origin
- existing `weapon/barrel` probe path
- barrel base/tip local/world coordinates

### My Sight Origin
- first-person `local_camera -> camera_position`
- use only when confirmed first-person/gunner view
- better future path:
  - optics mount / gunner sight transform
  - damage-model / named part / bone path

### My Local Axes
- existing `my_rot`
- existing helpers that derive local axes from rotation matrix

### Target Geometry
- current unit bbox path is usable as fallback
- better future path:
  - body-only bbox
  - turret-only bbox
  - named hit bone / damage-model transform

## Derivation Flow

### Phase 1: My Vehicle Geometry
1. Resolve `my_pos`
2. Resolve `my_rot`
3. Resolve `my gun origin`
4. Resolve `my sight origin`
5. Convert `(sight - gun)` into local-space deltas:
   - forward
   - up
   - lateral

Output:
- `my_parallax_local`

### Phase 2: Target Aim Geometry
1. Resolve target body/turret geometry
2. Pick target aimpoint in local target space
3. Transform target local aimpoint into world space

Output:
- `target_world_aimpoint`

Fallback if missing:
- use body/turret center from bbox

### Phase 3: Ballistic Solve
1. Use `target_world_aimpoint`
2. Solve travel time / drop
3. Apply my velocity compensation
4. Apply target velocity compensation if target is moving

Output:
- `predicted_world_impact`

### Phase 4: Parallax Solve
1. Convert `my_parallax_local` into world offset using my local axes
2. Apply sight-to-gun correction to predicted impact

Output:
- `world_impact_with_parallax`

### Phase 5: Screen Projection
1. Project `world_impact_with_parallax`
2. Render leadmark / hitpoint
3. Keep manual `vertical_correction` only as residual override

## Formula Sketch

### Local to World Parallax
```text
parallax_world =
    local_forward * my_axis_forward +
    local_up      * my_axis_up +
    local_left    * my_axis_left
```

### Final Aim
```text
target_world_aimpoint
  -> ballistic solve
  -> predicted_world_impact
  -> predicted_world_impact + parallax_world
  -> project to screen
```

## Ghidra Work Items

### My Sight / Optics
- find optics / gunner sight transform
- find vehicle-local camera mount if first-person changes object path
- verify whether optics object differs from active orbit camera

### Target Geometry
- find body-only bbox
- find turret-only bbox
- find named hit bone / weakspot transforms
- verify cannon is excluded from body bbox path

### Damage Model / Bones
- inspect model transform arrays
- inspect named part records
- map names to transform indices

## Runtime Implementation Plan

### V1
- Keep current vertical baseline config as fallback
- Add optional dynamic branch behind a flag
- Use:
  - current barrel origin
  - first-person sight estimate
  - current bbox target center

### V2
- Replace first-person sight estimate with true optics mount
- Replace target bbox center with body/turret geometry point

### V3
- Use dynamic path as primary
- Keep baseline config only as fallback/debug compare

## Validation Plan

For each my vehicle:
1. Test first-person untilted
2. Test first-person tilted-left
3. Test first-person tilted-right
4. Test near / mid / far distance
5. Compare:
   - dynamic path
   - baseline config fallback
   - residual manual correction needed

Success criteria:
- no per-vehicle table needed for primary path
- residual manual vertical correction stays small
- tilt no longer forces major retune

## Notes

- `camera_parallax` should become derived from geometry, not a main tuning knob.
- `vertical_correction` should remain a residual override, not the primary model.
- If true sight origin cannot be resolved, stay with mixed mode:
  - dynamic where geometry is trustworthy
  - config fallback where geometry is incomplete
