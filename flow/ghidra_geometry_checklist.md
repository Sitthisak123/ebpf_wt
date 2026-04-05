# Ghidra Geometry Checklist

Purpose:
- Resolve the missing game-side geometry needed for full-dynamic hitpoint calculation.

## Sight / Optics

- [x] Confirm active first-person camera object path.
- [x] Find whether first-person camera position is true gunner sight origin or only active view camera.
- [x] Find optics / gunner sight mount as a vehicle-local transform.
- [x] Check whether optics path is global-manager based or unit-local based.
- [ ] Verify if optics object changes between third-person and first-person.

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
  - current runtime fallback: first-person active camera position
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
- `first-person local_camera -> camera_position` is a usable runtime estimate, but Ghidra evidence suggests it is still an active view camera path, not the cleanest geometry source.
- runtime dumps across 9 ground vehicles showed:
  - `0x1f80 / 0x1f8c` is not usable as body bbox in current builds tested
  - `0x1f78 / 0x1f84` is stable but looks like a lower/partial strip
  - `0x1f90 / 0x1f9c` is stable and looks like the best turret/superstructure volume candidate
