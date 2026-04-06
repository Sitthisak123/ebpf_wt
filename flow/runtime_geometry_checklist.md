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
  - stronger consumer chain now confirmed:
    - `FUN_01621390` updates the `+0x88[seat]` holder
    - `FUN_01620fa0` consumes `+0xf0[seat]` part tables
    - `FUN_01d17f90` reads a ushort part selector and loads `0x40` transform rows from `+0xf0[seat]`
    - `FUN_01d4d170` forwards the composed `record + 0x88` payload into downstream updates
  - caller proof:
    - `FUN_0231d5f0`
      - passes `param_4 = *(unit_1068 + 0x88)[seat]`
      - can pass a real external output buffer as `param_3`
    - `FUN_00a74680`
      - passes `param_4 = *(unit_runtime + 0x88)[seat]`
      - passes `param_3 = 0`, implying internal seat-state update path is also valid
  - concrete seat-object geometry block now identified:
    - prior attribution to `FUN_01ca7e90` is revoked
    - that function is now identified as projectile-family runtime code, not clean seat/view evidence
  - angle population proof:
    - `FUN_0368b750` still converts runtime basis block `(source + 0xcdc)` into the three angles
  - source-transform proof:
    - `FUN_012f8fd0` returns `source + 0xcdc`
    - `FUN_00b91e10` uses `source + 0xcdc/+0xce8/+0xcf4/+0xd00...` together with part-table rows to compute world-space candidates
    - `FUN_01c887c0` reads `unit + 0xcdc/+0xce8/+0xcf4/+0xcfc` directly in gameplay code and subtracts those values from live state
  - corrected reading of that block:
    - local scanner/raw references in this repo repeatedly map nearby offsets to `rotation_matrix`
    - treat `+0xcdc` as the source object's orientation basis block
    - do not assume it is the optic mount by itself
  - neighboring source-family accessor:
    - `FUN_00b91d70` returns `object + 0x23f8`
    - current evidence says this is nearby embedded state, not the primary optic-mount transform
  - current strongest hypothesis:
    - the reusable source-object layout still likely uses `+0xcdc` for basis and `+0xd00/+0xd08` for world position
    - `FUN_01ca7e90` is not the seat-runtime bridge we want
    - the seat-runtime bridge now looks more like:
    - parser-known gunner fields -> `unit + 0x88 / +0xf0` holders -> `0x178`-stride record family -> composed transforms in `record + 0x88`
    - `FUN_01d4d3e0` is the dispatcher over bucket arrays at `+0xf0..+0x198`
    - `FUN_01d4d7c0` is a separate metadata/object-entry pre-pass over the first three buckets and depends on `owner + 0x248`
    - `FUN_01d4c790`, `FUN_01d4d500`, `FUN_01d4ca50`, and `FUN_01d4cd40` show that `record + 0xa0` is a downstream generated object-entry layer driven by filtered metadata/bitsets
    - that shifts the unresolved semantic question further upstream to the ushort selector table at `record + 0x50`
    - `FUN_01d512d0` and `FUN_01d52210` sit in a broader generic owner/runtime-management layer
    - wrappers/callers like `FUN_014084f0`, `FUN_0172e3a0`, `FUN_0174e060`, and `FUN_0174f4f0` are heavy on flight-model / warp / overspeed logic
    - that makes them useful for owner-layer placement, but not yet the best ground-optic selector source
    - `FUN_01d020b0` and `FUN_01d4de30` further split owner-local slot/object machinery from the record-family problem:
    - `(owner + 800)[slot]` holds slot-based object lists
    - `owner + 0x2b8` acts like reusable filter-token state for those object lists
    - this still does not explain who populates the `0x178`-stride record selector table at `record + 0x50`
    - wrappers `FUN_01d025e0..01d02730` and consumers `FUN_01d1d410/01d1d220` stay on the same slot/object side of the split
    - they are now deprioritized for the ground-optic selector problem
    - `FUN_01d00180` plus `FUN_01d5b320/01d5b4e0/01d5b590` make the owner-local registry clearer:
    - `(owner + 800)[slot]` = slot object lists with transform-capable runtime objects
    - `owner + 0x2b8` = slot-group registry used for present/active/ready counting and filter-token selection
    - consumer paths like `FUN_0167a970` and `FUN_01747600` stay on this registry side, not the bucket-record side
    - `FUN_01d2e060/01d2e1c0` only manage temporary `0x50`-byte filtered object lists inside `FUN_01d55f50`
    - `FUN_01d5b7f0/01d5b770/01d5b8c0` further confirm `+0x2a8/+0x2b8` is registry/group state, not the `+0xf0..+0x198` bucket-record source
    - `FUN_01d04e20` is now also placed on the registry side:
    - it iterates owner-local filtered groups via `owner + 0x2b8`
    - dispatches object virtual `+0x120`
    - do not treat it as a constructor for `record + 0x50`
    - `FUN_00a4b870` is a stronger owner update anchor:
    - it updates `*(DAT_00001090 + unit)` through `FUN_01d04e20`, `FUN_01d52210`, and `FUN_01d4d7c0`
    - then iterates owner-local objects from `owner + 0x2f0` with count `owner + 0x300`
    - this is useful owner-layer placement, but still not the selector-table builder
    - `FUN_01d4cc20` and `FUN_01d4d0f0` add another split above the bucket consumers:
    - `FUN_01d4cc20` = full eight-bucket post-pass over `+0xf0..+0x198`
    - `FUN_01d4d0f0` = first-three-bucket counterpart over `+0xf0/+0x108/+0x120`
    - wrappers `FUN_0231caf0` / `FUN_0231cba0` sit above those passes only
    - all of these consume already-built records rather than building the ushort selector table
    - `FUN_00ad82b0` and `FUN_00b26a00` now repeat the same owner-update template:
    - optional `FUN_01d512d0`
    - `FUN_01d52210`
    - `FUN_01d4d7c0`
    - then iterate owner-local objects from `owner + 0x2f0` with count `owner + 0x300`
    - these are sibling gameplay/update modes, not the missing bucket constructor
    - `FUN_00b11250` and `FUN_00b41720` sit one layer higher in heavy gameplay/aim/fire loops
    - both also use a separate side-record family at `owner + 0x1c8` with stride `0x300`
    - do not confuse that `0x300`-stride family with the unresolved `0x178`-stride bucket records
    - `FUN_01d512d0` itself now looks narrow enough to classify:
    - it updates the `owner + 0x1c8` / count `0x1d8` / stride `0x300` side-record family
    - and drives `FUN_01d20be0`, `FUN_01d248b0`, and `FUN_01d50ca0`
    - it does not seed `owner + 0xf0..+0x198`
    - `FUN_01d52210` is also narrower now:
    - it iterates object pointers from `owner + 0x308` with count `owner + 0x318`
    - and maintains cache/object state at `owner + 0x1400..+0x1590`
    - this is still object/cache management, not bucket construction
    - nearby helpers `FUN_01d4d850` and `FUN_01d4da90` also stay on the object-metrics side:
    - they aggregate counts from owner-local object lists and object-local `+0xa8 + idx*0xa0` groups
    - they are not part of the unresolved bucket-builder path
    - `FUN_0231b470` plus wrappers `FUN_0231cc50/01d0231ccf0` add another excluded layer:
    - these are higher render/effect-style wrappers above `FUN_01d4cc20`
    - they gate dispatch by view/state flags and local render-state blocks
    - they do not initialize the bucket family either
    - `FUN_00bba640` and `FUN_01c5a330` add another excluded layer above `FUN_00a4b870`:
    - both are high-level gameplay wrappers
    - both still spend most of their work on side-record/object-state logic
    - both eventually end by calling `FUN_00a4b870`
    - neither directly initializes `owner + 0xf0..+0x198`
    - `FUN_01d05000` adds another excluded side-record path:
    - it updates the `owner + 0x230/+0x240` family against the `owner + 0x1c8` side-record family
    - it is called from `FUN_01d4d7c0`, but it still does not initialize the bucket family
    - `FUN_01d4c790` now clarifies the `0x178` record layout further:
    - `record + 4/+8` are owner-local `(slot_group, object_index)` lookup fields into `(owner + 800)`
    - `FUN_01d4ca50`, `FUN_01d4cd40`, and `FUN_01d4d500` use those fields to build/refresh generated payloads at `record + 0xa0`
    - `record + 0x158` and `record + 0x16c` sit on that generated-payload side as control/fallback fields
    - this sharpens the separation from the still-unresolved semantic part-selector table at `record + 0x50`
    - `FUN_01d04b40` is just a gate helper for one `owner + 0x1c8 + slot*0x300` entry
    - `FUN_01d16ff0` is a reusable transform materializer for a selected runtime object
    - it can be reached from both `FUN_01d17f90` and registry/gameplay paths such as `00ae8520/00ae8f00`
    - this shows full transform materialization also exists outside the bucket family
    - `FUN_00ae8d10`, `FUN_00ae8520`, and `FUN_00ae1d00` further harden the meaning of `owner + 0x2b8`:
    - it is a live group/selection registry used for choosing objects and mapping semantic damage groups
    - not the bucket constructor we still need
    - `FUN_01d0b590` proves `+0x2a8/+0x2b8` are array pointer/count only in the separate `FUN_01d0bb20` record family
    - do not project that exact meaning onto the compact projectile-family object written by `FUN_01ca7e90`
    - the unresolved question is now narrower:
    - which constructor populates `record + 0x50`
    - and which ushort-selected `unit + 0xf0[seat]` entries correspond to tank datamine names like `optic_gun_dm`, `gunner_dm`, `bone_turret`, or `bone_gun_barrel`
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
