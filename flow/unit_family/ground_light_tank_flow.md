# Ground Light Tank Flow

## Problem

- Current runtime family resolver often receives only `exp_tank`.
- In that case the code falls back to `GROUND_MEDIUM_TANK`.
- Result:
  - light tanks are rendered as medium tanks
  - no dedicated `LT` class label/icon path exists unless a stronger token is present

## Current Runtime Path

1. Read DNA / profile:
   - `short_name`
   - `name_key`
   - `family`
   - `profile tag/path`
2. Resolve family in `_resolve_unit_family_enum(...)`
3. Convert family enum into:
   - class icon shape
   - debug label
   - ground/air branch decisions

## Current Code Status

- Added `UNIT_FAMILY_GROUND_LIGHT_TANK`
- Added explicit resolver support for:
  - `exp_light_tank`
  - `exp_tank_light`
  - token matches:
    - `light_tank`
    - `light tank`
- Added:
  - `LT` debug label
  - dedicated light-tank icon shape
  - ground-family membership for branch resolution

## Current Limitation

- Many vehicles still expose only `exp_tank`, not `exp_light_tank`.
- So explicit token support alone is not enough to classify all light tanks.
- Real missing discriminator is likely one of:
  - `class_id`
  - richer profile tag/path token
  - a runtime class pointer not yet used by overlay
  - external metadata keyed by `unit_key`

## Next Reverse Targets

1. Collect samples for vehicles known to be light tanks.
2. Compare:
   - `dna["class_id"]`
   - `dna["family"]`
   - `profile["tag"]`
   - `profile["path"]`
   - `unit_key`
3. Find stable discriminator that separates:
   - light tank
   - medium tank
   while both still report `exp_tank`

## Tooling

- Use [unit_class_type_compare_dumper.py](/mnt/ntfs-p3/My%20Projects/Python/ebpf_wt/tools/sub/unit_class_type_compare_dumper.py)
  - dumps:
    - DNA fields
    - profile tag/path/unit_key
    - raw info pointers / strings
    - `class_id`
    - current resolved family enum/label
    - token flags for `light/heavy/td/spaa/tank`
  - intended to build a future `class_id -> unit family` map

## Live Findings: 2026-04-26

Sample set from runtime compare dump:

- `Pz.II C`
  - `family=exp_tank`
  - `class_id=1`
  - user-expected class: light tank
- `Pz.IV C`
  - `family=exp_tank`
  - `class_id=1`
  - user-expected class: medium tank
- `PT-76B`
  - `family=exp_tank`
  - `class_id=3`
  - user-expected class: light tank
- `Panther D`
  - `family=exp_tank`
  - `class_id=3`
  - user-expected class: medium tank

Implication:

- `class_id` alone is **not sufficient** to separate light vs medium.
- `family=exp_tank` is also too coarse.
- Current resolver fallback `exp_tank -> MT` explains why light tanks are being lost.

Current conclusion:

- A robust light-tank classifier will need a richer discriminator than:
  - `family`
  - `profile tag`
  - `class_id`
- Next candidates to inspect:
  - `unit_key` patterns
  - profile path grouping
  - datamined vehicle metadata outside runtime family/class fields
  - `unit_ptr + 0x98` candidate from `offsets/ref.txt`

## Runtime Findings That Matter

- `class_id` alone is **not sufficient** to separate light vs medium.
- `unit_ptr + 0x98` is also **not useful** in the sampled build/runtime state.
- `unit_key` and profile path are the first runtime fields that stay:
  - stable
  - human-auditable
  - specific enough to separate `Pz.II C` from `Pz.IV C`

## Active Resolution Path

### V1: Pragmatic Pattern Resolver

- Add pattern-based matching inside `_resolve_unit_family_enum(...)`
- Use runtime `unit_key` / `profile_path` / `name_key` tokens already present in memory
- Return explicit family code before generic `exp_tank -> MT` fallback
- Current pragmatic targets include patterns such as:
  - `pt_76`
  - `pzkpfw_ii`
  - `panzerjager`
  - `sdkfz_6_2`
  - selected heavy-tank markers like `tiger_ii`, `kv_`, `is_`

Resolver order now is:

1. pragmatic `unit_key/profile_path/name_key` pattern match
2. explicit runtime family tokens
3. generic fallback logic

This is the current production path because it stays dynamic at runtime and avoids a static per-vehicle table.

### V2: Expand Pattern Coverage

- Keep using compare dump to collect more `unit_key/profile_path -> true class type` pairs
- Extend pattern groups as evidence grows
- Use runtime compare dump as validation, not as primary classifier

### V3: Replace Pattern Heuristics With Better Metadata If Found

- If a richer metadata source is found later:
  - datamined blk role/class
  - stronger runtime class pointer
  - reliable structured tag
- then replace part of the pattern heuristics with generated mapping

## Current Pattern Seeds

Current known-good examples for the first pragmatic rules:

- `germ_pzkpfw_II_ausf_C` -> token `pzkpfw_ii` -> `LT`
- `ussr_pt_76b` -> token `pt_76` -> `LT`
- `germ_panzerjager_tiger_P_ferdinand` -> token `panzerjager` -> `TD`
- `germ_panzerjager_tiger` -> token `panzerjager` -> `TD`
- `germ_sdkfz_6_2_flak36` -> token `sdkfz_6_2` -> `AA`
- `germ_pzkpfw_VI_ausf_b_tiger_IIh` -> token `tiger_ii` -> `HT`

## Summary

- We tried `family`.
- We tried `class_id`.
- We tried `unit_ptr + 0x98`.
- The practical discriminator that currently works best is runtime token/pattern matching on `unit_key` and `profile_path`.

So the class-type flow is now:

- runtime evidence collection
- human-confirmed ground truth
- pragmatic pattern layer on `unit_key/profile_path`
- generic fallback only when no override exists
