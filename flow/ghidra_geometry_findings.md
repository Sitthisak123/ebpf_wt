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
- when a live runtime source exists (`plVar15 != 0`), it writes:
  - `object + 0x2a0` = `plVar15[0x1a0]` (runtime pointer/anchor candidate)
  - `FUN_0368b750((long)plVar15 + 0xcdc, object + 0x2ac, object + 0x2b0, object + 0x2b4)`
  - `object + 0x2b8` = 0
- also updates:
  - `object + 0x294/+0x29c` from `object + 0x114/+0x11c` or `object + 0x130/+0x138`
  - `object + 0x2e0`
  - `object + 0x2e4`
  - `object + 0x290`

Interpretation:
- the seat/view object has a concrete geometry block now:
  - `+0x294/+0x29c` = position-like cached state
  - `+0x2a0` = live source/object pointer candidate
  - `+0x2ac/+0x2b0/+0x2b4` = orientation angles derived from a runtime basis block
- this is the strongest runtime struct evidence so far for a materialized seat/sight state object

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
  - resolve what object `+0x2a0` points at
  - map its `+0xcdc` block as a transform source

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
- previous assumption that `+0x2a8` was an index/id is wrong
- corrected field meaning:
  - `+0x2a0` = refcounted source/object pointer
  - `+0x2a8` = pointer to array of entry records
  - `+0x2b8` = count of those entries
- this makes `+0x2a0` even more likely to be the single live source object behind the seat/sight state

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
