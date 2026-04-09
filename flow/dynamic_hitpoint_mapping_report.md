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
  - seat-registry visible low value = `98`
  - live holder count = `98`
  - first observed hot triple also carries `word2 = 98`
  - this strongly suggests the visible registry low field is already on the same selector/remap axis as the live triple path
- `+0x630` semantics: likely state/cache layer, not final raw-remap-id proof yet

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
