# Flow Index

## Root

- `full_dynamic_geometry_flow.md`
  - dynamic lead / hitpoint / velocity stabilization main flow
- `runtime_geometry_checklist.md`
  - runtime reverse checklist
- `ghidra_geometry_checklist.md`
  - ghidra reverse checklist
- `ghidra_geometry_findings.md`
  - ghidra findings log
- `dynamic_hitpoint_mapping_report.md`
  - dynamic hitpoint runtime mapping report

## Grouped Folders

- `unit_family/`
  - unit class / icon / family-resolution issues
  - current practical resolution uses dynamic `unit_key/profile_path` pattern matching where runtime class fields are too coarse

## Notes

- New flows should go into a grouped subfolder when they are specific to one subsystem.
- Keep root-level files only for cross-cutting reports/checklists that touch multiple subsystems.
