// The controller core on a PC: a falling battery at night with the grid present.
// Shows the whole integration contract in ~60 lines: fill Clock + Inputs + Settings, call
// control() every 2 s and minute() every 60 s, perform the Actions, feed the read-back back in.
//
//   g++ -std=c++17 -I../../components/solar_autopilot main.cpp ../../components/solar_autopilot/ap_*.cpp
#include <cstdio>

#include "autopilot.h"

using namespace autopilot_core;

int main() {
  Controller ctl;
  Settings settings;              // defaults; a real device loads them from its storage
  settings.observe = false;       // default is observe-only (decide, never write)
  Inputs in;
  in.grid_known = in.grid = true;
  in.output_priority = OUT_SBU;   // the "inverter" starts on battery
  in.charger_source = CHG_SOLAR_ONLY;
  in.charge_current = 10;
  in.forecast_today_kwh = in.forecast_tomorrow_kwh = 9;   // sunny

  Clock c;
  c.valid = true;
  c.epoch = 1793000000;
  ctl.begin(0);
  for (c.ms = 0; c.ms <= 15 * 60000; c.ms += 2000) {
    c.epoch = 1793000000 + c.ms / 1000;
    c.hour = 21;
    c.sun_elevation = -30;        // night
    in.soc = 20 - c.ms / 60000.0f * 0.5f;   // 20 % falling 0.5 %/min
    in.load_w = 450;
    in.pv_w = 0;
    in.last_data_ms = c.ms;       // fresh inverter reply

    Actions acts;
    ctl.control(c, in, settings, acts);
    if (c.ms % 60000 == 0) ctl.minute(c, in, settings, acts);
    for (const Action &a : acts) {
      switch (a.type) {
        case ActionType::SET_OUTPUT_PRIORITY:
          printf("%5.1f min  write output priority %s\n", c.ms / 60000.0, a.code == OUT_SUB ? "SUB" : "SBU");
          in.output_priority = a.code;   // the inverter takes it (read back on the next poll)
          break;
        case ActionType::SET_CHARGER_SOURCE: in.charger_source = a.code; break;
        case ActionType::SET_CHARGE_CURRENT: in.charge_current = a.value; break;
        case ActionType::TUNE: printf("%5.1f min  sound %s\n", c.ms / 60000.0, tune_name((Tune) a.code)); break;
        case ActionType::NOTIFY: printf("%5.1f min  message: %s\n", c.ms / 60000.0, a.text); break;
        case ActionType::LOG: printf("%5.1f min  log: %s\n", c.ms / 60000.0, a.text); break;
        default: break;
      }
    }
  }
  const Status st = ctl.status();
  printf("end: reasons 0x%02X, reserve %.0f/%.0f %%, %s\n", st.reasons, st.reserve_sw, st.reserve_ret,
         st.want_sub ? "on grid" : "on battery");
  return st.want_sub ? 0 : 1;     // LOW (SOC < 18 %) must have switched to grid
}
