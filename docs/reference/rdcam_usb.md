# Ruida USB (RDCAM/RDWorks) transport reference

**Provenance.** This file transcribes the USB brief supplied by the
project owner in the Package U operating protocol, which the owner
derived from a decompile of the RDCAM/RDWorks client. No decompiler
output was read while writing this file, and no external source was
consulted. Where this document states a value, the value came from the
owner's brief; where it states a *measurement*, the measurement was
taken on the development machine and is labelled as such. Treat the
owner's brief as ground truth and this file as its checked-in form.

## 1. Framing

USB shares the UDP framing almost entirely:

- swizzle with magic `0x88`
- 7-bit encoding, same opcodes
- chunks of **at most 1000 bytes**, split on **command boundaries**
- ACK `0xCC` (also accept `0xC6`); NAK `0xCD` / `0xCF`
- **5 s ACK budget**, with retries
- keepalive/connection detection: ENQ `0xCE` -> ACK `0xCC`

The **only** wire difference from UDP:

> **No 2-byte checksum prefix.**

USB is a **single stream** — there is no separate jog port.

The existing ACK-paced send loop is to be **reused**, not reimplemented.

## 2. Backends

Both sit behind one `RuidaUsbTransport`.

### 2.1 d2xx (Windows default)

The open sequence must match `FUN_10001C80` exactly, in this order:

1. `open(index)`
2. `resetDevice()` — **abort on failure**
3. sleep `0.1`
4. `setDataCharacteristics(8, 0, 0)`
5. `setUSBParameters(1024, 1204)`
6. `setDeadmanTimeout(0xFFFFFFFF)`
7. `setTimeouts(100, 1000)`
8. `setBaudRate(19200)`
9. `purge(RX | TX)`
10. `clrRts()`
11. `clrDtr()`
12. sleep `0.1`
13. `setResetPipeRetryCount(100)` — if the binding exposes it

> `setUSBParameters(1024, 1204)` is asymmetric. The owner's brief gives
> it as written, and the protocol's standing rule is to match the
> decompile literally, so it is reproduced verbatim rather than
> "corrected" to 1024.

**Read loop.** Poll `read(n)` against the 100 ms driver timeout until
data arrives or the 5 s budget expires. Do not busy-spin without
yielding: the blocking I/O runs in an executor thread so the asyncio
loop stays responsive.

### 2.2 vcp (macOS/Linux default, Windows optional)

pyserial over `/dev/cu.usbserial-*`, `/dev/ttyUSB*`, or `COMn`.
8N1, baud 19200 nominal (an FT245 FIFO ignores it), timeout `0.1`,
same read loop.

### 2.3 Device selection

Better than RDWorks' `FT_Open(0)`:

- enumerate via `ftd2xx.listDevices` / `list_ports` filtered on VID `0403`
- **log every device's description and serial**
- prefer a profile-pinned serial number (`usb_serial`) when set
- otherwise fall back to index 0 **with a WARNING** that lists what else
  was found

The first hardware run must print the Ruida device's description and
serial so the owner can pin it.

## 3. Measured environment facts (development machine)

These were measured on the Windows development box and are **not** from
the owner's brief:

- The FTDI D2XX DLL is present, but only staged in the Windows driver
  store, not on the DLL search path:
  `C:\Windows\System32\DriverStore\FileRepository\ftdibus.inf_amd64_6d7e924c4fdd3111\amd64\ftd2xx64.dll`
  There is no `ftd2xx*.dll` in `System32` or `SysWOW64`, and no
  `ftdibus.sys` / `FTDIBUS` service is active — consistent with the
  driver package being staged and not yet bound to a device.
- `ctypes.WinDLL` loads that DLL directly and exports every entry point
  this transport needs, verified today: `FT_Open`, `FT_ListDevices`,
  `FT_SetResetPipeRetryCount`.
- The PyPI `ftd2xx` package **cannot be installed** in this repo's test
  environment: it requires `pywin32`, which has no MSYS2/MinGW build,
  and there is no native win-64 CPython on the machine. Its sdist also
  fails to build on Python 3.14 (`build_py_2to3` was removed from
  distutils).
- Consequence: the d2xx backend binds the DLL through `ctypes` rather
  than through the `ftd2xx` package. This is a deviation from the
  protocol's "install ftd2xx" instruction, forced by the environment,
  and it is strictly more capable — every D2XX export is reachable, so
  `setResetPipeRetryCount` is always available.
- `pyserial` 3.5 **is** installed and importable, so the vcp backend
  has a real dependency available.
