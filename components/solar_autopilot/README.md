# solar_autopilot

The controller of the [CYD inverter controller](../../README.md) as a reusable library. It decides
when a PI30 hybrid inverter (Axpert / Voltronic family) runs the house on battery or grid, when
the battery charges from the grid, and when to raise an alarm. The full rules are in the main
README, under "How it decides".

One folder, three ways to use it:

| Use | What you take |
|---|---|
| ESPHome | the whole folder as an external component |
| Arduino / PlatformIO | the core (`ap_*.h`, `ap_*.cpp`, `autopilot.h`); `library.json` selects it |
| ESP-IDF | the core as an IDF component; `CMakeLists.txt` builds it |
| PC / tests | the core with any C++17 compiler (`examples/desktop`, `tools/sim`) |

## The core

The core is plain C++17 with no framework and no heap. It never reads a clock or a pin. You give
it the time and the readings on every call, and it returns a list of actions for you to perform.

```cpp
#include "autopilot.h"
using namespace autopilot_core;

Controller ctl;          // ctl.restore(saved) after boot, then:
ctl.begin(millis());

// every 2 s
Actions acts;
ctl.control(clock, inputs, settings, acts);   // rules, charger manager, writes
// every 60 s
ctl.minute(clock, inputs, settings, acts);    // load statistics, sunrise, reserve planner, alarms
// when the debounced grid changes (not for its first reading)
ctl.grid_changed(grid, clock, inputs, acts);
// when the inverter enters float charging
ctl.float_entered(inputs, settings, acts);

for (const Action &a : acts) { /* SET_OUTPUT_PRIORITY, SET_CHARGER_SOURCE, SET_CHARGE_CURRENT,
                                  SET_FLOAT_VOLTAGE, TUNE, NOTIFY, LOG */ }
```

- **`Clock`:** `ms` (monotonic), `valid` (wall clock known), `epoch`, local `hour`/`minute`, and
  `sun_elevation` in degrees.
- **`Inputs`:**
  - SOC, load and PV
  - when the inverter last answered
  - debounced grid presence; `GridDebounce` does this if you have no filter of your own
  - the inverter's read-back of output priority, charger source, charge current and float voltage
  - measured solar today
  - forecast for today and tomorrow, in kWh
- **`Settings`:** every threshold, with its default. `NUMBER_INFO` and `SWITCH_INFO` list each
  setting's name, unit, range and step, for building your own settings UI.
- **Writes are requests.** You perform them, and the controller checks the read-back on later
  calls. It retries every 30 s, and after two failed tries sets `fault` and retries every 5 min.
- **`persist()` / `restore()`:** the few values that must survive a reboot. Save them when they
  change (`Persist` has `==`).
- **`status()`:** reasons, decision, reserve levels, forecast used, charging, predicted SOC at
  sunrise, base load and fault, for your screen or logs.
- **`sound_allowed(settings, clock, critical)`:** buzzer switch and quiet hours.

The defaults are safe: `observe` is on, so the controller decides and reports but writes nothing
until you turn it off.

Examples:
- `examples/desktop/main.cpp`: the whole contract in about 60 lines. It runs on a PC.
- `examples/arduino/solar_autopilot_basic`: ESP32 Arduino. The PI30 serial link and the sun
  elevation are left for you to fill in; a PI30 client is planned.

## ESPHome

```yaml
external_components:
  - source: github://rommo911/esphome-solar-inverter-cyd
    components: [solar_autopilot]

solar_autopilot:
  id: autopilot
  pipsolar_id: my_inverter           # that's all for the inverter (see below)
  forecast: { latitude: 36.15, longitude: 36.73 }    # optional, needs http_request:
  on_setting_change:                                 # optional: e.g. refresh a screen
    - logger.log: { format: "setting %s changed", args: [key.c_str()] }
  on_tune:
    - logger.log: { format: "sound %s", args: [tune.c_str()] }
  on_notify:
    - logger.log: { format: "%s", args: [message.c_str()] }
```

**`pipsolar_id`** connects the component to the inverter.

- **Readings:** the component takes them from the entities you declare under `- platform: pipsolar`
  with that id: `battery_capacity_percent`, `ac_output_active_power`, `pv_charging_power`,
  `grid_voltage`, `output_source_priority`, `charger_source_priority`,
  `current_max_ac_charging_current`, `battery_float_voltage`, and the binary sensor
  `charging_to_floating_mode`. If a required one is missing, the config check names it.
- **Writes:** sent to the inverter as PI30 commands (POP, PCP, MUCHGC, PBFT), so no selects are
  needed.
- **Grid:** "voltage above `grid_min_voltage` (150 V) for 30 s".
- **Link:** every reply refreshes it, through the SOC sensor's raw values.

Any key set by hand overrides this (`soc:`, `grid:`, `output_priority:` with a select, and so on),
which also lets you use the component without pipsolar. `solar_today:` (a total_daily_energy of PV
power) is optional; it's the fallback when there is no forecast. `time_id` and `sun_id` are found
automatically.


The component publishes its results as entities, so you don't need template sensors. Every key
is optional and takes the usual options (`name`, `id`, `internal`, filters, and so on):

```yaml
sensor:
  - platform: solar_autopilot     # published every minute
    reserve_switch: { name: "Reserve Switch SOC" }
    reserve_return: { name: "Reserve Return SOC" }
    forecast_used: { name: "Solar Forecast Used" }
    soc_at_sun: { name: "Predicted SOC At Sun" }
    base_load: { name: "Base Load" }
    battery_remaining: { name: "Battery Remaining" }
    battery_runtime: { name: "Battery Runtime" }     # at the base load
binary_sensor:
  - platform: solar_autopilot     # every 2 s
    link: { id: inv_link, name: "Inverter Link" }   # fresh inverter data
    cloudy: { name: "Cloudy Day Plan" }
    charging: { name: "Grid Charging Active" }
    fault: { name: "Controller Fault" }
    grid: { name: "Grid Available" }               # when the component debounces the grid
text_sensor:
  - platform: solar_autopilot
    state: { name: "Controller State" }             # e.g. "grid (SUB) LOW CHARGE"
```

For screen lambdas, everything is also available directly: `id(autopilot).status().reserve_sw`
and `id(autopilot).link()`. Status covers reasons, want_sub, cloudy, charging, soc_at_sun,
base_load, fault and more.

**Forecast.** With a `forecast:` block, the component fetches Forecast.Solar itself. That's
the free API with no key, and it needs `http_request:`. It gets the day totals for today and
tomorrow, then today's power curve. It fetches every `fc_interval_h` hours, retries every minute
after a failure, and waits 15 min after HTTP 429. The panel plane comes from the `pv_kwp`,
`pv_tilt` and `pv_az` settings.

```yaml
solar_autopilot:
  forecast: { latitude: 36.15, longitude: 36.73 }
sensor:
  - platform: solar_autopilot
    forecast_today: { name: "Solar Forecast Today" }
    forecast_tomorrow: { name: "Solar Forecast Tomorrow" }
    forecast_now: { name: "Solar Forecast Now" }     # W, from today's curve
text_sensor:
  - platform: solar_autopilot
    forecast_status: { name: "Forecast Status" }    # "ok 14:05: today 7.3 kWh, ..." / "HTTP 429: ..."
```

Screen lambdas: `id(autopilot).forecast().today_kwh()`, `.tomorrow_kwh()`, `.power_at(minute)` and
`.status()`. Without a `forecast:` block you can feed `forecast_today` and `forecast_tomorrow` as
lambdas, for example from Home Assistant. The core's `Forecast` class (`ap_forecast.h`) does the
scheduling, the URLs and the reply parsing without a JSON library. On another platform you only
do the HTTPS GET.

**Settings.** The component creates every setting as an entity: 42 numbers and 10 switches,
in the config category, saved in flash, and shown in Home Assistant. Each has its name, unit,
range, step and default from `settings_keys.py`, and ids `n_<key>` / `sw_<key>` (for example
`n_cloudy_kwh` or `sw_observe`), so lambdas can use `id(n_cloudy_kwh).state`. You can change one
like any entity, or give the id of your own entity instead:

```yaml
solar_autopilot:
  settings:
    cloudy_kwh: { name: "Cloudy Day Below", internal: true }
    batt_kwh: my_battery_capacity_number
```

They use the same flash storage as template numbers and switches with the same name, so moving
from template entities to these keeps the values already saved. `inverter-cyd.yaml` is the complete
example.

## Changing the logic

1. Edit `ap_*.cpp`.
2. Run `tools/sim/run.sh`. It runs 16 scenarios with 160 checks, and compares the result against a
   recorded run.
3. Add or rename settings in `tools/cyd_settings.py`, then run
   `tools/gen_autopilot_settings.py`.
