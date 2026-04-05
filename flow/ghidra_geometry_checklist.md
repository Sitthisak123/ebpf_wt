# Ghidra Geometry Checklist

Purpose:
- Resolve the missing game-side geometry needed for full-dynamic hitpoint calculation.

## Sight / Optics

- [ ] Confirm active first-person camera object path.
- [ ] Find whether first-person camera position is true gunner sight origin or only active view camera.
- [ ] Find optics / gunner sight mount as a vehicle-local transform.
- [ ] Check whether optics path is global-manager based or unit-local based.
- [ ] Verify if optics object changes between third-person and first-person.

## Gun / Barrel

- [ ] Confirm stable gun origin path.
- [ ] Confirm stable barrel base path.
- [ ] Confirm stable barrel tip / muzzle path.
- [ ] Verify which point best represents bore origin for parallax math.

## Vehicle Local Geometry

- [ ] Confirm local axes mapping from unit rotation matrix.
- [ ] Verify axis meaning per ground vehicle:
  - [ ] forward
  - [ ] up
  - [ ] left/right
- [ ] Confirm body bbox path.
- [ ] Confirm turret bbox path.
- [ ] Verify whether current bbox includes cannon length.

## Damage Model / Bones / Named Parts

- [ ] Inspect transform arrays related to vehicle parts.
- [ ] Inspect named part records.
- [ ] Map names to transform indices.
- [ ] Search for part names like:
  - [ ] `optic`
  - [ ] `sight`
  - [ ] `camera`
  - [ ] `gunner`
  - [ ] `barrel`
  - [ ] `muzzle`
  - [ ] `turret`
  - [ ] `hull`

## Target Geometry

- [ ] Find body-only bbox that excludes cannon.
- [ ] Find turret-only bbox.
- [ ] Find target hit bone / weakspot / preferred impact point if available.
- [ ] Verify whether turret/body transforms are usable at runtime.

## Validation

- [ ] Compare first-person camera local position against barrel base local position.
- [ ] Compare optics/sight candidate against first-person camera position.
- [ ] Compare body/turret bbox against on-screen 3D box.
- [ ] Verify all chosen paths across multiple vehicles.

## Output Needed

- [ ] `my_sight_origin`
- [ ] `my_gun_origin`
- [ ] `my_local_axes`
- [ ] `target_body_bbox`
- [ ] `target_turret_bbox`
- [ ] optional `target_hit_bone`
