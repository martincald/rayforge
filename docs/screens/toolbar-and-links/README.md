# Toolbar, Laser tab, Settings and About

Captured 2026-10-06 from the app at 1440x900, with no machine
connected, so every machine control is greyed out. The run was
isolated: second guard port, driver connect stubbed, network and
serial ports denied.

- `toolbar-{light,dark}.png`: the machine group now reads Home, Go
  Scale (frame icon), Cut Scale (the jog panel's laser icon), Send,
  Pause, Stop, Clear Alarm. The laser-pulse button is gone. Auto
  Layout's progress row with its Cancel button sits at the toolbar's
  end and is hidden unless a layout is running, so it is not in the
  image.
- `dock-laser-{light,dark}.png`: in the Laser tab, Power and Duration
  are insensitive ("Not supported on this controller"), and the new
  Focus Z row runs D8 2E.
- `settings-{light,dark}.png`: the Licenses page is gone, leaving five
  pages.
- `about-{light,dark}.png`: the plain-text line "Based on Rayforge by
  Samuel Abels, used under the MIT License." The License row is plain
  text and the Supporters row is gone; nothing opens a browser.

The dark toolbar and Laser tab captures are transparent where the
window draws its background, so they were composited onto a dark
fill.
