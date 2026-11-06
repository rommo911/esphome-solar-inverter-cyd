#include "ap_rules.h"

namespace autopilot_core {

void LowRule::update(const RuleCtx &c, uint8_t &r) {
  const uint32_t d = seconds_ms(c.s.low_delay);
  const bool on = on_.update(c.soc < c.reserve_sw, c.now, d);
  const bool off = off_.update(c.soc > c.reserve_ret, c.now, d);
  if (!c.s.rule_low) r &= ~R_LOW;
  else if (on) r |= R_LOW;
  else if (off) r &= ~R_LOW;
}

void HighRule::update(const RuleCtx &c, uint8_t &r) {
  const Settings &s = c.s;
  const bool on = on_.update(c.load > s.high_on_w && c.soc < s.high_max_soc &&
                                 (std::isnan(c.pv) || c.pv < s.high_max_pv),
                             c.now, seconds_ms(s.high_on_s));
  const bool off = off_.update(c.load < s.high_off_w, c.now, seconds_ms(s.high_off_s));
  if (!s.rule_high) r &= ~R_HIGH;
  else if (on) r |= R_HIGH;
  else if (off) r &= ~R_HIGH;
}

void NightRule::update(const RuleCtx &c, uint8_t &r) {
  const Settings &s = c.s;
  const bool on = on_.update(c.night && c.load > s.night_on_w && c.soc < s.night_max_soc, c.now,
                             seconds_ms(s.night_on_s));
  const bool off1 = off_.update(c.load < s.night_off_w && c.soc > c.reserve_ret, c.now, seconds_ms(s.night_off_s));
  const bool off2 = off2_.update(c.soc > s.back_soc && c.load < s.back_w, c.now, seconds_ms(s.back_s));
  if (!s.rule_night || !c.time_ok) r &= ~R_NIGHT;
  else if (on) r |= R_NIGHT;
  else if (off1 || off2) r &= ~R_NIGHT;
}

void OvernightRule::update(const RuleCtx &c, uint8_t &r) {
  const Settings &s = c.s;
  const float target = std::max(s.ovn_floor, c.reserve_sw);
  const bool known = !std::isnan(c.soc_at_sun);
  const bool on = on_.update(c.night && known && c.soc_at_sun < target, c.now, 5 * 60000);
  const bool off = off_.update(known && c.soc_at_sun > target + s.ovn_margin, c.now, 5 * 60000);
  if (!s.rule_ovn || !c.time_ok || !known) r &= ~R_OVN;
  else if (on) r |= R_OVN;
  else if (off || c.sun_useful) r &= ~R_OVN;
}

}  // namespace autopilot_core
