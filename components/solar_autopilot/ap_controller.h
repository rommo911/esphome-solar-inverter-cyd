// The controller: owns the parts and runs them in order.
//
//   control()       every 2 s   rules, charger manager, writers
//   minute()        every 60 s  load statistics, sunrise, reserve planner, alarms
//   grid_changed()  when the debounced grid changes (not for its first reading)
//   float_entered() when the inverter enters float charging
//
// Each call fills `out` with what to do, in order (see Actions). Safety: nothing is written for
// 30 s after begin(), while the inverter data is stale, with auto control off, or in
// observe-only mode (decisions are still made and shown).
#pragma once

#include "ap_actions.h"
#include "ap_alarms.h"
#include "ap_load_stats.h"
#include "ap_planner.h"
#include "ap_rules.h"
#include "ap_settings.h"
#include "ap_types.h"
#include "ap_writers.h"

namespace autopilot_core {

class Controller {
 public:
  void configure(const AlarmConfig &cfg) { cfg_ = cfg; }
  void begin(uint32_t now_ms) { boot_ms_ = std::max<uint32_t>(now_ms, 1); }
  void restore(const Persist &p);
  Persist persist() const;

  void control(const Clock &c, const Inputs &in, const Settings &s, Actions &out);
  void minute(const Clock &c, const Inputs &in, const Settings &s, Actions &out);
  void grid_changed(bool grid, const Clock &c, const Inputs &in, Actions &out);
  void float_entered(const Inputs &in, const Settings &s, Actions &out);

  // Fresh inverter data: a reply in the last 30 s with SOC and load known.
  static bool link(const Clock &c, const Inputs &in) {
    return in.last_data_ms != 0 && c.ms - in.last_data_ms < 30000 && !std::isnan(in.soc) && !std::isnan(in.load_w);
  }
  Status status() const;

 private:
  AlarmConfig cfg_;
  uint32_t boot_ms_ = 0;
  uint8_t reasons_ = 0;
  bool want_sub_ = false, fault_ = false;
  float soc_at_sun_ = NAN;
  float solar_yesterday_ = NAN, last_solar_ = NAN;
  int prev_hour_ = -1;

  LoadStats load_;
  SunTracker sun_;
  ReservePlanner planner_;
  LowRule low_;
  HighRule high_;
  NightRule night_;
  OvernightRule overnight_;
  ChargerManager charger_;
  OutputArbiter output_;
  ChargerWriter charger_writer_;
  AlarmManager alarms_;
};

// Grid present, debounced: a change counts after it has lasted `hold_ms` (default 30 s).
// For callers without their own filter (ESPHome uses delayed_on / delayed_off instead).
class GridDebounce {
 public:
  explicit GridDebounce(uint32_t hold_ms = 30000) : hold_(hold_ms) {}
  // Returns true when the debounced state changed; first = it was the first reading.
  bool update(bool raw, uint32_t now, bool *first = nullptr) {
    if (raw != raw_) {
      raw_ = raw;
      changed_ = now;
    }
    if ((!known_ || raw != state_) && now - changed_ >= hold_) {
      if (first) *first = !known_;
      known_ = true;
      state_ = raw;
      return true;
    }
    return false;
  }
  bool known() const { return known_; }
  bool state() const { return state_; }

 private:
  uint32_t hold_, changed_ = 0;
  bool raw_ = false, known_ = false, state_ = false;
};

}  // namespace autopilot_core
