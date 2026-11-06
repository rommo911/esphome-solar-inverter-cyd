# UI plan (after the HIL simulation)

From the owner's bench notes (2026-11-06). Do 1 and 6 first, then 3 / 4 / 5 / 2 / 7 together
(main screen redesign, with preview renders to approve before compiling), then 8.

1. **Two-line banner messages.** Fixed two-line height, word wrap, font measured for 2 x ~30
   characters. Shorter messages so a number never splits from its unit ("No grid - about 1.9 h of
   battery left"). `cyd_ui.py check` tests every message the controller can send against the banner.
2. **Icons instead of SBU / SUB / CHG / LOW text.**
   - One "power path" icon: battery first (sun + battery -> house), on grid (pylon -> house),
     grid charging (pylon -> battery +).
   - Reason badges only while active: battery-low (LOW), heavy load (HIGH), moon (NIGHT),
     sunrise + battery (Overnight), plug + (CHG).
   - Tap the icon: one-line explanation. The mode text goes away.
3. **"sun -160 %" replaced.** Sunrise icon with "Battery lasts until ~04:30" (red) when it would run
   out before the sun is useful, otherwise "~35 % at sunrise" (green). Never a negative %.
4. **Battery in the middle of the dials.** SOC large, up/down arrow for charge/discharge, battery
   power (+640 W / -380 W) below. The right-hand battery box goes, its space for grid power and today's energy.
5. **Scales and zero values.**
   - New setting "Inverter Max Power" (default 4000 W) = full scale of the load dial. PV dial keeps the array size.
   - Zero values dimmed with "-", not hidden (no layout jumps).
   - Grid icon always visible: green present, red lost (blinks the first minute), grey unknown.
     Grid power shown only when grid is used.
6. **"OVN" renamed** "Overnight" / sunrise badge everywhere (overnight rule: grid at night if the
   battery would not last until the sun is useful).
7. **Icons.**
   - Material Design Icons via ESPHome `image: mdi:<name>` (a few KB each, fine on a slow line).
   - Composite power-path icons built from 2-3 small icons and an arrow.
   - Recoloured in LVGL with the existing green / amber / red / grey.
8. **Setting explanations.**
   - "i" on every Setup / Advanced row: a popup with 1-3 lines of help text and the default value.
   - Help text: a new column in `tools/cyd_settings.py`, so the screen and the README share it.
