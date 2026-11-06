// Solar autopilot core: plain C++17, no Arduino / ESP-IDF / ESPHome. The caller passes the time
// and the readings in on every call; the core never reads a clock or a pin, and never allocates.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace autopilot_core {

// Time, given by the caller. All comparisons are elapsed-time (now - since), so the 49-day
// wrap of a 32-bit millisecond counter is harmless.
struct Clock {
  uint32_t ms = 0;              // monotonic milliseconds (millis())
  bool valid = false;           // wall clock known (SNTP synced)
  uint32_t epoch = 0;           // UTC seconds, only if valid
  int hour = 0, minute = 0;     // local time, only if valid
  double sun_elevation = NAN;   // degrees, only if valid
};

// Inverter values (PI30 numbering)
enum OutputPriority : uint8_t { OUT_USB = 0, OUT_SUB = 1, OUT_SBU = 2 };
enum ChargerSource : uint8_t { CHG_UTILITY_FIRST = 0, CHG_SOLAR_FIRST = 1, CHG_SOLAR_AND_UTILITY = 2, CHG_SOLAR_ONLY = 3 };

// Readings, refreshed by the caller before each call. NAN = unknown.
struct Inputs {
  float soc = NAN, load_w = NAN, pv_w = NAN;
  uint32_t last_data_ms = 0;            // Clock::ms of the last inverter reply, 0 = never
  bool grid_known = false, grid = false;  // grid present, debounced (see GridDebounce)
  float output_priority = NAN;          // read back from the inverter (OutputPriority)
  float charger_source = NAN;           // read back (ChargerSource)
  float charge_current = NAN;           // read back, max AC charging current (A)
  float float_voltage = NAN;            // read back (V)
  float solar_today_kwh = NAN;          // measured solar energy today
  float forecast_today_kwh = NAN, forecast_tomorrow_kwh = NAN;
};

// Reasons that want "Solar first (SUB)" (= grid allowed). None -> "Battery first (SBU)".
enum Reason : uint8_t { R_LOW = 1, R_HIGH = 2, R_NIGHT = 4, R_OVN = 8, R_CHG = 16 };

// What the controller decided and computed (screens, Home Assistant, logs).
struct Status {
  uint8_t reasons = 0;
  bool want_sub = false;        // decision (also in observe-only mode)
  bool fault = false;           // a write did not take after a retry
  float reserve_sw = 25, reserve_ret = 30;
  bool cloudy = true;           // planner: coming day cloudy (unknown counts as cloudy)
  float plan_fc = NAN;          // forecast kWh the planner used
  bool charging = false;        // charger manager latch
  float soc_at_sun = NAN;       // predicted SOC when the sun becomes useful
  float base_load = 300, load_median = NAN, load_mean5 = NAN;
  uint32_t sunrise_ts = 0;
  float solar_yesterday_kwh = NAN;
};

// State that should survive a reboot. The caller stores it (flash, NVS) when it changes.
struct Persist {
  uint8_t reasons = 0;
  bool cloudy = true, charging = false;
  float reserve_sw = 25, reserve_ret = 30;
  float solar_yesterday_kwh = NAN;
  uint32_t sunrise_ts = 0;

  // field by field (no padding bytes), NAN equals NAN: "changed since last saved?"
  bool operator==(const Persist &o) const {
    auto same = [](float a, float b) { return a == b || (std::isnan(a) && std::isnan(b)); };
    return reasons == o.reasons && cloudy == o.cloudy && charging == o.charging && same(reserve_sw, o.reserve_sw) &&
           same(reserve_ret, o.reserve_ret) && same(solar_yesterday_kwh, o.solar_yesterday_kwh) &&
           sunrise_ts == o.sunrise_ts;
  }
  bool operator!=(const Persist &o) const { return !(*this == o); }
};

// Condition held true for a duration. since = 0 means "not holding".
struct HeldTimer {
  uint32_t since = 0;
  bool update(bool cond, uint32_t now, uint32_t dur) {
    if (!cond) {
      since = 0;
      return false;
    }
    if (since == 0) since = std::max<uint32_t>(now, 1);
    return now - since >= dur;
  }
};

inline uint32_t seconds_ms(float s) { return (uint32_t) (s * 1000.0f); }

}  // namespace autopilot_core
