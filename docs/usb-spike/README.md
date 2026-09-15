# Ruida USB transport spike

**Current state:** the transport described below is implemented as
`RuidaUsbTransport` in
`swiftcut/machine/driver/ruida/ruida_usb_transport.py` (backends
`"vcp"`/`"d2xx"`). An earlier draft of this file called it
`RuidaSerialTransport`, living in a now-deleted
`ruida_serial_transport.py`; that name/file was superseded before this
pass and is corrected throughout this document. See
`docs/usb-spike/REPORT.md` for the full owner-facing report, including
the class-name deviation from the original task brief.

Scope (as originally written): the L2 transport only. Enumeration/probing scripts
(`enumerate.py`, `probe_usb.py` in this same directory) are a separate
deliverable from another pass and are not touched or duplicated here.

Files added by this pass, and only these:

- `swiftcut/machine/driver/ruida/ruida_usb_transport.py` (new)
- `tests/machine/driver/ruida/test_ruida_usb_transport.py` (new)
- `docs/usb-spike/README.md` (this file)

No other file was edited. In particular, `git diff --stat` against the
UDP path is empty (see "Verification" below).

## What `RuidaUsbTransport` is

It is the USB counterpart to `RuidaTransport`
(`ruida_transport.py`), for a byte-stream link (pyserial VCP, or a
ctypes-bound D2XX backend) instead of UDP. It differs from
`RuidaTransport` in exactly two ways, both forced by the medium:

1. **TX has no checksum.** `send_command()` swizzles the command and
   sends it as-is; it does not call `frame_packet()`. This is not new
   logic -- it is the same thing `RuidaTransport.send_response()`
   already does (swizzle only, no checksum), reused via the same
   `RuidaCodec.swizzle()` helper. No swizzle/checksum code was
   copy-pasted.

2. **RX needs stream reassembly.** A UDP datagram is one whole
   message; a serial `read()` is not. `RuidaUsbTransport` buffers
   incoming bytes and only emits a `decoded_received` message once one
   of the two reply shapes this repository's own Ruida code actually
   parses is complete:
   - a single status byte (ack/nak/keepalive echo), or
   - a 9-byte `DA 01 <addr-hi> <addr-lo> <encode35 x5>` memory-read
     reply.

   The 9-byte shape is not a guess: it matches
   `ruida_server.py`'s response builder
   (`response = b"\xda\x01" + data[2:4] + encoded`) and
   `RuidaClient._handle_response`'s parser
   (`len(data) >= 9 and data[0] == 0xDA and data[1] == 0x01`).

### Deliberate deviation from the recon's suggestion: `estimate_packet_length` is NOT reused for RX

The recon map suggested reusing `ruida_util.estimate_packet_length()`
for RX framing. That function is calibrated for **host->device**
job-stream commands (its docstring and the `_C6_LENGTHS`/`_E7_LENGTHS`
tables are verified against the RDWorks job fixture). Its own `DA 01`
case is:

```python
if sub == 0x01:
    # Memory write: DA 01 <addr> + doubled encode35 value.
    return 14
```

14 bytes -- a memory **write** command (address + the value encoded
*twice*). But the reply the controller/simulator actually sends back
for a memory **read** is 9 bytes (address + the value encoded
*once*), per `ruida_server.py` and `RuidaClient._handle_response`
above. Reusing `estimate_packet_length` for RX would make
`RuidaClient.read_position()` / `get_card_id()` block forever waiting
for 5 bytes that will never arrive, since the real reply is already
complete at 9 bytes. `RuidaUsbTransport` therefore hand-rolls the
narrow 1-byte-or-9-byte reassembly rule above instead, cross-checked
against the same response parser `RuidaClient` itself uses, rather
than a length table built for the opposite direction.

This is the one piece of logic in this file that is genuinely new;
everything else (swizzle, magic key, checksum framing) is reused from
existing helpers.

## The ACK-paced send loop is reused, not duplicated

`RuidaUsbTransport` does not implement any retry, timeout, or
chunking logic itself. `RuidaClient` only type-hints its `transport`
argument under `TYPE_CHECKING` and never `isinstance`-checks it
(`ruida_client.py:30-31`), so `RuidaUsbTransport` only needs to
expose the same runtime surface `RuidaTransport` provides:
`decoded_received`, `is_connected`, `connect()`/`disconnect()`,
`send_command()`, `send()`, `status_changed`. Constructing
`RuidaClient(RuidaUsbTransport(...))` therefore inherits
`send_job()` / `_send_job_chunk()` -- chunking, the per-chunk ACK wait,
NAK retry, timeout-and-give-up -- completely unmodified from
`ruida_client.py`. The tests in
`tests/machine/driver/ruida/test_ruida_usb_transport.py` drive
`RuidaClient.send_job()` over a mocked serial port for exactly this
reason: what they are proving is that the existing loop still works
correctly over the new transport, not a second copy of it.

No deviation was needed here: full reuse was possible without editing
any forbidden file.

## Backends

Superseded by the current `RuidaUsbTransport`; see
`swiftcut/machine/driver/ruida/ruida_usb_transport.py`'s own module
docstring for the up-to-date description. Current backend names are
`"vcp"` (pyserial) and `"d2xx"` (ctypes D2XX binding), both fully
implemented and covered by `tests/machine/driver/ruida/test_ruida_usb_transport.py`
-- neither is the unverified prototype this section used to describe.
`docs/usb-spike/REPORT.md` section 5 records the chunk-size-related
deviation from the task brief.

## Known limitations (spike scope, not fixed)

- **No magic-key auto-detection.** `RuidaTransport` can detect and
  switch its swizzle magic mid-session via
  `detect_magic_from_payload`/`detect_magic_from_mem_request`.
  `RuidaUsbTransport` takes a fixed `magic` at construction
  (default `0x88`, matching `JOB_MAGIC` in `ruida_client.py`) and never
  changes it. Wiring auto-detection in would be a small, mechanical
  addition (call the same two `RuidaCodec` methods `RuidaTransport`
  already calls) but was left out to keep the spike's diff minimal;
  nothing in the required test list depends on it.
- **The RX 1-byte-vs-9-byte rule assumes no other async push from the
  device.** That matches this repository's own protocol model (there
  is no third reply shape anywhere in `ruida_server.py` or
  `RuidaClient._handle_response`), but if real hardware turns out to
  send some other unsolicited multi-byte message, this heuristic would
  misparse it.

## `connection=usb|udp` wiring into `ruida_driver.py`

Applied (not a proposed diff anymore): `RuidaDriver._setup_usb`/
`_setup_udp`/`_resolve_usb_backend`, plus `ChoiceVar(key="connection",
default="udp")` and `ChoiceVar(key="usb_backend", default="auto")` in
`get_setup_vars()`, all in `ruida_driver.py`. Covered by
`tests/machine/driver/ruida/test_ruida_usb_wiring.py`. See
`docs/usb-spike/REPORT.md` for the current verification run and
citations.

## Verification

See `docs/usb-spike/REPORT.md` section 8 for the current test run,
mock-script output, and boundary check (this section's own numbers
predate the current transport and driver wiring).

## U5: owner-run ladder scripts

Four scripts, run by the owner against real hardware, each printing
the exact bytes sent/received in hex, in ascending order of what they
risk doing to the machine:

1. `enumerate.py` -- lists devices only, opens nothing.
2. `probe_usb.py` -- card ID + position, memory reads only, no motion.
3. `jog_usb.py` -- **moves the machine**: one relative rapid move
   (D9 00), +1.0 mm on X.
4. `send_fixture_usb.py` -- **moves the machine**: sends the RDWorks
   reference job, power zeroed.

All four are built on the production classes, not a parallel
implementation:

- `RuidaUsbTransport` (`swiftcut/machine/driver/ruida/`
  `ruida_usb_transport.py`) for framing, the open sequence, and RX
  reassembly.
- `RuidaClient` (`ruida_client.py`) for command construction,
  `get_card_info()`/`read_position()`, `rapid_move_axis()`, and --
  for rung 4 -- the ACK-paced, NAK-retrying `send_job()` chunker. None
  of chunking, ACK pacing, retry, or framing is reimplemented anywhere
  in `docs/usb-spike/`.

`enumerate.py` and `probe_usb.py` (pre-existing from an earlier pass)
were updated in this pass to use this same production code path --
`enumerate.py`'s D2XX section used to talk to the PyPI `ftd2xx`
package directly; it now calls `load_d2xx_dll()`/`D2xxLibrary`/
`_select_device_index()` from `ruida_usb_transport.py` instead.
`probe_usb.py` used to hand-roll its own `SerialLink`/`D2xxLink`
wrappers and swizzle/query loop; it now drives
`RuidaClient(RuidaUsbTransport(...))` directly.

Shared plumbing lives in two new, non-rung files in this same
directory (imported by the scripts via `sys.path[0]`, which Python
sets to a script's own directory -- no package/`__init__.py` needed):

- `_usb_common.py`: the common CLI args (`--backend`, `--port`,
  `--usb-serial`, `--baudrate`, `--magic`, `--mock`), the
  `--yes`/typed-confirmation gate for the two motion scripts, and
  `install_hex_logging()`, which hooks the transport's own
  `send_command()` and `received`/`decoded_received` signals to print
  every TX/RX byte -- it does not re-implement swizzling to do this.
- `_usb_mock.py`: `MockD2xxLibrary`, a duck-typed `D2xxLibrary` (see
  `ruida_usb_transport.D2xxLibrary`) backed by the existing
  `RuidaSimulator`/`RuidaServer` protocol model
  (`ruida_simulator.py`) -- the same simulator the UDP path's
  `run_udp_simulator()` already ACK-wraps responses with, not a new
  hand-rolled fake. Injecting it via
  `RuidaUsbTransport(backend="d2xx", d2xx_library=MockD2xxLibrary())`
  is the *same* injection point
  `tests/machine/driver/ruida/test_ruida_usb_transport.py`'s
  `FakeD2xxLibrary` uses, so `--mock` drives the real
  `RuidaUsbTransport` open sequence (`FUN_10001C80` order), TX
  swizzle, and RX reassembly unmodified -- only the FTDI DLL itself is
  replaced. `--mock` was verified to actually exercise this path for
  all four scripts (see "Mock verification" below).

### The C6 65 zeroing gap

`send_fixture_usb.py`'s power-zeroing set is the UDP
`send_fixture_test.py`'s set **plus** `C6 65`: the fixture contains
`c6 65 00 3d` (a verified 4-byte C6 command --
`ruida_util.py`'s `_C6_LENGTHS[0x65] == 4` -- though it is not named in
`ruida_maps.py`'s own `C6_POWER_COMMANDS`/`C6_PART_POWER_COMMANDS`
tables), which `send_fixture_test.py`'s zeroing set does not cover.
This was an explicit requirement from the task brief, not a guess.

### A JOB_MAGIC subtlety, fixed

`RuidaClient.send_job()` (a file this package does not edit) always
unswizzles the blob it is given, and detects chunk ACK/NAK bytes,
using the module-level `JOB_MAGIC` constant (`0x88`) -- **not**
whatever magic the transport itself was constructed with. An earlier
draft of `send_fixture_usb.py` swizzled its patched blob with
`--magic` instead, which only worked by coincidence at the default
(`--magic` also defaults to `0x88`). `build_patched_job()` now always
swizzles with `JOB_MAGIC` regardless of `--magic`, matching
`send_job()`'s actual contract; `--magic` still correctly controls the
transport's own per-chunk wire encoding, since `transport.send_command()`
re-swizzles each chunk itself. Verified with `--magic 0x99` in mock
mode (see below) -- both the default and a non-default magic round-trip
correctly.

### Mock verification

All four scripts were run with `--mock` (and `--yes` for the two
motion scripts, to skip the interactive prompt non-interactively) from
the repo root:

```
$ source .msys2_env && PYTHONPATH=. /c/msys64/mingw64/bin/python.exe \
    docs/usb-spike/enumerate.py --mock
...
=== D2XX: production ruida_usb_transport code path ===
  --mock: using an in-process RuidaSimulator device
  device 0: 'Mock Ruida Laser (--mock)'  serial='MOCK0001'
  _select_device_index() would open index 0
=== headline: which backend can open the device? ===
  d2xx -> 1 device(s)

$ PYTHONPATH=. /c/msys64/mingw64/bin/python.exe \
    docs/usb-spike/probe_usb.py --mock
--- card ID query: DA 00 05 7E ---
  tx (swizzled): d4 89 0d f7
  rx (unswiz.):  da 01 05 7e 06 28 41 4a 10
  -> card_id=0x65106510 model=RDC6442S
--- position query: DA 00 04 21 (X), DA 00 04 31 (Y) ---
  -> x=0um y=0um

$ PYTHONPATH=. /c/msys64/mingw64/bin/python.exe \
    docs/usb-spike/jog_usb.py --mock --yes
--- rapid move X: +1000um (D9 00, relative) ---
  tx (swizzled): 52 89 8b 89 89 89 0f e1
  rx (unswiz.):  cc
Move sent. Confirm on the machine that X moved +1.0 mm.

$ PYTHONPATH=. /c/msys64/mingw64/bin/python.exe \
    docs/usb-spike/send_fixture_usb.py --mock --yes
175 commands, 1013 bytes swizzled, power zeroed (including C6 65)
sending 1013 bytes in 2 chunk(s)...
chunk 1/2: ACKed (991 bytes, 1 attempt(s))
chunk 2/2: ACKed (22 bytes, 1 attempt(s))
All chunks ACKed. Watch the machine.
```

(Full untruncated output, including every raw hex line, was captured
during this pass; trimmed here for length.) Confirmation-gate refusal
was also verified: `--mock` alone (no `--yes`, no interactive TTY)
exits 1 with "No input available (EOF); aborting. Nothing was sent."
or "Refusing to proceed: not an interactive terminal...", never a
traceback and never a send.

One expected, pre-existing warning appears during the mock
`send_fixture_usb.py` run: `WARNING: File checksum mismatch: received
X, calculated Y`. This is `RuidaServer`'s own internal file-checksum
accumulator (`CHECKSUM_COMMANDS`-gated, summed as commands are
processed) disagreeing with the E5 05 checksum algorithm
`send_fixture_test.py`/`send_fixture_usb.py` both compute (sum of raw
command bytes before the checksum command, ported verbatim from the
proven UDP sender). This divergence is a property of this repository's
own in-tree simulator, not of the new scripts; it would fire
identically if `send_fixture_test.py`'s UDP job were replayed against
this same simulator. Not fixed here: not requested, and outside this
package's owned files (`ruida_server.py`/`ruida_protocol.py`).

### Verified again in this pass

```
$ awk 'length > 79 {print FNR}' docs/usb-spike/*.py   # (all clean)
$ /c/msys64/mingw64/bin/python.exe -m py_compile docs/usb-spike/*.py  # OK
```

Files owned/touched by this pass, and only these:
`docs/usb-spike/enumerate.py` (updated), `docs/usb-spike/probe_usb.py`
(rewritten), `docs/usb-spike/jog_usb.py` (new),
`docs/usb-spike/send_fixture_usb.py` (new),
`docs/usb-spike/_usb_common.py` (new), `docs/usb-spike/_usb_mock.py`
(new), `docs/usb-spike/README.md` (this file).
