# Object snapping, mid-drag

Captured 2026-09-30 by `scripts/screenshot/smart_snap.py` from the app
at 1440x900 (light theme, an isolated config with a 1400x900 mm bed,
zoom 3.5). The larger shape is contour.ryp's workpiece; the smaller,
selected one is a 60 % copy being dragged. Each drag would land 0.6 mm
off a line unsnapped, clear of every line on the other axis, so each
capture holds exactly one snap and one guide.

- `edge.png`: the copy's left edge snapped to the other shape's left
  edge; the guide runs along it from the copy's box to the other's.
- `center.png`: the copy's centre snapped to the other shape's centre.
- `bed-edge.png`: the copy's left edge snapped to the bed's; the guide
  runs the bed's full height over its edge line.
