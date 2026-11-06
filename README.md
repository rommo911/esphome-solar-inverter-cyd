# CYD inverter controller

A standalone smart controller for a hybrid solar inverter: an Axpert VMIII-4000 (24 V battery,
PI30 protocol over RS232) driven by an ESP32-2432S028R "Cheap Yellow Display" (2-USB revision,
ILI9342 2.8" touchscreen). It reads the inverter every few seconds and decides by itself when the
house runs on battery or grid and when the battery charges from the grid. It needs neither Home
Assistant nor the internet; with internet it adds a solar forecast, and Home Assistant can connect
later as a viewer and remote.

| File | What it is |
|---|---|
| `inverter-cyd.yaml` | The ESPHome config for the board: hardware, screen, forecast, entities |
| `components/solar_autopilot/` | The controller logic: a plain C++ core plus its ESPHome component (see [Code structure](#code-structure)) |
| `CYD_HANDOFF.md` | Background, hardware notes and the agreed design (v4 logic) |
| `docs/screens/` | Rendered previews of every screen page |
| `docs/proposal/` | One-page project proposal (English and Arabic) |
| `tools/` | Settings table, screen layout generator, simulator (see [Workflow](#workflow)) |

## Contents
- [Hardware and wiring](#hardware-and-wiring)
- [How it decides](#how-it-decides)
- [Alarms and sounds](#alarms-and-sounds)
- [Screen, icons and LED](#screen-icons-and-led)
- [Settings](#settings)
- [Network and Home Assistant](#network-and-home-assistant)
- [Code structure](#code-structure)
- [Workflow](#workflow)

## Hardware and wiring

| Function | Pins / part | Notes |
|---|---|---|
| Display | SPI 14/13/12, CS 15, DC 2 | ESPHome preset `ESP32-2432S028-9342` (native 320x240 landscape) |
| Touch (XPT2046) | SPI 25/32/39, CS 33, IRQ 36 | Orientation is cycled with the **BOOT** button (8 options, saved) |
| Backlight | GPIO21 | PWM, linear (gamma 1.0) |
| RGB status LED | R 4, G 16, B 17 | Common anode, pins inverted |
| Speaker | P4 "SPEAK" (GPIO26 + on-board amp) | Connect an 8 Ω speaker; tunes are RTTTL |
| Light sensor (LDR) | GPIO34 | Used for optional auto brightness |
| Inverter link | CN1: TX 22, RX 27 | Through a MAX3232 to the inverter's RS232 port, 2400 baud 8N1, TX/RX crossed, common GND |

Only one controller may be on the inverter's RS232 port at a time.

### Memory (no PSRAM)
The ESP32 has 520 KB of internal RAM; the compile line "RAM … of 180736 bytes" only counts the
static-data region. What matters at runtime is the heap, which HTTPS needs about 45 KB of (one
24 KB block). To keep it free:
- the screen is drawn in strips of 10 % (`buffer_size: 10%`);
- WiFi keeps 6 static receive buffers instead of 10 (and fewer dynamic / management buffers);
- the 14 settings-only pages are **one** screen page (`page_set`) that the `set_ui` script refills
  as you page through them, so their widgets exist once in RAM instead of 14 times;
- TLS buffers are allocated only during a fetch (mbedTLS dynamic buffers).

At boot the log shows `[mem]` lines with the free heap before and after the screen and WiFi start;
Info → System shows the current values.

Flash: quad SPI (QIO) at 80 MHz; `minimum_chip_revision: "3.1"` (this board's chip).

## How it decides

### Safety rules (always)
- **One writer per setting.** Output priority, charger source and AC charge current are written only
  by the controller. The rules below only raise *reasons*.
- **Fresh data only.** Nothing is written in the first 30 s after boot, or when no valid inverter
  reply has arrived for 30 s (or SOC/load are unknown). Latched reasons are kept, not acted on.
- **Observe only** (default **on**): everything is computed and shown ("OBSERVE: would SUB …"),
  nothing is written. Turn it off on the Control page when you trust the decisions.
- **Auto Control off** = hands off: the controller writes nothing (the screen's Battery / Grid
  buttons turn it off). Exception: the float-voltage rule has its own switch.
- **Verify and retry.** A write is repeated while the inverter's read-back differs, at most every
  30 s. If it has not taken after a retry, the **Controller Fault** alarm fires and it retries every
  5 min.
- **No clock** (no NTP after a power cut): the time-based rules (night, overnight) pause; the
  battery and load rules keep working; non-critical sounds stay silent.

### Output priority
Any active reason switches the inverter to **SUB** (solar first, then grid; the battery rests). No
reason means **SBU** (solar, then battery, grid only as a last resort). It goes to SUB at once, but
returns to SBU only after at least **Min Time On Grid** (3 min) on SUB, so it never flaps.

### Reserve planner (every minute)
1. Picks the forecast for the coming day: **today's** before 12:00, **tomorrow's** after.
2. No internet forecast: uses today's measured solar after 15:00, otherwise yesterday's.
3. **Cloudy** = that forecast is below **Cloudy Below** (5 kWh), or unknown.
4. Sets the reserve: sunny **18 / 25 %**, cloudy **25 / 30 %** (switch to grid below / back to
   battery above). Clamped: switch 16 to 37 %, return at least switch + 3 and 25 %, at most 40 %.

### Reasons (rules)

| Reason | Turns ON when | Turns OFF when |
|---|---|---|
| **LOW** battery | SOC < reserve switch level for 60 s | SOC > reserve return level for 60 s |
| **HIGH** load | load > 2500 W for 6 s, and SOC < 80 %, and PV < 1200 W | load < 2000 W for 45 s |
| **NIGHT** load | night, load > 1600 W for 30 s, SOC < 70 % | load < 600 W for 60 s with SOC above the return level, **or** SOC > 60 % with load < 1000 W for 10 s |
| **OVERNIGHT** | night, and the predicted SOC at "sun useful" stays below max(10 %, switch level) for 5 min | prediction above that + 5 % for 5 min, or the sun is useful |
| **CHARGE** | the charger manager is grid-charging (below) | charging stops |

Each rule has an on/off switch (Setup → Rules). Night = sun below -0.833°.

### Overnight prediction
```
base load   = max(median of the last 3 h of 1-minute loads, Base Load Floor 300 W)
delay       = 1.5 h after sunrise (sunny day) or 3 h (cloudy day)
sun useful  = daytime and (PV >= base load, or time since sunrise > delay)
hours left  = at night: until next sunrise + delay;  in the morning: delay - time since sunrise
SOC at sun  = SOC - base load x hours left / battery capacity
```
The 3-hour median ignores a kettle or an hour of heating. In simulation (SOC 60 % at 17:00, sunny
tomorrow) it used the grid from 17:51 to 03:28 and kept 33 % for 08:20.

### Charger manager
The only writer of the charger source and AC charge current.
- **Starts** (after 60 s) with grid present and either a cloudy plan and SOC below
  **Grid Charge Target − Restart Margin** (40 − 10 = 30 %), or SOC below **Emergency Charge Below** (15 %).
- **Stops** at the target (cloudy: 40 %, otherwise the emergency target 25 %) or when the grid goes.
- While charging: source **Solar and utility**, current **20 A** below 20 % SOC, otherwise **10 A**
  (rounded to the inverter's steps 2/10/20/30/40/50/60). Not charging: **Solar only**, **10 A**.

### Float voltage
When the inverter enters float mode, the float voltage is set to **Float Voltage Target** (27.0 V)
if it differs. Switch: Rule Float Voltage.

### Solar forecast
Forecast.Solar (free API, HTTPS) for this location and the **PV Array Size / Tilt / Azimuth**
settings (default 2 kWp, 40°, south): today's and tomorrow's kWh plus today's power curve
("solar now"). Fetched about a minute after boot, then every **Forecast Refresh** hours (2 to 8, default 2); after a failure every 1 min
(15 min after HTTP 429, the free rate limit). Every failure is logged under the tag `fc` and shown
on Info → Projections and in the **Forecast Status** sensor. The fetch is skipped when free memory
is below 45 KB (largest block 24 KB).

### Energy and statistics
- Energy today (solar, load, grid import, battery charge / discharge) resets at local midnight
  (Asia/Damascus) and survives reboots.
- Battery remaining = capacity × (SOC − Battery Empty At) / 100. Runtime at the current load and at
  the 1-hour average load.
- Settings and state are saved to flash at most every 15 s.

## Alarms and sounds

| Event | Sound | Plays in quiet hours |
|---|---|---|
| Grid lost (30 s debounce, not in the first 90 s after boot) | grid lost, or the alarm if SOC < 30 % | no |
| Grid back | grid back | no |
| Switched to grid because of LOW | to grid (low) + banner | no |
| Switched to grid, other reason (not routine charging) | to grid | no |
| No grid and SOC < 30 % | alarm, repeating every 10 min below 20 % | **yes** |
| No grid and runtime < 2 h at base load (2 min) or < 30 min at the 5-min mean (5 min) | alarm + banner, at most every 30 min | **yes** |
| No grid and the battery may not last until sunrise (5 min) | morning warning + banner, every 30 min | **yes** |
| Inverter did not accept a write (after a retry) | alarm + banner | **yes** |

Quiet hours: 01:00 to 09:00 by default (switchable). A higher-priority tune interrupts a lower one.
Tap the red banner to silence and dismiss it. Setup → Sound has Test tune and Silence.

## Screen, icons and LED

Bottom bar: **Home · Info · Control · Setup · Advanced**; ‹ › moves between the pages of a group.

| Page | Shows |
|---|---|
| Home | Triple gauge (outer battery %, middle solar, inner load), Batt % / PV / Load / Grid, mode and active reasons, clock, reserve (switch/return %), predicted SOC at sunrise |
| Info 1-4 | Live power · Projections (battery kWh left, runtimes, forecast now / today / tomorrow, forecast status) · Energy today · System (firmware, WiFi, IP, signal, uptime, memory) |
| Control | Auto and Observe switches, Battery / Grid buttons (turn Auto off), inverter and charger state |
| Setup 1-5 | Battery reserve · Forecast and charging · Rules · Sound · Display |
| Advanced 1-13 | High load, night load, overnight, grid charging, charge current, timing, battery capacity, solar panels, Restore defaults |

Without fresh inverter data every inverter value shows **N/A** and the inverter buttons send nothing.

| Indicator | Meaning |
|---|---|
| **INV** green / red | Inverter data fresh / missing |
| **HA** green / red / grey | Home Assistant connected / not connected / API not built in |
| **WiFi** green / yellow / red | Internet OK (NTP sync or forecast reply in the last 11 min) / WiFi without internet / no WiFi |
| LED at boot | 1 s red, 1 s green, 1 s blue, 2 s off (colour check; also the **LED Test** button) |
| LED red blinking | No inverter data |
| LED blue | No WiFi |
| LED amber | On grid for a reason |
| LED green | All OK |

- **Backlight:** dims to 15 % after 90 s idle, off after 10 min; a touch wakes it. Optional auto
  brightness from the light sensor (Setup → Display: "Dark = now" / "Bright = now" to calibrate).
- **Touch calibration:** press **BOOT** to try the next of 8 orientations; the red touch dot
  (Setup → Display) shows where a touch lands.
- **Restore defaults** (Advanced, last page, tap twice within 5 s): every setting and switch back to
  its default; keeps the touch, light-sensor and LED calibration.

## Settings

All settings are on the screen or in Home Assistant (entity category *config*), saved across reboots.
This list is generated from `tools/cyd_settings.py` by `tools/cyd_readme.py`.

<!-- settings:begin -->
**Reserve planner and forecast**

| Setting (HA name) | Default | Range | Step | On screen | Kept by Restore defaults |
|---|---|---|---|---|---|
| Cloudy Below | 5 kWh | 0 to 20 | 0.5 | yes | no |
| Forecast Refresh | 2 h | 2 to 8 | 1 | yes | no |
| Sunny Day Switch SOC | 18 % | 16 to 37 | 1 | yes | no |
| Sunny Day Return SOC | 25 % | 25 to 40 | 1 | yes | no |
| Cloudy Day Switch SOC | 25 % | 16 to 37 | 1 | yes | no |
| Cloudy Day Return SOC | 30 % | 25 to 40 | 1 | yes | no |

**Charger manager**

| Setting (HA name) | Default | Range | Step | On screen | Kept by Restore defaults |
|---|---|---|---|---|---|
| Grid Charge Target | 40 % | 20 to 80 | 1 | yes | no |
| Grid Charge Restart Margin | 10 % | 3 to 30 | 1 | yes | no |
| Emergency Charge Below | 15 % | 5 to 30 | 1 | yes | no |
| Emergency Charge Target | 25 % | 15 to 50 | 1 | yes | no |
| Fast Charge Below | 20 % | 5 to 50 | 1 | yes | no |
| Fast Charge Current | 20 A | 2 to 60 | 1 | yes | no |
| Normal Charge Current | 10 A | 2 to 60 | 1 | yes | no |

**Overnight rule**

| Setting (HA name) | Default | Range | Step | On screen | Kept by Restore defaults |
|---|---|---|---|---|---|
| Overnight Floor SOC | 10 % | 5 to 40 | 1 | yes | no |
| Overnight Margin | 5 % | 1 to 20 | 1 | yes | no |
| Base Load Floor | 300 W | 50 to 2000 | 50 | yes | no |
| Sun Useful Delay Sunny | 1.5 h | 0 to 6 | 0.5 | yes | no |
| Sun Useful Delay Cloudy | 3 h | 0 to 8 | 0.5 | yes | no |

**Timing and float voltage**

| Setting (HA name) | Default | Range | Step | On screen | Kept by Restore defaults |
|---|---|---|---|---|---|
| Low SOC Delay | 60 s | 0 to 300 | 5 | yes | no |
| Min Time On Grid | 3 min | 0 to 30 | 1 | yes | no |
| Float Voltage Target | 27 V | 24 to 29.2 | 0.1 | yes | no |

**High-load rule**

| Setting (HA name) | Default | Range | Step | On screen | Kept by Restore defaults |
|---|---|---|---|---|---|
| High Load On | 2500 W | 1000 to 4000 | 100 | yes | no |
| High Load On Delay | 6 s | 0 to 60 | 1 | yes | no |
| High Load Off | 2000 W | 500 to 3500 | 100 | yes | no |
| High Load Off Delay | 45 s | 5 to 300 | 5 | yes | no |
| High Load Max SOC | 80 % | 30 to 100 | 5 | yes | no |
| High Load Max PV | 1200 W | 0 to 4000 | 100 | yes | no |

**Night-load rule**

| Setting (HA name) | Default | Range | Step | On screen | Kept by Restore defaults |
|---|---|---|---|---|---|
| Night Load On | 1600 W | 500 to 3000 | 100 | yes | no |
| Night Load On Delay | 30 s | 0 to 300 | 5 | yes | no |
| Night Max SOC | 70 % | 30 to 100 | 5 | yes | no |
| Night Load Off | 600 W | 100 to 2000 | 50 | yes | no |
| Night Load Off Delay | 60 s | 10 to 600 | 10 | yes | no |
| Night Release SOC | 60 % | 30 to 100 | 5 | yes | no |
| Night Release Load | 1000 W | 200 to 3000 | 100 | yes | no |
| Night Release Delay | 10 s | 0 to 120 | 5 | yes | no |

**Battery and solar array**

| Setting (HA name) | Default | Range | Step | On screen | Kept by Restore defaults |
|---|---|---|---|---|---|
| Battery Capacity | 4.5 kWh | 1 to 30 | 0.1 | yes | no |
| Battery Empty At | 5 % | 0 to 30 | 1 | yes | no |
| PV Array Size | 2 kWp | 0.5 to 20 | 0.1 | yes | no |
| PV Tilt | 40° | 0 to 90 | 1 | yes | no |
| PV Azimuth | 0° | -180 to 180 | 5 | yes | no |

**Sound**

| Setting (HA name) | Default | Range | Step | On screen | Kept by Restore defaults |
|---|---|---|---|---|---|
| Quiet Hours From | 1 h | 0 to 23 | 1 | yes | no |
| Quiet Hours Until | 9 h | 0 to 23 | 1 | yes | no |

**Display and LED (calibration)**

| Setting (HA name) | Default | Range | Step | On screen | Kept by Restore defaults |
|---|---|---|---|---|---|
| Backlight Min (auto) | 20 % | 5 to 100 | 5 | yes | no |
| LDR Dark Reading | 0.3 V | 0 to 1.2 | 0.001 | no (HA only) | yes |
| LDR Bright Reading | 0 V | 0 to 1.2 | 0.001 | no (HA only) | yes |
| LED Red Level | 100 % | 5 to 100 | 5 | no (HA only) | yes |
| LED Green Level | 100 % | 5 to 100 | 5 | no (HA only) | yes |
| LED Blue Level | 100 % | 5 to 100 | 5 | no (HA only) | yes |

**Switches**

| Switch (HA name) | Default | On screen |
|---|---|---|
| Auto Control | on | yes |
| Observe Only | on | yes |
| Rule Low Battery | on | yes |
| Rule High Load | on | yes |
| Rule Night Load | on | yes |
| Rule Overnight | on | yes |
| Charger Manager | on | yes |
| Rule Float Voltage | on | yes |
| Buzzer | on | yes |
| Buzzer Quiet Hours | on | yes |
| Auto Brightness | off | yes |
| Touch Debug | off | yes |
<!-- settings:end -->

## Network and Home Assistant

- **WiFi:** DHCP (any network). The house's fixed address (192.168.10.4, gateway .1) is in the YAML,
  commented out; enable it only on that network or the board has no internet.
- **Time:** NTP from 0.pool.ntp.org, time.google.com and time.cloudflare.com, every 5 min.
- **Home Assistant API: off by default.** Uncomment `api:` (and the `homeassistant` time source) to
  connect HA. Without the API the dashboard's WiFi log viewer does not work; read logs over USB
  (web.esphome.io). OTA updates work either way.
- **Exposed to HA:** all settings and switches; the useful readings (SOC, battery V/W, PV, load, grid
  V/W, temperature); cumulative energy for HA's Energy dashboard; the plan (reserve, forecast,
  predicted SOC at sun, base load, battery kWh and runtime, Controller State, Cloudy Day Plan, Grid
  Charging Active, Controller Fault, Forecast Status); grid / link / warnings / faults; Output and
  Charger Source Priority and AC charge current; diagnostics (WiFi, IP, version, uptime, memory,
  restart, safe mode). Internal: raw inverter read-backs, the inverter's battery-voltage setters,
  daily counters, individual warning bits, LED / backlight entities.
- **Letting HA take over:** turn **Auto Control** off (and **Rule Float Voltage** if HA handles
  float too). Guard every HA automation with the **Inverter Link** entity, because HA keeps the last
  values when the board is offline. With Auto on, the controller reverts other writers within 30 s.

## Code structure

The decision logic described above is not YAML any more: it is the **solar autopilot core**,
plain C++17 in `components/solar_autopilot/ap_*.{h,cpp}`. It has no Arduino, ESP-IDF or ESPHome
dependency, no heap allocation and no clock of its own: the caller passes the time and the
readings in on every call and performs the actions it returns. The same core runs on this board
(ESPHome), in the simulator on a PC, and in plain Arduino or ESP-IDF projects.

| Class (file) | Job |
|---|---|
| `Controller` (`ap_controller`) | Owns the parts below; safety gate (30 s after boot, stale data, auto / observe) |
| `LoadStats` (`ap_load_stats`) | 1-minute load means: 3 h median (base load), 5-minute mean |
| `SunTracker`, `ReservePlanner`, `predict_soc_at_sun` (`ap_planner`) | Sunrise time, forecast -> switch / return SOC, SOC when the sun becomes useful |
| `LowRule`, `HighRule`, `NightRule`, `OvernightRule` (`ap_rules`) | One reason bit each, latched with their own hold times |
| `ChargerManager`, `OutputArbiter`, `ChargerWriter` (`ap_writers`) | Grid-charge latch; writing output priority and charger source / current with retries and fault |
| `AlarmManager`, `sound_allowed` (`ap_alarms`) | Alarms without grid, grid lost / back sounds, quiet hours |
| `Settings` (`ap_settings.h`, generated) | All controller settings with defaults, from `tools/cyd_settings.py` |

The ESPHome side (`solar_autopilot.{h,cpp}`, `__init__.py`) reads the entities, calls the core
every 2 s (`control`) and every minute (`minute`), writes the selects, saves the state that must
survive a reboot, and fires `on_tune` / `on_notify` (the YAML plays the sound and shows the
message). Screen and HA lambdas read the results with `id(autopilot).status()` (for example
`.reserve_sw`, `.reasons`, `.soc_at_sun`), `id(autopilot).link()` and `id(autopilot).last_data_ms()`.
How to use the core elsewhere: [components/solar_autopilot/README.md](components/solar_autopilot/README.md).

## Workflow

**Rules (from the owner):** back up before changing, validate with `esphome config`, compile only
with the owner's OK, never flash from here (the owner flashes `firmware/inverter-cyd.factory.bin`
at web.esphome.io). `firmware/`, `backups/` and `config/` (secrets) are not in git.

The ESPHome container (`compose.yaml`) uses `./config` as `/config`; copy the YAML there to build:

    docker cp inverter-cyd.yaml esphome:/config/inverter-cyd.yaml
    docker exec esphome sh -c 'rm -rf /config/components/solar_autopilot && mkdir -p /config/components'
    docker cp components/solar_autopilot esphome:/config/components/
    docker exec esphome esphome config /config/inverter-cyd.yaml
    docker exec -e ESPHOME_ESP_IDF_PREFIX=/config/.esphome/idf esphome esphome compile /config/inverter-cyd.yaml

Pass `ESPHOME_ESP_IDF_PREFIX` exactly as above (the dashboard uses it), and never compile from the
command line while a dashboard build runs: they share one build folder.

**Generated parts** (edit the tool, not the YAML):

| Part | Source | Apply |
|---|---|---|
| `number:` / `switch:`, `ui_sync_all`, `restore_defaults` | `tools/cyd_settings.py` | `python3 tools/cyd_settings_apply.py inverter-cyd.yaml` |
| `lvgl:` section, `ui_refresh_values`, `set_ui` (shared settings page) | `tools/cyd_ui.py` (pages of settings rows: `VPAGES` in `cyd_settings.py`) | run `cyd_ui.py check / render / yaml / script` in the container, then `tools/cyd_ui_inject.py` |
| Settings tables in this README | `tools/cyd_settings.py` | `python3 tools/cyd_readme.py README.md` |
| Controller `Settings` (`ap_settings.h`, `settings_keys.py`) and the `settings:` block of `solar_autopilot:` | `tools/cyd_settings.py` | `python3 tools/gen_autopilot_settings.py` (then update the `settings:` block if a key was added) |

`cyd_ui.py check` verifies against LVGL's real Montserrat glyph widths that no text overlaps or
leaves the screen; `render` draws PNG previews.

**Simulation.** `tools/sim/run.sh` compiles the controller core (g++ in the ESPHome container)
against a simulated house, battery, PV, grid and inverter, runs 16 scenarios (sunny and cloudy
days, outages, SOC glitch, link loss, no clock, write failures, observe only, …) and checks 160
expectations. The world calls the core through a small adapter, the same way the ESPHome
component does, and the YAML's own `play_tune` lambda is extracted and compiled with it. Run it
after any change to the control logic:

    cd tools/sim && ./run.sh ../../inverter-cyd.yaml results

To prove a refactor changes no decision, record a run before it and compare after: every write,
sound, message and minute sample must be identical (`CORE=1` forces the C++ core for a YAML
that still has the old lambdas).

    ./run.sh ../../inverter-cyd.yaml results_before     # before the change
    ./run.sh ../../inverter-cyd.yaml results && diff -r results_before results
