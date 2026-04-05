# Ghidra Geometry Findings

Purpose:
- Capture concrete findings from Ghidra that matter for the full-dynamic geometry path.

## Key Functions

- `FUN_018aaba0`
  - unit config parser with the strongest optics/camera geometry evidence
- `FUN_00f05270`
  - runtime `UnitOptic` registration / binding path
- `FUN_0105a9b0`
  - DAScript bind function exposing camera and turret aim APIs
- `FUN_00ae4310`
  - turret bone bbox path
- `FUN_00ae4ed0`
  - `turretsBoundingBoxExtent` path
- `FUN_004448b0`
  - weapon ECS registration path that includes `weapon_rearsight_node__nodeTm`
- `FUN_01cc3980`
  - optics-related weapon/guidance config path with mount/offset fields

## Sight / Optics

### `FUN_018aaba0`

Confirmed parsed unit fields:
- `additionalCameraOffset`
- `cameraDistanceScale`
- `forceSetCameraToSight`
- `headPos`
- `headPosVr`
- `headPivotPos`
- `headPosOnShooting`
- `headPosOnShootingPivotPos`
- `headPosOnSides`
- `cameraHeightOnGround`
- `zoomInFov`
- `zoomOutFov`
- `sightInFov`
- `sightOutFov`
- `sightFov`

### `gunnerFps`

`FUN_018aaba0` parses:
- `head`
- `turret`
- `turretNo`
- `pos`
- `offsetRotatable`
- `limits`
- `drawDetailedCockpit`

Interpretation:
- `gunnerFps.pos` is a vehicle-local first-person mount candidate.

### `gunnerOpticFps`

`FUN_018aaba0` parses:
- `head`
- `turret`
- `turretNo`
- `pos`
- `limits`
- `offsetRotatable`
- `angularLimits`
- `opticType`
- `nvIndex`
- `name`

Interpretation:
- `gunnerOpticFps[].pos` is currently the best candidate for true gunner optic / sight local transform.
- It is stronger than using active camera position alone.

### `commanderView`

`FUN_018aaba0` parses:
- `aimModeAvailable`
- `optics`
- `zoomOutFov`
- `zoomInFov`
- `sightSize`

Interpretation:
- commander optics are a distinct path and should not be assumed identical to gunner optics.

### `optics`

`FUN_018aaba0` parses:
- `binoculars`
- `aimingReticule`
- `driverReticule`
- `binocularsFov`

Interpretation:
- general optics setup is separate from per-seat gunner optic transform data.

## Runtime Camera / Aim APIs

### `FUN_0105a9b0`

Exposed DAScript APIs include:
- `get_turret_aim_angles`
- `set_turret_aim_angles`
- `get_turret_aim_camera_pos`
- `set_turret_aim_camera_pos`
- `get_turret_aim_mouse_aim`
- `set_turret_aim_mouse_aim`
- `get_turret_aim_vector`
- `get_camera_pos`
- `get_camera_orig_pos`
- `get_camera_orig_dir`

Interpretation:
- runtime engine already distinguishes turret-aim camera position from generic camera position.
- this is a strong sign there is a clean runtime path for sight-related camera origin.

## Weapon / Rear Sight Node

### `FUN_004448b0`

Observed ECS weapon registration string:
- `weapon_rearsight_node__nodeTm`

Interpretation:
- weapon-side ECS includes a node transform keyed by rearsight node name.
- likely useful for exact weapon node / sight node transform recovery.
- this is not yet resolved to a direct runtime memory offset in the overlay.

## Turret / Target Geometry

### `FUN_00ae4310`

Observed:
- uses `bone_turret`
- computes extents stored around `param_1 + 0x38e8 .. 0x38fc`

### `FUN_00ae4ed0`

Observed:
- uses `turretsBoundingBoxExtent`
- prefixes include:
  - `turret_`
  - `superstructure_`
  - `aps_launcher_`
- computes extents around:
  - `param_1 + 0x1f90 .. 0x1fa4`
  - copies also around:
    - `param_1 + 0x1f78 .. 0x1f8c`

Interpretation:
- engine has a turret/superstructure-specific bbox path.
- this is the best current candidate for target turret bbox that excludes some cannon inflation present in full-unit bbox paths.

## UnitOptic Runtime Class

### `FUN_00f05270`

Observed strings:
- `UnitOptic`
- `SeekerTarget`
- `PointOfInterest`
- `SensorTargetOfInterest`

Interpretation:
- runtime has a dedicated optic-related class.
- likely relevant for actual optic state, but not yet tied to a resolved memory offset path.

## Current Conclusions

- `my_sight_origin`
  - best config-side candidate: `gunnerOpticFps[].pos`
  - fallback config-side candidate: `gunnerFps.pos`
  - current runtime estimate: first-person `local_camera -> camera_position`
- `my_gun_origin`
  - current runtime barrel probe path is still the usable source
  - `weapon_rearsight_node__nodeTm` suggests exact node transforms may be recoverable later
- `target_turret_bbox`
  - best current candidate: turret/superstructure bbox path from `FUN_00ae4310` and `FUN_00ae4ed0`

## Runtime Dumper Validation

### `optic_runtime_probe_dumper.py`

Validated on `ussr_2s3m` in first-person:
- `Cam-Barrel Δ mean = [0.4164, -0.0216, -1.6128]`
- `stddev = [0.0, 0.0, 0.0]`

Interpretation:
- first-person active camera minus barrel-base local delta is stable enough to use as a runtime candidate.
- only the `up` component should be trusted first for parallax math.
- this path should be limited to first-person / gunner view.

Observed stale candidates:
- direct world offsets `0x1e6c` and `0x2638` returned zero vectors on current build and should not be promoted.

### `turret_bbox_candidate_dumper.py`

Validated across 9 ground vehicles:
- `0x1f80 / 0x1f8c`
  - invalid on all tested vehicles
- `0x1f78 / 0x1f84`
  - valid on all tested vehicles
  - appears to be a lower / thinner partial strip
- `0x1f90 / 0x1f9c`
  - valid on all tested vehicles
  - appears to be the best full turret / superstructure volume candidate

Current runtime ranking:
1. `target_turret_bbox = 0x1f90 / 0x1f9c`
2. fallback candidate `0x1f78 / 0x1f84`
3. reject `0x1f80 / 0x1f8c`

## Still Missing

- direct runtime memory offsets for:
  - `gunnerOpticFps[].pos`
  - `gunnerFps.pos`
  - turret bbox chosen path
  - exact rear sight / muzzle node transform
- body-only bbox path confirmed to exclude cannon
- target hit bone / preferred weakspot geometry
