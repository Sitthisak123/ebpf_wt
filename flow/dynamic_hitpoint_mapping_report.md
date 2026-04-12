# DynamicHitPoint Mapping Report

## Scope

This report extracts the current high-confidence reverse state for the live `DynamicHitPoint`-style path:

- packed triple family under `*(manager + 0x350) + 0x148`
- canonical damage-part ids (`word1`)
- vehicle-local selector/remap ids (`word2`)
- live runtime destination chain into the seat-holder / event-effect commit family

This file is meant to be the compact operational summary, separate from the longer Ghidra notes.

## Packed Triple

Current best split of the packed `uint6` triple:

| field | meaning |
| --- | --- |
| `word0` | descriptor index |
| `word1` | interned canonical damage-part id |
| `word2` | seat-registry-derived selector/remap id |

Builder-side chain:

1. canonical name/id
2. seat-registry selector via `FUN_01631fa0(...)`
3. compact `ushort` table near `manager + 0x358`
4. `meta + 0x08`
5. packed triple `word2` via `FUN_0163db10(...)`

## Runtime Destination Chain

Current high-confidence runtime chain:

1. canonical name
2. seat-registry selector
3. packed triple `word2`
4. remap/state cache at `manager + 0x630` via `FUN_0161ad00(...)`
5. live holder lookup in `manager + 0x88[seat]`
6. dispatch into `FUN_01625d20(...)`
7. candidate build via `FUN_0161d4e0(...)`
8. queue/commit via `FUN_019240c0(...)` and `FUN_01925700(...)`
9. holder writeback via `FUN_0161b220(...)`

Caller split:

- `FUN_016278d0(...)` = single-dispatch path
- `FUN_0162aac0(...)` = bulk-dispatch sibling path

Both land in the same live event/effect commit family.

## Canonical Mapping

Current high-confidence canonical classes:

| canonical / `word1` | runtime `word2` family | common invariant DM names | current vehicle-specific examples |
| --- | --- | --- | --- |
| `gun_barrel` | gun / weapon selector family | `gun_barrel_dm` | `BT-7`: main gun `emitter = "bone_gun_barrel"`; `AMX-30`: main gun `gunner0`, coaxial `gunner1`, with `gun_barrel_01_dm` and `bone_gun_barrel_01` expansion |
| `cannon_breech` | gun / weapon selector family | `cannon_breech_dm` | `BT-7`: `breechDP = "cannon_breech_dm"`; `AMX-30`: same plus extra suffixed breech parts |
| `gunner` | gunner / crew selector family | `gunner_dm` | `BT-7`: crew family; `AMX-30`: `tank_crew.gunner.dmPart = "gunner_dm"` and turret `gunnerDm = "gunner_dm"` |
| `optic_gun` | gunner / optic selector family | `optic_gun_dm` | `BT-7`: optics block includes `optic_gun_dm`; `AMX-30`: `optic_gun_dm` and `optic_gun_01_dm` expansion |
| `track` | left / right chassis selector family | `track_l_dm`, `track_r_dm` | `BT-7`: base left/right track parts only; `AMX-30`: adds `track_l_01_dm` / `track_r_01_dm` and wheel `onKill` collapse into track parts |
| `body` | hull / body selector family | `body_dm` family | `AMX-30`: body-side DM pieces like `body_top_dm`, `body_front_dm`, `body_side_dm`, `body_back_dm`, `body_bottom_dm`; runtime canonical body family sits above these |

## Invariant vs Vehicle-Specific

| layer | cross-vehicle stable | vehicle-specific |
| --- | --- | --- |
| canonical / `word1` | `gun_barrel`, `cannon_breech`, `gunner`, `optic_gun`, `track`, `body` | optional extra classes and exact population |
| `word2` family reading | gun/weapon, gunner/optic, chassis/track, hull/body selector families | exact selector population and per-seat distribution |
| DM layer | `gun_barrel_dm`, `cannon_breech_dm`, `gunner_dm`, `optic_gun_dm`, `track_l_dm`, `track_r_dm`, `body_dm` family | suffixed expansion counts like `_01_dm`, `_02_dm`, ... |
| node/binding layer | same broad roles: gun barrel, turret, crew, track, hull | exact bones, emitters, secondary triggers, extra weapon branches |

## MemRead Targets

If verifying in real time, the most useful surfaces are:

- `manager + 0x408` = packed triple table in the current live layout
- `*(manager + 0x350) + 0x148` = alternate/fallback packed-triple container view
- `manager + 0x3d8` = descriptor metadata
- `manager + 0x358` = compact selector/remap table
- `manager + 0x578 + seat * 0x20` = seat registries
- `manager + 0x630` = runtime remap/state cache
- `manager + 0x88[seat]` = live seat holders
- `manager + 0x658` = descriptor family used by the bulk-dispatch sibling path

## Live MemRead Notes

Latest real-time probe results:

- the best current live manager root comes from `my_unit + 0x1068` (dereferenced)
- the hottest live packed-triple view is `manager + 0x408`
  - current observed header:
    - `data_ptr != 0`
    - `count = 138`
    - `cap = 138`
  - current observed non-sentinel examples:
    - `(word0, word1, word2) = (31, 3955, 98)`
    - `(4, 794, 48)`
    - `(73, 1474, 83)`
    - `(72, 1476, 82)`
    - `(8, 58, 1)`
    - `(69, 1326, 81)`
    - `(33, 2943, 58)`
    - `(6, 795, 50)`
    - `(10, 2944, 96)`
  - unlike the alternate `+0x350/+0x148` route, this view yields mixed non-`0xffff` triples immediately
- the alternate `*(manager + 0x350) + 0x148` container still exists, but the current live preview was dominated by `0xffff` entries
- seat registry at `manager + 0x578 + seat * 0x20` currently behaves like:
  - entry stride `0x10`
  - `count = 2`
  - both visible entries currently carry low value `98`
  - entry field `+0x00` does not behave like a plain `char *`
  - at least one observed entry is a string-object family whose first qword dereferences again to a real string such as `@root`
  - nested pointers inside the same object suggest multiple string/object layers rather than a flat C-string table
  - recursive live decoding of that first entry currently surfaces names like:
    - `@root`
    - `antenna`
    - `bone_antenna_01`
    - `bone_gun`
  - this is the strongest live proof so far that the registry path is exposing a small object tree / grouped-name family, not a sorted flat `char **` table in the current in-memory representation
  - another observed entry looked like a packed / UTF-16-like short-string object rather than a normal C string
  - so the registry-name layer should currently be treated as a string-object family, not as a raw `char **` table
- `manager + 0x630` currently reads more like a live state/weight array than raw ids:
  - observed count-like field aligned with holder count `98`
  - preview values were `1.0f` repeated
  - so this surface should currently be treated as a materialized runtime state/cache, not yet as a proven raw id table
- `manager + 0x88[0]` holder view is live and coherent:
  - valid holder pointer
  - current count `98`
- cross-seat live probing now shows at least three runtime seat shapes:
  - `seat 0`:
    - can expose an active registry tree with `count = 2`
    - visible low selector value has been observed as both `98` and `91` in different live states
    - holder count has been observed as both `98` and `91` in different live states
    - recursive string-object decode surfaces `@root`, `antenna`, `bone_antenna_01`, `bone_gun`
  - `seat 1`:
    - registry currently empty (`count = 0`)
    - remap cache empty
    - holder exists with count `69`, but current tail preview is zeroed
  - `seat 2 / 3`:
    - share a compact live triple set with `count = 169`
    - visible `word2` examples include `48`, `10`, `83`, `82`, `50`
    - remap/state count-like field at `+0x644` is `91`
    - registry header shape differs from seat 0 and currently decodes as a more compact / unresolved layout rather than the string-object tree seen on seat 0

This means the current best live reading is no longer "one registry layout for every seat":

- `seat 0` currently exposes a richer grouped-name tree
- `seat 1` can be structurally present but inactive
- `seat 2 / 3` likely sit on a different compact selector surface that still feeds the same packed-triple path
- and re-tests show this is state-dependent, not just seat-index-dependent:
  - in a later session/state, `seat 0` moved onto the same `count = 169` triple family as `seat 2`
  - but still kept the richer grouped-name tree decode at `+0x578`
  - so the safest current model is:
    - `manager + 0x408` = stable hot triple surface
    - `manager + 0x578 + seat * 0x20` = per-seat surface whose concrete layout can vary with live state

Working live interpretation after the first MemRead pass:

- manager root: `my_unit + 0x1068` dereferenced
- live triple table: `manager + 0x408`
- `+0x350` family: still related, but not the best direct live preview route
- registry-name decoding: still incomplete
- but the first live MemRead pass now strongly suggests mixed string-object layouts:
  - pointer-to-string objects such as `@root`
  - and packed short-string / UTF-16-like objects
- recursive probing now adds concrete child names under the same live object family:
  - `antenna`
  - `bone_antenna_01`
  - `bone_gun`
  - this makes the current best live reading of seat registry state:
    - not a final canonical-name table
    - but a grouped runtime object/name tree that still preserves useful node names for selector verification
- first concrete live correlation is now:
  - one live state gave seat-registry visible low value = `98`, holder count = `98`, and hot triple `word2 = 98`
  - a later live state gave seat-registry visible low value = `91` and holder count = `91`
  - a direct histogram pass on the hot triple table then showed `registry low_u16 = 91` occurs in `triple.word2` exactly once in that state
  - the concrete matched row in that state is now pinned:
    - `idx = 57`
    - `word0 = 30`
    - `word1 = 3855`
    - `word2 = 91`
  - the corresponding descriptor metadata row at `*(manager + 0x3d8) + word0 * 0x14` was also read live:
    - raw = `ffff0e001e000f0f5b000000000080bf000080bf`
    - `+0x02` flags field = `0x000e`
    - `+0x04` mirrors `word0 = 30`
    - `+0x06` mirrors `word1 = 3855`
    - `+0x08` mirrors `word2 = 91`
    - trailing floats currently read as `-1.0f`, `-1.0f`
  - this strongly suggests the visible registry low field tracks the same selector/remap axis as the live triple / holder path, but that axis is runtime-state-dependent
  - for a later verified `ussr_2s19_m1` live state, the same method yielded:
    - `unit_key = ussr_2s19_m1`
    - registry low value = `170`
    - target row = `idx = 198`, `word0 = 176`, `word1 = 1738`, `word2 = 170`
    - metadata row still mirrors those fields directly through the `+0x3d8` `0x14`-stride family
  - the matched `ussr_2s19_m1` target is not isolated:
    - it sits inside a contiguous superfamily
    - `idx = 191..211`
    - `word0 = 169..189`
    - `word1 = 1731..1751`
    - `word2 = 163..183`
    - every row seen in this superfamily currently shares `flags = 0x0008`
  - in that same `ussr_2s19_m1` state the live registry tree exposed:
    - `@root`
    - `antenna`
    - `bone_antenna_01`
    - `bone_commander_sight_h`
  - current best interpretation is therefore:
    - the `word2 = 163..183` superfamily is a sensor / commander-sight family for this vehicle/state
    - not the gun-barrel family
  - explicit comparison runs on the same `ussr_2s19_m1` state now separate the other two major candidate blocks:
    - `word2 = 457..481`
      - contiguous block length = `25`
      - `idx = 149..173`
      - `word0 = 132..156`
      - `word1 = 1653..1677`
      - flags split into two phases in live re-tests:
        - earlier probe: `457..472` => `flags = 0x0008`, `473..481` => `flags = 0x000a`
        - later re-test: `457..478` => `flags = 0x0008`, `479..481` => `flags = 0x000a`
      - compact summary from the later re-test:
        - `flags_hist = { 0x0008: 22, 0x000a: 3 }`
      - implication:
        - this block is stable as a contiguous family
        - but the exact internal flag boundary is runtime-state-dependent
      - this is currently the strongest gun-family candidate block for `ussr_2s19_m1` because it is the largest alternate contiguous family that is not coupled to the visible `antenna / commander_sight` tree
    - `word2 = 155..162`
      - contiguous block length = `8`
      - `idx = 141..148`
      - `word0 = 124..131`
      - `word1 = 1645..1652`
      - all rows currently share `flags = 0x0008`
      - this looks like a smaller homogeneous side family, but it correlates less strongly with the suspected weapon/gun cluster than `457..481`
  - current ranking for `ussr_2s19_m1` live selector families:
    - `163..183` => strongest commander/sensor family candidate
    - `457..481` => strongest gun-family candidate
    - `155..162` => smaller secondary family, currently weaker gun correlation than `457..481`
  - brief cross-seat probe on the same live state currently shows:
    - `seat 0` is the only seat with a clean registry/holder correlation surface for this path
    - `seat 0` => `reg_count = 2`, `holder_count = 170`, `values = [170]`
    - `seat 1+` currently do not expose a comparably valid registry surface for this selector path in the probe output
  - current practical implication:
    - for `ussr_2s19_m1`, live verification of these selector families should stay anchored on `seat 0`
    - multi-seat scanning is still useful for noise rejection, but not yet for direct name correlation
  - current blocker is no longer field layout:
    - live MemRead already separates the main families cleanly
    - the remaining ambiguity is runtime context
    - the strongest gun candidate block (`457..481`) still needs a gun-active state to correlate against a tree that exposes `bone_gun / gun_barrel / optic_gun` rather than the currently visible `antenna / commander_sight` branch
  - probe support was extended to make that next verification cheaper:
    - explicit `word2` ranges now print a compact block summary
    - summary includes `idx`, `word0`, `word1`, `word2` spans and `flags_hist`
  - cross-view comparison on `ussr_2s19_m1` was then verified from user-provided live logs:
    - modes checked:
      - main gun scope view
      - third-person view
      - binocular view
      - possible commander-sight style view
    - invariant across all of those logs:
      - registry still surfaced the same `seat 0` family anchor
      - visible registry tree stayed on the same branch:
        - `@root`
        - `antenna`
        - `bone_antenna_01`
        - `bone_commander_sight_h`
      - the candidate gun-family block itself stayed stable:
        - `idx = 149..173`
        - `word0 = 132..156`
        - `word1 = 1653..1677`
        - `word2 = 457..481`
    - what changed across views was only the internal flag split at the end of the block:
      - one run: `flags_hist = { 0x0008: 22, 0x000a: 3 }`
      - another run: `flags_hist = { 0x0008: 23, 0x000a: 2 }`
    - implication:
      - camera/view mode alone does not switch the visible registry branch from `commander/antenna` over to a `bone_gun` branch in the current probe surface
      - but it does perturb the tail state of the `457..481` block
      - that makes `457..481` look even more like a live weapon-related family whose internal tail records react to runtime state
  - direct lookup-surface probing was then added for the `457..481` block:
    - the `+0x648` lookup table is not constant across the block
    - instead it shows a repeating grouped pattern over `word0 = 132..156`
    - later live sample for `457..481`:
      - `lookup_hist = {1090767339:2, 1051931444:6, 1028443344:6, 1090945184:2, 1091120421:2, 1091296997:2, 1091316010:2, 1091493272:2, 1091668944:1}`
    - practical interpretation:
      - this block is not behaving like a flat selector-id run
      - it is carrying structured per-record lookup state with repeated subpatterns inside the contiguous family
      - that strengthens the view that `457..481` is a live weapon/gun family with internal subroles, not a random contiguous alias block
    - decoding the observed `lookup_u32` values as `float` makes the subpattern clearer:
      - repeating small constants:
        - `1051931444 -> 0.35000002`
        - `1028443344 -> 0.05000001`
      - interleaved larger monotonic values:
        - `1090767339 -> 8.2367964`
        - `1090945184 -> 8.4064026`
        - `1091120421 -> 8.5735216`
        - `1091296997 -> 8.7419176`
        - `1091316010 -> 8.7600498`
        - `1091493272 -> 8.9291000`
        - `1091668944 -> 9.0966339`
    - implication:
      - the `+0x648` lookup surface for `457..481` looks like live geometric/state parameters, not opaque ids
      - the monotonic `~8.24 .. 9.10` ladder plus repeated `0.35 / 0.05` constants is consistent with a structured weapon-side family with repeated per-subpart parameters
      - this further strengthens the gun/weapon interpretation of `457..481`
  - sibling-family check on `word2 = 540..551` then showed a closely related pattern:
    - contiguous block length = `12`
    - `idx = 174..185`
    - `word0 = 157..168`
    - `word1 = 1678..1689`
    - `word2 = 540..551`
    - all rows currently share `flags = 0x000a`
    - `lookup_hist = {1051931444:3, 1028443344:3, 1091668944:1, 1091843199:2, 1092021796:2, 1092198538:1}`
    - decoded float pattern:
      - repeated constants:
        - `1051931444 -> 0.35000002`
        - `1028443344 -> 0.05000001`
      - monotonic ladder:
        - `1091668944 -> 9.0966339`
        - `1091843199 -> 9.2628164`
        - `1092021796 -> 9.4331398`
        - `1092198538 -> 9.6016941`
    - interpretation:
      - `540..551` does not look like the commander/sensor family
      - it looks like a sibling weapon-side subfamily adjacent to `457..481`
      - compared to `457..481`, it is shorter and fully in the `flags = 0x000a` state
    - local datamine on `ussr_2s19_m1.blkx` strengthens that reading:
      - main gun path:
        - `trigger = "gunner0"`
        - `emitter = "bone_gun_barrel"`
        - `barrelDP = "gun_barrel_dm"`
        - `breechDP = "cannon_breech_dm"`
        - gun nodes:
          - `gun = "bone_gun"`
          - `barrel = "bone_gun_barrel"`
      - commander-sight path:
        - `trigger = "gunner3"`
        - `triggerGroup = "commander"`
        - `emitter = "bone_commander_sight_v"`
        - `gun = "bone_commander_sight_v"`
        - `verDriveDm / horDriveDm = "commander_panoramic_sight_dm"`
      - machine-gun path:
        - `trigger = "gunner2"`
        - `triggerGroup = "machinegun"`
        - `barrelDP = "gun_barrel_02_dm"`
        - `gunnerDm = "commander_dm"`
    - practical implication:
      - because the commander branch already correlates with the `163..183` family, the sibling weapon-side block `540..551` now looks more like an auxiliary / machine-gun / attachment subfamily than a commander-sight family
  - current weapon-side grouping for `ussr_2s19_m1` is therefore:
    - primary gun-family candidate:
      - `word2 = 457..481`
    - likely sibling weapon/coax/optic-side subfamily:
      - `word2 = 540..551`
    - smaller secondary family:
      - `word2 = 155..162`
  - follow-up check on `word2 = 155..162` showed it is materially different from the two stronger weapon-side blocks:
    - contiguous block length = `8`
    - `idx = 141..148`
    - `word0 = 124..131`
    - `word1 = 1645..1652`
    - `word2 = 155..162`
    - all rows keep `flags = 0x0008`
    - `lookup_hist = {33507070:1, 524653:1, 725:1, 0:1, 1090591976:2, 1051931444:1, 1028443344:1}`
    - decoded float-like values include:
      - `1090591976 -> 8.0695572`
      - `1051931444 -> 0.35000002`
      - `1028443344 -> 0.05000001`
      - plus several near-zero / non-meaningful tiny values from raw integer-like entries:
        - `33507070`
        - `524653`
        - `725`
        - `0`
    - interpretation:
      - unlike `457..481` and `540..551`, this block does not present a clean monotonic ladder of weapon-like lookup floats
      - it still shares the repeated `0.35 / 0.05` constants, so it may be related
      - but it now looks more like a secondary/support family than a primary weapon geometry family
  - local tool bridge check on `src/utils/mul.py:get_weapon_barrel(...)`:
    - this helper is a heuristic barrel-bone resolver used by:
      - `radar_overlay.py`
      - `tools/sub/vehicle_ballistics_compare_dumper.py`
      - `tools/sub/camera_parallax_probe_dumper.py`
      - `tools/sub/optic_runtime_probe_dumper.py`
    - it scans packed-name blobs under several candidate unit offsets and scores names by priority:
      - strongest positive matches:
        - `bone_gun_barrel`
        - `gun_barrel`
        - `bone_gun`
        - `barrel`
      - strong negative filters:
        - `optic`
        - `antenna`
        - `camera`
        - `track`
        - `wheel`
        - `root`
    - implication:
      - this helper is useful as a practical bridge for live validation of the gun side
      - but it does not, by itself, prove the identity of the `457..481` runtime selector family
      - the correct use is correlation:
        - compare the gun-family candidate block against a simultaneously resolved barrel bone/path from `get_weapon_barrel(...)`
        - not to treat the helper as the source of truth for the runtime family
  - the live probe was extended accordingly:
    - `tools/sub/dynamic_hitpoint_realtime_probe.py` now prints a `[barrel-bridge]` section
    - it resolves:
      - `unit_pos`
      - `barrel_base`
      - `barrel_tip`
      - `dir = barrel_tip - barrel_base`
    - practical next use:
      - rerun the same live probe while inspecting the `457..481` block
      - then compare whether the gun-family candidate stays stable while the barrel bridge resolves a plausible `bone_gun_barrel / bone_gun` path on the same frame

### 2S19M1 Final Vehicle Table

- `word2 = 163..183`
  - likely role: commander / sensor / panoramic-sight family
  - live evidence:
    - `idx = 191..211`
    - `word0 = 169..189`
    - `word1 = 1731..1751`
    - all rows currently `flags = 0x0008`
    - registry branch exposed:
      - `@root`
      - `antenna`
      - `bone_antenna_01`
      - `bone_commander_sight_h`
  - datamine evidence:
    - `triggerGroup = "commander"`
    - `emitter = "bone_commander_sight_v"`
    - `gun = "bone_commander_sight_v"`
    - `commander_panoramic_sight_dm`

- `word2 = 457..481`
  - likely role: primary main-gun family
  - live evidence:
    - `idx = 149..173`
    - `word0 = 132..156`
    - `word1 = 1653..1677`
    - stable contiguous block across view changes
    - mixed live tail flags:
      - `flags_hist = { 0x0008: 22..23, 0x000a: 2..3 }`
    - structured lookup-float pattern:
      - repeated `0.35 / 0.05`
      - monotonic ladder roughly `8.24 .. 9.10`
    - barrel bridge resolves a plausible main-gun world path on the same live state
  - datamine evidence:
    - `trigger = "gunner0"`
    - `emitter = "bone_gun_barrel"`
    - `barrelDP = "gun_barrel_dm"`
    - `breechDP = "cannon_breech_dm"`
    - `gun = "bone_gun"`
    - `barrel = "bone_gun_barrel"`

- `word2 = 540..551`
  - likely role: sibling weapon-side subfamily, most likely auxiliary machine-gun / attachment-side
  - live evidence:
    - `idx = 174..185`
    - `word0 = 157..168`
    - `word1 = 1678..1689`
    - all rows currently `flags = 0x000a`
    - lookup-float pattern matches weapon-side structure:
      - repeated `0.35 / 0.05`
      - monotonic ladder roughly `9.10 .. 9.60`
  - datamine evidence:
    - `trigger = "gunner2"`
    - `triggerGroup = "machinegun"`
    - `barrelDP = "gun_barrel_02_dm"`
    - `gunnerDm = "commander_dm"`

- `word2 = 155..162`
  - likely role: secondary/support family
  - live evidence:
    - `idx = 141..148`
    - `word0 = 124..131`
    - `word1 = 1645..1652`
    - all rows currently `flags = 0x0008`
    - lookup surface is mixed:
      - shares `0.35 / 0.05`
      - but also contains zero / tiny integer-like values
      - does not present the clean monotonic ladder seen in the stronger weapon families
  - datamine evidence:
    - no direct one-to-one binding closed yet
    - currently treated as a related support/auxiliary family rather than the primary gun path
- `+0x630` semantics: likely state/cache layer, not final raw-remap-id proof yet
- seat handling is mixed:
  - not every seat exposes the same registry shape at `+0x578`
  - so per-seat probing is required before assuming a single flat decode strategy

## New Vehicle Baseline: `ussr_t_44_100`

- live baseline after vehicle switch:
  - `unit_key = ussr_t_44_100`
  - `short_name = T-44-100`
  - `family = exp_tank`
  - `seat 0` is `READY`
  - barrel bridge resolves a plausible main-gun path:
    - `barrel_base = [1728.1395, 219.3111, 1788.6556]`
    - `barrel_tip = [1757.8512, 220.0711, 1792.7348]`
    - `dir = [29.7117, 0.7599, 4.0792]`
- unlike `2S19M1`, the currently visible `seat 0` registry branch already exposes:
  - `@root`
  - `antenna`
  - `bone_antenna_01`
  - `bone_gun`
- target row in the current live state:
  - registry low value = `98`
  - `idx = 1`
  - `word0 = 31`
  - `word1 = 3955`
  - `word2 = 98`
  - metadata mirror:
    - `flags = 0x000e`
    - raw = `ffff0e001f00730f62000000000080bf000080bf`
- neighborhood around `word0 = 31` is not a large clean superfamily:
  - `w0 = 29` => `word2 = 42`, `flags = 0x000e`
  - `w0 = 30` => `word2 = 55`, `flags = 0x000e`
  - `w0 = 31` => `word2 = 98`, `flags = 0x000e`
  - `w0 = 32` => `word2 = 59`, `flags = 0x000a`
  - `w0 = 33` => `word2 = 58`, `flags = 0x000a`
- contiguous-family scan for this vehicle/state currently shows small weapon-like clusters instead of one large block:
  - `idx = 98..100` => `word0 = 114..116`, `word1 = 1750..1752`, `word2 = 453..455`
  - `idx = 101..103` => `word0 = 99..101`, `word1 = 1735..1737`, `word2 = 438..440`
  - `idx = 104..106` => `word0 = 104..106`, `word1 = 1740..1742`, `word2 = 443..445`
  - `idx = 107..109` => `word0 = 109..111`, `word1 = 1745..1747`, `word2 = 448..450`
- practical implication:
  - for `T-44-100`, the next useful target is not the old `2S19M1` ranges
  - the new gun-side candidates to compare next are:
    - `word2 = 438..440`
    - `word2 = 443..445`
    - `word2 = 448..450`
    - `word2 = 453..455`
  - first focused follow-up on `word2 = 453..455`:
    - contiguous block length = `3`
    - `idx = 98..100`
    - `word0 = 114..116`
    - `word1 = 1750..1752`
    - `word2 = 453..455`
    - all rows currently share `flags = 0x000a`
    - lookup values:
      - `5570644 = 0x00550054`
      - `5701718 = 0x00570056`
      - `5832792 = 0x00590058`
    - the lookup values advance by a constant delta `0x00020002`
    - practical interpretation:
      - unlike the `2S19M1` weapon families, this `T-44-100` block does not currently look float-like
      - it looks more like a compact paired / packed integer progression
      - still weapon-side plausible because it is a clean contiguous family near the `bone_gun`-visible seat-0 registry state, but its internal representation appears different from the SPG case
  - second focused follow-up on `word2 = 448..450`:
    - contiguous block length = `3`
    - `idx = 107..109`
    - `word0 = 109..111`
    - `word1 = 1745..1747`
    - `word2 = 448..450`
    - mixed flags:
      - `448..449` => `flags = 0x0008`
      - `450` => `flags = 0x000a`
    - lookup values:
      - `4915274 = 0x004b004a`
      - `5046348 = 0x004d004c`
      - `5177422 = 0x004f004e`
    - the lookup values again advance by a constant delta `0x00020002`
    - interpretation:
      - this is another packed-integer sibling progression of the same general family style as `453..455`
      - together they suggest the `T-44-100` gun-side cluster is split into several short monotonic packed subranges rather than one large float-driven block like `2S19M1`
  - third focused follow-up on `word2 = 443..445`:
    - contiguous block length = `3`
    - `idx = 104..106`
    - `word0 = 104..106`
    - `word1 = 1740..1742`
    - `word2 = 443..445`
    - all rows currently share `flags = 0x0008`
    - lookup values:
      - `4259904 = 0x00410040`
      - `4390978 = 0x00430042`
      - `4522052 = 0x00450044`
    - again the lookup values advance by the same constant delta `0x00020002`
    - interpretation:
      - this confirms a repeated packed progression pattern across multiple short gun-side blocks on `T-44-100`
      - the currently observed cluster is now:
        - `443..445`
        - `448..450`
        - `453..455`
  - fourth focused follow-up on `word2 = 438..440`:
    - contiguous block length = `3`
    - `idx = 101..103`
    - `word0 = 99..101`
    - `word1 = 1735..1737`
    - `word2 = 438..440`
    - all rows currently share `flags = 0x0008`
    - lookup values:
      - `3604534 = 0x00370036`
      - `3735608 = 0x00390038`
      - `3866682 = 0x003b003a`
    - again the lookup values advance by the same constant delta `0x00020002`
    - interpretation:
      - this closes the currently visible packed cluster for `T-44-100`
      - the gun-side family on this vehicle/state is best modeled as a series of short packed monotonic subranges:
        - `438..440`
        - `443..445`
        - `448..450`
        - `453..455`

### T-44-100 Final Vehicle Table

- `word2 = 98`
  - likely role: visible seat-anchor / root-correlated descriptor
  - live evidence:
    - `idx = 1`
    - `word0 = 31`
    - `word1 = 3955`
    - `flags = 0x000e`
    - registry branch shows:
      - `@root`
      - `antenna`
      - `bone_antenna_01`
      - `bone_gun`
  - interpretation:
    - useful live anchor for the current state
    - not the packed gun-side cluster itself

- `word2 = 438..440`
  - likely role: packed gun-side subrange A
  - live evidence:
    - `idx = 101..103`
    - `word0 = 99..101`
    - `word1 = 1735..1737`
    - `flags = 0x0008`
    - lookup progression:
      - `0x00370036`
      - `0x00390038`
      - `0x003b003a`

- `word2 = 443..445`
  - likely role: packed gun-side subrange B
  - live evidence:
    - `idx = 104..106`
    - `word0 = 104..106`
    - `word1 = 1740..1742`
    - `flags = 0x0008`
    - lookup progression:
      - `0x00410040`
      - `0x00430042`
      - `0x00450044`

- `word2 = 448..450`
  - likely role: packed gun-side subrange C
  - live evidence:
    - `idx = 107..109`
    - `word0 = 109..111`
    - `word1 = 1745..1747`
    - mixed flags:
      - `448..449 = 0x0008`
      - `450 = 0x000a`
    - lookup progression:
      - `0x004b004a`
      - `0x004d004c`
      - `0x004f004e`

- `word2 = 453..455`
  - likely role: packed gun-side subrange D
  - live evidence:
    - `idx = 98..100`
    - `word0 = 114..116`
    - `word1 = 1750..1752`
    - `flags = 0x000a`
    - lookup progression:
      - `0x00550054`
      - `0x00570056`
      - `0x00590058`

- vehicle-level conclusion for `ussr_t_44_100`
  - current gun-side family is best modeled as a packed monotonic cluster of short adjacent subranges:
    - `438..440`
    - `443..445`
    - `448..450`
    - `453..455`
  - this differs from `2S19M1`, where the strongest weapon family appears as a larger contiguous block with float-like lookup values
  - for `T-44-100`, the simultaneous presence of:
    - a valid barrel bridge
    - `bone_gun` in the seat-0 registry branch
    - and the four packed monotonic subranges above
    strongly supports treating this cluster as the active gun-side family in the current state

## Automated New Vehicle Baseline: `ussr_zsu_57_2`

- automation support was added to the live probe:
  - `--auto-family-scan N`
  - this automatically expands the top contiguous selector families for the current live vehicle
- first automated baseline on the new vehicle yielded:
  - `unit_key = ussr_zsu_57_2`
  - `short_name = ZSU-57-2`
  - `family = exp_SPAA`
  - valid barrel bridge:
    - `barrel_base = [1726.1504, 219.4524, 1788.6811]`
    - `barrel_tip = [1755.9691, 219.7050, 1791.9648]`
    - `dir = [29.8187, 0.2527, 3.2836]`
  - visible seat-0 registry branch:
    - `@root`
    - `antenna`
    - `bone_antenna_01`
    - `bone_gun`
- current seat-anchor row:
  - registry low value = `91`
  - `idx = 57`
  - `word0 = 30`
  - `word1 = 3855`
  - `word2 = 91`
  - `flags = 0x000e`
- automated family scan shows the current live selector landscape is different again:
  - `word2 = 401..433`
    - `len = 33`
    - `idx = 112..144`
    - `word0 = 78..110`
    - `word1 = 1645..1677`
    - all rows `flags = 0x0008`
    - lookup surface is mixed:
      - many `1.0f` entries (`1065353216`)
      - plus sentinels / zeros / small integers
  - `word2 = 434..443`
    - `len = 10`
    - `idx = 97..106`
    - `word0 = 117..126`
    - `word1 = 1731..1740`
    - flags split:
      - `434..435` => `0x0008`
      - `436..443` => `0x000a`
    - lookup is constant across the whole block:
      - `1325399723`
  - `word2 = 446..451`
    - `len = 6`
    - `idx = 89..94`
    - `word0 = 129..134`
    - `word1 = 1743..1748`
    - all rows `flags = 0x000a`
    - lookup is constant:
      - `1325399723`
  - `word2 = 452..457`
    - `len = 6`
    - `idx = 83..88`
    - `word0 = 135..140`
    - `word1 = 1749..1754`
    - all rows `flags = 0x000a`
    - lookup is mixed/noisy:
      - `1325399723`
      - `33558772`
      - `2919305771`
      - `37`
      - `0`
  - `word2 = 542..547`
    - `len = 6`
    - `idx = 145..150`
    - `word0 = 111..116`
    - `word1 = 1678..1683`
    - all rows `flags = 0x0008`
    - lookup mostly `0` plus small sentinels and one `1325399723`
- practical interpretation:
  - `ussr_zsu_57_2` does not match the `2S19M1` float-ladder style or the `T-44-100` packed short-range style
  - the strongest current gun-side candidates are now:
    - `434..443`
    - `446..451`
    - `452..457`
  - while:
    - `401..433` looks broader and more state-heavy
    - `542..547` currently looks auxiliary / trailing rather than primary

## Current Status

Completed for this pass:

- packed triple semantics
- builder/source chain for `word2`
- runtime destination chain for `word2`
- stable canonical matrix for the main ground-tank classes
- cross-check on `fr_amx_30_1972` and `ussr_bt_7_1937`

Still open:

- bulk runtime extraction of exact selector populations per live vehicle
- one-to-one live `word2` value dumps from MemRead for a running match/session
