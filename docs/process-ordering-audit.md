# Ruida process-ordering audit

How a Rayforge document becomes a Ruida process, and where that
translation loses the operator's intent. Companion to
`MOTION_AUDIT.md`, which covers interactive motion; this one covers
the job stream: parts, their settings, the order they are declared
in, and the two places a job leaves the application (`send_job` and
`.rd` export).

## Reference-material caveat

The only in-repo ground truth for the job stream is
`tests/machine/driver/ruida/fixtures/rdworks_reference.rd`, a
single-part contour job written by RDWorks for this controller. It
was decoded for this audit (swizzle magic `0x88`, commands split on
the MSB) and every byte quoted below comes from it.

Two fixtures that would settle the remaining unknowns do **not**
exist in this repository:

- `fixtures/rdworks_scan.rd` - a scan (raster) part, which would
  give the `CA 41 <part> <mode>` mode byte and the body
  `CA 01 <mode>` byte for a scan.
- `fixtures/rdworks_scan_plus_cut.rd` - a scan part followed by a
  cut part, which would give the two-part ordering and block
  layout.

Everything this audit says about the **mode byte** is therefore
unverified. The reference file's single contour part carries
`CA 41 00 00` and `CA 01 00`, so mode `0` is ground truth for a cut
part and is what the encoder emits for every part until a scan
fixture exists. See PRO-09.

## Severity

| Severity | Meaning |
| --- | --- |
| SAFETY | The machine cuts at settings the operator did not choose. |
| BROKEN | A feature does not work at all. |
| DEGRADED | Works, but not the way the operator was told. |
| SMELL | Correct today, fragile tomorrow. |

## Index

| Id | Severity | Summary |
| --- | --- | --- |
| PRO-01 | SAFETY | The pre-scan latches the first settings after a marker and discards every later group, so geometry cut under the second group runs at the first group's speed and power. |
| PRO-02 | SAFETY | Part boundaries are decided twice, by two independent walks, with only a uid to notice when they disagree. |
| PRO-03 | DEGRADED | A marker with no geometry still claims a part index and inflates `CA 22`. |
| PRO-04 | DEGRADED | `CA 41` is emitted only when `follow_reference` is on, so the part's work-mode declaration vanishes with the reference replay. |
| PRO-05 | DEGRADED | Travel speed is parsed, stored and dropped: no `C9 03` is ever emitted, so every part's rapids run at whatever the previous job left on the controller. |
| PRO-06 | BROKEN | `.rd` export reads `driver_data` off the pipeline's `EncodedOutput`, which the pipeline strips, so the export always fails with "does not produce Ruida job data". |
| PRO-07 | DEGRADED | The job is always anchored at the bounding box's minimum corner; the operator cannot say which corner of the job the head is standing on. |
| PRO-08 | DEGRADED | `home()` stops at the limit switches and parks nowhere, so the head's resting corner is a property of the machine's wiring rather than of the application. |
| PRO-09 | SMELL | The `CA 41` / `CA 01` mode byte is hard-coded `0` with no fixture that shows what a scan part uses. |

## Findings

### PRO-01 - The pre-scan latches the first settings after a marker and discards every later group

- **Severity:** SAFETY
- **Location:** `rayforge/machine/driver/ruida/ruida_encoder.py`, `_collect_job_info`
- **Status:** FIXED (commit A)

**Evidence**

```python
elif ct == CommandType.SET_FEED_RATE:
    cur_speed = ops.rate(i)
    if current is not None and not current["explicit_speed"]:
        current["speed"] = cur_speed
        current["explicit_speed"] = True
```

The same `explicit_*` guard exists for power and for air assist.

**Expected**

Every distinct settings combination the job asks for reaches the
controller as its own part, whatever marker it arrived under.

**Actual**

The first `SET_FEED_RATE` after a `LAYER_START` wins and every later
one inside that marker is dropped on the floor - silently, because
the guard is a plain boolean with no else branch. The geometry that
follows the discarded group is still emitted, so it is cut at the
first group's speed and power. This is exactly how an engrave step
followed by a cut step ran the cut outline at engrave speed and
engrave power: the pipeline handed the encoder one marker holding
both steps.

`0ae8a33` fixed the pipeline so that a step is its own marker group,
which removes today's reproduction. It does not remove the latch:
the encoder still cannot survive two settings groups inside one
marker, and it is the encoder that decides what the controller is
told.

**Fix**

The pre-scan stops latching. Within a part, a settings change that
lands before any cut updates that part in place - the last value
before the first cut is the part's value. A settings change that
lands *after* geometry has been cut under the current part opens a
new part entry, carrying the enclosing marker's uid so the
document-side lookups (min power in particular) still resolve.

**Test strategy**

Encode a real two-step document through the production path
(`IntentBuilder` -> `execute_stages` -> `RuidaEncoder`, which is what
`RuidaDriver.run` does via `build_rd_bytes`) and assert two `CA 02`
parts, `CA 22 == 1`, both `C9 04` header speeds and both power pairs
bound to the right part index, and that the cut geometry sits inside
the part that declares the cut speed. Disable the first step and
assert exactly one part, carrying the *second* step's settings.

---

### PRO-02 - Part boundaries are decided twice, by two independent walks

- **Severity:** SAFETY
- **Location:** `ruida_encoder.py`, `_collect_job_info` and `_handle_layer_start`
- **Status:** FIXED (commit A)

**Evidence**

```python
def _handle_layer_start(self, ops, idx, binary, text):
    uid = ops.layer_uid(idx)
    self._part += 1
    part = self._part
    layer = self._settings_for(uid, part)
```

The header is emitted from the pre-scan's list; the body increments
its own counter over the same ops. Nothing but the uid comparison in
`_settings_for` ties the two together, and when they disagree the
encoder falls back to *the index it already had*:

```python
self._warn_unresolved_uid(uid, f"part {part} settings")
if part < len(self._layers):
    return self._layers[part]
```

**Expected**

One site decides where a part begins. The body cannot disagree with
the header, because it never forms an opinion.

**Actual**

Two walks with two sets of rules. Today they agree only because both
are driven by `LAYER_START` and nothing else. The moment either
learns another boundary rule - which PRO-01's fix requires - they
diverge, and the divergence binds geometry to another part's
settings while emitting a warning nobody reads at cut time.

**Fix**

The pre-scan becomes the only site that decides part boundaries. It
returns, alongside the part list, the map from *ops index* to the
part that opens there. The body walk consults that map and does not
count. A body block is emitted at exactly the indices the pre-scan
nominated, from exactly the settings the pre-scan resolved.

**Test strategy**

The two-step production-path test above binds geometry to blocks
rather than only checking values: the raster rows (which emit `C7`
immediate power) must sit in the block that declares the engrave
speed, and the cut moves in the block that declares the cut speed.

---

### PRO-03 - A marker with no geometry still claims a part index

- **Severity:** DEGRADED
- **Location:** `ruida_encoder.py`, `_collect_job_info`
- **Status:** FIXED (commit A)

**Expected**

`CA 22` names the last part that has something to cut.

**Actual**

Every `LAYER_START` appends an entry, geometry or not. An empty
marker gets a header block, a body block, a part index, and a seat
in the `CA 22` count - a part the controller will select, set up,
and find nothing in.

**Fix**

Parts with no motion at all are dropped after the walk, and the
index map is renumbered with them. A job that ends up with no parts
still declares one, so the prologue keeps its shape.

---

### PRO-04 - `CA 41` is gated behind `follow_reference`

- **Severity:** DEGRADED
- **Location:** `ruida_encoder.py`, `_handle_job_start`
- **Status:** FIXED (commit A)

**Evidence**

```python
binary.append(b"\xca\x06" + part_b + z5)
if self.follow_reference:
    binary.append(b"\xca\x41" + part_b + b"\x00")
```

**Expected**

`CA 41` declares the part's work mode. That is a property of the
job, not of the decision to replay the reference file's unexplained
constants.

**Actual**

It sits in the same bucket as `C6 65 <part> 3D` and `E7 61/62`,
whose payloads really are copied verbatim because their meaning is
unknown. `CA 41`'s shape is known - part index, then mode - so
withholding it is a behaviour change disguised as a fidelity switch.

**Fix**

Emit `CA 41 <part> <mode>` unconditionally, from the part's own
mode.

---

### PRO-05 - Travel speed is parsed, stored, and dropped

- **Severity:** DEGRADED
- **Location:** `ruida_encoder.py`, `_handle_set_travel_speed`
- **Status:** FIXED (commit A)

**Evidence**

```python
speed = ops.rate(idx)
self.travel_speed = speed
text.append(f"TRAVEL_SPEED {speed:.1f}")
```

**Expected**

A step that says how fast the head should traverse between cuts says
so on the wire.

**Actual**

Nothing is emitted. The comment justifies it by the reference file,
which contains no `C9 03` - but the reference file is a single
default-speed contour, so its silence is not evidence. The
controller keeps whatever axis speed the previous job left in it, so
a job's rapids are a property of the job before it.

`C9 03` is decoded in-repo as "Axis Speed", opcode plus a 5-byte
`encode35` micrometres-per-second value, seven bytes total
(`ruida_server.py::_handle_c9_command`), and `estimate_packet_length`
already sizes it correctly, so it chunks and acks like every other
command.

**Fix**

Each part records the travel speed in force when it opens and emits
`C9 03` in its body block, right after its `C9 02`. The value goes
through `_speed_to_um_s`, the encoder's single mm/min -> um/s site,
so it obeys the same invariant every other speed does. A part with
no travel speed emits nothing.

---

### PRO-06 - `.rd` export reads data the pipeline strips

- **Severity:** BROKEN
- **Location:** `rayforge/doceditor/file_cmd.py`, `export_rd_to_path`
- **Status:** FIXED (commit B)

**Evidence**

```python
encoded = artifact.encoded_output
commands = encoded.driver_data.get("commands") if encoded else None
if not commands:
    raise ValueError(
        "The current machine does not produce Ruida job data."
    )
```

And, in the driver, the reason that can never succeed:

```python
# The pipeline rebuilds EncodedOutput from
# EncodeOutput.MachineCode, which carries only text and op_map,
# so encoded.driver_data never reaches the driver. Build the
# blob from ops here; encoded serves UI progress mapping only.
blob = build_rd_bytes(ops, self._machine, doc)
```

**Expected**

Exporting a `.rd` writes the bytes the machine would have received.

**Actual**

`driver_data` is always empty by the time the artifact reaches the
UI, so the export always raises, and the message blames the
machine's capabilities for a plumbing fault. `run()` already worked
around this; the export never got the same treatment.

**Fix**

Route the export through the identical path `run()` uses:
`build_rd_bytes(artifact.ops, machine, doc)` on the production ops,
via the existing `export_rd` helper. The capability check goes with
it - there is nothing left for it to check.

**Test strategy**

Drive `export_rd_to_path` with a stubbed artifact and assert the
written file equals `build_rd_bytes` of the same ops, which
`test_export_writes_the_same_blob_as_send` already ties to the
`send_job` blob.

---

### PRO-07 - The job is always anchored at the bounding box minimum

- **Severity:** DEGRADED
- **Location:** `ruida_encoder.py`, `_handle_job_start`; `ruida_driver.py`, `trace_frame`
- **Status:** FIXED (commit C)

**Evidence**

```python
rect = ops.rect()
self.origin_um = (self._mm_to_um(rect[0]), self._mm_to_um(rect[1]))
```

**Expected**

The operator parks the head on a corner of the stock and tells the
application *which* corner that is. The job lands accordingly.

**Actual**

Job-local `(0, 0)` is always the bounding box's minimum corner, so
the head is always assumed to be standing on that one corner. Every
other placement means jogging to a corner the operator has to
compute.

**Fix**

The machine profile carries a start corner (TL, TR, BL, BR; default
TL). At job build the job-local geometry is translated so the
selected corner of the bounding box lands at `(0, 0)`: TL no shift,
TR `x -= w`, BL `y -= h`, BR both. One helper computes that offset
and all three consumers - jobs, Go Scale and Cut Scale - call it
with the same width and height, taken from `ops.rect()`, so the
traced outline and the cut outline cannot drift apart.

The corner names are the machine's own axis convention, not a second
mapping: job-local space already inherits the profile's origin and
reverse-axis settings, so no direction is re-derived here.

---

### PRO-08 - `home()` parks the head nowhere

- **Severity:** DEGRADED
- **Location:** `ruida_driver.py`, `home`
- **Status:** FIXED (commit D)

**What Home sends today**

1. `C9 02` at the profile's max travel speed
   (`_set_max_travel_speed`).
2. `D8 2A` Home XY, when the request covers X or Y.
3. `D8 2C` Home Z, when it covers Z.
4. `_wait_for_status_idle("home")`, polling `0x0400` until the
   job-running bit clears.
5. In `finally`: the response timeout is restored, `_jog_busy` is
   released, and `_last_known_pos` is dropped (MOT-23).

**Why the head lands top-right**

`D8 2A` carries no coordinates. It is a controller-side seek to the
X and Y limit switches, and where it stops is where the switches
are. Nothing between `home()` and the wire touches
`reverse_x_axis`, `reverse_y_axis`, `origin`, `_to_controller` or
`_axis_range` - the byte is the same for every profile. The head
lands top-right because this machine's switches are top-right, and
that is not something the application can fix by changing a mapping.
(For contrast, the in-repo simulator implements `D8 2A` as
`s.x = 0; s.y = 0`, which is why the current tests can assert a
zero.)

So this is a switch-location fact, not a coordinate-mapping error,
and the fix is to add a park rather than to change a mapping.

**Expected**

Home ends with the head somewhere the operator chose, at a speed the
operator can see, and it can be stopped like every other motion.

**Fix**

Physical home first - `D8 2A` behind the busy interlock, on the long
homing timeout, with the cached position resynced from the
controller once the status bit clears. Then one rapid to the
machine's top-left bed corner at the *current panel jog speed*,
through `_set_travel_speed`, the driver's single mm/min -> um/s
site, and `_jog_move_to`, its single absolute-target site. The park
holds the busy interlock and watches the frame epoch, so `cancel()`
and the Stop button abandon it exactly as they abandon a Go Scale.

Which end of each axis "top-left" is comes from the profile's own
`calculate_jog` direction convention plus `_axis_range`, so no
second mapping site is introduced. The corner is inset by
`JOG_LIMIT_MARGIN_MM`, the same margin a held jog stops at, so the
park never drives into a hard stop.

A Z-only home does not park: the park is the XY home's behaviour.

---

### PRO-09 - The `CA 41` / `CA 01` mode byte is hard-coded

- **Severity:** SMELL
- **Location:** `ruida_encoder.py`
- **Status:** OPEN - needs a fixture

**Evidence**

The reference file's only part is a contour cut, and it carries
`CA 41 00 00` in the header and `CA 01 00` in the body. Mode `0` is
therefore ground truth for a cut part and for nothing else.

**Actual**

Every part is emitted with mode `0`, scan parts included. Whether a
raster part should declare a different mode is unknown: no fixture
in this repository contains one.

**What would close it**

`fixtures/rdworks_scan.rd` (a scan part) gives the header mode byte
and the body `CA 01` byte directly.
`fixtures/rdworks_scan_plus_cut.rd` additionally pins the two-part
ordering. Until one of them exists the mode stays `0`, carried as a
per-part field and logged per part, so the day a fixture arrives the
value has exactly one place to change.

---

## Summary

| Severity | Status | Count | Findings |
| --- | --- | --- | --- |
| SAFETY | Fixed | 2 | PRO-01, PRO-02 |
| BROKEN | Fixed | 1 | PRO-06 |
| DEGRADED | Fixed | 5 | PRO-03, PRO-04, PRO-05, PRO-07, PRO-08 |
| SMELL | Needs a fixture | 1 | PRO-09 |

## Invariants after this audit

- **One part per settings combination, decided once.** The job
  pre-scan is the only site that decides where a part begins; the
  body walk emits blocks at the indices the pre-scan nominated and
  never counts for itself. A part's settings are the last values
  seen before its first cut.
- **Every part states itself in full.** A part's body block restates
  its mode, index, laser, air assist, cut speed, travel speed and
  both power pairs before any geometry, and every `CA 02` switch
  clears the encoder's emission memory, so no setting can be
  suppressed by what the previous part emitted and the first move
  after a switch is absolute.
- **One authoritative unit conversion per value path.**
  `RuidaEncoder._speed_to_um_s` is the only place a job speed - cut
  or travel - becomes um/s, and `RuidaDriver._set_travel_speed` is
  the only place an interactive speed does.
- **One axis-direction convention.** Job-local placement, Go Scale
  and Cut Scale share one start-corner helper, and the driver's park
  target is derived from the profile's existing `calculate_jog`
  convention rather than from a second reading of the reverse flags.
- **What leaves the application is what the machine gets.** The
  `.rd` export and `send_job` build their bytes from the same call
  on the same ops.
- **Anything the app starts, the app can stop.** The home park is
  behind the busy interlock and the frame epoch, like every other
  motion (MOTION_AUDIT.md).
