# Other objects stay visible while one is dragged

Manual check for commit "fix(canvas): the other objects stay visible
while one is dragged", captured 2026-09-29 from the app at 1440x900
with the base images hidden (show_workpieces off, the setting under
which the whole scene used to vanish during a drag).

- `idle-light.png`: two copies of contour.ryp's workpiece, one selected.
- `mid-drag-light.png`: the selected copy is being dragged by
  (60, -40) px. Its dashed frame has moved; the other copy's ops
  outline is still drawn where it was. The surface reported
  `ops_suppressed=False` overall, suppressed for the moving element
  only.
