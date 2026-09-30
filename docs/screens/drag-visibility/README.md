# Nothing vanishes while the canvas is worked

Manual check for the drag/pan visibility fixes, captured 2026-09-30
from the app at 1440x900 with the base images hidden (show_workpieces
off, the setting under which the scene used to vanish).

- `idle-light.png`: two copies of contour.ryp's workpiece, one selected.
- `mid-drag-light.png`: the selected copy is being dragged by
  (60, -40) px. Both ops outlines are drawn: the moved one inside its
  dashed frame, the other where it was.
- `mid-pan-light.png`: a middle-drag pan of (40, 25) px is in
  progress; every shape stays drawn, shifted with the view.
