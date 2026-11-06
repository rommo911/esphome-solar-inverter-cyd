#include "ap_alarms.h"

namespace autopilot_core {

void AlarmManager::runtime(uint32_t now, bool link, const Inputs &in, const Settings &s, float base_load, float mean5,
                           float soc_at_sun, Actions &out) {
  const bool no_grid = in.grid_known && !in.grid;
  if (!link || !no_grid) {
    rt_base_.since = rt_now_.since = morning_.since = 0;
    return;
  }
  const float usable = std::max(0.0f, s.batt_kwh * 10.0f * (in.soc - s.empty_soc));
  const float rt_base = usable / base_load;
  const float rt_now = std::isnan(mean5) ? NAN : usable / std::max(mean5, 50.0f);
  const bool b = rt_base_.update(rt_base < 2.0f, now, 120000);
  const bool n = rt_now_.update(!std::isnan(rt_now) && rt_now < 0.5f, now, 300000);
  if ((b || n) && (last_rt_ == 0 || now - last_rt_ >= 1800000)) {
    last_rt_ = now;
    // hours + minutes: no decimal point, which the screen would wrap at
    const float h = std::min(rt_base, std::isnan(rt_now) ? rt_base : rt_now);
    out.text(ActionType::NOTIFY, "No grid: battery lasts about %d h %02d min", (int) h, (int) ((h - (int) h) * 60));
    out.tune(Tune::ALARM_NO_GRID, 3, true);
  }
  if (morning_.update(!std::isnan(soc_at_sun) && soc_at_sun < s.ovn_floor, now, 300000) &&
      (last_mw_ == 0 || now - last_mw_ >= 1800000)) {
    last_mw_ = now;
    out.text(ActionType::NOTIFY, "No grid: battery may run out before the sun is up");
    out.tune(Tune::WARN_MORNING, 3, true);
  }
}

void AlarmManager::low_soc(uint32_t now, const Inputs &in, const AlarmConfig &cfg, Actions &out) {
  const float soc = in.soc;
  const bool fresh = now - in.last_data_ms < 120000;
  if (!in.grid_known || in.grid || std::isnan(soc) || !fresh || soc >= cfg.alarm_soc) {
    if (soc >= cfg.alarm_soc + 5 || (in.grid_known && in.grid)) low_alarmed_ = false;
    return;
  }
  if (!low_alarmed_ || (soc < cfg.repeat_soc && now - last_low_ >= 600000)) {
    low_alarmed_ = true;
    last_low_ = now;
    out.tune(Tune::ALARM_NO_GRID, 3, true);
  }
}

void AlarmManager::grid_changed(bool grid, float soc, const AlarmConfig &cfg, Actions &out) {
  if (grid) {
    out.tune(Tune::GRID_BACK, 1, false);
    return;
  }
  const bool low = !std::isnan(soc) && soc < cfg.alarm_soc;
  low_alarmed_ = low;
  out.tune(low ? Tune::ALARM_NO_GRID : Tune::GRID_LOST, low ? 3 : 2, low);
}

}  // namespace autopilot_core
