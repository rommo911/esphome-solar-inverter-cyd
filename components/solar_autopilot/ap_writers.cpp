#include "ap_writers.h"

namespace autopilot_core {

void ChargerManager::update(const RuleCtx &c, bool grid, bool cloudy, uint8_t &r) {
  const Settings &s = c.s;
  const float emerg_t = s.emerg_target;
  const float chg_t = cloudy ? std::max(s.chg_target, emerg_t) : emerg_t;
  const bool start = start_.update(grid && ((cloudy && c.soc < s.chg_target - s.chg_margin) || c.soc < s.emerg_soc),
                                   c.now, seconds_ms(s.low_delay));
  const bool stop = !grid || c.soc >= chg_t;
  if (!s.rule_charge) charging = false;
  else charging = start || (charging && !stop);
  if (charging && grid && c.soc < chg_t) r |= R_CHG;
  else r &= ~R_CHG;
}

bool OutputArbiter::update(const WriteCtx &c, uint8_t r, bool &fault, Actions &out) {
  const uint32_t now = c.now;
  const bool want = r != 0;
  const float rb = c.in.output_priority;
  const bool is_sub = rb == 1.0f, is_sbu = rb == 2.0f;
  if (!is_sub) sub_since_ = 0;
  else if (sub_since_ == 0) sub_since_ = std::max<uint32_t>(now, 1);
  const bool min_ok = !is_sub || now - sub_since_ >= (uint32_t) (c.s.min_sub * 60000.0f);
  const bool bad = want ? !is_sub : !is_sbu;
  if (!c.active || !bad) {
    tries_ = 0;
  } else if (want || min_ok) {
    const uint32_t gap = tries_ >= 2 ? 300000 : 30000;
    if (last_write_ == 0 || now - last_write_ >= gap) {
      if (tries_ == 2 && !fault) {
        fault = true;
        out.text(ActionType::NOTIFY, "Inverter did not accept the output priority");
        out.tune(Tune::ALARM_NO_GRID, 3, true);
      }
      if (want && is_sbu && c.grid && tries_ == 0 && (r & ~R_CHG))   // routine charging: no tune
        out.tune((r & R_LOW) ? Tune::TO_GRID_LOW : Tune::TO_GRID, (r & R_LOW) ? 2 : 1, false);
      if (want && (r & R_LOW) && tries_ == 0) out.text(ActionType::NOTIFY, "Battery low - switched to grid");
      out.set(ActionType::SET_OUTPUT_PRIORITY, want ? OUT_SUB : OUT_SBU);
      out.text(ActionType::LOG, "priority -> %s (reasons=0x%02X soc=%.0f load=%.0f reserve %.0f/%.0f try %u)",
               want ? "SUB" : "SBU", r, c.soc, c.load, c.reserve_sw, c.reserve_ret, tries_ + 1u);
      last_write_ = now;
      if (tries_ < 2) tries_++;
    }
  }
  return bad;
}

bool ChargerWriter::update(const WriteCtx &c, bool charging, bool &fault, Actions &out) {
  if (!c.s.rule_charge) return false;
  const uint32_t now = c.now;
  const float src_v = charging ? 2.0f : 3.0f;   // 2 = solar and utility, 3 = solar only
  const float want_a = (charging && c.soc < c.s.fast_below) ? c.s.chg_fast_a : c.s.chg_norm_a;
  static const int OPTS[] = {2, 10, 20, 30, 40, 50, 60};   // the inverter's AC current steps
  int best = 0;
  for (int i = 1; i < 7; i++)
    if (fabsf(OPTS[i] - want_a) < fabsf(OPTS[best] - want_a)) best = i;
  const bool src_bad = c.in.charger_source != src_v;
  const float cur = c.in.charge_current;
  const bool cur_bad = std::isnan(cur) || (int) cur != OPTS[best];
  const bool bad = src_bad || cur_bad;
  if (!c.active || !bad) {
    tries_ = 0;
  } else if (last_write_ == 0 || now - last_write_ >= (tries_ >= 2 ? 300000u : 30000u)) {
    if (tries_ == 2 && !fault) {
      fault = true;
      out.text(ActionType::NOTIFY, "Inverter did not accept the charger setting");
    }
    if (src_bad) out.set(ActionType::SET_CHARGER_SOURCE, charging ? CHG_SOLAR_AND_UTILITY : CHG_SOLAR_ONLY);
    else out.set(ActionType::SET_CHARGE_CURRENT, 0, (float) OPTS[best]);
    out.text(ActionType::LOG, "charger -> %s %d A (soc=%.0f)", charging ? "solar+utility" : "solar only", OPTS[best],
             c.soc);
    last_write_ = now;
    if (tries_ < 2) tries_++;
  }
  return bad;
}

}  // namespace autopilot_core
