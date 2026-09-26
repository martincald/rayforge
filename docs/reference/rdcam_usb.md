# How RDWorks talks to the controller over USB

Recovered from `rdcam.dll` (RDWorks V8.01.66, 2024-12-13). The USB path is a single function, `FUN_10001C80`, plus two call sites for I/O.

## It is FTDI D2XX, not a COM port

`rdcam.dll` imports 14 functions from **`FTD2XX.dll`** — FTDI's proprietary D2XX driver — all by ordinal. Not a virtual COM port, not raw WinUSB, not HID. There is a separate serial path (`CreateFileA("\\\\.\\COM%d")` + `SetCommState`) and a separate UDP path; USB is its own third branch.

Resolved ordinals (confirmed against an `ftd2xx.dll` export dump, and each one independently consistent with its argument count and the values passed):

| ord | function | ord | function |
|---|---|---|---|
| 1 | `FT_Open` | 13 | `FT_ClrRts` |
| 2 | `FT_Close` | 16 | `FT_Purge` |
| 3 | `FT_Read` | 17 | `FT_SetTimeouts` |
| 4 | `FT_Write` | 33 | `FT_SetUSBParameters` |
| 6 | `FT_ResetDevice` | 65 | `FT_SetResetPipeRetryCount` |
| 7 | `FT_SetBaudRate` | 73 | `FT_SetDeadmanTimeout` |
| 8 | `FT_SetDataCharacteristics` | 11 | `FT_ClrDtr` |

Note what is *absent*: no `FT_ListDevices`, no `FT_OpenEx`, no VID/PID or serial-number matching anywhere in the binary.

## The open sequence

`FUN_10001C80` @ `0x10001C80`, read straight off the disassembly with the real stdcall argument order:

```c
FT_Open(0, &handle);                              // device INDEX 0 — hardcoded
if (FT_ResetDevice(handle) != FT_OK) {            // nonzero = give up
    FT_Close(handle);  handle = 0;  return 2;
}
Sleep(100);

FT_SetDataCharacteristics(handle, 8, 0, 0);       // 8 data bits, 1 stop, no parity
FT_SetUSBParameters(handle, 0x400, 0x4B4);        // in-transfer 1024, out-transfer 1204
FT_SetDeadmanTimeout(handle, 0xFFFFFFFF);         // effectively disabled
FT_SetTimeouts(handle, 100, 1000);                // read 100 ms, write 1000 ms
FT_SetBaudRate(handle, 0x4B00);                   // 19200
FT_Purge(handle, 3);                              // FT_PURGE_RX | FT_PURGE_TX
FT_ClrRts(handle);
FT_ClrDtr(handle);
Sleep(100);
FT_SetResetPipeRetryCount(handle, 100);

g_ftHandle = handle;                              // .data 0x100E0824
return 0;
```

Two things worth knowing before you copy it:

- **`FT_Open(0)` takes whatever FTDI device is first on the machine.** No filtering at all. If the user has any other FTDI-based device plugged in — an Arduino clone, a USB-serial cable, a 3D printer — RDWorks may open that one instead. For your own driver, matching on description or serial number is strictly better behaviour, not a deviation worth worrying about.
- **The 19200 baud rate is almost certainly meaningless.** Ruida boards use an FT245-style parallel FIFO, where the "baud rate" has no wire effect — it is a leftover from the D2XX API surface. `FT_SetUSBParameters`' 1024-byte in-transfer and the 100 ms read timeout are the settings that actually matter for throughput and latency.

## Which transport gets used

`RD_Open` → `FUN_10003630` → `FUN_10002400` stores the choice, then `FUN_100024F0` acts on it:

```c
// FUN_10002400 — record the choice
g_useNet  = param_1;        // .data 0x100E0820
g_comPort = param_2;        // .data 0x100E0822
...
if (g_useNet == 0 && comPort < 3)
    g_comPort = 0;          // ← anything under COM3 means "use USB"

// FUN_100024F0 — connect
if (g_useNet == 0) {
    if (g_comPort == 0)  FUN_10001C80(0);        // FTDI USB
    else                 FUN_10001DA0(comPort);  // real serial COM<n>
} else {
    FUN_10001FD0();                              // UDP socket
}
if (ok) Sleep(100);
```

The device dialog's strings line up with this: `USB:Auto`, `USB:COM%d`, `IP:`. "USB: Auto" passes 0 and lands on `FT_Open(0)`.

## Reading and writing

Both live inside the same functions that serve the serial and UDP paths, branching on the same two globals.

**Write** — `FUN_10002660` @ `0x10002775`:

```c
if (g_useNet) {
    // UDP: 2-byte big-endian checksum of the scrambled bytes, then sendto
} else if (g_comPort == 0) {
    FT_Write(g_ftHandle, buf, len, &written);      // USB
} else {
    WriteFile(g_comHandle, buf, len, &written);    // serial
}
```

**Read** — `FUN_100021B0`:

```c
start = clock();
while (clock() - start < 5000) {          // 5 s budget
    if (g_comPort == 0) {
        if (FT_Read(g_ftHandle, buf, len, &got) == FT_OK && got != 0)
            return got;                    // first non-empty read wins
    } else {
        if (ReadFile(g_comHandle, buf, len, &got) && got != 0)
            return got;
    }
}
return 1;                                  // timeout
```

It is a busy poll with no sleep, leaning on `FT_SetTimeouts`' 100 ms read timeout to pace itself.

**The critical difference from UDP:** on USB (and serial) the payload is **scrambled but carries no checksum prefix**. The 2-byte big-endian sum is added only on the socket branch. Everything else is identical — same `0x88` swizzle, same 7-bit encoding, same opcodes, same `0xCC` / `0xCD` acknowledgements, same ≤1000-byte chunking (`FUN_100050C0` splits at 1000) and the same 5-second ACK budget in `FUN_100036E0`.

**Close** — `FUN_10002550` tears down whichever is open:

```c
if (g_ftHandle)  { FT_Close(g_ftHandle);   g_ftHandle = 0; }
if (g_comHandle) { CloseHandle(g_comHandle); g_comHandle = 0; }
if (g_socket)    { setsockopt(...); shutdown(...); closesocket(...); }
```

## Reference implementation

```python
"""USB transport for a Ruida controller, matching rdcam.dll FUN_10001C80."""
import ftd2xx   # or pyftdi / libftdi on Linux

FT_PURGE_RX, FT_PURGE_TX = 1, 2

class RuidaUsb:
    def __init__(self, index=0):
        self.d = ftd2xx.open(index)          # FT_Open(0, &h)
        self.d.resetDevice()                 # FT_ResetDevice — abort on failure
        time.sleep(0.1)
        self.d.setDataCharacteristics(8, 0, 0)          # 8N1
        self.d.setUSBParameters(1024, 1204)             # in / out transfer size
        self.d.setDeadmanTimeout(0xFFFFFFFF)
        self.d.setTimeouts(100, 1000)                   # read ms, write ms
        self.d.setBaudRate(19200)                       # nominal; FIFO ignores it
        self.d.purge(FT_PURGE_RX | FT_PURGE_TX)
        self.d.clrRts()
        self.d.clrDtr()
        time.sleep(0.1)
        # self.d.setResetPipeRetryCount(100)   # if your binding exposes it

    def send(self, payload: bytes):
        """Scrambled payload, NO checksum prefix — that is UDP-only."""
        data = scramble_bytes(payload)
        for i in range(0, len(data), 1000):        # same 1000-byte chunking
            self.d.write(data[i:i + 1000])

    def recv(self, n=1, timeout=5.0):
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            got = self.d.read(n)
            if got:
                return unscramble_bytes(got)
        raise TimeoutError

    def close(self):
        self.d.close()
```

### On Linux

`ftdi_sio` claims FTDI devices as `/dev/ttyUSB*` at plug-in, so you have two options:

- **Use the VCP.** Open `/dev/ttyUSB0` and set 8N1. The baud rate does not matter on an FT245 FIFO, and you get the kernel's buffering. Simplest path, and closest to what RDWorks' own serial branch does anyway.
- **Detach and use libftdi/pyftdi.** `usb.core` + `detach_kernel_driver`, or a udev rule blacklisting the interface. This is the only way to reproduce `FT_SetUSBParameters` and the exact latency behaviour, which matters if you see throughput problems on large raster jobs.

Start with the VCP. Reach for libftdi only if 1000-byte chunks with ACK pacing turn out too slow, since that is where the 1024-byte in-transfer size and the FTDI latency timer start to show.

## Evidence

| what | where |
|---|---|
| USB open sequence | `FUN_10001C80` @ `0x10001C80` |
| FTDI imports (by ordinal) | IAT `0x1002C000`–`0x1002C034` |
| transport recorded | `FUN_10002400` @ `0x10002400` |
| transport dispatched | `FUN_100024F0` @ `0x100024F0` |
| write branch | `FUN_10002660`, `FT_Write` at `0x10002775` |
| read loop | `FUN_100021B0`, `FT_Read` at `0x10002209` |
| teardown | `FUN_10002550` @ `0x10002550` |
| serial branch (for contrast) | `FUN_10001DA0` @ `0x10001DA0` |
| globals | `0x100E0820` net flag · `0x100E0822` COM port · `0x100E0824` FT handle · `0x100E0828` COM handle · `0x100E082C` socket |

---

## Appendix A: measured on the Windows development machine

Everything above is the owner's brief, verbatim. This appendix is
**not** from the brief: it records what was measured on the Windows
development box while building the d2xx backend
(`swiftcut/machine/driver/ruida/ruida_usb_transport.py`).

- The FTDI D2XX DLL is present, but only staged in the Windows driver
  store, not on the DLL search path:
  `C:\Windows\System32\DriverStore\FileRepository\ftdibus.inf_amd64_6d7e924c4fdd3111\amd64\ftd2xx64.dll`
  There is no `ftd2xx*.dll` in `System32` or `SysWOW64`, and no
  `ftdibus.sys` / `FTDIBUS` service is active — consistent with the
  driver package being staged and not yet bound to a device.
- `ctypes.WinDLL` loads that DLL directly and exports every entry point
  the transport needs, including `FT_SetResetPipeRetryCount`.
- The PyPI `ftd2xx` package **cannot be installed** in this repo's test
  environment: it requires `pywin32`, which has no MSYS2/MinGW build,
  and its sdist fails to build on Python 3.14 (`build_py_2to3` was
  removed from distutils).
- Consequence: the d2xx backend binds the DLL through `ctypes` rather
  than through the `ftd2xx` package, so every D2XX export is reachable.
- `pyserial` 3.5 **is** installed and importable, so the vcp backend
  has a real dependency available.
