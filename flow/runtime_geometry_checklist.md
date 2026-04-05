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
  - live proof shows this path collapses to zero offset during active FPS gameplay
  - do not use it as the primary live geometry source
  - current reverse target from Ghidra/runtime side: materialized runtime path for `gunnerOpticFps[].pos`
  - parsed ground-config object now confirmed to come from:
    - `FUN_01c14070` cache/factory
    - `FUN_00afdda0` ground config builder
  - confirmed live runtime holder offsets for that config pointer:
    - `runtime + 0x1d18`
    - `runtime + 0xfe8`
  - confirmed top-level runtime parent: `FUN_017429f0`
  - confirmed parsed optic array storage exists before runtime materialization:
    - `+0x2d0/+0x2d8/+0x2e0/+0x2e4/+0x2e8`
  - current unresolved step:
    - identify the direct live consumer of that parsed optic array
  - checked direct consumer family:
    - `FUN_01cffff0`
    - `FUN_01678fd0`
    - `FUN_01682400`
  - result:
    - this family belongs to secondary-weapon slot/current-index handling
    - do not use it as the optic runtime extraction path
  - best non-weapon holder-path consumer so far:
    - `FUN_01d23630`
  - current meaning:
    - live turret/aim code definitely reads config-side fields through `runtime + 0xfe8`
    - parser binding proves `config + 0x2f0` is commander-view gating, not optic-array data
    - the exact `gunnerOpticFps[]` array deref is still unresolved
  - strongest live gameplay geometry consumer found after that:
    - `FUN_01d0bb20`
  - current meaning of this path:
    - consumes the `gunnerFps`-adjacent block at `+0x298..+0x2c8`
    - builds/transforms seat-local geometry into live output buffers
    - currently the best runtime bridge candidate from parser-known gunner fields to usable optic/sight geometry
  - live holder families now tied to this path:
    - `unit_runtime + 0x88`
    - `unit_runtime + 0xf0`
  - caller proof:
    - `FUN_0231d5f0`
      - passes `param_4 = *(unit_1068 + 0x88)[seat]`
      - can pass a real external output buffer as `param_3`
    - `FUN_00a74680`
      - passes `param_4 = *(unit_runtime + 0x88)[seat]`
      - passes `param_3 = 0`, implying internal seat-state update path is also valid
  - concrete seat-object geometry block now identified:
    - `+0x294/+0x29c` cached position-like state
    - `+0x2a0` live refcounted source/object pointer candidate
    - `+0x2a8` pointer to entry-array
    - `+0x2ac/+0x2b0/+0x2b4` orientation angles
    - `+0x2b8` entry-array count
  - angle population proof:
    - `FUN_01ca7e90` writes these fields
    - `FUN_0368b750` converts runtime basis block `(source + 0xcdc)` into the three angles
  - source-transform proof:
    - `FUN_012f8fd0` returns `source + 0xcdc`
    - `FUN_00b91e10` uses `source + 0xcdc/+0xce8/+0xcf4/+0xd00...` together with part-table rows to compute world-space candidates
    - `FUN_01c887c0` reads `unit + 0xcdc/+0xce8/+0xcf4/+0xcfc` directly in gameplay code and subtracts those values from live state
  - neighboring source-family accessor:
    - `FUN_00b91d70` returns `object + 0x23f8`
    - current evidence says this is nearby embedded state, not the primary optic-mount transform
  - current strongest hypothesis:
    - `+0x2a0` identifies the single live source object that owns the seat or sight transform
    - `+0x2a8/+0x2b8` describe an auxiliary entry array, not the primary source id
    - the embedded block at `source + 0xcdc` is closer to the true runtime optic/seat transform than active camera state
  - deprioritized helpers:
    - `FUN_01d1cd80`
    - `FUN_017a5060`
    - `FUN_017a2be0`
  - generic field accessor only:
    - `FUN_078dc510`
  - meaning:
    - proves one runtime object family exposes `+0x2b0/+0x2b4/+0x2b8/+0x2c8`
    - but is not itself an optic-mount materialization path
- `target_turret_bbox`
  - current runtime candidate winner is `0x1f90 / 0x1f9c`
  - secondary candidate is `0x1f78 / 0x1f84`
  - `0x1f80 / 0x1f8c` is currently rejected
- current stable production fallback remains `vertical_baseline_table.json`
- optics runtime note:
  - first-person `camera_local - barrel_base_local` looked stable in raw snapshots
  - but live gameplay world offset collapsed to zero
  - pause / third-person produced non-zero offsets
  - treat active camera as a view-state hint only, not optic mount truth
- parts/object runtime note:
  - `FUN_05098200` appears to be an `object` / `cutObject` builder path
  - useful for future body/part geometry investigation
  - not currently the best optic mount target
- geometry-subobject runtime note:
  - `FUN_0163db10` rebuilds the large subobject at `vehicle_root + 0x1068`
  - major rebuilt arrays live at:
    - `+0x358`
    - `+0x3d8`
    - `+0x490`
    - `+0x5b8`
    - `+0x5e8`
    - `+0x6c8`
  - this looks like damage/model/part runtime state, not a direct optic mount chain yet
- generic-builder note:
  - `FUN_0163acc0` has multiple callers and now looks more like a generic model/resource assembler
  - do not assume it is the direct `gunnerOpticFps[].pos -> live mount` path
