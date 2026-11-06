#include "ap_planner.h"

namespace autopilot_core {

void SunTracker::update(const Clock &c) {
  if (!c.valid) return;
  const float el = c.sun_elevation;
  if (!std::isnan(prev_el_) && prev_el_ < -0.833f && el >= -0.833f) sunrise_ts = c.epoch;
  prev_el_ = el;
}

void ReservePlanner::update(const Clock &c, const Inputs &in, const Settings &s, float solar_yesterday_kwh) {
  float fc = (c.valid && c.hour >= 12) ? in.forecast_tomorrow_kwh : in.forecast_today_kwh;
  if (std::isnan(fc))   // no internet: persistence (today so far after 15:00, else yesterday)
    fc = (c.valid && c.hour >= 15) ? in.solar_today_kwh : solar_yesterday_kwh;
  const bool cl = std::isnan(fc) || fc < s.cloudy_kwh;
  plan_fc = fc;
  cloudy = cl;
  const float sw = std::clamp(cl ? s.cloudy_sw : s.sunny_sw, 16.0f, 37.0f);
  const float ret = std::min(std::max({cl ? s.cloudy_ret : s.sunny_ret, sw + 3.0f, 25.0f}), 40.0f);
  reserve_sw = sw;
  reserve_ret = ret;
}

SunPrediction predict_soc_at_sun(const Clock &c, float soc, float pv, float base_load, bool cloudy,
                                 uint32_t sunrise_ts, const Settings &s) {
  const bool time_ok = c.valid;
  const bool night = is_night(c);
  const float delay_h = cloudy ? s.sun_delay_cloudy : s.sun_delay_sunny;
  const bool rise_known = time_ok && sunrise_ts != 0 && c.epoch >= sunrise_ts && c.epoch - sunrise_ts < 2 * 86400;
  SunPrediction p;
  float hrs = NAN;
  if (time_ok && !night) {
    const float since_h = rise_known ? (c.epoch - sunrise_ts) / 3600.0f : 99.0f;
    p.sun_useful = (!std::isnan(pv) && pv >= base_load) || since_h > delay_h;
    hrs = p.sun_useful ? 0.0f : std::max(delay_h - since_h, 0.0f);
  } else if (night && rise_known) {
    uint32_t next = sunrise_ts;
    while (next <= c.epoch) next += 86400;   // same time tomorrow (+-2 min)
    hrs = (next - c.epoch) / 3600.0f + delay_h;
  }
  p.soc_at_sun = std::isnan(hrs) ? NAN : soc - base_load * hrs / (s.batt_kwh * 10.0f);
  return p;
}

}  // namespace autopilot_core
