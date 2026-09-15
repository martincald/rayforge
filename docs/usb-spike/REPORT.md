# Ruida USB Transport Spike — Report (brief item U6)

Scope: owner-facing summary of the whole USB spike (U1-U6), verified
against the *current* tree in this pass (the transport, its wiring,
and both ladder scripts already exist; this pass re-verified every
claim, closed U2, fixed one real bug, and rewrote this report, which
had gone stale relative to the code).

Boundary compliance (verified in this pass):
`git diff --stat HEAD -- swiftcut/machine/transport/ swiftcut/machine/driver/ruida/ruida_transport.py swiftcut/machine/driver/ruida/ruida_client.py`
shows only `ruida_client.py` (+9, diagnostics timestamps
`last_enq_sent_at`/`last_ack_received_at`, unrelated to chunking/ACK
logic) and `swiftcut/machine/transport/udp.py` (+29, a bind-error
message for the UDP response port). Neither line came from this pass
-- both predate it / belong to the parallel UDP-path package. This
pass's only source edits are in `swiftcut/machine/driver/ruida/ruida_usb_transport.py`
(an owned file, two fixes -- see "Bugs found and fixed" below), plus
the U4 ENQ/ACK probe step added to `docs/usb-spike/probe_usb.py` /
`_usb_common.py` / `_usb_mock.py` and a new test in
`tests/machine/driver/ruida/test_ruida_usb_transport.py`.

## 1. What is known

### U1 facts (restated, not re-derived)

RDWorks talks to Ruida over USB via `FTD2XX.dll`. Serial framing =
same swizzle as UDP, but **no** 2-byte checksum; USB is a **single
stream** (no jog port). Baud is contested 19200 vs 38400, moot if the
chip is an FT245 FIFO (ignores baud). ACK `0xCC`/`0xC6`, NAK
`0xCF`/`0xCD`, stated as "same as UDP".

### U2: meerk40t reference (closed this pass)

`external/meerk40t` does not exist in this repo, but the box **does**
have network access (verified this pass, contradicting an earlier
pass's "the box is offline" note). Shallow-cloned to the scratchpad:

```
git clone --depth 1 https://github.com/meerk40t/meerk40t.git
commit 105bb5aa16540ded174ad423ccb13e87b9de22fc  (2026-08-25)
```

meerk40t has **two** Ruida serial-related files; only one is wired up.
`meerk40t/ruida/serial_connection.py`'s `SerialConnection` is
referenced only in that module's own README bullet -- grep across the
whole clone shows no import of it anywhere. The class actually
instantiated for `interface == 'usb'` is `USBTransport`
(`meerk40t/ruida/ruidasession.py:102` -> `usb.USBTransport(self.service)`),
defined in `meerk40t/ruida/usb_transport.py`. Citations below are all
against `USBTransport` at this commit:

| Fact | meerk40t citation | Value |
|---|---|---|
| Class / wiring | `meerk40t/ruida/usb_transport.py:31`, instantiated at `meerk40t/ruida/ruidasession.py:102` | `class USBTransport(RuidaTransport)` |
| Baud rate | `meerk40t/ruida/usb_transport.py:51` | hardcoded `115200` at open, with the code comment "Baud doesn't seem to matter much" (line 51) -- `self.baud = self.service.baud_rate` is stored at line 34 but never passed to `serial_open()` |
| Flow control | `meerk40t/ruida/usb_transport.py:53-54` | `rtscts=True, dsrdtr=True` (RTS/CTS and DSR/DTR hardware handshake enabled) |
| Timeouts | `meerk40t/ruida/usb_transport.py:38,52,101-109` | read timeout `0.25` s (`self._s_to`), passed as `timeout=self._s_to` to `serial_open()`; adjustable later via `set_timeout()` |
| ACK handling | `meerk40t/ruida/usb_transport.py:16-17` (module docstring) | **"There is no ACK handshake. The controller doesn't reply to ENQ since there is not ACK."** Confirmed by absence: `grep -rn "0xCC\|0xC6\|0xCF\|0xCD"` across `meerk40t/ruida/*.py` returns nothing. |
| Checksum | `meerk40t/ruida/usb_transport.py:15` | "There is no checksum on data sent to the controller." (agrees with U1/this repo) |
| VID:PID | `meerk40t/ruida/usb_transport.py:9` | `0x0403:0x6001` |

**This contradicts U1's ACK claim.** U1 states USB ACK bytes are "same
as UDP" (`0xCC`/`0xC6`, NAK `0xCF`/`0xCD`); meerk40t's own
reverse-engineering notes (its module docstring, sourced from a
Wireshark capture, not a guess) say the opposite: no ACK handshake
over USB at all, and the controller doesn't even answer ENQ. This
repo's `RuidaUsbTransport`/`RuidaClient.send_job()` currently assume
UDP-identical ACK/NAK bytes over USB (mock-verified only -- see
"Risks"). If meerk40t's finding holds for this hardware too, the
ACK-paced send loop would hang on every chunk until
`JOB_ACK_TIMEOUT`/`JOB_SEND_ATTEMPTS` are exhausted, then falsely
report every USB job send as failed. **This is the single highest-value
thing the owner's hardware run can settle**; see the decision table
in section 3.

### What the repo already provides

- `RuidaUsbTransport` (`swiftcut/machine/driver/ruida/ruida_usb_transport.py`)
  implements both backends: `"vcp"` (pyserial, `_VcpBackend` at
  ruida_usb_transport.py:508) and `"d2xx"` (ctypes D2XX binding,
  `_D2xxBackend` at ruida_usb_transport.py:549).
- **No checksum on TX** -- `send_command()`
  (ruida_usb_transport.py:713-726) swizzles and sends directly, no
  `frame_packet()` call, mirroring `RuidaTransport.send_response()`.
- **The ACK-paced send loop is reused, not duplicated.** Grepped
  `ruida_usb_transport.py` for any ACK/NAK/retry logic: none exists.
  `RuidaClient.send_job()`/`_send_job_chunk()`
  (`ruida_client.py:268`/`311`) own chunking, the per-chunk ACK wait,
  NAK retry, and timeout/give-up, unmodified for either transport --
  `RuidaClient` only type-hints `transport` under `TYPE_CHECKING` and
  never `isinstance`-checks it, so `RuidaUsbTransport` only needs to
  duck-type the same surface `RuidaTransport` provides.
- Wired into the driver (package U3 diff, already applied, uncommitted):
  `RuidaDriver._setup_usb`/`_setup_udp`/`_resolve_usb_backend`
  (`ruida_driver.py`), `ChoiceVar(key="connection", default="udp")`
  and `ChoiceVar(key="usb_backend", default="auto")` in
  `get_setup_vars()`. `connection` defaults to `"udp"`; the UDP branch
  (`_setup_udp`) is byte-for-byte what `_setup_implementation` did
  before this package existed (see "Verification" below).

## 2. What the owner must run

Before both steps: close RDWorks and SwiftCut. An FTDI device can be
opened by only one process at a time, so a program holding it makes
`probe_usb.py` look like "no device" and sends you down the wrong row
of the decision table.

Step 1 (opens/sends nothing):
```
source .msys2_env && PYTHONPATH=. /c/msys64/mingw64/bin/python.exe docs/usb-spike/enumerate.py
```
Run once with the laser's USB cable plugged in and once unplugged;
whatever entry disappears is the laser's FTDI chip.

Step 2 (sends only two read-only memory queries and one keepalive ENQ,
never motion/job commands -- verified by reading `probe_usb.py`: it
calls only `RuidaClient.get_card_info()`/`read_position()`/
`send_command_wait_ack(b"\xce", ...)`):
```
source .msys2_env && PYTHONPATH=. /c/msys64/mingw64/bin/python.exe docs/usb-spike/probe_usb.py --port COM<n>
# or, for D2XX-only devices:
source .msys2_env && PYTHONPATH=. /c/msys64/mingw64/bin/python.exe docs/usb-spike/probe_usb.py --backend d2xx
```
On the wire this sends the card-ID query `DA 00 05 7E`, the position
query `DA 00 04 21`/`DA 00 04 31`, and then a keepalive ENQ `0xCE` --
all swizzled with **no** checksum prefix (4 raw bytes on the wire for
a 2-byte command, not 6) -- confirmed against the mock in this pass
(see "Verification"). The ENQ step is a deliberate addition beyond
U4's original text (card ID + position only); see "Deviations from
spec" for why it was necessary.

## 3. What the results decide

`enumerate.py`'s result picks the backend to point `probe_usb.py` at
(same as before):

| `enumerate.py` result | Meaning | Next step |
|---|---|---|
| Shows a COM port with FTDI VID `0x0403` | Chip is in VCP mode | `probe_usb.py --port COM<n>` (backend `vcp`) |
| Shows no COM port, but D2XX lists >=1 device | Chip is D2XX-only (VCP bit cleared in EEPROM) | `probe_usb.py --backend d2xx`; `pyserial` will never see this device |
| Finds nothing on either backend | Cable/power/driver-binding issue | Check Device Manager for a WinUSB/libusbK rebind (e.g. via Zadig) before assuming no device |

`probe_usb.py` now asks two independent questions -- does the card-ID
query decode, and does ENQ get ACKed -- because the first alone cannot
settle whether this hardware ACKs at all (see U2/meerk40t: memory
reads may well work even on hardware with no ACK handshake, since a
`DA 01 ...` reply is not the same thing as an ACK byte). **The
combination of both answers**, not either alone, decides the next
step:

| Card ID / position decode? | ENQ/ACK support? | Meaning | Next step |
|---|---|---|---|
| OK | YES (`0xCC`/`0xC6` within ~1s) | Framing, swizzle, RX reassembly, and the ACK handshake all work on this hardware -- consistent with U1's "same as UDP" assumption, not meerk40t's | The current ACK-paced design is viable for this hardware **once the keepalive-race blocker in Risks (item a) is fixed**. Only then proceed to `jog_usb.py`, then `send_fixture_usb.py`, when ready to move the machine. |
| OK | NO (timeout or NAK) | Memory reads work (a `DA 01` reply is not an ACK byte), but the ACK handshake this repo's `send_job()`/`send_command_wait_ack()` depend on does not exist on this hardware -- matches meerk40t's finding exactly | **Stop. Do not run `send_fixture_usb.py`.** `send_job()`'s ACK-paced chunking and the driver's connect handshake (which also waits on ACKs) cannot work unmodified over this link. The pacing strategy needs a redesign before any real job send is attempted -- see meerk40t's approach (`meerk40t/ruida/usb_transport.py`: no ACK wait at all, chunked write-and-continue) as a starting point for that redesign, which is out of this spike's scope. |
| TIMEOUT (no reply at all, not even a NAK) | -- (unreachable; ENQ is sent after the position query) | Framing/magic/backend problem, not a protocol-behavior question | Try `--magic` variants; if still silent, re-check wiring/power and the backend chosen by `enumerate.py` before re-running |

## 4. Risks

FTDI Windows driver data-loss / large-write issues are a documented
real risk for a job stream that can be many kilobytes. The mitigations
below are inherited unmodified from the UDP path because `RuidaClient`
owns them for both transports -- **but see item (a): one of them is
currently not effective for either transport in the real app.**

- **Small chunks**: `JOB_CHUNK_MAX_BYTES = 1000` (`ruida_client.py:39`),
  used by `send_job()`/`build_datagrams()` regardless of transport.
- **ACK pacing + NAK retry**: `JOB_ACK_TIMEOUT = 4.0`,
  `JOB_SEND_ATTEMPTS = 4` (`ruida_client.py`, same block), enforced in
  `_send_job_chunk()` (`ruida_client.py:311`).
- **E5 05 file checksum**: an end-to-end integrity check independent
  of transport framing. `RuidaServer._accumulate_checksum()`
  (`ruida_server.py:1338`, gated on `CHECKSUM_COMMANDS` from
  `ruida_maps.py:567`) accumulates payload bytes as commands are
  processed; compared against the `0xE5 0x05` command
  (`ruida_server.py:126`, `ruida_protocol.py:40`). The encoder side is
  documented at `ruida_encoder.py:1127-1128`; `send_fixture_usb.py`
  computes and sends it (see its own docstring).

### (a) BLOCKER, shared code, not fixed by this pass: the keepalive ENQ is not actually suspended during a job send

**"ACK pacing" above is not an effective mitigation in the app as it
stands today, for USB or UDP, until this is fixed.** Verified against
the real `RuidaClient`/`RuidaDriver`, not just read:

- The comment at `ruida_driver.py:851-853` and the `send_job()`
  docstring at `ruida_client.py:281-282` both say the caller "must
  suspend keepalive and position polling for the whole send", and
  `RuidaDriver._send_job`-adjacent code wraps the send in
  `with self._polling_suspended():` (`ruida_driver.py:850`).
- But `_polling_suspended()`'s flag, `_suppress_polling`
  (`ruida_driver.py:250-252`), only gates the two *position-poll*
  blocks (`ruida_driver.py:696-699`, `:715-717`) -- **not** the
  keepalive-ENQ send at `ruida_driver.py:690-694`, which fires
  unconditionally on its own 1-second timer regardless of suspension.
- During `send_job`, that ENQ is serialized behind the same FIFO
  `_send_lock` job chunks use (`ruida_client.py:239-240` for
  `send_command`, `:322` for `_send_job_chunk`), so it queues onto the
  wire between two chunks rather than being blocked. Its `0xCC` reply
  then resolves `self._pending_job_acks.pop(0)`
  (`ruida_client.py:166-170`) -- the *next* pending chunk's future, not
  the ENQ's own tracking (there is none). Orchestrator repro against
  the real `RuidaClient`: wire order `chunk1, ENQ, chunk2` results in
  the ENQ's reply releasing what should have been chunk 3's wait
  before chunk 2 was ever acknowledged.
- Introduced by commit `01d841e3a` (MOT-22).
- **Does this apply to `send_fixture_usb.py`?** No -- verified by
  reading it: it constructs a bare `RuidaClient(transport)` directly
  (`send_fixture_usb.py:163`), never a `RuidaDriver`, so there is no
  background connection-management loop and no 1-second keepalive
  timer running concurrently with its `send_job()` call. The race is
  real, but it is a `RuidaDriver`-only defect (i.e. it affects the
  actual app, both over USB and UDP), not something this spike's own
  ladder script can trigger.
- Not fixed here: `ruida_driver.py` (outside this package's USB-only
  edit scope for that file) and `ruida_client.py` (fully forbidden)
  both need the fix, and the UDP path shares the exact same code path,
  so this is not a USB-specific defect to begin with.

### (b) No purge before a job send

`RuidaUsbTransport.purge()` (`ruida_usb_transport.py:705-707`, which
delegates to the backend-level `purge()` at `ruida_usb_transport.py:476`)
is only ever invoked as part of the D2XX open sequence itself
(`_D2xxBackend._open()`, `ruida_usb_transport.py:584`); grepping
`ruida_client.py` and `ruida_driver.py` for `.purge(` finds no other
call site. Nothing purges the RX buffer/driver buffer immediately
before `send_job()` starts. A stale byte left over from a previous
exchange could satisfy chunk 1's ACK wait spuriously, or a stray
`0xDA` byte could desync `RuidaUsbTransport._on_raw_received`'s
1-byte-or-9-byte reassembler (`ruida_usb_transport.py:728-747`) for
every reply after it. Not fixed: would need a `purge()` call added to
`RuidaClient.send_job()` itself, which is forbidden to this package.

### (c) `_UsbBackendBase.disconnect` closed the handle before joining the reader thread -- fixed this pass

Was: `_close()` (FT_Close/`serial.close()`) ran before
`self._reader_thread.join()`, so the close could race a `FT_Read()`/
`serial.read()` call still in flight on the reader thread -- a
driver-level race, not just a Python one. Fixed by reordering: the
reader thread is now joined first (bounded by each backend's own read
timeout -- 100 ms for d2xx via `FT_SetTimeouts`, 0.1 s for vcp via
pyserial's `timeout=` -- so the join cannot hang), then the handle is
closed. See `ruida_usb_transport.py`'s `disconnect()` docstring for
the reasoning, and `test_disconnect_joins_reader_thread_before_closing`
(`tests/machine/driver/ruida/test_ruida_usb_transport.py`) for the
regression test, which spies on the mock serial port's `close()` call
and asserts the reader thread has already exited by the time it fires.

### Residual/new risk found this pass: the ACK-handshake question itself is open

meerk40t's own USB reverse-engineering notes claim there is **no ACK
handshake at all** over USB serial (see U2 table), directly
contradicting U1's "ACK same as UDP" assumption that this repo's
transport and tests currently bake in. Nothing here has been run
against real Ruida hardware. `probe_usb.py`'s new ENQ/ACK step (see
"What the owner must run") is what settles this -- see the decision
table in section 3 for what each combination of results means. If
meerk40t is right for this hardware, `send_job()`'s ACK-paced chunking
would never see an ACK and time out/retry to exhaustion rather than
corrupting data -- fail-safe, but still means the current design
cannot send a real job over USB without a redesign.

Chunk size/timeout/retry values were carried over from UDP defaults,
not re-tuned for serial latency/throughput; if real-hardware testing
shows drops within a chunk, the fix (smaller chunks and/or longer
`JOB_ACK_TIMEOUT`) requires editing `ruida_client.py`, a file this
package does not own.

## 5. Deviations from spec

- **ctypes instead of the `ftd2xx` PyPI package.** The `ftd2xx` package
  cannot be installed in this environment (needs `pywin32`, no
  MSYS2/MinGW build; sdist fails on Python 3.14). `D2xxLibrary`
  (`ruida_usb_transport.py:148`) binds `ftd2xx64.dll` directly via
  `ctypes.WinDLL`, searching the normal DLL path first, then the
  Windows driver store (`_DRIVER_STORE_GLOB`,
  `ruida_usb_transport.py:90-93`). Documented and accepted (see
  `docs/reference/rdcam_usb.md` section 3).
- **Class name.** The spec text (and this repo's own stale
  `README.md`, until this pass) call it `RuidaSerialTransport`. The
  code that is actually wired into `RuidaDriver` is `RuidaUsbTransport`
  (`swiftcut/machine/driver/ruida/ruida_usb_transport.py:624`). Not
  renamed in this pass -- it is already imported by
  `ruida_driver.py` and covered by 117 passing tests under that name;
  renaming now would touch the USB-wiring block of `ruida_driver.py`
  for no functional gain. `README.md` is corrected in this pass to use
  the real name throughout.
- **Chunk size -- OPEN SPEC CONFLICT, not changed.** The task brief
  handed to this pass states "chunk size 512" for the USB transport.
  The checked-in, owner-derived brief transcription,
  `docs/reference/rdcam_usb.md:18`, states **"chunks of at most 1000
  bytes"** for the exact same job-stream TX path -- matching the
  current code, `JOB_CHUNK_MAX_BYTES = 1000` at `ruida_client.py:39`,
  shared verbatim with UDP. These two owner-sourced numbers disagree
  with each other, not just with the code. No `512` constant exists
  anywhere in the current USB code (confirmed by grep) -- an earlier,
  now-superseded draft used `CHUNK_SIZE = 512` for one backend's own
  *read*-buffer size only (not TX chunking), in a file that no longer
  exists; today both backends use `_READ_CHUNK_SIZE = 1024`
  (`ruida_usb_transport.py:76`). Changing `JOB_CHUNK_MAX_BYTES` to 512
  would require editing `ruida_client.py` (forbidden to this package)
  and would change the UDP path's chunk size too, since UDP and USB
  share that constant by design -- violating the "byte-identical UDP
  path" acceptance criterion. **Left as-is (1000, matching
  `rdcam_usb.md:18` and the current code); the owner needs to decide
  between "512 per the U5 spec text" and "1000 per the decompiled
  RDWorks brief and current code" -- this pass does not have grounds
  to pick one over the other.**
- **ENQ/ACK probe step in `probe_usb.py` (U4 addition, not in the
  original U4 text).** U4 only specified a card-ID query and a
  position read, both memory reads. Added in this pass: a third,
  still-read-only step that sends the keepalive ENQ (`0xCE`, swizzled,
  no checksum -- `probe_usb.py`'s `send_command_wait_ack(b"\xce", ...)`
  call) and reports whether an ACK comes back within ~1s. Necessary
  because U4's original two steps cannot distinguish "this hardware
  ACKs like UDP" from "this hardware has no ACK handshake at all"
  (meerk40t's finding, U2) -- a `DA 01` memory-read reply is not an ACK
  byte, so card ID/position could decode perfectly on hardware that
  never ACKs anything else. See the decision table in section 3 for
  why this distinction is load-bearing before `send_fixture_usb.py`
  is ever run.
- **Scope additions beyond U3/U5, not requested but already fully
  wired, so left in place per this package's file-boundary
  instructions**: `_UsbTrafficCounter` (`ruida_driver.py:52-99`, 48
  lines) and `RuidaDiagnostics.usb_backend`/`usb_device`/
  `usb_bytes_sent`/`usb_bytes_received` (`ruida_driver.py:100-128`,
  29 lines, 5 of those lines are the new `usb_*` fields). These are
  not dead code: `swiftcut/ui_gtk/machine/device_settings_page.py`
  (lines 195-198, 448-502) reads `get_diagnostics()` and renders all
  four `usb_*` fields in the Device settings page, and
  `tests/machine/driver/ruida/test_ruida_usb_wiring.py`
  (`TestUsbTrafficCounter`, `TestUsbDiagnostics`) covers them. Not
  removed (outside this package's mandate to delete unrequested-but-working
  code), and their removal would require editing a forbidden UI file
  anyway.

## 6. `jog_usb.py` / `send_fixture_usb.py` move the machine

These two scripts are **not** part of the U3/U4 decision ladder and
were not requested by the spec (U3 asked for `enumerate.py`, U4 asked
for `probe_usb.py`, both read-only -- `probe_usb.py`'s new ENQ step,
section 5, is still read-only: it sends one keepalive byte, no
motion). Verified by reading their code this pass:

- `jog_usb.py` calls `RuidaClient.rapid_move_axis(axis=0x00, coord=MOVE_UM)`
  -- one relative rapid move, +1.0 mm on X (`D9 00`).
- `send_fixture_usb.py` calls `RuidaClient.send_job(...)` with the
  RDWorks reference job (power zeroed), i.e. a full cut/engrave job
  stream.

Both are gated behind `confirm_or_exit()` (`_usb_common.py:89-106`,
requires `--yes` or a typed confirmation, refuses non-interactively
with no traceback) and were **not run against real hardware** in this
pass -- only `--mock` (see "Verification"). Do not run either against
a real controller without deliberately choosing to move the machine.
**Do not run `send_fixture_usb.py` at all until `probe_usb.py`'s
ENQ/ACK step reports YES and the keepalive-race blocker (Risks item a)
is fixed** -- see the decision table in section 3.

## 7. Bugs found and fixed this pass

1. `_D2xxBackend._open()` (`ruida_usb_transport.py`) called
   `clr_dtr()` then `clr_rts()`; the owner's brief
   (`docs/reference/rdcam_usb.md`, steps 10-11: `clrRts()` then
   `clrDtr()`) and this repo's own test
   (`test_d2xx_open_sequence_matches_brief_order`) both require the
   opposite order. Fixed by swapping the two calls (2-line change);
   the previously-failing test now passes. This was a real divergence
   from `FUN_10001C80`'s literal call order, not a cosmetic issue --
   the protocol's standing rule for this brief is to match the
   decompile exactly.
2. `_UsbBackendBase.disconnect()` closed the device handle before
   joining the reader thread -- see Risks item (c) for the full
   description, the fix, and its regression test.

## 8. Verification (this pass)

Tests:
```
$ source .msys2_env && /c/msys64/mingw64/bin/python.exe -m pytest \
    tests/machine/driver/ruida/test_ruida_usb_transport.py \
    tests/machine/driver/ruida/test_ruida_usb_wiring.py \
    tests/machine/driver/ruida/test_ruida_driver.py \
    -p no:cacheprovider -q
117 passed in 37.33s
```
(Before the two fixes in section 7: 1 failed, 115 passed, 116 total;
the 117th test is the new disconnect-ordering regression test.)

Mock scripts, both `--mock` ACK modes:
```
$ PYTHONPATH=. python docs/usb-spike/enumerate.py --mock
...
=== headline: which backend can open the device? ===
  d2xx -> 1 device(s)

$ PYTHONPATH=. python docs/usb-spike/probe_usb.py --mock
--- card ID query: DA 00 05 7E ---
  tx (swizzled): d4 89 0d f7          <- 4 bytes: no checksum prefix
  rx (unswiz.):  da 01 05 7e 06 28 41 4a 10
  -> card_id=0x65106510 model=RDC6442S
--- position query: DA 00 04 21 (X), DA 00 04 31 (Y) ---
  -> x=0um y=0um
--- keepalive probe: ENQ 0xCE (no checksum) ---
  tx (swizzled): c8
  rx (raw):      c6
  rx (unswiz.):  cc
  ACK/ENQ support: YES (0xCC/0xC6 received)

$ PYTHONPATH=. python docs/usb-spike/probe_usb.py --mock --mock-no-enq-reply
--mock-no-enq-reply: this mock device never ACKs ENQ.
--- card ID query: DA 00 05 7E ---
  -> card_id=0x65106510 model=RDC6442S
--- position query: DA 00 04 21 (X), DA 00 04 31 (Y) ---
  -> x=0um y=0um
--- keepalive probe: ENQ 0xCE (no checksum) ---
  tx (swizzled): c8
  ACK/ENQ support: NO (no reply within 1.0s)
```
Both modes decode card ID/position identically; only the ENQ step
differs, confirming `--mock-no-enq-reply` isolates exactly the
question the decision table needs answered.

Style: `awk 'length > 79'` and `python -m py_compile` against
`ruida_usb_transport.py`, `tests/machine/driver/ruida/test_ruida_usb_transport.py`,
and every `docs/usb-spike/*.py` -- both clean. Ruff/flake8 could not
be run (not installable in this environment); no ruff-clean claim is
made.

Boundary:
```
$ git diff --stat HEAD -- swiftcut/machine/transport/ \
    swiftcut/machine/driver/ruida/ruida_transport.py \
    swiftcut/machine/driver/ruida/ruida_client.py
 swiftcut/machine/driver/ruida/ruida_client.py |  9 +++++++++
 swiftcut/machine/transport/udp.py             | 29 ++++++++++++++++++++++++++-
```
Neither file's changes came from this pass (see the top of this
report); this pass's own source edit is confined to
`ruida_usb_transport.py`.

## 9. Status

Done and verified in this pass: `enumerate.py`/`probe_usb.py` exist,
compile, pass the 79-column check, and were re-run against `--mock` in
both ACK modes. `RuidaUsbTransport` exists, both backends implemented,
the d2xx open sequence now matches the brief exactly, and
`disconnect()` now joins the reader thread before closing the handle
(two bugs fixed, section 7). USB wiring in `RuidaDriver` (`_setup_usb`,
`precheck`, `get_setup_vars`) exists and is tested
(`test_ruida_usb_wiring.py`). U2 is closed with real citations against
a live clone. `probe_usb.py` now settles the ACK-handshake question
U1/U2 leave open, not just framing. Boundary respected: the only
forbidden-file diffs present belong to the concurrent UDP package, not
this pass.

**Not viable to ship as-is, pending one shared-code fix**: the
keepalive-ENQ race (Risks item a) means "ACK pacing" is not actually
effective in the running app today, for USB or UDP, regardless of
what the owner's hardware run reports. This is a `RuidaDriver`/
`RuidaClient` defect outside this package's edit scope, not a USB-spike
defect -- flagged, not fixed, per the file boundary.

Untested without real hardware, label as "mock-tested"/"static-review
only": byte-level correctness against a real Ruida controller for
either backend; whether the ACK-loop assumption (U1) or meerk40t's
"no ACK" finding (U2) is the one that holds for this hardware (now
directly testable via `probe_usb.py`'s ENQ step, but not yet tested
against real hardware); `jog_usb.py`/`send_fixture_usb.py`
(deliberately not run against real hardware by this pass, and not
part of the decision ladder -- see section 6).

The one next action for the owner: run `enumerate.py`, then
`probe_usb.py`, against the real controller, and read the *combination*
of its card-ID/position result and its ACK/ENQ result against the
section 3 table -- then fix the keepalive-race blocker (Risks item a)
before trusting any real job send, USB or UDP.
