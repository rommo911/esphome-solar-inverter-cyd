#include "solar_autopilot.h"

#include "esphome/core/helpers.h"
#include "esphome/core/log.h"

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

  if (this->grid_ != nullptr) {
    this->grid_->add_on_state_callback([this](bool state) {
      if (!this->grid_seen_) {   // first reading after boot: no sound
        this->grid_seen_ = true;
        return;
      }
      autopilot_core::Actions a;
      this->ctl_.grid_changed(state, this->clock_(), this->inputs_(), a);
      this->run_(a);
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
  }
  in.output_priority = st(this->out_rb_);
  in.charger_source = st(this->chg_rb_);
  in.charge_current = st(this->cur_rb_);
  in.float_voltage = st(this->float_rb_);
  in.solar_today_kwh = st(this->solar_today_);
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
  auto set = [](select::Select *sel, const std::string &opt) {
    if (sel != nullptr) sel->make_call().set_option(opt).perform();
  };
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
        set(this->sel_out_, OUT[a.code % 3]);
        break;
      case ActionType::SET_CHARGER_SOURCE:
        set(this->sel_chg_, CHG[a.code % 4]);
        break;
      case ActionType::SET_CHARGE_CURRENT:
        set(this->sel_cur_, std::to_string((int) a.value));
        break;
      case ActionType::SET_FLOAT_VOLTAGE:
        set(this->sel_float_, str_sprintf("%.1f", a.value));
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
  const bool bin[OUT_BINARY_COUNT] = {link, st.cloudy, st.charging, st.fault};
  for (uint8_t i = 0; i < OUT_BINARY_COUNT; i++)
    if (this->out_binaries_[i] != nullptr) this->out_binaries_[i]->publish_state(bin[i]);
#ifdef USE_TEXT_SENSOR
  if (this->state_text_ != nullptr) {
    char buf[96];
    autopilot_core::describe(st, s, link, buf, sizeof buf);
    if (!this->state_text_->has_state() || this->state_text_->state != buf) this->state_text_->publish_state(buf);
  }
#endif
  if (!minute) return;
  const float soc = link ? in.soc : NAN;
  const float val[OUT_SENSOR_COUNT] = {
      st.reserve_sw, st.reserve_ret, st.plan_fc, st.soc_at_sun, st.base_load,
      autopilot_core::battery_remaining_kwh(soc, s), autopilot_core::battery_runtime_h(soc, st.base_load, s)};
  for (uint8_t i = 0; i < OUT_SENSOR_COUNT; i++)
    if (this->out_sensors_[i] != nullptr) this->out_sensors_[i]->publish_state(val[i]);
}

void SolarAutopilot::save_() {
  const autopilot_core::Persist p = this->ctl_.persist();
  if (p == this->saved_) return;
  this->saved_ = p;
  this->pref_.save(&p);   // written to flash at the preferences' flash_write_interval
}

}  // namespace solar_autopilot
}  // namespace esphome
