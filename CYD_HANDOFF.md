# CYD Inverter Controller — Handoff for a New Claude Session

Exported 2026-11-01 from the Raspberry Pi session. Ships with `inverter-cyd.yaml`, the CYD ESPHome draft.

**How to use this file:**
1. Put this file and `inverter-cyd.yaml` in one folder on the WSL machine.
2. Start Claude Code in that folder.
3. Say: *"Read CYD_HANDOFF.md first, then continue the CYD project."*

---

## 0. Rules (from the owner; not optional)

This inverter runs a **house**. Follow these in every session:

1. **Back up before changing anything.** Make a timestamped copy before every edit.
2. **Validate only.** Run `esphome config inverter-cyd.yaml`.
   - **Never compile, flash or OTA without an explicit "yes" from the owner.**
   - A compile-only test (it builds a file and touches no device) also needs a yes.
3. **Show the plan before big changes.**
4. **Reliable or nothing.** "If you are making things dirty to get something running, drop it."
5. **CYD and Home Assistant are two separate projects. Don't mix them.**
   - The CYD must not depend on HA data, such as HA's solar forecast.
   - HA work is not shaped around the CYD.
   - The only shared fact is physical: the inverter has **one RS232 port**, so only one controller can be wired and active at a time.
6. Don't touch the live inverter ESP (`inverter-esphome.yaml`, IP .3). The CYD is a separate board.
7. Phone alerts go only to the owner's phone (Rami, Samsung S26). That is an HA feature, not part of the CYD.
8. `secrets.yaml` (`wifi_ssid`, `wifi_password`) is **not** included. Create it locally and never share it.

---

## 1. Hardware

| Item | Value |
|---|---|
| Inverter | Axpert VMIII-4000, 24 V, PI30 protocol, RS232 at 2400 8N1 |
| Battery | 4.5 kWh, 24 V; treat 5 % SOC as empty |
| Load profile | 300–400 W normally (3 h median ≈ 190 W, p90 ≈ 1.5 kW, max ≈ 5.3 kW). Heavy loads up to 2 kW for about an hour (dishwasher, heater). |
| PV | Forecast.Solar plane values aren't known yet. The YAML placeholders are 30°, 0° (south) and 3 kWp. |
| Location | About 36° N 37° E. Timezone **Asia/Damascus** (UTC+3 all year). Exact coordinates are in the YAML substitutions. |
| Network | 192.168.10.0/24. Gateway .1. Live inverter ESP is .3. CYD draft is .4 and takes over .3 and the name `inverter_esphome` at cut-over. |

### CYD board: ESP32-2432S028R (confirmed by the owner)
2.8" ILI9341 320×240 with XPT2046 resistive touch, ESP32-WROOM. **No PSRAM** (520 KB RAM). 4 MB flash, which is about 1.8 MB per OTA slot.

| Function | GPIO | Notes |
|---|---|---|
| TFT SPI | CLK 14, MOSI 13, MISO 12, CS 15, DC 2 | Validator warns that 12, 15 and 2 are strapping pins. That is the board's own wiring and is expected. |
| Backlight | 21 | `ledc` PWM |
| Touch SPI | CLK 25, MOSI 32, MISO 39, CS 33, IRQ 36 | Calibration values are placeholders: **calibrate per board** |
| RGB LED | R 4, G 16, B 17 | Active low |
| Speaker | 26, on connector **P4 "SPEAK"** | Goes through the on-board amplifier. See below. |
| Light sensor (LDR) | 34 (ADC1, input only) | Added 2026-11-01, measure only |
| Inverter UART | **CN1**: TX 22, RX 27 | Through a MAX3232 module to the inverter's RS232 port |
| Avoid | P3 (35/22/21), BOOT (0), SD card (5/18/19/23) | 22 is our TX and 21 is the backlight |

**Check the board revision.** If the board has **2 USB ports**, it is the newer revision and the display needs `invert_colors: true` (possibly the ST7789 model).

**Speaker wiring:** P4 is the *amplifier output*, so connect an **8 Ω speaker (0.5–2 W)** or a bare passive buzzer element there. A 3-pin "PWM buzzer module" (VCC/GND/IO) does **not** belong on P4, and the CYD exposes no free output GPIO for one. Use a small speaker.

**RS232 wiring:** inverter RJ45/DB9 → MAX3232 (3.3 V side) → CN1. Cross TX and RX. Power the MAX3232 from CN1 3.3 V. Common GND.

---

## 2. Status of each piece (as of 2026-11-01)

| Piece | Status |
|---|---|
| `inverter-cyd.yaml` (the attached file) | **Draft v1.** `esphome config` says it's valid. **Never compiled, never flashed.** About 2300 lines. |
| Live inverter ESP | Unchanged and running. One pending fix (`on_raw_value` for the data watchdog) is validated but not flashed, waiting for the owner. |
| HA automations ("v4") | Installed. Go live at the owner's next HA restart. They are the **reference logic** for the CYD port (section 4). |
| Pi buzzer service | Running, HA side only. Not part of the CYD. |

### What draft v1 already has
- Full pipsolar sensors, selects and outputs, copied from the live ESP.
- `on_raw_value` data watchdog (`last_inverter_data`) and an "Inverter Data Age" sensor.
- **One controller lambda** (every 2 s) using a reasons bitmask: `LOW=1`, `HIGH=2`, `NIGHT=4`. Any reason → SUB (grid allowed), none → SBU.
  - It writes only when the wanted state changes (edge-triggered).
  - It does nothing in the first 30 s after boot, or when inverter data is older than 30 s, or when Auto is off.
- `held(since, cond, ms)` debounce timers.
- A low-sun check at sun elevation +10° and at solar noon. It uses an **HTTPS Forecast.Solar fetch, which is to be removed** (see gaps).
- Float-voltage rule: when the inverter enters float, set the configured float voltage (27.0 V).
- Buzzer through `rtttl` on GPIO26:
  - The `play_tune(tune, prio, critical)` script handles priority and quiet hours (default 01–09, with an on/off switch). Critical tunes ignore quiet hours.
  - Events: grid lost or back (`bs_grid` > 150 V, 30 s debounce, muted for 90 s after boot), switch to grid (low or other reason), and a no-grid low-SOC alarm (< 30 %, repeating every 10 min below 20 %).
- 24 `number` entities and 10 `switch` entities, all `entity_category: config` and `restore_value`.
  - They are editable on the screen and from HA through the ESPHome API.
  - LVGL widgets are synced in `on_value`, guarded by `boot_ms != 0`, plus the `ui_sync_all` script at boot.
- UI with 2 pages: a main page (SOC arc, power flow, mode and reasons, Battery/Grid/Auto/Setup buttons, alert banner) and a settings tabview (Batt, Load, Night, Sun, Rules).
- Status LED: red blinking = no inverter data, blue = no WiFi, amber = on grid for a reason, green = OK.
- Backlight dims after 90 s idle and turns off after 10 min. Touch wakes it.
- `api.reboot_timeout: 0s` and `wifi.reboot_timeout: 0s`, so it never reboots because HA or WiFi is missing.

### Fixed in this review (2026-11-01, validated)
- 24 label format strings ended in a bare `%`. That is undefined behaviour in `printf`. Changed to `%%`.
- `Low SOC Delay` default changed from 10 s to **60 s** (maximum 300 s). History shows a 100 → 0 % SOC glitch lasting about 30 s on 2026-10-25. With 10 s, that glitch would have switched to grid and fired the alarm.
- Added the LDR sensor `Ambient Light (raw)` on GPIO34 (diagnostic, 5 s, median of 5).
- Added the confirmed board and pin map to the header comment.

### Gaps: draft v1 vs the agreed design (what the next session builds)
Draft v1 ports the **original 8 HA automations**. The HA logic has since been rewritten (v4, section 4). Gaps:

1. **No reserve planner.** v1 uses fixed thresholds of 16/25 % plus a low-sun override of 25/40 %. v4 uses sunny 18/25 % and cloudy 25/30 %, chosen from the coming day's forecast and clamped.
2. **No charger manager.** v4:
   - Charger source is "Solar only" by default.
   - It grid-charges to 40 % on cloudy days, or to 25 % in an emergency below 15 %.
   - Current is 20 A below 20 % SOC, otherwise 10 A.
   - v1 only bumps the charge current on a low-sun day and **never sets it back**.
3. **No overnight rule.** v4 switches to grid when the predicted SOC at "sun useful" would drop below max(10 %, reserve).
4. **No 3-minute minimum on SUB** before returning to SBU. v1 can flap.
5. **No verify and retry** after writing the output priority. v1 writes once and forgets it.
6. **Low-sun bug in v1:** `low_sun_check` sets the LOW bit, but if "Rule Low Battery" is off, the controller clears that bit 2 s later. The rewrite makes it obsolete.
7. **HTTPS Forecast.Solar fetch.** It needs about 40 KB of contiguous heap on a board with no PSRAM, which risks crashes. **Remove it.** Use the persistence forecast instead (section 5).
8. **ntfy push over HTTPS.** Same memory risk. Remove it (or use plain-HTTP ntfy later if flash allows). The `notify` script is also `mode: queued` with a 5-minute delay, so banners stack up.
9. **No `warn_morning` buzzer tune.** It needs the overnight prediction.
10. **UI is 2 pages with about 24 sliders.** The agreed design is **6 pages with about 11 settings on screen** (section 6).
11. **No observe-only mode** for the side-by-side test before cut-over.
12. **No 3-hour median load on the ESP.** It's needed for the overnight prediction and runtime.

---

## 3. Design principles (they held up against real data)

- **One owner per setting.** Exactly one piece of code writes the output priority, one writes the charger source and current, and one writes the reserve. Rules never write to the inverter directly; they only set reasons.
- **Reasons and latches instead of edge triggers.** Each reason has an ON condition (debounced) and an OFF condition (debounced) and stays latched between them.
  - Wanted mode = SUB if any reason is active, otherwise SBU.
  - Go to SUB immediately. Go back to SBU only after at least 3 minutes on SUB.
- **Stale data means do nothing.** Without fresh inverter data, nothing is written, and no alarms fire that are based on old values.
- **Unknown time means pause the time-based rules** (night, overnight, planner). The battery and load rules keep running. The ESP has no RTC, so after a power cut with no internet the time is unknown.
- **The unknown case falls on the safe side.** Unknown forecast counts as cloudy, which means the higher reserve.
- **Debounce SOC for at least 60 s** because of the 100 → 0 % glitch.
- **Manual override is the "Auto control" switch.** The Battery/Grid buttons turn Auto off; the Auto button turns it back on and re-applies the wanted mode.

---

## 4. Reference logic (HA v4, which the CYD reimplements)

Defaults are in brackets. All of these are HA helpers today; on the CYD they become `number`/`switch` entities.

### A. Reserve planner (sets `switch_soc`, `return_soc`, `low_sun_day`)
- **When it runs:** sunset, sunrise + 1 h, boot, Auto turned on, a reserve setting changed.
- **Which forecast:** if the hour is ≥ 12, use **tomorrow's** forecast; otherwise use today's.
- **Cloudy** = forecast < cloudy threshold [5 kWh]. An unknown forecast counts as cloudy.
- **Reserve values:**
  - Cloudy: switch [25], return [30].
  - Sunny: switch [18], return [25].
  - Clamp: `sw = clamp(sw, 16, 37)`, `ret = clamp(max(ret, sw + 3, 25), ·, 40)`.
- `low_sun_day = cloudy`.

### B. Charger manager (the only writer of charger source and charge current)
- **When it runs:** every 5 min, plus changes in low_sun_day, grid, data_ok, Auto or SOC.
- **Charge target:** `target = cloudy ? max(charge_target [40], emerg_target [25]) : emerg_target`.
- **Start:** grid present AND ((cloudy AND SOC < charge_target − 3) OR SOC < emerg_soc [15]).
- **Stop:** no grid OR SOC ≥ target.
- `charging = start OR (charging AND NOT stop)`. This is a latch; keep it in a restored global.
- **Charger source:** "Solar and utility" while charging, otherwise **"Solar only"**.
- **Current while charging:** SOC < fast_below [20] → fast [20 A], otherwise normal [10 A]. Round to the nearest inverter step (2/10/20/30/40/50/60).

### C. Output controller (the only writer of output priority)
Runs every minute and on every relevant change. Needs Auto on AND data OK.

| Reason | ON | OFF (latch release) |
|---|---|---|
| LOW | SOC < switch_soc for 60 s | SOC > return_soc for 60 s |
| HIGH | load > 2500 W for 6 s AND SOC < 80 AND PV < 1200 W | load < 2000 W for 45 s |
| NIGHT | night AND load > 1600 W for 30 s AND SOC < 70 | (load < 600 W for 60 s AND SOC > return_soc) OR (SOC > 60 AND load < 1000 W for 10 s) |
| OVERNIGHT | rule on AND night AND predicted SOC at sun-useful < max(floor [10], switch_soc) for 5 min | prediction > that target + margin [5] for 5 min, OR sun useful |
| CHARGE | charger manager is charging AND grid present AND SOC < max(charge_target, emerg_target) | otherwise |

- `want = any reason ? SUB : SBU`.
- **Write rule:**
  - Write only if `cur != want` AND (want is SUB OR at least min_sub [3] minutes on SUB).
  - After writing, check that the read-back matches within 30 s. Retry once. If it still fails, raise an alarm.
- **Sun useful:** sun above the horizon AND (PV ≥ base_load OR time since sunrise > delay).
  - The delay is [1.5 h] on a sunny day and [3 h] on a low-sun day.
  - Night means sun below the horizon (HA). On the ESP, use elevation < −0.833°.

### D. Overnight prediction
```
base_load = max(median_load_3h, base_load_floor [300 W])
delay     = low_sun_day ? 3 h : 1.5 h
hrs       = night ? (next_sunrise - now) + delay
                  : max(delay - (now - sunrise), 0)
soc_at_sun = soc - base_load * hrs / capacity_Wh [4500] * 100
```
Using the 3-hour median means a heater running for an hour doesn't trigger the rule.

A simulation of one real night gave: grid at about 17:00, back to battery at about 04:00, and about 30 % SOC when the sun became useful.

### E. Runtime (for display and alarms)
```
usable_Wh   = max(0, capacity * (soc - empty_soc [5]) / 100)
runtime_base = usable_Wh / max(median_load_3h, 300)    # hours
runtime_now  = usable_Wh / max(mean_load_5min, 50)
```
**Alarm with no grid:** runtime_base < 2 h for 2 min, or runtime_now < 30 min for 5 min. At most once every 30 min.

### F. Data OK
- **HA side:** the ESP is connected AND SOC and load have values AND (any of 8 live sensors changed within 300 s OR Data Age < 120 s), with a 20 s delay-off.
- **On the CYD:** use `millis() - last_inverter_data < 30 s` (from `on_raw_value`) and that SOC and load are not NaN.

### G. Buzzer events (same tunes as the Pi, RTTTL)
| Event | Tune | Priority | Plays during quiet hours |
|---|---|---|---|
| Grid lost (V < 150 for 30 s) | `gridlost:d=8,o=6,b=140:e,c,4a5` | 2 | no |
| Grid back | `gridback:d=8,o=5,b=150:a,c6,4e6` | 1 | no |
| Switched to grid, LOW reason | `togridlow:d=8,o=6,b=125:e,4c,p,e,4c` | 2 | no |
| Switched to grid, other reason | `togrid:d=8,o=6,b=125:e,4c` | 1 | no |
| No grid AND SOC < 30 (repeats every 10 min below 20) | `alarm:d=16,o=6,b=180:a,e,a,e,a,e,8p,a,e,a,e,a,e,8p,a,e,a,e,a,e` | 3 | **yes** |
| No grid AND soc_at_sun < floor for 5 min (repeats every 30 min) | `morning:d=8,o=5,b=110:c6,p,g,p,e,p,4c,4p,c6,p,g,p,e,p,4c` | 3 | **yes** |
| Test button | `test:d=16,o=6,b=160:c,e,g,c7,8p,g,4c7` | 1 | — |

- If grid is lost while SOC is already below 30, play the alarm instead of "grid lost".
- A higher priority interrupts a lower one. Equal or lower priority is dropped while a tune is playing.
- Quiet hours have an on/off switch [on], from [01] until [09]. The window can wrap past midnight.

### H. Float voltage
When the inverter enters float mode, set float voltage to [27.0 V] if it differs.

---

## 5. Changes required by standalone operation

- **Forecast without the internet or HA (persistence):**
  - Store yesterday's and today's measured solar kWh from `total_daily_energy` in `restore_value` globals.
  - "Forecast for the coming day" = today's kWh so far if it's past about 15:00, otherwise yesterday's kWh.
  - If nothing is stored yet (first boot), it is **unknown, which counts as cloudy**.
  - Optional later: a plain-HTTP source. No HTTPS.
- **3-hour median load on the ESP:**
  - Keep a ring buffer of 180 one-minute load means (720 bytes).
  - Compute the median every minute with `nth_element` on a copy (small, about 1 ms).
  - Until 30 samples exist, use base_load_floor.
- **5-minute mean load:** `sliding_window_moving_average` on a template sensor, or 5 slots in the same ring buffer.
- **Sunrise and sunset:** the `sun` component. "Sunrise time" = when elevation crosses −0.833° upward; store it in a global for the "since sunrise" calculations. `next_sunrise` comes from `id(sun_c).sunrise(...)`.
- **Time unknown** (no SNTP after a power cut): pause the planner, night, overnight and sun-useful rules. LOW, HIGH, CHARGE (SOC-based only) and the alarms keep running.
- **Observe-only switch** (new, default **on** for the first install): the controller computes everything and shows what it *would* do on screen and in a text sensor, but never writes to the inverter. The owner compares it with HA for a day before cut-over.

---

## 6. Agreed UI (6 pages, 320×240 landscape)

The bottom bar has **Home · Power · Control · Setup**. **Advanced** opens with a 2-second hold on Setup. An **alarm overlay** can cover any page.

1. **Home:** SOC arc, mode (SBU or SUB plus the active reasons), grid on/off, runtime, clock, predicted SOC at sunrise.
2. **Power:** live flow (PV, load, battery ±, grid), today's kWh (solar, load, grid), heat sink temperature.
3. **Control:** Auto on/off, manual Battery/Grid (these turn Auto off), charger state, observe-only indicator.
4. **Setup (5 settings):** cloudy threshold kWh, sunny reserve, cloudy reserve, grid-charge target, overnight rule on/off.
5. **Advanced (about 6):** high-load and night-load thresholds, overnight floor, no-grid alarm level, battery capacity, screen timeout, restore defaults, buzzer and quiet hours.
6. **Alarm overlay:** a red banner with the reason, a "Silence" button, and the RGB LED.

All other settings (delays, margins, charge currents and so on) stay as ESPHome `number` entities with defaults. They are editable from HA when it's connected (native API; MQTT is optional), but have no slider on screen.

**Memory and flash:**
- LVGL with 6 pages is about 40–60 KB of RAM. Use `buffer_size: 25%` and at most 3 font sizes.
- The estimated firmware is about 1.5–1.7 MB against about 1.8 MB per slot.
- **This hasn't been checked. A compile-only test needs the owner's OK.**
- If it's too big, the first things to drop are `http_request`, extra fonts and the `web_server` (not included).

**Backlight:** the LDR is measured now. Auto-dimming comes only after real readings are logged. The CYD's LDR has a small range, and the backlight itself affects it.

---

## 7. Cut-over plan (later, only with the owner's OK)

1. Build and compile-test with the owner's OK. Check flash and RAM.
2. Flash the CYD over USB on the bench, with **observe-only on** and **no UART connected**. Calibrate touch and check the screen, buzzer and LDR.
3. Wire it to the inverter **in place of** the old ESP (one RS232 port). Keep observe-only on and compare its decisions with HA for at least a day.
4. Cut-over:
   - Rename it to `inverter_esphome` and give it IP .3 so the HA entities continue.
   - Turn off HA's "Inverter Auto Control" so HA's controllers stand down.
   - Turn off observe-only on the CYD.
5. Rollback: put the old ESP back on the RS232 cable. Its config is unchanged.

---

## 8. Open questions for the owner

- [ ] 1 or 2 USB ports on the CYD? (This decides the display setting.)
- [ ] Where will the CYD be mounted, and how long is the RS232 run (fine up to about 10–15 m)?
- [ ] PV array: tilt, azimuth and kWp. Only needed if a forecast source is ever added.
- [ ] Speaker: 8 Ω speaker on P4? (Recommended.)
- [ ] OK for a compile-only test to measure flash and RAM?

---

## 9. Suggested first steps for the new session

1. Read this file and `inverter-cyd.yaml`. Run `esphome config inverter-cyd.yaml` with a local `secrets.yaml`.
2. Present a plan to rewrite the controller per sections 4–5, in a way that stays understandable:
   - one `controller` lambda with reasons and latches
   - a `planner` script
   - a `charger` block
   - the ring-buffer median
   - observe-only
   **Wait for approval.**
3. Rebuild the UI per section 6 and remove the HTTPS fetch and ntfy.
4. Validate only. Ask before compiling.
