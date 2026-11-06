// Charger manager (when to grid-charge) and the two writers that bring the inverter to the
// wanted state: output priority, and charger source + AC charge current. State-based: a writer
// writes while the read-back differs, at most every 30 s; after two tries that did not take it
// raises the shared fault and retries every 5 min.
#pragma once

#include "ap_actions.h"
#include "ap_rules.h"

namespace autopilot_core {

// Latch: start (held for the low delay) when the grid is there and the battery is low for the
// coming day (cloudy) or very low (emergency); stop at the target or when the grid goes.
class ChargerManager {
 public:
  void update(const RuleCtx &c, bool grid, bool cloudy, uint8_t &reasons);
  bool charging = false;

 private:
  HeldTimer start_;
};

struct WriteCtx {
  uint32_t now;
  bool active;          // auto control on and not observe-only
  bool grid;
  float soc, load;
  float reserve_sw, reserve_ret;
  const Inputs &in;
  const Settings &s;
};

// Output priority: SUB as soon as any reason wants it; back to SBU only after the minimum time
// on SUB. Returns true while the inverter is not where it should be.
class OutputArbiter {
 public:
  bool update(const WriteCtx &c, uint8_t reasons, bool &fault, Actions &out);

 private:
  uint32_t sub_since_ = 0, last_write_ = 0;
  uint8_t tries_ = 0;
};

// Charger source + current (the only writer of both): "Solar only" unless charging, then
// "Solar and utility"; fast current below the fast-charge SOC.
class ChargerWriter {
 public:
  bool update(const WriteCtx &c, bool charging, bool &fault, Actions &out);

 private:
  uint32_t last_write_ = 0;
  uint8_t tries_ = 0;
};

}  // namespace autopilot_core
