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
- `record + 0x50` is now sharper than before:
  - it is a seat-indexed ushort table, read as `*(ushort *)(*(long *)(record + 0x50) + seat*2)`
  - it is not an owner-local object selector
  - it supplies the part-table row used from `unit + 0xf0[seat]`
- the function now shows a hybrid split inside one record family:
  - object-backed path: resolve `(record + 4, record + 8)` through `owner + 800`, then try `FUN_01d16ff0(...)`
  - part-table path: use `record + 0x50[seat]` to pull a `0x40` row from the unit part-transform table
  - object-backed records can still be forced through the part-table path when the control fields around `record + 0xd8/+0x158` require it
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

### `FUN_01d19930`

Confirmed behavior:
- iterates only two bucket families:
  - `owner + 0xf0`
  - `owner + 0x120`
- for each `0x178` record, reads a per-seat index map from `record + 0x40`
- uses that map to select a destination transform slot from the destination object/table passed in `param_3`
- then copies/composes the transform from the record-local matrix block into the destination transform buffers

Interpretation:
- this is another downstream consumer of the already-built `0x178` records
- `record + 0x40` is a per-seat destination remap table, separate from both:
  - `record + 4/+8` object-list lookup
  - `record + 0x50` semantic part-table selector
- the record layout split is therefore sharper:
  - `+0x40` = destination remap
  - `+0x50` = semantic seat/part selector
  - `+0xa0/+0x158/+0x16c` = generated object-entry payload/control

### `FUN_01c86990`

Confirmed behavior:
- works on a different structure family rooted at `param_1`
- builds a contiguous enabled-range bitset using:
  - `param_1 + 0x670`
  - `param_1 + 0x674`
- writes the resulting generated payload into `param_1 + 0x678` through `FUN_01d60810(...)`

Interpretation:
- useful only as a cross-check for `FUN_01d60810`
- confirms again that `FUN_01d60810` is a generic generated-payload writer, not a bucket-record constructor
- this path is not part of the `0x178` bucket family

### `FUN_01cc0d30`

Confirmed behavior:
- is a runtime position/origin helper for another object family
- when side-record state exists at:
  - `owner + 0x1c8 + idx*0x300`
  it can either:
  - call a virtual transform getter on that side-record object, or
  - call `FUN_01d16ff0(owner, unit + 0xcdc, side_record_object, 1, 0xffffffff, out)`
- otherwise falls back to plain object/world state such as `object + 0xd08`

Interpretation:
- this is another owner-side transform materializer consumer
- it does not touch the `0x178` bucket family or `record + 0x50`

### `FUN_01cc0ff0` and `FUN_01cc1b40`

Confirmed behavior:
- both are higher UI/aiming helpers around `FUN_01cc0d30`
- `FUN_01cc0ff0` creates/updates a helper object and caches the origin returned by `FUN_01cc0d30`
- `FUN_01cc1b40` repeatedly uses `FUN_01cc0d30` to build aim/orientation data, fallback vectors, and UI-facing output blocks

Interpretation:
- these functions sit on the same owner-side UI/selection branch as `FUN_01cc0d30`
- they are not upstream builders of the bucket-record selector table

### `FUN_021ede10`

Confirmed behavior:
- commander-sight/HUD path
- selects a runtime object through `FUN_00ae8d10(...)`
- then calls `FUN_01d16ff0(owner, unit + 0xcdc, selected_object, 1, 0xffffffff, out, 0)`
- uses the resulting transform to drive commander-sight screen-space calculations

Interpretation:
- another direct proof that `FUN_01d16ff0` is widely reused by owner-side view/UI systems
- does not expose the builder for the `0x178` bucket family or for `record + 0x50`

### `FUN_01d4d170`

Confirmed behavior:
- walks `0x178` records, using:
  - `record + 4/+8` for owner-local object lookup
  - `record + 0x98` to choose whether to copy from `record + 0x20` into `record + 0x140`
  - `record + 0x40[seat]` as a per-seat dispatch/remap id
- for each live record, calls:
  - `FUN_01d5f800(record + 0xa0, record + 0x88 + seat*0x30, *(uint *)(record + 0x40 + seat*4), ...)`

Interpretation:
- `record + 0x40` is not just a destination remap table in `FUN_01d19930`
- it is also the downstream dispatch key consumed by `FUN_01d5f800(...)`
- this sharpens the split further:
  - `+0x40` = downstream dispatch/remap ids
  - `+0x50` = semantic part selector
  - `+0xa0` = generated payload root

### `FUN_01c86730`

Confirmed behavior:
- operates on another structure family rooted at `param_1`
- builds a local orientation basis from quaternion-like fields at:
  - `param_1 + 0x198 .. +0x1a8`
- initializes/clears a bitset sized by:
  - `param_1 + 0x670`
  - `param_1 + 0x674`
- then calls:
  - `FUN_01d5f800(param_1 + 0x678, &DAT_09b53cc0, 0xffffffff, &DAT_07f4a0a0, local_basis, 1, bitset)`

Interpretation:
- this is another direct proof that `FUN_01d5f800` is a generic downstream dispatcher used by more than the `0x178` bucket family
- it should not be treated as evidence for the upstream constructor of `record + 0x50`

### `FUN_02186860`

Confirmed behavior:
- validates that the unit object at `param_3 + 0x18` is in the expected live family
- reads the owner pointer directly from:
  - `*(DAT_00001090 + unit)`
- if present, reads a subobject at:
  - `owner + 0x1148`
- derives one output byte from `*(int *)(owner_subobj + 0x30)` and copies another flag from `unit + 0x5181`

Interpretation:
- this is the first direct proof in the notes that the owner object behind `DAT_00001090 + unit` has a meaningful subobject/hub at `+0x1148`
- useful for owner-layout mapping
- still not evidence for the `0x178` bucket-record constructor or writer of `record + 0x50`

### `FUN_021867d0`, `FUN_02186910`, `FUN_021869f0`, and `FUN_02186af0`

Confirmed behavior:
- these neighboring functions all populate small output/status blocks from unit or owner-adjacent runtime state
- examples:
  - `FUN_021867d0` reads unit-side state around `unit + 0xf60` and nested pointers under `param_3 + 0x58`
  - `FUN_02186910` reads flags/timers from `*(param_3 + 0x40) + 0x4fcc/0x5020/0x5048/0x5070`
  - `FUN_021869f0` reads values from `*(param_3 + 0x20) + 0x32f0/0x3318/0x3320/0x3350`
  - `FUN_02186af0` builds another small status block from a separate object returned by `FUN_01822ef0(...)`

Interpretation:
- this `021867xx..02186axx` cluster is a descriptor/status-builder subsystem
- it is useful for owner/unit layout clues only
- it does not look like the constructor or template builder for the `0x178` bucket family

### `FUN_01d19cd0`

Confirmed behavior:
- is a direct pointer-bundle allocator/reset helper rooted at `param_1`
- resizes and clears multiple pointer-like fields together for `param_2` entries:
  - `+0x10` as a `count * 4` array
  - `+0x20` as a `count * 0x30` array
  - `+0x30` as a second `count * 0x30` array
  - `+0x40` as a `count * 4` array
  - `+0x50` as a `count * 2` array initialized to `0xffff`
  - `+0x88` as another `count * 0x30` array
- clears one byte flag at `+0x80`, one byte flag at `+0x98`, then resets downstream state at `+0xa0` via `FUN_01d5ec30(...)`

Interpretation:
- with the corrected call-site interpretation from `FUN_01d3a310`, this helper now aligns with the shallow field bundle of one real `0x178` record
- the earlier mismatch came from reading `FUN_01d1aa30` through the decompiler's `int *` type instead of byte offsets
- this helper should now be treated as the direct resize/reset step for:
  - `record + 0x10/+0x18`
  - `record + 0x20/+0x28`
  - `record + 0x30/+0x38`
  - `record + 0x40/+0x48`
  - `record + 0x50/+0x58`
  - `record + 0x88/+0x90`
- and for resetting the deep payload root at:
  - `record + 0xa0`

### `FUN_01d1aa30`

Confirmed behavior:
- immediately begins by calling `FUN_01d19cd0(param_2, *(int *)(param_1 + 0x284))`
- then fills the newly allocated arrays in `param_2` by iterating seat/entry data from `param_4 + 0xf0` and `param_4 + 0x88`
- key writes after node lookup and part resolution:
  - writes an index array through `*(long *)(param_2 + 0x10)`
  - writes a pointer/handle array through `*(long *)(param_2 + 4)`
  - copies `0x30` transform/template rows into arrays at `+0x20`, `+0x30`, and `+0x88`
  - writes ushort values through `*(long *)(param_2 + 0x14)`
- uses `FUN_03690af0(...)` to resolve node names against the selected part table row

Interpretation:
- major correction:
  - exact call sites inside `FUN_01d3a310` now show:
    - `01d3dc70` -> `FUN_01d1a870`
    - `01d3dc81` -> `FUN_01d2ba20`
    - `01d3dcd3` -> `FUN_01d1aa30`
  - the freshly appended `0x178` record returned by `FUN_01d2ba20` is passed directly into `FUN_01d1aa30`
- so `FUN_01d1aa30` is not a sibling-family writer after all
- it is the direct field-bundle writer for the real `0x178` record family
- the decompiler's `int *param_2` type obscured the true byte offsets
- corrected byte mapping is:
  - `param_2 + 4` -> `record + 0x10`
  - `param_2 + 8` -> `record + 0x20`
  - `param_2 + 0xc` -> `record + 0x30`
  - `param_2 + 0x10` -> `record + 0x40`
  - `param_2 + 0x14` -> `record + 0x50`
  - `param_2 + 0x22` -> `record + 0x88`
  - `param_2 + 0x28` -> `record + 0xa0`
- this finally closes the main unresolved point:
  - `record + 0x40/+0x48` is populated here as the `uint32` remap-table descriptor
  - `record + 0x50/+0x58` is populated here as the `ushort` selector-table descriptor
- the real setup chain is now:
  - `FUN_01d1a870` -> choose typed bucket
  - `FUN_01d2ba20` -> append one `0x178` record
  - `FUN_01d1aa30` -> populate the shallow and deep record bundle

Additional semantic mapping details now confirmed from the same decompilation:
- selector side:
  - `uVar31 = *(ushort *)(plVar36[4] + uVar35 * 2)`
  - so `plVar36[4]` is a node-index -> selector mapping table
  - `uVar35` is the emitter/node index returned from `FUN_03690af0(plVar36, param_5)`
- selector-name side:
  - `__s1 = (char *)((ulong)*(ushort *)(plVar36[8] + (ulong)uVar31 * 2) + plVar36[8])`
  - so `plVar36[8]` is a string-offset table / packed name blob keyed by selector value
  - `record + 0x50` is therefore not just numeric; its values map to concrete part/node names through this selector-name table
- remap side:
  - `FUN_0161ac60(param_4, seat)` returns a seat-specific registry at:
    - `param_4 + 0x578 + seat * 0x20`
    - gated by `param_4 + 0x590`
  - `FUN_01d1aa30` binary-searches the sorted names from that seat registry
  - on success it writes:
    - `*(uint *)(*(long *)(record + 0x40) + seat * 4)` from the registry's ushort->runtime-id mapping table

Interpretation:
- the `0x178` semantic chain is now sharper:
  - emitter/node name -> `FUN_03690af0`
  - node index -> selector value through `plVar36[4]`
  - selector value -> selector name through `plVar36[8]`
  - selector name -> runtime remap id through the seat registry returned by `FUN_0161ac60`
- this means the unresolved work is no longer “where are the tables written”
- it is now “dump or name the selector-name table and the seat registry tables concretely”

Packed selector-name table is now partially grounded by adjacent consumers:
- `plVar36[8]` is not just an opaque blob; selector values are turned back into concrete names by:
  - `name = (char *)((ulong)*(ushort *)(plVar36[8] + selector * 2) + plVar36[8])`
- this is an in-place packed string blob with a `ushort` offset table at the front
- we still do not have a raw blob dump, but we do now have a concrete decode rule for it

### `FUN_0161ac60`

Confirmed behavior:
- if `param_1 + 0x590` is non-zero, returns:
  - `param_1 + 0x578 + seat * 0x20`
- otherwise returns a static empty singleton

Interpretation:
- this is the accessor for the seat-specific name/remap registry used by `FUN_01d1aa30`
- it confirms the remap side is prebuilt seat metadata, not ad hoc lookup against arbitrary live objects

Registry shape is now much sharper with adjacent consumers:
- `FUN_00a67bb0(registry, name)` binary-searches:
  - `*registry` as a sorted pointer array of names
  - `registry + 8` as the element count
- `FUN_0161c3f0` then uses:
  - `*(long *)(registry + 0x10) + idx * 2`
  - as the selector/id array matched to those names

Interpretation:
- the seat registry returned by `FUN_0161ac60` is not opaque anymore
- its front half is at least:
  - `+0x00` = sorted `char **` name table
  - `+0x08` = count
  - `+0x10` = `ushort` selector/id table aligned with the names

### `FUN_01631fa0`

Confirmed behavior:
- is a large seat/damage registry builder operating over the same runtime object family
- uses:
  - `FUN_0161ac60(param_1, 0)`
  - `FUN_0161ac60(param_1, 1)`
- fills and refreshes several selector/name caches under the manager, including:
  - `param_1 + 0x324`
  - `param_1 + 0x32c`
  - `param_1 + 0xbc`
  - `param_1 + 0xc4`
- also rebuilds a per-seat `%s_dm` tuple table at:
  - `param_1 + 0x80`
  - each seat contributes a `0x10`-byte header pointing at `0xc`-byte entries
  - each entry stores:
    - interned `"%s_dm"` name id
    - node index from `FUN_03690af0(...)`
    - selector/id copied from the canonical seat registry
- binary-searches canonical names through `FUN_00a67bb0(...)`
- iterates the seat registry names and selector ids returned by `FUN_0161ac60(...)`
- calls `FUN_0162e140(...)` once per registry entry
- uses both string-interner directions directly:
  - `FUN_014f6b40(id)` to recover canonical names from existing interned ids
  - `FUN_014f6b60(name)` to intern newly built `"%s_dm"` names

Interpretation:
- this is the strongest current builder-side proof for the seat registry path
- even without a raw blob dump, it confirms the sorted name table and aligned `ushort` table are rebuilt and consumed as first-class metadata
- it is now the best upstream target if we later want to dump the seat registry contents from memory
- more importantly, it gives a second extraction surface besides the packed source blob:
  - the builder materializes per-seat `"%s_dm"` tuples explicitly
  - those tuples already bridge canonical seat-registry names to interned runtime ids and node indices
- practical extraction path is now:
  - canonical name id -> `FUN_014f6b40(...)`
  - per-seat `"%s_dm"` tuple at `manager + 0x80`
  - selector/id from the aligned seat registry table

Direct wrapper/build proof is now available too:
- `FUN_01bdf8d0` calls:
  - `FUN_0163db10(0, *(param_1 + 0x41a), param_1, DamageParts, DamageEffects, MetaParts, 0, 0, 1, 0)`
  - immediately followed by:
  - `FUN_01631fa0(*(param_1 + 0x41a), param_1, param_2, 0, 0)`
- so `*(param_1 + 0x41a)` is the manager object that owns the seat/damage registries consumed by `FUN_01631fa0`
- this places the registry build step directly in the runtime build chain, not in a detached maintenance path

### `FUN_01617550`

Confirmed behavior:
- is the constructor / shape-initializer for the manager object later passed as `*(param_1 + 0x41a)`
- caller set matches the same build family:
  - `FUN_01bdf8d0`
  - `FUN_00a8cb60`
  - `FUN_017429f0`
  - `FUN_01767130`
- initializes and zeros multiple dynamic families, including the region around:
  - `+0x568`
  - `+0x578`
  - `+0x580`
  - `+0x590`
  - `+0x638`
  - `+0x658`
- explicitly leaves `+0x590` cleared during construction
- also allocates/reset-shapes several adjacent arrays with element counts derived from `*(uint *)(manager + 0x4c)`

Interpretation:
- this is the manager constructor we were missing
- but it is only a shape/ownership initializer, not the place where canonical registry names are seeded
- important consequence:
  - `+0x578/+0x590` are manager-owned fields from the start
  - concrete name/selector contents are still populated later by the build phase, strongest at `FUN_01631fa0`

### `FUN_014f6b40` / `FUN_014f6b60`

Confirmed behavior:
- `FUN_014f6b40(id)` is a thin wrapper over `FUN_05439b20(&DAT_099102c0, id)`
- `FUN_014f6b60(name)` is a thin wrapper over `FUN_05439b80(&DAT_099102c0, name)`
- `FUN_05439b20(...)` resolves intern-registry ids back into string pointers
- `FUN_05439b80(...)` hashes / looks up / inserts strings into the same runtime registry

Interpretation:
- `DAT_099102c0` is the global canonical string interner used by this runtime family
- the seat-registry build path is not trapped inside opaque local blobs anymore:
  - interned ids are reversible through `FUN_014f6b40(...)`
  - new canonical names are inserted through `FUN_014f6b60(...)`
- together with `FUN_01631fa0`, this means canonical runtime names can be recovered from either:
  - the upstream packed source blob
  - or the already-interned ids stored in manager-owned tuple tables

Related interner helpers now confirmed:
- `FUN_014f6990()` is a thin wrapper over:
  - `FUN_05439b10(&DAT_099102c0)`
- `FUN_014f7710()` lazily interns and caches:
  - `"body_dm"`
- `FUN_0352be70(...)` is the hashed string lookup helper used under `FUN_05439b80(...)`

Interpretation:
- the interner path is now structurally closed:
  - init / count through `FUN_014f6990`
  - id -> name through `FUN_014f6b40`
  - name -> id through `FUN_014f6b60`
  - concrete example id for `"body_dm"` through `FUN_014f7710`

### `FUN_014f6630`

Confirmed behavior:
- performs one-time initialization of the global interner backing store at:
  - `DAT_099102c0`
- zeros the whole registry state
- seeds auxiliary pointers / metadata around:
  - `DAT_099102c8`
  - `DAT_09910308`
  - `DAT_09910318`
  - `DAT_09910358`
  - `DAT_09910360`
- then calls:
  - `FUN_05439670(&DAT_099102c0, ...)`

Interpretation:
- this is the real runtime initializer for the canonical name interner
- it confirms the zeroed data seen in the binary image is expected startup state, not missing evidence
- practical consequence:
  - any concrete name dump must come from runtime-filled tables or from loader/build code, not from static .data contents alone

### `FUN_014f72e0`

Confirmed behavior:
- is a loader helper that reads string params from blk/config and resolves them into interned part ids
- for each string value:
  - tries `FUN_054082c0(...)` first
  - falls back to `FUN_05439b80(&DAT_099102c0, name)` if needed
- appends the resulting short ids into a caller-owned dynamic array

Interpretation:
- this is direct proof that runtime part ids are created from text names in blk/config paths
- it strengthens the extraction story:
  - interner ids are not opaque random numbers
  - they are generated from concrete part strings during load/build phases

### `FUN_01611dc0`

Confirmed behavior:
- is called only from `FUN_01631fa0`
- receives:
  - `param_1 = **(long **)(manager + 0x78)`
  - `param_2 = &manager`
- iterates a source metadata object with:
  - `*(int *)(source + 8)` = entry count
  - `*(long *)(source + 0x40)` = packed name blob / offset table base
- decodes each source name as:
  - `name = (char *)(*(long *)(source + 0x40) + *(ushort *)(*(long *)(source + 0x40) + idx * 2))`
- appends per-entry mapping records into manager-owned arrays
- resolves node indices via `FUN_03690a50(object + 0x230, name)`
- also retries with a `"_dm"`-style suffixed variant when direct lookup fails

Interpretation:
- this is the strongest source-format proof so far
- the sorted seat-registry names used later by `FUN_01631fa0` are derived from an upstream packed-name blob at `source + 0x40`
- because `manager + 0x78` is byte-scaled from the `undefined2 *` decompiler type, this is actually:
  - `manager + 0xf0`
- `FUN_01631fa0` later also iterates:
  - `*(long *)(*(long *)(manager + 0xf0) + seat * 8)`
- so the upstream packed-name blob belongs to the per-seat source-object array rooted at `manager + 0xf0`
- this means the unresolved work is no longer about unknown source layout:
  - the raw source name format is now known
  - what remains is dumping actual contents from that blob

### `FUN_0163db10`

Confirmed behavior:
- is the heavy upstream metadata builder that runs immediately before `FUN_01631fa0`
- uses `FUN_014f6b60(...)` on damage-part names resolved from `damageModelParts.blk`
- grows a local table at:
  - `*(manager + 0x350) + 0x148`
  - with packed `6`-byte entries
- seeds each entry with:
  - a local slot/index
  - the corresponding interned damage-part name id

Interpretation:
- this is the broader metadata phase that seeds the same global interner before seat-registry rebuild
- together with `FUN_01631fa0`, it shows two complementary name surfaces:
  - damage-model part ids interned from `damageModelParts.blk`
  - per-seat canonical / `"%s_dm"` tuples derived from the packed source blob
- this matters for extraction because the runtime already preserves names as interned ids in manager-owned arrays instead of relying only on one-shot packed blobs

### `FUN_03690a50`

Confirmed behavior:
- takes `(source, name)`
- scans the same packed-name blob layout used by `FUN_01611dc0`
- uses:
  - `*(long *)(source + 0x40)` as packed string base
  - `*(long *)(source + 8)` as count
- compares each decoded entry with `strcmp(...)`
- returns the matched index or `0xffffffffffffffff`

Interpretation:
- this independently confirms the packed-name layout at `source + 0x40`
- the upstream canonical-name source for registry building is now structurally resolved:
  - count at `+8`
  - packed string/offset blob at `+0x40`
- and it confirms that both:
  - `FUN_01611dc0`
  - `FUN_03690af0`
  consume the same per-seat source-object name blob family

### `FUN_0161ad00`

Confirmed behavior:
- consumes the seat-specific registry returned by `FUN_0161ac60(param_1, seat)`
- ensures an output `uint32` array at `param_1 + 0x630` sized to the registry count at `registry + 8`
- for each registry entry:
  - reads a `ushort` selector/id from `*(long *)(registry + 0x10) + idx * 2`
  - looks up a runtime remap id from the live seat object at `*(param_1 + 0x88)[seat]`
  - falls back to `FUN_015ea6c0(...)` when the selector exceeds the live table bounds
- writes the resolved dword ids into `param_1 + 0x630`

Interpretation:
- this is the explicit builder for the runtime remap-id table that `FUN_01d1aa30` later consumes through the seat registry path
- combined with `FUN_01d1aa30`, the semantic mapping now looks like:
  - selector value -> selector name (`plVar36[8]`)
  - selector name -> registry slot (`FUN_0161ac60`)
  - registry slot / selector id -> runtime remap dword (`FUN_0161ad00`)

### `FUN_0162e140`

Confirmed behavior:
- takes one registry name and one selector/id and emits a packed `0x18` descriptor into:
  - `*(long *)(manager + 0x658) + idx * 0x18`
- classifies several canonical names directly:
  - `"emtr_"`
  - `"track"`
  - `"gun_barrel"`
  - `"hatch"`
  - `"antenna"`
- resolves:
  - node index through `FUN_03690af0(*(*(long *)(manager) + 0xf0), name)`
  - damage selector by searching `"%s_dmg"`
  - destroy selector by searching `"%s_dstr"`
- stores those selectors into the descriptor alongside packed orientation/flag data

Interpretation:
- this gives the first direct semantic bridge from registry names to runtime damage selectors
- `gun_barrel` is now concretely present in the builder path, and its derived names:
  - `gun_barrel_dmg`
  - `gun_barrel_dstr`
  are generated explicitly at runtime
- the same canonical registry family also includes:
  - `emtr_`
  - `track`
  - `hatch`
  - `antenna`
- this strongly matches local `Toy` names such as:
  - `bone_gun_barrel`
  - `gun_barrel_dm`
  - `gunner_dm`
- practical reading:
  - seat-registry names appear to be canonical gameplay names like `gun_barrel`
  - tankmodel / damage-model files then expose nearby node and damage names such as `bone_gun_barrel` and `gun_barrel_dm`
  - `track` likely bridges toward tankmodel damage names like `track_l_dm` / `track_r_dm`
  - `emtr_` likely bridges toward effect/emitter names like `emtr_gun_flame`, `emtr_fire_dmg`, and related tankmodel emitters

### `FUN_01637a40`

Confirmed behavior:
- is a live event / damage consumer over the same manager family
- consumes descriptor entries from:
  - `*(long *)(manager + 0x658) + idx * 0x18`
- for each descriptor, uses:
  - selector/id at `+0x06`
  - runtime remap / destination-like fields at `+0x02`, `+0x0a`, `+0x0c`
- calls:
  - `FUN_016278d0(...)`
  - `FUN_016288b0(...)`
  - and updates live arrays under:
    - `manager + 0x1c8`
    - `manager + 0x208`

Interpretation:
- this is the first strong downstream consumer tying the `FUN_0162e140` canonical-name descriptors into live runtime event handling
- practical consequence:
  - the path from canonical name -> descriptor -> live damage/runtime reaction is now concrete
  - but it still consumes the `+0x658` descriptor family, not the per-seat `"%s_dm"` tuples at `manager + 0x80`
- so `manager + 0x80` remains a promising extraction surface, while `manager + 0x658` is the clearer live-consumer surface

Additional downstream consumers now confirmed:
- `FUN_016297e0(...)`
  - iterates canonical registry names through `FUN_0161ac60(param_1, 1)`
  - resolves them against the packed source blob with `FUN_03690a50(...)`
  - writes live transforms into the seat object at `*(long *)(*(long *)(param_1 + 0x88) + 0x10)`
  - also iterates `manager + 0x658` and dispatches through `FUN_016278d0(...)`
- `FUN_0162a640(...)`
  - takes a `ushort` index list
  - resolves each index into `*(long *)(manager + 0x658) + idx * 0x18`
  - uses descriptor fields at `+0x02`, `+0x04`, and `+0x0a`
  - then calls `FUN_016278d0(...)`

Interpretation:
- `manager + 0x658` is now firmly established as the canonical live-consumer descriptor family for this path
- multiple runtime consumers use it directly:
  - `FUN_01637a40`
  - `FUN_016297e0`
  - `FUN_0162a640`
- this strengthens the split:
  - `manager + 0x80` = better extraction surface for per-seat `"%s_dm"` tuples
  - `manager + 0x658` = better live runtime behavior surface

### `FUN_01637770`

Confirmed behavior:
- is a recursive hash-table insert / growth helper
- used from `FUN_01637a40`
- operates on `0x18`-byte hash buckets holding:
  - an 8-byte key
  - a `ushort` payload field at `+0x10`
- calls:
  - `FUN_01637270`
  - `FUN_01637510`

Interpretation:
- this is not a tuple/name enumerator for `manager + 0x80`
- it is local hash infrastructure used by the live event path around `manager + 0x438`
- so it does not provide a shortcut to dump canonical names; it only stores opaque 8-byte keys and small payloads

### `FUN_00a74680`

Confirmed behavior:
- is a high-value ground/runtime consumer that reads interned names back through `FUN_014f6b40(...)`
- for queued pending entries under:
  - `param_1[0x42c]`
  - count `param_1[0x42e]`
- does:
  - `name = FUN_014f6b40(interned_id)`
  - `FUN_0161c3f0(manager, name, 1, 0)`
  - then resolves the matching triple from:
    - `*(manager + 0x350) + 0x148`
    - using the same packed `6`-byte records seeded by `FUN_0163db10`
  - and sends that triple into `FUN_0161c7b0(...)`

Interpretation:
- this is the strongest current proof that the runtime can round-trip:
  - interned id -> canonical name -> selector triple -> live application
- it also means extraction no longer depends on finding a direct consumer of `manager + 0x80`
- any surface that yields interned ids is already enough, because `FUN_014f6b40(...)` plus the `+0x350/+0x148` table closes the loop

### `FUN_016fea00`

Confirmed behavior:
- is another runtime consumer that repeatedly does:
  - `name = FUN_014f6b40(interned_id)`
  - `FUN_0161c3f0(manager, name, 1, 0)`
  - then fetches the packed triple from:
    - `*(manager + 0x350) + 0x148`
  - and applies it via `FUN_0161c7b0(...)`
- also walks ranges from `param_1 + 0x4270`, suggesting grouped preset/runtime mappings rather than ad hoc single events

Interpretation:
- this independently confirms the same round-trip path seen in `FUN_00a74680`
- together they prove the reversible extraction surface is already present in live runtime code:
  - interned id
  - `FUN_014f6b40(...)`
  - `FUN_0161c3f0(...)`
  - packed selector triple from `*(manager + 0x350) + 0x148`

### `FUN_0161c7b0`

Confirmed behavior:
- takes one packed selector triple and applies it across one or two seat/group ranges
- consumes:
  - `*(long *)(manager + 0x118)` as per-group rule tables
  - `*(long *)(manager + 0x88)` as live seat objects
  - `manager + 0x130` as an optional downstream callback target
- the input triple layout is now partly concrete:
  - `word0` / `+0x00` is the live descriptor key consumed by `FUN_01620030(...)`
  - `word1` / `+0x02` is the selector/group key consumed directly by `FUN_0161c7b0(...)`
  - `word2` / `+0x04` is still unresolved from this function alone
- on the write path it sets live entries to `1.0f` and calls `FUN_015ea5d0(...)`
- on the clear path it zeros matching live entries and may also call `FUN_015ea5d0(...)`
- `FUN_0161c7b0(...)` never reads `word0` directly:
  - it starts from `*(short *)(triple + 2)` and uses that value to search rule entries in `manager + 0x118`
  - matching rule entries then provide `(start,count)` ranges into the backing `uint` list at `rule_desc + 0x20`
- this makes `word1` the strongest current candidate for the canonical selector/group id in the packed triple family

Interpretation:
- this is the central packed-triple applier behind several higher-level runtime paths
- it confirms the `*(manager + 0x350) + 0x148` table is not just metadata storage:
  - its `6`-byte entries are immediately usable control triples for live runtime state

Additional triple-driven callers now confirmed:
- `FUN_016f45f0(...)`
  - resolves `param_3` or falls back to `FUN_014f7710()` for `"body_dm"`
  - fetches the `6`-byte triple from `*(manager + 0x350) + 0x148`
  - then does:
    - `FUN_014f6b40(id)`
    - `FUN_0161c3f0(...)`
    - `FUN_0161c7b0(...)`
- `FUN_00a69d70(...)`
  - same pattern for another gameplay/runtime path
  - fetches the triple from `*(manager + 0x350) + 0x148`
  - applies it through `FUN_0161c7b0(...)`
- `FUN_016cf230(...)`
  - iterates grouped part-id ranges from `param_2`
  - repeatedly resolves ids through `FUN_014f6b40(...)`
  - fetches triples from `*(manager + 0x350) + 0x148`
  - applies them with `FUN_0161c7b0(...)`

Interpretation:
- the `6`-byte table at `*(manager + 0x350) + 0x148` is now the clearest bulk extraction surface
- unlike `manager + 0x80`, it already sits at the exact intersection of:
  - interned ids
  - canonical names
  - packed live-application triples
- if we can enumerate the ids used by these callers, we can reconstruct concrete name -> triple mappings directly

### `FUN_05409550`

Confirmed behavior:
- is a thin indexed accessor over the packed `6`-byte triple table
- reads:
  - `*(uint6 *)(*param_1 + idx * 6)`
- uses:
  - `param_1 + 0x08` / `*(uint *)(param_1 + 1)` as the element count
- returns:
  - the packed `6`-byte triple
  - or `0xffffffffffff` when out of bounds

Interpretation:
- this closes the table shape at `*(manager + 0x350) + 0x148`
- it is not an ad hoc blob:
  - it is explicitly modeled as an array of `uint6` records

### `FUN_054095b0`

Confirmed behavior:
- is a large builder for the same packed-triple family
- takes a source name, hashes/looks it up, and either reuses or inserts the corresponding interned id
- appends that `ushort` id into one compact id list
- appends a default `0x130`-byte rule record into a second table
- appends a default `0x14`-byte metadata record into a third table
- returns a pair whose low half is the interned `ushort` id and whose high half is the metadata-record index

Interpretation:
- this is the strongest current constructor-side proof for the packed-triple ecosystem around:
  - `+0x148` = `6`-byte id/triple table
  - adjacent `0x130` rule records
  - adjacent `0x14` metadata records
- together with `FUN_05409550`, this means the `*(manager + 0x350)` subobject is now understood as a real managed container family, not just a passive lookup table

Additional build/query users now confirmed:
- `FUN_015e1470(...)`
  - loads `DamageParts` from blk/config
  - calls `FUN_054095b0(...)`
  - stores the returned packed result into:
    - `param_1 + 0xec/+0xee/+0xf0`
  - then allocates and appends a new `0xa8`-stride attachable-side rule record under:
    - `*(manager + 0x350) + 0x170`
- `FUN_0161caf0(...)`
  - is a query/volume helper over a linked list at `*(param_1 + 0x50) + 0x60`
  - uses:
    - `FUN_05409550(param_1 + 0x408, idx)`
  - to resolve a packed selector from the `6`-byte table during runtime checks

Interpretation:
- the same container family is now proven to participate in both:
  - build-time / attachable construction (`FUN_015e1470`)
  - runtime query logic (`FUN_0161caf0`)
- this further supports using the `+0x148` / adjacent tables as the best bulk extraction target

More runtime-query users now confirmed:
- `FUN_0162a550(...)`
  - calls `FUN_05409550(param_1 + 0x408, idx)`
  - then uses the resolved selector to gate bitset state under `param_1 + 0x2a8`
- `FUN_0162ac60(...)`
  - performs trace / collision-style runtime checks
  - calls `FUN_05409550(param_2 + 0x408, *(uint *)(hit + 0x1c))`
  - uses the resolved selector against live seat state and damageable visual-model logic
- `FUN_016fecf0(...)`
  - uses `FUN_05409550(*(runtime + 0x1068) + 0x408, hit_idx)` to resolve a packed triple
  - then forwards the resulting selector triple into `FUN_016fea00(...)`
- `FUN_0169d060(...)`
  - is the strongest bulk-enumerator found so far for the same ecosystem
  - walks multiple mapping layers under `param_1`
  - resolves packed triples via:
    - `FUN_05409550(runtime + 0x408, idx)`
  - extracts the middle `short` from each resolved `uint6` triple
  - appends those values into a caller-owned dynamic `int` array
  - so this is not a one-off query:
    - it bulk-collects live selector/group ids from the `+0x408` table
- `FUN_016fd070(...)`
  - is a high-level hit / trace / collision path that repeatedly resolves packed triples from the same `+0x408` table
  - during the live-part loop it uses:
    - `FUN_05409550(*(runtime + 0x1068) + 0x408, part_desc[0x5e])`
  - then forwards the extracted middle selector into `FUN_016c1cf0(...)`
  - later it also resolves the incoming `param_2[0]` id through the same triple table before calling `FUN_01620030(...)`

### `FUN_01620030`

Confirmed behavior:
- takes a packed triple pointer but only consumes:
  - `*(short *)(triple + 0x00)`
- validates that first `short` against:
  - `manager + 0x3e0`
  - indirection table `manager + 0x368`
  - final live-object table `manager + 0x548`
- returns the live object pointer at:
  - `*(manager + 0x548) + mapped_idx * 0x40`

Interpretation:
- this makes `word0` of the packed triple the best current candidate for:
  - live damageable-part descriptor id
  - or canonical visual/damage node key that resolves to a `0x40`-stride live object entry
- together with `FUN_0161c7b0(...)` and `FUN_0169d060(...)`, the packed triple now splits cleanly into:
  - `word0` = live-object lookup id
  - `word1` = selector/group id
  - `word2` = still unresolved tail field

### `FUN_0162a550`

Confirmed behavior:
- resolves a packed triple through:
  - `FUN_05409550(param_1 + 0x408, idx)`
- then consumes only the low `short` of that triple
- if the resolved low `short` is valid, it reads:
  - `*(byte *)(*(long *)(param_1 + 0x3d8) + (long)word0 * 0x14 + 2)`
- bit `0x4` in that `0x14`-stride metadata record gates whether a bitset at `param_1 + 0x2a8` is consulted

Interpretation:
- this is a second independent confirmation that `word0` is not just an opaque id:
  - it indexes descriptor metadata at `+0x3d8`
  - and also resolves through `FUN_01620030(...)` into live `0x40`-stride objects
- so `word0` is now best read as the canonical live damageable-descriptor id in this triple family

### `FUN_0162b6e0`

Confirmed behavior:
- resolves a packed triple through:
  - `FUN_05409550(param_1 + 0x408, idx)`
- then consumes only the low `short` of that triple
- if the resolved `word0` is valid, it checks bit `0x2` in:
  - `*(byte *)(*(long *)(param_1 + 0x3d8) + (long)word0 * 0x14 + 2)`
- if that bit is set, it also consults a nibble-packed state table at:
  - `param_1 + 0x5e8/+0x5f0`

Interpretation:
- together with `FUN_0162a550(...)`, this makes the `+0x3d8` `0x14`-stride metadata family tightly bound to `triple.word0`
- so `word0` is now confirmed to participate in:
  - live object lookup
  - descriptor metadata lookup
  - runtime gating / state suppression checks

### `FUN_0161caf0`

Confirmed behavior:
- walks a linked list under:
  - `*(long *)(*(long *)(param_1 + 0x50) + 0x60)`
- for each node it resolves a packed triple through:
  - `FUN_05409550(param_1 + 0x408, *(ushort *)(node + 0xbc))`
- then compares only the low `short` of that triple against `*param_2`
- on match, it computes and returns volume / bounds data from that same node

Interpretation:
- this is another independent consumer where only `word0` matters
- so the packed triple's low word is also the lookup key into the volume/query path, not just the live-object path

Current refinement:
- across `FUN_01620030`, `FUN_0162a550`, `FUN_0162b6e0`, and `FUN_0161caf0`:
  - `word0` is consistently the canonical descriptor id
- across `FUN_0161c7b0`, `FUN_0169d060`, and `FUN_016fd070`:
  - `word1` is consistently the selector/group id
- `word2` still has no direct consumer in the strongest currently analyzed runtime paths

### `FUN_00a9a770`

Confirmed behavior:
- resolves an interned id through the packed triple table at:
  - `*(runtime + 0x350) + 0x148`
- materializes the full 6-byte triple twice into a local stack buffer
- first sends that stack triple into:
  - `FUN_0162a0c0(runtime, &triple)`
- then sends the same stack triple into:
  - `FUN_0161c7b0(runtime, &triple, enable, !enable)`

Interpretation:
- this is a useful bridge because it proves there is at least one runtime path that carries the full packed triple as a local object, not just extracted `word0` or `word1`
- however, the first helper it feeds still only consumes `word0`

### `FUN_0162a0c0`

Confirmed behavior:
- consumes only:
  - `*param_2` / `triple.word0`
- checks:
  - `*(short *)(*(long *)(runtime + 0x648) + word0 * 2) != -1`
- and then calls:
  - `FUN_016288b0()`

Interpretation:
- this is yet another independent `word0` consumer
- it ties `word0` to an additional remap/lookup table at `runtime + 0x648`
- but still does not reveal a direct use of `word2`

### `FUN_00a69d70`

Confirmed behavior:
- resolves an interned id into a full packed triple from:
  - `*(runtime + 0x350) + 0x148`
- carries the full `6`-byte triple in locals:
  - `local_2e/local_2c/local_2a`
- then passes that full triple into:
  - `FUN_01620b50(runtime, &triple, short_timer, 0)`
  - `FUN_0162a0c0(runtime, &triple, 0)`
  - `FUN_0161c7b0(runtime, &triple, 0, 1)`
  - `FUN_01d213f0(param_1, param_2[0x212], &triple)`
- the caller itself only directly inspects descriptor metadata via `+0x3d8`, not `word2`

Interpretation:
- this is another bridge path showing the full packed triple is preserved across several downstream helpers
- but it still does not provide a direct caller-side consumer for `word2`
- it does narrow the next target:
  - if `word2` matters, `FUN_01620b50(...)` or `FUN_01d213f0(...)` are now stronger candidates than this caller

### `FUN_016f45f0`

Confirmed behavior:
- resolves an interned id into a full packed triple from:
  - `*(runtime + 0x350) + 0x148`
- carries that full triple in locals:
  - `local_2e/local_2c/local_2a`
- then passes it into:
  - `FUN_01620b50(runtime, &triple, timer, 0)`
  - `FUN_01620300(runtime, &triple)`
  - `FUN_0161c7b0(runtime, &triple, 0, 1)` and `FUN_0161c7b0(runtime, &triple, 2, 3)`
  - `FUN_01d213f0(param_1, *(DAT_00001090 + unit), &triple)`
- the caller also does:
  - `FUN_014f6b40(id)`
  - `FUN_0161c3f0(...)`
  before the `FUN_0161c7b0(...)` writes

Interpretation:
- like `FUN_00a69d70(...)`, this is a strong full-triple bridge path
- but it still never reads `word2` directly at caller level
- current best hypothesis is now stronger:
  - if `word2` has semantic meaning, it is most likely consumed in downstream helpers such as `FUN_01620b50(...)`, `FUN_01620300(...)`, or `FUN_01d213f0(...)`

### `FUN_01620b50`

Confirmed behavior:
- consumes only:
  - `*param_2` / `triple.word0`
- compares that `word0` against the first `short` field of the `0x14`-stride metadata record at:
  - `*(long *)(runtime + 0x3d8) + word0 * 0x14`
- if the current short differs from `param_3`, it forwards to:
  - `FUN_01620450(runtime, triple, param_3)`
  - and sets `*(byte *)(runtime + 0x6b8) = 1`

Interpretation:
- this is another pure `word0` consumer
- so one more of the strongest downstream helpers still ignores `word2`

### `FUN_01620300`

Confirmed behavior:
- consumes only:
  - `*param_2` / `triple.word0`
- uses that low `short` to read a nibble-packed state value from:
  - `runtime + 0x5e8/+0x5f0`

Interpretation:
- this reinforces the current split:
  - `word0` drives descriptor-state lookup
  - `word1` drives selector/group behavior
- no evidence here for `word2`

### `FUN_01d213f0`

Confirmed behavior:
- consumes:
  - `*param_3` / `triple.word0`
  - `param_3[1]` / `triple.word1`
- it uses `word0` to clear matching `short` lists embedded in the `0x300`-stride side-record family at:
  - `+0x1ec/+0x1f0`
  - `+0x22c/+0x230`
  - `+0x24c/+0x250`
- it then uses `word1` directly in the downstream object loop:
  - compares `*(int *)(obj + 0x1fc)` and `*(int *)(obj + 0x23c)` against `(int)param_3[1]`
- there is still no direct read of:
  - `param_3[2]` / `triple.word2`

Interpretation:
- this is the strongest downstream confirmation so far that the packed triple's meaningful live payload is concentrated in:
  - `word0` = descriptor id
  - `word1` = selector/group id
- `word2` remains unused even in one of the main helpers that receives the full triple from both `FUN_00a69d70(...)` and `FUN_016f45f0(...)`

### builder-side refinement from `FUN_054095b0`

Confirmed behavior:
- `FUN_054095b0(...)` still does not write the packed `6`-byte triple table directly
- but it very clearly builds the adjacent container families that feed the same ecosystem:
  - appends a compact `ushort` id into the id list at `param_2`
  - appends a default `0x130` rule record into the table at `param_2 + 0x10`
  - appends a default `0x14` metadata record into the table at `param_3`
- the appended `0x14` metadata record is initialized with:
  - first `ushort` = interned id returned by the name lookup/insert
  - second `short` = metadata-record index
  - remaining fields seeded to defaults like `0x000a`, `0xffff`, and `-1.0f`
- the function returns:
  - low `ushort` = interned id
  - high `ushort` = metadata-record index

Interpretation:
- this further tightens the builder-side link between:
  - canonical interned ids
  - the `0x14` descriptor metadata family
  - the broader packed-triple / rule-record ecosystem
- but it still does not reveal the first direct seed of `triple.word2`
- after this pass, the best remaining upstream candidate for `word2` seeding is no longer `FUN_054095b0(...)` itself, but the larger manager builder:
  - `FUN_0163db10(...)`

### `FUN_0163db10`

Confirmed behavior:
- is the first direct builder now identified for the packed `6`-byte triple table at:
  - `*(manager + 0x350) + 0x148`
- it resizes that table to match the current descriptor count and initializes new entries to `0xffff`
- it also rebuilds the adjacent `0x14` metadata family at:
  - `manager + 0x3d8`
- for each descriptor index `idx`, it seeds metadata as:
  - `*(short *)(meta + 0x04) = idx`
  - `*(short *)(meta + 0x08) = *(short *)(manager + 0x358 + idx * 2)`
  - `*(short *)(meta + 0x06) = FUN_014f6b60(name_from_damageModelParts_blk)`
- once that interned part-id is valid, it writes the triple entry directly:
  - `*(uint32 *)(triple + 0x00) = *(uint32 *)(meta + 0x04)`
  - `*(ushort *)(triple + 0x04) = *(ushort *)(meta + 0x08)`
- in `ushort` terms this means:
  - `triple.word0 = *(short *)(meta + 0x04) = descriptor index`
  - `triple.word1 = *(short *)(meta + 0x06) = interned damage-part id`
  - `triple.word2 = *(short *)(meta + 0x08) = upstream selector/remap id from manager + 0x358`

Interpretation:
- this is the first concrete seed-site for all three packed-triple words
- it forces a refinement of the earlier semantics:
  - `word0` is not just a generic live-object lookup id; it is the descriptor index that later drives live-object lookup, metadata lookup, and gating
  - `word1` is the interned damage-part id produced from `damageModelParts.blk` names
  - `word2` is not spare in the builder at all; it is the upstream selector/remap id copied from the compact `ushort` table at `manager + 0x358`
- downstream runtime consumers still mostly use:
  - `word0` for descriptor/object/metadata lookups
  - `word1` for part-id / group-style behavior
- but the builder proves `word2` is a real seeded field, even if few hot consumers have used it in the paths checked so far

### `FUN_01631fa0` refinement for `manager + 0x358`

Confirmed behavior:
- `FUN_01631fa0(...)` is the upstream builder that prepares the compact selector tables consumed later by `FUN_0163db10(...)`
- it allocates and clears a temporary `ushort` table at:
  - `manager + 0x324`
- then, for each active descriptor record in `manager + 0x1ec`:
  - reads the interned canonical name id from `*(short *)(record + 0x06)`
  - resolves that id back to a string through `FUN_014f6b40(...)`
  - binary-searches the seat registry with `FUN_00a67bb0(...)`
  - stores the resulting seat-registry selector into:
    - `*(ushort *)(*(long *)(manager + 0x324) + descriptor_index * 2)`
- later in the same function it materializes per-seat `%s_dm` tuple tables at `manager + 0x80`
  - tuple field `+0x04` is copied from the seat-registry selector array

Interpretation:
- this narrows `manager + 0x358` from a vague compact `ushort` array to a selector/remap table in the same semantic family as the temporary builder table at `manager + 0x324`
- together with `FUN_0163db10(...)`, the current best chain is:
  - canonical name/id -> seat-registry selector via `FUN_01631fa0`
  - compact selector table near `manager + 0x358`
  - `meta + 0x08`
  - `triple.word2`
- so `word2` is best read as the seat-registry-derived selector/remap id, not a generic spare field

### `FUN_01521a70` / `FUN_015ea070`

Confirmed behavior:
- these helpers are broad container builders/resizers for the adjacent setup families used by `FUN_0163db10(...)`
- they resize:
  - compact `ushort` arrays
  - `0x130` descriptor records
  - another `ushort` array
  - `uint32` tables
  - `0x14` metadata records
- but they do not themselves reveal new semantics for `word2`

Interpretation:
- they support the same build chain structurally
- but the semantic source of `word2` is better explained by `FUN_01631fa0(...)` plus the direct write in `FUN_0163db10(...)`

### explicit canonical -> Toy examples from local data

Confirmed local examples:
- `config/damagemodelparts.blkx` exposes canonical damage-part classes such as:
  - `body`
  - `gun_barrel`
  - `cannon_breech`
  - `track`
  - `gunner`
  - `optic`
  - `optic_gun`
- `config/damagemodel.blkx` and tankmodel files then expose nearby DM/node names in a different namespace layer:
  - `gun_barrel_dm`
  - `optic_gun_dm`
  - `gunner_dm`
  - `bone_gun_barrel`
  - `bone_gun`
  - `bone_turret`
- concrete example from `fr_amx_30_1972.blkx`:
  - weapon emitter = `bone_gun_barrel`
  - `barrelDP = "gun_barrel_dm"`
  - turret nodes:
    - `head = "bone_turret"`
    - `gun = "bone_gun"`
    - `barrel = "bone_gun_barrel"`
  - crew binding:
    - `gunnerDm = "gunner_dm"`

Interpretation:
- current best explicit mapping examples are:
  - canonical `gun_barrel`
    - -> DM part `gun_barrel_dm`
    - -> visual node `bone_gun_barrel`
  - canonical `gunner`
    - -> DM part `gunner_dm`
  - canonical `optic_gun`
    - -> DM part `optic_gun_dm`
  - canonical `track`
    - -> DM parts `track_l_dm` / `track_r_dm`
- so `word1` should be read as an interned canonical damage-part id, while `Toy` often exposes a neighboring but not identical DM/node name

Working matrix from local tank examples (`ussr_bt_7_1937`, `fr_amx_30_1972`):

| canonical / `word1` family | DM / repair name layer | tankmodel binding layer |
| --- | --- | --- |
| `body` | `body_dm` | hull/body aggregate, unit-level body bindings |
| `gun_barrel` | `gun_barrel_dm` | `barrelDP = "gun_barrel_dm"`, `emitter = "bone_gun_barrel"`, turret `barrel = "bone_gun_barrel"` |
| `cannon_breech` | `cannon_breech_dm` | `breechDP = "cannon_breech_dm"` |
| `gunner` | `gunner_dm` | crew `dmPart = "gunner_dm"`, weapon/turret `gunnerDm = "gunner_dm"` |
| `optic_gun` | `optic_gun_dm` | optic damage-part blocks under tankmodel / damage model |
| `track` | `track_l_dm`, `track_r_dm` | left/right track node sets and repair groups |

Interpretation:
- this matrix matches the reverse-engineered namespace split:
  - `word1` = canonical damage-part class/id
  - DM layer = `*_dm` / repair / hit part names
  - tankmodel layer = bone/node and weapon binding names
- so the practical mapping task is no longer “what kind of field is `word1`?”:
  - it is now “which canonical class expands to which DM/node variants for the current vehicle?”
- strongest explicit current one-to-one mappings:
  - `gun_barrel`
    - has direct runtime string proof as `"gun_barrel"`
    - canonical class in `damageModelParts.blk`
    - DM layer in `damagemodel.blk`: `gun_barrel_dm`, `gun_barrel_01_dm`, ...
    - tankmodel layer in `BT-7` / `AMX-30`: `barrelDP = "gun_barrel_dm"`, `emitter = "bone_gun_barrel"`, turret `barrel = "bone_gun_barrel"`
  - `cannon_breech`
    - canonical class in `damageModelParts.blk`
    - DM layer: `cannon_breech_dm`, `cannon_breech_01_dm`, ...
    - tankmodel binding through `breechDP = "cannon_breech_dm"`
  - `gunner`
    - canonical class/templates in `damageModelParts.blk`
    - DM layer: `gunner_dm`, `gunner_01_dm`, ...
    - tankmodel bindings through crew `dmPart = "gunner_dm"` and weapon/turret `gunnerDm = "gunner_dm"`
  - `optic_gun`
    - canonical class in `damageModelParts.blk`
    - DM layer: `optic_gun_dm`, `optic_gun_01_dm`
    - tankmodel layer appears in optic/sight damage blocks
  - `track`
    - canonical family expands into split left/right DM names
    - local examples consistently expose `track_l_dm` / `track_r_dm`
  - `body`
    - canonical family maps to `body_dm`
    - related runtime interner proof already exists through lazy intern of `"body_dm"`

Seat-registry confirmation for `word2`:
- `FUN_0161ac60(manager, seat)` returns the per-seat registry at:
  - `manager + 0x578 + seat * 0x20`
- `FUN_00a67bb0(registry, name)` binary-searches the sorted name table inside that registry
- combined with `FUN_01631fa0(...)`, this keeps the current `word2` reading stable:
  - `word2` = selector/remap id obtained from the sorted seat registry for the canonical name
- `FUN_0161ad00(manager, seat)` now makes the runtime side concrete:
  - it walks the aligned `ushort` selector table at `registry + 0x10`
  - resolves each selector against the live seat holder at `manager + 0x88[seat]`
  - and materializes the resulting `uint32` remap/state cache at `manager + 0x630`
- `FUN_016278d0(...)` is a concrete downstream user of that family:
  - it takes `param_5 & 0xffff` as the resolved selector/remap index
  - uses that low `ushort` against the live holder at `manager + 0x88[seat]`
  - and forwards the resolved transform/state into `FUN_01625d20(...)`
- `FUN_01625d20(...)` is therefore the live trace/effect applier below the same selector/remap path:
  - it is only called by `FUN_016278d0(...)` and `FUN_0162aac0(...)`
  - it first checks the seat-holder-side active list for the incoming selector/remap `ushort`
  - builds the actual collision / effect candidate through `FUN_0161d4e0(...)`
  - commits/enqueues it through `FUN_019240c0(...)` + `FUN_01925700(...)`
  - and mirrors the committed result back into the live seat holder through `FUN_0161b220(...)`
- `FUN_0162aac0(...)` is now identified as the bulk-dispatch sibling of `FUN_016278d0(...)`, not a separate destination family:
  - it is only called by `FUN_00a96e40(...)`
  - starts by clearing/preparing selector state through `FUN_0162a8a0(...)`
  - iterates a descriptor list whose entries index `manager + 0x658`
  - resolves live object transforms from the seat-0 holder at `manager + 0x88[0]`
  - then forwards each selected descriptor into the same `FUN_01625d20(...)` commit path
- `FUN_0162a8a0(...)` is the matching pre-clear helper for that bulk path:
  - it walks the same `manager + 0x658` descriptors
  - zeroes the corresponding live holder slots in `manager + 0x88[0/1]`
  - and also clears mirrored state through the optional `+0x130` fallback store
- `FUN_019240c0(...)` is the queue allocator/commit stage beneath `FUN_01625d20(...)`:
  - it copies the full `0x3b0` event/effect candidate into the global queue under `DAT_09915e20`
  - returns the queue slot index
  - and `FUN_01925700(...)` then attaches the holder/object identity and selector metadata to that slot
- `FUN_01621390(...)` remains the matching updater for the `manager + 0x88[seat]` holder
- practical runtime chain now:
  - canonical name
  - -> seat-registry selector
  - -> compact selector table near `manager + 0x358`
  - -> packed triple `word2`
  - -> runtime `uint32` remap cache at `manager + 0x630` (`FUN_0161ad00`)
  - -> either single-dispatch lookup in `manager + 0x88[seat]` (`FUN_016278d0`) or bulk descriptor dispatch via `manager + 0x658` + `manager + 0x88[0]` (`FUN_0162aac0`)
  - -> collision / effect candidate build (`FUN_0161d4e0`)
  - -> event/commit queue (`FUN_019240c0` / `FUN_01925700`)
  - -> live holder state writeback (`FUN_0161b220`)

Current step closure:
- the destination side of `word2` is now closed:
  - it lands in one live event/effect commit family through either the single-dispatch caller `FUN_016278d0(...)` or the bulk-dispatch sibling `FUN_0162aac0(...)`
- the strongest current canonical one-to-one mappings are also closed enough to use:
  - `gun_barrel`
  - `cannon_breech`
  - `gunner`
  - `optic_gun`
  - `track`
  - `body`
- remaining work after this step is no longer destination tracing:
  - it is bulk extraction/reporting of selector families per canonical class for concrete vehicles

Concrete per-vehicle extraction now started with `fr_amx_30_1972`:

| canonical / `word1` | selector-family reading | explicit DM names in vehicle data | explicit binding / trigger data in vehicle data |
| --- | --- | --- | --- |
| `gun_barrel` | gun / weapon selector family | `gun_barrel_dm`, `gun_barrel_01_dm`, `gun_barrel_02_dm`, ... | main weapon `trigger = "gunner0"`, `barrelDP = "gun_barrel_dm"`, `emitter = "bone_gun_barrel"`, turret `barrel = "bone_gun_barrel"`; coaxial path `trigger = "gunner1"`, `barrelDP = "gun_barrel_01_dm"`, `emitter = "bone_gun_barrel_01"` |
| `cannon_breech` | same gun / weapon selector family as barrel | `cannon_breech_dm`, `cannon_breech_01_dm`, ... | main weapon `breechDP = "cannon_breech_dm"` |
| `gunner` | gunner / crew selector family | `gunner_dm`, `gunner_01_dm`, `gunner_02_dm`, `gunner_03_dm` | `tank_crew.gunner.dmPart = "gunner_dm"`; turret weapon blocks use `gunnerDm = "gunner_dm"` |
| `optic_gun` | gunner / optic selector family | `optic_gun_dm`, `optic_gun_01_dm` | sight / optic damage blocks present in local DM data; canonical family still aligns with gunner sight path |
| `track` | left / right chassis selector family | `track_l_dm`, `track_r_dm`, `track_l_01_dm`, `track_r_01_dm` | wheel damage links collapse into `track_l_dm` / `track_r_dm` through `onKill` mappings |
| `body` | hull / body selector family | `body_top_dm`, `body_front_dm`, `body_side_dm`, `body_back_dm`, `body_bottom_dm` and aggregate `body_dm` family | body-side meta groups aggregate many hull pieces; runtime canonical body family should sit above these DM names |

Interpretation for the AMX-30 pass:
- this is now enough to treat `fr_amx_30_1972` as a concrete reporting example for the current reverse model
- `gun_barrel` and `cannon_breech` are the strongest explicit gunner-seat mappings
- `gunner` and `optic_gun` remain the strongest crew / sight mappings
- `track` and `body` show the expected chassis / hull split underneath the same canonical -> DM expansion model

Cross-check against `ussr_bt_7_1937`:
- the same canonical invariants repeat cleanly:
  - `gun_barrel` -> `gun_barrel_dm` + turret `barrel = "bone_gun_barrel"` + weapon `emitter = "bone_gun_barrel"`
  - `cannon_breech` -> `cannon_breech_dm`
  - `gunner` -> `gunner_dm`
  - `optic_gun` -> `optic_gun_dm`
  - `track` -> `track_l_dm` / `track_r_dm`
- the main variation between vehicles is not the canonical family itself, but the expansion shape:
  - count of suffixed DM entries like `gun_barrel_01_dm`, `gun_barrel_02_dm`, ...
  - whether secondary weapons share the same gunner family or fan out into additional trigger groups
  - exact node/bone names for secondary barrels such as `bone_gun_barrel_01`
- this makes the current split stronger:
  - canonical class / `word1` is invariant enough across vehicles
  - `word2` still selects the vehicle-local runtime selector/remap family
  - DM/node bindings are the vehicle-specific expansion layer beneath that canonical class

Current invariant vs vehicle-specific split:

| layer | appears invariant across `BT-7` and `AMX-30` | appears vehicle-specific |
| --- | --- | --- |
| canonical / `word1` | `gun_barrel`, `cannon_breech`, `gunner`, `optic_gun`, `track`, `body` | additional optional classes and exact family population |
| `word2` family reading | gun/weapon, gunner/optic, chassis/track, hull/body selector families | exact selector population and per-seat distribution |
| DM layer | base names like `gun_barrel_dm`, `cannon_breech_dm`, `gunner_dm`, `track_l_dm`, `track_r_dm` | number of suffixed entries such as `_01_dm`, `_02_dm`, ... |
| node/binding layer | gun/turret/body roles stay structurally similar | exact bones, extra emitters, secondary weapon bindings |

Final reporting table for the current pass:

| canonical / `word1` | runtime `word2` family | common invariant DM names | vehicle-specific examples |
| --- | --- | --- | --- |
| `gun_barrel` | gun / weapon selector family | `gun_barrel_dm` | `BT-7`: main gun `trigger = "gunner0"`, `emitter = "bone_gun_barrel"`; `AMX-30`: main gun `gunner0`, coaxial `gunner1`, with `gun_barrel_01_dm` and `bone_gun_barrel_01` expansions |
| `cannon_breech` | gun / weapon selector family | `cannon_breech_dm` | `BT-7`: `breechDP = "cannon_breech_dm"`; `AMX-30`: same main-gun binding plus extra suffixed breech parts |
| `gunner` | gunner / crew selector family | `gunner_dm` | `BT-7`: crew damage family only; `AMX-30`: `tank_crew.gunner.dmPart = "gunner_dm"` and turret `gunnerDm = "gunner_dm"` |
| `optic_gun` | gunner / optic selector family | `optic_gun_dm` | `BT-7`: optic block plus turret optics; `AMX-30`: optic damage family present with `optic_gun_01_dm` expansion |
| `track` | left / right chassis selector family | `track_l_dm`, `track_r_dm` | `BT-7`: base left/right tracks only; `AMX-30`: adds `track_l_01_dm` / `track_r_01_dm` and wheel `onKill` collapse into track parts |
| `body` | hull / body selector family | `body_dm` family | `BT-7`: hull/body aggregate family; `AMX-30`: body-side DM pieces like `body_top_dm`, `body_front_dm`, `body_side_dm`, `body_back_dm`, `body_bottom_dm` |

Use for `DynamicHitPoint`:
- treat `word1` as the cross-vehicle canonical class
- treat `word2` as the vehicle-local runtime selector/remap family for that class
- treat DM names and node/binding names as the expansion layer to report per vehicle

Practical working matrix for the strongest current groups:

| canonical / `word1` | likely `word2` selector family | DM / repair names seen in Toy | tankmodel / node bindings seen in Toy |
| --- | --- | --- | --- |
| `gun_barrel` | gun/weapon seat selector family, typically on `gunner0` weapon chains | `gun_barrel_dm`, `gun_barrel_01_dm`... | `barrelDP`, `emitter = bone_gun_barrel`, turret `barrel = bone_gun_barrel` |
| `cannon_breech` | same gun/weapon seat family as barrel | `cannon_breech_dm`, `cannon_breech_01_dm`... | `breechDP = cannon_breech_dm` |
| `gunner` | crew/seat selector family on gunner-related seats | `gunner_dm`, `gunner_01_dm`, ... | crew `dmPart = gunner_dm`, weapon `gunnerDm = gunner_dm` |
| `optic_gun` | sight/optic selector family near gunner sight bindings | `optic_gun_dm`, `optic_gun_01_dm` | optic damage blocks; likely tied to gunner sight/optic records |
| `track` | left/right chassis selector family, likely split by side | `track_l_dm`, `track_r_dm`, `track_l_01_dm`, `track_r_01_dm` | left/right track node groups and repair blocks |
| `body` | hull/body selector family | `body_dm` | hull/body aggregate bindings |

Interpretation:
- the `+0x408` / packed-triple accessor path is now confirmed in:
  - build-time setup
  - runtime query/volume logic
  - bulk selector/group enumeration
  - trace/collision filtering
  - hit/impact forwarding
- so this container family is not peripheral bookkeeping:
  - it is central to live damageable-part selection

### `FUN_0169b090`

Confirmed behavior:
- is a formatting helper for interned ids and special encoded part names
- if the high-bit/encoding path is not taken, it simply returns:
  - `FUN_014f6b40(id)`

Interpretation:
- this is a lightweight confirmation that interned ids in this runtime family are expected to be rendered back into human-readable names
- useful as a secondary proof of the reversible name path, but less directly tied to the damage registry than:
  - `FUN_00a74680`
  - `FUN_016fea00`

### `FUN_01620450` / `FUN_01620b50`

Confirmed behavior:
- `FUN_01620b50(...)` is a thin change-gate around `FUN_01620450(...)`
- `FUN_01620450(...)` updates one live damage/health slot in:
  - `*(long *)(manager + 0x3d8) + slot * 0x14`
- triggers downstream callbacks when the value changes

Interpretation:
- these are live state mutators layered below the registry / descriptor builders
- they do not enumerate canonical names or consume the per-seat `"%s_dm"` tuple table directly
- useful mainly as proof that the registry/descriptor families already feed concrete mutable runtime state

### `FUN_0161c3f0`

Confirmed behavior:
- uses `FUN_0161ac60(param_1, seat)` to get a seat registry
- uses `FUN_00a67bb0(registry, param_2)` to find a name within that registry
- on success, reads:
  - `*(ushort *)(*(long *)(registry + 0x10) + idx * 2)`
  - as the selector/id corresponding to that name
- then applies that selector/id back into the live seat object at:
  - `*(param_1 + 0x88)[seat]`

Interpretation:
- this is strong proof that the seat registry is the canonical name -> selector map for each seat
- and that the selector values written into `record + 0x50` are not anonymous ids:
  - they are looked up and manipulated by name through this registry

### `FUN_00a67bb0`

Confirmed behavior:
- takes `(registry, name)`
- binary-searches `*(char ***)registry` with count `*(int64 *)(registry + 8)`
- returns the matching slot index or `0xffffffff`

Interpretation:
- this closes the front-end shape of the seat registry:
  - `+0x00` = sorted name table
  - `+0x08` = count
- together with `FUN_0161c3f0`, we now know the next aligned field too:
  - `+0x10` = selector/id table

### `FUN_01d5ec30`

Confirmed behavior:
- tears down/reset downstream state rooted at `param_1 + 0xa0`
- frees object-entry arrays at:
  - `+0x28/+0x38`
  - `+0x40/+0x50`
- resets allocator owners at:
  - `+0x18`
  - `+0x30`
  - `+0x48`
- ends by setting a default marker at `+0xc0`

Interpretation:
- this confirms `FUN_01d19cd0` manages the real `0x178` record's downstream payload root at `+0xa0`
- it is no longer just an analogue once the corrected `FUN_01d3a310 -> FUN_01d2ba20 -> FUN_01d1aa30` chain is applied

### `FUN_01c85190`

Confirmed behavior:
- is another setup/configuration writer for a different family rooted at `param_1`
- resizes/copies two string-like buffers at:
  - `param_1 + 0x10/+0x20/+0x24`
  - `param_1 + 0x28/+0x38/+0x3c`
- then drives generic setup helpers:
  - `FUN_0726ab20(param_1 + 0x44c, ...)`
  - `FUN_01cab840(...)`
  - `FUN_01d5dbf0(param_1 + 0x4c0)`
  - `FUN_01d5edc0(param_1 + 0x618)`
  - `FUN_01d5e040(..., param_1 + 0x4c0)`
  - `FUN_01d617a0(param_1 + 0x4c0, ..., param_1 + 0x618, ...)`

Interpretation:
- this is another sibling setup family that shares downstream setup helpers with `FUN_01d1aa30`
- however, it is resource/string driven rather than part-selector/template driven
- useful mainly to confirm that:
  - `FUN_01d5e040`
  - `FUN_01d617a0`
  are generic setup plumbing reused by multiple families

### `FUN_01c86510`

Confirmed behavior:
- updates runtime transform-ish state for the same `01c85190` family
- copies a transform block into `param_2 + 0x30 .. +0x90`
- if a backing object exists at `param_2 + 0x660`, reuses its prebuilt setup rooted at:
  - `backing + 0x4c0`
  - `param_2 + 0x678`
- then calls:
  - `FUN_01d617a0(backing + 0x4c0, ..., param_2 + 0x678, ...)`
  - `FUN_01d60c00(param_2 + 0x678, ...)`

Interpretation:
- another confirmation that the `+0x4c0/+0x618/+0x678` setup family is separate generic machinery
- not the direct builder of the unresolved `0x178` bucket records

### `FUN_01d3a310`

Confirmed behavior:
- is the immediate manager above `FUN_01d1aa30`
- callers currently seen:
  - `FUN_00a8cb60`
  - `FUN_016f06f0`
  - `FUN_017429f0`
- also directly calls at least two more sibling setup families:
  - `FUN_01d1bb50`
  - `FUN_01d31010`

Interpretation:
- this keeps the `FUN_01d19cd0 -> FUN_01d1aa30 -> FUN_01d3a310` chain as the best local example of a real template/setup family
- but `FUN_01d3a310` itself is now clearly a broader weapon/setup manager, not a single-family wrapper
- we still need a different sibling chain under this manager whose layout matches the `0x178` bucket records more closely

### `FUN_01d1a870`

Confirmed behavior:
- routes a blk node to one bucket-header offset within the manager object passed as `param_1`
- direct mappings currently confirmed:
  - `bombGun` -> `param_1 + 0xf0`
  - `rocketGun` or `drawRocketInBullet` -> `param_1 + 0x108`
  - `torpedoGun` -> `param_1 + 0x120`
  - `fuelTankGun` -> `param_1 + 0x138`
  - `boosterGun` -> `param_1 + 0x150`
  - `undercarriageGun` -> `param_1 + 0x168`
  - `airDropGun` -> `param_1 + 0x180`
  - `targetingPodGun` -> `param_1 + 0x198`
- recursively resolves nested `container.blk` and then returns the same mapped bucket pointer
- xrefs currently show only self-recursion and `FUN_01d3a310`

Interpretation:
- this is the strongest proof so far that the `+0xf0..+0x198` cluster inside the `01d3a310`-managed object is a typed bucket-header family
- the bucket choice is driven by weapon/container class, not by generic owner-read helpers
- however, this still does not expose the writer of the unresolved `0x178` record field bundle directly

### `FUN_01d1bb50`

Confirmed behavior:
- is another sibling setup writer used only from `FUN_01d3a310`
- recursively handles `container` blocks and emitter-like child nodes
- resolves skeleton node names through `FUN_03690af0(...)`
- dynamically builds `count * 0x30` transform/template arrays for emitter nodes, then multiplies them against an input transform block
- writes aggregated transform data into output arrays passed by reference through `param_5/param_6`

Interpretation:
- this is a real setup writer, but it is an emitter/container transform family
- its output shape is dynamic transform arrays, not the `0x178` bucket-record layout we are trying to match

### `FUN_01d31010`

Confirmed behavior:
- is a very large sibling setup writer called only from `FUN_01d3a310`
- parses many weapon-class blk types and fields including:
  - `bombGun`
  - `rocketGun`
  - `torpedoGun`
  - `fuelTankGun`
  - `boosterGun`
  - `airDropGun`
  - `undercarriageGun`
  - `targetingPodGun`
  - `gearRange`
  - `sweepRange`
  - `fieldOffsets`
  - `shellCasing`
- builds and appends multiple runtime record families, notably:
  - a `0x60`-stride per-weapon entry array rooted at `plVar71[0x9a]`
  - a `0x40`-stride range/mechanism table rooted at `param_1 + 0x260`
  - a small `0xc`-stride `fieldOffsets` list rooted at `plVar71[0xb4]`
- also populates weapon flags such as `circleAim`, `aimingFromBoneGun`, `hasAdditionalSight`, and `hasSpecialNightVision`

Interpretation:
- `FUN_01d31010` confirms `FUN_01d3a310` is a broad weapon/setup manager with multiple downstream record families
- but the layouts here are `0x60`, `0x40`, and `0xc` driven weapon-support structures, not the unresolved `0x178` bucket-record family
- this is therefore a sibling setup family, not yet the direct `record + 0x50` writer we still need

### `FUN_01d2ba20`

Confirmed behavior:
- is a direct allocator/append helper for the unresolved `0x178` record family
- xrefs currently show only one caller:
  - `FUN_01d3a310`
- it grows `param_1` as an array of `0x178`-byte entries
- on append, it zero-initializes most pointer/state fields and seeds key sentinels:
  - `+0x4` gets `0xffffffff`
  - `+0xc` gets `0`
  - `+0x164` gets `0xffffffff`
  - `+0x168` and `+0x16c` are also initialized to invalid/default markers
- move/copy logic preserves the full mixed layout, including embedded dynamic subobjects and pointer-owned fields

Interpretation:
- this is the first direct constructor-layer proof for the actual `0x178` bucket-record family
- `FUN_01d3a310` is therefore not just managing analogous families; it really does allocate the exact record type we have been tracing through:
  - `FUN_01d17f90`
  - `FUN_01d19930`
  - `FUN_01d4d170`
- the remaining unresolved step is now narrower still:
  - identify where `FUN_01d3a310` fills the newly appended `0x178` entry, especially `+0x30/+0x40/+0x50/+0x88/+0xa0/+0x140/+0x150`

### `FUN_01d2c390`

Confirmed behavior:
- is a full reset/reseed helper for the same setup-manager object that owns the `0x178` bucket cluster
- xrefs currently show only two callers:
  - `FUN_01d3a310`
  - `FUN_01d2d0b0`
- begins by clearing every typed `0x178` bucket header through repeated calls to:
  - `FUN_01d2c150(param_1 + 0xf0)`
  - `FUN_01d2c150(param_1 + 0x108)`
  - `FUN_01d2c150(param_1 + 0x120)`
  - `FUN_01d2c150(param_1 + 0x138)`
  - `FUN_01d2c150(param_1 + 0x150)`
  - `FUN_01d2c150(param_1 + 0x168)`
  - `FUN_01d2c150(param_1 + 0x180)`
  - `FUN_01d2c150(param_1 + 0x198)`
- also tears down and zeros multiple sibling families in the same object:
  - `+0xb8/+0xc0` large `0x308`-stride family
  - `+0x1c8/+0x1d8` `0x300`-stride side-record family
  - `+0x1e0/+0x1f0` and `+0x1f8/+0x208` two separate `0x68`-stride families
  - `+0x2b8` registry/group state via `FUN_01d59770` and `FUN_01d5bcb0`
- then reseeds fixed descriptor/status tables instead of leaving the manager empty:
  - writes a three-entry descriptor block at `+0x1310` with ids/states centered around `7`, `8`, `9`
  - writes a five-entry descriptor block at `+0x1400` with ids/states centered around `0`, `1`, `4`, `7`, `8`

Interpretation:
- `FUN_01d2c390` is not just a bucket clear helper; it is the manager-level reset/rebuild gate for the whole setup object
- this makes the call at the top of `FUN_01d3a310` much more meaningful:
  - `FUN_01d3a310` starts from a fully reinitialized manager state before it begins repopulating typed bucket records
- it also strengthens the lifecycle picture:
  - `FUN_01d2d0b0` is the destructor/reset side
  - `FUN_01d2c390` is the reusable clear/reseed side
  - `FUN_01d3a310` is the repopulation/build side

### `FUN_01d2d0b0`

Confirmed behavior:
- is a larger lifecycle destructor/reset wrapper for the same setup-manager object
- xrefs currently show one caller:
  - `FUN_01d2e040`
- calls `FUN_01d2c390` first, then proceeds to tear down the remaining manager-owned families
- notably walks and destroys multiple `0x178` bucket arrays through `FUN_01d2b6c0`, matching the typed cluster rooted at:
  - `+0xf0`
  - `+0x108`
  - `+0x120`
  - `+0x138`
  - `+0x150`
  - `+0x168`
  - `+0x180`
  - `+0x198`

Interpretation:
- this is the strong lifecycle complement to `FUN_01d2ba20`
- together they now bracket the real `0x178` family cleanly:
  - `FUN_01d2ba20` appends one live entry
  - `FUN_01d2c390` clears/reseeds the manager
  - `FUN_01d2d0b0` destroys the manager-side families during teardown

### `FUN_01d2c150`

Confirmed behavior:
- is the bucket-array clear helper for one typed header of `0x178` records
- xrefs currently show one caller:
  - `FUN_01d2c390`
- walks `count * 0x178` bytes and performs a two-stage reset:
  - stage 1 clears shallow pointer-like fields directly:
    - `+0x10/+0x18`
    - `+0x20/+0x28`
    - `+0x30/+0x38`
    - `+0x40/+0x48`
    - `+0x50/+0x58`
    - `+0x88/+0x90`
  - also clears flags at:
    - `+0x80`
    - `+0x98`
  - and resets generated payload state via:
    - `FUN_01d5edc0(record + 0xa0)`
- stage 2 then calls `FUN_01d2b6c0(record)` for each entry to tear down the deeper owned substructures

Interpretation:
- this strongly separates the `0x178` record into two ownership layers:
  - a shallow dynamic-buffer layer at `+0x10/+0x20/+0x30/+0x40/+0x50/+0x88`
  - a deeper owned-object layer starting at `+0xa0` and above
- it also reinforces that the field bundle we are tracking is real and grouped intentionally, not just accidental offset reuse

### `FUN_01d2b6c0`

Confirmed behavior:
- is the deep per-record teardown helper for one `0x178` entry
- xrefs currently show three callers:
  - `FUN_01d2ba20`
  - `FUN_01d2c150`
  - `FUN_01d2d0b0`
- tears down the upper half of the record in a structured order:
  - frees `+0x150`
  - iterates pointer/object array at `+0x140` using count `+0x148`
  - clears embedded subobjects at `+0xf8` and `+0x118` via `FUN_049f1e80`
  - frees a `0x50`-stride owned array at `+0xe0` with count `+0xf0`
  - frees a `0x48`-stride owned array at `+0xc8` with count `+0xd8`
  - releases allocator-owned handle/object at `+0xb0/+0xb8`
  - clears a `0x20`-stride subobject array at `+0xa0` with count `+0xa8`
  - finally frees the shallow buffers at `+0x88`, `+0x50`, `+0x40`, `+0x30`, `+0x20`, `+0x10`

Interpretation:
- `FUN_01d2b6c0` makes the internal bundle of the `0x178` record much sharper:
  - `+0x10/+0x20/+0x30/+0x40/+0x50/+0x88` are plain dynamic buffers
  - `+0xa0/+0xc8/+0xe0/+0xf8/+0x118/+0x140/+0x150` are owned structured subfamilies
- this matters for the unresolved writer problem because it suggests `FUN_01d3a310` probably fills one record in layers:
  - first grow/assign shallow arrays
  - then build deeper generated payload/object tables
  - rather than writing everything in a single contiguous block

### `FUN_01cf1c70` and `FUN_01cf2080`

Confirmed behavior:
- both are mesh/container setup builders from a different setup family reached via:
  - `FUN_01d1cd80`
- they repeatedly use the same embedded-subobject helpers we have seen around the `0x178` family:
  - `FUN_049f1830`
  - `FUN_049f1850`
  - `FUN_049f1e80`
- each appended entry here is `0x20` bytes wide:
  - zero first 16 bytes
  - initialize an embedded subobject with `FUN_049f1830`
  - populate it with `FUN_049f1dd0`
  - destroy temporaries with `FUN_049f1e80`
- `FUN_01cf2080` also recurses through `"container"` blk nodes, while `FUN_01cf1c70` handles direct `"mesh"` / `"mesh_deployed"` leaves

Interpretation:
- these functions are not writing the `0x178` record family directly
- but they provide a strong analogue for one specific subfield inside it:
  - `FUN_01d2b6c0` frees `record + 0xa0` as a `0x20`-stride array
  - the `01cf1c70/01cf2080` pattern shows exactly how such `0x20`-stride entries are commonly built in this codebase
- so `record + 0xa0` is now best read as a generated mesh/container payload family built with generic embedded-subobject constructors, not as the semantic selector table itself
- this pushes the unresolved semantic part-selector problem even more narrowly onto the shallow buffers:
  - especially `+0x40`
  - and `+0x50`

### `FUN_01d617a0`

Confirmed behavior:
- is a larger analogue setup builder used by:
  - `FUN_01d1aa30`
  - `FUN_01c85190`
  - `FUN_01c86510`
- it begins by clearing a generated payload family with `FUN_01d5ec30(param_3)`
- then ensures a `0x20`-stride payload array matches the source count:
  - reallocates/grows the backing array as needed
  - initializes newly added entries with `FUN_049f1830`
- it uses `FUN_01d2b1b0` as a generic `0x30`-stride resize helper for transform/template arrays
- later it builds additional owned subfamilies:
  - a `0x48`-stride object table
  - a `0x40`-stride table rooted at `param_3[0x14]`
  - plus several id/name mappings and embedded object handles
- repeatedly uses `FUN_01d5f1e0` followed by `FUN_049f1dd0` / `FUN_049f1e80` to materialize name/model-backed payload nodes

Interpretation:
- `FUN_01d617a0` is not the `0x178` record writer, but it gives a strong build-order analogue
- the pattern is layered and explicit:
  - clear generated payload layer first
  - grow `0x20` payload entries
  - grow `0x30` transform/template rows with `FUN_01d2b1b0`
  - then build higher tables like `0x40` and `0x48`
- this is consistent with the teardown-based read of the `0x178` record
- and it further supports the idea that in `FUN_01d3a310` the semantic selector problem should be searched in the shallow table phase rather than the deep `+0xa0` payload phase

Refined analogue from `FUN_01d1aa30`:
- this function now shows the shallow-table write pattern explicitly in a sibling family under the same top manager
- for each seat/index it performs direct inline writes, not helper-based writes:
  - writes `0xffffffff` into `*(uint *)(*(long *)(param_2 + 0x10) + seat * 4)` on failure
  - writes a resolved `uint32` remap value into that same `param_2 + 0x10` table on success
  - writes `*(undefined2 *)(*(long *)(param_2 + 0x14) + seat * 2)` from a `ushort` source selector table
  - writes `*(undefined8 *)(*(long *)(param_2 + 4) + seat * 8)` as a seat-indexed object/handle table
- alongside those shallow table writes, it also copies `0x30`-stride transform/template rows into:
  - `param_2 + 8`
  - `param_2 + 0xc`
  - `param_2 + 0x22`
- and later builds the deep payload family at:
  - `param_2 + 0x28`
  - through `FUN_01d617a0`

Interpretation:
- this is the clearest analogue yet for what we should expect inside `FUN_01d3a310`
- in this sibling family, the semantic shallow tables are populated inline by direct indexed stores:
  - `uint32` remap table
  - `ushort` selector table
  - object/handle table
- so the lack of a standalone helper for `+0x40/+0x50` in the `0x178` family is no longer just a negative result
- it now matches a confirmed codebase pattern under the same manager hierarchy

### Early direct-store branch inside `FUN_01d3a310`

Confirmed disassembly around `01d3aaff..01d3af1b`:
- this branch indexes entries as:
  - `RBX = *(R15 + 0xd0) + index * 0x48`
- then writes:
  - `RBX + 0x38` = resolved `0x40`-stride transform/object pointer
  - `RBX + 0x40` = `FUN_0161b450(...)` result / local id-like value
- the branch resolves source rows through:
  - `FUN_06e6fc10(...)`
  - `FUN_03690af0(...)`
  - fallback lookup through `(*(owner + 0xf0))[0]`

Interpretation:
- this is an important cut:
  - `FUN_01d3a310` does contain direct inline stores into shallow-looking fields
  - but this specific branch is building a sibling `0x48`-stride record family, not the target `0x178` bucket records
- therefore these visible stores do not explain the unresolved `0x178` descriptors at:
  - `record + 0x40/+0x48`
  - `record + 0x50/+0x58`
- still, the branch reinforces the higher-level pattern:
  - `FUN_01d3a310` is willing to populate sibling setup families by direct inline writes rather than by small dedicated helpers

### `FUN_01d5f1e0`

Confirmed behavior:
- is a generic name/model payload materializer used by:
  - `FUN_01d617a0`
  - `FUN_01d1aa30`
  - `FUN_01cf1c70`
  - `FUN_01cf2080`
  - `FUN_01d5f6d0`
- it builds a small object with:
  - string/name resolution
  - `FUN_049f1830`
  - `FUN_049f1850`
  - `FUN_049f2140`
- then returns that object as a reusable payload node

Interpretation:
- `FUN_01d5f1e0` confirms the deep payload side is generic shared machinery across multiple setup families
- so it should not be treated as evidence for the semantic meaning of `record + 0x40/+0x50`
- instead it strengthens the split:
  - deep payload generation is generic
  - unresolved semantics are still most likely encoded in shallow tables such as `+0x40/+0x50`

### `FUN_01d61640`

Confirmed behavior:
- is another generic qword (`0x8`-stride) resize helper
- xrefs currently show one caller:
  - `FUN_01d617a0`
- decompilation is effectively identical in shape to `FUN_01d2b430`
- uses the same allocator vtable growth/realloc/free pattern

Interpretation:
- this confirms the codebase reuses one generic qword-table growth pattern in multiple setup families
- but it also sharpens a negative result for the `0x178` investigation:
  - in the nearby helper clusters we now have strong matches for `0x30` arrays and qword arrays
  - but still no dedicated generic helper for `uint32` or `uint16` selector-table growth
- that makes it more likely that the unresolved shallow selector buffers at `+0x40/+0x50` in the `0x178` record are filled by direct writes or inline copies inside `FUN_01d3a310`, rather than by a small standalone resizer helper

### `FUN_01d17f90`

Refined field reads now confirmed directly from the decompilation:
- for each `0x178` record, the semantic part-selector read is:
  - `uVar30 = *(ushort *)(*(long *)(record + 0x50) + seat * 2)`
- so `record + 0x50` is not just “some pointer-like field”
- it is specifically a pointer to a `ushort` table indexed by seat
- this selector is then used to index the part-transform source at `unit + 0xf0[seat]`

Additional structure-level observations:
- `record + 0x30` is read as a `0x30`-stride transform/template row array
- `record + 0x88` is written as a `0x30`-stride composed transform/output array
- `record + 0x140` and `record + 0x150` are consumed later as `0x40`-stride instance/object transform tables

Interpretation:
- this is the strongest direct proof yet that `record + 0x50` is the semantic selector table we have been tracking
- combined with the helper survey, it now looks even more likely that the `ushort` contents of this table are populated inline inside `FUN_01d3a310`, not through a standalone shared helper

### `FUN_01d19930`

Refined field reads now confirmed directly from the decompilation:
- this function reads:
  - `uVar14 = *(uint *)(*(long *)(record + 0x40) + index * 4)`
- so `record + 0x40` is specifically a pointer to a `uint32` table indexed by the dispatch/input index
- that `uint32` value is then used as a destination/remap index into the downstream transform destination arrays

Interpretation:
- `record + 0x40` is no longer just “dispatch-like”
- it is concretely a `uint32` remap/dispatch table
- together with `FUN_01d17f90`, the shallow semantic layer of the `0x178` record now splits cleanly into:
  - `+0x40` = `uint32` destination/remap table
  - `+0x50` = `ushort` part-selector table
- this also explains why the nearby helper sweep failed to find a shared `uint16`/`uint32` table builder:
  - these two tables are very likely filled directly inside `FUN_01d3a310`

Constructor/teardown nuance from `FUN_01d2ba20` and `FUN_01d2c150`:
- the shallow table fields are not stored as lone pointers
- each one is a 16-byte pair that moves and resets together:
  - `+0x10/+0x18`
  - `+0x20/+0x28`
  - `+0x30/+0x38`
  - `+0x40/+0x48`
  - `+0x50/+0x58`
  - `+0x88/+0x90`
- `FUN_01d2ba20` move/copy logic transfers both qwords of each pair when reallocating the `0x178` array
- `FUN_01d2c150` clears the high qword of each pair before freeing the low qword pointer

Interpretation:
- `record + 0x40` and `record + 0x50` should now be read as the base pointers of two shallow table-descriptor pairs:
  - `+0x40/+0x48` = `uint32` remap-table descriptor
  - `+0x50/+0x58` = `ushort` selector-table descriptor
- the second qword is still unresolved, but it is almost certainly per-table metadata rather than a separate semantic payload
- this strengthens the expectation that `FUN_01d3a310` fills these tables inline as descriptor pairs, not as bare pointers

### `FUN_01d2b110`, `FUN_01d2b160`, `FUN_01d2b190`, and `FUN_01d2b310`

Confirmed behavior:
- these nearby `01d2b***` helpers are not part of the `0x178` shallow-table writer path:
  - `FUN_01d2b110` parses just `activeTime` / `reloadTime`
  - `FUN_01d2b160` rotates a small modulo-3 state
  - `FUN_01d2b190` reads that modulo-3 state back through a tiny lookup table
  - `FUN_01d2b310` is a small-string/inline-buffer helper used under `FUN_01d31010`

Interpretation:
- this largely closes the nearby `01d2b***` cluster as a source of hidden selector-table builders
- after separating these out, the unresolved semantic write to `+0x40/+0x50` looks even more likely to live inline in `FUN_01d3a310` itself

### `FUN_01d2b590`

Confirmed behavior:
- is a separate append helper for a `0x48`-byte record family
- xrefs currently show only one caller:
  - `FUN_01d3a310`
- grows an array of 9 qwords per entry and appends one copied record
- decompilation/disassembly now make the layout exact:
  - `9 * 8 = 0x48` bytes per entry
  - existing entries are copied with four `xmmword` moves plus one trailing qword
  - appended entries are likewise copied as one fixed `0x48` block
- it is pure fixed-block append/realloc logic:
  - no per-seat loop
  - no `ushort` selector writes
  - no descriptor-pair handling like the `0x178` family

Interpretation:
- useful as a nearby contrast inside the same manager
- confirms `FUN_01d3a310` is building multiple record families in parallel
- together with the visible direct-store branch at `01d3aaff..01d3af1b`, this now strongly supports:
  - that branch belongs to the `0x48` sibling family
  - not to the unresolved `0x178` bucket-record path
- so these `RBX + 0x38/+0x40` writes should no longer be considered candidate writes for:
  - `record + 0x40/+0x48`
  - `record + 0x50/+0x58`

### `FUN_01d1bb50`

Refined behavior now confirmed from decompilation:
- is a recursive container/emitter transform builder
- starts from `blk` / `mesh` / `emitter` metadata
- resolves emitter node names through:
  - `FUN_03690af0(...)`
- accumulates emitter transforms into dynamic `0x30`-stride arrays
- can recurse back into itself when a nested `"container"` blk is present
- writes/updates:
  - transform arrays in `param_5`
  - associated name/object handle in `param_6`
  - count/ammo-like totals through `param_7`
  - aggregate mass-style floats through `param_8` / `param_9`

Interpretation:
- this is still a sibling setup family under `FUN_01d3a310`
- but it is building emitter/container transform arrays, not the `0x178` bucket-record semantic tables
- useful mainly as another contrast:
  - it reinforces that `FUN_01d3a310` mixes several recursive weapon/container builders
  - but none of its visible `0x30` array work should be conflated with the unresolved `0x178` `+0x40/+0x50` descriptors

### `FUN_01d1cc10`

Refined behavior now confirmed from decompilation:
- is a downstream distribution/update helper over an array of object pointers
- input shape is:
  - `param_1` = object-pointer array
  - `param_2` = count / divisor-like value
  - `param_3` = quantity to distribute
- it divides `param_3` across the array, then for each live object:
  - checks object readiness through virtual `+0x1f0`
  - updates an integer field around `object + 0x370`
  - calls virtual `+0xe8`

Interpretation:
- this is not part of record construction at all
- it is a pure post-setup distribution/helper stage under `FUN_01d3a310`
- therefore it should be removed from the candidate set for the missing `0x178` shallow semantic writer

### `FUN_01d30880`

Confirmed behavior:
- xrefs currently show one caller:
  - `FUN_01d3a310`
- it manages an array of `0x10`-byte entries
- each entry is effectively:
  - one `uint32`/small scalar field
  - one owned qword/pointer-like field
- on insert/realloc it:
  - shifts existing entries by `0x10`
  - move-transfers the owned qword field
  - releases the displaced owned field through `DAT_09b4f1e0 + 0x40`

Interpretation:
- this is another sibling container helper under `FUN_01d3a310`
- but it is not part of the `0x178` record family, and not a writer for:
  - `record + 0x40/+0x48`
  - `record + 0x50/+0x58`
- useful mainly as negative control:
  - `FUN_01d3a310` mixes several setup families of different strides
  - so visible direct stores in one branch must be checked against stride/layout before being treated as evidence for the `0x178` path

### `FUN_01d2b1b0`

Confirmed behavior:
- is a generic dynamic-array resize helper for `0x30`-stride elements
- xrefs currently show two callers:
  - `FUN_01d3a310`
  - `FUN_01d617a0`
- signature shape is effectively:
  - `buffer_ptr`
  - `new_count`
  - `allow_realloc`
- uses allocator vtable methods at `+0x18/+0x30/+0x38/+0x40`
- when growth requires reallocation, it copies `count * 0x30` bytes and preserves existing contents

Interpretation:
- `FUN_01d2b1b0` is not specific to the `0x178` family
- but it is now a strong candidate for how `FUN_01d3a310` grows per-record subarrays that look like:
  - `+0x20`
  - `+0x30`
  - `+0x88`
- this fits the emerging picture where `FUN_01d3a310` appends one `0x178` record via `FUN_01d2ba20`, then populates its embedded dynamic subfields with generic resizers rather than one monolithic writer

### `FUN_01d2b430`

Confirmed behavior:
- is a generic dynamic-array resize helper for qword (`0x8`-stride) elements
- xrefs currently show one caller:
  - `FUN_01d3a310`
- also uses allocator vtable methods at `+0x18/+0x30/+0x38/+0x40`
- enforces a minimum capacity of `2` entries and copies old qword contents forward on resize

Interpretation:
- this is another likely building block used by `FUN_01d3a310` while filling freshly appended `0x178` records
- candidate fields in the record bundle that could plausibly be serviced by this helper are the pointer/handle tables such as:
  - `+0x10`
  - `+0x40`
  - `+0x140`
  - `+0x150`
- like `FUN_01d2b1b0`, it looks generic rather than semantic by itself
- so the remaining task is still to identify which branch in `FUN_01d3a310` pairs:
  - `FUN_01d2ba20` for record append
  - with `FUN_01d2b1b0` / `FUN_01d2b430` for subfield growth
  - and the semantic writes that fill `+0x40/+0x50`

### `FUN_01d1dbf0`

Confirmed behavior:
- builds a dynamic `0x14`-stride list of angle/pitch records from a blk node
- xrefs currently show only one caller:
  - `FUN_01d3a310`
- output records hold pairs of floats plus one tag/id field, then mark a flag byte at `param_3 + 0x44`

Interpretation:
- another sibling setup helper under `FUN_01d3a310`
- relevant mainly as negative control: this is a small per-weapon tuning list, not the `0x178` bucket-record writer

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
