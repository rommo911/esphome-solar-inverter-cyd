#include "ap_controller.h"

namespace autopilot_core {

void Controller::restore(const Persist &p) {
  reasons_ = p.reasons;
  planner_.cloudy = p.cloudy;
  planner_.reserve_sw = p.reserve_sw;
  planner_.reserve_ret = p.reserve_ret;
  charger_.charging = p.charging;
  solar_yesterday_ = p.solar_yesterday_kwh;
  sun_.sunrise_ts = p.sunrise_ts;
}

Persist Controller::persist() const {
  Persist p;
  p.reasons = reasons_;
  p.cloudy = planner_.cloudy;
  p.reserve_sw = planner_.reserve_sw;
  p.reserve_ret = planner_.reserve_ret;
  p.charging = charger_.charging;
  p.solar_yesterday_kwh = solar_yesterday_;
  p.sunrise_ts = sun_.sunrise_ts;
  return p;
}

Status Controller::status() const {
  Status st;
  st.reasons = reasons_;
  st.want_sub = want_sub_;
  st.fault = fault_;
  st.reserve_sw = planner_.reserve_sw;
  st.reserve_ret = planner_.reserve_ret;
  st.cloudy = planner_.cloudy;
  st.plan_fc = planner_.plan_fc;
  st.charging = charger_.charging;
  st.soc_at_sun = soc_at_sun_;
  st.base_load = load_.base();
  st.load_median = load_.median();
  st.load_mean5 = load_.mean5();
  st.sunrise_ts = sun_.sunrise_ts;
  st.solar_yesterday_kwh = solar_yesterday_;
  return st;
}

void Controller::control(const Clock &c, const Inputs &in, const Settings &s, Actions &out) {
  const uint32_t now = c.ms;
  if (now - boot_ms_ < 30000) return;   // let the inverter readings settle
  if (!link(c, in)) return;             // stale data: write nothing, keep latches
  const float soc = in.soc, load = in.load_w, pv = in.pv_w;
  load_.add(load);
  const bool grid = in.grid_known && in.grid;
  const bool time_ok = c.valid;         // no clock -> time-based rules pause
  const bool night = is_night(c);
  const float sw = planner_.reserve_sw, ret = planner_.reserve_ret;

  const SunPrediction p = predict_soc_at_sun(c, soc, pv, load_.base(), planner_.cloudy, sun_.sunrise_ts, s);
  soc_at_sun_ = p.soc_at_sun;

  const RuleCtx rc{now, soc, load, pv, night, time_ok, sw, ret, p.soc_at_sun, p.sun_useful, s};
  uint8_t r = reasons_;
  low_.update(rc, r);
  high_.update(rc, r);
  night_.update(rc, r);
  overnight_.update(rc, r);
  charger_.update(rc, grid, planner_.cloudy, r);
  reasons_ = r;
  want_sub_ = r != 0;

  const WriteCtx wc{now, s.auto_ctl && !s.observe, grid, soc, load, sw, ret, in, s};
  const bool out_bad = output_.update(wc, r, fault_, out);
  const bool chg_bad = charger_writer_.update(wc, charger_.charging, fault_, out);
  if (fault_ && !out_bad && !chg_bad) fault_ = false;
}

void Controller::minute(const Clock &c, const Inputs &in, const Settings &s, Actions &out) {
  // yesterday's measured solar (persistence forecast): the last value before the day changed
  if (c.valid) {
    if (prev_hour_ >= 0 && c.hour < prev_hour_ && !std::isnan(last_solar_)) solar_yesterday_ = last_solar_;
    if (!std::isnan(in.solar_today_kwh)) last_solar_ = in.solar_today_kwh;
    prev_hour_ = c.hour;
  }
  load_.minute(s.base_floor);
  sun_.update(c);
  planner_.update(c, in, s, solar_yesterday_);
  alarms_.runtime(c.ms, link(c, in), in, s, load_.base(), load_.mean5(), soc_at_sun_, out);
  alarms_.low_soc(c.ms, in, cfg_, out);
}

void Controller::grid_changed(bool grid, const Clock &c, const Inputs &in, Actions &out) {
  if (boot_ms_ == 0 || c.ms - boot_ms_ <= 90000) return;   // no sounds for the boot-time reading
  alarms_.grid_changed(grid, in.soc, cfg_, out);
}

void Controller::float_entered(const Inputs &in, const Settings &s, Actions &out) {
  if (s.rule_float && fabsf(in.float_voltage - s.float_v) > 0.05f)
    out.set(ActionType::SET_FLOAT_VOLTAGE, 0, s.float_v);
}

}  // namespace autopilot_core
