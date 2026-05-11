# Full Dynamic Geometry Flow

Purpose:
- Replace per-vehicle vertical baseline lookup with geometry-driven calculation from game data.
- Reduce manual calibration to residual fine-tune only.

## Goal

Compute final hitpoint from:
- `my gun origin`
- `my sight origin`
- `my local axes`
- `target body/turret bbox or target hit bone`
- `projectile profile`
- `camera/view projection`

Target result:
1. Build a world-space aimpoint from target geometry.
2. Apply projectile ballistics.
3. Apply sight-to-gun parallax from my vehicle geometry.
4. Project final point to screen.

## Required Data

### My Vehicle
- `my_pos`
- `my_rot`
- `my local axes`
- `my gun origin`
- `my sight origin`
- optional:
  - `my body bbox`
  - `my turret bbox`
  - `my barrel base / tip`

### Target Vehicle
- `target_pos`
- `target_rot`
- `target body-only bbox`
- `target turret-only bbox`
- or:
  - preferred hit bone / weakspot transform

### Ballistics
- projectile speed
- caliber
- mass
- drag / cx
- zeroing state

### Projection
- active camera position
- active view matrix
- world-to-screen

## Current Gaps

Still missing for true full-dynamic:
- confirmed `gunner sight / optics mount` as vehicle-local transform
- target body/turret-only geometry that excludes cannon inflation
- target weakspot/preferred hitpoint geometry

## Current Best Candidate Sources

### My Gun Origin
- existing `weapon/barrel` probe path
- barrel base/tip local/world coordinates

### My Sight Origin
- first-person `local_camera -> camera_position`
- use only when confirmed first-person/gunner view
- better future path:
  - optics mount / gunner sight transform
  - damage-model / named part / bone path

### My Local Axes
- existing `my_rot`
- existing helpers that derive local axes from rotation matrix

### Target Geometry
- current unit bbox path is usable as fallback
- better future path:
  - body-only bbox
  - turret-only bbox
  - named hit bone / damage-model transform

## Derivation Flow

### Phase 1: My Vehicle Geometry
1. Resolve `my_pos`
2. Resolve `my_rot`
3. Resolve `my gun origin`
4. Resolve `my sight origin`
5. Convert `(sight - gun)` into local-space deltas:
   - forward
   - up
   - lateral

Output:
- `my_parallax_local`

### Phase 2: Target Aim Geometry
1. Resolve target body/turret geometry
2. Pick target aimpoint in local target space
3. Transform target local aimpoint into world space

Output:
- `target_world_aimpoint`

Fallback if missing:
- use body/turret center from bbox

### Phase 3: Ballistic Solve
1. Use `target_world_aimpoint`
2. Solve travel time / drop
3. Apply my velocity compensation
4. Apply target velocity compensation if target is moving

Output:
- `predicted_world_impact`

### Phase 4: Parallax Solve
1. Convert `my_parallax_local` into world offset using my local axes
2. Apply sight-to-gun correction to predicted impact

Output:
- `world_impact_with_parallax`

### Phase 5: Screen Projection
1. Project `world_impact_with_parallax`
2. Render leadmark / hitpoint
3. Keep manual `vertical_correction` only as residual override

## Formula Sketch

### Local to World Parallax
```text
parallax_world =
    local_forward * my_axis_forward +
    local_up      * my_axis_up +
    local_left    * my_axis_left
```

### Final Aim
```text
target_world_aimpoint
  -> ballistic solve
  -> predicted_world_impact
  -> predicted_world_impact + parallax_world
  -> project to screen
```

## Ghidra Work Items

### My Sight / Optics
- find optics / gunner sight transform
- find vehicle-local camera mount if first-person changes object path
- verify whether optics object differs from active orbit camera

### Target Geometry
- find body-only bbox
- find turret-only bbox
- find named hit bone / weakspot transforms
- verify cannon is excluded from body bbox path

### Damage Model / Bones
- inspect model transform arrays
- inspect named part records
- map names to transform indices

## Runtime Implementation Plan

### V1
- Keep current vertical baseline config as fallback
- Add optional dynamic branch behind a flag
- Use:
  - current barrel origin
  - first-person sight estimate
  - current bbox target center

### V2
- Replace first-person sight estimate with true optics mount
- Replace target bbox center with body/turret geometry point

### V3
- Use dynamic path as primary
- Keep baseline config only as fallback/debug compare

## Validation Plan

For each my vehicle:
1. Test first-person untilted
2. Test first-person tilted-left
3. Test first-person tilted-right
4. Test near / mid / far distance
5. Compare:
   - dynamic path
   - baseline config fallback
   - residual manual correction needed

Success criteria:
- no per-vehicle table needed for primary path
- residual manual vertical correction stays small
- tilt no longer forces major retune

## Notes

- `camera_parallax` should become derived from geometry, not a main tuning knob.
- `vertical_correction` should remain a residual override, not the primary model.
- If true sight origin cannot be resolved, stay with mixed mode:
  - dynamic where geometry is trustworthy
  - config fallback where geometry is incomplete

### Velocity Jitter Findings

- Ground lead jitter propagated into air leadmark because solver subtracts `my_vel` for all targets.
- Root cause was not only ground smoothing; some ground fallback readers decoded vertical-only noise such as `(0, -0.61, 0)`.
- Applied fixes:
  - reject ground velocity candidates with near-zero planar `XZ` speed but large `Y` speed
  - use planar `XZ` magnitude for ground source selection
  - add ground sticky/hysteresis for `idle/move`
  - filter short-frame ground `pos_vel`
  - avoid `blended` mode when `pos_vel` is effectively zero
  - throttle repeated `VEL READ FAIL` / `VEL FALLBACK HIT` logs
  - score multiple valid ground specs and prefer `GROUND_PRIMARY` when planar behavior is stronger / cleaner than fallbacks
- Result after first pass: ground-induced leadmark jitter reduced by roughly `90%+` in live testing.

### Dead-State Ghost Filtering

- Some live sessions show unit-state glitches:
  - a dead unit can briefly report `state = alive` again while the player changes vehicle
  - a dead unit can stay logically "alive" forever after that player leaves the match
- A plain `dead_unit_latch = set(ptr)` is not sufficient for those cases because the runtime pointer alone does not prove a new vehicle/entity identity.
- Applied fix:
  - change dead latch from `set(unit_ptr)` to `dict(unit_ptr -> latched info_ptr)`
  - once a unit reports dead, keep it hidden until its `info_ptr` changes to a new valid identity
  - still clear latch automatically when the unit pointer disappears from the live unit list
- Expected effect:
  - no short false revive of a corpse during vehicle-switch transitions
  - no permanently visible dead ghost if the same dead entity keeps toggling/holding `alive` state incorrectly
- Limitation:
  - if the game itself keeps exporting a dead ghost as `alive` even after ESP restarts, history-based latch is not enough
  - that case requires a separate runtime discriminator from the current memory image, not from prior overlay history
- Tool added for that path:
  - `tools/sub/ghost_unit_runtime_compare_dumper.py`
  - purpose: compare live/ghost/dead candidates by `info_ptr`, `movement ptr`, `reload`, `bbox`, `velocity`, and raw state bytes

### Air Secondary / Bomb Path

- Added tool:
  - `tools/sub/air_secondary_weapon_dumper.py`
- Purpose:
  - dump active air-weapon bullet slots
  - scan plausible secondary weapon blocks around `my_unit` / `cgame`
  - surface bomb-like candidates with:
    - name candidates
    - mass candidates
    - caliber candidates
    - count candidates
    - per-slot bomb-like heuristic score
- Intended use:
  - identify bomb/secondary payload runtime path before building bomb CCIP against terrain/enemy-ground reference
- Current live findings on `mig-15bis_ish`:
  - `active_weapon` still resolves to the primary gun path, not the bomb store
  - the bomb/loadout preset anchor is at `my_unit + 0x7c0`
  - live anchor text:
    - `mig_15bis_ish_500_bombs`
  - the child object at anchor `+0x78` repeats embedded records that look like pylon/preset entries:
    - `driver_optics`
    - `blister4`
    - `blister5`
    - `blister6`
    - `Zone0`
    - `mig_15bis_ish_500_bombs`
  - this strongly suggests the bomb path is stored as a loadout/preset structure, not as a standard bullet-slot list
- Further live refinement:
  - anchor child `+0x230` behaves like an entry table with repeating records:
    - `ptr + codeA + codeB` on `0x10` stride
  - visible live entries include:
    - `ptr=0x3095aaa0 code=(4,4)`
    - `ptr=0x30959bc0 code=(5,5)`
    - `ptr=0x309599f0 code=(5,5)`
    - `ptr=0x30959d90 code=(4,4)`
    - `ptr=0x30959f60 code=(4,4)`
  - strongest bomb-bearing candidates so far:
    - `0x30959d90`
      - contains embedded names `driver_optics`, `blister4`, `blister5`
      - also carries the same `8 / 32 / 16 / 33 / 115 / 33` scalar pattern seen in the parent preset block
    - `0x30959f60`
      - contains repeated small ints including `1 / 2 / 1 / 2 / 2`
      - likely state/count-oriented rather than display-name oriented
  - stronger split after deeper probing:
    - `0x30959bc0 code=(5,5)` and `0x309599f0 code=(5,5)`
      - behave like a twin payload-profile pair
      - both contain repeated float rows with the same core shape:
        - about `[-100, 1, 35, 30, 30, 5, 300, 200]`
      - the duplication strongly suggests left/right bomb profiles rather than unique named pylons
    - `0x30959f60 code=(4,4)`
      - behaves like a state/count controller block
      - has repeated `2` values at `0x74`, `0xc4`, `0x114`, `0x118`
      - this is the strongest current candidate for the active payload count (`2 bombs`)
- Practical implication:
  - do not assume UI slot numbers `1..13` match runtime slot indices directly
  - first map the runtime pylon/preset records, then correlate them back to occupied UI slots
- Focused follow-up tool:
  - `tools/sub/bomb_runtime_probe.py`
  - purpose:
    - read only the CCIP-relevant runtime path
    - `preset root`
    - `entry table`
    - `twin payload profiles`
    - `count block candidates`
  - intended outcome:
    - avoid re-reading the larger exploratory dumper when the goal is runtime bomb state for CCIP

- Snapshot comparison result:
  - `bomb_runtime_probe` on state `2 bombs` vs `0 bombs` produced the same payload/count blocks
  - therefore the currently decoded objects are still mostly preset/runtime-structure, not direct live remaining-count state
  - next step requires a live diff watcher during the actual bomb-release event
- Added live diff tool:
  - `tools/sub/bomb_runtime_watch.py`
  - purpose: watch the confirmed loadout path in real time and log changed `u32/f32` fields while bombs are released

- Updated bomb runtime direction:
  - stop treating `2` as a reliable total-count field
  - current hypothesis is per-slot occupancy/state, e.g. `1+1` across two bomb slots rather than a single `2`
  - `bomb_runtime_probe` now reports slot-occupancy pair candidates from count blocks
  - `bomb_runtime_watch` now validates the preset anchor instead of trusting `unit+0x7c0` blindly

- Live watch result on stabilized child branches:
  - watcher narrowed to child branches like `0x40 / 0x48 / 0x210` to avoid unrelated animation-state noise
  - confirmed live transition on `mig_15bis_ish_500_bombs`:
    - `child_0x40 + 0x98 : 3 -> 5 -> 3`
  - interpretation:
    - this looks like a release/selection enum toggle, not a direct remaining-count field
    - useful as an event trigger candidate for bomb release timing
  - next follow-up:
    - inspect nearby offsets around `child_0x40 + 0x90..0xA8`
    - look for a companion field that changes once per release event and does not bounce back immediately

- Preset comparison update (`MiG-15bis ISh`):
  - `2x FAB-500`:
    - anchor text: `mig_15bis_ish_500_bombs`
    - exposed richer dynamic structures:
      - twin `code=(5,5)` payload-profile pair
      - `code=(4,4)` count/state-side blocks
  - `4x FAB-250`:
    - anchor text: `mig_15bis_ish_250_bombs`
    - current dynamic branch is different:
      - child `0x210` with inline strings like `weaponTurningSpeedMult`
      - child `0x40` / `0x48` exist but current `ptr_code_entries` are low-signal (`code=(1,0)`, `code=(37,0)`, etc.)
      - no `code=(5,5)` / `code=(4,4)` pair surfaced in this state
  - conclusion:
    - bomb runtime layout is preset-dependent, not only state-dependent
    - `250_bombs` does not currently expose the same rich payload/count signature as `500_bombs`
    - `500_bombs` remains the stronger reverse-engineering anchor for locating release/count state for future Bomb CCIP work

- HUD-side probe update:
  - `plane_hud_slots_probe.py` was reworked to find HUD root dynamically from topology instead of trusting old absolute `hud_offset`
  - result so far:
    - global-neighborhood scan still resolves false positives (code/data blobs) rather than a live HUD object
    - even after stricter scoring, candidate roots still expose invalid pointer-like garbage and no readable semantic HUD strings
  - conclusion:
    - the relative HUD field layout from `offsets/RAW/FUN_01d1fb30` is still valuable
    - but HUD root discovery via nearby global offsets is not reliable enough
    - next step should pivot to `get_cur_hud` chain / function-based root discovery from `offsets/Offsets_path`

- HUD chain-scan follow-up:
  - `plane_hud_slots_probe.py` was reworked again to walk pointer chains from `cgame`, `localplayer`, and old `hud_ref_*` roots
  - current result:
    - no credible HUD root candidate was found (`hud_ptr=0x0`, `score=-1`)
  - conclusion:
    - simple pointer-chain exploration from known globals is still insufficient
    - next step should be a focused chain dumper around `cgame/localplayer` references to surface stable subgraphs, then pin HUD-like branches from observed structure rather than broad scoring

- HUD chain graph dump update:
  - first run of `hud_chain_graph_dumper.py` with stale global root refs produced:
    - empty `[seeds]`
    - empty `[top-nodes]`
  - conclusion:
    - old absolute HUD/global refs are stale enough that even graph expansion cannot start from them
    - the dumper should seed from runtime-resolved objects instead:
      - `cgame_live`
      - `my_unit`
      - `my_unit_info`
      - `camera_ptr`
      - `weapon_ptr`
  - next step:
    - rerun the graph dumper after switching seeds to runtime-resolved roots
    - use the resulting graph to identify any HUD-adjacent branch with `bomb/weapon/slot/ccip/trigger` semantics

- HUD chain graph dump update (runtime seeds):
  - after switching to runtime-resolved seeds, graph expansion works
  - live seeds now include:
    - `cgame_live`
    - `my_unit`
    - `my_unit_info`
    - `camera_ptr`
    - `camera_nested`
    - `weapon_ptr`
  - strongest graph hits are not a HUD root yet, but reflection-like field-name branches under `my_unit`
    - `my_unit + 0xae8 -> bombDelayExplosion`
    - `my_unit + 0xb38 -> rocketFuseDist`
    - `my_unit + 0xb60 -> torpedoDiveDepth`
    - `my_unit + 0x7c0 -> mig_15bis_ish_250_bombs`
    - later nearby names include `supportPlanesCount`, `supportPlaneCatapultsFuseMask`, `visualReloadProgress`
  - conclusion:
    - current graph is surfacing unit-side reflection/descriptor tables more reliably than a direct HUD object
    - this is still valuable because it gives semantically named field neighborhoods for bombs/support weapon systems
  - next step:
    - pivot from broad HUD-root search to a targeted `my_unit` reflection probe around these named offsets
    - use the descriptor neighborhood to correlate field-name pointers with nearby live values/state transitions

- `my_unit` reflection probe plan:
  - added `tools/sub/my_unit_bomb_reflection_probe.py`
  - target scan window:
    - `my_unit + 0x7c0 .. 0xb80`
  - probe goals:
    - find field-name pointers with bomb/support semantics
    - summarize pointed descriptor objects (`inline_strings`, `int_hits`, `float_hits`)
    - correlate each named field with nearby live scalar/pointer neighbors in the owning `my_unit` block
  - intended use:
    - compare across presets (`250_bombs` vs `500_bombs`)
    - compare before/after bomb release
    - identify whether the named reflection neighborhood exposes stable count/state fields more directly than current preset child watchers

- `my_unit` reflection probe update (`MiG-15bis ISh`, `250_bombs`):
  - strongest named fields in `my_unit + 0x7c0 .. 0xb80` are:
    - `0x7c0 -> mig_15bis_ish_250_bombs`
    - `0xa10 -> supportPlanesCount`
    - `0xa38 -> supportPlaneCatapultsFuseMask`
    - `0xa98 -> visualReloadProgress`
    - `0xae8 -> bombDelayExplosion`
    - `0xb10 -> delayWithFlightTime`
    - `0xb38 -> rocketFuseDist`
    - `0xb60 -> torpedoDiveDepth`
  - current observation:
    - this neighborhood is semantically correct, but still descriptor-heavy
    - nearby scalars are mostly stable low floats (`~2.5057`, `1.5`, `1.0`) rather than obvious live remaining-count fields
    - no direct `250 / 97 / 79 / 114` payload metadata surfaced as clean live scalars in this neighborhood
  - next step:
    - added `tools/sub/my_unit_bomb_reflection_watch.py`
    - watch focused offsets in `0x9f0 .. 0xb80` during:
      - bomb release
      - preset change
    - goal:
      - determine whether this reflection neighborhood exposes event/state transitions more clearly than preset child watchers

- `my_unit` reflection watch update:
  - dropping a bomb does not trigger obvious per-drop changes in the reflection neighborhood
  - but dropping the **last** bomb triggered:
    - `my_unit + 0xad8 : 770965504 -> 770965506`
  - interpretation:
    - `0xad8` is more likely an `empty / has-payload-left` state bitfield or enum edge
    - it does **not** look like a direct remaining-count field
  - watcher was expanded to:
    - label `0xad8` as a payload-availability-side candidate
    - also monitor scalar changes inside the preset object pointed to by `my_unit + 0x7c0`
    - extend preset-object watch range from `0x10..0x140` to `0x10..0x240`
    - loosen preset change filtering so deeper low-delta count/state transitions can surface
  - next step:
    - rerun the reflection watcher and compare:
      - single drop with bombs still remaining
      - final drop to empty
    - check whether the preset object exposes `4 -> 3 -> 2 -> ...` style transitions even when the reflection block only exposes the final-empty edge

- Bomb profile resolver pivot:
  - requirement was reduced:
    - Bomb CCIP currently needs bomb-info/profile resolution
    - remaining-count state is not required for this step
  - chosen runtime key:
    - `my_unit + 0x7c0 -> preset identity`
  - implemented artifacts:
    - `config/bomb_profile_table.json`
    - `src/utils/bomb_profile.py`
    - `tools/sub/bomb_profile_probe.py`
    - `radar_overlay.py` hook that resolves the current bomb profile each frame for air units
  - seeded profiles:
    - `mig_15bis_ish_250_bombs`
      - `initial_count=4`
      - `bomb_mass=250`
      - `explosive_mass=97`
      - `armor_pen=79`
      - `explode_radius=6`
      - `fragment_radius=114`
    - `mig_15bis_ish_500_bombs`
      - `initial_count=2`
      - `bomb_mass=500`
      - `explosive_mass=201`
      - `armor_pen=88`
      - `explode_radius=9`
      - `fragment_radius=134`
  - conclusion:
    - current practical path for Bomb CCIP is:
      - resolve preset name from runtime
      - map preset name to bomb profile from config
    - this is materially more stable and useful right now than continuing to reverse direct count-state fields
