# macOS USB ladder

Four scripts that take a Mac from "is the laser even visible" to
"it ran the reference job", one rung at a time, over the laser's USB
cable. They talk through the app's own `RuidaUsbTransport` (vcp
backend) and `RuidaClient`, so a rung that works here works in
SwiftCut.

No driver install and no admin rights: macOS's built-in FTDI driver
exposes the controller as `/dev/cu.usbserial-<serial>`, and pyserial
opens it as the logged-in user. Nothing here uses the network.

Every rung prints each byte it writes and reads, twice: `wire` (as it
crossed the port: swizzled, no checksum) and `plain` (decoded).

## Run order

From the repository root, with the laser's USB cable plugged in and
the controller on. Stop at the first rung that fails and report its
full output.

| # | script | moves? | what it does |
|---|---|---|---|
| 1 | `enumerate.py` | no | lists `/dev/cu.*` with VID:PID, description, serial; shows which FTDI port the app would open. Sends nothing. |
| 2 | `probe.py` | no | card ID `DA 00 05 7E`, X position `DA 00 04 21`, keepalive `CE` (expects ACK `CC`) |
| 3 | `jog.py` | **yes** | one rapid `D9 00`, X +1 mm; reads X before and after |
| 4 | `fixture.py` | **yes** | the RDWorks reference job, every power command zeroed (incl. `C6 65`) |

```sh
PYTHONPATH=. pixi run python docs/usb-spike/mac/enumerate.py
PYTHONPATH=. pixi run python docs/usb-spike/mac/probe.py
PYTHONPATH=. pixi run python docs/usb-spike/mac/jog.py        # types MOVE to confirm
PYTHONPATH=. pixi run python docs/usb-spike/mac/fixture.py    # types SEND to confirm
```

Keep the E-stop within reach for rungs 3 and 4. Jog the head clear of
the +X end before rung 3.

**What to report from rung 1:** the FTDI line's `description` and
`serial`. The serial is what pins the laser (`usb_serial` in the
profile, or Device settings > USB Device) if another FTDI device is
ever plugged in. If more than one FTDI device is attached, pass
`--usb-serial <serial>` to rungs 2-4.

If rung 1 lists no FTDI port with the laser on, report the laser's
Vendor ID and Product ID from `system_profiler SPUSBDataType`.

## Dry run

`--mock` runs any rung against a simulated FTDI port with the in-repo
Ruida simulator behind it (`_mock_port.py`); nothing is opened.
`tests/machine/driver/ruida/test_usb_mac_ladder.py` runs all four this
way.

```sh
PYTHONPATH=. pixi run python docs/usb-spike/mac/probe.py --mock
PYTHONPATH=. pixi run python docs/usb-spike/mac/fixture.py --mock --yes
```
