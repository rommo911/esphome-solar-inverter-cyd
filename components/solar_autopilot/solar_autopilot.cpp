#include "solar_autopilot.h"

#include "esphome/core/helpers.h"
#include "esphome/core/log.h"
#ifdef USE_WIFI
#include "esphome/components/wifi/wifi_component.h"
#endif
#ifdef USE_ESP32
#include <esp_heap_caps.h>
#endif

namespace esphome {
namespace solar_autopilot {

static const char *const TAG = "ctl";

static float st(sensor::Sensor *s) { return s == nullptr ? NAN : s->state; }


void SolarAutopilot::setup() {
  this->pref_ = global_preferences->make_preference<autopilot_core::Persist>(0x5A7A0001u);
  autopilot_core::Persist p;
  if (this->pref_.load(&p)) this->ctl_.restore(p);
  this->saved_ = this->ctl_.persist();
  this->ctl_.configure(this->cfg_);
  this->ctl_.begin(millis());

  if (this->soc_ != nullptr) {   // every inverter reply refreshes the link (raw = before filters)
    this->soc_->add_on_raw_state_callback([this](float x) {
      if (!std::isnan(x)) this->mark_data();
    });
  }
  if (this->grid_ != nullptr) {
    this->grid_->add_on_state_callback([this](bool state) {
      if (!this->grid_seen_) {   // first reading after boot: no sound
        this->grid_seen_ = true;
        return;
      }
      this->grid_event_(state);
    });
  }
  if (this->floating_ != nullptr) {
    this->floating_->add_on_state_callback([this](bool state) {
      const bool entered = state && !this->floating_prev_;
      this->floating_prev_ = state;
      if (!entered) return;
      autopilot_core::Actions a;
      this->ctl_.float_entered(this->inputs_(), this->settings_(), a);
      this->run_(a);
    });
  }
  this->set_interval("control", 2000, [this]() {
    autopilot_core::Actions a;
    this->ctl_.control(this->clock_(), this->inputs_(), this->settings_(), a);
    this->run_(a);
    this->save_();
    this->publish_(false);
  });
  this->set_interval("minute", 60000, [this]() {
    autopilot_core::Actions a;
#ifdef USE_SOLAR_AUTOPILOT_FORECAST
    this->forecast_minute_();
#endif
    this->ctl_.minute(this->clock_(), this->inputs_(), this->settings_(), a);
    this->run_(a);
    this->save_();
    this->publish_(true);
  });
}

void SolarAutopilot::dump_config() {
  ESP_LOGCONFIG(TAG, "Solar autopilot:");
  ESP_LOGCONFIG(TAG, "  alarm below %.0f %%, repeat below %.0f %%", this->cfg_.alarm_soc, this->cfg_.repeat_soc);
  int n = 0, s = 0;
  for (auto *x : this->numbers_) n += x != nullptr;
  for (auto *x : this->switches_) s += x != nullptr;
  ESP_LOGCONFIG(TAG, "  settings bound: %d/%d numbers, %d/%d switches (others use defaults)", n,
                (int) autopilot_core::NUMBER_COUNT, s, (int) autopilot_core::SWITCH_COUNT);
}

// grid from its voltage: changes count after 30 s (like delayed_on / delayed_off)
void SolarAutopilot::loop() {
  if (this->grid_ != nullptr || this->grid_v_ == nullptr) return;
  const float v = this->grid_v_->state;
  bool first = false;
  if (!this->grid_debounce_.update(!std::isnan(v) && v > this->grid_min_v_, millis(), &first)) return;
  if (this->out_binaries_[OUT_GRID] != nullptr) this->out_binaries_[OUT_GRID]->publish_state(this->grid_debounce_.state());
  if (!first) this->grid_event_(this->grid_debounce_.state());   // first reading after boot: no sound
}

void SolarAutopilot::grid_event_(bool state) {
  autopilot_core::Actions a;
  this->ctl_.grid_changed(state, this->clock_(), this->inputs_(), a);
  this->run_(a);
}

autopilot_core::Clock SolarAutopilot::clock_() {
  autopilot_core::Clock c;
  c.ms = millis();
  if (this->time_ == nullptr) return c;
  const ESPTime t = this->time_->now();
  c.valid = t.is_valid();
  if (c.valid) {
    c.epoch = (uint32_t) t.timestamp;
    c.hour = t.hour;
    c.minute = t.minute;
    c.sun_elevation = this->sun_ != nullptr ? this->sun_->elevation() : NAN;
  }
  return c;
}

autopilot_core::Inputs SolarAutopilot::inputs_() {
  autopilot_core::Inputs in;
  in.soc = st(this->soc_);
  in.load_w = st(this->load_);
  in.pv_w = st(this->pv_);
  in.last_data_ms = this->last_data_ms_;
  if (this->grid_ != nullptr) {
    in.grid_known = this->grid_->has_state();
    in.grid = this->grid_->state;
  } else {
    in.grid_known = this->grid_debounce_.known();
    in.grid = this->grid_debounce_.state();
  }
  in.output_priority = st(this->out_rb_);
  in.charger_source = st(this->chg_rb_);
  in.charge_current = st(this->cur_rb_);
  in.float_voltage = st(this->float_rb_);
  in.solar_today_kwh = st(this->solar_today_);
#ifdef USE_SOLAR_AUTOPILOT_FORECAST
  in.forecast_today_kwh = this->forecast_.today_kwh();
  in.forecast_tomorrow_kwh = this->forecast_.tomorrow_kwh();
#endif
  if (this->fc_today_.has_value()) in.forecast_today_kwh = this->fc_today_.value();
  if (this->fc_tomorrow_.has_value()) in.forecast_tomorrow_kwh = this->fc_tomorrow_.value();
  return in;
}

autopilot_core::Settings SolarAutopilot::settings_() {
  autopilot_core::Settings s;   // defaults for anything not bound
  for (uint8_t i = 0; i < autopilot_core::NUMBER_COUNT; i++) {
    number::Number *n = this->numbers_[i];
    if (n != nullptr && n->has_state() && !std::isnan(n->state))
      *autopilot_core::number_ptr(s, (autopilot_core::NumberId) i) = n->state;
  }
  for (uint8_t i = 0; i < autopilot_core::SWITCH_COUNT; i++) {
    switch_::Switch *w = this->switches_[i];
    if (w != nullptr) *autopilot_core::switch_ptr(s, (autopilot_core::SwitchId) i) = w->state;
  }
  return s;
}

void SolarAutopilot::run_(const autopilot_core::Actions &acts) {
  using autopilot_core::ActionType;
  static const char *const OUT[] = {"Utility first (USB)", "Solar first (SUB)", "Battery first (SBU)"};
  static const char *const CHG[] = {"Utility first", "Solar first", "Solar and utility", "Solar only"};
  for (const auto &a : acts) {
    switch (a.type) {
      case ActionType::NOTIFY:
        for (auto *t : this->notify_triggers_) t->trigger(std::string(a.text));
        break;
      case ActionType::TUNE:
        for (auto *t : this->tune_triggers_)
          t->trigger(std::string(autopilot_core::tune_name((autopilot_core::Tune) a.code)), (int) a.prio, a.critical);
        break;
      case ActionType::SET_OUTPUT_PRIORITY:
        this->write_(this->sel_out_, OUT[a.code % 3], str_sprintf("POP%02d", a.code % 3).c_str());
        break;
      case ActionType::SET_CHARGER_SOURCE:
        this->write_(this->sel_chg_, CHG[a.code % 4], str_sprintf("PCP%02d", a.code % 4).c_str());
        break;
      case ActionType::SET_CHARGE_CURRENT:
        this->write_(this->sel_cur_, std::to_string((int) a.value), str_sprintf("MUCHGC0%02.0f", a.value).c_str());
        break;
      case ActionType::SET_FLOAT_VOLTAGE:
        this->write_(this->sel_float_, str_sprintf("%.1f", a.value), str_sprintf("PBFT%02.1f", a.value).c_str());
        break;
      case ActionType::LOG:
        ESP_LOGW(TAG, "%s", a.text);
        break;
    }
  }
  if (acts.dropped() != 0) ESP_LOGE(TAG, "%u actions dropped (queue full)", (unsigned) acts.dropped());
}

// binary sensors and the state text every 2 s (published on change), values once a minute
void SolarAutopilot::publish_(bool minute) {
  const autopilot_core::Status st = this->ctl_.status();
  const autopilot_core::Inputs in = this->inputs_();
  const autopilot_core::Settings s = this->settings_();
  const bool link = autopilot_core::Controller::link(this->clock_(), in);
  const bool bin[OUT_GRID] = {link, st.cloudy, st.charging, st.fault};   // grid: published by loop()
  for (uint8_t i = 0; i < OUT_GRID; i++)
    if (this->out_binaries_[i] != nullptr) this->out_binaries_[i]->publish_state(bin[i]);
#ifdef USE_TEXT_SENSOR
  if (this->state_text_ != nullptr) {
    char buf[96];
    autopilot_core::describe(st, s, link, buf, sizeof buf);
    if (!this->state_text_->has_state() || this->state_text_->state != buf) this->state_text_->publish_state(buf);
  }
  if (this->forecast_text_ != nullptr &&
      (!this->forecast_text_->has_state() || this->forecast_text_->state != this->forecast_.detail()))
    this->forecast_text_->publish_state(this->forecast_.detail());
#endif
  if (!minute) return;
  const float soc = link ? in.soc : NAN;
  const autopilot_core::Clock c = this->clock_();
  const float val[OUT_SENSOR_COUNT] = {
      st.reserve_sw, st.reserve_ret, st.plan_fc, st.soc_at_sun, st.base_load,
      autopilot_core::battery_remaining_kwh(soc, s), autopilot_core::battery_runtime_h(soc, st.base_load, s),
      in.forecast_today_kwh, in.forecast_tomorrow_kwh,
      c.valid ? this->forecast_.power_at(c.hour * 60 + c.minute) : NAN};
  for (uint8_t i = 0; i < OUT_SENSOR_COUNT; i++)
    if (this->out_sensors_[i] != nullptr) this->out_sensors_[i]->publish_state(val[i]);
}

#ifdef USE_SOLAR_AUTOPILOT_FORECAST
// Forecast.Solar: day totals, then 2 s later today's power curve. The GET blocks the loop for a
// few seconds (TLS handshake), as the http_request action does.
void SolarAutopilot::forecast_minute_() {
  const autopilot_core::Clock c = this->clock_();
  this->forecast_.tick(c);
  bool wifi_ok = true;
#ifdef USE_WIFI
  wifi_ok = wifi::global_wifi_component->is_connected();
#endif
  if (!this->forecast_.due(c.ms, this->settings_(), wifi_ok, c.valid)) return;
  this->forecast_.fetch_started(c.ms);
  this->fetch_(autopilot_core::Forecast::DAY_TOTALS);
  if (this->forecast_.ok())
    this->set_timeout("forecast_watts", 2000, [this]() { this->fetch_(autopilot_core::Forecast::WATTS); });
}

// HTTPS needs ~40 KB of heap for TLS on a board without PSRAM: skip rather than fail half-way.
bool SolarAutopilot::room_for_tls_() {
#ifdef USE_ESP32
  const size_t blk = heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
  const size_t fre = heap_caps_get_free_size(MALLOC_CAP_8BIT);
  if (blk < 24000 || fre < 45000) {
    char d[120];
    snprintf(d, sizeof d, "not enough memory for HTTPS (free %u B, largest block %u B; need 45000 / 24000)",
             (unsigned) fre, (unsigned) blk);
    this->forecast_.skipped("low memory", d);
    ESP_LOGW("fc", "%s", this->forecast_.detail());
    return false;
  }
#endif
  return true;
}

void SolarAutopilot::fetch_(autopilot_core::Forecast::Kind kind) {
  const bool day = kind == autopilot_core::Forecast::DAY_TOTALS;
  if (!this->room_for_tls_()) return;
  char url[160];
  this->forecast_.url(kind, this->settings_(), url, sizeof url);
#ifdef USE_ESP32
  ESP_LOGW("fc", "GET %s (free %u B, block %u B)", url, (unsigned) heap_caps_get_free_size(MALLOC_CAP_8BIT),
           (unsigned) heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
#else
  ESP_LOGW("fc", "GET %s", url);
#endif
  auto resp = this->http_->get(url);
  if (resp == nullptr) {
    if (day) this->forecast_.connect_failed("day totals");
    ESP_LOGW("fc", "%s: connection / TLS failed (see the http_request error above)", day ? "day totals" : "power curve");
    return;
  }
  // read the reply (day totals ~200 B, power curve ~2 KB; a cut-short reply still gives what came)
  const size_t max = day ? 1024 : 4096;
  std::string body(max, '\0');
  size_t n = 0;
  uint32_t last = millis();
  while (n < max) {
    const int r = resp->read(reinterpret_cast<uint8_t *>(&body[n]), max - n);
    const auto res = http_request::http_read_loop_result(r, last, 10000, resp->is_read_complete());
    if (res == http_request::HttpReadLoopResult::RETRY) continue;
    if (res != http_request::HttpReadLoopResult::DATA) break;
    n += r;
  }
  const int code = resp->status_code;
  resp->end();
  body.resize(n);
  ESPTime t = this->time_->now();
  if (!t.is_valid()) return;
  char today[11], tomorrow[11], hhmm[6];
  t.strftime(today, sizeof today, "%Y-%m-%d");
  ESPTime::from_epoch_local(t.timestamp + 86400).strftime(tomorrow, sizeof tomorrow, "%Y-%m-%d");
  t.strftime(hhmm, sizeof hhmm, "%H:%M");
  if (day) {
    this->forecast_.day_totals(code, body.c_str(), n, today, tomorrow, hhmm, millis());
    ESP_LOGW("fc", "%s", this->forecast_.detail());
  } else if (this->forecast_.watts(code, body.c_str(), n, today)) {
    ESP_LOGW("fc", "power curve: %u points for today", (unsigned) this->forecast_.points());
  } else {
    ESP_LOGW("fc", "%s", this->forecast_.detail());
  }
}
#endif

// A select if one is configured (its set_action does the write), else the PI30 command directly.
void SolarAutopilot::write_(select::Select *sel, const std::string &option, const char *command) {
  if (sel != nullptr) {
    sel->make_call().set_option(option).perform();
    return;
  }
#ifdef USE_SOLAR_AUTOPILOT_PIPSOLAR
  if (this->pipsolar_ != nullptr) {
    this->pipsolar_->queue_command(command);
    return;
  }
#endif
  ESP_LOGE(TAG, "no way to write %s: set pipsolar_id or a select", command);
}

void SolarAutopilot::save_() {
  const autopilot_core::Persist p = this->ctl_.persist();
  if (p == this->saved_) return;
  this->saved_ = p;
  this->pref_.save(&p);   // written to flash at the preferences' flash_write_interval
}

}  // namespace solar_autopilot
}  // namespace esphome
