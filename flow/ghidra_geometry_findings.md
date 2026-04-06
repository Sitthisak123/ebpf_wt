# Ghidra Geometry Findings

Purpose:
- Capture concrete findings from Ghidra that matter for the full-dynamic geometry path.

## Key Functions

- `FUN_018aaba0`
  - unit config parser with the strongest optics/camera geometry evidence
- `FUN_00f05270`
  - runtime `UnitOptic` registration / binding path
- `FUN_017429f0`
  - top-level vehicle runtime build/update path that consumes parsed config and dispatches sub-builders
- `FUN_0163acc0`
  - main runtime assembler that builds vehicle-related state from config/runtime inputs
- `FUN_0163db10`
  - large runtime builder that still looks like the primary consumer-side path for optics/geometry-related config blocks
- `FUN_01d1cd80`
  - weapon blk walker; not an optic mount resolver
- `FUN_017a5060`
  - cached blk loader/validator helper
- `FUN_017a2be0`
  - blk refcount release helper
- `FUN_05098200`
  - runtime `object` / `cutObject` parts path; useful for part/element geometry, not a direct optic mount path
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
- In `FUN_018aaba0`, parsed `gunnerOpticFps` entries are stored into a config-side runtime-owned array:
  - `param_1 + 0x2d0` = entry array pointer
  - `param_1 + 0x2d8` = allocator / backing container
  - `param_1 + 0x2e0` = count
  - `param_1 + 0x2e4` = capacity
  - `param_1 + 0x2e8` = bit/flag field for entries with explicit `head`
- This means the clean optic reverse question is now:
  - who consumes the parsed `gunnerOpticFps` array at `+0x2d0/+0x2e0`
  - not just which function receives some generic descriptor blob

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

## Runtime Consumer Path

### `FUN_01c14070`

Confirmed behavior:
- acts as a cache/factory for a parsed unit-config object keyed by unit name / path
- uses `FUN_017a5060` to load the unit blk
- allocates a config object and invokes its init path through vtable
- returns a cached parsed-config pointer from `DAT_0991b340[...]`

Interpretation:
- this is the strong entry for obtaining the long-lived parsed config object that later runtime code uses.
- it is not the live optic mount consumer itself, but it explains where the parsed optic array object comes from.

### `FUN_00afdda0`

Confirmed behavior:
- ground-vehicle config builder / initializer
- calls `FUN_00a8b080`, which in turn calls `FUN_018aaba0`
- fills the larger ground unit config object with vehicle-, artillery-, sensor-, and additional-sight data

Interpretation:
- for ground vehicles, the parsed optic array at `+0x2d0/+0x2e0` lives inside this long-lived config object.
- this confirms the optic array is part of the ground vehicle config object, not a transient stack-only parse artifact.

### `FUN_01c1d560`

Confirmed behavior:
- obtains a ground config object via `FUN_01c14070(param_2, param_3)`
- stores that returned pointer into the runtime object at:
  - `param_1 + 0x1d18`
  - `param_1 + 0xfe8`
- then calls:
  - `FUN_01882700(param_1 + 0x1498)`
  - `FUN_018858d0(param_1)`

Interpretation:
- this is the first confirmed live runtime holder path for the ground config object.
- `runtime + 0x1d18` / `runtime + 0xfe8` are now the strongest holder candidates for the config object containing `gunnerOpticFps[]`.

### `FUN_018858d0`

Confirmed behavior:
- does **not** consume `gunnerOpticFps`
- only resolves the unit's `tags` blk and stores:
  - `runtime + 0x39c` = tags block pointer
  - `runtime + 0x39d` = flag

Interpretation:
- despite being called right after storing the config pointer, it is not the optic-array consumer.

### `FUN_017429f0`

Confirmed runtime behavior:
- reads parsed config from `R14 + 0x1068`
- prepares several blk/config helper structures
- builds config-derived state into runtime object fields under `R14`
- calls:
  - `FUN_0163acc0`
  - `FUN_0163db10`
  - `FUN_01d1cd80`
  - `FUN_01886b40`
  - `FUN_05098200`

Important interpretation:
- this is currently the strongest top-level runtime entry we have for tracing `gunnerOpticFps` from parsed config into live vehicle state.
- it is not itself the final optic mount offset source, but it is the right parent function for following the path.
- Refined conclusion from the current pass:
  - the stack-local descriptor built immediately before the `FUN_0163acc0` call does not currently look like raw `gunnerOpticFps` entries
  - it looks more like a generic model/collision/explosive-resource descriptor
  - so `FUN_017429f0 -> FUN_0163acc0` is no longer the strongest direct optic-materialization hypothesis

### `FUN_01d1cd80`

Confirmed behavior:
- iterates `Weapon` / `weapon` blk children
- loads cached blks with `FUN_017a5060`
- releases them with `FUN_017a2be0`
- forwards resulting weapon blk data to `FUN_01cf1c70` / `FUN_01cf2080`

Interpretation:
- this is a weapon blk walker / loader.
- it is not the direct optic mount path and should be treated as helper-only for this reverse goal.

### `FUN_017a5060`

Confirmed behavior:
- wraps `FUN_017a4890`
- validates cached blk contents from `globalBlkCache`

Interpretation:
- helper only.
- no direct sight/optic transform evidence.

### `FUN_017a2be0`

Confirmed behavior:
- decrements blk refcount only

Interpretation:
- helper only.

### `FUN_0163acc0`

Confirmed behavior:
- takes a runtime object and a large parameter block
- rebuilds significant vehicle runtime state
- loads collision/explosion assets
- allocates and fills multiple runtime arrays
- copies/derives geometry-like structures into fields such as:
  - `param_1 + 0x228`
  - `param_1 + 0x238`
  - `param_1 + 0x530`
  - `param_1 + 0x538`
- uses part/model data heavily and performs transform/bbox-like aggregation

Interpretation:
- this is a high-value runtime assembler.
- it looks more relevant to geometry/state realization than `FUN_01d1cd80`.
- it still does not expose a clean final `gunnerOpticFps[].pos` field by itself from the decompiler output seen so far.
- Additional evidence that it is generic rather than optic-specific:
  - current callers:
    - `FUN_017429f0`
    - `FUN_01bdf8d0`
    - `FUN_00a8cb60`

### `FUN_0163db10`

Current interpretation from decompiler and caller context:
- SysV call shape from `FUN_017429f0` indicates:
  - `param_2` is the large runtime subobject stored at `vehicle_root + 0x1068`
  - `param_3` is the parent vehicle object
  - `param_4..param_10` are config blk / helper inputs assembled by `FUN_017429f0`
- this function clears and rebuilds a large geometry/damage-related runtime state block

Observed runtime fields written on `param_2`:
- `+0x250 / +0x252`
  - visible-damage thresholds / flags
- `+0x350`
  - helper object with multiple arrays and capacities
- `+0x358`
  - primary part-index / damage-part source array built via `FUN_01521a70`
- `+0x368 .. +0x370`
  - array of `0x130`-byte records that gets released/reset before rebuild
- `+0x3d8 .. +0x3e4`
  - array of `0x14`-byte runtime records, one per active part
- `+0x490 .. +0x49c`
  - array of `0x88`-byte larger runtime records, populated via `FUN_05395620`
- `+0x5b8 .. +0x5d8`
  - multiple `u32`-style side arrays cleared/resized to part count
- `+0x5e8 .. +0x5f4`
  - bitset/flag storage resized to `(part_count * 4 + 7) >> 3`
- `+0x600 .. +0x618`
  - another per-part structure reset/init path
- `+0x620 .. +0x62c`
  - `u16`-style storage resized to part count
- `+0x6c8 .. +0x6cc`
  - sorted/indexed structure reset and optionally sorted
- `+0x6e0 .. +0x700`
  - follow-up state initialized via `FUN_04d7c0b0`

What it appears to do:
- build damage/model part mappings from config blk inputs
- allocate per-part runtime records
- map source part ids to runtime indices
- prepare side arrays/bitsets for later simulation/visibility logic

Important conclusion:
- `FUN_0163db10` is a confirmed runtime consumer of config-derived geometry input.
- however, in the currently inspected path it looks centered on damage/model parts, not directly on `gunnerOpticFps[].pos`.
- the strongest practical chain found so far is:
  - `vehicle_root + 0x1068` -> large geometry/damage runtime subobject
  - inside it, `+0x358`, `+0x3d8`, `+0x490`, `+0x5b8`, `+0x5e8`, `+0x6c8` are the major rebuilt arrays
- this is useful for target geometry reverse work, but it is not yet a clean optic mount offset chain.

### `FUN_05098200`

Confirmed behavior:
- parses `object`, `fm`, and `cutObject` entries
- builds arrays under `param_1 + 0x56c8` and nearby ranges
- handles `elementType`, `elementIndex`, `impulseVelLimits`, `usePartsMasses`

Interpretation:
- this is a destructible/object-parts builder path.
- useful for body/part geometry investigation.
- not a direct candidate for true optic mount resolution.

## Current Conclusions

- `my_sight_origin`
  - best config-side candidate: `gunnerOpticFps[].pos`
  - fallback config-side candidate: `gunnerFps.pos`
  - rejected as live-runtime primary path: first-person `local_camera -> camera_position`
  - current reverse parent: `FUN_017429f0`
  - current confirmed parsed storage for optic entries:
    - `+0x2d0/+0x2d8/+0x2e0/+0x2e4/+0x2e8`
  - current likely gap:
    - the direct consumer of the parsed optic-entry array is still unresolved
  - strongest non-weapon holder-path consumer found so far:
    - `FUN_01d23630`
  - current meaning:
    - live aim/turret code definitely reads config-side fields via `runtime + 0xfe8`
    - but the exact parsed `gunnerOpticFps[]` deref is still unresolved
  - checked direct `+0x2d0/+0x2e0` consumer family:
    - `FUN_01cffff0`
    - `FUN_01678fd0`
    - `FUN_01682400`
  - result:
    - this family is tied to secondary-weapon slot/current-index handling
    - it is not the optic-mount materialization path we want
  - downgraded as direct optic candidates:
    - `FUN_0163acc0`
    - `FUN_0163db10`
  - deprioritized helpers:
    - `FUN_01d1cd80`
    - `FUN_017a5060`
    - `FUN_017a2be0`
- `my_gun_origin`
  - current runtime barrel probe path is still the usable source
  - `weapon_rearsight_node__nodeTm` suggests exact node transforms may be recoverable later
- `target_turret_bbox`
  - best current candidate: turret/superstructure bbox path from `FUN_00ae4310` and `FUN_00ae4ed0`

## Direct `+0x2d0/+0x2e0` Consumer Findings

### `FUN_01cffff0`

Confirmed behavior:
- checks `*(int *)(param_1 + 0x2e0)`
- indexes:
  - `*(long *)(param_1 + 0x2d0) + slot * 0x18`
- walks entry objects from that slot and calls vfuncs on them
- also gates through:
  - `*(int *)(param_1 + 0x270 + idx * 4)`

Interpretation:
- direct consumer, but not enough by itself to prove optic usage.

### `FUN_01678fd0`

Confirmed behavior:
- gets object through:
  - `*(long *)(&DAT_00001090 + FUN_017a6860())`
- uses:
  - `obj + 0x2e8` as current slot index
  - `obj + 0x2e0` as slot count
- cycles through slots with:
  - `FUN_01cffff0(obj, next_slot)`
- emits:
  - `onSwitchSecondaryWeaponCycle`

Interpretation:
- this is secondary-weapon cycle logic, not optic mount logic.

### `FUN_01682400`

Confirmed behavior:
- large weapon/control update path
- uses object `lVar13 = plVar12[0x212]`
- calls:
  - `FUN_01cffff0(lVar13, *(undefined4 *)(lVar13 + 0x2e8))`
  - `FUN_01cfff20(lVar13)`
  - `FUN_01d00170(lVar13, *(undefined4 *)(lVar13 + 0x2e8))`

Interpretation:
- reinforces that this direct-consumer family belongs to weapon slot state, not seat optics.

## Non-Weapon Holder-Path Consumers

### `FUN_01d23630`

Confirmed behavior:
- runtime-heavy turret / aim logic path
- starts from live unit object at:
  - `param_4 + 0x248`
- reads runtime-held config pointer through:
  - `*(long *)(lVar9 + 0xfe8)`
- then checks:
  - `*(char *)(*(long *)(lVar9 + 0xfe8) + 0x2f0)`
- surrounding logic is aim / turret / targeting behavior, not metadata-only getters

Interpretation:
- this is the best non-weapon consumer found from the `+0xfe8` holder path so far.
- it still does not dereference `+0x2d0/+0x2e0` directly.
- it does prove that live turret/aim code consumes config-side fields through the runtime-held config pointer.
- field binding for `config + 0x2f0` is now known from parser:
  - in `FUN_018aaba0`
    - `param_1 + 0x2f0` = `commanderView` present flag
    - `param_1 + 0x2f1` = `commanderView.aimModeAvailable`
    - `param_1 + 0x2f8` = `commanderView.optics`
    - `param_1 + 0x300` = commander `zoomOutFov`
    - `param_1 + 0x304` = commander `zoomInFov`
    - `param_1 + 0x308` = `commanderView.sightSize`
- therefore `FUN_01d23630` is currently touching commander-view config gating, not parsed `gunnerOpticFps[]`.

### `FUN_078dc510`

Confirmed behavior:
- generic field accessor over an object pointer
- enum-like selector reads:
  - `+0x2a4`
  - `+0x238`
  - `+0x23c`
  - `+0x2b0`
  - `+0x2b4`
  - `+0x2b8`
  - `+0x2c8`

Interpretation:
- this is not a live optic/seat consumer
- it is useful only as confirmation that one runtime object family exposes the `gunnerFps`-adjacent fields directly

### `FUN_01d0bb20`

Confirmed behavior:
- large live gameplay consumer with callers:
  - `FUN_0231d5f0`
  - `FUN_00a74680`
  - `FUN_00ac8540`
- reads a per-seat/per-part record at `lVar28 = param_2 * 0x420 + *plVar22`
- uses config/runtime fields in the exact gunner range:
  - `+0x298`
  - `+0x2a0`
  - `+0x2a8`
  - `+0x2b0`
  - `+0x2c8`
- also consumes nearby transformed geometry:
  - `+0x3d8..+0x404`
  - `+0x78..+0xa4`
  - `+0x144..+0x1ec`
  - `+0x2b0`
  - `+0x310`
  - `+0x358`
- writes large batches of transformed points/matrices into live buffers passed in via `param_4`

Interpretation:
- this is the strongest live runtime geometry consumer found so far for the `gunnerFps` / seat-local block
- unlike `FUN_01d23630`, it is not just commander-view gating
- unlike `FUN_01cffff0` family, it is not weapon-slot cycling
- current best hypothesis:
  - `FUN_01d0bb20` materializes seat / sight / local aiming geometry from the config-adjacent block that includes `gunnerFps`
  - it may be the best bridge from parser-known seat fields to usable runtime optic-mount geometry

### `FUN_0231d5f0`

Confirmed caller behavior:
- prepares local transform state with `FUN_0189b3d0`
- resolves a live seat/view object via unit runtime holders:
  - `*(unit_1068 + 0xf0)[seat_index]`
  - fallback to `*(unit_1068 + 0xf0)[0]`
- resolves another live object through:
  - `*( *(unit_1068 + 0x88) + seat_index * 8 )`
- calls:
  - `FUN_01d19930(*(unit + 0x1090), seat_index, seat_obj_88, *(unit + 0xff0), local_state)`
  - `FUN_01d0bb20(*(unit + 0x1090), seat_index, output_buf, seat_obj_88, local_state, flag)`

Important call shape:
- `param_4` of `FUN_01d0bb20` is a live seat/view object from the `unit_1068 + 0x88` family
- `param_3` is an external output buffer:
  - `(result_index * 0x30) + *(**(unit + 0xff0) + seat_index * 0xf8 + 0xe0) + 0x18`

Interpretation:
- `FUN_01d0bb20` is not only mutating internal state; it can also project/build seat geometry into a caller-provided output buffer
- the `unit_1068 + 0x88/+0xf0` families are now strong candidates for live seat/sight runtime state

### `FUN_00a74680`

Confirmed caller behavior:
- higher-level ground vehicle update path
- builds local transform state with `FUN_0189b010`
- calls `FUN_01621390(..., seat=0/1, ...)`
- then calls:
  - `FUN_01d0bb20(param_1[0x212], 1, 0, *( *(param_1[0x20d] + 0x88) + 8 ), &local_68, 0)`
  - `FUN_01d0bb20(param_1[0x212], 0, 0, **(long **)(param_1[0x20d] + 0x88), &local_68, 0)`

Important call shape:
- again, `param_4` is a live seat/view object from `unit_runtime + 0x88`
- `param_3` can legitimately be `0`
- this means `FUN_01d0bb20` has two roles:
  - update/materialize live seat geometry internally
  - optionally emit it into an external output buffer when caller supplies one

Interpretation:
- this strongly reinforces that the right runtime target is no longer the parsed optic array directly
- the better extraction target is the live seat/view object family at `unit_runtime + 0x88/+0xf0` plus the transforms `FUN_01d0bb20` writes into/through it

### `FUN_0368b750`

Confirmed behavior:
- input:
  - `param_1` = 9-float basis/axis block
  - `param_2` = output angle #1
  - `param_3` = output angle #2
  - `param_4` = output angle #3
- normalizes the 3 basis vectors
- converts them through `atan2f/asinf`
- emits three angle-like outputs

Interpretation:
- this is a basis-to-Euler conversion helper
- it does not resolve optic mounts by itself
- but it is critical because `FUN_01ca7e90` uses it to populate seat object orientation state

### `FUN_01ca7e90`

Confirmed object-field writes:
- initializes/updates an object with many transform/state fields
- first resolves a live source object from `object + 0x230`
- when that live runtime source exists (`plVar15 != 0`), it writes:
  - `object + 0x2a0` = raw 8-byte copy of `plVar15[0x1a0]`
  - `object + 0x2a8` = low 32 bits of `plVar15[0x1a1]`
  - `FUN_0368b750((long)plVar15 + 0xcdc, object + 0x2ac, object + 0x2b0, object + 0x2b4)`
- also updates:
  - `object + 0x294/+0x29c` from `object + 0x114/+0x11c` or `object + 0x130/+0x138`
  - `object + 0x2e0`
  - `object + 0x2e4`
  - `object + 0x290`

Interpretation:
- this compact object family should no longer be treated as seat/view runtime proof
- re-validation now shows it belongs to a projectile family:
  - `FUN_01ca2920` manipulates `"rbuFire"` / `"missileOut"`
  - `FUN_01ca2920` binds `"thrust"` / `"mach"`
  - `FUN_01ca7e90` references `../../skyquake/prog/weapon/rocket.cpp(1053)`
- the useful residue is narrower:
  - `+0x2a0/+0x2a8` are raw values copied from `source[0x1a0]/source[0x1a1]`
  - `+0x2ac/+0x2b0/+0x2b4` are orientation angles derived from a runtime basis block
  - those fields are derived from the object currently held at `object + 0x230`
- this is evidence for a reusable source-object transform layout, not direct gunner seat/sight runtime state

### New inference: `source[0x1a0]` likely maps to source world position

Cross-check:

- `0x1a0 * 8 = 0xd00`
- the local repo repeatedly maps:
  - `unit/source + 0xcdc` -> rotation basis block
  - `unit/source + 0xd00/+0xd08` -> world position

Interpretation:

- `plVar15[0x1a0]` is still very likely the 8-byte `x/y` portion of source world position
- low 32 bits of `plVar15[0x1a1]` are very likely the `z` float at `source + 0xd08`
- but because `FUN_01ca7e90` is projectile-family code, this is not proof of a seat/optic materialization path
- keep this as source-layout evidence only

### `FUN_012f8fd0`

Confirmed behavior:
- trivial helper:
  - `return param_1 + 0xcdc`

Interpretation:
- confirms the block at `+0xcdc` is intentionally exposed as a sub-structure / transform block
- useful as a strong hint that `+0xcdc` is a meaningful embedded geometry object, not random packed fields

### `FUN_00b91e10`

Confirmed behavior:
- consumes:
  - `param_1 + 0xcdc/+0xce8/+0xcf4/+0xd00/+0xd04/+0xd08`
- repeatedly resolves part indices through:
  - `FUN_0162c580(...)`
  - part table at `**(long **)(param_1 + 0x230)`
- computes world-space candidate positions from:
  - local transform block at `+0xcdc`
  - part table rows at `part_index * 0x40`
- selects nearest candidate to `param_2`

Interpretation:
- `+0xcdc` is not just orientation angles; it participates directly in transforming part-space points into world-space
- this means the source object behind `plVar15` likely contains a full local transform anchor usable for seat/sight geometry
- the reverse target should now move from “find consumer of parsed optic array” to:
  - find a non-projectile runtime consumer tied to the confirmed `unit_runtime + 0x88 / +0xf0` path
  - use `source + 0xd00/+0xd08` and `source + 0xcdc` only as reusable source-layout evidence

### `FUN_01d17f90`

Confirmed behavior:
- iterates the `0x178`-stride subrecords stored under a holder family passed from `FUN_01d4d3e0`
- reads a per-seat part-table object through:
  - `(*(long *)(&DAT_00001068 + *(long *)(param_1 + 0x248)) + 0xf0)[seat]`
  - fallback to slot `0`
- uses a ushort selector from `record + 0x50[seat]` as the part index
- when the part index is valid, loads a `0x40`-stride transform row from that `unit + 0xf0[seat]` table
- multiplies that row with local templates from `record + 0x30 + seat*0x30`
- writes composed transforms into:
  - `record + 0x88 + seat*0x30`
  - `record + 0x20 + seat*0x30`
  - auxiliary arrays rooted at `record + 0x140`
  - auxiliary object arrays rooted at `record + 0x150`
- for object-backed entries, further composes with the owning unit transform at:
  - `unit + 0xcdc/+0xce8/+0xcf4/+0xd00/+0xd04/+0xd08`

Interpretation:
- this is the clearest proof so far that `unit_runtime + 0xf0` is a seat-indexed part-transform source
- the `0x178`-stride records under this family are not generic noise; they carry per-seat part selectors and local templates
- if we can name the ushort selector table at `record + 0x50`, we can likely map runtime entries to tank datamine names such as:
  - `optic_gun_dm`
  - `gunner_dm`
  - `bone_turret`
  - `bone_gun`
  - `bone_gun_barrel`

### `FUN_01d4d3e0`

Confirmed behavior:
- acts as a dispatcher over the holder rooted at `param_1`
- first passes five buckets into `FUN_01d17f90`:
  - `param_1 + 0xf0`
  - `param_1 + 0x108`
  - `param_1 + 0x120`
  - `param_1 + 0x138`
  - `param_1 + 0x168`
- then passes eight buckets into `FUN_01d4d170`:
  - `param_1 + 0xf0`
  - `param_1 + 0x108`
  - `param_1 + 0x120`
  - `param_1 + 0x138`
  - `param_1 + 0x150`
  - `param_1 + 0x168`
  - `param_1 + 0x180`
  - `param_1 + 0x198`

Interpretation:
- this function does not build the record family
- it is the runtime dispatcher that fans out work across pre-existing bucket arrays
- the constructor/populator for `record + 0x50` must sit upstream from this stage

### `FUN_01d4d7c0`

Confirmed behavior:
- checks `owner + 0x248` before doing work
- calls `FUN_01d05000(...)`
- then runs `FUN_01d4d500(...)` only across the first three buckets:
  - `owner + 0xf0`
  - `owner + 0x108`
  - `owner + 0x120`

Interpretation:
- this is a metadata/object-entry pre-pass for the same owner object used by `FUN_01d4d3e0`
- it is not the bucket/selector constructor either
- the split now looks like:
  - upstream builder populates bucket records and ushort selectors
  - `FUN_01d4d7c0` maintains/generated downstream object-entry state
  - `FUN_01d4d3e0` consumes the finished record buckets for runtime transform dispatch

### `FUN_01d4c790`

Confirmed behavior:
- resolves one runtime object through the owner-local slot/object lists at:
  - `*(owner + 800) + *(int *)(record + 4) * 0x18`
  - object index `*(uint *)(record + 8)`
- builds a temporary bitset/vector sized from either:
  - virtual count on the selected object, or
  - `*(uint *)(record + 0x148)`
- for the special object mode, uses object-local state around:
  - `object + 0x584`
  - `object + 0x6b`
  - per-subentry data at `+0xa8 + idx*0xa0`
- returns the temporary bitset through the small vector rooted at `param_1`

Interpretation:
- this is not part-selector setup
- it proves `record + 4/+8` belong to owner-local object-list lookup, not to the unresolved ushort selector table at `record + 0x50`
- the generated bitset is downstream metadata that later feeds the object-entry payload at `record + 0xa0`

### `FUN_01d4ca50`

Confirmed behavior:
- walks one bucket as `count * 0x178` records
- only processes records with `*(char *)(record + 0xc) != 0`
- validates `record + 4/+8` against the owner-local slot/object lists at `owner + 800`
- falls back to `record + 0x16c` when the object lookup path is unavailable
- otherwise:
  - calls `FUN_01d4c790(...)` to build the record-local bitset/filter payload
  - copies that payload through `FUN_01cf0c60(...)`
  - writes/refreshes generated state at `record + 0xa0` through `FUN_01d60810(...)`

Interpretation:
- `record + 0xa0` is confirmed again as generated downstream object-entry state
- `record + 0x16c` behaves like a fallback/generated-object selector, not like the semantic part selector at `record + 0x50`

### `FUN_01d4cd40`

Confirmed behavior:
- is the three-bucket sibling of `FUN_01d4ca50`
- walks `0x178` records, checks `record + 0xc`, resolves `record + 4/+8` through `owner + 800`, and rebuilds the same temporary bitset via `FUN_01d4c790(...)`
- writes the resulting generated payload into `record + 0xa0` through `FUN_01d60810(...)`

Interpretation:
- this keeps the same separation intact for the first-three-bucket metadata pass:
  - `record + 4/+8` = owner-local object lookup
  - `record + 0xa0` = generated payload
  - `record + 0x50` = still separate unresolved semantic part-selector table

### `FUN_01d4d500`

Confirmed behavior:
- also walks `0x178` records in the first three buckets
- only acts when `*(int *)(record + 0x158) != 0` and `*(int *)(record + 4) >= 0`
- resolves `record + 4/+8` through `owner + 800`
- derives a variant/choice index from selected-object virtuals and per-object subentry data:
  - object byte flags at `+0x584`
  - object table at `object[0x6b] + 0xa8 + idx*0xa0`
- rebuilds the temporary bitset with `FUN_01d4c790(...)`
- then writes the chosen object-entry state to `record + 0xa0` through `FUN_01d60400(...)`

Interpretation:
- `record + 0x158` is another downstream generated-payload control field
- this function strengthens the split:
  - object-list selection and generated payloads live around `record + 4/+8/+0xa0/+0x158/+0x16c`
  - semantic seat/part selection still lives elsewhere, with `record + 0x50` remaining the best unresolved upstream target

### `FUN_014084e0` and `FUN_014084f0`

Confirmed behavior:
- both are thin wrappers around `FUN_01d52210`
- `FUN_014084f0` gathers a few state bytes/flags from sibling objects before forwarding them

Interpretation:
- neither function is a selector-table constructor
- they only confirm that `FUN_01d52210` is used as a generic owner-update stage

### `FUN_0172e3a0`, `FUN_0174e060`, and `FUN_0174f4f0`

Confirmed behavior:
- each function calls `FUN_01d52210(...)`
- each function also calls `FUN_01d512d0(...)`
- the surrounding logic is strongly flight/generic-vehicle oriented:
  - `Warp drive active` logging
  - overspeed / cut-part handling
  - repeated flight-model and failure-state updates
  - follow-up calls into `FUN_01d55f50(...)` and `FUN_01d00850(...,7)`

Interpretation:
- these functions confirm that `FUN_01d512d0` and `FUN_01d52210` belong to a generic owner/runtime-management layer
- this layer is upstream of the bucket consumers, but it still does not expose where `record + 0x50` is populated
- for the ground-optic target, this path is now lower-priority than a more specific ground-owner/builder path

### `FUN_01d020b0`

Confirmed behavior:
- works over `(owner + 800)[slot]`, where each slot is an object list with pointer/count
- when `param_3 == 0`, it returns the first live/usable object candidate
- when `param_3 != 0`, it builds a temporary filtered index list
- filtering uses:
  - `FUN_01d5b7f0(owner + 0x2b8, token, slot)`
  - `FUN_01d5b8c0(object[0x81], filter_token)`
- it also checks per-object readiness through virtual methods like `+0xd0`, `+0x198`, `+0xc0`, `+0xd8`, `+0xb8`

Interpretation:
- this is a slot/object selector helper for the owner family rooted at `DAT_00001090 + unit`
- it does not populate the `0x178`-stride record selectors at `record + 0x50`
- but it confirms that `owner + 0x2b8` carries a reusable filter-token state that gates object selection across multiple slot families

### `FUN_01d4de30`

Confirmed behavior:
- reads slot lists from `(owner + 800)[slot]`
- uses the same `owner + 0x2b8` filter-token path through `FUN_01d5b7c0` / `FUN_01d5b8c0`
- for some slot kinds it builds candidate subsets, ranks them, and dispatches updates through virtual object methods
- for other slot kinds it falls back to direct `object->method(0x120)` / `FUN_01c70390(...)` style updates
- it also writes per-slot timing/result data into owner-local storage such as:
  - `owner + 0x134c + slot*0x50` for the `param_4 - 7` group
  - `*(float *)((long)slot_entry + 0x3c)` / `*(float *)(slot_entry + 8)` in selected object entries

Interpretation:
- this is a heavy runtime dispatcher/update path for slot-based object families under the same owner
- it still operates downstream from the unresolved `record + 0x50` part-selector problem
- the useful new split is:
  - `owner + 800` = slot/object lists
  - `owner + 0x2b8` = reusable filter-token state
  - `record + 0x50` = still separate upstream part-selector table for the `0x178`-stride record family

### `FUN_01d025e0`, `FUN_01d02640`, `FUN_01d026b0`, and `FUN_01d02730`

Confirmed behavior:
- all four are thin wrappers around `FUN_01d020b0`
- they derive the same filter token from:
  - `owner + 0x248`
  - `owner->d10 + 0x3220`
  - the `*(short *)(owner + 0x54) == 0` state
- outputs are simple query-style results:
  - `FUN_01d025e0` just triggers the selection helper
  - `FUN_01d02640` returns `selected_object + 0x408`
  - `FUN_01d026b0` returns the negated result of virtual method `+0x158`
  - `FUN_01d02730` returns a few virtual-query fields from the selected object

Interpretation:
- these functions are not constructors for the `0x178`-stride record family
- they only expose lightweight queries over the owner’s slot/object lists

### `FUN_01d1d410`

Confirmed behavior:
- selects slot `4` through `FUN_01d020b0(...)`
- reads a few readiness/visibility style methods from the selected object
- combines them with owner-side tuning fields near:
  - `owner->d10 + 0x7c3b`
  - `owner->d10 + 0x7c3d`
  - `owner->d10 + 0x2b68`
  - `owner->d10 + 0x2b6c`
  - `owner->d10 + 0x7cc4`

Interpretation:
- another consumer/query path over slot-selected objects
- useful as evidence that slot `4` has special meaning in this owner family
- not evidence for `record + 0x50` construction

### `FUN_01d1d220`

Confirmed behavior:
- iterates objects returned by `FUN_01d5b770(owner + 0x2b8)`
- aggregates per-object counts and flags for slot ids `3..9`
- updates owner counters around:
  - `owner + 0x12d8 .. +0x12f0`
- conditionally triggers a callback off a secondary owner object at `owner->0x248->0xf60`

Interpretation:
- this function consumes the `owner + 0x2b8` filter-token/object-selection layer
- it is downstream bookkeeping, not the origin of the `0x178`-stride part-selector records

### `FUN_01d00180`

Confirmed behavior:
- scans `(owner + 800)[slot]`
- finds a live object through virtual method `+0x1f0`
- emits object transform data through virtual method `+0x278`
- when allowed, it can average/merge data from a following object entry
- returns the chosen object pointer and fills an output transform buffer

Interpretation:
- this is a slot/object transform-query helper
- it reinforces that `(owner + 800)[slot]` is a runtime object-list registry with geometry-capable members
- still separate from the unresolved `0x178`-stride part-selector records

### `FUN_01d5b320`, `FUN_01d5b4e0`, and `FUN_01d5b590`

Confirmed behavior:
- all three index the same registry-like substructure under `owner + 0x2b8`
- `FUN_01d5b320(slot)`:
  - returns true when any object in the slot passes virtual method `+0xd0`
- `FUN_01d5b4e0(slot)`:
  - sums virtual method `+0xc0`
- `FUN_01d5b590(slot)`:
  - sums virtual method `+0xd8`

Interpretation:
- `owner + 0x2b8` is now best treated as a slot-group registry over runtime objects
- these helpers expose “present / active / ready” style counts for each slot group
- this registry is useful for owner-local selection and monitoring, but it is not the constructor of the `0x178`-stride `record + 0x50` selector table

### `FUN_0167a970` and `FUN_01747600`

Confirmed behavior:
- both consume the same owner-local registry layers:
  - `owner + 0x2b8`
  - `owner + 0x2d0`
  - `owner + 0x2f0`
- `FUN_0167a970` mixes slot-object lookups (`FUN_01d00180`) with registry counts from `FUN_01d5b4e0` / `FUN_01d5b590`
- `FUN_01747600` builds status flags from the same helpers

Interpretation:
- these functions are monitoring/consumer paths over the registry layer
- they strengthen the split between:
  - owner-local slot/object registry at `+0x2b8/+0x2d0/+0x2f0`
  - separate bucket-record family at `+0xf0..+0x198`

### `FUN_01d2e060` and `FUN_01d2e1c0`

Confirmed behavior:
- both are helper routines used by `FUN_01d55f50`
- they operate on arrays of `0x50`-byte entries, not `0x178`-byte records
- `FUN_01d2e060`:
  - reallocates/grows a vector-like buffer
  - copies existing `0x50` entries
  - appends one new `0x50` entry
- `FUN_01d2e1c0`:
  - filters entries from a source vector based on bit tests in the second byte
  - appends matching entries into a destination vector
  - updates count fields around `+0x2b8/+0x2c0` of its local working structure

Interpretation:
- these helpers belong to the temporary filtered-object-list machinery inside `FUN_01d55f50`
- they are not constructors for the `0x178`-stride bucket records consumed by `FUN_01d17f90` / `FUN_01d4d170`
- this is another useful negative result: the `0x50`-entry helper family is separate from the unresolved bucket-record builder

### `FUN_01d5b7f0`, `FUN_01d5b770`, and `FUN_01d5b8c0`

Confirmed behavior:
- `FUN_01d5b7f0(owner + 0x2b8, token, slot)`:
  - returns `selected_group_entry->0x408` when the slot token matches
- `FUN_01d5b770(owner + 0x2b8, slot)`:
  - returns pointer/count metadata from `owner + 0x2a8 + slot*0x18`
- `FUN_01d5b8c0(a, b)`:
  - compares registry/object identity via `+0x80`, with pointer-equality fallback

Interpretation:
- this confirms `owner + 0x2a8/+0x2b8` is a registry/group layer for slot-object selection
- it remains distinct from the `+0xf0..+0x198` bucket arrays and their `record + 0x50` part-selector table

### `FUN_01d4d170`

Confirmed behavior:
- walks the same `0x178`-stride record family used by `FUN_01d17f90`
- copies already-built `0x40` transforms from `record + 0x20 + seat*0x30` into auxiliary storage at `record + 0x140`
- always forwards the composed payload at `record + 0x88 + seat*0x30` into `FUN_01d5f800(record + 0xa0, ...)`

Interpretation:
- this is the next hard consumer after `FUN_01d17f90`
- `record + 0x88` is not dead cache; it is live dispatch payload
- `record + 0xa0` is the downstream object-entry layer that receives the already-composed transform set

### `FUN_01d4c790`

Confirmed behavior:
- resolves a gameplay object from indexed storage rooted at `(param_2 + 800)`
- uses `record.type` / `record.index` style selectors to pick the object family
- allocates or rebuilds a bitset work buffer through `FUN_01c86150`
- fills that bitset from object-provided counts and masks
- returns a filtered selection set for later object-entry updates

Interpretation:
- this function does not name the part selector at `record + 0x50`
- instead, it builds the filtered downstream target set that `record + 0xa0` and later update functions consume
- that makes `record + 0xa0` a generated object-entry layer, not the root semantic selector table

### `FUN_01d4d500`

Confirmed behavior:
- iterates the same `0x178`-stride record family
- only processes records with non-zero state near `record + 0x158`
- calls `FUN_01d4c790(...)`
- then forwards the chosen subset into `FUN_01d60400(object, record + 0xa0, chosen_index, bitset, ...)`

Interpretation:
- this is one of the metadata-driven producers for the `record + 0xa0` layer
- it still sits downstream from the unresolved seat-part selector table at `record + 0x50`

### `FUN_01d4ca50` and `FUN_01d4cd40`

Confirmed behavior:
- both call `FUN_01d4c790(...)`
- both then forward state into `FUN_01d60810(record + 0xa0, ...)`

Interpretation:
- these are sibling metadata/update paths for the same generated object-entry layer rooted at `record + 0xa0`
- they strengthen the split:
  - `record + 0x50` = upstream per-seat part selector table
  - `record + 0xa0` = downstream generated object-entry storage and dispatch state

Current highest-value unresolved question:
- which constructor or owner populates the ushort selector table at `record + 0x50`
- once that builder is identified, we should be able to map selectors onto tank datamine names such as `optic_gun_dm`, `gunner_dm`, `bone_turret`, `bone_gun`, or `bone_gun_barrel`
- copies already-built `0x40` transforms from `record + 0x20 + seat*0x30` into `record + 0x140` when the record is not in the alternate path
- always dispatches `FUN_01d5f800(record + 0xa0, record + 0x88 + seat*0x30, ...)`

Interpretation:
- `FUN_01d17f90` and `FUN_01d4d170` form a coherent consumer chain over the same record family
- `record + 0x88` now looks like the composed transform payload consumed by later render/gameplay object updates
- this strengthens the plan to reverse the record metadata instead of chasing the projectile-family false lead

### Datamine Cross-Check: Ground Tank Naming

Concrete `Toy` evidence from `gamedata/units/tankmodels/ussr_bt_7_1937.blkx`:
- crew seat naming:
  - `gunner.dmPart = "gunner_dm"`
  - `driver.dmPart = "driver_dm"`
  - `loader.dmPart = "loader_dm"`
- weapon/turret naming:
  - main gun trigger `gunner0`
  - `turret.head = "bone_turret"`
  - `turret.gun = "bone_gun"`
  - `turret.barrel = "bone_gun_barrel"`
  - `barrelDP = "gun_barrel_dm"`
  - `breechDP = "cannon_breech_dm"`
- optics/damage naming:
  - `optic_gun_dm`
  - `optic_turret_01_dm` ...
  - `commander_panoramic_sight_dm`
- cockpit fallback/view naming:
  - `cockpit.headPos`
  - `cockpit.headPosOnShooting`
  - `cockpit.sightFov`

Interpretation:
- the datamine gives us a practical naming dictionary for the runtime part-table reverse
- the next best correlation target inside the `unit + 0xf0[seat]` path is no longer abstract “optic-ish parts”
- it is specific ground-tank names from the datamine family above

### `FUN_01d0b590`

Confirmed cleanup behavior over the `0x308` seat-object records:
- if `record + 0x19 != 0`, releases object at `record + 0x298`
- always releases object at `record + 0x2a0`
- if `record + 0x288 != 0`, releases that object too
- if `record + 0x2b8 != 0`:
  - treats `record + 0x2a8` as pointer to an array
  - array element size is `0x58`
  - releases `entry + 0x10` for each element
  - then zeroes `record + 0x2b8`
- also releases `record + 0x2f8`

Interpretation:
- for the `FUN_01d0bb20` `0x308`-stride record family specifically:
  - `+0x2a0` = refcounted source/object pointer
  - `+0x2a8` = pointer to array of entry records
  - `+0x2b8` = count of those entries
- this does not prove that another object family using the same offsets has the same field meanings
- therefore the old direct field-match from `FUN_01ca7e90` into this record layout was too aggressive

### `FUN_05a921e0`

Confirmed behavior:
- constructor / initializer for a large PhysX scene-side object
- caller:
  - `FUN_058f8c90`
- not related to the seat/view runtime family under investigation

Interpretation:
- direct store match for `+0x2a0` was a false lead from an unrelated object family

### `FUN_00b91d70`

Decompile result:

```c
long FUN_00b91d70(long param_1)
{
  return *(long *)(&DAT_000036f0 + param_1) + 0x23f8;
}
```

Implications:

- this is a direct accessor into a sub-structure at `object + 0x23f8`
- it is used by mixed gameplay families, including some seat/aim code and some weapon/bullet code
- by itself it is not the optic mount path, but it confirms another intentionally exposed embedded geometry/state block in the same source-object family

Current status:

- treat `+0x23f8` as a useful neighboring sub-structure, not as the primary optic-mount target

### `FUN_01c887c0`

This function is more important than it first looked.

Observed behavior:

- it starts from the same seat/runtime family and calls `FUN_01cafb70(...)`
- in one live gameplay branch it reads directly from the unit/source object:
  - `unit + 0xcdc`
  - `unit + 0xce8`
  - `unit + 0xcf4`
  - `unit + 0xcfc`
- then it subtracts those transformed offsets from `param_2 + 0x114/+0x11c`

Why this matters:

- this is direct gameplay evidence that the `+0xcdc` block is consumed live, not just by helper functions
- it strengthens the conclusion that `+0xcdc` belongs to the true source/seat geometry family behind the seat object
- it also suggests the runtime path may be:
  - seat/view object -> source object
  - source object -> transform block at `+0xcdc`
  - gameplay code consumes that block directly when updating local projectile/view state

Conclusion:

- `FUN_01c887c0` is now one of the strongest non-helper proofs that `+0xcdc` is the embedded transform block we actually want

### Local repo cross-check: `+0xcdc` / `rotation_matrix`

Cross-check from local scanner references and raw logs:

- `src/v1/RAW.txt`
  - repeatedly records `UNIT_X = 0xd00 (หมุน = 0xcdc)`
- `src/v1/scanner/_win_ref_offsets`
  - current-style entries use `rotation_matrix_offset = 0xce4`
  - older/alternate snapshots also show nearby rotation-matrix offsets in the same family

Interpretation:

- the `+0xcdc` block is very likely the unit/source object's orientation matrix block
- this means our earlier reading was too strong:
  - `+0xcdc` is strong proof of a live transform basis
  - but it is not, by itself, proof of an optic-mount-specific transform

Corrected conclusion:

- the important chain is now:
  - `seat + 0x230` -> source object
  - source object `+0xcdc` -> orientation basis of that source object
  - `seat + 0x2a0 = source[0x1a0]` remains the better optic/sight-anchor candidate
- so the next reverse target should shift from “is `+0xcdc` the optic mount?” to:
  - what exactly is `source[0x1a0]`
  - and whether `seat + 0x2a0` is the real sight/seat anchor object

### `FUN_01caf750`, `FUN_01caecc0`, `FUN_01ca9350`

These were checked to avoid another false lead.

- `FUN_01caf750`
  - update/dispatch function
  - refreshes runtime state and forwards to source object hooks
  - not the constructor/writer of `seat.+0x2a0`
- `FUN_01caecc0`
  - trivial 16-bit split helper
  - unrelated to optic geometry
- `FUN_01ca9350`
  - empty stub
  - not useful for lineage
- do not use this path for optic/sight reverse

### `FUN_01d23f60`

Confirmed behavior:
- tiny wrapper around `FUN_01d23630`
- passes fixed angle pair `0x4334000043340000`

Interpretation:
- same family; no extra optic-array evidence.

### `FUN_01d248b0`

Confirmed behavior:
- higher-level aim / tracking control path
- calls `FUN_01d23630(param_4, param_7, param_8, 0, &DAT_07f4a0a0)` near the end
- also manages local aim state, target blending, and reticle/turret state

Interpretation:
- confirms `FUN_01d23630` belongs to the live aim-control family.
- still no direct `gunnerOpticFps[]` deref in this branch.

### `FUN_01d50ca0`

Confirmed behavior:
- another aim / turret control caller of `FUN_01d23630`
- invokes it either with default constants or with values derived from current weapon/turret state

Interpretation:
- same live aim-control family.
- reinforces that the `+0xfe8 -> +0x2f0` path is about commander/aim-mode gating, not the parsed gunner-optic array itself.

### `FUN_0186f7f0`

Confirmed behavior:
- if transformed runtime data is missing, it falls back to:
  - `*(undefined8 *)(*(long *)(param_1 + 0xfe8) + 0xf4)`

Interpretation:
- another proof that live runtime geometry code uses fields from the holder-path config object.
- not a direct `gunnerOpticFps[]` array consumer.

### `FUN_016b51c0`

Confirmed behavior:
- reads geometry/range-like fields from:
  - `config + 0xc4`
  - `config + 0xc8`
  - `config + 0xcc`
  - `config + 0x1ec`
  through the `+0xfe8` holder path

Interpretation:
- useful proof of active gameplay consumption of config geometry fields.
- still not the parsed optic-array deref we need.

## Runtime Dumper Validation

### `optic_runtime_probe_dumper.py`

Validated on `ussr_2s3m` in first-person:
- `Cam-Barrel Δ mean = [0.4164, -0.0216, -1.6128]`
- `stddev = [0.0, 0.0, 0.0]`

Interpretation:
- first-person active camera minus barrel-base local delta is stable enough to use as a runtime candidate.
- only the `up` component should be trusted first for parallax math.
- this path should be limited to first-person / gunner view.

Live gameplay rejection:
- in live FPS gameplay the world-space `camera_world - barrel_base_world` path collapsed to `(0, 0, 0)`
- screen-space delta also collapsed to `0`
- in pause / stopped / third-person states the same path became non-zero

Conclusion:
- `local_camera -> camera_position` is an active view camera path, not a stable live firing optic mount path.
- do not use it as the primary live geometry source for sight-to-gun compensation.
- keep it only as a fallback / view-state hint until true optic mount runtime data is resolved.

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

## Additional Owner/Bucket Notes

### `FUN_01d04e20`

Confirmed behavior:
- iterates a fixed selector list from `DAT_0991c220 .. DAT_0991c24f`
- queries object groups through:
  - `FUN_01d5b750(owner + 0x2b8, selector_id)`
- walks returned object pointers and dispatches their virtual `+0x120`
- uses owner state at:
  - `owner + 0x248`
  - `owner + 0x250`
  - `owner + 0x2b8`
- may stop early depending on object-local byte `object + 0x29b`

Interpretation:
- this is a registry/filter pre-pass over owner-local object groups
- it belongs to the already-separated `(owner + 800)` / `owner + 0x2b8` machinery
- do not treat it as an upstream builder for the `0x178`-stride selector records

### `FUN_00a4b870`

Confirmed behavior:
- updates the owner object at `*(DAT_00001090 + unit)`
- optional early stage:
  - `FUN_01d512d0(...)`
- always runs:
  - `FUN_01d04e20(...)`
  - `FUN_01d52210(...)`
  - `FUN_01d4d7c0(...)`
- then iterates owner-local objects from:
  - `owner + 0x2f0`
  - count at `owner + 0x300`
- each object receives a virtual `+0x130` dispatch with filter-token root:
  - `owner + 0x2b8`

Interpretation:
- this is a strong owner update path for the runtime object at `DAT_00001090 + unit`
- but it still sits on the registry/object-dispatch side of the split
- it does not expose the constructor that seeds `record + 0x50`

### `FUN_01d4cc20`

Confirmed behavior:
- iterates all eight owner buckets:
  - `+0xf0`
  - `+0x108`
  - `+0x120`
  - `+0x138`
  - `+0x150`
  - `+0x168`
  - `+0x180`
  - `+0x198`
- forwards each bucket to:
  - `FUN_01d4ca50(owner, ctx, bucket, local_state, extra)`
- optional extra object pass:
  - `owner + 0x1620`
  - count at `owner + 0x1630`
- ends with:
  - `FUN_01ceb050(owner + 0x1b8, ctx)`

Interpretation:
- this is a post-pass wrapper over the full bucket family
- it consumes prebuilt `0x178` records and downstream object-entry state
- it is not the bucket allocator/constructor

### `FUN_01d4d0f0`

Confirmed behavior:
- iterates only the first three owner buckets:
  - `+0xf0`
  - `+0x108`
  - `+0x120`
- forwards each bucket into:
  - `FUN_01d4cd40(owner, ctx, bucket, local_state, extra)`

Interpretation:
- this is the three-bucket counterpart to `FUN_01d4cc20`
- it reinforces the split between:
  - first-three-bucket metadata/object-entry work
  - all-bucket post-dispatch work

### `FUN_0231caf0` and `FUN_0231cba0`

Confirmed behavior:
- both prepare a small local state block from fields around:
  - `+0x5338`
  - `+0x5348`
  - `+0x5358`
- then call:
  - `FUN_0231caf0` -> `FUN_01d4cc20(*(DAT_00001090 + unit), ...)`
  - `FUN_0231cba0` -> `FUN_01d4d0f0(*(DAT_00001090 + unit), ...)`

Interpretation:
- these are thin wrappers above the bucket post-pass helpers
- useful for locating higher owner/render call chains
- not bucket constructors

### `FUN_014085a0`

Confirmed behavior:
- thin wrapper that eventually forwards into:
  - `FUN_01d04e20(...)`

Interpretation:
- reinforces that `FUN_01d04e20` is a reusable owner-registry stage
- adds no evidence for `record + 0x50` construction

### Updated caller picture for `FUN_00a74680` and `FUN_0231d5f0`

Confirmed behavior:
- both functions still end by dispatching:
  - `FUN_01d4d3e0(*(DAT_00001090 + unit), seat, local_transform_state)`
- `FUN_0231d5f0` also runs:
  - `FUN_01d19930(...)`
  - `FUN_01d0bb20(...)`
  - `FUN_01620fa0(...)`

Interpretation:
- these remain strong proof that `unit + 0x88 / +0xf0` is live runtime geometry
- but they are consumers of an already-built owner bucket family, not the code that seeds its selectors

### `FUN_00ad82b0`

Confirmed behavior:
- updates `*(DAT_00001090 + unit)` using the now-familiar owner chain:
  - optional `FUN_01d512d0(...)`
  - `FUN_01d52210(...)`
  - `FUN_01d4d7c0(...)`
- then calls:
  - `FUN_00ad7cf0(unit)`
- then iterates owner-local objects from:
  - `owner + 0x2f0`
  - count at `owner + 0x300`
- each object receives virtual `+0x130` with:
  - filter-token root `owner + 0x2b8`
  - a randomized threshold based on `local_5c`

Interpretation:
- this is another sibling owner update mode, not a bucket constructor
- it reinforces that:
  - `01d512d0/01d52210/01d4d7c0` form an owner-update stage
  - iteration over `owner + 0x2f0/+0x300` is downstream object dispatch

### `FUN_00b26a00`

Confirmed behavior:
- same high-level owner chain again:
  - optional `FUN_01d512d0(...)`
  - `FUN_01d52210(...)`
  - `FUN_01d4d7c0(...)`
- then iterates:
  - `owner + 0x2f0`
  - count at `owner + 0x300`
- dispatches each object via virtual `+0x130`
- unlike `FUN_00ad82b0`, this path passes a constant truthy test into the virtual call instead of a randomized compare

Interpretation:
- this is another sibling gameplay/update mode over the same owner-local object list
- it still belongs to the object-dispatch side of the split, not to bucket construction

### `FUN_00b11250`

Confirmed behavior:
- heavy gameplay/aim/fire loop that eventually calls:
  - `FUN_00ad82b0(...)`
- also works extensively with a separate `0x300`-stride side-record family rooted at:
  - `owner + 0x1c8`
  - count at `owner + 0x1d8`
- uses many gameplay/fire checks around:
  - `object + 0x10`
  - `record + 0xd0/+0xd2`
  - unit-local state near `param_1 + 0x2e30`

Interpretation:
- this path is valuable for placing `00ad82b0` inside the larger gameplay loop
- but it does not look like the constructor for the `+0xf0..+0x198` bucket family
- it introduces yet another adjacent record family:
  - `owner + 0x1c8`, stride `0x300`
  - separate from the unresolved `0x178`-stride bucket records

### `FUN_00b41720`

Confirmed behavior:
- heavy sibling gameplay path that eventually calls:
  - `FUN_00b26a00(...)`
- before that, it also iterates the separate `owner + 0x1c8` / `0x1d8` / stride `0x300` family
- uses transform sources around:
  - `param_1 + 0x4a00`
  - `param_1 + 0x4a18`
  - `param_1 + 0x4728`
  - `param_1 + 0x4740`

Interpretation:
- this is a sibling of `FUN_00b11250`, not an upstream bucket constructor
- it further confirms the pattern:
  - high-level gameplay loop
  - side-record family at `owner + 0x1c8`
  - then owner update mode over `owner + 0x2f0/+0x300`
- the missing constructor for the `0x178`-stride bucket records is still elsewhere

### `FUN_01d512d0`

Confirmed behavior:
- heavily updates the separate side-record family rooted at:
  - `owner + 0x1c8`
  - count at `owner + 0x1d8`
  - stride `0x300`
- calls:
  - `FUN_01d20be0(...)`
  - `FUN_01d248b0(...)`
  - `FUN_01d50ca0(...)`
- also iterates another object list at:
  - `owner + 0x50`
  - count at `owner + 0x60`
- writes many transformed values through part/object state, but not through `owner + 0xf0..+0x198`

Interpretation:
- this is an aim/control updater over the `0x300`-stride side-record family
- it is not the constructor for the unresolved `0x178`-stride bucket family

### `FUN_01d52210`

Confirmed behavior:
- iterates object pointers from:
  - `owner + 0x308`
  - count at `owner + 0x318`
- maintains a cache/object block rooted at:
  - `owner + 0x1400 .. +0x1590`
- repeatedly uses:
  - `owner + 0x248`
  - `owner + 0x250`
  - `owner + 0x298`
  - `owner + 0x2b8`
- may allocate/rebind cached objects through lookups from `local_2c0 + 0x150`
- does not iterate or seed the bucket headers at `owner + 0xf0..+0x198`

Interpretation:
- this is another owner-local object/cache management stage
- it sits on the object-dispatch side of the split, not the bucket-construction side

### `FUN_01d4d850`

Confirmed behavior:
- scans owner-local object lists rooted at:
  - `*(owner + 800) + 0x150`
  - count at `*(owner + 800) + 0x158`
- for active objects, walks their internal `+0xa8 + idx*0xa0` groups
- aggregates two output counters into `*param_2` and `*param_3`

Interpretation:
- this is an aggregation/count helper for owner-local runtime objects
- it is not part of the `0x178` bucket-record builder path

### `FUN_01d4da90`

Confirmed behavior:
- consumes one selected runtime object
- if object is not in the special branch, aggregates counts from its internal:
  - `object[0x6b] + 0xa8 + idx*0xa0`
- used only by:
  - `FUN_01d4de30`

Interpretation:
- another object-metrics helper near the registry/object-update path
- useful for separating concerns inside the `01d4xxxx` region
- not evidence for bucket construction

### `FUN_0231b470`

Confirmed behavior:
- high-level wrapper around rendering/effect-style dispatch decisions
- under one branch it prepares a local state block and calls:
  - `FUN_01d4cc20(owner, ctx, local_state, param_4 & 1, extra)`
- other branches call:
  - `FUN_02353290(...)`
  - `FUN_0161c030(...)`
  - `FUN_0161be90(...)`
  - `FUN_018913d0(...)`
- heavily gated by runtime view/state flags around:
  - `param_1 + 0x13c`
  - `param_1 + 0x285c`
  - `param_1 + 0x39f0`
  - `param_1 + 0x41a8`
  - `param_1 + 0x5338 .. +0x5360`

Interpretation:
- this is a higher wrapper above the bucket post-pass, not the constructor for bucket records
- it places `FUN_01d4cc20` in a render/effect dispatch context rather than an initialization context

### `FUN_0231cc50` and `FUN_0231ccf0`

Confirmed behavior:
- both are thin gating wrappers around:
  - `FUN_0231b470(...)`
- they mainly check:
  - visibility/state masks
  - current selected/global object guards

Interpretation:
- these are wrapper-only paths above `FUN_0231b470`
- they do not help explain `record + 0x50` construction

### `FUN_00bba640`

Confirmed behavior:
- high-level gameplay wrapper that eventually ends with:
  - `FUN_00a4b870(param_3, param_4, lVar16 + 0xfb0, lVar16 + 0x10, ...)`
- before that it heavily processes:
  - side-record family at `owner + 0x1c8` / count `+0x1d8` / stride `0x300`
  - owner-local state around `param_3 + 0x2e30`
  - owner registry queries via `owner + 0x2b8`
  - several owner-linked objects around `+0x1148/+0x1150/+0x1158/+0x1160`
- also uses `FUN_01d04b40(...)` during side-record/object checks

Interpretation:
- this is another high-level gameplay/update wrapper above `FUN_00a4b870`
- it still does not initialize the bucket family at `+0xf0..+0x198`

### `FUN_01c5a330`

Confirmed behavior:
- another high-level wrapper that ends with:
  - `FUN_00a4b870(param_1, param_2, param_1 + 0x5638, param_1 + 0x4160, param_1 + 0x5660, param_1 + 0x4188)`
- before that it:
  - builds a transform block from `param_1 + 0x5638/+0x5650`
  - iterates the side-record family at `owner + 0x1c8` / `+0x1d8`
  - updates owner-local state at `param_1 + 0x2e30`
- does not touch bucket headers `owner + 0xf0..+0x198` directly

Interpretation:
- this is a sibling high-level gameplay wrapper above `FUN_00a4b870`
- useful for placing `00a4b870` in the broader runtime stack
- not the missing bucket constructor

### `FUN_01d05000`

Confirmed behavior:
- updates records from the family at:
  - `owner + 0x230`
  - count at `owner + 0x240`
- repeatedly maps those entries onto the side-record family at:
  - `owner + 0x1c8`
  - stride `0x300`
- also consumes a direction/input vector via `param_4`
- called by:
  - `FUN_01d4d7c0`
  - `FUN_00a497b0`
  - `FUN_00a45db0`

Interpretation:
- this is another updater for adjacent side-record families
- it does not initialize or populate the `+0xf0..+0x198` bucket-record family

### `FUN_01d04b40`

Confirmed behavior:
- gate/check helper over one side-record entry at:
  - `owner + 0x1c8 + slot*0x300`
- depends on:
  - `owner + 0x248`
  - `record + 0xd2`
  - `record + 0x288`
- used by:
  - `FUN_00bba640`
  - several gameplay wrappers

Interpretation:
- this is a side-record eligibility helper
- it is not part of bucket initialization

### `FUN_01d16ff0`

Confirmed behavior:
- materializes a transform/output block for one selected runtime object
- consumes:
  - owner object pointer
  - source transform block (`param_2`)
  - selected runtime object (`param_3`)
  - optional part index / sub-transform selector (`param_5`)
- if object-local cached records exist at:
  - `owner + 0xb8`
  - count at `owner + 200`
  it can reuse those
- otherwise it composes transforms from:
  - selected object's local data
  - side-record family at `owner + 0x1c8`
  - source transform block
- called by:
  - `FUN_01d17f90`
  - `FUN_00ae8520`
  - `FUN_00ae8f00`
  - multiple other gameplay/render paths

Interpretation:
- this is a reusable transform materializer for selected runtime objects
- important as proof that owner-side registry/selection paths can emit full transforms without going through the bucket family
- still not the constructor for `record + 0x50`

### `FUN_00ae8d10`

Confirmed behavior:
- picks a preferred runtime object from owner-local registries
- first may query:
  - `FUN_01d5b750(owner + 0x2b8, 0x16)`
- otherwise falls back to:
  - slot/object lists rooted at `owner + 800`
- then cross-checks against the side-record family at:
  - `owner + 0x1c8`

Interpretation:
- this is a registry/selection helper
- it reinforces that `owner + 0x2b8` is a live group-lookup layer
- not a bucket initializer

### `FUN_00ae8520`

Confirmed behavior:
- for mode `0x18`, calls:
  - `FUN_01d5b750(owner + 0x2b8, idx)`
  - `FUN_01d16ff0(owner, unit + 0xcdc, selected_object, ...)`
- then converts the resulting transform into angles/orientation output

Interpretation:
- another direct proof that registry-selected objects can be turned into transforms through `FUN_01d16ff0`
- still separate from the unresolved bucket-record constructor path

### `FUN_00ae1d00`

Confirmed behavior:
- damage/event dispatch logic over many unit ranges
- uses `FUN_01d5b750(owner + 0x2b8, group_id)` to map hit indices onto runtime groups such as:
  - gun breech
  - machine gun
  - coaxial gun
- also checks multiple static/dynamic damage ranges on the unit object

Interpretation:
- this is strong semantic evidence that `owner + 0x2b8` is a named/grouped runtime registry
- useful for interpreting group ids
- but unrelated to bucket construction
