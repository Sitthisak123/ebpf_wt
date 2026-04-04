# view_matrix_aim_match_dumper.py

Find the `matrix_off + projection_mode` combination that best matches the target you are aiming at.

## Purpose
- Help recover broken 3D ESP by ranking view-matrix candidates from live aim state.
- While you aim a target near the crosshair, the tool tests many matrix candidates in the same frame.
- It scores candidates by how close an enemy projects to screen center.
- It tries both:
  - axis order swaps (`xyz/xzy/...`)
  - axis sign flips (`+++`, `-++`, `+-+`, ...)

## Run
```bash
sudo venv/bin/python tools/view_matrix_aim_match_dumper.py
```

Target-specific run:
```bash
sudo venv/bin/python tools/view_matrix_aim_match_dumper.py --target "Sd.Kfz. 6/2"
```

Multi-step run:
```bash
sudo venv/bin/python tools/view_matrix_aim_match_dumper.py --target "Sd.Kfz. 6/2" --steps 3 --samples-per-step 5
```

Multi-step run with promotion threshold:
```bash
sudo venv/bin/python tools/view_matrix_aim_match_dumper.py --target "Sd.Kfz. 6/2" --steps 3 --samples-per-step 5 --promote-threshold 3
```

## Controls
- `F6`: capture current aim state
- `F10`: abort

## Multi-step scan
- Step 1: coarse scan over all `matrix_off + mode + sign` combos
- Step 2: keep only top-ranked combos and rescan
- Step 3: final rescan on the narrowest combo set
- Dump includes a `MULTISTEP` section with rankings per step

## Candidate persistence
- Each capture updates `config/view_matrix_candidate_persistence.json`
- The winning combo is tracked across multiple target captures
- A combo is promoted to `global_candidate` only after it wins at least `--promote-threshold` times
- This avoids promoting a single target-fit combo too early

## Output
- `dumps/view_matrix_aim_match_*.json`
- `dumps/view_matrix_aim_match_*.txt`
- `config/view_matrix_candidate_persistence.json`
- Separate rankings for:
  - `top_candidates`
  - `best_ground`
  - `best_air`

## What to look at
- `matrix_off`
- `projection_mode`
- `axis_signs`
- `best_enemy.label`
- `best_enemy.projection.center_dist`
- `best_ground.label`
- `best_air.label`
- `chosen.target_filter`
- `chosen.target_filter_applied`
- `chosen.final_combo_filter`
- `multistep`
- `candidate_persistence`

Lower `center_dist` means that candidate projects the aimed target closer to the actual crosshair center.
