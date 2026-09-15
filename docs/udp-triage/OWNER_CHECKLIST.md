# Ruida UDP connection checklist (ilab-614)

Run these in order. Each step says what to look for before moving on.

## 1. Fix the port drift on the live profile

The live machine profile's ports had drifted (`port: 50201`,
`jog_port: 50200`). Correct values: `port: 50200`, `jog_port: 50207`.

**Preferred: in the app.**
1. Open SwiftCut.
2. Machine Settings > **Device** > **Diagnostics** section.
3. If ports are wrong, a row titled *"Ports do not match the
   ilab-614 defaults"* appears, with a **"Reset ports to defaults"**
   button on it. Click it.
4. The notice disappears and a toast confirms *"Ports reset to
   defaults."*

**Alternative: edit the file directly.**
1. Close SwiftCut completely first (it must not have the file open).
2. Edit
   `C:\Users\<you>\AppData\Local\swiftcut\swiftcut\machines\<machine-id>.yaml`
   and set, under `machine.driver_args`:
   ```yaml
   port: 50200
   jog_port: 50207
   ```
3. Save and relaunch SwiftCut.

## 2. Check the newest session log

Open the newest file in
`C:\Users\<you>\AppData\Local\swiftcut\swiftcut\Logs\session-*.log`
(sorted by name/timestamp; there is **no** `swiftcut/logs/swiftcut.log`
-- that path does not exist). Search for these exact strings:

- `Loaded machine '<name>' from` -- confirms which profile file was
  actually loaded.
- `Driver resolved: RuidaDriver for profile` -- confirms the Ruida
  driver was built for that profile.
- `has non-default Ruida ports` -- this line must be **absent** after
  step 1. If it is still present, step 1 did not take (wrong file
  edited, or SwiftCut re-loaded before the edit was saved).
- `RX:` -- proof a reply actually came back from the controller. Every
  line in the log has this shape:
  ```
  <timestamp> - <pid> - <thread> - swiftcut.machine.driver.ruida.ruida_transport - DEBUG [RAW_IO] - RX: b'...'
  ```
  If you only ever see `TX:` lines and never an `RX:` line after
  connecting, the controller's replies are not reaching SwiftCut --
  go to steps 3 and 4.

## 3. Check for response-port contention (RDWorks)

SwiftCut listens for the controller's replies on local UDP port
40200. RDWorks binds the same local port, and only one program can
hold it at a time. **Close RDWorks before starting SwiftCut.**

To check whether something already holds it, open Command Prompt:
```
netstat -ano -p udp | findstr 40200
```
This prints the PID of whatever owns the port (last column). Identify
it:
```
tasklist /FI "PID eq <pid>"
```
If that PID is `RDWorksV8.exe` (or another Ruida tool), close it and
try SwiftCut again.

## 4. Windows Firewall

Windows Firewall silently dropping the reply datagrams on port 40200
looks identical to the port-contention problem above -- a clean
timeout, no error. SwiftCut shows a note in the Device page's error
state when this may be happening: *"Windows Firewall may be blocking
SwiftCut.exe - allow it for private networks"*.

SwiftCut adds its own inbound rule automatically on startup, but only
if it is already running elevated; a normal launch cannot prompt for
that. To add the rule yourself:

1. Open Command Prompt **as Administrator** (right-click > "Run as
   administrator").
2. Run:
   ```
   netsh advfirewall firewall add rule name="SwiftCut UDP 40200" dir=in action=allow protocol=UDP localport=40200 profile=private
   ```
3. Confirm your network is set to **Private**, not Public: Settings >
   Network & Internet > (your network) > Network profile type. A
   Public profile is more restrictive and can block the rule above
   from taking effect.

## 5. Basic reachability

1. Confirm the PC's network adapter has an address on the laser's
   subnet (`192.168.1.x`) -- Settings > Network & Internet, or
   `ipconfig` in Command Prompt.
2. Ping the controller:
   ```
   ping 192.168.1.100
   ```
   No reply means a cabling/switch/IP problem upstream of anything
   SwiftCut can fix -- check the controller is powered on and wired to
   the same network.
