// Alarms without grid (low SOC, short runtime, morning warning), grid lost / back sounds and
// the quiet-hours policy for sounds.
#pragma once

#include "ap_actions.h"
#include "ap_settings.h"
#include "ap_types.h"

namespace autopilot_core {

struct AlarmConfig {
  float alarm_soc = 30;         // no grid: alarm once below this SOC
  float repeat_soc = 20;        // ... then every 10 min below this SOC
};

class AlarmManager {
 public:
  // Once a minute. Runtime alarm (< 2 h at base load or < 0.5 h at the 5-min mean) and the
  // morning warning (battery may run out before the sun is useful), each at most every 30 min.
  void runtime(uint32_t now, bool link, const Inputs &in, const Settings &s, float base_load, float mean5,
               float soc_at_sun, Actions &out);
  // Once a minute. Low SOC without grid.
  void low_soc(uint32_t now, const Inputs &in, const AlarmConfig &cfg, Actions &out);
  // The debounced grid changed (not called for the first reading).
  void grid_changed(bool grid, float soc, const AlarmConfig &cfg, Actions &out);

 private:
  HeldTimer rt_base_, rt_now_, morning_;
  uint32_t last_rt_ = 0, last_mw_ = 0, last_low_ = 0;
  bool low_alarmed_ = false;
};

// May a sound play now? Non-critical sounds are muted in quiet hours (and when the clock is
// unknown, as it might be night).
inline bool sound_allowed(const Settings &s, const Clock &c, bool critical) {
  if (!s.buzzer) return false;
  if (!critical && s.quiet && !c.valid) return false;
  if (!critical && s.quiet && c.valid) {
    const int a = (int) s.quiet_start, b = (int) s.quiet_end, h = c.hour;
    const bool quiet = a <= b ? (h >= a && h < b) : (h >= a || h < b);
    if (quiet) return false;
  }
  return true;
}

}  // namespace autopilot_core
