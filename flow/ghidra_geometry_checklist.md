# Ghidra Geometry Checklist

Purpose:
- Resolve the missing game-side geometry needed for full-dynamic hitpoint calculation.

## Sight / Optics

- [x] Confirm active first-person camera object path.
- [x] Find whether first-person camera position is true gunner sight origin or only active view camera.
- [x] Find optics / gunner sight mount as a vehicle-local transform.
- [x] Check whether optics path is global-manager based or unit-local based.
- [x] Verify if optics object changes between third-person and first-person.
- [x] Identify top-level runtime consumer that dispatches optic-related build paths.
- [x] Check first direct `+0x2d0/+0x2e0` consumer family.
- [ ] Resolve which runtime sub-builder materializes `gunnerOpticFps[].pos`.
- [x] Identify large geometry/damage runtime subobject rebuilt from config.
- [ ] Find an optic-specific consumer instead of a secondary-weapon slot consumer.
- [x] Find a live gameplay consumer of the `gunnerFps`-adjacent field block (`+0x298..+0x2c8`).
- [x] Identify the live seat/view object family passed into that consumer.
- [x] Identify concrete geometry/orientation fields inside the live seat/view object.
- [x] Confirm that the source behind those fields exposes a dedicated transform block at `+0xcdc`.
- [x] Confirm that the `+0xcdc` block is consumed by live gameplay code, not only helpers.
- [x] Identify whether neighboring embedded sub-structures exist on the same source-object family.

## Gun / Barrel

- [x] Confirm stable gun origin path.
- [ ] Confirm stable barrel base path.
- [ ] Confirm stable barrel tip / muzzle path.
- [ ] Verify which point best represents bore origin for parallax math.

## Vehicle Local Geometry

- [x] Confirm local axes mapping from unit rotation matrix.
- [ ] Verify axis meaning per ground vehicle:
  - [x] forward
  - [x] up
  - [x] left/right
- [ ] Confirm body bbox path.
- [x] Confirm turret bbox path.
- [x] Verify whether current bbox includes cannon length.

## Damage Model / Bones / Named Parts

- [ ] Inspect transform arrays related to vehicle parts.
- [ ] Inspect named part records.
- [ ] Map names to transform indices.
- [ ] Search for part names like:
  - [ ] `optic`
  - [ ] `sight`
  - [ ] `camera`
  - [x] `gunner`
  - [ ] `barrel`
  - [ ] `muzzle`
  - [x] `turret`
  - [ ] `hull`

## Target Geometry

- [ ] Find body-only bbox that excludes cannon.
- [x] Find turret-only bbox.
- [ ] Find target hit bone / weakspot / preferred impact point if available.
- [ ] Verify whether turret/body transforms are usable at runtime.

## Validation

- [x] Compare first-person camera local position against barrel base local position.
- [ ] Compare optics/sight candidate against first-person camera position.
- [x] Compare body/turret bbox against on-screen 3D box.
- [ ] Verify all chosen paths across multiple vehicles.

## Output Needed

- [x] `my_sight_origin`
- [x] `my_gun_origin`
- [x] `my_local_axes`
- [ ] `target_body_bbox`
- [x] `target_turret_bbox`
- [ ] optional `target_hit_bone`

## Current Best Candidates

- `my_sight_origin`
  - primary candidate: `gunnerOpticFps[].pos`
  - fallback candidate: `gunnerFps.pos`
  - rejected live-runtime path: first-person active camera position
  - parsed ground-config builder: `FUN_00afdda0`
  - parsed config cache/factory: `FUN_01c14070`
  - confirmed live runtime holder offsets in ground runtime object:
    - `+0x1d18`
    - `+0xfe8`
  - top-level runtime parent: `FUN_017429f0`
  - parsed config-side optic array now confirmed at:
    - `+0x2d0` pointer
    - `+0x2d8` allocator/container
    - `+0x2e0` count
    - `+0x2e4` capacity
    - `+0x2e8` flags
  - highest-value remaining question:
    - who consumes the parsed optic array into live runtime mount state
  - checked and rejected as optic target:
    - `FUN_01cffff0`
    - `FUN_01678fd0`
    - `FUN_01682400`
  - reason:
    - this family cycles/validates secondary-weapon slots via `+0x2e8` and `+0x2e0`
  - best non-weapon holder-path consumer so far:
    - `FUN_01d23630`
  - current status:
    - confirms live aim/turret code reads config fields from `+0xfe8`
    - parser binding now shows `+0x2f0` is `commanderView` present flag, not `gunnerOpticFps`
    - still does not expose direct `gunnerOpticFps[]` array consumption
  - new strongest live gameplay consumer of adjacent gunner/seat fields:
    - `FUN_01d0bb20`
  - reason:
    - directly reads the `+0x298..+0x2c8` block and transformed geometry ranges around it
    - not just commander-view gating
    - not the secondary-weapon slot family
  - live object family now tied to that path:
    - `unit_runtime + 0x88`
    - `unit_runtime + 0xf0`
  - caller proof:
    - `FUN_0231d5f0`
    - `FUN_00a74680`
  - concrete seat-object geometry fields now confirmed:
    - `+0x2a0` refcounted source/object pointer candidate
    - `+0x2a8` pointer to entry-array
    - `+0x2ac/+0x2b0/+0x2b4` orientation angles
    - `+0x294/+0x29c` cached position-like state
    - `+0x2b8` entry-array count
  - helper that populates angles:
    - `FUN_0368b750`
  - stronger source-geometry proof:
    - `FUN_012f8fd0` exposes `object + 0xcdc` directly
    - `FUN_00b91e10` uses `+0xcdc/+0xce8/+0xcf4/+0xd00...` as a transform block to project part-table points into world-space
    - `FUN_01c887c0` reads `unit + 0xcdc/+0xce8/+0xcf4/+0xcfc` directly in gameplay code and subtracts them from live state
  - neighboring embedded sub-structure:
    - `FUN_00b91d70` exposes `object + 0x23f8` directly
    - current evidence says this is adjacent source-family state, not the primary optic-mount target
  - corrected by cleanup proof:
    - `FUN_01d0b590` frees `+0x2a0` as a single object
    - `FUN_01d0b590` treats `+0x2a8` as array pointer with `+0x2b8` count and stride `0x58`
  - helper-only paths:
    - `FUN_01d1cd80`
    - `FUN_017a5060`
    - `FUN_017a2be0`
- `my_gun_origin`
  - current runtime barrel probe path is usable
  - `weapon_rearsight_node__nodeTm` exists in ECS weapon path and may help locate exact weapon node transforms
- `target_turret_bbox`
  - turret/superstructure bbox path exists via `bone_turret` and `turretsBoundingBoxExtent`
  - current runtime candidate winner: `0x1f90 / 0x1f9c`
  - secondary runtime candidate: `0x1f78 / 0x1f84`

## Notes

- `FUN_018aaba0` is the strongest config-side parser found so far for unit optics/camera geometry.
- `gunnerOpticFps[].pos` is currently the best confirmed vehicle-local sight candidate.
- `FUN_017429f0` is now the confirmed top-level runtime parent for the next reverse step.
- `FUN_0163db10` now looks like a geometry/damage runtime subobject builder for `vehicle_root + 0x1068`.
- key rebuilt array groups in that subobject include:
  - `+0x358`
  - `+0x3d8`
  - `+0x490`
  - `+0x5b8`
  - `+0x5e8`
  - `+0x6c8`
- this is valuable for target/body/part geometry reverse, but still not a clean optic mount chain.
- `FUN_0163acc0` now looks more like a generic model/resource builder than a direct optic-entry consumer.
- other callers of `FUN_0163acc0` (`FUN_01bdf8d0`, `FUN_00a8cb60`) reinforce that it is likely generic.
- `first-person local_camera -> camera_position` is not usable as the primary live FPS geometry source:
  - live gameplay collapsed world offset to zero
  - pause / third-person produced non-zero offsets
  - therefore it behaves like view camera state, not true optic mount state.
- runtime dumps across 9 ground vehicles showed:
  - `0x1f80 / 0x1f8c` is not usable as body bbox in current builds tested
  - `0x1f78 / 0x1f84` is stable but looks like a lower/partial strip
  - `0x1f90 / 0x1f9c` is stable and looks like the best turret/superstructure volume candidate
