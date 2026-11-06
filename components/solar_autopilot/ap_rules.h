// The four "go to grid" rules. Each one sets or clears its reason bit; the bit is latched
// between calls (on and off conditions have their own hold times).
#pragma once

#include "ap_settings.h"
#include "ap_types.h"

namespace autopilot_core {

struct RuleCtx {
  uint32_t now;
  float soc, load, pv;
  bool night, time_ok;
  float reserve_sw, reserve_ret;
  float soc_at_sun;
  bool sun_useful;
  const Settings &s;
};

// LOW: SOC below the planner's switch level -> grid; above its return level -> release.
class LowRule {
 public:
  void update(const RuleCtx &c, uint8_t &reasons);

 private:
  HeldTimer on_, off_;
};

// HIGH: heavy load while SOC and PV are low.
class HighRule {
 public:
  void update(const RuleCtx &c, uint8_t &reasons);

 private:
  HeldTimer on_, off_;
};

// NIGHT: medium load at night with SOC below the night limit.
class NightRule {
 public:
  void update(const RuleCtx &c, uint8_t &reasons);

 private:
  HeldTimer on_, off_, off2_;
};

// OVERNIGHT: the battery would be too low when the sun becomes useful.
class OvernightRule {
 public:
  void update(const RuleCtx &c, uint8_t &reasons);

 private:
  HeldTimer on_, off_;
};

}  // namespace autopilot_core
