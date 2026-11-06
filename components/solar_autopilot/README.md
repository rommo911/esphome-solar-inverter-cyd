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
  time_id: sntp_time
  sun_id: sun_c
  soc: s_soc
  load_power: s_load_power
  pv_power: s_pv_power
  grid: bs_grid                      # binary sensor, debounced (delayed_on/off 30 s)
  output_priority_state: s_output_source_priority
  output_priority: sel_output_source_priority
  # optional: floating, solar_today, charger_source(_state), charge_current(_state),
  #           float_voltage(_state), forecast_today / forecast_tomorrow (lambda), alarm_soc,
  #           alarm_repeat_soc, settings: {key: number or switch id}
  on_tune:
    - logger.log: { format: "sound %s", args: [tune.c_str()] }
  on_notify:
    - logger.log: { format: "%s", args: [message.c_str()] }
```

Feed it the inverter replies with `id(autopilot).mark_data();` in a pipsolar sensor's
`on_raw_value`. Unbound settings use their defaults. `inverter-cyd.yaml` is the complete
example.

## Changing the logic

1. Edit `ap_*.cpp`.
2. Run `tools/sim/run.sh`. It runs 16 scenarios with 160 checks, and compares the result against a
   recorded run.
3. Add or rename settings in `tools/cyd_settings.py`, then run
   `tools/gen_autopilot_settings.py`.
