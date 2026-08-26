# Motion subsystem audit

Systematic audit of the interactive-motion subsystem: everything that
makes the head move outside a job. Scope, verbatim from the brief:

- IN: `ruida_driver.py` (jog / move / home / go-scale / position /
  busy logic), `ruida_client.py` (interactive commands, response
  handling, locks, futures), `ui_gtk/machine/jog_widget.py` and its
  `machine_cmd` / controller plumbing, position polling and the
  `_last_known_pos` lifecycle.
- OUT: the job encoder, `build_rd_bytes`, `send_job` framing and the
  `.rd` format. Nothing below requires changing them.

Method: eight independent auditors, one per failure class, each
reading every in-scope path in full; every finding then re-judged by
an adversarial verifier that defaults to REFUTED and must point at
the code. 68 raw findings, 51 confirmed, 17 rejected as duplicates or
refuted (listed at the end so nothing is silently dropped).

## Reference-material caveat

The brief asks for every interactive byte to be diffed against
`docs/reference/rdcam_opcode_table.md`. **That file does not exist in
this repository** (there is no `docs/` tree at all). The only in-repo
authorities are:

- `rayforge/machine/driver/ruida/ruida_maps.py` - opcode name tables.
- `rayforge/machine/driver/ruida/ruida_server.py` - the simulator's
  own decoder, i.e. Rayforge's belief about the protocol, not the
  controller's behaviour.
- `tests/machine/driver/ruida/fixtures/rdworks_reference.rd` - a real
  RDWorks capture, which contains **zero `D9` commands**: it is a job
  stream, and jobs never use the interactive rapid.

So no interactive motion byte this driver emits is confirmed by
ground truth. That is itself a finding (MOT-47) and it is why several
entries below are marked NEEDS-HARDWARE rather than fixed blind.

## Severity

| Severity | Meaning |
| --- | --- |
| SAFETY | Head can move when it should not, cannot be stopped, or the laser can fire unexpectedly. |
| BROKEN | Intended behaviour does not happen at all. |
| DEGRADED | Works, but wrongly under some condition. |
| SMELL | Correctness-neutral: misleading name, dead code, duplication. |

## Index

| ID | Sev | Location | Finding |
| --- | --- | --- | --- |
| MOT-01 | SAFETY | `ruida_driver.py:577` | The STOP button does not stop a Go Scale — the trace pauses, then resumes and completes |
| MOT-02 | SAFETY | `ruida_driver.py:637` | Go Scale's Stop is erased by the trace it was meant to cancel |
| MOT-03 | SAFETY | `ruida_driver.py:809` | Same STOP bypass restarts a held jog: releasing one half of a diagonal after STOP re-issues motion |
| MOT-04 | SAFETY | `ruida_driver.py:822` | release_all_jog_keys clears trace_frame's borrowed _jog_busy: Go Scale stops, then resumes moving on its own |
| MOT-05 | SAFETY | `ruida_driver.py:833` | D8 01 is assumed to halt an interactive D9 10 rapid; the only in-repo decoder says it is a process stop that does not touch motion |
| MOT-06 | SAFETY | `ruida_driver.py:856` | A key-up can be overtaken by the key-down it is releasing: D9 run-to-limit lands after D8 01 |
| MOT-07 | SAFETY | `ruida_driver.py:879` | Held jog and step jog drive the head to the wrong end of the axis when reverse_x_axis / reverse_y_axis is set |
| MOT-08 | SAFETY | `ruida_driver.py:936` | A failed position read makes the jog origin (0, 0), turning a 10 mm jog into a full-bed traverse to the machine corner |
| MOT-09 | SAFETY | `jog_widget.py:754` | Stop during a Cut Scale calls cancel_frame(), which cannot stop a job — the laser keeps cutting |
| MOT-10 | BROKEN | `ruida_driver.py:548` | _wait_for_job_completion can never exit against an unresponsive controller, and it holds _suppress_polling so the connection loop's watchdog stays disarmed |
| MOT-11 | BROKEN | `ruida_driver.py:608` | home() is not tracked as busy and its completion wait is satisfied by any position reply, including the background poller's |
| MOT-12 | BROKEN | `ruida_driver.py:791` | jog_key_down leaks _jog_busy=True when _jog_to_limit finds an emptied key set, bricking every further jog until the panel is unmapped |
| MOT-13 | BROKEN | `ruida_driver.py:855` | Z jog deltas are silently discarded by both Ruida jog paths while the Z buttons stay enabled, and a Z hold leaks _jog_busy |
| MOT-14 | BROKEN | `ruida_driver.py:969` | _wait_for_jog_settled always computes a zero travel distance, so a step jog gives up after 1 s and the next step is measured from a mid-move position |
| MOT-15 | BROKEN | `jog_widget.py:257` | EventControllerMotion 'leave' never fires while the button is held, so dragging off does not stop the jog |
| MOT-16 | DEGRADED | `cmd.py:591` | Interactive commands are dispatched as unkeyed TaskManager coroutines, which gives them no ordering at all |
| MOT-17 | DEGRADED | `ruida_client.py:147` | A single 0xCC from any interactive command pops the head of _pending_job_acks and falsely acknowledges an outstanding job chunk |
| MOT-18 | DEGRADED | `ruida_client.py:165` | DA replies are attributed by address alone, so the connection loop's un-futured position poll answers an interactive read that had not been sent yet |
| MOT-19 | DEGRADED | `ruida_client.py:188` | _response_received is set by every decoded packet, so a bare transport ACK satisfies the connection loop's liveness wait and masks a controller that has stopped answering position reads |
| MOT-20 | DEGRADED | `ruida_client.py:906` | _pending_mem_reads holds one future per address: a second overlapping read of the same address orphans the first, and the orphan's timeout evicts a stranger's future |
| MOT-21 | DEGRADED | `ruida_driver.py:114` | Hold-jog speed defaults to 12000 mm/min (200 mm/s) and is never synced from the UI, so a press-and-hold runs 12x faster than the Jog Speed row shows |
| MOT-22 | DEGRADED | `ruida_driver.py:382` | The connection loop never sends a keepalive after the first, and its 1.0 s sleep makes POSITION_POLL_INTERVAL=0.5 unreachable |
| MOT-23 | DEGRADED | `ruida_driver.py:601` | home() zeroes the machine but never invalidates _last_known_pos; only X is corrected, by accident |
| MOT-24 | DEGRADED | `ruida_driver.py:638` | Go Scale outlines the box at the current head position, but the job (and Cut Scale) cut it at the REF0 anchor |
| MOT-25 | DEGRADED | `ruida_driver.py:653` | _suppress_polling is one boolean with two owners: trace_frame's exit re-enables position polling in the middle of a job upload |
| MOT-26 | DEGRADED | `ruida_driver.py:656` | Go Scale hard-codes 100 mm/s and is the only travel path that ignores the profile's max travel speed |
| MOT-27 | DEGRADED | `ruida_driver.py:809` | jog_key_up sets _jog_busy = True outside any try/finally; an error from _jog_to_limit leaks the flag and blocks every step jog |
| MOT-28 | DEGRADED | `ruida_driver.py:845` | _stop_jog_motion leaves the commanded bed-limit target cached when the resync read fails, so the next step jog runs to the far end of the bed |
| MOT-29 | DEGRADED | `ruida_driver.py:850` | _stop_jog_motion clears _jog_busy regardless of who owns it, dropping Go Scale's ignore interlock |
| MOT-30 | DEGRADED | `ruida_driver.py:951` | Go Scale corners are silently clamped to the bed, so the traced rectangle is not the job's size |
| MOT-31 | DEGRADED | `ruida_driver.py:1083` | _on_position_updated invents 0 for the axis it has not seen yet, so a jog landing between the X and Y position responses drives Y to the bed edge |
| MOT-32 | DEGRADED | `bottom_panel.py:461` | Jog speed round-trips base -> display -> int(mm/s) -> base, quantising to 60 mm/min steps and forcing a 60 mm/min floor at the bottom of the row's range |
| MOT-33 | DEGRADED | `jog_widget.py:62` | JogWidget.jog_speed defaults to 100 mm/s, six times the Jog Speed row's own default, so a click-jog runs at 6000 mm/min while the panel reads 1000 mm/min |
| MOT-34 | DEGRADED | `jog_widget.py:222` | Arrow-key jog has no key-release handler and no repeat guard; each repeat queues an unkeyed task |
| MOT-35 | DEGRADED | `jog_widget.py:374` | _update_button_sensitivity flips every jog button insensitive, which cancels an in-flight press |
| MOT-36 | DEGRADED | `jog_widget.py:551` | One hold timer for every arrow: a second press kills the first's hold, and any release kills whichever hold is armed |
| MOT-37 | DEGRADED | `jog_widget.py:571` | Held keys are released by (axis,sign) identity, not by the button that pressed them |
| MOT-38 | SMELL | `ruida_client.py:418` | D9 10 targets are documented as anchor-relative but fed absolute machine coordinates read back from 0x0421/0x0431 |
| MOT-39 | SMELL | `ruida_client.py:510` | The repo's only modelled motion-stop primitive, and the whole jog UDP channel, are dead code |
| MOT-40 | SMELL | `ruida_client.py:526` | D9 00 / D9 01 have three mutually contradictory documented meanings in-repo, and rapid_move_axis's axis numbering does not match its own callers |
| MOT-41 | SMELL | `ruida_client.py:713` | _build_jog_keyup always emits the negative-direction key-up opcode, so a positive-direction key would never be released |
| MOT-42 | SMELL | `ruida_client.py:738` | C9 02 has a second, contradictory encoder: _build_speed takes mm/s while set_travel_speed takes um/s |
| MOT-43 | SMELL | `ruida_driver.py:341` | _fetch_card_info is launched as an unreferenced, uncancelled task whose non-OSError exceptions are silently lost |
| MOT-44 | SMELL | `ruida_driver.py:384` | _connection_loop swallows CancelledError and returns normally, so cleanup()'s own except CancelledError is dead code |
| MOT-45 | SMELL | `ruida_driver.py:751` | clear_alarm is byte-identical to cancel — both send D8 01 Stop Process |
| MOT-46 | SMELL | `ruida_driver.py:944` | _jog_move_to's rationale comment claims D9 00/01 are absolute; both in-repo references say relative, and the 'absolute' jog_move_x/jog_move_y helpers are dead |
| MOT-47 | SMELL | `ruida_server.py:299` | No in-repo ground truth exists for any interactive opcode: the fixture contains zero D9 commands and the sole authority is Rayforge's own simulator |
| MOT-48 | SMELL | `ruida_transport.py:140` | The transport's single-byte fast path is behaviourally identical to the general path and omits 0xC6, implying a distinction that does not exist |
| MOT-49 | SMELL | `jog_widget.py:585` | _on_unmapped clears the root handler id even when it did not disconnect, and never remembers which root it connected to |
| MOT-50 | SMELL | `jog_widget.py:599` | The jog-speed debounce timeout is never cancelled on teardown |
| MOT-51 | SMELL | `jog_widget.py:652` | _on_connection_status_changed drops the held-key set without sending key-ups or the driver sweep |

---

## Findings

### MOT-01 - The STOP button does not stop a Go Scale — the trace pauses, then resumes and completes

- **Severity:** SAFETY
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:577`
- **Class:** Failure class 6 — stop semantics of the interactive-motion subsystem (Ruida)
- **Status:** FIXED 47a49acd0
- **Phase 2:** reproduced by `tests/machine/driver/ruida/test_motion_audit.py::TestStopReachesEveryMotion::test_cancel_aborts_a_running_go_scale`

**Evidence**

```python
    async def cancel(self) -> None:
        assert self._client
        await self._client.stop_process()
```

**Expected**

Pressing the big red STOP button (jog_widget._on_stop_clicked,
jog_widget.py:816 `self.machine_cmd.cancel_job(self.machine)`) while a Go
Scale is running should halt the head and abandon the remaining corners,
exactly like the Go Scale button's own Stop state (jog_widget.py:757
`self.machine_cmd.cancel_frame(self.machine)`).

**Actual**

cancel_job -> cmd.py:412 `lambda ctx: driver.cancel()` -> stop_process (D8
01) and NOTHING else. It never sets `_frame_cancelled`, never clears
`_jog_keys_down`, and never goes through `_stop_jog_motion`. trace_frame's
corner loop (ruida_driver.py:657-665) only ever consults `_frame_cancelled`:
for x_um, y_um in corners: if self._frame_cancelled: logger.info( "Go Scale
cancelled", extra=self._log_extra("USER_COMMAND"), ) return target = await
self._jog_move_to(x_um, y_um) await self._wait_for_frame_corner(*target) so
the loop is untouched by cancel(). The head stops mid-edge,
`_wait_for_frame_corner` never sees the corner reached, burns
FRAME_CORNER_TIMEOUT = 15.0 s, logs a warning at ruida_driver.py:707 and
RETURNS (it does not raise), and the very next iteration issues
`_jog_move_to` for the next corner — the head starts moving again. cancel-
job and trace-frame are separate task-manager keys running concurrently on
the same loop, so this is not a queuing artefact.

**Verification**

Confirmed: jog_widget._on_stop_clicked:813-816 -> cmd.cancel_job:408-413 ->
driver.cancel():577-579 = stop_process only. It never sets _frame_cancelled,
never clears _jog_keys_down and never goes through _stop_jog_motion, while
the corner loop (657-665) and _wait_for_frame_corner (697) consult
_frame_cancelled alone; _wait_for_frame_corner then burns
FRAME_CORNER_TIMEOUT=15 s, logs at 707-711 and RETURNS, so the next corner
is issued. cancel-job and trace-frame are separate task keys running
concurrently (cmd.py:412 vs 460). The head restarting after the emergency
STOP = SAFETY. Kept separate from the release_all_jog_keys finding:
different entry path and a different fix (cancel() must cancel the frame).

**Proposed fix**

Make cancel() the one universal stop for this driver: async def cancel(self)
-> None: assert self._client self._frame_cancelled = True
self._jog_keys_down.clear() await self._stop_jog_motion() # sends D8 01 and
resyncs position `_stop_jog_motion` already sends stop_process, so a running
job still gets its D8 01; a running trace now sees `_frame_cancelled` on the
next corner check and returns; a held jog can no longer be restarted by the
`if self._jog_keys_down:` branch of jog_key_up (ruida_driver.py:809-812).
Consider also clearing the widget's `_keys_down` from `_on_stop_clicked` so
the two views stay in sync.

**Test strategy**

`_ScaleClientSpy`-style stub client
(tests/machine/driver/ruida/test_ruida_scale_jobs.py:40). Set
`driver.FRAME_CORNER_TIMEOUT = 0.05` and `FRAME_POLL_INTERVAL = 0.01`. Wrap
`spy.rapid_move_xy` so that after the 2nd corner it (a) stops advancing
`spy.position` — simulating a head halted mid-edge — and (b) awaits
`driver.cancel()`. Then `await driver.trace_frame(100.0, 50.0)` and assert
`len(_corners(spy.commands)) == 2`. Today it emits all 5 corners. Add a
sibling test asserting `driver._frame_cancelled` is True immediately after
`await driver.cancel()`.

**Hardware check:** None needed for the control-flow defect. On hardware: start a Go Scale on a
large rectangle, press STOP mid-edge, and time how long until the head moves
again (expect ~15 s, then the rectangle finishes).

---

### MOT-02 - Go Scale's Stop is erased by the trace it was meant to cancel

- **Severity:** SAFETY
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:637`
- **Class:** Failure class 5 — queue / ignore semantics (input during motion must be IGNORED, never QUEUED, at every layer including the transport)
- **Status:** FIXED 47a49acd0
- **Phase 2:** reproduced by `tests/machine/driver/ruida/test_motion_audit.py::TestStopReachesEveryMotion::test_cancel_before_a_trace_is_not_erased`

**Evidence**

```python
        self._frame_cancelled = False
        start = await self._client.read_position()
```

**Expected**

Clicking Go Scale a second time (the button relabels to "Stop" the instant
the first click lands) must guarantee the head never starts, or stops
immediately. A cancel that arrives before motion begins is still a cancel.

**Actual**

MachineCmd.trace_frame queues _trace_frame, which first awaits
self._editor.pipeline.generate_job_artifact_async() (cmd.py:470) — a full
pipeline run — before ever calling driver.trace_frame(). The user's second
click runs MachineCmd.cancel_frame (cmd.py:579) as a separate, concurrently-
scheduled task; driver.cancel_frame() sets _frame_cancelled = True and,
because _jog_busy is still False (trace_frame has not run yet), sends no
stop. When the trace task finally reaches driver.trace_frame(), line 637
wipes the flag back to False and all five corners are traced. The user
pressed Stop and the head then started moving, with the button still reading
"Stop" until the run it was cancelling completes.

**Verification**

Traced: jog_widget._on_go_scale_clicked:754-764 flips the button to 'Stop'
synchronously before scheduling, and cmd._trace_frame awaits
generate_job_artifact_async (cmd.py:470) before ever calling
driver.trace_frame (481). A Stop during that window runs cmd.cancel_frame
(key='cancel-frame', a separate concurrent task) ->
driver.cancel_frame:678-680, which sets _frame_cancelled=True and sends
nothing because _jog_busy is still False. trace_frame:637 then
unconditionally resets `self._frame_cancelled = False` and traces all five
corners. The head starts moving after the user pressed Stop = SAFETY.

**Proposed fix**

Make cancellation an epoch, not a boolean the callee owns. Add
self._frame_epoch: int and have cancel_frame() bump it (self._frame_epoch +=
1) instead of setting a flag; trace_frame() captures `epoch =
self._frame_epoch` at entry and tests `if self._frame_epoch != epoch` at the
top of the corner loop and inside _wait_for_frame_corner, in place of
_frame_cancelled. Delete the `self._frame_cancelled = False` at line 637 and
the reset at line 668. Minimum viable alternative: do not reset
_frame_cancelled at entry — reset it only after a completed run — but the
epoch is the honest fix because it also survives a cancel that arrives
between two traces.

**Test strategy**

_JogClientSpy-style stub client, direct driver call (reproduced, currently
fails): inject the spy, `await driver.cancel_frame()`, then `await
driver.trace_frame(100.0, 50.0)`; assert no D9 10 command was recorded.
Observed: 5 corner moves emitted after the cancel.

**Hardware check:** None needed — pure driver-side sequencing, no opcode semantics involved.

---

### MOT-03 - Same STOP bypass restarts a held jog: releasing one half of a diagonal after STOP re-issues motion

- **Severity:** SAFETY
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:809`
- **Class:** Failure class 6 — stop semantics of the interactive-motion subsystem (Ruida)
- **Status:** FIXED 47a49acd0
- **Phase 2:** reproduced by `tests/machine/driver/ruida/test_motion_audit.py::TestStopReachesEveryMotion::test_cancel_does_not_let_a_diagonal_restart`

**Evidence**

```python
        await self._stop_jog_motion()
        if self._jog_keys_down:
            # One half of a diagonal let go: keep going on the rest.
            self._jog_busy = True
            await self._jog_to_limit()
```

**Expected**

After the user has pressed STOP, no subsequent UI event should be able to
command new motion without a fresh, deliberate jog press.

**Actual**

cancel() leaves `_jog_keys_down` populated. On a touchscreen (or with a
second pointer) the user can hold a diagonal — two keys down, e.g.
{('x',1),('y',1)} — press STOP (D8 01 goes out, head stops), then lift one
finger. jog_key_up discards only that key, calls `_stop_jog_motion` (a
second D8 01), sees `_jog_keys_down` still non-empty, sets `_jog_busy =
True` and calls `_jog_to_limit()`, which emits a fresh C9 02 + D9 10 driving
the remaining axis all the way to bed-limit − JOG_LIMIT_MARGIN_MM. The head
resumes travelling after an emergency stop, with no further user intent
expressed. Separately verified and REFUTED: the prompt's hypothesis that
this path leaves `_jog_busy` True forever. Every producer clears it —
trace_frame in its `finally` (ruida_driver.py:669), jog() in its `finally`
(927), `_stop_jog_motion` in its `finally` (851). There is no permanent-
brick path for `_jog_busy`.

**Verification**

Confirmed: cancel():577-579 leaves _jog_keys_down populated, and
jog_key_up:802-812 discards only the released key, then - seeing the set
still non-empty - sets _jog_busy=True and calls _jog_to_limit, emitting a
fresh C9 02 + D9 10 to bed-limit minus margin. Motion after an emergency
stop with no new jog press. Narrower than stated in one respect I checked:
machine-cancel has no keyboard accelerator (only main_menu.py:201 and
toolbar.py:169 plus the jog widget's stop button), so it needs a
touchscreen/second pointer to press STOP while an arrow is held. Their own
note that _jog_busy is not permanently leaked on THIS path is correct.

**Proposed fix**

Covered by the cancel() fix above (`self._jog_keys_down.clear()` before
`_stop_jog_motion()`). Independently, guard the restart branch on a driver-
level `_stopped` latch that cancel() sets and only a fresh jog_key_down
clears.

**Test strategy**

`_JogClientSpy` (tests/machine/driver/ruida/test_ruida_driver.py:1591).
`await driver.jog_key_down('x', 1)`; `await driver.jog_key_down('y', 1)`;
record `len(_motion(spy.commands))`; `await driver.cancel()`; `await
driver.jog_key_up('x', 1)`; assert no new `\xd9` command was emitted after
the cancel. Today one is.

**Hardware check:** Optional: reproduce on a touchscreen panel by holding a diagonal, tapping
STOP with a second finger, then lifting one of the two.

---

### MOT-04 - release_all_jog_keys clears trace_frame's borrowed _jog_busy: Go Scale stops, then resumes moving on its own

- **Severity:** SAFETY
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:822`
- **Class:** Failure class 3 — state desync of RuidaDriver._last_known_pos and _jog_busy (full read/write lifecycle, leak analysis, plus the shared _suppress_polling flag)
- **Status:** FIXED 47a49acd0
- **Phase 2:** reproduced by `tests/machine/driver/ruida/test_motion_audit.py::TestStopReachesEveryMotion::test_release_all_keys_aborts_a_running_go_scale`

**Evidence**

```python
        if keys or self._jog_busy:
            await self._stop_jog_motion()
```

**Expected**

release_all_jog_keys is the stop-everything safety net (driver.py:702-708:
"a held key that never sees its key-up leaves the head moving"). It is fired
by JogWidget on window focus loss (jog_widget.py:592-594), on widget unmap
(jog_widget.py:585-590), on set_machine (jog_widget.py:325) and by
_disconnect_transports (ruida_driver.py:401). After it runs, the head must
be stopped and must stay stopped.

**Actual**

trace_frame borrows the jog subsystem's flag (ruida_driver.py:654
`self._jog_busy = True`) but signals its own abort through a DIFFERENT flag,
_frame_cancelled. During a Go Scale, _jog_keys_down is empty but _jog_busy
is True, so release_all_jog_keys takes the `or self._jog_busy` branch, sends
D8 01 through _stop_jog_motion and clears _jog_busy — and never sets
_frame_cancelled. trace_frame's loop (line 658) and _wait_for_frame_corner
(line 697) only test _frame_cancelled, so the corner wait polls out its full
FRAME_CORNER_TIMEOUT (15 s), logs "corner not reached ... continuing", and
then commands the NEXT corner. Probed: with a stub client, calling
release_all_jog_keys after the 2nd corner produced D8 01 followed by 3 more
D9 10 rapid moves; the full 5-corner rectangle still completed. Net effect:
the user alt-tabs (or the panel is unmapped) during Go Scale, the head
halts, and ~15 s later it starts moving again with the window unfocused.

**Verification**

Traced: trace_frame borrows the jog flag (654 `self._jog_busy = True`) but
aborts on a different flag (_frame_cancelled). release_all_jog_keys:822
takes the `or self._jog_busy` branch with an empty key set, calls
_stop_jog_motion (D8 01, then clears _jog_busy at 851) and never touches
_frame_cancelled. The corner loop (658) and _wait_for_frame_corner (697)
test only _frame_cancelled, so the wait burns FRAME_CORNER_TIMEOUT=15 s,
logs at 707-711 and returns, and the loop issues the next corner. The widget
fires this on window focus loss, unmap and set_machine (jog_widget.py:325,
590, 594) - all reachable mid-trace. Motion resuming after a stop with no
user input = SAFETY.

**Proposed fix**

Stop sharing the flag. Either (a) have release_all_jog_keys call `await
self.cancel_frame()` (which sets _frame_cancelled) before/instead of the
bare _stop_jog_motion, or (b) give the trace its own `_frame_busy` flag so
the jog safety net neither sees nor clears it, and make _stop_jog_motion set
`self._frame_cancelled = True` unconditionally so any halt also aborts the
trace. Additionally, _wait_for_frame_corner should return as soon as a stop
has been issued rather than burning 15 s.

**Test strategy**

_ScaleClientSpy-style stub client from
tests/machine/driver/ruida/test_ruida_scale_jobs.py. Shrink
FRAME_CORNER_TIMEOUT/FRAME_POLL_INTERVAL, wrap spy.rapid_move_xy so it
awaits driver.release_all_jog_keys() after the 2nd corner, then assert that
no b"\xd9\x10" command is recorded at an index after the b"\xd8\x01" index
(currently 3 are).

**Hardware check:** Confirm on the controller that D8 01 actually halts an in-flight D9 10
rapid, and that a subsequent D9 10 is accepted without any re-arm; the
driver's own comment at lines 833-838 flags this as unverified.

---

### MOT-05 - D8 01 is assumed to halt an interactive D9 10 rapid; the only in-repo decoder says it is a process stop that does not touch motion

- **Severity:** SAFETY
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:833`
- **Class:** Failure class 6 — stop semantics of the interactive-motion subsystem (Ruida)
- **Status:** NEEDS-HARDWARE - observe whether memory 0x0421 keeps changing after a D8 01 sent mid-flight into a D9 10 rapid. If it does, D8 01 does not brake an interactive move and the chunked-move fallback in _stop_jog_motion's docstring has to be built. Capture the exchange as a second fixture either way.
- **Phase 2:** no automated reproduction; see the note below

**Evidence**

```python
        HARDWARE NOTE: this assumes D8 01 halts an interactive rapid.
        If it turns out not to on this controller, the fallback is to
        keep the long move but chunk it into 25 mm relative moves,
        issued only once the polled position shows the previous chunk
        nearly consumed -- still behind the busy flag, so the queue
        never grows past one outstanding move.
```

**Expected**

Every interactive motion this driver starts (hold jog, single step, Go Scale
corner, move_to) is halted by the one byte pair the driver sends to stop it.
That claim should be backed by something in the repo or by a hardware log.

**Actual**

Nothing in the repo supports it, and the one decoder that models controller
state contradicts it. ruida_maps.py:155 names 0x01 `"Stop Process"`.
ruida_server.py:248-250 implements it as a process-state change only: elif
subcmd == 0x01: s.program_mode = False s.machine_status = 22 It does not
clear `s.jog_active`, and it does not touch `s.x`/`s.y`. The simulator's D9
10 handler (ruida_server.py:341-353) teleports — `s.x = x` / `s.y = y` — so
the simulator models no in-flight motion at all and can neither confirm nor
refute the assumption; no test over ruida_simulator can. Meanwhile the ONLY
motion-stop the repo actually models is D8 KeyUp (ruida_server.py:273-275,
`s.jog_active[D8_KEYUP_AXIS_MAP[subcmd]] = 0`), and the client method that
builds it (`RuidaClient.jog_stop`, ruida_client.py:510-517) is never called
by the driver. If the assumption is wrong, then STOP, jog release, focus
loss, unmap, disconnect and cleanup ALL fail to stop the head: every one of
them funnels through `_stop_jog_motion` -> stop_process. The head would run
to bed-limit − 1 mm (bounded, because D9 10 is a finite absolute move) with
no way for the user to interrupt it — the definition of a SAFETY defect.

**Verification**

The verifiable parts all check out: the HARDWARE NOTE at 833-838 concedes
the assumption; _stop_jog_motion:844 sends only stop_process;
ruida_maps.py:155 names 0x01 'Stop Process'; ruida_server.py:248-250 changes
program_mode/machine_status only and leaves s.jog_active and s.x/s.y alone;
the simulator's D9 10 teleports (352-353) so no test can settle it. I also
checked the vendored meerk40t: it uses stop_process only for job abort
(controller.py:412-414) and models no motion halt either, so nothing in the
repo supports the assumption. The only modelled motion stop, D8 KeyUp
(ruida_server.py:273-275 / RuidaClient.jog_stop), has no production caller.
Held at SAFETY because if the assumption is wrong every stop path (release,
STOP, focus loss, unmap, disconnect, cleanup) fails - but note the hazard is
contingent on hardware the repo cannot verify, not a demonstrated failure.

**Proposed fix**

Two steps. (1) Verify on hardware before shipping; record the capture as a
fixture next to tests/machine/driver/ruida/fixtures/rdworks_reference.rd so
the assumption stops being folklore. (2) If D8 01 does not halt a D9 10,
implement the chunked fallback the note already describes: replace the
single long `_jog_to_limit` move with repeated bounded relative moves gated
on the polled position, so the worst-case uncommanded travel after a release
is one chunk (25 mm) rather than the whole axis. Do NOT paper over it by
additionally emitting D8 KeyUp — the driver never sent the matching KeyDown,
and that byte is equally unverified in this context.

**Test strategy**

Not testable in-repo — state that explicitly in the code. What can be
tested: assert that `_stop_jog_motion` emits exactly `b"\xd8\x01"` (already
covered by `test_release_stops_and_resyncs`). The real gate is a hardware
capture. If the chunked fallback is implemented, `_JogClientSpy` can assert
that a hold jog emits a bounded sequence of ≤ 25 mm moves and that a release
leaves at most one outstanding.

**Hardware procedure.** On the real controller: send C9 02 (slow, e.g. 10 mm/s) then D9 10 to the
far end of X; 1 s later send D8 01; poll 0x0421 and confirm X stops
changing. Repeat with D8 02 (pause) and with the axis D8 KeyUp bytes to
learn which one actually brakes an interactive rapid.

**Not reproducible in a test.** The claim is about what the *controller* does with `D8 01` while a `D9 10` rapid is in flight. `ruida_server`'s `D9 10` handler teleports (`s.x = x`), so the simulator models no in-flight motion and can neither confirm nor refute it, and the RDWorks fixture contains no `D9` at all. **Hardware check:** send `C9 02` at 10 mm/s, then `D9 10` to the far end of X; one second later send `D8 01` and poll `0x0421`. If X keeps changing, `D8 01` does not halt an interactive rapid and the chunked-move fallback in `_stop_jog_motion`'s docstring must be implemented. Capture the exchange as a fixture either way.

---

### MOT-06 - A key-up can be overtaken by the key-down it is releasing: D9 run-to-limit lands after D8 01

- **Severity:** SAFETY
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:856`
- **Class:** Failure class 5 — queue / ignore semantics (input during motion must be IGNORED, never QUEUED, at every layer including the transport)
- **Status:** FIXED 47a49acd0
- **Phase 2:** reproduced by `tests/machine/driver/ruida/test_motion_audit.py::TestStopReachesEveryMotion::test_key_up_cannot_be_overtaken_by_its_key_down`

**Evidence**

```python
        deltas = {"x": 0, "y": 0}
        for axis, direction in self._jog_keys_down:
            if axis in deltas:
                deltas[axis] += direction
        if not (deltas["x"] or deltas["y"]):
            return

        pos_x, pos_y = await self._jog_origin()
```

**Expected**

Releasing an arrow must leave the head stopped. After jog_key_up returns, no
further motion command for that key may reach the controller.

**Actual**

_jog_to_limit snapshots _jog_keys_down BEFORE its awaits (_jog_origin() does
a read_position with a 2 s timeout per register when _last_known_pos is
None; _jog_move_to then awaits the send). MachineCmd.jog_key_down and
jog_key_up are dispatched as two independent, unkeyed TaskManager coroutines
(cmd.py:597 and cmd.py:605 — Task.key defaults to id(self), so nothing
serialises them; TaskManager.add_task fires each straight at the loop with
run_coroutine_threadsafe, manager.py:206). So jog_key_up can run to
completion — D8 01 sent, position resynced, _jog_keys_down emptied,
_jog_busy set False — while jog_key_down is parked inside _jog_origin.
jog_key_down then resumes on its stale snapshot and sends the D9 10 run-to-
limit. Wire order observed: C9 02, D8 01, D9 10 <bed limit>. The head
departs for within 1 mm of the bed limit with no button held, _jog_keys_down
== set() and _jog_busy == False, so nothing in the driver will ever stop it
— the next release, focus loss or release_all_jog_keys finds no key to
release.

**Verification**

Confirmed. _jog_to_limit snapshots _jog_keys_down at 856-858 and only then
awaits _jog_origin (which does a 2 s-per-register read_position when the
cache is None) and _jog_move_to. The two coroutines really are independent
concurrent tasks (cmd.py:587-607 unkeyed, task.py:33 id-keyed,
manager.py:206), so jog_key_up can complete - D8 01 sent, keys emptied,
_jog_busy cleared at 851 - while jog_key_down is parked, after which it
issues the run-to-limit D9 10 from its stale snapshot. The head then travels
to within JOG_LIMIT_MARGIN_MM of the bed edge with no key held and no busy
flag for any later stop path to notice (822 sees neither keys nor busy).

**Proposed fix**

Give the driver one asyncio.Lock (self._jog_lock) and wrap the whole bodies
of jog(), jog_key_down(), jog_key_up(), release_all_jog_keys() and
trace_frame() in `async with self._jog_lock:`, so an interactive sequence is
atomic against the next one instead of only its individual sends being
atomic (RuidaClient._send_lock only serialises single datagrams).
Additionally re-read _jog_keys_down after the await in _jog_to_limit and
bail if it no longer contains the direction being driven — cheap belt-and-
braces if the lock is ever relaxed.

**Test strategy**

_JogClientSpy-style stub client whose read_position awaits
asyncio.sleep(0.05) (reproduced, currently fails): set
driver._last_known_pos = None, `down =
asyncio.create_task(driver.jog_key_down("x", 1))`, `await
asyncio.sleep(0.01)`, `await driver.jog_key_up("x", 1)`, `await down`;
assert no b"\xd9" appears at or after the index of b"\xd8\x01" in
spy.commands. Observed: 1 move after the stop, keys set() and busy False.

**Hardware check:** Whether D8 01 truly halts an interactive D9 rapid is already flagged as an
unverified assumption in _stop_jog_motion's docstring (ruida_driver.py:833).
This finding is about ORDER, not about D8 01's meaning: even if D8 01 halts
perfectly, it is emitted before the move it must halt. No hardware check
required.

---

### MOT-07 - Held jog and step jog drive the head to the wrong end of the axis when reverse_x_axis / reverse_y_axis is set

- **Severity:** SAFETY
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:879`
- **Class:** Failure class 2 — sign / axis / frame errors in the interactive-motion subsystem (jog arrows → D9 10 payload, Go Scale / Cut Scale framing)
- **Status:** FIXED 47a49acd0
- **Phase 2:** reproduced by `tests/machine/driver/ruida/test_motion_audit.py::TestReversedAxesJogTheRightWay` (all three tests)

**Evidence**

```python
    @staticmethod
    def _axis_limit(
        pos_um: int, direction: int, extent_um: int, margin_um: int
    ) -> int:
        """The far end of the travel an axis has left, or where it is."""
        if direction > 0:
            return max(pos_um, extent_um - margin_um)
        if direction < 0:
            return min(pos_um, margin_um)
        return pos_um
```

**Expected**

JogWidget._jog_keys (jog_widget.py:497 `keys.append((axis.name.lower(), 1 if
delta > 0 else -1))`) hands the driver the SIGN OF THE MACHINE-SPACE DELTA
that MachinePanel.calculate_jog produced. calculate_jog folds in both the
origin corner AND the reverse flags, and for a reversed axis
Machine.get_soft_limits (machine.py:932-935 `x_min = -w if
self.reverse_x_axis else 0.0`) puts that axis in [-extent, 0]. So with
reverse_x_axis=True a press of EAST must drive the head toward machine X =
-(extent-margin); the head must end up at the east edge, 1 mm inside the
limit.

**Actual**

_axis_limit and _jog_move_to both hard-code a 0..extent space with '+1 ==
toward extent', and RuidaDriver never reads machine.reverse_x_axis /
reverse_y_axis anywhere. Verified numerically against the real code
(MachineSpace.get_world_to_machine_matrix + RuidaDriver._axis_limit + the
_jog_move_to clamp), bed 400x300, Origin.BOTTOM_LEFT, reverse_x=True: EAST
-> key ('x', -1) -> _axis_limit(+100000, -1, 400000, 1000) = +1000 um -> D9
10 X = 1 mm (the WEST edge). WEST -> key ('x', +1) -> +399000 um -> D9 10 X
= 399 mm (the EAST edge). The arrows are exactly swapped, and because it is
a press-and-hold the head traverses the whole bed the wrong way. If the
controller does report the model's negative coordinates instead, it is
worse: EAST at pos=-100 mm gives _axis_limit = -100000, which _jog_move_to's
`max(0, ...)` turns into 0, so the head slams to machine X = 0 with the 1 mm
JOG_LIMIT_MARGIN_MM protection silently discarded. The same inversion hits
the single-step path: RuidaDriver.jog() at line 924 computes `pos_x + dx_um`
from a controller-raw pos and an app-signed delta, so a 10 mm EAST click
moves 10 mm WEST. With soft limits ENABLED it degrades further:
MachineController.jog calls Machine._adjust_jog_distance_for_limits, which
with reverse_x sees x_max = 0.0 and a positive reported x_pos = 100 mm and
rewrites the requested -10 mm delta to `x_max - x_pos` = -100 mm -- a 10 mm
jog request becomes a 100 mm move. The same mismatch makes
JogWidget._update_limit_status paint every X/Y arrow permanently 'warning',
and makes the position readout (jog_widget.py:643, fed by
_on_position_updated's raw `value_um / 1000.0`) show 0..extent while the
model claims [-extent, 0].

**Verification**

Verified through the whole chain. jog_widget._jog_keys:492-498 takes the
sign of machine_panel.calculate_jog's delta, which for X/Y comes from
get_world_to_machine_matrix (machine_panel.py:442-449) and that matrix
composes the reverse sign flips (coordspace.py:227-233). So reverse_x=True +
BOTTOM_LEFT origin turns EAST into ('x', -1).
ruida_driver._axis_limit:873-882 and the clamp at 951-952 hard-code a
0..extent space with +1 toward the extent, and `grep reverse` over
ruida_driver.py returns nothing - the driver never consults
machine.reverse_x_axis/reverse_y_axis. EAST therefore targets margin_um (1
mm, the opposite edge) and WEST targets extent-margin. The soft-limit leg
also checks out: get_soft_limits (machine.py:932-935) puts a reversed X in
[-w, 0] while _on_position_updated:1081 publishes the raw positive um, so
_adjust_jog_distance_for_limits:986-993 rewrites a -10 mm request to x_max -
x_pos = -100 mm. The setting is user-reachable (hardware_page.py:86-95,
'Makes coordinate values negative'). Config-gated, but a full-bed traverse
in the wrong direction plus a 10x-magnitude step is a crash hazard.

**Proposed fix**

Make RuidaDriver convert at its own boundary instead of assuming the profile
has no reversals. Add a helper pair, e.g. `_to_controller(axis, mm)` /
`_from_controller(axis, um)`, that negates when machine.reverse_x_axis /
reverse_y_axis is set, and apply it in exactly four places: (1)
_on_position_updated, before writing state.machine_pos and _last_known_pos;
(2) _jog_origin's read-back; (3) _jog_move_to, just before rapid_move_xy,
replacing the `max(0, min(...))` clamp with a clamp against
machine.get_soft_limits() so a negative range is respected; (4) move_to.
With that, _axis_limit's 0..extent assumption becomes correct because it
only ever sees app-machine coordinates. If reversals are genuinely
unsupported on Ruida, the alternative is to make can_jog()/can_hold_jog()
return False (and log loudly) whenever either flag is set, rather than
silently inverting the arrows.

**Test strategy**

_JogClientSpy-style stub client in
tests/machine/driver/ruida/test_ruida_driver.py::TestHoldJog. Build the
driver's machine with set_axis_extents(400, 300) and
set_reverse_x_axis(True); derive the key the way the widget does
(`machine.panel.calculate_jog(JogDirection.EAST, 10.0)` -> sign -> ('x',
-1)); set driver._last_known_pos to the east-ward start; `await
driver.jog_key_down('x', -1)` and assert decode35(move[3:8]) is the EAST
limit, not 1000. Add the step-jog twin: `await driver.jog(6000, x=<signed
delta from calculate_jog>)` and assert the commanded X is 10 mm further east
than the start. Also add a machine-model test that RuidaDriver's published
machine_pos falls inside Machine.get_soft_limits() for all four reverse
combinations.

**Hardware check:** On a Ruida with reverse_x_axis toggled on in the profile, read memory 0x0421
(Current X) at the left and right bed edges. If both readings are >= 0 the
controller ignores the profile flag entirely and the arrows are simply
swapped; if the right edge reads negative the controller shares the model's
convention and the max(0, ...) clamp is the dominant fault. Either result
confirms the finding; it only selects which half of the fix matters most.

---

### MOT-08 - A failed position read makes the jog origin (0, 0), turning a 10 mm jog into a full-bed traverse to the machine corner

- **Severity:** SAFETY
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:936`
- **Class:** Unit errors on the interactive-motion speed and distance paths (jog / hold-jog / Go Scale), from the human-facing control to the byte on the wire and back
- **Status:** FIXED 47a49acd0
- **Phase 2:** reproduced by `tests/machine/driver/ruida/test_motion_audit.py::TestOriginIsNeverInvented` (step, hold and Go Scale)

**Evidence**

```python
    async def _jog_origin(self) -> tuple[int, int]:
        """The position a jog is measured from, read back if unknown."""
        assert self._client
        if self._last_known_pos is None:
            pos = await self._client.read_position()
            if pos is not None:
                self._last_known_pos = pos
        return self._last_known_pos or (0, 0)
```

**Expected**

Every jog target is absolute (D9 10), so the origin it is measured from must
be a real, read-back head position. If the position is unknown --
read_position() returns None because _read_memory_wait timed out on 0x0421
or 0x0431 -- no motion may be commanded at all; the user should see the jog
refused.

**Actual**

read_position() returning None leaves _last_known_pos as None and the `or
(0, 0)` substitutes the machine corner as the origin. jog() then sends an
absolute D9 10 to (0 + dx, 0 + dy). Verified by running the real driver
against a stub whose read_position returns None: a request to jog X by +10
mm from a head sitting mid-bed emitted `('speed', 10000), ('move', 10000,
0)` -- an absolute rapid to (10 mm, 0 mm), i.e. the head crosses the entire
bed to the front-left corner at jog speed. _jog_to_limit() (hold jog) and
trace_frame() line 640 (`start = self._last_known_pos or (0, 0)`) fabricate
the same origin, so a Go Scale started after a failed read traces its
rectangle from the machine corner instead of from the head.

**Verification**

Confirmed at ruida_driver.py:929-936: `_jog_origin` returns
`self._last_known_pos or (0, 0)`, and `read_position()` returns None on a DA
timeout (ruida_client.py:855-859, 911-914). jog() then builds an ABSOLUTE D9
10 target from (0,0) (line 924 -> _jog_move_to -> rapid_move_xy).
trace_frame:640 has the identical fallback. The None path is not exotic: two
concurrent read_position() calls collide in `_pending_mem_reads`
(ruida_client.py:906 overwrites the dict entry by address), orphaning the
first future so it times out after 2 s. Uncommanded full-bed motion from a
wrong origin = SAFETY.

**Proposed fix**

Make the unknown case explicit instead of substituting zero. Change
_jog_origin to `-> tuple[int, int] | None`, returning None when
read_position() returns None (and logging a warning at USER_COMMAND level);
make jog(), _jog_to_limit() and trace_frame() return without emitting any
command when the origin is None. Apply the same treatment to trace_frame's
`start = self._last_known_pos or (0, 0)` at line 640. Note the read itself
already logs `Timeout reading memory 0x%04X` in
RuidaClient._read_memory_wait, so the failure is detectable.

**Test strategy**

_JogClientSpy-style stub client in
tests/machine/driver/ruida/test_ruida_driver.py (class TestHoldJog): add a
spy whose `read_position` returns None, set `driver._last_known_pos = None`,
then assert `await driver.jog(600, x=10.0)` and `await
driver.jog_key_down('x', 1)` each emit zero `\xd9` commands
(`_motion(spy.commands) == []`) and leave `_jog_busy` False. Add the mirror
case for `trace_frame(100.0, 50.0)`.

**Hardware check:** None needed -- the defect is entirely host-side. On hardware it would show
as: pull the controller's network cable mid-session (or blackhole port 50200
replies), press a jog arrow, and watch the head run to the origin corner
instead of stepping.

---

### MOT-09 - Stop during a Cut Scale calls cancel_frame(), which cannot stop a job — the laser keeps cutting

- **Severity:** SAFETY
- **Location:** `rayforge/ui_gtk/machine/jog_widget.py:754`
- **Class:** FAILURE CLASS 8 — UI handler wiring in rayforge/ui_gtk/machine/jog_widget.py (connection, ownership, and teardown of the interactive-motion handlers)
- **Status:** FIXED 47a49acd0
- **Phase 2:** reproduced by `tests/ui_gtk/machine/test_jog_widget_motion_audit.py::test_stop_during_a_cut_scale_cancels_the_job`

**Evidence**

```python
        if self._scaling:
            # Go Scale is rapids, not a job: cancelling stops the
            # motion in flight rather than aborting a process.
            self.machine_cmd.cancel_frame(self.machine)
            return
```

**Expected**

While a Cut Scale is running (laser on, cutting the bounding-box rectangle),
the button that now reads "Stop" must abort the cut. That requires
MachineCmd.cancel_job() -> driver.cancel() -> RuidaClient.stop_process().

**Actual**

self._scaling is set True by BOTH scale runs — _on_go_scale_clicked (line
760) and the cut-scale confirm() callback (line 775) — and
_update_scale_buttons() (line 732) relabels the SAME go_scale_btn to "Stop"
for both. Clicking Stop during a Cut Scale therefore calls
MachineCmd.cancel_frame (cmd.py:579) -> RuidaDriver.cancel_frame
(ruida_driver.py:671), whose whole body is `self._frame_cancelled = True`
plus `if self._jog_busy: await self._stop_jog_motion()`. During a Cut Scale
the job runs through driver.run(); _jog_busy is False and _frame_cancelled
is read only by trace_frame()/_wait_for_frame_corner(), which are not
running. So the click sends nothing to the controller: the laser keeps
cutting the full rectangle at the confirmed power while the UI shows a red
"Stop" button. In the print-and-cut wizard (wizard.py:267 constructs
JogWidget(show_actions=False)) the action column with the real stop_btn is
hidden, so there is NO working stop for a running Cut Scale in that window
at all.

**Verification**

Confirmed at every hop. _scaling is set True by both runs (line 760 for Go
Scale, line 775 inside the Cut Scale confirm callback) and
_update_scale_buttons() (730-738) relabels the SAME go_scale_btn to "Stop"
with tooltip "Stop the running scale" for both. _on_go_scale_clicked's
running branch (754-758) calls MachineCmd.cancel_frame (cmd.py:579-585) ->
RuidaDriver.cancel_frame (ruida_driver.py:671-680) whose entire body is
`self._frame_cancelled = True` plus `if self._jog_busy: await
self._stop_jog_motion()`. A Cut Scale runs through run_cut_scale ->
_run_scale_job -> _scale_job -> _execute_monitored_job (driver.run); I
grepped every _jog_busy assignment in ruida_driver.py (113, 654, 669, 784,
792, 800, 811, 841, 851, 920, 927) and none is on the run() path, and
_frame_cancelled is read only at 658 (trace_frame) and 697
(_wait_for_frame_corner). So the click is a complete no-op while the laser
is cutting the rectangle. The main panel still has the separate destructive
stop_btn -> cancel_job -> driver.cancel() -> stop_process(), but
wizard.py:267 constructs JogWidget(show_actions=False), which hides the
action grid while the scale box (attached to the jog grid at row 3) stays
visible -- so that window really has no working stop for a running Cut
Scale. SAFETY stands: a control labelled Stop fails to stop a firing laser.

**Proposed fix**

Record which run is in flight instead of a single boolean: set
self._scale_kind = "go" | "cut" alongside self._scaling in
_on_go_scale_clicked and in confirm(), clear it in _on_scale_done, and
dispatch in _on_go_scale_clicked: `if self._scale_kind == "cut":
self.machine_cmd.cancel_job(self.machine) else:
self.machine_cmd.cancel_frame(self.machine)`. (cancel_job already exists at
cmd.py:408 and maps to driver.cancel() -> stop_process().)

**Test strategy**

Direct widget handler invocation with a MagicMock MachineCmd (the
tests/ui_gtk/machine/test_jog_widget_hold.py harness): drive
_on_cut_scale_clicked's confirm path (or set widget._scaling=True via the
cut entry point), then call widget._on_go_scale_clicked(widget.go_scale_btn)
and assert machine_cmd.cancel_job.assert_called_once_with(machine) and
machine_cmd.cancel_frame.assert_not_called(). Add the mirror test for Go
Scale asserting cancel_frame, not cancel_job.

**Hardware check:** On the machine: load a job, press Cut Scale, confirm, then press Stop mid-
rectangle. Expect: motion and beam stop. Observed with this code: the
rectangle finishes. Watch the driver log — no stop_process is emitted for
the Stop click.

---

### MOT-10 - _wait_for_job_completion can never exit against an unresponsive controller, and it holds _suppress_polling so the connection loop's watchdog stays disarmed

- **Severity:** BROKEN
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:548`
- **Class:** FAILURE CLASS 4 - Concurrency in RuidaClient and the driver's loops (tasks, locks, futures, Events, response attribution)
- **Status:** FIXED ff8431006
- **Phase 2:** reproduced by `tests/machine/driver/ruida/test_motion_audit.py::TestWaitsAreBounded::test_job_completion_wait_gives_up_on_a_silent_controller`

**Evidence**

```python
361            try:
362                await asyncio.wait_for(
363                    self._response_received.wait(),
364                    timeout=self._response_timeout,
365                )   # not gated on _suppress_polling; disarmed because
                    # _response_received.clear() only runs at line 357
```

**Expected**

If the controller stops answering during a job, the driver gives up within a
bounded time, reports the failure, and emits job_finished so the app can
start another job.

**Actual**

The only exit conditions are 'the job-running bit cleared' and 'the client
says it is disconnected'. `RuidaClient.is_connected` delegates to
`UdpTransport.is_connected`, which is just `self.writer is not None` -- for
UDP that stays True when the controller is unplugged, because nothing ever
fails a send and recvfrom simply never returns. `_read_memory_wait` returns
None on timeout, so the loop just sleeps 0.5 s and retries forever.
Meanwhile `run()`'s `finally: self._suppress_polling = False` (line 494-495)
has not executed, so the connection loop is still skipping its poll AND its
liveness wait (lines 352-373 are both gated on `not self._suppress_polling`)
and can never detect the dead controller either. The result is a permanent
hang inside run(): `job_finished` is never sent, MachineCmd's
`_current_monitor` is never cleared, and every subsequent job start raises
'Tried to start a job while another is running.' The app must be restarted.

**Verification**

Confirmed with one mechanism correction. The loop at 548-554 exits only on
the status bit or `is_connected`, and RuidaClient.is_connected ->
RuidaTransport.is_connected -> UdpTransport.is_connected is literally
`return self.writer is not None` (udp.py:26-28), which never goes False for
UDP; _read_memory_wait returns None on timeout (ruida_client.py:911-914) so
the loop retries forever, and _start_job's monitor cleanup never runs
(cmd.py:143-147, 160-171). The watchdog conclusion holds but NOT for the
stated reason: the liveness wait at 361-373 is NOT gated on
_suppress_polling - only the poll (352) and ref poll (375) are. It is
disarmed because `self._response_received.clear()` only happens inside the
gated poll branch (357), so during suppression the event stays set from the
last received datagram and wait_for returns immediately every iteration.

**Proposed fix**

Bound the wait and treat repeated read failures as a lost controller:
deadline_misses = 0 while self._client and self._client.is_connected: status
= await self._client._read_memory_wait(self.MACHINE_STATUS_ADDRESS) if
status is None: deadline_misses += 1 if deadline_misses >= N:
logger.warning('Controller stopped answering status; abandoning job wait')
return else: deadline_misses = 0 if not status &
self.STATUS_JOB_RUNNING_BIT: return await
asyncio.sleep(self.STATUS_POLL_INTERVAL) Wrap run()'s body so job_finished
is emitted on the failure path too. (Also note _wait_for_job_completion
reaches into the client's private _read_memory_wait; a public
read_machine_status() would be the right seam.)

**Test strategy**

Driver-level with a stub client whose is_connected is always True and whose
_read_memory_wait always returns None. `await
asyncio.wait_for(driver._wait_for_job_completion(), timeout=3)` must not
raise TimeoutError; today it always does. End-to-end with ruida_simulator:
start driver.run(), then stop the simulator's UDP server mid-job and assert
run() returns and job_finished fires within a bounded time.

**Hardware check:** Confirm on hardware that 0x0400 bit 0 actually clears when a job ends; if it
does not, this loop never returns even on a healthy controller, which would
raise this to SAFETY-adjacent (the UI stays locked in 'running').

---

### MOT-11 - home() is not tracked as busy and its completion wait is satisfied by any position reply, including the background poller's

- **Severity:** BROKEN
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:608`
- **Class:** Failure class 6 — stop semantics of the interactive-motion subsystem (Ruida)
- **Status:** FIXED ff8431006
- **Phase 2:** reproduced by `tests/machine/driver/ruida/test_motion_audit.py::TestWaitsAreBounded::test_home_waits_on_machine_status_not_on_current_x`

**Evidence**

```python
        self._response_timeout = self.HOMING_TIMEOUT
        try:
            await self._set_max_travel_speed()
            if home_xy:
                await self._client.home_xy()
            if home_z:
                await self._client.home_z()
            await self._client._read_memory_wait(
                0x0421, timeout=self.HOMING_TIMEOUT
            )
        finally:
            self._response_timeout = self.CONNECTION_TIMEOUT
```

**Expected**

The HOMING_TIMEOUT = 40.0 s budget and the temporary `_response_timeout`
bump say plainly that home() is meant to block for the duration of the
homing cycle, so the UI knows when the head is done moving and nothing else
commands motion meanwhile.

**Actual**

0x0421 is the CURRENT X register, not a completion flag — it answers with
wherever the head is at that instant, which carries no information about
whether homing finished. Worse, home() never sets `_suppress_polling`, so
the connection loop keeps calling `_poll_position()` every
POSITION_POLL_INTERVAL = 0.5 s (ruida_driver.py:352-359), and
`_pending_mem_reads` is keyed by address (ruida_client.py:906) so the reply
to the POLLER's 0x0421 request pops and resolves home()'s future
(ruida_client.py:165-168). home() therefore returns within roughly one poll
interval, `_response_timeout` snaps back to 2.0 s, and the caller believes
homing is over while the head is still travelling. Consequences for stop
semantics: (1) nothing in the driver marks a home in progress — `_jog_busy`
is never set — so the jog buttons stay sensitive
(jog_widget._update_button_sensitivity enables them on connection alone) and
a jog press during a home emits C9 02 + D9 10 straight into a homing
controller; (2) the only stop offered for a home is the same `cancel()` ->
D8 01 whose effect on a D8 2A homing cycle is unverified (see the D8 01
finding), and there is no home-specific abort anywhere in the UI or the
Driver base contract.

**Verification**

Confirmed: 0x0421 is 'Current X' (ruida_maps.py:552), a live register, so
the reply to home's own request at 608-610 resolves the wait immediately;
and because home() never sets _suppress_polling, the loop keeps issuing
0x0421 (418-425 -> ruida_client.py:836) while _pending_mem_reads is keyed by
address alone (ruida_client.py:906, popped at 165-168), so the poller's
reply can resolve home's future too. HOMING_TIMEOUT=40 s therefore never
governs anything and home() returns while the head is still travelling. The
jog buttons are indeed enabled on connection alone (jog_widget.py:392-424)
and nothing marks a home in progress. The right pattern exists in the same
file (_wait_for_job_completion polling MACHINE_STATUS_ADDRESS, 544-554).

**Proposed fix**

Wait on something that actually reports completion, and hold a busy flag
while doing it: set `self._suppress_polling = True` for the duration (so
nothing else can resolve the future), then poll MACHINE_STATUS_ADDRESS
(0x0400) the way `_wait_for_job_completion` does (ruida_driver.py:544-554)
until the machine reports idle, bounded by HOMING_TIMEOUT. Set `_jog_busy =
True` across the home so `jog()` and `jog_key_down` short-circuit, and clear
it in the `finally`. If 0x0400 turns out not to expose a homing bit, at
minimum guard `_read_memory_wait` against a second waiter clobbering the
first and note in the docstring that home() does not wait.

**Test strategy**

Stub client (the `_JogClientSpy` pattern) exposing `home_xy`,
`_read_memory_wait`, `set_travel_speed`. Have `_read_memory_wait(0x0421,
...)` return a constant immediately, and `_read_memory_wait(0x0400, ...)`
return busy for the first 3 calls then idle. Assert `home()` only returns
after the 4th 0x0400 read — today it returns after the single 0x0421 read
and never touches 0x0400. Add a second test asserting `driver._jog_busy` is
True at the moment `home_xy` is awaited (inject the assertion from the
stub's `home_xy`).

**Hardware check:** Does the controller answer DA 00 04 21 while a D8 2A home is running? If
yes, home() provably returns early. If the controller goes silent for the
whole cycle, home() waits correctly by accident — but the poller-clobber
path and the missing busy flag are defects either way. Also confirm whether
D8 01 aborts a homing cycle, and whether 0x0400 carries a homing/idle bit.

---

### MOT-12 - jog_key_down leaks _jog_busy=True when _jog_to_limit finds an emptied key set, bricking every further jog until the panel is unmapped

- **Severity:** BROKEN
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:791`
- **Class:** FAILURE CLASS 4 - Concurrency in RuidaClient and the driver's loops (tasks, locks, futures, Events, response attribution)
- **Status:** FIXED 47a49acd0
- **Phase 2:** reproduced by `tests/machine/driver/ruida/test_motion_audit.py::TestBusyFlagNeverLeaks::test_diagonal_release_leaves_the_driver_usable`

**Evidence**

```python
        if holding:
            await self._stop_jog_motion()
        try:
            self._jog_busy = True
            await self._client.set_travel_speed(
                int(self._jog_speed_mm_min * 1000 / 60)
            )
            await self._jog_to_limit()
        except (OSError, RuntimeError) as e:
            logger.warning(f"Hold jog failed to start: {e}")
            self._jog_keys_down.discard(key)
            self._jog_busy = False
```

**Expected**

After a diagonal press-and-hold is released, _jog_busy is False and the jog
buttons work again: a click moves one step, a hold starts a new move.

**Actual**

There is no `finally`. `_jog_busy = True` is set unconditionally, but the
only paths that clear it are the `except (OSError, RuntimeError)` branch and
`_stop_jog_motion`'s own `finally` (line 851). `_jog_to_limit` re-reads the
LIVE key set and bails out silently when it is empty (line 856-860: `for
axis, direction in self._jog_keys_down: ...` / `if not (deltas["x"] or
deltas["y"]): return`), leaving _jog_busy stuck True. Reachable interleaving
-- MachineCmd.jog_key_down/jog_key_up are UNKEYED coroutines
(cmd.py:558-568), and Task.key falls back to `id(self)`
(shared/tasker/task.py:33), so add_coroutine never replaces them and each is
scheduled with its own `asyncio.run_coroutine_threadsafe` (manager.py:206).
They therefore run CONCURRENTLY on the TaskManager loop, interleaving at
every await. A diagonal button enqueues two key_downs in one GTK callback
and two key_ups in another (jog_widget.py `_start_hold` /
`_on_jog_released`). Sequence: 1. key_down(x+) runs to completion without
ever yielding (asyncio.Lock uncontended + UdpTransport.send is a non-
yielding sendto), sets _jog_busy=True, sends the move. 2. key_down(y+) sees
holding=True, adds y+, and suspends inside `await self._stop_jog_motion()`
-> read_position() -> asyncio.wait_for. 3. The user lets go. key_up(x+) and
key_up(y+) each discard their key and call _stop_jog_motion; the set is now
EMPTY and both finish with _jog_busy=False. 4. key_down(y+) resumes, sets
_jog_busy=True, streams C9 02, calls _jog_to_limit() -> empty set -> return.
_jog_busy stays True forever. The window in step 2 is normally milliseconds,
but the _pending_mem_reads collision above widens it to the full 2.0 s read
timeout on essentially every diagonal release (key_down(y+)'s 0x0421 future
is the one that gets overwritten by key_up(x+)'s read), so this is the
common case, not the rare one. What the user sees: after releasing a
diagonal jog, all jog buttons stop doing anything -- `jog()` returns at `if
self._jog_busy: return` (line 905) and `jog_key_down` returns at `if
self._jog_busy and not holding: return` (line 784). Nothing recovers it
except release_all_jog_keys(), i.e. moving focus to another window,
unmapping the panel, or disconnecting.

**Verification**

Traced and confirmed. No `finally` at 791-800; the only clears are the
except branch (797-800) and _stop_jog_motion:851, and _jog_to_limit re-reads
the LIVE set and returns silently at 856-860. The interleaving is reachable:
cmd.jog_key_down/jog_key_up are unkeyed (cmd.py:587-607), Task.key falls
back to id(self) (task.py:33) so _add_or_replace_task_unsafe never replaces
them, and each is launched with run_coroutine_threadsafe (manager.py:206) as
its own task on one loop. The second key_down suspends in _stop_jog_motion
-> read_position -> asyncio.wait_for; the widening mechanism is real too -
key_up's read_position overwrites the same 0x0421 entry in
_pending_mem_reads (ruida_client.py:906), orphaning the suspended read's
future so it waits the full 2 s. On resume _jog_busy=True is set with an
empty key set and never cleared, after which 784 and 905 reject everything.
Recovery only via release_all_jog_keys (jog_widget.py:531/590/594).

**Proposed fix**

Give the block a finally that reflects reality rather than intent: try:
self._jog_busy = True await self._client.set_travel_speed(...) await
self._jog_to_limit() except (OSError, RuntimeError) as e:
logger.warning(f"Hold jog failed to start: {e}")
self._jog_keys_down.discard(key) finally: if not self._jog_keys_down:
self._jog_busy = False Apply the same guard to the tail of jog_key_up (lines
809-812), which sets _jog_busy=True before its own _jog_to_limit call.

**Test strategy**

Extend _JogClientSpy (tests/machine/driver/ruida/test_ruida_driver.py:1591)
with a gate: `self.read_gate = asyncio.Event(); self.read_gate.set()` and
`async def read_position(self, timeout=2.0): self.reads += 1; await
self.read_gate.wait(); return self.position`. Then in TestHoldJog:
spy.read_gate.clear() d1 = asyncio.create_task(driver.jog_key_down('x', 1));
await asyncio.sleep(0) d2 = asyncio.create_task(driver.jog_key_down('y',
1)); await asyncio.sleep(0) # suspended in _stop_jog_motion
spy.read_gate.set() await driver.jog_key_up('x', 1); await
driver.jog_key_up('y', 1) await asyncio.gather(d1, d2) assert
driver._jog_keys_down == set() assert driver._jog_busy is False # fails
today Then assert a following `await driver.jog(1200, x=1.0)` actually emits
a D9 10 (it emits nothing today).

---

### MOT-13 - Z jog deltas are silently discarded by both Ruida jog paths while the Z buttons stay enabled, and a Z hold leaks _jog_busy

- **Severity:** BROKEN
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:855`
- **Class:** Unit errors on the interactive-motion speed and distance paths (jog / hold-jog / Go Scale), from the human-facing control to the byte on the wire and back
- **Status:** FIXED 47a49acd0
- **Phase 2:** reproduced by `tests/machine/driver/ruida/test_motion_audit.py::TestBusyFlagNeverLeaks::test_a_held_z_key_does_not_block_x_and_y`

**Evidence**

```python
    async def _jog_to_limit(self) -> None:
        """Move toward the bed limit along the held direction(s)."""
        deltas = {"x": 0, "y": 0}
        for axis, direction in self._jog_keys_down:
            if axis in deltas:
                deltas[axis] += direction
        if not (deltas["x"] or deltas["y"]):
            return

(and the step path, lines 910-918)
        for axis_name, delta in deltas.items():
            axis_lower = axis_name.lower()
            delta_um = int(delta * 1000)
            if axis_lower == "x":
                dx_um += delta_um
            elif axis_lower == "y":
                dy_um += delta_um
        if not (dx_um or dy_um):
            return
```

**Expected**

`RuidaDriver.can_jog()` returns True for every axis (line 762-763), so
JogWidget enables the Z+/Z- buttons (`_can_jog_direction(JogDirection.UP)`
resolves to `machine.can_jog(Axis.Z)`), and pressing them should move Z or
the buttons should be disabled.

**Actual**

Both jog paths accept only 'x' and 'y'; the mm->um conversion for a Z delta
is performed and then dropped on the floor. Verified against the real
driver: `await driver.jog(600, z=5.0)` emitted nothing at all, and `await
driver.jog_key_down('z', 1)` emitted only `('speed', 200000)` with no motion
command -- and left `_jog_busy = True` with ('z', 1) in `_jog_keys_down`.
While that flag is stuck, every single-step jog is silently swallowed by the
`if self._jog_busy: return` guard at line 905, so a lost Z key-up bricks
click-jogging until the widget's `_release_all_jog_keys` sweep happens to
fire. RuidaClient already has the primitives (`_build_jog_keydown('z', ±1)`
-> D8 24/25, `rapid_move_axis(0x12, ...)`), so this is unimplemented
plumbing, not a hardware limit.

**Verification**

Traced fully. can_jog returns True unconditionally (ruida_driver.py:762-763)
-> controller.can_jog passthrough (controller.py:618-622) ->
jog_widget.py:413-416 enables z_plus/z_minus via _can_jog_direction(UP),
whose deltas come from machine_panel.calculate_jog:433-434 = {Axis.Z: ...}.
_jog_to_limit's deltas dict is pre-seeded with only 'x'/'y' (855-860) and
jog() accumulates only 'x'/'y' (910-918), so a Z delta is converted and
dropped. The busy leak is also real: jog_key_down sets _jog_busy=True at
792, _jog_to_limit returns at 860 without raising, and nothing in that
function clears it, so every jog() is swallowed by the guard at 905 for as
long as the Z key is held.

**Proposed fix**

Minimum honest fix: make the capability match the implementation -- `def
can_jog(self, axis: Axis | None = None) -> bool: return axis is None or not
bool(axis & Axis.Z)` -- and return from `jog_key_down` before setting
`_jog_busy` when the axis is not 'x'/'y', so the flag cannot leak. If Z
motion is wanted, route it through `rapid_move_axis(0x12, target_um)` with
the same absolute-target + clamp treatment `_jog_move_to` gives X/Y.

**Test strategy**

_JogClientSpy in test_ruida_driver.py: assert `driver.can_jog(Axis.Z) is
False`; assert `await driver.jog(600, z=5.0)` emits nothing AND leaves
`_jog_busy` False; assert `await driver.jog_key_down('z', 1)` emits nothing
and leaves `_jog_busy` False and `_jog_keys_down` empty. Widget side
(test_jog_widget_hold.py): assert `widget.z_plus_btn.get_sensitive() is
False` with a connected Ruida-like driver.

**Hardware check:** Whether the bed actually has a powered Z on the target machine decides
between the two fixes; D8 24/25 (Z keydown/keyup) is modelled by
ruida_server._handle_d8_command, so the simulator can validate either.

---

### MOT-14 - _wait_for_jog_settled always computes a zero travel distance, so a step jog gives up after 1 s and the next step is measured from a mid-move position

- **Severity:** BROKEN
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:969`
- **Class:** Unit errors on the interactive-motion speed and distance paths (jog / hold-jog / Go Scale), from the human-facing control to the byte on the wire and back
- **Status:** FIXED 47a49acd0
- **Phase 2:** reproduced by `tests/machine/driver/ruida/test_motion_audit.py::TestWaitsAreBounded::test_settle_timeout_scales_with_the_step`

**Evidence**

```python
        start = self._last_known_pos or target
        distance_um = max(abs(target[0] - start[0]), abs(target[1] - start[1]))
        speed_um_s = max(1.0, speed_mm_min * 1000.0 / 60.0)
        timeout = distance_um / speed_um_s + self.JOG_SETTLE_GRACE
```

**Expected**

Per the method's own docstring: "The timeout is the move's own travel time
plus a grace period, so a slow jog over a long step is not cut short." A 200
mm step at 600 mm/min (10 mm/s) should wait about 20 s + 1 s grace.

**Actual**

_jog_move_to has already overwritten `self._last_known_pos` with the
commanded target two lines earlier (line 956: `self._last_known_pos = (x_um,
y_um)`), so `start` is identical to `target`, `distance_um` is always 0, and
the timeout is always exactly JOG_SETTLE_GRACE = 1.0 s regardless of step
size or speed. Verified by running the real `jog()` against a stub whose
head never arrives: a 200 mm step at 600 mm/min returned after 1.04 s
instead of ~21 s. Consequence for the user: `_jog_busy` clears ~20 s early,
so the next click is accepted while the head is still travelling, and its
origin comes from `_jog_origin()` = the last polled mid-move position -- the
second D9 10 overrides the first move, and the head ends short of the two
full steps the user asked for. The distance error equals whatever the first
move had left to run.

**Verification**

Confirmed deterministically. jog() line 924 `target = await
self._jog_move_to(...)`; _jog_move_to writes `self._last_known_pos = (x_um,
y_um)` at line 956 and returns that same tuple; line 925 calls
_wait_for_jog_settled, whose first statements (968-969, no await in between
- awaiting a coroutine does not yield before its body runs) read `start =
self._last_known_pos or target`. start == target, distance_um == 0, timeout
== JOG_SETTLE_GRACE == 1.0 s always. The documented travel-time term never
contributes at all, so BROKEN stands; the visible consequence (early
_jog_busy clear, next click computed from a mid-flight poll) follows from
lines 905 and 977.

**Proposed fix**

Pass the pre-move origin through instead of re-reading the field that the
move just clobbered: in `jog()`, keep `origin = await self._jog_origin()`,
then `await self._wait_for_jog_settled(origin, target, speed)`, and change
the signature to `_wait_for_jog_settled(self, start, target, speed_mm_min)`
using the passed `start` for `distance_um`.

**Test strategy**

_JogClientSpy in test_ruida_driver.py, reusing the `frozen` rapid_move_xy
stub already present in `test_single_step_gives_up_after_the_timeout` (which
deliberately never updates spy.position). Set JOG_SETTLE_POLL_INTERVAL =
0.01 and JOG_SETTLE_GRACE = 0.05, run `await driver.jog(600, x=200.0)`, and
assert `spy.reads` is in the thousands (travel-time-bounded) rather than ~5
(grace-bounded); today it is ~5.

---

### MOT-15 - EventControllerMotion 'leave' never fires while the button is held, so dragging off does not stop the jog

- **Severity:** BROKEN
- **Location:** `rayforge/ui_gtk/machine/jog_widget.py:257`
- **Class:** FAILURE CLASS 8 — UI handler wiring in rayforge/ui_gtk/machine/jog_widget.py (connection, ownership, and teardown of the interactive-motion handlers)
- **Status:** FIXED d426885ac
- **Phase 2:** reproduced by `tests/ui_gtk/machine/test_jog_widget_motion_audit.py::test_dragging_off_a_held_button_releases_it` and siblings

**Evidence**

```python
        # Dragging off the button must stop the motion too.
        motion = Gtk.EventControllerMotion()
        motion.connect("leave", self._on_jog_leave, directions)
        button.add_controller(motion)
```

**Expected**

Per the comment, sliding the pointer off a held arrow aborts the motion
immediately: _on_jog_leave -> _release_jog_key -> jog_key_up ->
RuidaDriver._stop_jog_motion().

**Actual**

GTK4 does not deliver widget-level crossing events while an implicit pointer
grab is in effect, so no 'leave' is emitted between press and release.
Verified in the shipped binary (.pixi/envs/default/lib/libgtk-4.1.dylib,
gtk4 4.22.4), inside gtk_main_do_event's pointing-event handler at 0x116104:
`bl _gtk_window_lookup_pointer_focus_implicit_grab` / `cbnz x0, 0x116128` —
when a grab exists it jumps straight past the `bl
_gtk_synthesize_crossing_events` at 0x116124. The grab is established on
button-press and only revoked at release (0x11624c `bl
_gtk_window_set_pointer_focus_grab` with NULL, then a crossing synthesis
with GDK_CROSSING_UNGRAB). Consequence: press NORTH, hold, then drag the
pointer anywhere off the button — RuidaDriver._jog_to_limit() has already
issued ONE long absolute move to the far end of the bed
(ruida_driver.py:853-871), and it keeps executing until the mouse button is
physically released. The intended abort gesture silently does nothing; the
head travels the whole bed. ('leave' does fire, correctly, just after the
release — GTK synthesizes it before propagating the release event — which is
why the existing test test_pointer_leave_releases_a_held_key passes while
the live behaviour is wrong.)

**Verification**

I reproduced the disassembly independently against
.pixi/envs/default/lib/libgtk-4.1.dylib and it is even stronger than
claimed. Inside _gtk_main_do_event, the pointing-event jump-table entry at
0x1160a8 calls _gtk_window_lookup_pointer_focus_implicit_grab and, on a hit
(`cbnz x0, 0x1160cc`), skips _gtk_widget_pick entirely and keeps the grab
widget as the target; the second check at 0x116104-0x116108 then jumps past
the `bl 0x1153c4 <_gtk_synthesize_crossing_events>` at 0x116124. Since
gtk_synthesize_crossing_events is the only producer of the
GDK_ENTER/LEAVE_NOTIFY events GtkEventControllerMotion turns into
enter/leave, no 'leave' can be emitted between press and release. So the
controller added at jog_widget.py:257-260 with the comment "Dragging off the
button must stop the motion too" never fires for its stated purpose; the
release-time UNGRAB crossing arrives after _on_jog_released has already let
the keys go, which is exactly why test_pointer_leave_releases_a_held_key
(tests/ui_gtk/machine/test_jog_widget_hold.py:140) passes -- it calls
_on_jog_leave directly. Severity raised from DEGRADED to BROKEN: the
intended abort gesture does not happen at all. Not SAFETY, because the head
still stops on the physical button release and _jog_to_limit() bounds the
move to the bed extent minus JOG_LIMIT_MARGIN_MM.

**Proposed fix**

Track the drag inside the grab, where the events actually arrive: connect
the same GestureClick's "update" signal (GtkGesture emits it for every
motion on the tracked sequence) and release that button's keys when the
point leaves the widget, e.g. `gesture.connect("update",
self._on_jog_gesture_update, button, directions)` with `ok, x, y =
gesture.get_point(seq)` then `if not button.contains(x, y): release`. Keep
the 'leave' handler as a belt-and-braces path for the ungrabbed case.

**Test strategy**

Widget-level: direct invocation of the new _on_jog_gesture_update with an
out-of-bounds point after _hold(widget, EAST), asserting
machine_cmd.jog_key_up is called. The GTK-level claim itself is not
reproducible in the pytest harness (it needs a real pointer grab) — settle
it manually by connecting a print to 'leave' on any GTK4 button and dragging
off with the button held.

**Hardware check:** Press and hold an arrow, drag the pointer off the button, keep the mouse
button down: the head keeps travelling toward the bed limit. It stops only
when the mouse button is released.

**The GTK-level claim is not reproducible in the pytest harness** -- it needs a real implicit pointer grab, which the headless test session never creates. What the reproduction pins instead is the missing abort path: there is no gesture-update handler at all, so no code exists that *could* see a drag inside the grab. **Manual check:** connect a print to `leave` on any GTK4 button and drag off with the mouse button held; no leave arrives until the release.

---

### MOT-16 - Interactive commands are dispatched as unkeyed TaskManager coroutines, which gives them no ordering at all

- **Severity:** DEGRADED
- **Location:** `rayforge/machine/cmd.py:591`
- **Class:** Failure class 5 — queue / ignore semantics (input during motion must be IGNORED, never QUEUED, at every layer including the transport)
- **Status:** FIXED 6ee845366

**Evidence**

```python
cmd.py:587-599 jog_key_down/jog_key_up dispatch with no key=; cmd.py:613 release_all_jog_keys and cmd.py:426 jog likewise. task.py:33 `self.key: Any = key if key is not None else id(self)`. manager.py:203-208 add_task -> _add_or_replace_task_unsafe (emits tasks_updated at 192) then asyncio.run_coroutine_threadsafe(self._run_task(...), self.loop); _run_task (517) holds no lock and manager.py contains no asyncio.Lock or Semaphore at all.
```

**Expected**

The comment's premise is right — keying jog_key_down/jog_key_up would let
one press cancel the previous release — but the reader is left believing
unkeyed is therefore safe.

**Actual**

Unkeyed means Task.key = id(self) (rayforge/shared/tasker/task.py:33), so
nothing is ever replaced — and nothing is ever serialised either.
TaskManager.add_task hands each coroutine straight to the loop with
asyncio.run_coroutine_threadsafe (manager.py:206), so every press, release
and release_all runs CONCURRENTLY with no ordering guarantee whatsoever.
RuidaClient._send_lock (ruida_client.py:216) serialises individual datagrams
but not a driver-level sequence, which is precisely what lets the D9 in
finding 2 land after the D8 01. Queue depth, for the record: the widget's
_keys_down guard (jog_widget.py:500-506) caps it at one down + one up per
key, so it does not grow without bound while a finger is down — but
MachineCmd.jog (cmd.py:426) is also unkeyed with no dedupe anywhere, and
JogWidget._on_key_pressed (jog_widget.py:818) fires it per GTK keyboard
auto-repeat event, so holding a keyboard arrow allocates and registers
~25-30 throwaway Tasks per second in TaskManager._tasks (each emitting
tasks_updated) that the driver then discards via `if self._jog_busy:
return`.

**Verification**

Every quoted line is at the claimed location and says what the auditor says
it says. Traced end to end: unkeyed -> Task.key = id(self) (task.py:33) so
_add_or_replace_task_unsafe never replaces anything, and add_task hands each
coroutine straight to the loop via run_coroutine_threadsafe (manager.py:206)
with no lock anywhere in _run_task or the manager, so interactive driver
calls interleave at every await point. RuidaClient._send_lock
(ruida_client.py:216) is confirmed to wrap one datagram, not a driver-level
sequence. The keyboard-churn sub-claim is also confirmed: _on_key_pressed
(jog_widget.py:818) -> _on_x_plus_clicked (684) -> _perform_visual_jog (678)
-> _perform_jog (661) -> machine_cmd.jog (cmd.py:426, unkeyed) ->
Machine.jog (machine.py:1020) -> MachineController.jog (controller.py:358)
-> RuidaDriver.jog (ruida_driver.py:897) which discards on `if
self._jog_busy: return` (905); no dedupe exists on that path, and each
throwaway Task registers in _tasks and emits tasks_updated. Two reasoning
corrections that do not refute it: (1) run_coroutine_threadsafe from the
single GTK main thread does preserve FIFO *start* order via
call_soon_threadsafe, so 'no ordering guarantee whatsoever' overstates it -
what is actually absent is serialization to completion; (2) the auditor
omits a real partial guard, _jog_to_limit (ruida_driver.py:855-860), which
recomputes deltas from the live _jog_keys_down and returns without motion
when a concurrent jog_key_up has already emptied it at line 806, closing the
common press/release interleaving. A residual window does survive:
_jog_origin (929-936) awaits read_position while _last_known_pos is None
(initialized None at 111) AFTER the key set was read, so a key-up's D8 01
can complete before the in-flight key-down's rapid_move_xy (953) emits its
D9. Severity corrected from SMELL: the missing serialization is not
correctness-neutral - interactive stop and move commands genuinely
interleave wrongly under fast input, and holding an arrow key churns ~25-30
signal-emitting Tasks/second that are then thrown away. It is not raised to
SAFETY on its own because the head-moves-with-no-key-held outcome needs the
extra _jog_origin window the auditor never establishes, and the finding
itself defers that consequence to a separate finding not in this list.

**Proposed fix**

Keep the tasks unkeyed and fix ordering where it belongs — the driver-side
asyncio.Lock from finding 2. Then correct this docstring to say why: unkeyed
keeps the task manager from swallowing a release, and the driver's own lock
provides the ordering the task manager deliberately does not. Optionally
give MachineCmd.jog the same _keys_down-style dedupe the hold path has, or
route the keyboard-arrow handler through the hold path, so auto-repeat stops
minting tasks the driver will discard.

**Test strategy**

Not a behavioural test — verify by reading. If you want a regression guard
for the ordering fix, the finding-2 test (_JogClientSpy with a delayed
read_position, key_down and key_up as concurrent tasks) is the one that
proves the lock works.

**Not reproducible in a test.** None.

---

### MOT-17 - A single 0xCC from any interactive command pops the head of _pending_job_acks and falsely acknowledges an outstanding job chunk

- **Severity:** DEGRADED
- **Location:** `rayforge/machine/driver/ruida/ruida_client.py:147`
- **Class:** FAILURE CLASS 4 - Concurrency in RuidaClient and the driver's loops (tasks, locks, futures, Events, response attribution)
- **Status:** DEFERRED - the minimal fix edits how a reply is matched to a pending job-chunk ack, and send_job's ack handling is fenced off by the brief. 47a49acd0 removes the trigger instead: a job now holds an interlock for its whole upload and run, so no interactive command can be in flight to steal the ack. Revisit with approval if job acks are ever wanted concurrently with interactive traffic.

**Evidence**

```python
Supporting citation corrected: the 'Pause and Stop stay sensitive whenever connected' code is rayforge/ui_gtk/machine/jog_widget.py:421-424 (`# Job controls - always enabled when connected` / start_btn/pause_btn/stop_btn set_sensitive(True), reached after the only gate at :392 `if self.machine is None or not self.machine.is_connected(): return`). The cited jog_widget.py:850-853 does not exist; the file is 843 lines.
```

**Expected**

A job chunk's ACK future is resolved only by the controller's reply to that
chunk. Pressing Pause or Stop during an upload stops the job; it does not
alter which chunk the sender believes was acknowledged.

**Actual**

Resolution is positional and source-blind: ANY single-byte
0xCC/0xC6/0xCF/0xCD arriving while `_pending_job_acks` is non-empty pops the
head of the list. The in-repo simulator ACKs EVERY datagram on the main
channel -- ruida_simulator.py:247-252 `if response == b"\xcc" or not
response: await main_transport.send_response(b"\xcc", addr)` -- so a D8 01
(Stop), D8 02 (Pause), C9 02 (jog speed), D9 10 (jog move) or DA 00
(position read) each produce a bare 0xCC. `send_command` takes `_send_lock`
but registers no ack future (line 216-217), so those bytes have no owner of
their own; `_pending_acks` is production-dead (`send_command_wait_ack` is
called only from tests/machine/driver/ruida/test_ruida_client.py:547), so
the `elif` at 152-159 never claims them either. And these commands ARE
reachable mid-upload: jog_widget.py:850-853 keeps Pause and Stop sensitive
whenever the machine is connected, and the jog arrows too, with no job-
running gate. Concrete failure: the user hits Stop during a 40-chunk upload.
`driver.cancel()` sends D8 01; its 0xCC pops chunk N's future, so
`_send_job_chunk` reports chunk N acked and immediately sends chunk N+1.
Chunk N's real ACK then pops chunk N+1's future. The ack pipeline is
permanently off by one and the sender races ahead of the controller; a NAK
is now attributed to the wrong chunk, so the WRONG chunk is retransmitted
(JOB_SEND_ATTEMPTS retry) and the controller receives a duplicated block in
the middle of the job stream.

**Verification**

Quote at :147-151 verified exactly, and _JOB_ACK_BYTES (:46-48) does contain
0xCC. Resolution is positional and source-blind. Verified the supporting
chain: RuidaTransport._on_raw_received :140-142 forwards a bare single-byte
0xCC/0xCD/0xCE straight to _handle_response; ruida_simulator.py:247-252 ACKs
every main-channel datagram with 0xCC; _pending_acks is production-dead
(send_command_wait_ack only at
tests/machine/driver/ruida/test_ruida_client.py:547) so the elif at :152-159
never claims those bytes; run() sets _suppress_polling (ruida_driver.py:478)
so the poll loop is quiet, but cmd.py:411-413 ('cancel-job'), :404-406
('set-hold') and :426 (jog) are separate TaskManager coroutines with
distinct keys and the jog widget leaves Stop/Pause/arrows sensitive whenever
connected. One correction to the mechanism: _send_lock is held across the
whole ACK wait (:299-304), so an interactive command cannot interleave
*inside* a chunk; it is sent in the gap between chunks and its ACK then
lands on the next chunk's future, which produces exactly the permanent off-
by-one the finding describes (a later NAK is attributed to the wrong chunk
and the wrong chunk is retransmitted). Downgraded BROKEN -> DEGRADED: an
undisturbed upload acks correctly end to end; corruption requires the
concurrent-interactive-command condition.

**Proposed fix**

Do not let a job ack be resolved by traffic the job did not generate.
Minimal fix inside the client: record a monotonic send counter with each
job-ack future and refuse to resolve it from a reply that arrived after a
non-job send: self._sends = 0 # incremented in send_command and
_send_job_chunk self._pending_job_acks.append((self._sends, future)) and in
_handle_response only pop the head when its recorded counter still equals
self._sends. The better structural fix is to make the client refuse or queue
interactive commands for the duration of a send: add a `_job_in_flight` flag
set by send_job, and have send_command raise (or await its clearance) while
it is set, so Stop/Pause are routed through a path that first aborts the
upload.

**Test strategy**

Client-level with a stub transport, no UDP needed: append a job-ack future
by starting `asyncio.create_task(client._send_job_chunk(b'\x88\x00'))`,
`await asyncio.sleep(0)`, then inject `client._handle_response(None,
b'\xcc')` as if it were the reply to an unrelated Stop, and assert the chunk
future is NOT resolved. End-to-end with ruida_simulator over UDP: instrument
the simulator's on_command hook to record every chunk it receives, run
`driver.run()` on a >3-chunk blob, call `await driver.cancel()` mid-send,
and assert the simulator saw each chunk exactly once and in order.

**Hardware check:** The simulator's blanket 0xCC-per-datagram is the in-repo ground truth. On
real hardware, confirm with a packet capture that an RDC controller replies
0xCC to D8 01 / D8 02 while a job upload is in progress; if it stays silent
for D8, the reachable trigger narrows to DA reads (position poll / jog
resync), which still ACK.

---

### MOT-18 - DA replies are attributed by address alone, so the connection loop's un-futured position poll answers an interactive read that had not been sent yet

- **Severity:** DEGRADED
- **Location:** `rayforge/machine/driver/ruida/ruida_client.py:165`
- **Class:** FAILURE CLASS 4 - Concurrency in RuidaClient and the driver's loops (tasks, locks, futures, Events, response attribution)
- **Status:** FIXED 01d841e3a

**Evidence**

```python
            if mem_address in self._pending_mem_reads:
                future = self._pending_mem_reads.pop(mem_address)
                if not future.done():
                    future.set_result(value)
```

**Expected**

`read_position()` returns where the head is now, after the caller's own DA
00 request. `home()`'s `_read_memory_wait(0x0421,
timeout=self.HOMING_TIMEOUT)` waits for a fresh answer, not for a sample the
poll loop took a second ago.

**Actual**

There is no request/reply correlation of any kind -- the address in the
reply is the only key. The connection loop's poll uses `get_position()`,
which calls the fire-and-forget `_read_memory` (client lines 836-838) and
registers NO future, so its replies are unowned and will resolve whichever
interactive `_read_memory_wait` for the same address happens to be pending.
The interactive caller is therefore answered by a sample taken BEFORE its
own request went out. This bites the two places that use position as a
completion test: `_wait_for_jog_settled` (driver 974-983) and
`_wait_for_frame_corner` (driver 696-705) both compare a possibly pre-move
sample against the target, and `home()` (driver 608-610) waits on 0x0421 for
up to 40 s but is released by the very next routine poll reply ~1 s later,
so home() reports done while the head is still travelling. Distinct from the
dict-overwrite defect: here nothing is overwritten and nothing hangs -- the
answer is simply the wrong sample.

**Verification**

Verified. ruida_client.py:161-168 keys resolution solely on the address
decoded out of the reply; there is no sequence number or request identity
anywhere. get_position() (:824-839) calls the fire-and-forget _read_memory
for 0x0421/0x0431/0x0441 and registers no future, so its replies are unowned
and will resolve whichever _read_memory_wait for the same address is pending
-- a sample taken before the interactive request went out. _suppress_polling
is set only at ruida_driver.py:478 (run) and :653 (trace_frame), so the poll
loop is live during jog() and home(). Two corrections to the claimed impact:
(a) _wait_for_frame_corner (:682-705) runs inside trace_frame's
_suppress_polling window, so the poll loop is NOT competing there -- that
instance is guarded; (b) home()'s early return is over-attributed:
_read_memory_wait(0x0421) would be answered immediately by the controller's
own reply to home()'s own request too, since a DA read returns the
instantaneous position, so home() never waits for homing to finish with or
without this defect. The live instance is _wait_for_jog_settled (:959-983),
which can compare a pre-move poll sample against the target. DEGRADED
confirmed.

**Proposed fix**

Route the poll loop through the same waiting path so every reply has an
owner and FIFO ordering is meaningful: make `_poll_position` call
`read_position()` (which pairs with the FIFO fix from the _pending_mem_reads
finding) instead of `get_position()`. If the fire-and-forget poll must stay,
stamp each pending read with the time (or a send sequence number) taken at
the moment its DA 00 left, and have _handle_response discard replies that
predate it.

**Test strategy**

Client-level stub transport: call `_read_memory(0x0421)` (no future) then
start `read_position()`, inject one DA 01 04 21 reply, and assert
read_position is still waiting rather than returning the un-requested
sample. Driver-level: run against ruida_simulator with the poll loop live,
call `await driver.home()` and assert it does not return before the
simulator reports the homing move complete.

---

### MOT-19 - _response_received is set by every decoded packet, so a bare transport ACK satisfies the connection loop's liveness wait and masks a controller that has stopped answering position reads

- **Severity:** DEGRADED
- **Location:** `rayforge/machine/driver/ruida/ruida_client.py:188`
- **Class:** FAILURE CLASS 4 - Concurrency in RuidaClient and the driver's loops (tasks, locks, futures, Events, response attribution)
- **Status:** FIXED 01d841e3a

**Evidence**

```python
        self.state_changed.send(self)
```

**Expected**

The connection loop's `await
asyncio.wait_for(self._response_received.wait(),
timeout=self._response_timeout)` (ruida_driver.py:361-365) proves the
controller answered the position poll it just sent. If position replies
stop, the loop logs 'Controller stopped responding, reconnecting' and
reconnects.

**Actual**

Line 188 fires `state_changed` unconditionally at the end of
_handle_response -- outside every parsing branch, for a bare 0xCC, for a
card-info reply, for a malformed datagram. ruida_driver.py:1076-1077 `def
_on_state_changed(self, sender) -> None: self._response_received.set()`
turns any of those into 'the controller is alive'. The same single Event
serves the initial connect handshake (driver line 312-319) and the per-poll
liveness wait (driver line 357-373), and the fire-and-forget
`_fetch_card_info` task (line 341) sets it too. Because the simulator (and
real controllers) ACK the DA read datagram itself with 0xCC before sending
the DA 01 payload, the liveness wait is satisfied by the transport-level
ACK, never by an actual position reply. A controller whose memory-read
subsystem is wedged -- ACKing packets but never returning DA 01 -- keeps the
driver in CONNECTED indefinitely: the DRO freezes at its last value,
`_last_known_pos` goes stale, and the driver never reconnects. The stale
`_last_known_pos` then feeds `_jog_to_limit`/`_jog_origin`, so the next
press-and-hold computes its bed-limit target from a position the head no
longer occupies.

**Verification**

Verified end to end. ruida_client.py:188 `self.state_changed.send(self)`
sits at function scope in _handle_response, outside every parsing branch, so
it fires for a bare 0xCC, a card-info reply, or an unparsed datagram alike;
RuidaTransport._on_raw_received :140-142 explicitly routes single-byte
0xCC/0xCD/0xCE into that handler; ruida_driver.py:1076-1077
`_on_state_changed` -> `self._response_received.set()`. The same Event backs
both the connect handshake (driver :312-319) and the per-poll liveness wait
(:357-373), and the fire-and-forget _fetch_card_info task (:341) also trips
it. ruida_simulator.py:247-252 confirms the transport-level 0xCC precedes
any DA 01 payload, so the wait is satisfied by the ACK, never by a position
reply. A controller that ACKs but stops answering DA reads therefore stays
CONNECTED forever, the DRO freezes, and the stale _last_known_pos feeds
_jog_origin/_jog_to_limit (:929-871). DEGRADED is right: the reconnect works
when the controller goes fully silent, and fails only in the partial-failure
case.

**Proposed fix**

Stop using a shared 'something arrived' Event as the poll's liveness proof.
Replace the _poll_position + _response_received.wait() pair with a read that
owns its own future: pos = await
self._client.read_position(timeout=self._response_timeout) if pos is None:
logger.warning('Controller stopped responding, reconnecting', ...)
self._is_connected = False; await self._disconnect_transports(); break Keep
_response_received only for the initial connect handshake, and clear it
immediately before `keep_alive()` (as it already does) so a buffered
datagram from a previous session cannot satisfy it.

**Test strategy**

Drive the real _connection_loop against a stub RuidaTransport that replies
0xCC to every send but never emits a DA 01 packet. Assert that within ~2 *
driver._response_timeout the driver logs 'Controller stopped responding' and
_is_connected goes False. Today the loop stays CONNECTED forever. A narrower
unit test: connect driver._on_state_changed, call
client._handle_response(None, b'\xcc'), and assert driver._response_received
is not set.

---

### MOT-20 - _pending_mem_reads holds one future per address: a second overlapping read of the same address orphans the first, and the orphan's timeout evicts a stranger's future

- **Severity:** DEGRADED
- **Location:** `rayforge/machine/driver/ruida/ruida_client.py:906`
- **Class:** FAILURE CLASS 4 - Concurrency in RuidaClient and the driver's loops (tasks, locks, futures, Events, response attribution)
- **Status:** FIXED 01d841e3a

**Evidence**

```python
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_mem_reads[mem_address] = future

        try:
            await self._read_memory(mem_address)
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            self._pending_mem_reads.pop(mem_address, None)
            logger.warning(f"Timeout reading memory 0x{mem_address:04X}")
            return None
```

**Expected**

Two concurrent read_position() calls each get their own reply. Both return
within one network round trip (a few ms on a LAN), and a timeout on one read
cancels only that read's own waiter.

**Actual**

The dict is keyed by address only (line 120: `self._pending_mem_reads:
dict[int, asyncio.Future] = {}`), and the future is registered at line 906
OUTSIDE `_send_lock` (the lock is only taken later, inside `send_command`,
line 216). So both callers register before either sends, and the second
assignment silently replaces the first future -- the first is now
unreachable from the dict and nobody will ever resolve it.
`_handle_response` line 165-168 pops the single entry and resolves it with
the FIRST reply that arrives; the second reply finds `mem_address not in
self._pending_mem_reads` and is discarded. Net effect: caller B is answered
by caller A's reply, caller A blocks for the full 2.0 s timeout, and A's
timeout handler then executes `self._pending_mem_reads.pop(mem_address,
None)` -- which pops whatever future is registered under that address AT
THAT MOMENT, i.e. a third, unrelated caller's future, which then also hangs
2.0 s and evicts a fourth. The eviction cascades. (This also answers the
'late reply finds no future' question: the late reply is not fully lost --
lines 170-186 still update self.state and emit position_updated -- but the
pop-by-address is the non-benign half.)

**Verification**

Verified line by line. ruida_client.py:120 `self._pending_mem_reads:
dict[int, asyncio.Future] = {}`; :904-914 creates and stores the future at
:906 *before* any lock is taken (the only lock, _send_lock, is acquired
inside send_command at :216, downstream of :909 `await
self._read_memory(...)`), so two callers both register before either sends
and the second assignment silently orphans the first. _handle_response
:165-168 pops the single entry and resolves it with the first matching DA
01; the late reply falls through :170-186 (state + position_updated still
updated) but resolves nobody. The timeout branch :911-914 does
`self._pending_mem_reads.pop(mem_address, None)` -- an unconditional pop-by-
address that evicts whatever future is registered at that instant, i.e. a
third caller's, which then also hangs its full 2.0 s. Reachable:
read_position() is called from ruida_driver.py:638, :699, :845, :933 and
:975, and cmd.py dispatches jog/cancel-frame/cancel-job under distinct
TaskManager keys, so those coroutines genuinely overlap. Downgraded BROKEN
-> DEGRADED: the single-reader path (the common case) is correct; the defect
needs two overlapping reads of one address, and the stranded caller degrades
to a None return that its callers tolerate rather than to no behaviour at
all.

**Proposed fix**

Make the pending map hold a FIFO of waiters and remove by identity, not by
address: self._pending_mem_reads: dict[int, list[asyncio.Future]] = {} #
register: self._pending_mem_reads.setdefault(mem_address, []).append(future)
# resolve: waiters = self._pending_mem_reads.get(mem_address) # while
waiters: # f = waiters.pop(0) # if not f.done(): f.set_result(value); break
# timeout: waiters = self._pending_mem_reads.get(mem_address, []) # if
future in waiters: waiters.remove(future) The identity-based removal on the
timeout path is the load-bearing half; the FIFO list removes the
orphan/hang.

**Test strategy**

pytest-asyncio, client-level with a stub transport (no UDP): construct
RuidaClient(FakeTransport()) where FakeTransport.send_command records bytes
and the test drives client._handle_response(None, data) by hand. Launch two
asyncio tasks running client._read_memory_wait(0x0421, timeout=0.2)
concurrently, await asyncio.sleep(0) so both register, inject one
b'\xda\x01\x04\x21' + encode35(123456), and assert BOTH tasks are still
pending on exactly one reply (i.e. only one resolves) -- then inject a
second reply and assert both return 123456 and client._pending_mem_reads ==
{} (or has an empty list). Today the second reply is dropped and one task
returns None after the timeout. Add a third task registered during the
orphan's timeout window and assert it is not evicted.

**Hardware check:** Not needed -- this is pure client-side bookkeeping, provable against the in-
repo ruida_simulator over UDP or a stub transport. On real hardware, watch
for repeated 'Timeout reading memory 0x0421' warnings during diagonal jog
release, which is the signature.

---

### MOT-21 - Hold-jog speed defaults to 12000 mm/min (200 mm/s) and is never synced from the UI, so a press-and-hold runs 12x faster than the Jog Speed row shows

- **Severity:** DEGRADED
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:114`
- **Class:** Unit errors on the interactive-motion speed and distance paths (jog / hold-jog / Go Scale), from the human-facing control to the byte on the wire and back
- **Status:** FIXED 47a49acd0 and cd33192d1

**Evidence**

```python
    DEFAULT_TRAVEL_SPEED = 12000  # mm/min          (line 71)
...
        self._jog_speed_mm_min = self.DEFAULT_TRAVEL_SPEED   (line 114)
...
        await self._client.set_travel_speed(
            int(self._jog_speed_mm_min * 1000 / 60)
        )                                                     (lines 793-795)
```

**Expected**

The head should hold-jog at the speed shown in the bottom panel's "Jog
Speed" row, which is constructed with `value_in_base=1000`
(rayforge/ui_gtk/doceditor/bottom_panel.py:437) and therefore displays 16.67
mm/s.

**Actual**

Nothing ever pushes the row's initial value to the driver. UnitSpinRow's
constructor sets the initial value under `self._is_updating = True`
precisely so it does NOT fire value_changed
(rayforge/ui_gtk/shared/pref_rows/unit_spin_row.py:66-76), so
`_on_speed_changed` never runs at startup, `JogWidget._commit_jog_speed`
never runs, and `RuidaDriver._jog_speed_mm_min` keeps its 12000 mm/min seed.
Running the real jog_key_down against a stub client emitted `('speed',
200000)` -- 200000 um/s = 200 mm/s on the wire, 12x the displayed 16.67
mm/s. Second leg of the same defect: `_commit_jog_speed` is gated on
`self._hold_jog_supported()` (jog_widget.py:608), so a speed the user sets
while the machine is disconnected is silently dropped and is never re-pushed
on connect. Third leg: DEFAULT_TRAVEL_SPEED is documented (lines 69-70) as
the *homing and move-to* fallback; reusing the max-travel constant as the
interactive jog default is what makes the value 200 mm/s.

**Verification**

Verified end to end: ruida_driver.py:71 DEFAULT_TRAVEL_SPEED=12000, :114
seeds _jog_speed_mm_min from it, :793-795 streams int(12000*1000/60)=200000
um/s = 200 mm/s. The only push path is bottom_panel.py:439
`speed_row.value_changed.connect(self._on_speed_changed)` ->
jog_widget.set_jog_speed -> _commit_jog_speed -> cmd.set_jog_speed; the
row's initial value_in_base=1000 (16.67 mm/s displayed) is set inside
UnitSpinRow.__init__ under `_is_updating = True` (unit_spin_row.py:68-76)
AND before the handler is connected, so it never reaches the driver. The
gating on `_hold_jog_supported()` (jog_widget.py:608, requires is_connected)
is also real. Severity corrected from BROKEN: jogging does happen and the
correct value is pushed as soon as the user touches the row, so this is
wrong-under-a-condition (untouched row), not absent behaviour.

**Proposed fix**

(1) Give the hold jog its own default instead of borrowing
DEFAULT_TRAVEL_SPEED -- e.g. `self._jog_speed_mm_min = 1000` to match the UI
row's `value_in_base=1000`, or derive it from
`self._machine.max_travel_speed` at first use. (2) Push the current speed at
the point the widget learns about a machine: call `_commit_jog_speed()` at
the end of `JogWidget.set_machine`, and re-push it from
`_on_connection_status_changed` when the machine becomes connected, so a
value set while disconnected is not lost. (3) Have bottom_panel seed the
widget once after construction (`self._on_speed_changed(self.speed_row)`),
so one constant owns the default instead of three.

**Test strategy**

Two tests. Driver side (_JogClientSpy in test_ruida_driver.py): with no
`set_jog_speed` call at all, assert `jog_key_down('x', 1)` emits
`b"\xc9\x02" + encode35(<profile-derived value>)` rather than
encode35(200000). Widget side (tests/ui_gtk/machine/test_jog_widget_hold.py,
MagicMock machine_cmd + `_hold_jog_driver`): assert
`machine_cmd.set_jog_speed` is called with 1000 after `set_machine`, and
again after a disconnect/reconnect cycle driven through
`_on_connection_status_changed`.

**Hardware check:** On hardware, log the C9 02 payload emitted on the first press-and-hold after
a fresh launch; it will decode to 200 mm/s while the panel reads 16.67 mm/s.

---

### MOT-22 - The connection loop never sends a keepalive after the first, and its 1.0 s sleep makes POSITION_POLL_INTERVAL=0.5 unreachable

- **Severity:** DEGRADED
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:382`
- **Class:** FAILURE CLASS 4 - Concurrency in RuidaClient and the driver's loops (tasks, locks, futures, Events, response attribution)
- **Status:** FIXED 01d841e3a

**Evidence**

```python
                    await asyncio.sleep(self.KEEPALIVE_INTERVAL)
```

**Expected**

KEEPALIVE_INTERVAL = 1.0 means a keepalive (0xCE) goes out every second;
POSITION_POLL_INTERVAL = 0.5 means the DRO refreshes twice a second.

**Actual**

`await self._client.keep_alive()` appears exactly once in the whole driver,
at line 313, BEFORE the inner loop -- it is the connect handshake. The inner
`while self._keep_running and self._is_connected:` body (lines 349-382)
never calls it; KEEPALIVE_INTERVAL is used only as the loop's sleep period.
So the driver sends exactly one keepalive per connection attempt, and all
liveness traffic is incidental to position polling. The poll cadence is also
not what the constant says: `current_time` is sampled once at the top of the
iteration (line 350), `last_poll_time = current_time` is assigned the pre-
poll timestamp (line 359), and every iteration ends in a 1.0 s sleep plus
the time spent in `await asyncio.wait_for(self._response_received.wait(),
...)`. The real position poll period is therefore >= 1.0 s + round-trip,
never 0.5 s. The user sees a DRO that updates at about 1 Hz while the head
moves, and `_last_known_pos` -- which `_jog_origin`/`_jog_to_limit` use to
compute the bed-limit target of a press-and-hold -- is up to a second stale.
Additionally, while `_suppress_polling` is True (whole of `run()` and
`trace_frame()`) the loop transmits nothing of its own at all, so the only
reason the session survives a long upload is the job traffic itself.

**Verification**

Both halves verified. `grep keep_alive ruida_driver.py` returns exactly one
hit, line 313, before the inner loop; the loop body (349-382) never calls it
and uses KEEPALIVE_INTERVAL only as its sleep. Cadence: current_time is
sampled once at 350, last_poll_time is set to that pre-poll sample at 359,
and each iteration ends with a 1.0 s sleep plus the response wait, so the
poll period is >= 1.0 s + RTT and 0.5 s is unreachable. The stale-
_last_known_pos consequence for hold-jog limit targets follows. The
'transmits nothing while _suppress_polling' claim is also correct.

**Proposed fix**

Drive the loop off a short tick and let each activity own its own deadline:
await asyncio.sleep(0.1) # loop tick if now - last_keepalive >=
self.KEEPALIVE_INTERVAL: await self._client.keep_alive(); last_keepalive =
now if not self._suppress_polling and now - last_poll >=
self.POSITION_POLL_INTERVAL: ... and re-sample `current_time` after the
response wait before assigning last_poll_time. Send the keepalive even while
_suppress_polling is set (it is one byte and elicits one byte) or document
that job traffic replaces it.

**Test strategy**

Run the driver against ruida_simulator over UDP for 5 s with the simulator's
on_command hook recording every command. Assert >= 8 DA 00 04 21 requests (2
Hz) -- today it records about 5 -- and assert >= 4 0xCE keepalives; today
exactly 1 arrives, at connect.

---

### MOT-23 - home() zeroes the machine but never invalidates _last_known_pos; only X is corrected, by accident

- **Severity:** DEGRADED
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:601`
- **Class:** Failure class 3 — state desync of RuidaDriver._last_known_pos and _jog_busy (full read/write lifecycle, leak analysis, plus the shared _suppress_polling flag)
- **Status:** FIXED ff8431006
- **Phase 2:** reproduced by `tests/machine/driver/ruida/test_motion_audit.py::TestWaitsAreBounded::test_home_invalidates_the_cached_position`

**Evidence**

```python
        self._response_timeout = self.HOMING_TIMEOUT
        try:
            await self._set_max_travel_speed()
            if home_xy:
                await self._client.home_xy()
            if home_z:
                await self._client.home_z()
            await self._client._read_memory_wait(
                0x0421, timeout=self.HOMING_TIMEOUT
            )
        finally:
            self._response_timeout = self.CONNECTION_TIMEOUT
```

**Expected**

After homing, the cached jog origin matches the machine's new zero, or is
marked unknown so the next jog re-reads it.

**Actual**

No statement on the home path writes _last_known_pos. home_xy() sends D8 2A,
which the simulator's own decoder implements as `s.x = 0; s.y = 0`
(ruida_server.py:264-266). Probed against the simulator over UDP: head
seeded at (300000, 200000) um, cache seeded from the truth, `await
driver.home()` → simulator state (0, 0), driver cache (0, 200000). X is
repaired only as an accidental side effect of home's own
_read_memory_wait(0x0421) resolving through _handle_response ->
position_updated -> _on_position_updated; Y is never touched and keeps its
pre-home value until the ~1 Hz poller lands. A step jog clicked in that
window computes an ABSOLUTE target from the stale Y: "north 10 mm" right
after homing commands y = 210000 um — a 210 mm rapid from the freshly homed
corner.

**Verification**

Confirmed: nothing on the home path (ruida_driver.py:584-612) writes
_last_known_pos, and home_xy sends D8 2A which zeroes both axes
(ruida_server.py:264-266). X is repaired only as a side effect - the reply
to home's own _read_memory_wait(0x0421) also fires position_updated
(ruida_client.py:171-186) -> _on_position_updated:1087, which merges the
fresh x with the stale cached y. Y stays pre-home until the next poll, and
any jog in that window builds an absolute D9 10 target from it. The window
is widened by home() returning early (see the 0x0421 completion-wait
finding).

**Proposed fix**

Set `self._last_known_pos = None` in home()'s finally (paired with the
_jog_origin fix so a None cache forces a fresh read rather than fabricating
(0,0)). Do the same in _disconnect_transports so a reconnect never inherits
a pre-disconnect cache.

**Test strategy**

ruida_simulator over UDP (the `ruida_simulator` fixture in
tests/machine/driver/ruida/test_ruida_driver.py): set sim.state.x/y to
(300000, 200000), seed driver._last_known_pos from read_position(), call
`await driver.home()`, assert driver._last_known_pos is None (or (0, 0))
rather than (0, 200000).

**Hardware check:** Confirm the controller reports 0x0431 as 0 only once homing has completed.
Note that on real hardware _read_memory_wait(0x0421) at line 608 resolves on
the FIRST 0x0421 response — including a mid-home one, or one elicited by the
concurrent poller — so home() can return while the head is still travelling,
widening this window considerably.

---

### MOT-24 - Go Scale outlines the box at the current head position, but the job (and Cut Scale) cut it at the REF0 anchor

- **Severity:** DEGRADED
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:638`
- **Class:** Failure class 2 — sign / axis / frame errors in the interactive-motion subsystem (jog arrows → D9 10 payload, Go Scale / Cut Scale framing)
- **Status:** DEFERRED - anchoring the trace at REF0 rather than at the head changes what Go Scale means, and depends on REF0 semantics this repository cannot confirm (see MOT-38). It is a behaviour decision for the user, not a repair. What is fixed is the part that was unambiguously wrong: an outline that runs off the bed is now refused rather than clamped into a rectangle that is not the job's (MOT-30).

**Evidence**

```python
        start = await self._client.read_position()
        if start is None:
            start = self._last_known_pos or (0, 0)
        self._last_known_pos = start
        corners = [
            (start[0] + dx, start[1] + dy)
            for dx, dy in (
                (0, 0),
                (width_um, 0),
                (width_um, height_um),
                (0, height_um),
                (0, 0),
            )
        ]
```

**Expected**

Driver.trace_frame's contract (driver/driver.py:561-573) is 'Trace a
rectangle of the given size around the job origin', and the button tooltip
is 'Traverse the job outline with the laser off'. The Ruida job stream is
anchored: RuidaEncoder sets JOB_REF_POINT = 'REF0' (ruida_encoder.py:58,
emitting D8 12) and re-bases every coordinate on the job's own minimum
(`self.origin_um = (self._mm_to_um(rect[0]), self._mm_to_um(rect[1]))`,
ruida_encoder.py:839-843). So the job physically cuts at anchor + (0..w,
0..h), and Go Scale must trace anchor + (0..w, 0..h) too. Cut Scale already
does: _cut_scale_ops builds _rect_corners(width, height) starting at (0, 0)
(cmd.py:707-715, 734), which the encoder re-bases to the same anchor.

**Actual**

Go Scale builds its five corners from `read_position()` -- wherever the head
happens to be parked -- so the outline is offset from the real cut by (head
- anchor). tests/machine/driver/ruida/test_ruida_scale_jobs.py::test_corners
_are_offset_from_the_start_position pins this behaviour: with the head at
(60000, 40000) and a 100x50 job the corners are (60,40)-(160,90) mm.
Concretely: anchor set at machine (20, 20) mm, job 100x50 mm, operator homes
(head at 0,0) and presses Go Scale -> the pointer outlines (0,0)-(100,50);
pressing Start then cuts (20,20)-(120,70). The operator aligns material to a
rectangle 28 mm away from where the laser actually fires, so the cut runs
off the stock. Pressing Go Scale and then Cut Scale in the same session
traces two different rectangles. MachineCmd._trace_frame compounds it by
discarding the outline's position entirely (cmd.py:479-481: `min_x, min_y,
max_x, max_y = artifact.ops.rect()` followed by `await
driver.trace_frame(max_x - min_x, max_y - min_y)`).

**Verification**

Both halves confirmed. trace_frame:637-651 builds corners from
read_position() (0x0421/0x0431 = 'Current X/Y', ruida_maps.py:552-553), and
the driver's own log says 'from the current position' (631-634). The job
stream is anchored: ruida_encoder.py:58 JOB_REF_POINT='REF0' emitted at
834/850, and 839-843 re-bases coordinates onto ops.rect()'s minimum. Cut
Scale builds _rect_corners from (0,0) (cmd.py:707-715, 734) so it lands on
the same anchor. cmd.py:479-481 does discard the outline's position.
tests/machine/driver/ruida/test_ruida_scale_jobs.py:109-123 pins the head-
relative behaviour exactly as quoted. Severity corrected from BROKEN: a
correctly sized rectangle is traced, and it coincides with the cut whenever
the head sits at the anchor - it is misplaced only when it does not.

**Proposed fix**

Anchor the trace where the job anchors. In RuidaDriver.trace_frame, replace
the read_position() start with the REF0 offset the encoder uses: `off =
await self._client.get_ref_point_offset(ruida_encoder.JOB_REF_POINT)` (the
client already exposes it via REF_POINT_OFFSET_ADDRESSES 0x0224/0x0234),
falling back to read_position() only when the read fails, and log which
anchor was used. Keep the width/height signature -- because the encoder re-
bases the job to its own minimum, w/h plus the anchor is exactly enough to
reproduce the cut rectangle. Correct the Ruida trace_frame docstring, which
currently advertises 'built from the head position the trace starts at' as
if that were the intent.

**Test strategy**

Extend the _ScaleClientSpy in
tests/machine/driver/ruida/test_ruida_scale_jobs.py with `async def
get_ref_point_offset(self, ref)` returning (50000, 25000) while
read_position() returns a different point (e.g. (200000, 180000)). Assert
trace_frame(100.0, 50.0) emits corners (50,25), (150,25), (150,75), (50,75),
(50,25) mm -- i.e. that the traced box follows the anchor and is independent
of where the head is parked. Pair it with an encoder assertion that
_cut_scale_ops(machine, 100, 50, ...) produces the same rectangle relative
to the same D8 12 anchor, so the two scale actions are locked together by
test.

**Hardware check:** Set the panel Origin key somewhere away from home, home the machine, press
Go Scale, mark the traced rectangle, then run the job (or Cut Scale) and
compare. The offset between the two rectangles equals the anchor.

---

### MOT-25 - _suppress_polling is one boolean with two owners: trace_frame's exit re-enables position polling in the middle of a job upload

- **Severity:** DEGRADED
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:653`
- **Class:** Failure class 3 — state desync of RuidaDriver._last_known_pos and _jog_busy (full read/write lifecycle, leak analysis, plus the shared _suppress_polling flag)
- **Status:** FIXED 47a49acd0

**Evidence**

```python
        self._suppress_polling = True
        self._jog_busy = True
```

**Expected**

run()'s own comment at lines 480-481: "The proven sender had no concurrent
traffic: keepalive and position polling stay suspended for the whole send."

**Actual**

run() sets _suppress_polling True at line 478 and clears it in its finally
at line 495; trace_frame sets it True at line 653 and clears it in its
finally at line 667. They are independent tasks on the same loop and both
are reachable from the UI at the same time —
JogWidget._update_button_sensitivity only gates Go Scale on connected +
has_job_ops (jog_widget.py:745-747), never on a running job, so the Start
and Go Scale buttons are both live during an upload. Whichever finishes
first clears the other's suspension. Probed: with _suppress_polling pre-set
True (as run() leaves it), `await driver.trace_frame(10, 10)` returned with
_suppress_polling == False. The connection loop (lines 352-380) then resumes
DA position reads and ref-point-mode polling on the same socket while
send_job is still chunking. Symmetrically, run()'s finally re-enables
polling in the middle of a trace, whose corner detection makes its own
read_position calls and whose _last_known_pos is then overwritten mid-trace
by _on_position_updated.

**Verification**

Confirmed: run() sets the flag at 478 and clears it in `finally` at 494-495;
trace_frame sets it at 653 and clears it in `finally` at 666-667. Neither
checks a prior owner. Concurrency is real - cmd.run_send_job uses key='send-
job' (cmd.py:396) and trace_frame key='trace-frame' (cmd.py:460), so neither
replaces the other, and jog_widget._update_scale_buttons:745-747 gates Go
Scale only on connected + has_job_ops while start_btn is enabled on
connection alone (jog_widget.py:422). The connection loop's poll and ref-
mode poll (352-359, 375-380) then resume on the same socket mid-upload,
against run()'s stated invariant at 480-481.

**Proposed fix**

Replace the boolean with a counter or a re-entrant suspend context:
`self._polling_suspensions += 1` on entry, `-= 1` in the finally, and poll
only while the count is 0. Separately, disable the Go Scale / Cut Scale
buttons while a job is running so the two scopes cannot overlap in the first
place.

**Test strategy**

Direct on the driver with the _ScaleClientSpy stub: set
driver._suppress_polling = True, `await driver.trace_frame(10.0, 10.0)`,
assert driver._suppress_polling is still True on return. Mirror it for run()
by pre-setting the flag and driving a stubbed send_job.

---

### MOT-26 - Go Scale hard-codes 100 mm/s and is the only travel path that ignores the profile's max travel speed

- **Severity:** DEGRADED
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:656`
- **Class:** Unit errors on the interactive-motion speed and distance paths (jog / hold-jog / Go Scale), from the human-facing control to the byte on the wire and back
- **Status:** FIXED 47a49acd0

**Evidence**

```python
    FRAME_SPEED_MM_S = 100                                      (line 79)
...
            await self._client.set_travel_speed(self.FRAME_SPEED_MM_S * 1000)   (line 656)

(every other travel path, lines 723-729)
    async def _set_max_travel_speed(self) -> None:
        """Stream C9 02 at the profile's max travel speed."""
        assert self._client
        speed_mm_min = (
            self._machine.max_travel_speed or self.DEFAULT_TRAVEL_SPEED
        )
        await self._client.set_travel_speed(int(speed_mm_min * 1000 / 60))
```

**Expected**

The arithmetic itself is right (100 mm/s x 1000 = 100000 um/s, and
ruida_server._handle_c9_command decodes C9 02 as `decode35(...)/1000.0`
mm/s, confirming um/s). But a traverse should not exceed the profile's
configured maximum travel speed, which homing and move_to both honour via
_set_max_travel_speed.

**Actual**

Go Scale commands 100 mm/s = 6000 mm/min unconditionally.
`Machine.max_travel_speed` defaults to 3000 mm/min
(rayforge/machine/models/machine.py:139), so on a default profile the trace
runs at double the machine's declared maximum, and on a slow gantry profile
(1500 mm/min) at four times. It is also the only site that converts a travel
speed into um/s from mm/s (x1000) instead of from mm/min (x1000/60), so "the
interactive travel speed" now has two independent conversion authorities in
one file -- three call sites open-code `int(x * 1000 / 60)` and this one
open-codes `x * 1000`.

**Verification**

Confirmed: ruida_driver.py:79/656 sends 100 mm/s = 100000 um/s = 6000
mm/min, while every other travel path goes through _set_max_travel_speed
(723-729) which honours machine.max_travel_speed, default 3000 mm/min
(machine.py:139). ruida_server._handle_c9_command:1030-1034 decodes C9 02 as
decode35/1000.0 mm/s, confirming the unit is um/s, so the arithmetic is
right and the excess is real. Also confirmed as the only x1000 (mm/s)
conversion against three x1000/60 (mm/min) sites (729, 794, 922).

**Proposed fix**

Route the trace through the existing single authority: replace line 656 with
`await self._set_max_travel_speed()` and delete FRAME_SPEED_MM_S, or, if a
deliberately slower alignment speed is wanted, keep the constant but clamp
it: `speed_mm_min = min(self.FRAME_SPEED_MM_S * 60,
self._machine.max_travel_speed or self.DEFAULT_TRAVEL_SPEED)` and feed it
through `_set_max_travel_speed`'s conversion so only one expression converts
mm/min to um/s.

**Test strategy**

tests/machine/driver/ruida/test_ruida_scale_jobs.py already asserts
`spy.commands[0] == b"\xc9\x02" + encode35(ruida_driver.FRAME_SPEED_MM_S *
1000)`; change it to set `machine.set_max_travel_speed(1500)` and assert the
emitted speed is `encode35(25000)` (25 mm/s), i.e. the trace never exceeds
the profile.

**Hardware check:** Whether 100 mm/s is physically safe on the target gantry is a machine
question; the controller may clamp it internally to its own max-speed
register. The host-side defect -- ignoring the profile the user configured
-- stands either way.

---

### MOT-27 - jog_key_up sets _jog_busy = True outside any try/finally; an error from _jog_to_limit leaks the flag and blocks every step jog

- **Severity:** DEGRADED
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:809`
- **Class:** Failure class 3 — state desync of RuidaDriver._last_known_pos and _jog_busy (full read/write lifecycle, leak analysis, plus the shared _suppress_polling flag)
- **Status:** FIXED 47a49acd0

**Evidence**

```python
        if self._jog_keys_down:
            # One half of a diagonal let go: keep going on the rest.
            self._jog_busy = True
            await self._jog_to_limit()
```

**Expected**

_jog_busy is a short-lived in-flight marker; no path may leave it True once
the coroutine that set it has returned or raised.

**Actual**

There is no try/finally here. Probed: hold x+1 and y+1, make the client's
rapid_move_xy raise OSError (socket dropped mid-hold), release x → the
OSError propagates out of jog_key_up leaving _jog_busy == True and
_jog_keys_down == {('y', 1)}. Every subsequent step jog is then swallowed by
the guard at line 905 (`if self._jog_busy: return`), so click-jogging is
dead until the user happens to release the remaining half or a disconnect
sweep runs _stop_jog_motion. The same shape exists in jog_key_down: its
handler at line 797 is `except (OSError, RuntimeError)`, which does not
cover asyncio.CancelledError (a BaseException — task-manager cancellation,
and cmd.jog_key_down schedules these coroutines unkeyed), AssertionError
(`assert self._client` inside _jog_origin/_jog_move_to if cleanup nulls the
client mid-hold, ruida_driver.py:282), or ValueError; any of those leaves
both _jog_busy True and the key still registered in _jog_keys_down.

**Verification**

Confirmed at ruida_driver.py:802-812: the `self._jog_busy = True` at 811 and
`await self._jog_to_limit()` at 812 sit in no try/finally, so an OSError out
of rapid_move_xy propagates with the flag still True; jog() then returns at
905 and jog_key_down returns at 784 for every later press, until
release_all_jog_keys sweeps. The secondary claim about jog_key_down's
`except (OSError, RuntimeError)` at 797 not covering
CancelledError/AssertionError is also correct - the coroutines are scheduled
unkeyed and cancellable (cmd.py:597-599, manager.py:206) and `assert
self._client` appears at 931/949.

**Proposed fix**

Wrap the tail of jog_key_up in `try: ... finally: self._jog_busy = False`
(discarding the remaining keys on failure), and change jog_key_down's
handler to catch BaseException — clearing the flag and the key, stopping the
motion, then re-raising CancelledError — or restructure both around a single
`finally` that clears _jog_busy the way jog() at line 926-927 already does.

**Test strategy**

_JogClientSpy: jog_key_down("x",1) and jog_key_down("y",1), then swap
spy.rapid_move_xy for a coroutine that raises OSError and call
jog_key_up("x",1) inside pytest.raises(OSError); assert driver._jog_busy is
False afterwards and that a following driver.jog(6000, x=10.0) still emits a
D9 command. Add a CancelledError variant for jog_key_down.

---

### MOT-28 - _stop_jog_motion leaves the commanded bed-limit target cached when the resync read fails, so the next step jog runs to the far end of the bed

- **Severity:** DEGRADED
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:845`
- **Class:** Failure class 3 — state desync of RuidaDriver._last_known_pos and _jog_busy (full read/write lifecycle, leak analysis, plus the shared _suppress_polling flag)
- **Status:** FIXED 47a49acd0
- **Phase 2:** reproduced by `tests/machine/driver/ruida/test_motion_audit.py::TestStopReachesEveryMotion::test_stop_resyncs_before_clearing_busy`

**Evidence**

```python
            pos = await self._client.read_position()
            if pos is not None:
                self._last_known_pos = pos
        except (OSError, RuntimeError) as e:
            logger.warning(f"Jog stop failed: {e}")
        finally:
            self._jog_busy = False
```

**Expected**

Per the docstring at lines 826-832, after a hold is halted "whatever comes
back is where the head actually ended up" — the cache holds where the head
parked.

**Actual**

_jog_to_limit -> _jog_move_to already wrote the COMMANDED bed-limit target
into _last_known_pos (line 956) before the head moved a millimetre. If the
resync read returns None, or stop_process/read_position raises
OSError/RuntimeError, nothing overwrites it and — critically — nothing
invalidates it either. Probed: hold east from x=100 mm on a 400 mm bed →
cache becomes (399000, 100000); release with the head really at 105 mm and
read_position returning None → cache stays (399000, 100000); the user's next
10 mm WEST step then commands D9 10 x=389000 — a 284 mm rapid EAST when the
user asked for 10 mm west. The ~1 Hz position poller normally repairs this
within a second, but not in the case that matters: when the failure IS the
link dying, _disconnect_transports -> release_all_jog_keys hits the same
failing resync, the poller is stopped, and nothing re-initialises
_last_known_pos on reconnect (no write on connect, on _connection_loop re-
entry, or on cleanup).

**Verification**

Code confirmed: _jog_move_to:956 writes the COMMANDED target (for a hold,
extent-1 mm) into _last_known_pos before any motion, and
_stop_jog_motion:843-851 only overwrites it `if pos is not None`, with no
invalidation on the None or the OSError/RuntimeError path, while `finally`
clears _jog_busy regardless. The next jog then measures from the bed limit
(929-936). The reconnect leg is also right - nothing re-initialises
_last_known_pos on connect or in _connection_loop. Severity corrected from
BROKEN to DEGRADED: it needs a failed read AND the ~1 Hz poller (which
writes the cache via _on_position_updated:1087/1090) to not repair it before
the next click; the finding itself concedes the repair path.

**Proposed fix**

Invalidate on failure rather than keeping the commanded target:
`self._last_known_pos = pos` unconditionally (None included), and add
`self._last_known_pos = None` in the except branch. This is only safe
together with the _jog_origin fix above, so a None cache forces a fresh read
instead of fabricating (0,0). Also set `self._last_known_pos = None` in
_disconnect_transports / at the top of each _connection_loop iteration.

**Test strategy**

_JogClientSpy with a read_returns_pos switch: jog_key_down("x", 1), flip
read_position to return None, jog_key_up("x", 1); assert
driver._last_known_pos is None (today it is the bed-limit target (399000,
100000)), and that a following jog(6000, x=-10.0) either re-reads or emits
nothing.

---

### MOT-29 - _stop_jog_motion clears _jog_busy regardless of who owns it, dropping Go Scale's ignore interlock

- **Severity:** DEGRADED
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:850`
- **Class:** Failure class 5 — queue / ignore semantics (input during motion must be IGNORED, never QUEUED, at every layer including the transport)
- **Status:** FIXED 47a49acd0

**Evidence**

```python
        finally:
            self._jog_busy = False
```

**Expected**

_jog_busy is the single interlock that makes input during motion be IGNORED.
While Go Scale is running (trace_frame sets _jog_busy = True at line 654)
every jog() and jog_key_down() must keep being ignored for the whole run.

**Actual**

_jog_busy is a bare bool with no notion of an owner, and _stop_jog_motion
unconditionally clears it in its finally. release_all_jog_keys (line 822:
`if keys or self._jog_busy:`) therefore calls _stop_jog_motion during a
frame purely BECAUSE the frame set the flag — and clears it. The widget
calls release_all_jog_keys on window focus loss, unmap and set_machine
(jog_widget.py:531), all of which happen freely mid-Go-Scale. From that
point until trace_frame's finally, `if self._jog_busy and not holding:
return` (line 784) and `if self._jog_busy: return` (line 905) both pass: an
arrow press is accepted mid-frame, adds itself to _jog_keys_down and issues
its own run-to-limit D9 that fights the frame's corner moves. The same hole
opens for a single-step jog() still inside _wait_for_jog_settled when
release_all_jog_keys runs.

**Verification**

Real and distinct from the 'frame resumes' finding (same root flag,
different consequence and different fix). _jog_busy is a bare bool;
_stop_jog_motion clears it in `finally` at 850-851 with no owner check, and
release_all_jog_keys:822 calls it during a frame precisely because the frame
set the flag at 654. From then until trace_frame's finally at 669, `if
self._jog_busy and not holding: return` (784) and `if self._jog_busy:
return` (905) both pass, so a jog press is accepted mid-frame, registers in
_jog_keys_down and issues its own run-to-limit D9 10 against the frame's
corner moves. Severity corrected from BROKEN: the interlock works normally
and fails only after a stop path fires mid-frame.

**Proposed fix**

Replace the bool with an owner token, e.g. self._motion_owner: str | None
taking "jog" / "frame" / None, set by whoever starts the motion and cleared
only by that owner (`if self._motion_owner == owner: self._motion_owner =
None`). _stop_jog_motion takes an `owner` argument and only clears when it
matches. The ignore guards become `if self._motion_owner is not None and not
holding: return`. Minimum viable alternative if that refactor is too wide:
give trace_frame its own self._frame_running flag and have both ignore
guards test `self._jog_busy or self._frame_running`.

**Test strategy**

_JogClientSpy-style stub client, direct driver call (reproduced, currently
fails): hook spy.rapid_move_xy so that after the 2nd corner it awaits
driver.release_all_jog_keys() and then driver.jog_key_down("x", 1); assert
driver._jog_keys_down == set() at that point. Observed: {('x', 1)} — the jog
was accepted during Go Scale.

**Hardware check:** None.

---

### MOT-30 - Go Scale corners are silently clamped to the bed, so the traced rectangle is not the job's size

- **Severity:** DEGRADED
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:951`
- **Class:** Failure class 2 — sign / axis / frame errors in the interactive-motion subsystem (jog arrows → D9 10 payload, Go Scale / Cut Scale framing)
- **Status:** FIXED 47a49acd0

**Evidence**

```python
        bed_w_mm, bed_h_mm = self._machine.axis_extents
        x_um = max(0, min(x_um, int(bed_w_mm * 1000)))
        y_um = max(0, min(y_um, int(bed_h_mm * 1000)))
        await self._client.rapid_move_xy(x_um, y_um)
```

**Expected**

Go Scale is an alignment aid: the traced rectangle must be the job's
bounding box, or the operator must be told it could not be traced. A box
that does not fit from the chosen start is a user error worth a warning, not
a silent reshape.

**Actual**

trace_frame builds its corners as start + (width, height) (line 642-651) and
pushes each through _jog_move_to, whose clamp rewrites any corner that
leaves the bed. Head parked at machine (350, 250) on a 400x300 bed, job
100x50 mm: the corner (450000, 250000) is clamped to (400000, 250000), so
the pointer traces a 50x50 box instead of 100x50. _wait_for_frame_corner is
handed the clamped target (line 664-665 `target = await
self._jog_move_to(...)`), so it reaches it immediately and nothing times out
-- the run completes cleanly and the operator sees a wrong-sized outline
with no indication anything was truncated. The clamp is also the mechanism
that voids the 1 mm JOG_LIMIT_MARGIN_MM protection described in finding 1.

**Verification**

Confirmed: _jog_move_to:950-952 clamps every target to 0..axis_extents and
returns the CLAMPED tuple, which trace_frame:664-665 hands straight to
_wait_for_frame_corner, so a truncated corner compares equal to its own
clamped target and the run completes with no warning. trace_frame:642-651
does build corners as start + (width, height) with no fit check, so a job
that does not fit from the start position traces a smaller rectangle
silently.

**Proposed fix**

Separate 'clamp' from 'refuse'. In trace_frame, compute all five corners
first and, if any falls outside the bed (or outside
machine.get_soft_limits()), log a warning naming the overhang and abort the
trace before the first move rather than tracing a deformed box. Leave
_jog_move_to's clamp for the jog paths only, and make it clamp against
get_soft_limits() rather than 0..extent so it stays correct under reversed
axes.

**Test strategy**

_ScaleClientSpy in tests/machine/driver/ruida/test_ruida_scale_jobs.py: set
the driver machine to set_axis_extents(400, 300), spy position (350000,
250000), `await ruida_driver.trace_frame(100.0, 50.0)`. Assert either that
no D9 10 was emitted and a warning was logged (caplog), or that the five
corners still describe a 100x50 rectangle -- currently they describe 50x50.

---

### MOT-31 - _on_position_updated invents 0 for the axis it has not seen yet, so a jog landing between the X and Y position responses drives Y to the bed edge

- **Severity:** DEGRADED
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:1083`
- **Class:** Unit errors on the interactive-motion speed and distance paths (jog / hold-jog / Go Scale), from the human-facing control to the byte on the wire and back
- **Status:** FIXED 47a49acd0
- **Phase 2:** reproduced by `tests/machine/driver/ruida/test_motion_audit.py::TestOriginIsNeverInvented::test_partial_position_update_does_not_invent_the_other`

**Evidence**

```python
        pos_mm = value_um / 1000.0
        current_pos = self.state.machine_pos
        last_x, last_y = self._last_known_pos or (0, 0)

        if axis == "x":
            new_pos = (pos_mm, current_pos[1], current_pos[2])
            self._last_known_pos = (value_um, last_y)
```

**Expected**

_last_known_pos is the origin every absolute D9 10 jog target is built from,
so it must never contain a coordinate that was not actually read back from
the controller.

**Actual**

`get_position()` issues three separate DA reads (0x0421, 0x0431, 0x0441) and
their replies arrive as separate datagrams. On the first poll after connect,
`_last_known_pos` is still None, so the X reply publishes `(real_x, 0)` -- a
fabricated Y. Any jog whose `_jog_origin()` runs in the window between the X
and Y callbacks (both are plain coroutine callbacks on the same loop, and
jog tasks are scheduled independently by the task manager) takes Y = 0 as
its origin and commands an absolute D9 10 to `(x + dx, 0 + dy)`: on a 300 mm
bed with the head at Y = 150 mm, a pure X jog also slams Y to the front
edge. The window is narrow -- it exists once per driver instance, right
after connect -- which is why this is a race rather than a certainty.

**Verification**

Confirmed at ruida_driver.py:1083-1090: with _last_known_pos None, an x-only
update writes (value_um, 0) - a y coordinate never read back - and
get_position() (ruida_client.py:836-838) does fire 0x0421/0x0431/0x0441 as
three separate requests whose replies arrive as separate datagrams handled
in separate loop callbacks. A jog issued in that window, or after a dropped
0x0431 reply, takes y=0 as the absolute origin. Kept at DEGRADED rather than
SAFETY: the fabricated value only survives until the next poll and requires
a race or a dropped datagram.

**Proposed fix**

Do not publish a partial position. Track the two axes separately
(`self._last_x_um`, `self._last_y_um`, both Optional) and expose
`_last_known_pos` as a property that returns None unless both are known;
`_jog_origin` then falls into its read_position path (and, with finding 1
fixed, refuses to move when that fails) instead of using an invented zero.

**Test strategy**

Direct driver-method invocation, no client needed: set
`driver._last_known_pos = None`, call `driver._on_position_updated(None,
axis='x', value_um=250000)`, and assert `driver._last_known_pos` is still
None (or that the Y component is not 0). Then deliver the Y update and
assert both components are present.

---

### MOT-32 - Jog speed round-trips base -> display -> int(mm/s) -> base, quantising to 60 mm/min steps and forcing a 60 mm/min floor at the bottom of the row's range

- **Severity:** DEGRADED
- **Location:** `rayforge/ui_gtk/doceditor/bottom_panel.py:461`
- **Class:** Unit errors on the interactive-motion speed and distance paths (jog / hold-jog / Go Scale), from the human-facing control to the byte on the wire and back
- **Status:** FIXED cd33192d1

**Evidence**

```python
bottom_panel.py:454-461 `def _on_speed_changed(self, row): ... display = _JOG_SPEED_UNIT.from_base(self.speed_row.get_value_in_base_units()); self.jog_widget.set_jog_speed(max(1, round(display)))` — quote is verbatim; line 461 is the set_jog_speed call.
```

**Expected**

The mm/min value the user picked in the row should reach the driver
unchanged; the row's declared range is `lower=1, upper=60000` base units,
i.e. it advertises 1 mm/min resolution.

**Actual**

The value is converted a second time (base -> mm/s), rounded to a whole
mm/s, then converted back (`int(_JOG_SPEED_UNIT.to_base(self.jog_speed))` in
jog_widget.py:611 and 675). Only multiples of 60 mm/min survive: a user who
types 16.67 mm/s (1000 mm/min) gets 17 mm/s = 1020 mm/min on the wire while
the row keeps displaying 16.67. At the low end of the advertised range the
error is not a rounding error but a factor: any request below 30 mm/min
rounds to 0 mm/s, and `max(1, ...)` then floors it to 1 mm/s = 60 mm/min --
a request for the row's minimum of 1 mm/min produces 60 mm/min, 60x too
fast, which is exactly the regime (slow, careful positioning) where a user
asks for a low jog speed.

**Verification**

Verified end to end. definitions.py sets the speed base unit to mm/min
(`set_base_unit("speed", "mm/min")`) and mm/s is the display unit, so
`_JOG_SPEED_UNIT.from_base()` at bottom_panel.py:458 divides by 60.
`round(...)` then collapses to whole mm/s, and jog_widget.py:598 stores it
as `int(speed_mm_s)`; both consumers multiply back by 60 —
`int(_JOG_SPEED_UNIT.to_base(self.jog_speed))` at jog_widget.py:611
(_commit_jog_speed -> machine_cmd.set_jog_speed) and :675 (_perform_jog ->
machine_cmd.jog). Driver.jog/set_jog_speed docstrings (driver.py:657, 715)
confirm the parameter is mm/min, and ruida_driver.py:891 stores it verbatim
as `_jog_speed_mm_min`, so the quantised value reaches the wire with no
further correction. I ran the round-trip numerically: 1000 mm/min -> 16.6667
mm/s -> 17 -> 1020 mm/min; 1, 10, 29 and 30 mm/min all -> 60 mm/min
(round(0.5) is 0 under banker's rounding, then `max(1, ...)` floors it to 1
mm/s). The row genuinely advertises that range: SpeedSpinRow is built with
lower=1, upper=60000 (bottom_panel.py:435-436) and UnitSpinRow treats
lower/upper as base units (unit_spin_row.py:109-110, docstring lines 22-24),
so the adjustment's display lower is 1/60 = 0.0167 mm/s and
`_get_display_value` clamps to it — a user at the row minimum really does
get 60 mm/min sent. No guard corrects this anywhere: `_on_speed_changed`
never writes back to the row, so the displayed value and the transmitted
value diverge silently, and the row's digits are max(unit.precision=1,
min_digits=2) = 2, i.e. it accepts and shows hundredths of a mm/s that the
handler then discards. Severity stays DEGRADED rather than SAFETY: the head
only moves when a jog is actually requested and hold-jog release/stop paths
are unaffected — the defect is that the commanded speed is wrong (2x-60x too
fast at the low end, ~2% at typical speeds), not that motion happens
uncommanded or cannot be stopped. Not a duplicate; it is the only finding in
the list.

**Proposed fix**

Stop the display round-trip: have JogWidget carry the jog speed in
application base units (`self.jog_speed_mm_min`) and let `_on_speed_changed`
pass `self.speed_row.get_value_in_base_units()` straight through.
`_commit_jog_speed` and `_perform_jog` then send that value with no
conversion at all, and `_JOG_SPEED_UNIT` is only needed for display. If the
widget must keep a display-unit field, drop the `round()`/`int()` and keep
it a float.

**Test strategy**

Direct handler invocation on bottom_panel with a MagicMock jog_widget:
`speed_row.set_value_in_base_units(1)`, fire `_on_speed_changed`, assert the
value that reaches `machine_cmd.set_jog_speed` is 1, not 60. Repeat with
1000 -> assert 1000, not 1020.

---

### MOT-33 - JogWidget.jog_speed defaults to 100 mm/s, six times the Jog Speed row's own default, so a click-jog runs at 6000 mm/min while the panel reads 1000 mm/min

- **Severity:** DEGRADED
- **Location:** `rayforge/ui_gtk/machine/jog_widget.py:62`
- **Class:** Unit errors on the interactive-motion speed and distance paths (jog / hold-jog / Go Scale), from the human-facing control to the byte on the wire and back
- **Status:** FIXED cd33192d1

**Evidence**

```python
        self.jog_speed = 100  # mm/s
        self.jog_distance = 10.0

(consumed at lines 672-676)
            self.machine_cmd.jog(
                self.machine,
                deltas,
                int(_JOG_SPEED_UNIT.to_base(self.jog_speed)),
            )
```

**Expected**

The widget's default jog speed should be the same value the Jog Speed row is
constructed with -- `value_in_base=1000` mm/min, displayed as 16.67 mm/s
(rayforge/ui_gtk/doceditor/bottom_panel.py:432-438). `jog_distance = 10.0`
correctly mirrors the distance row's `value_in_base=10.0`; the speed default
does not mirror its row.

**Actual**

`_JOG_SPEED_UNIT.to_base(100)` is 6000.0 (verified: mm/s -> mm/min is x60),
so a short press -- which `_on_jog_released` routes to `_perform_visual_jog`
-> `machine_cmd.jog` -> `RuidaDriver.jog(6000, ...)` ->
`set_travel_speed(100000)` -- moves the head at 100 mm/s while the panel
displays 16.67 mm/s. Because UnitSpinRow suppresses value_changed on
construction, this default survives until the user actually edits the row.
The same widget is embedded in the print-and-cut wizard, which sets
jog_distance but never jog_speed, so it always click-jogs at 100 mm/s.

**Verification**

Verified end to end. jog_widget.py:62 `self.jog_speed = 100 # mm/s`;
_JOG_SPEED_UNIT is get_unit("mm/s") (line 14) and definitions.py:111
`set_base_unit("speed", "mm/min")`, so to_base(100)=6000.
bottom_panel.py:432-438 builds the Jog Speed row with value_in_base=1000
(mm/min = 16.67 mm/s). UnitSpinRow.__init__ (unit_spin_row.py:68-76) sets
the initial value inside `self._is_updating = True`, so value_changed never
fires at construction and _on_speed_changed (bottom_panel.py:454-461) never
runs until the user edits the row; _update_wcs_ui() (line 645) touches no
jog speed. Consumption at jog_widget.py:672-676 -> MachineCmd.jog ->
RuidaDriver.jog (ruida_driver.py:897) ->
`set_travel_speed(int(speed*1000/60))` = 100000, i.e. 100 mm/s. wizard.py
sets only jog_distance (lines 611, 615), never jog_speed, so the print-and-
cut widget always click-jogs at 100 mm/s. Severity lowered from BROKEN: the
jog does happen, in the right direction and the right distance -- it is the
speed that is wrong, which is DEGRADED ("works, but wrongly"), not an absent
behaviour.

**Proposed fix**

Delete the magic literal and let one place own the default: keep the
widget's speed in base units (`self.jog_speed_mm_min = 1000`) seeded from
the same constant the row uses, or have bottom_panel push the row's value
into the widget once at construction
(`self._on_speed_changed(self.speed_row)`). Both this and the driver-side
default (finding 2) should end up reading one constant.

**Test strategy**

Direct widget handler invocation
(tests/ui_gtk/machine/test_jog_widget_hold.py style, MagicMock machine_cmd,
no hold-jog driver so the release path takes the step branch): call
`widget._on_jog_released(None, 1, 0.0, 0.0, (JogDirection.EAST,))` on a
freshly constructed widget and assert the third positional argument to
`machine_cmd.jog` is 1000, not 6000.

---

### MOT-34 - Arrow-key jog has no key-release handler and no repeat guard; each repeat queues an unkeyed task

- **Severity:** DEGRADED
- **Location:** `rayforge/ui_gtk/machine/jog_widget.py:222`
- **Class:** FAILURE CLASS 8 — UI handler wiring in rayforge/ui_gtk/machine/jog_widget.py (connection, ownership, and teardown of the interactive-motion handlers)
- **Status:** FIXED d426885ac

**Evidence**

```python
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)
```

**Expected**

Holding an arrow key should behave like holding an arrow button — one
bounded motion that ends when the key is released — or at minimum should not
command more travel than the user asked for.

**Actual**

Only "key-pressed" is connected; there is no "key-released" handler and no
state tracking of which keyvals are down. _on_key_pressed (818-843) routes
each repeat straight into _perform_visual_jog -> _perform_jog ->
MachineCmd.jog, which schedules an UNKEYED coroutine (cmd.py:422-428, no
`key=` argument), so Task.key falls back to id(self)
(shared/tasker/task.py:33) and every repeat becomes a separate live task
instead of replacing the previous one. X11/Wayland autorepeat is ~25-30
events/s, so two seconds on the Left arrow queues ~50 jog tasks of
jog_distance mm each (default 10 mm from bottom_panel.py:447) = ~500 mm of
commanded travel. The widget itself has no busy flag at all; on Ruida the
driver absorbs the excess (`if self._jog_busy: return`,
ruida_driver.py:905-906), but GRBL's jog() has no such guard
(grbl/grbl_serial.py:1178-1199 emits a $J= per call), so the queued jogs
land in the planner buffer and the head keeps moving well after the key is
released. The keyboard path also ignores can_hold_jog() entirely, so on a
Ruida the keyboard and the buttons behave differently.

**Verification**

Every link checked. jog_widget.py:222-224 connects only "key-pressed"; there
is no "key-released" handler and no keyval bookkeeping anywhere in the file.
_on_key_pressed (818-843) routes each event straight to _on_y_plus_clicked
etc. -> _perform_visual_jog -> _perform_jog -> MachineCmd.jog
(cmd.py:422-428), which calls add_coroutine with no `key=`; Task.__init__
then does `self.key = key if key is not None else id(self)`
(shared/tasker/task.py:33), so every repeat is a distinct live task rather
than replacing the previous one. RuidaDriver.jog does guard with `if
self._jog_busy: return` (ruida_driver.py:905-906), but GRBL's jog
(grbl/grbl_serial.py:1178-1199) has no busy flag and emits one $J= per call,
so the excess lands in the planner buffer. can_hold_jog() is only overridden
by RuidaDriver (ruida_driver.py:765), so the keyboard/button divergence on
Ruida is real too. DEGRADED confirmed rather than SAFETY: each queued move
is a bounded jog_distance step the user's own (auto-repeated) key presses
requested, and feed-hold/stop still works.

**Proposed fix**

Track pressed keyvals: ignore a key-pressed whose keyval is already in the
set (that removes autorepeat), connect "key-released" on the same controller
and route the arrows through _press_jog_key/_release_jog_key when
_hold_jog_supported(), falling back to a single _perform_visual_jog per
press otherwise. Also give MachineCmd.jog a task key (e.g. key="jog") so a
pending step jog is replaced rather than stacked.

**Test strategy**

Direct handler invocation: call widget._on_key_pressed(None, Gdk.KEY_Left,
0, 0) thirty times with a MagicMock machine_cmd and assert
machine_cmd.jog.call_count == 1; then call the new _on_key_released and
assert jog_key_up/no further motion. Cross-check the task keying with a fake
TaskManager asserting a single live task key.

**Hardware check:** Focus the jog pad, hold Left for ~2 s, release. On a GRBL machine the head
keeps travelling after the key is up; count $J= lines in the serial log.

---

### MOT-35 - _update_button_sensitivity flips every jog button insensitive, which cancels an in-flight press

- **Severity:** DEGRADED
- **Location:** `rayforge/ui_gtk/machine/jog_widget.py:374`
- **Class:** FAILURE CLASS 8 — UI handler wiring in rayforge/ui_gtk/machine/jog_widget.py (connection, ownership, and teardown of the interactive-motion handlers)
- **Status:** FIXED d426885ac

**Evidence**

```python
        # Default all buttons to disabled
        self.east_btn.set_sensitive(False)
        self.west_btn.set_sensitive(False)
        self.north_btn.set_sensitive(False)
```

**Expected**

Recomputing sensitivity is a display concern and must not disturb a jog the
user is currently holding.

**Actual**

The method unconditionally writes False to every button and then writes the
real value back. gtk_widget_set_sensitive early-returns only when the value
is UNCHANGED, so the False write is a real state change on an enabled
button; verified in libgtk-4.1.dylib at 0x240288-0x24029c, where the
sensitivity change walks the widget's controller list calling `bl
_gtk_event_controller_reset` on each. Resetting a GtkGestureClick with a
live sequence emits "cancel", so _on_jog_cancelled fires and the hold ends
mid-motion with the user's finger still down — and it does not resume,
because no new press event will arrive. Good news for the safety question:
the keys ARE released on this path, so no key is left stuck. Trigger is any
machine.changed emission during a hold (_on_machine_changed, line 345), e.g.
an edit in the machine settings or a WCS/extent change from another panel —
not a routine poll, since device_state updates go to state_changed and only
touch CSS classes.

**Verification**

Both halves verified. jog_widget.py:373-389 writes False to all sixteen
buttons unconditionally before recomputing. Disassembling
_gtk_widget_set_sensitive in libgtk-4.1.dylib: 0x2401e4-0x2401fc computes
new_sensitive XOR !old_sensitive and `tbz` falls through only when the value
is UNCHANGED; on a change it reaches 0x240278, stores the bit, and runs the
inlined loop at 0x240288-0x24029c walking the widget's controller list with
`bl 0x97530 <_gtk_event_controller_reset>`. Resetting a GtkGestureClick with
a live sequence cancels it, which fires the "cancel" handler connected at
line 254 -> _on_jog_cancelled -> keys released mid-hold with the finger
still down, and no new press event follows. Reachability is narrow but real:
the trigger is machine.changed (_on_machine_changed, 345-348), which Machine
only emits from genuine setter changes -- set_active_wcs
(machine.py:1363-1375) and set_unit_system are value-guarded, and
device_state updates go to state_changed which only touches CSS and the
position label. Confidence was rated low; the mechanism is confirmed, the
trigger is uncommon. DEGRADED is correct -- notably the keys ARE released on
this path, so nothing is left moving.

**Proposed fix**

Compute each button's target value once and write it once (drop the blanket
`set_sensitive(False)` prologue; for the not-connected early return, write
False explicitly there). GTK then no-ops the writes that do not change, and
an in-flight press survives an unrelated machine.changed.

**Test strategy**

Direct invocation with a spy: patch each jog button's set_sensitive and call
_update_button_sensitivity() twice on a connected machine; assert no call
with False is made on the second pass. The gesture-cancel consequence itself
is a GTK behaviour, confirmed by the disassembly above.

---

### MOT-36 - One hold timer for every arrow: a second press kills the first's hold, and any release kills whichever hold is armed

- **Severity:** DEGRADED
- **Location:** `rayforge/ui_gtk/machine/jog_widget.py:551`
- **Class:** Failure class 5 — queue / ignore semantics (input during motion must be IGNORED, never QUEUED, at every layer including the transport)
- **Status:** FIXED d426885ac

**Evidence**

```python
        self._cancel_pending_hold()
        self._hold_timeout_id = GLib.timeout_add(
            _HOLD_START_DELAY_MS, self._start_hold, directions
        )
```

**Expected**

Each arrow's press independently either becomes a hold after 200 ms or, if
released sooner, moves exactly one step (jog_widget.py:557-559: "A press too
short to become a hold is a click: one step of the step-size control").
Pressing one arrow must not change what another arrow does.

**Actual**

_hold_timeout_id (line 71) is a single int with no record of which
directions armed it, and _cancel_pending_hold() (line 533) cancels whatever
is in it. Mash East then North inside the 200 ms window (two fingers on a
touch panel, or any multi-pointer input): North's press cancels East's
timer; East's release then calls _cancel_pending_hold(), which cancels
NORTH's timer, returns True, and step-jogs East. When North is finally
released, _cancel_pending_hold() returns False and _hold_jog_supported() is
True, so control falls to `for key in self._jog_keys(*directions):
self._release_jog_key(key)` — the key was never in _keys_down, so it does
nothing. The North button was pressed and released and produced no motion at
all: no hold, no step. It is dead until pressed again. Nothing is left
moving, so this is not a stuck head — but the arrow silently ignores the
user.

**Verification**

Code matches: _hold_timeout_id is a single int (line 71) with no owner,
_cancel_pending_hold() (533-539) drops whatever is armed, _on_jog_pressed
(548-554) unconditionally cancels before arming, and _on_jog_released
(556-564) branches on _cancel_pending_hold()'s return. I traced the stated
sequence: press EAST (arms), press NORTH within 200 ms (cancels EAST's
timer, arms its own), release EAST (cancels NORTH's timer, returns True,
step-jogs EAST), release NORTH (returns False, _hold_jog_supported() True,
so the release loop runs and finds ('y',1) absent from _keys_down) -- NORTH
produces no motion at all. Reachable only with two live pointer sequences:
each button owns its own Gtk.GestureClick (line 248-255) and GestureSingle
is not touch-only, so two fingers on a touch panel (or touch+mouse) does it;
a single mouse cannot. Severity lowered from BROKEN to DEGRADED: the arrows
work correctly on the single-pointer path and fail only under that
concurrency condition.

**Proposed fix**

Key the pending hold by the directions that armed it: `self._pending_holds:
dict[tuple[JogDirection, ...], int] = {}`. _on_jog_pressed stores
`self._pending_holds[directions] = GLib.timeout_add(...)`;
_cancel_pending_hold(directions) pops and removes only that entry and
returns whether one was pending; _start_hold pops its own entry before
pressing keys; _release_all_jog_keys drains and removes every entry. Every
existing call site already has `directions` in hand.

**Test strategy**

Direct widget handler invocation under `pixi run uitest`, with
jog_widget.GLib.timeout_add / source_remove patched to record ids
(reproduced, currently fails): press EAST, press NORTH, release EAST,
release NORTH; assert machine_cmd.jog.call_count == 2. Observed: timers [1,
2] added, [1, 2] removed, only one jog call ({Axis.X: 10.0}) and zero
jog_key_down calls — the North press vanished.

**Hardware check:** None — pure GTK-side bookkeeping.

---

### MOT-37 - Held keys are released by (axis,sign) identity, not by the button that pressed them

- **Severity:** DEGRADED
- **Location:** `rayforge/ui_gtk/machine/jog_widget.py:571`
- **Class:** FAILURE CLASS 8 — UI handler wiring in rayforge/ui_gtk/machine/jog_widget.py (connection, ownership, and teardown of the interactive-motion handlers)
- **Status:** FIXED d426885ac

**Evidence**

```python
    def _on_jog_leave(self, controller, directions):
        self._cancel_pending_hold()
        for key in self._jog_keys(*directions):
            self._release_jog_key(key)
```

**Expected**

A release/leave/cancel on button B must only end the motion B started.
Ending a hold the user is still pressing on button A is a wrong-direction
stop.

**Actual**

self._keys_down (line 66) is a flat set of (axis, sign) tuples with no owner
and no refcount, and _on_jog_leave (571), _on_jog_released (556) and
_on_jog_cancelled (566) all release every key their OWN directions map to.
Diagonal buttons alias the cardinals: north_east_btn is attached with (EAST,
NORTH) (line 113) and MachinePanel.calculate_jog maps those to {Axis.X:+d}
and {Axis.Y:+d} on a NATIVE panel, so _jog_keys(EAST, NORTH) ==
[('x',1),('y',1)] — a strict superset of north_btn's [('y',1)]. Any
released/cancel/leave event on NORTH_EAST therefore sends jog_key_up('y',1)
and stops a NORTH hold that is still under the user's finger; the later real
release of NORTH is a no-op because the key is already out of the set.
Reachable whenever two pointer sequences are live at once (two fingers on a
touch panel, or touch plus mouse), which GestureClick supports — touch-only
is False and each button owns its own gesture. Single-mouse flows are not
affected, because GTK suppresses crossing during the grab (see the finding
above) and the release-time 'leave' lands on the correct button.

**Verification**

Verified. _keys_down (line 66) is a flat set of (axis, sign) with no owner
or refcount; _release_jog_key (508-513) discards by identity;
_on_jog_released (563-564), _on_jog_cancelled (568-569) and _on_jog_leave
(573-574) each release every key their own directions map to. north_east_btn
is attached with (EAST, NORTH) at line 113 and MachinePanel.calculate_jog
(machine_panel.py:418-450) maps EAST->{Axis.X:+d} and NORTH->{Axis.Y:+d} on
an unrotated bed, so _jog_keys(EAST, NORTH) == [('x',1),('y',1)], a strict
superset of north_btn's [('y',1)]. Traced: hold NORTH (keys {('y',1)}), then
hold NORTH_EAST (adds ('x',1); ('y',1) is deduped by _press_jog_key's early
return at 501-502), then release NORTH_EAST -> jog_key_up('y',1) stops the
NORTH hold still under the user's finger, and the later real NORTH release
is a no-op. Requires two simultaneous pointer sequences (touch), same as the
timer findings; the auditor's own note that single-mouse flows are safe is
correct. DEGRADED is right.

**Proposed fix**

Give the held keys an owner: `self._keys_down: dict[tuple[str,int],
set[int]]` keyed by key -> set of owning gesture ids (or button objects).
_press_jog_key adds the owner and only sends jog_key_down on the 0->1
transition; _release_jog_key(owner, key) discards that owner and only sends
jog_key_up when the owner set empties. Pass the gesture/button through from
the three handlers (they already receive `gesture`/`controller` as the first
argument).

**Test strategy**

Direct widget handler invocation: `_hold(widget, JogDirection.NORTH)` then
`widget._on_jog_released(ne_gesture, 1, 0.0, 0.0, (EAST, NORTH))`; assert
machine_cmd.jog_key_up is NOT called with (machine, 'y', 1) and that ('y',1)
is still in widget._keys_down. Repeat for _on_jog_leave and
_on_jog_cancelled.

**Hardware check:** On a touch panel: hold N with one finger, tap NE with a second finger and
lift it. The head stops while the first finger is still down.

---

### MOT-38 - D9 10 targets are documented as anchor-relative but fed absolute machine coordinates read back from 0x0421/0x0431

- **Severity:** SMELL
- **Location:** `rayforge/machine/driver/ruida/ruida_client.py:418`
- **Class:** Failure class 2 — sign / axis / frame errors in the interactive-motion subsystem (jog arrows → D9 10 payload, Go Scale / Cut Scale framing)
- **Status:** FIXED 6ee845366 (documentation only) - NEEDS-HARDWARE for the byte itself: capture an RDWorks panel jog and read the D9 10 option byte and payload against a known non-zero REF0 offset. The wire bytes were deliberately left alone; the two readings coincide whenever that offset is zero, so changing them on the strength of a docstring could only move the head somewhere new.

**Evidence**

```python
        """
        Rapid move to a position relative to the stored anchor (D9 10).

        This is the interactive motion command used by real Ruida
        hardware; job streams use move_abs (0x88) instead. The move is
        a traversal: the laser never fires.

        Args:
            x_um: X coordinate in micrometers, relative to the anchor
            y_um: Y coordinate in micrometers, relative to the anchor
            light: Switch the red pointer on for the move
        """
        opts = self._build_move_opts(origin=True, light=light)
```

**Expected**

Caller and callee must agree on the coordinate frame. Either rapid_move_xy
takes anchor-relative micrometres (as its own docstring and the opts=0x00
'Origin' flag say, and as the job stream's D8 12 + job-local re-basing in
ruida_encoder.py:58/839-843 would imply), or it takes absolute machine
micrometres.

**Actual**

Every RuidaDriver caller feeds it ABSOLUTE machine coordinates: _jog_move_to
clamps against machine.axis_extents (line 950-952) and passes the result
straight through; _jog_to_limit derives targets from _jog_origin(), i.e.
from RuidaClient.read_position() which decodes registers 0x0421/0x0431
('Current X'/'Current Y'); trace_frame builds corners from the same read. If
the docstring is right, then with a non-zero REF0 anchor of (50, 50) mm and
the head at machine (100, 100) a 10 mm east step commands D9 10 (110000,
100000), which the controller resolves as anchor + that = (160, 150) mm -- a
60 mm diagonal jump instead of a 10 mm step -- and _wait_for_jog_settled /
_wait_for_frame_corner, which compare the polled absolute position against
those same targets, would never match and would burn their full timeouts (5
x FRAME_CORNER_TIMEOUT = 75 s of 'corner not reached' warnings per Go
Scale). The in-repo simulator cannot settle it:
ruida_server._handle_d9_command's 0x10 branch ignores the opts byte entirely
and does `s.x = x; s.y = y` (absolute), and the _JogClientSpy /
_ScaleClientSpy stubs simply record the bytes -- so all current green tests
are blind to this.

**Verification**

The internal contradiction is real and verified: ruida_client.py:417-427
documents x_um/y_um as 'relative to the anchor' and :429 passes origin=True
(opts 0x00), while every production caller supplies an absolute machine
coordinate -- ruida_driver.py:950-953 clamps against machine.axis_extents
and calls rapid_move_xy; :862/:929-936 derive the origin from
read_position() (registers 0x0421/0x0431 = current X/Y); :638-651 builds Go
Scale corners from the same read; :938-947 explicitly calls it 'an absolute
target'. But the claimed behavioural harm (controller adds the REF0 anchor,
60 mm diagonal jumps, five FRAME_CORNER_TIMEOUTs) is contradicted by in-repo
evidence: commit 6a69331b8 records bench observation that the two-axis path
was the *working* one ('Every jog now goes through the proven D9 10 option
0x00 form with a target computed from the last known position and clamped to
the bed'), the single-axis D9 00/01 path being the one that misbehaved;
ruida_driver.py:944-947 records the same bench finding; and
ruida_server.py:341-354 (the only in-repo model) resolves D9 10 as absolute
regardless of the opts byte. move_to() and Go Scale would both be grossly
and visibly wrong if the anchor were added. What survives is a misleading
docstring on rapid_move_xy, which is correctness-neutral. DEGRADED -> SMELL.

**Proposed fix**

Decide and encode the answer. If the frame is absolute, correct the
rapid_move_xy docstring (drop 'relative to the stored anchor' from the
summary and both Args lines) so the driver's usage is no longer contradicted
by its own client. If the frame is anchor-relative, subtract the REF0 offset
in _jog_move_to before the send and add it back before comparing polled
positions in _wait_for_jog_settled / _wait_for_frame_corner -- and cache the
offset once per interactive session rather than per move. Either way add an
assertion-bearing test so the choice stops being folklore.

**Test strategy**

The ruida_simulator over UDP cannot decide this (its D9 10 handler discards
opts). Settle it on hardware, then lock it with a _JogClientSpy test that
asserts the exact frame conversion. As a defensive interim, add a simulator-
level test that ruida_server's D9 10 handler and RuidaDriver agree, so at
least the in-repo pair stays self-consistent.

**Not reproducible in a test.** Set REF0 to a clearly non-zero anchor (e.g. move to machine (50,50) and
press Origin on the panel), select REF0, read 0x0421/0x0431, then send one
D9 10 with opts 0x00 targeting the currently reported position. If the head
does not move, D9 10 opts=0x00 is absolute and the docstring is wrong; if
the head jumps by the anchor, the driver's whole interactive path is off by
the anchor and needs the offset conversion.

---

### MOT-39 - The repo's only modelled motion-stop primitive, and the whole jog UDP channel, are dead code

- **Severity:** SMELL
- **Location:** `rayforge/machine/driver/ruida/ruida_client.py:510`
- **Class:** Failure class 6 — stop semantics of the interactive-motion subsystem (Ruida)
- **Status:** FIXED 6ee845366

**Evidence**

```python
    async def jog_stop(self, axis: str) -> None:
        """
        Stop continuous jog on an axis.

        Args:
            axis: Axis name ('x', 'y', 'z', or 'u')
        """
        await self.send_command(self._build_jog_keyup(axis))
```

**Expected**

Either the D8 KeyDown/KeyUp interactive-jog vocabulary is the driver's stop
mechanism, or it is deleted — leaving both a live D8 01 path and an unused
D8 KeyUp path invites the next reader to assume the wrong one is
authoritative.

**Actual**

`jog_start`, `jog_stop`, `jog_move_x` and `jog_move_y`
(ruida_client.py:500-535) have no callers in rayforge/ — only
tests/machine/driver/ruida/test_ruida_client.py exercises the last two.
`_build_jog_keydown`/`_build_jog_keyup` exist solely for them. This matters
because `jog_stop`'s D8 KeyUp is the ONE stop that ruida_server.py actually
models as affecting motion (`s.jog_active[...] = 0`, line 275), while the
byte the driver really sends, D8 01, is modelled there as a process-state
change only. Related dead weight:
`_jog_udp_transport`/`_jog_ruida_transport` on port 50207 are created
(ruida_driver.py:211-216), connected and disconnected
(ruida_client.py:193-200), and advertised in `resource_uri` as "(jog:
{port})" — but `send_jog_command` (ruida_client.py:326-336) forwards to
`send_command`, i.e. the MAIN channel, so `self._jog_transport` is never
sent a single byte. `send_jog_command` itself has no callers either.

**Verification**

Every dead-code claim verified by grep across rayforge/ and tests/.
jog_start (:500) and jog_stop (:510) have zero callers anywhere;
jog_move_x/jog_move_y (:519-535) only in
tests/machine/driver/ruida/test_ruida_client.py:299-311; send_jog_command
(:326-336) has no callers and forwards to send_command (the main channel)
anyway; KEY_DOWN_PREFIX/KEY_UP_PREFIX (:55-56) are never referenced again;
_jog_transport is touched only at :118 (stored), :193-194 (connect) and
:198-199 (disconnect) -- never sent on. ruida_driver.py:211-216 builds and
wires it, :164-170 exposes the user-facing 'Jog Port' var, :132-134
advertises `(jog: {self.jog_port})` in resource_uri. The asymmetry claim
also checks out: ruida_server.py:273-275 zeroes s.jog_active only for D8
0x30-0x37, while D8 01 at :248-250 only flips program_mode/machine_status.
SMELL is correct -- nothing misbehaves, it is unreachable surface plus a
misleading model.

**Proposed fix**

Delete `jog_start`, `jog_stop`, `jog_move_x`, `jog_move_y`,
`send_jog_command`, `_build_jog_keydown` and `_build_jog_keyup` along with
their tests — OR, if the hardware check for the D8 01 finding shows D8 KeyUp
is the real motion stop, wire `jog_stop` into `_stop_jog_motion` and delete
the rest. Either way, drop the unused jog transport and the jog_port setup
var, or make `send_jog_command` actually use `self._jog_transport`. Per repo
convention this is a 'mention, do not delete' item unless the D8 01
verification forces the decision.

**Test strategy**

No behavioural test. If the transport is kept, add an assertion in
tests/machine/driver/ruida/test_ruida_driver.py that `client._jog_transport`
receives the bytes `send_jog_command` is given; that test fails today, which
is the point.

**Not reproducible in a test.** Same capture as the D8 01 finding — it decides whether this code is deleted
or promoted.

---

### MOT-40 - D9 00 / D9 01 have three mutually contradictory documented meanings in-repo, and rapid_move_axis's axis numbering does not match its own callers

- **Severity:** SMELL
- **Location:** `rayforge/machine/driver/ruida/ruida_client.py:526`
- **Class:** Failure class 7 — protocol correctness of the interactive byte stream (D9 rapid moves, D8 realtime commands, C9 speed, DA memory) as emitted by RuidaDriver/RuidaClient, diffed against the only in-repo references (ruida_maps.py, ruida_server.py, fixtures/rdworks_reference.rd)
- **Status:** FIXED 6ee845366 (documentation only) - NEEDS-HARDWARE for the frame: send D9 00 twice from a known position and see whether the head accumulates. Nothing in the driver emits D9 00/01, so the answer changes documentation, not behaviour.

**Evidence**

```python
ruida_client.py:519-526 (client: absolute)
    async def jog_move_x(self, target_x: int) -> None:
        """
        Rapid move X axis to absolute target position.
...
        await self.send_command(self._build_rapid_move_axis(0x00, target_x))

ruida_server.py:321-324 (simulator: relative)
            self._log_command(
                f"Rapid move {opt_desc} {axis}: {coord:+d}um (rel)", data[:8]
            )
            if base_axis == 0x00:
                s.x += coord

ruida_driver.py:944-947 (driver comment: absolute, from bench observation)
        D9 10 is the only motion form used: the single-axis D9 00/01
        commands take an absolute coordinate in the same slot, so
        feeding them a relative delta drove the head to the wrong end
        of the axis.

ruida_client.py:439-449 vs :654 (axis numbering vs the mask)
            axis: Axis number (0x10=X, 0x11=Y, 0x12=Z, 0x13=U)
...
        return b"\xd9" + bytes([axis & 0x0F]) + bytes([opts]) + encode35(coord)
```

**Expected**

One documented semantic for D9 00/01, agreed by the client, the driver's
comment and the simulator's decoder; and one axis numbering convention used
by both the docstring and the callers.

**Actual**

Three sources disagree. The client's jog_move_x/jog_move_y say "absolute",
the simulator decodes the identical bytes as relative (`s.x += coord`, and
it even logs "(rel)"), and the driver's comment reports that hardware treats
them as absolute — which, if true, means ruida_server._handle_d9_command is
wrong and any future test written against the simulator will encode the
wrong belief. The methods are dead in production (only
tests/machine/driver/ruida/test_ruida_client.py calls them), so nothing
misbehaves today. Alongside it, rapid_move_axis documents axis as
0x10=X/0x11=Y/0x12=Z/0x13=U while _build_rapid_move_axis masks with & 0x0F,
and the one real caller — tests/machine/driver/ruida/client_app.py:379-384 —
passes 0x00 and 0x01. Both spellings happen to land on the same wire byte
because of the mask, so the contradiction is invisible until someone passes
0x50 (the D9 50-53 variant ruida_server.py:310 also accepts) and watches the
high nibble get thrown away.

**Verification**

All four quotes verified. ruida_client.py:519-526/528-535 document
jog_move_x/jog_move_y as 'Rapid move ... to absolute target position';
ruida_server.py:310-331 decodes the identical D9 00/01 bytes as relative,
does `s.x += coord` / `s.y += coord`, and even logs '(rel)';
ruida_driver.py:944-947 states from bench observation that those commands
take an absolute coordinate. The numbering contradiction is also real: the
docstring at :443 says 'axis: Axis number (0x10=X, 0x11=Y, 0x12=Z, 0x13=U)'
while _build_rapid_move_axis :654 emits `bytes([axis & 0x0F])`, and the one
real caller, tests/machine/driver/ruida/client_app.py:379-384, passes
0x00/0x01 -- both spellings collapse to the same wire byte, and the
0x50-0x53 variant ruida_server.py:310 accepts would silently lose its high
nibble. Grep confirms jog_move_x/jog_move_y and rapid_move_axis are
production-dead, so nothing misbehaves today. SMELL confirmed.

**Proposed fix**

Pick the hardware truth and write it down once. If the driver's bench
observation stands, fix ruida_server._handle_d9_command to assign rather
than accumulate for subcmd 0x00-0x03 (and correct the "(rel)" log text), and
keep the client docstrings. If the simulator is right, correct the client
docstrings and the driver comment. Either way, drop the `& 0x0F` mask and
document axis as the literal sub-opcode (0x00=X, 0x01=Y, 0x02=Z, 0x03=U), so
the 0x50-0x53 variant stays expressible; then delete jog_move_x/jog_move_y,
which are dead either way (see the dead-surface finding).

**Test strategy**

Once the semantics are settled, add a ruida_server unit test in
tests/machine/driver/ruida/ that feeds D9 00 02 <encode35(10000)> to a
server whose state starts at x=5000 and asserts the resulting s.x (15000 if
relative, 10000 if absolute) — a decoder test, not a driver test, so it pins
the reference the rest of the suite trusts.

**Hardware check:** With the head parked at a known X read from mem 0x0421, send D9 00 02
<encode35(known_x + 10000)>, re-read 0x0421, and see whether the head moved
10 mm (absolute) or (known_x + 10) mm (relative).

---

### MOT-41 - _build_jog_keyup always emits the negative-direction key-up opcode, so a positive-direction key would never be released

- **Severity:** SMELL
- **Location:** `rayforge/machine/driver/ruida/ruida_client.py:713`
- **Class:** Failure class 7 — protocol correctness of the interactive byte stream (D9 rapid moves, D8 realtime commands, C9 speed, DA memory) as emitted by RuidaDriver/RuidaClient, diffed against the only in-repo references (ruida_maps.py, ruida_server.py, fixtures/rdworks_reference.rd)
- **Status:** FIXED 6ee845366

**Evidence**

```python
ruida_client.py:711-720
    def _build_jog_keyup(self, axis: str) -> bytes:
        axis_map = {
            "x": 0x30,
            "y": 0x32,
            "z": 0x34,
            "u": 0x36,
        }
        if axis.lower() not in axis_map:
            raise ValueError(f"Invalid axis: {axis}")
        return b"\xd8" + bytes([axis_map[axis.lower()]])

ruida_maps.py:174-181 (key-up opcodes are direction-specific)
    0x30: "KeyUp -X +Left",
    0x31: "KeyUp +X +Right",
    0x32: "KeyUp +Y +Top",
    0x33: "KeyUp -Y +Bottom",
    0x34: "KeyUp +Z",
    0x35: "KeyUp -Z",
    0x36: "KeyUp +U",

ruida_client.py:695-709 (key-down IS direction-specific and matches the table exactly)
            ("x", -1): 0x20,
            ("x", 1): 0x21,
```

**Expected**

A key-up releases the key that was pressed: D8 21 (KeyDown +X) is released
by D8 31 (KeyUp +X); D8 22 (KeyDown +Y) by D8 32 (KeyUp +Y).
_build_jog_keyup should take the same (axis, direction) pair
_build_jog_keydown takes.

**Actual**

It takes only the axis and hardcodes one opcode per axis: x always releases
with 0x30 = "KeyUp -X", y with 0x32 = "KeyUp +Y", z with 0x34 = "KeyUp +Z",
u with 0x36 = "KeyUp +U". Three of the four are the wrong opcode for half
the directions. On hardware that latches per key, jog_start("x", 1) followed
by jog_stop("x") would release a key that was never pressed and leave +X
running. This is currently unreachable — grep finds no caller of
jog_start/jog_stop anywhere in rayforge/ or tests/ — but it is a loaded gun
aimed at whoever implements the fallback the driver's HARDWARE NOTE
contemplates. The simulator cannot catch it either: ruida_maps.py:604-613
D8_KEYUP_AXIS_MAP collapses 0x30 and 0x31 to the same "x", so
ruida_server.py:275 zeroes the axis whichever opcode arrives.

**Verification**

Code quotes verified exactly: ruida_client.py:711-720 maps axis->one opcode
(x:0x30, y:0x32, z:0x34, u:0x36) with no direction parameter, while
ruida_maps.py:174-181 labels those opcodes direction-specifically (0x30
'KeyUp -X', 0x31 'KeyUp +X', 0x32 'KeyUp +Y', 0x33 'KeyUp -Y') and
_build_jog_keydown :695-709 IS direction-keyed and matches the table
exactly. So jog_start('x', 1) (D8 21) would be released with D8 30, the -X
key-up. The simulator blind spot is real too: ruida_maps.py:604-613
D8_KEYUP_AXIS_MAP collapses 0x30/0x31 to 'x', and ruida_server.py:273-275
zeroes the axis for either. Downgraded BROKEN -> SMELL: the auditor's own
text concedes the path is unreachable, and I confirmed jog_start/jog_stop
have no callers in rayforge/ or tests/, so no intended behaviour fails
today. It is an inconsistency in dead code, not a live break.

**Proposed fix**

Change the signature to `_build_jog_keyup(self, axis: str, direction: int)`
with the full eight-entry map {("x",-1):0x30, ("x",1):0x31, ("y",1):0x32,
("y",-1):0x33, ("z",1):0x34, ("z",-1):0x35, ("u",1):0x36, ("u",-1):0x37} —
i.e. the key-down map plus 0x10 — and thread `direction` through
client.jog_stop. Better still, since nothing calls either method, delete
jog_start/jog_stop/_build_jog_keydown/_build_jog_keyup outright and re-add
them from the table when a caller actually exists.

**Test strategy**

Pure builder test in tests/machine/driver/ruida/test_ruida_client.py
(MagicMock transport, no simulator needed): assert
client._build_jog_keyup("x", 1) == b"\xd8\x31" and _build_jog_keyup("x", -1)
== b"\xd8\x30", then a table-driven test asserting every (axis, direction)
key-up opcode equals its key-down opcode + 0x10 and appears in
ruida_maps.D8_COMMANDS with a matching sign in the label.

**Hardware check:** Only needed if the key protocol is ever adopted: press D8 21, release with
D8 30, and watch whether X keeps travelling.

---

### MOT-42 - C9 02 has a second, contradictory encoder: _build_speed takes mm/s while set_travel_speed takes um/s

- **Severity:** SMELL
- **Location:** `rayforge/machine/driver/ruida/ruida_client.py:738`
- **Class:** Unit errors on the interactive-motion speed and distance paths (jog / hold-jog / Go Scale), from the human-facing control to the byte on the wire and back
- **Status:** FIXED cd33192d1

**Evidence**

```python
    def _build_speed(self, speed_mm_s: float) -> bytes:
        speed_val = int(speed_mm_s * 1000)
        return b"\xc9\x02" + encode35(speed_val)

(the other authority for the same opcode, line 591)
        await self.send_command(b"\xc9\x02" + encode35(um_per_s))
```

**Expected**

One logical value -- interactive travel speed -- should have exactly one
encoder and one documented input unit for a given opcode.

**Actual**

Two public entry points build C9 02 with different declared argument units
(`set_speed(speed_mm_s)` vs `set_travel_speed(um_per_s)`), and
`_build_axis_speed`/`set_axis_speed` do the same for C9 03. The arithmetic
agrees today only because both end up multiplying to um/s, and neither
`set_speed` nor `set_axis_speed` is called anywhere in production -- grep
finds callers only in
tests/machine/driver/ruida/test_ruida_client.py:414-424. That makes the harm
latent rather than active, but it is a live trap: the driver's own
vocabulary elsewhere is mm/min, so a future caller writing `await
client.set_speed(machine.max_travel_speed)` with a 3000 mm/min profile would
command 3000 mm/s -- 60x over -- and nothing in the signature would flag it.

**Verification**

Quotes verified exactly. ruida_client.py:738-740 `_build_speed(self,
speed_mm_s: float)` -> `int(speed_mm_s * 1000)` -> b"\xc9\x02" +
encode35(...), and ruida_client.py:591 `await self.send_command(b"\xc9\x02"
+ encode35(um_per_s))`. Same for C9 03 (_build_axis_speed at :757-759). Grep
confirms set_speed/set_axis_speed have no callers outside
tests/machine/driver/ruida/test_ruida_client.py:414-424; the only production
C9 02 path is set_travel_speed, fed from ruida_driver.py:729 (`speed_mm_min
* 1000 / 60`), :793-795 and :922, all correctly converting mm/min -> um/s.
So the arithmetic is correct on every live path and there is no condition
under which today's code behaves wrongly. Downgraded DEGRADED -> SMELL: this
is a latent API trap in dead code, correctness-neutral as written.

**Proposed fix**

Delete `set_speed`, `_build_speed`, `set_axis_speed` and `_build_axis_speed`
(and their two tests), leaving `set_travel_speed(um_per_s)` as the sole C9
02 authority; if C9 03 is ever needed, add `set_axis_travel_speed(um_per_s:
int)` next to it using the same unit. Alternatively keep the mm/s wrappers
but have them delegate: `await self.set_travel_speed(int(speed_mm_s *
1000))`.

**Test strategy**

Removal is verified by the existing suite still passing after the two tests
at test_ruida_client.py:414-424 are deleted. If the delegate option is taken
instead, assert `set_speed(100.0)` and `set_travel_speed(100000)` emit byte-
identical commands.

---

### MOT-43 - _fetch_card_info is launched as an unreferenced, uncancelled task whose non-OSError exceptions are silently lost

- **Severity:** SMELL
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:341`
- **Class:** FAILURE CLASS 4 - Concurrency in RuidaClient and the driver's loops (tasks, locks, futures, Events, response attribution)
- **Status:** FIXED 01d841e3a

**Evidence**

```python
                asyncio.create_task(
                    self._fetch_card_info(),
                    name="ruida-fetch-card-info",
                )
```

**Expected**

A background task the driver starts is owned by the driver: it is stored,
cancelled in cleanup(), and its exceptions are surfaced.

**Actual**

The task object is discarded, so nothing holds a strong reference (CPython
can garbage-collect a running task whose only reference is the loop's, and
the loop's reference is dropped once it completes) and cleanup() -- which
cancels only `_connection_task` (lines 259-266) -- has no way to cancel it.
`_fetch_card_info` catches only `(OSError, asyncio.TimeoutError)` (line
1073), so anything else (a ValueError from a malformed card id, a
RuntimeError from the transport) is swallowed into 'Task exception was never
retrieved' at GC time, if it is printed at all. The task also runs
`_read_memory_wait(CARD_ID_ADDRESS)` (0x057E) concurrently with the poll
loop -- it contends for `_send_lock`, and its reply sets
`_response_received`, feeding the shared-Event liveness problem above. It
happens not to collide in `_pending_mem_reads` only because 0x057E differs
from the polled 0x0421/0x0431/0x0441; a future caller reading a polled
address the same way would hit the overwrite defect head-on.

**Verification**

Confirmed: ruida_driver.py:341-344 discards the Task object, cleanup()
cancels only _connection_task (259-266), and _fetch_card_info catches only
(OSError, asyncio.TimeoutError) at 1073. It is also re-launched on every
reconnect iteration. Correctness-neutral in practice - CARD_ID_ADDRESS
0x057E does not collide with the polled 0x0421/0x0431/0x0441 in
_pending_mem_reads - so SMELL is right.

**Proposed fix**

Store it and tear it down with the driver: self._card_info_task =
asyncio.create_task(self._fetch_card_info(), name='ruida-fetch-card-info')
self._card_info_task.add_done_callback(_log_task_exception) and in
cleanup(), cancel and await it next to _connection_task. Broaden the except
in _fetch_card_info to `except Exception` with logger.exception, since it is
a task boundary.

**Test strategy**

Driver-level: patch client.get_card_info to raise RuntimeError, run
_connect_implementation against ruida_simulator, and assert the driver
logged the failure (caplog) rather than leaving an unretrieved task
exception. Separately, call cleanup() immediately after connect while the
card-info read is still outstanding and assert no task remains pending on
the loop.

---

### MOT-44 - _connection_loop swallows CancelledError and returns normally, so cleanup()'s own except CancelledError is dead code

- **Severity:** SMELL
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:384`
- **Class:** FAILURE CLASS 4 - Concurrency in RuidaClient and the driver's loops (tasks, locks, futures, Events, response attribution)
- **Status:** FIXED 01d841e3a

**Evidence**

```python
            except asyncio.CancelledError:
                logger.debug("Connection loop cancelled")
                break
            except Exception as e:  # noqa: BLE001 - connection loop boundary
                logger.error(f"Connection error: {e}")
```

**Expected**

A cancelled task propagates CancelledError so the canceller can tell
cancellation from normal completion.

**Actual**

Which clause catches it, to settle the question directly: `except
asyncio.CancelledError` at line 384. Since Python 3.8 CancelledError derives
from BaseException, so the broad `except Exception` at 387 could not catch
it even if the order were reversed -- the loop is NOT at risk of routing a
cancellation into the reconnect-and-sleep path. But the CancelledError
clause `break`s out of the outer while and the coroutine then returns
normally, so `self._connection_task` completes with a result instead of a
cancellation, and cleanup()'s `except asyncio.CancelledError: pass` (lines
262-264) never runs. There is no deadlock: cleanup() sets `_keep_running =
False` before cancelling, and if the cancel lands on the `await
asyncio.sleep(self.RECONNECT_INTERVAL)` at line 394 -- which is OUTSIDE the
try -- CancelledError propagates properly and the except in cleanup does
fire. The defect is the inconsistency, not a hang. The break also skips
`_disconnect_transports()`, which is harmless only because cleanup()
disconnects afterwards; a cancel from any other source (e.g. TaskManager's
shutdown, which cancels every pending task -- manager.py:140-142) leaves the
transports open.

**Verification**

Confirmed: the `except asyncio.CancelledError` at 384-386 breaks the outer
`while self._keep_running`, so the coroutine returns normally and the task
completes with a result rather than as cancelled, leaving cleanup()'s
`except asyncio.CancelledError: pass` (262-264) unreachable for that case.
The finding's own caveats are correct too - CancelledError is a
BaseException so the broad `except Exception` at 387 could not catch it, and
a cancel landing on the sleep at 394 (outside the try) does propagate. The
skipped _disconnect_transports on that path is real but masked by cleanup()
disconnecting afterwards.

**Proposed fix**

Log and re-raise instead of breaking: except asyncio.CancelledError:
logger.debug("Connection loop cancelled") await
self._disconnect_transports() raise The outer `while self._keep_running`
already exits on the flag, so the break is not needed for the cleanup path.

**Test strategy**

Driver-level, pytest-asyncio: start _connect_implementation, await one loop
iteration, then `driver._connection_task.cancel()` and await it -- assert
`driver._connection_task.cancelled()` is True (False today). Separately
assert the transports are disconnected after a bare cancel that does not go
through cleanup().

---

### MOT-45 - clear_alarm is byte-identical to cancel — both send D8 01 Stop Process

- **Severity:** SMELL
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:751`
- **Class:** Failure class 7 — protocol correctness of the interactive byte stream (D9 rapid moves, D8 realtime commands, C9 speed, DA memory) as emitted by RuidaDriver/RuidaClient, diffed against the only in-repo references (ruida_maps.py, ruida_server.py, fixtures/rdworks_reference.rd)
- **Status:** FIXED 6ee845366

**Evidence**

```python
ruida_driver.py:749-751
    async def clear_alarm(self) -> None:
        assert self._client
        await self._client.stop_process()

ruida_driver.py:577-579
    async def cancel(self) -> None:
        assert self._client
        await self._client.stop_process()

ruida_maps.py:154-157 (no alarm-clear entry exists in the D8 table)
    0x00: "Start Process",
    0x01: "Stop Process",
    0x02: "Pause Process",
    0x03: "Restore Process",
```

**Expected**

Clearing an alarm and cancelling a job are different operations, and the
toolbar exposes them as different buttons
(rayforge/ui_gtk/toolbar.py:172-179 "machine-clear-alarm" vs the jog
widget's stop button, which routes to MachineCmd.cancel_job at
cmd.py:408-413).

**Actual**

Both emit D8 01. Pressing "Clear Alarm" while a job is running aborts the
job. The rest of the D8 mapping is correct and confirmed against
ruida_maps.py — set_hold(True)->D8 02 "Pause Process", set_hold(False)->D8
03 "Restore Process", cancel()->D8 01 "Stop Process" — so this is the one
entry with no counterpart in the table. The closest in-repo candidates are
the panel keys A5 50 07 "ESC" and A5 50 5A "Reset" (ruida_maps.py
INTERFACE_COMMANDS:62,73), neither of which the client can currently send.
Impact is limited today because the auto-clear path is gated on
DeviceStatus.ALARM (rayforge/ui_gtk/mainwindow.py:1083-1091) and RuidaDriver
never reports ALARM, so only the manual toolbar button reaches it.

**Verification**

Confirmed: clear_alarm (749-751) and cancel (577-579) both call
stop_process, and D8 has no alarm-clear entry (ruida_maps.py:153-157). The
mitigation is real and I verified it: RuidaDriver never sets
DeviceStatus.ALARM (no ALARM reference anywhere in ruida_driver.py), and the
action is enabled only on ALARM or driver.state.error
(mainwindow.py:1701-1707), with the auto-clear gated on ALARM at 1083-1091.
Correctness-neutral in practice = SMELL.

**Proposed fix**

Ruida has no alarm state the driver models, so make that explicit rather
than aliasing a destructive command: have clear_alarm log at debug and
return without sending anything, and add a one-line comment saying the
controller reports no alarm state and that D8 01 belongs to cancel(). If a
real reset is wanted later, add it as A5 50 5A on a raw path once that path
exists and the byte is captured.

**Test strategy**

_JogClientSpy-style stub: `await driver.clear_alarm()` and assert the
recorded command list is empty, alongside the existing assertion that `await
driver.cancel()` records b"\xd8\x01". Cheap and it pins the intent.

**Hardware check:** Put the controller into its error state (open the interlock mid-job), then
send D8 01 and observe whether the panel error clears or merely the job
stops.

---

### MOT-46 - _jog_move_to's rationale comment claims D9 00/01 are absolute; both in-repo references say relative, and the 'absolute' jog_move_x/jog_move_y helpers are dead

- **Severity:** SMELL
- **Location:** `rayforge/machine/driver/ruida/ruida_driver.py:944`
- **Class:** Failure class 2 — sign / axis / frame errors in the interactive-motion subsystem (jog arrows → D9 10 payload, Go Scale / Cut Scale framing)
- **Status:** FIXED 47a49acd0 and 6ee845366

**Evidence**

```python
944        D9 10 is the only motion form used: the single-axis D9 00/01
945        commands take an absolute coordinate in the same slot, so
946        feeding them a relative delta drove the head to the wrong end
947        of the axis.
```

**Expected**

A rationale comment that steers future motion work should agree with the
only opcode references this repo has (ruida_maps.py and ruida_server.py), or
say plainly that it is an unconfirmed hardware observation that contradicts
them.

**Actual**

ruida_server._handle_d9_command treats D9 00/01 as RELATIVE -- it logs
'(rel)' and applies `s.x += coord` / `s.y += coord`
(ruida_server.py:321-326) -- and the reference sender app does the same,
feeding a signed step delta: `self.client.client.rapid_move_axis(0x00,
direction * step_um)` (tests/machine/driver/ruida/client_app.py:379).
Meanwhile RuidaClient.jog_move_x still documents itself as 'Rapid move X
axis to absolute target position' (ruida_client.py:521) while emitting the
same D9 00 the simulator applies relatively. jog_start, jog_stop, jog_move_x
and jog_move_y now have no production callers at all -- only
tests/machine/driver/ruida/test_ruida_client.py exercises them -- so the
misleading 'absolute' contract sits unrefuted in a dead path, ready to be
trusted by the next person who needs single-axis motion. Nothing moves
wrongly today; the risk is purely that the comment is load-bearing folklore.

**Verification**

Confirmed, and stronger than claimed: ruida_server.py:321-326 logs '(rel)'
and applies s.x += coord, AND the vendored meerk40t emulator does the same
(external/meerk40t/meerk40t/ruida/emulator.py:595-612, `move_abs(self.x +
coord * self.scale, self.y)`), while D9 10 is absolute in both
(ruida_server.py:352-353, emulator.py:633-642). client_app.py:379 feeds a
signed relative step. RuidaClient.jog_move_x still documents 'absolute'
(ruida_client.py:519-526). Dead-path claim verified: grep across rayforge/
and tests/ shows jog_move_x/jog_move_y only in test_ruida_client.py:299-311
and jog_start/jog_stop with no callers at all. Correctness-neutral today;
line anchor is off by one - the quoted comment starts at 944, not 943.

**Proposed fix**

Reword the _jog_move_to comment to state what is actually known: 'D9 10 is
the only motion form used. D9 00/01 are relative per
ruida_server._handle_d9_command and client_app; an earlier attempt to use
them as absolute targets drove the head to the wrong end, which is
consistent with them being relative.' Then either delete
jog_move_x/jog_move_y (and their tests) as dead code, or fix their
docstrings to say 'relative offset' and rename them to match
move_rel_x/move_rel_y semantics. Mention rather than silently delete --
jog_start/jog_stop are the D8 keydown path and may still be wanted.

**Test strategy**

tests/machine/driver/ruida/test_ruida_client.py already has
test_jog_move_x/test_jog_move_y; extend them to feed the emitted bytes
through RuidaServer._process_single_command and assert the resulting s.x
delta, which pins the relative interpretation in a test instead of a
comment. The rd-fixture skill can cross-check against
tests/machine/driver/ruida/fixtures/rdworks_reference.rd if any D9 00/01
appears there.

---

### MOT-47 - No in-repo ground truth exists for any interactive opcode: the fixture contains zero D9 commands and the sole authority is Rayforge's own simulator

- **Severity:** SMELL
- **Location:** `rayforge/machine/driver/ruida/ruida_server.py:299`
- **Class:** Failure class 7 — protocol correctness of the interactive byte stream (D9 rapid moves, D8 realtime commands, C9 speed, DA memory) as emitted by RuidaDriver/RuidaClient, diffed against the only in-repo references (ruida_maps.py, ruida_server.py, fixtures/rdworks_reference.rd)
- **Status:** FIXED 6ee845366 (the inferred handlers are now labelled) - NEEDS-HARDWARE for the capture itself: one RDWorks session exercising panel jog in four directions, move-to, Frame, Stop, Pause, Resume and Home, saved beside rdworks_reference.rd, and the decoded command list written up as the opcode table this audit's brief assumed already existed.

**Evidence**

```python
ruida_server.py:299-308 - get_opt_desc is quoted verbatim and is at the claimed lines:
        def get_opt_desc(opts: int) -> str:
            if opts == 0x00:
                return "Origin"
            elif opts == 0x01:
                return "Light/Origin"
            elif opts == 0x02:
                return ""
            elif opts == 0x03:
                return "Light"
            return f"opts={opts}"

Two corrections to the surrounding prose, neither of which weakens the claim:

(1) get_opt_desc is NOT the only in-repo definition of the option byte. rayforge/machine/driver/ruida/ruida_client.py:656-663 is the producer-side definition:
    def _build_move_opts(self, origin: bool, light: bool) -> int:
        if origin and light:
            return 0x01
        elif origin:
            return 0x00
        elif light:
            return 0x03
        return 0x02
It agrees with get_opt_desc bit-for-bit. Since it is also Rayforge source authored alongside the emitter, it corroborates rather than refutes the self-reference argument.

(2) ruida_maps.py contains no D9 option-byte semantics at all (grep for D9 in ruida_maps.py: no hits). The three in-repo references are ruida_server.py (decoder/logger), ruida_client.py (encoder), and ruida_util.py (length map only, lines 281-287). ruida_maps.py and ruida_util.py headers do cite upstream projects (edutechwiki Ruida, meerk40t, StevenIsaacs/ruida-protocol-analyzer), but none of that material is vendored into the repo, so "no in-repo ground truth" holds.

Fixture analysis independently reproduced using the repo's own unswizzle_byte (magic 0x88) on tests/machine/driver/ruida/fixtures/rdworks_reference.rd (1013 bytes): 88 x1, a9 x100, c601/c602/c612/c613/c621/c622/c631/c632/c641/c642/c650/c651/c665 x1 each, c902 x1, c904 x1, ca01 x4, ca02/ca03/ca06/ca10/ca22/ca41 x1 each, d7 x1, d800 x1, d812 x1, da01 x1, e3, e4, e505, e7xx, ea, eb, f0, f1xx, f2xx. D9 total: 0. D8 total: 2 (d812, d800). Exactly as claimed.
```

**Expected**

The task brief and the repo's own comments assume a
docs/reference/rdcam_opcode_table.md. Every interactive byte the driver
emits should be traceable to a capture of real RDWorks traffic or to a
vendor table.

**Actual**

docs/reference/ does not exist (`ls docs/reference/` -> No such file or
directory), and no file in the repo references rdcam_opcode_table.md. The
fixture is a job stream only: it proves the encoder's C9/C6/CA/E7/A9 usage
and nothing about D9 10, D9 00/01, D8 01/02/03, D8 20-37, or the option
byte. That leaves ruida_maps.py and ruida_server.py as the only references —
and both are Rayforge source, authored alongside the emitter they are used
to validate. Checking rapid_move_xy against get_opt_desc is checking one
half of this repo against the other half; it can catch internal
inconsistency (and does — see the D9 10 opts finding) but cannot establish
what the controller does. Every 'confirmed' verdict in this audit therefore
rests on a self-reference, and the simulator is demonstrably contested in at
least one place already (D9 00/01 rel-vs-abs).

**Verification**

Traced every factual leg myself and all of them hold. (a) The get_opt_desc
quote is verbatim and at the claimed lines 299-308 of
rayforge/machine/driver/ruida/ruida_server.py. (b) I decoded
tests/machine/driver/ruida/fixtures/rdworks_reference.rd with the repo's own
unswizzle_byte(magic=0x88) and split on the MSB; the opcode histogram
matches the auditor's list item for item, D9 count is zero, and the only D8
commands are D8 12 and D8 00. (c) `ls docs/` -> No such file or directory,
so docs/reference/ cannot exist, and a repo-wide grep for
rdcam_opcode_table.md returns nothing. (d) The 'simulator is contested' sub-
claim is real: ruida_driver.py:944-947 documents that the single-axis D9
00/01 commands take an ABSOLUTE coordinate ('feeding them a relative delta
drove the head to the wrong end of the axis'), while ruida_server.py:323-330
applies them as RELATIVE (s.x += coord). Driver and simulator directly
contradict each other on that opcode, exactly as asserted. Two prose
overstatements corrected in corrected_evidence: ruida_client.py:656-663
(_build_move_opts) is a second in-repo definition of the same option byte,
and ruida_maps.py carries no D9 opt semantics at all. Both corrections leave
the substance intact, because _build_move_opts is Rayforge source too - it
is the emitter half being validated, so checking it against get_opt_desc is
precisely the circularity the finding names. Severity SMELL is correct and
needs no change: this is an observation about the evidentiary basis of the
audit, not a code defect. No head motion, no laser enable, no broken or
conditionally-wrong behaviour follows from it - it is correctness-neutral,
which is the definition of SMELL. It is also the only finding in the list,
so it cannot be a duplicate.

**Proposed fix**

Capture one RDWorks session that exercises the interactive commands — panel
jog in all four directions, a move-to, Go Scale/Frame, Stop, Pause, Resume,
Home — save it as a second fixture next to rdworks_reference.rd, and write
the decoded command list into docs/reference/rdcam_opcode_table.md with a
provenance line naming the controller model and firmware. Until that exists,
mark ruida_server.py's D8/D9 handlers with an explicit 'UNVERIFIED —
inferred, not captured' comment so nobody else mistakes them for a
specification, and add the same note above _build_move_opts.

**Test strategy**

Add a fixture-parity test in the shape of the existing encoder tests (see
the rd-fixture skill): decode the new interactive capture command-by-command
and assert that each byte sequence RuidaClient builds for the equivalent
action appears in it. That converts the simulator from the reference into
just another thing under test.

**Not reproducible in a test.** Wireshark on UDP 50200/50207 between RDWorks (or the RDCam panel software)
and the controller, one action at a time, with the head position noted
before and after each.

---

### MOT-48 - The transport's single-byte fast path is behaviourally identical to the general path and omits 0xC6, implying a distinction that does not exist

- **Severity:** SMELL
- **Location:** `rayforge/machine/driver/ruida/ruida_transport.py:140`
- **Class:** FAILURE CLASS 4 - Concurrency in RuidaClient and the driver's loops (tasks, locks, futures, Events, response attribution)
- **Status:** FIXED 6ee845366

**Evidence**

```python
        if len(data) == 1 and unswizzled[0] in (0xCC, 0xCD, 0xCE):
            self.decoded_received.send(self, data=unswizzled)
            return
```

**Expected**

Either the fast path does something the general path does not, or it is not
there.

**Actual**

Answering the question about 0xC6 directly: no, a single 0xC6 does not take
this path -- but it makes no difference. Both branches end in the same
`self.decoded_received.send(self, data=unswizzled)`, and the two magic
detectors the fast path skips are both no-ops for a 1-byte packet:
`detect_magic_from_payload` returns None unless `len(payload) == 4`
(ruida_codec.py:64-66) and `detect_magic_from_mem_request` requires
`len(unswizzled) >= 4` (ruida_codec.py:77-81). So a single 0xC6 -- a valid
job ACK per `_JOB_ACK_BYTES` in ruida_client.py:46 -- reaches
_handle_response identically to a 0xCC. The branch is correctness-neutral
dead weight whose asymmetric byte list invites the reader to believe 0xC6 is
handled differently, and it is exactly the kind of special case that would
silently become load-bearing if magic detection were ever extended to short
packets.

**Verification**

Verified line-by-line. The quoted code is exact and at the claimed line:
ruida_transport.py:140-142 reads `if len(data) == 1 and unswizzled[0] in
(0xCC, 0xCD, 0xCE): self.decoded_received.send(self, data=unswizzled);
return`. Both branches terminate in the same call with the same sender and
kwargs (line 141 vs line 153), and the RX debug log at 131-138 runs before
the branch, so it is common to both. The two detectors the fast path skips
are provably no-ops at length 1: detect_magic_from_payload returns None
unless len(payload)==4 (ruida_codec.py:64-66), and
detect_magic_from_mem_request requires len(unswizzled)>=4
(ruida_codec.py:77-81). I found no guard, side effect, or ordering
difference that makes the branch load-bearing. The 0xC6 half of the claim
also checks out: _JOB_ACK_BYTES at ruida_client.py:46-48 is frozenset({0xCC,
0xC6} | {unswizzle_byte(b, JOB_MAGIC) for b in (0xCC, 0xC6)}), and
_handle_response resolves a single 0xC6 as an ACK at ruida_client.py:148 and
:154 — it just arrives via line 153 instead of 141, indistinguishably. Git
history reinforces the reading rather than contradicting it: commit
3e73de87c added the branch in the same hunk that switched
detect_magic_from_payload(payload) to detect_magic_from_payload(data), i.e.
it was collateral to an argument change, not a protection for some
behaviour. Severity SMELL is right and should not be raised: no motion, no
firing, no lost behaviour, no conditional misbehaviour — purely a
readability/latent-hazard concern about an asymmetric byte list that would
become meaningful only if magic detection were extended to short packets.

**Proposed fix**

Delete the branch, or if it is meant as a documented guard against a future
short-packet detector, include the full ACK/NAK set and say so: `if
len(data) == 1: self.decoded_received.send(self, data=unswizzled); return`
with a comment that single-byte replies carry no magic and must never reach
the detectors.

**Test strategy**

Direct transport test: build RuidaTransport over a stub, record
decoded_received, and feed swizzled single bytes for 0xCC, 0xC6, 0xCF, 0xCD,
0xCE. Assert all five arrive unswizzled at the handler and that
transport.magic is unchanged in every case -- pinning the equivalence before
deleting the branch.

---

### MOT-49 - _on_unmapped clears the root handler id even when it did not disconnect, and never remembers which root it connected to

- **Severity:** SMELL
- **Location:** `rayforge/ui_gtk/machine/jog_widget.py:585`
- **Class:** FAILURE CLASS 8 — UI handler wiring in rayforge/ui_gtk/machine/jog_widget.py (connection, ownership, and teardown of the interactive-motion handlers)
- **Status:** FIXED d426885ac

**Evidence**

```python
    def _on_unmapped(self, widget):
        root = self.get_root()
        if isinstance(root, Gtk.Window) and self._root_active_handler:
            root.disconnect(self._root_active_handler)
        self._root_active_handler = None
```

**Expected**

The notify::is-active connection is disconnected from the exact object it
was made on, and the stored id is cleared only when the disconnect actually
happened.

**Actual**

The handler id is stored without its root, the connect guard tests `is None`
while the disconnect guard tests truthiness, and the id is cleared
unconditionally — so if get_root() ever returns None or a non-Window at
unmap time the connection leaks permanently (the closure keeps a reference
to the widget) and the next map adds a second handler, doubling
_release_all_jog_keys on every window deactivation. In practice this is
currently unreachable: GtkWindow is the only GtkRoot implementation in GTK4
(so the isinstance guard is dead code), GTK always emits "unmap" before
unrooting a widget, and both call sites root the widget in a real window
(bottom_panel.py:121 in the main window, wizard.py:267 inside
PatchedDialogWindow, which subclasses Adw.Window). Worth tightening because
the failure mode is silent and the fix is two lines.

**Verification**

The quoted code at jog_widget.py:585-589 is verbatim, and the asymmetry is
genuine: _on_mapped (576-583) guards with `is None` while _on_unmapped
guards with truthiness, the handler id is stored without the object it was
connected to, and `self._root_active_handler = None` executes even when the
disconnect branch did not. I confirmed the reachability caveat too -- every
GtkRoot implementor in the shipped typelibs (Gtk-4.0.gir and Adw-1.gir:
AboutDialog, ApplicationWindow, Assistant, Adw.Window,
Adw.PreferencesWindow, ...) derives from GtkWindow, so the isinstance guard
cannot fail today, and both call sites (bottom_panel.py:101/121 and
wizard.py:267) root the widget in a real window. Correctly filed as SMELL:
latent, currently unreachable, correctness-neutral.

**Proposed fix**

Store the object alongside the id (`self._root_window = root`), disconnect
from self._root_window rather than from get_root(), guard both sides with
`is not None`, and only clear the id inside the branch that actually
disconnected.

**Test strategy**

Direct handler invocation: call widget._on_mapped(widget) with a stubbed
get_root returning a MagicMock window, then _on_unmapped with get_root
patched to return None, then _on_mapped again; assert the stub window saw
exactly one connect and one disconnect.

---

### MOT-50 - The jog-speed debounce timeout is never cancelled on teardown

- **Severity:** SMELL
- **Location:** `rayforge/ui_gtk/machine/jog_widget.py:599`
- **Class:** FAILURE CLASS 8 — UI handler wiring in rayforge/ui_gtk/machine/jog_widget.py (connection, ownership, and teardown of the interactive-motion handlers)
- **Status:** FIXED d426885ac

**Evidence**

```python
        if self._jog_speed_timeout_id is not None:
            GLib.source_remove(self._jog_speed_timeout_id)
        self._jog_speed_timeout_id = GLib.timeout_add(
            _JOG_SPEED_DEBOUNCE_MS, self._commit_jog_speed
        )
```

**Expected**

Every GLib source the widget owns is dropped when the widget goes away;
nothing it scheduled should reach a driver after teardown.

**Actual**

Two timeouts exist, and only one is cleaned up: _cancel_pending_hold()
removes _hold_timeout_id from _release_all_jog_keys (line 522), which
_on_unmapped calls — but _jog_speed_timeout_id is removed only by the next
set_jog_speed() or by its own firing. There is no destroy/dispose handler
(GTK4 has no "destroy" signal; the widget also does not override do_dispose
or hook "unroot"). Close the panel or the print-and-cut wizard within 300 ms
of moving the speed slider and _commit_jog_speed still runs, pushing
set_jog_speed to the driver of a widget that no longer exists. It is not a
use-after-free — PyGObject's timeout holds a strong reference to the bound
method, and _commit_jog_speed touches no GTK API — so the real cost is a
stray command plus the widget being kept alive for the remainder of the
interval.

**Verification**

Confirmed: _cancel_pending_hold() (533-539) is the only GLib source cleanup,
it is reached from _release_all_jog_keys (522) and hence from _on_unmapped
(590), and _jog_speed_timeout_id (line 71, armed at 599-603) is removed only
by the next set_jog_speed() or by _commit_jog_speed firing (607). Nothing in
the class overrides do_dispose or hooks a teardown signal. One factual
correction to the write-up: GTK4 DOES still have the GtkWidget::destroy
signal (Gtk-4.0.gir:181873 `<glib:signal name="destroy">`), and this
codebase already uses it -- pref_rows/base.py:101 `self.connect("destroy",
self._on_destroy)` -- so the claim that no destroy hook is available is
wrong and the fix is even simpler than stated. The impact assessment stands:
_commit_jog_speed touches no GTK API and only pushes set_jog_speed to the
driver, so the cost is a stray command plus a briefly retained widget. SMELL
is correct.

**Proposed fix**

Add the same removal to _on_unmapped: `if self._jog_speed_timeout_id is not
None: GLib.source_remove(self._jog_speed_timeout_id);
self._jog_speed_timeout_id = None` — or factor a
_cancel_pending_speed_push() next to _cancel_pending_hold() and call it from
_release_all_jog_keys.

**Test strategy**

Direct handler invocation: widget.set_jog_speed(80);
widget._on_unmapped(widget); assert widget._jog_speed_timeout_id is None and
that calling the (now removed) callback is impossible — plus
machine_cmd.set_jog_speed.assert_not_called().

---

### MOT-51 - _on_connection_status_changed drops the held-key set without sending key-ups or the driver sweep

- **Severity:** SMELL
- **Location:** `rayforge/ui_gtk/machine/jog_widget.py:652`
- **Class:** FAILURE CLASS 8 — UI handler wiring in rayforge/ui_gtk/machine/jog_widget.py (connection, ownership, and teardown of the interactive-motion handlers)
- **Status:** FIXED d426885ac

**Evidence**

```python
    def _on_connection_status_changed(self, sender, **kwargs):
        """Handle connection status changes to update button sensitivity."""
        if self.machine and not self.machine.is_connected():
            # Nothing can be sent any more; the driver releases its own
            # held keys as it tears the transports down.
            self._cancel_pending_hold()
            self._keys_down.clear()
```

**Expected**

Per the base contract (driver.py:700-707, "the safety net behind press-and-
hold jogging ... Callers invoke it whenever the UI can no longer guarantee a
release") and the widget's own _release_all_jog_keys docstring ("Called from
every path where a key-up could otherwise be lost"), a lost connection
should queue jog_key_up / release_all_jog_keys so the release reaches the
driver as soon as anything is sendable again.

**Actual**

This is the one release path that sends nothing at all — it only clears the
widget's own set. The comment's premise is a driver-specific accident, not a
contract: Driver.release_all_jog_keys (driver.py:700) has an empty body, and
only RuidaDriver happens to call it from _disconnect_transports
(ruida_driver.py:398-400) and cleanup (254). The status the widget reacts to
is forwarded straight from the transport (RuidaDriver._on_status_changed,
ruida_driver.py:1104-1107, fed by UdpTransport's ERROR emissions in
transport/udp.py:60,72,145), which fires before — and independently of — the
driver's own teardown. In that window the widget has forgotten ('x',1) while
the driver still holds it and the long move is still executing, so the
user's subsequent button release sends no key-up; the head is left to the
driver's teardown sweep, which for any future hold-jog driver that does not
implement one is nothing at all.

**Verification**

The code is exactly as quoted at jog_widget.py:652-659, and it is indeed the
only release path that clears _keys_down without queueing jog_key_up /
release_all_jog_keys, contradicting _release_all_jog_keys' own docstring
(515-521). Driver.release_all_jog_keys (driver.py:700-707) really is an
empty body, and only RuidaDriver calls it from cleanup (254) and
_disconnect_transports (398-400). The ordering window is real: the
connection loop emits `_update_connection_status(TransportStatus.ERROR,
...)` before `await self._disconnect_transports()`. But I could not find any
reachable harm, so the severity is over-rated. Only the main
_ruida_transport's status_changed is wired to _on_status_changed
(ruida_driver.py:219) -- the jog UDP transport is not -- so every non-
CONNECTED status means the link is genuinely down and no key-up could reach
the controller anyway, and RuidaDriver (the only can_hold_jog driver today)
sweeps its own _jog_keys_down microseconds later on the same event-loop
pass. Downgraded to SMELL: a genuine inconsistency with the widget's stated
contract, correctness-neutral in every shipping configuration; the 'future
driver without a sweep' harm is speculative.

**Proposed fix**

Replace the bare `self._keys_down.clear()` with
`self._release_all_jog_keys()` (which already sends the per-key jog_key_up
plus machine_cmd.release_all_jog_keys as a sweep). Those tasks are cheap no-
ops when the driver is genuinely gone, and correct when the drop was
transient.

**Test strategy**

Extend tests/ui_gtk/machine/test_jog_widget_hold.py::test_disconnect_drops_t
he_held_key_set: after _hold(widget, EAST) and a DISCONNECTED status, assert
machine_cmd.jog_key_up.assert_called_once_with(machine, 'x', 1) and
machine_cmd.release_all_jog_keys.assert_called_once_with(machine), not just
that _keys_down is empty.

---

## Rejected during verification

Kept for the record; none of these were deleted, they simply did not
survive adversarial review or duplicate a finding above.

| Claim | Disposition |
| --- | --- |
| _wait_for_jog_settled always computes a zero distance, so the settle timeout is a flat 1.0 s regardless of step size or speed | duplicate of *_wait_for_jog_settled always computes a zero travel distance, so a step jog gives up after 1 s and the next step is measured from a mid-move position* |
| _jog_origin fabricates (0,0) when the position read fails, turning a 10 mm step into a full-bed absolute rapid | duplicate of *A failed position read makes the jog origin (0, 0), turning a 10 mm jog into a full-bed traverse to the machine corner* |
| _on_position_updated invents the unseen axis as 0, and the resulting non-None cache stops _jog_origin from ever re-reading | duplicate of *_on_position_updated invents 0 for the axis it has not seen yet, so a jog landing between the X and Y position responses drives Y to the bed edge* |
| A single-step jog's settle timeout is always exactly JOG_SETTLE_GRACE (1.0 s) — the travel-time term is always zero | duplicate of *_wait_for_jog_settled always computes a zero travel distance, so a step jog gives up after 1 s and the next step is measured from a mid-move position* |
| A failed position resync in _stop_jog_motion leaves the cache holding the commanded bed-limit target, then clears the busy flag anyway | duplicate of *_stop_jog_motion leaves the commanded bed-limit target cached when the resync read fails, so the next step jog runs to the far end of the bed* |
| _jog_origin falls back to (0, 0), so an unknown position sends the head to the origin corner on the next jog | duplicate of *A failed position read makes the jog origin (0, 0), turning a 10 mm jog into a full-bed traverse to the machine corner* |
| Go Scale streams the travel speed once for five moves, contradicting set_travel_speed's own documented non-persistence | refuted: REFUTED. The claimed consequence contradicts the code it cites: the C9 02 at ruida_driver.py:656 IS the last speed latched before all five _jog_move_to calls, and nothing between them (the loop only sends D9 10 via rapid_move_xy) changes it - _jog_move_to explicitly sends no speed (docstring at 940- |
| A jog stop during Go Scale halts the head, then the frame loop resumes motion on its own | duplicate of *release_all_jog_keys clears trace_frame's borrowed _jog_busy: Go Scale stops, then resumes moving on its own* |
| Concurrent position reads of one register strand each other; no request/response correlation and purge() is never called | duplicate of *_pending_mem_reads holds one future per address: a second overlapping read of the same address orphans the first, and the orphan's timeout evicts a stranger's future* |
| Z jog is advertised by the UI but silently dropped by the driver, and a held Z arrow pins _jog_busy so X/Y clicks stop working | duplicate of *Z jog deltas are silently discarded by both Ruida jog paths while the Z buttons stay enabled, and a Z hold leaks _jog_busy* |
| _on_position_updated fabricates 0 for the partner axis when no position is cached yet | duplicate of *_on_position_updated invents 0 for the axis it has not seen yet, so a jog landing between the X and Y position responses drives Y to the bed edge* |
| Every interactive rapid is sent with option byte 0x00 = "Origin" while the payload is an absolute machine coordinate | duplicate of *D9 10 targets are documented as anchor-relative but fed absolute machine coordinates read back from 0x0421/0x0431* |
| D8 01 is the only stop for a press-and-hold jog, and nothing in the repo confirms it halts a D9 10 rapid | duplicate of *D8 01 is assumed to halt an interactive D9 10 rapid; the only in-repo decoder says it is a process stop that does not touch motion* |
| home() waits on a Current-X memory read, which the position poller answers within 500 ms regardless of homing state | duplicate of *home() is not tracked as busy and its completion wait is satisfied by any position reply, including the background poller's* |
| Z jog is advertised and enabled but emits no motion opcode — a Z hold sends only a speed command and then a Stop Process | duplicate of *Z jog deltas are silently discarded by both Ruida jog paths while the Z buttons stay enabled, and a Z hold leaks _jog_busy* |
| The jog channel (port 50207) is opened and never used; the whole panel-key command surface is unreachable | duplicate of *The repo's only modelled motion-stop primitive, and the whole jog UDP channel, are dead code* |
| One shared _hold_timeout_id for all jog buttons — any press/leave/release cancels another button's pending hold | duplicate of *One hold timer for every arrow: a second press kills the first's hold, and any release kills whichever hold is armed* |

---

## Summary

| Severity | Status | Count | Findings |
| --- | --- | --- | --- |
| SAFETY | Fixed | 8 | MOT-01, MOT-02, MOT-03, MOT-04, MOT-06, MOT-07, MOT-08, MOT-09 |
| SAFETY | Needs hardware | 1 | MOT-05 |
| BROKEN | Fixed | 6 | MOT-10, MOT-11, MOT-12, MOT-13, MOT-14, MOT-15 |
| DEGRADED | Fixed | 20 | MOT-16, MOT-18, MOT-19, MOT-20, MOT-21, MOT-22, MOT-23, MOT-25, MOT-26, MOT-27, MOT-28, MOT-29, MOT-30, MOT-31, MOT-32, MOT-33, MOT-34, MOT-35, MOT-36, MOT-37 |
| DEGRADED | Deferred | 2 | MOT-17, MOT-24 |
| SMELL | Fixed | 11 | MOT-39, MOT-41, MOT-42, MOT-43, MOT-44, MOT-45, MOT-46, MOT-48, MOT-49, MOT-50, MOT-51 |
| SMELL | Fixed, byte unverified | 3 | MOT-38, MOT-40, MOT-47 |

| Status | Count |
| --- | --- |
| Fixed | 45 |
| Fixed, byte unverified | 3 |
| Needs hardware | 1 |
| Deferred | 2 |
| **Total** | **51** |

### Invariants at the end of Phase 3

- **Any motion the app starts, the app can stop, and every stop
  resyncs position before the busy flag clears.** `cancel()` is the
  one universal halt: it bumps the frame epoch, drops the held
  keys and goes through `_stop_jog_motion`, which sends the stop,
  reads the position back, and clears the cache outright when that
  read fails rather than keeping the target the head was only
  commanded toward. Covered by
  `TestStopReachesEveryMotion` and `TestEveryReleasePathStops`.
  The one thing this cannot promise is that `D8 01` brakes the
  controller: see MOT-05.
- **Input during motion is ignored, never queued.** The driver's
  busy interlock covers jog, step jog and trace alike, a job holds
  it for its whole upload and run, and a jog that commands nothing
  releases it instead of pinning it. At the widget, arrow-key
  auto-repeat counts once and `MachineCmd.jog` is keyed so a
  pending step is replaced rather than stacked. Below that,
  `UdpTransport.send` hands each datagram straight to the socket,
  so there is no application-level send queue to defeat the flag.
- **One authoritative unit conversion per value path.** The jog
  speed is mm/min from the panel row to `Driver.set_jog_speed`
  with no conversion in between; `RuidaDriver._set_travel_speed`
  is the only place mm/min becomes um/s; and
  `RuidaClient.set_travel_speed` is the only encoder of `C9 02`.
- **Every safety release path is covered by a test.** Release,
  gesture cancel, pointer leave, drag-off inside the grab, unmap,
  window focus loss, dropped connection and machine swap at the
  widget; key-up, release-all, transport teardown, cancel and
  cleanup at the driver.
