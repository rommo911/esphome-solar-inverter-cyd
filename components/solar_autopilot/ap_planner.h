// Reserve planner (forecast -> switch / return SOC), sunrise tracking and the predicted SOC at
// the moment the sun becomes useful.
#pragma once

#include "ap_settings.h"
#include "ap_types.h"

namespace autopilot_core {

// Records the time of sunrise: the sun crossing -0.833 deg upward. Call once a minute.
class SunTracker {
 public:
  void update(const Clock &c);
  uint32_t sunrise_ts = 0;      // epoch of the last sunrise, 0 = unknown

 private:
  float prev_el_ = NAN;
};

class ReservePlanner {
 public:
  // Forecast for the coming day (afternoon -> tomorrow). Without a forecast: today's measured
  // solar after 15:00, else yesterday's. Unknown counts as cloudy.
  void update(const Clock &c, const Inputs &in, const Settings &s, float solar_yesterday_kwh);

  bool cloudy = true;
  float plan_fc = NAN;
  float reserve_sw = 25, reserve_ret = 30;
};

struct SunPrediction {
  float soc_at_sun = NAN;       // NAN = unknown (no clock, or night with sunrise unknown)
  bool sun_useful = false;      // PV covers the base load, or the "sun useful" delay has passed
};

// SOC when the sun becomes useful: SOC - base load x hours until then.
SunPrediction predict_soc_at_sun(const Clock &c, float soc, float pv, float base_load, bool cloudy,
                                 uint32_t sunrise_ts, const Settings &s);

inline bool is_night(const Clock &c) { return c.valid && c.sun_elevation < -0.833; }

}  // namespace autopilot_core
