// ESPHome adapter for the solar autopilot core: entities in, selects and triggers out.
#pragma once

#include "esphome/core/automation.h"
#include "esphome/core/component.h"
#include "esphome/core/preferences.h"
#include "esphome/components/binary_sensor/binary_sensor.h"
#include "esphome/components/number/number.h"
#include "esphome/components/select/select.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/components/sun/sun.h"
#include "esphome/components/switch/switch.h"
#include "esphome/components/time/real_time_clock.h"

#include <string>
#include <vector>

#include "autopilot.h"

namespace esphome {
namespace solar_autopilot {

class TuneTrigger;
class NotifyTrigger;

class SolarAutopilot : public Component {
 public:
  void setup() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::DATA; }

  // configuration (from __init__.py)
  void set_time(time::RealTimeClock *t) { time_ = t; }
  void set_sun(sun::Sun *s) { sun_ = s; }
  void set_alarm_config(float alarm_soc, float repeat_soc) { cfg_ = {alarm_soc, repeat_soc}; }
  void set_soc(sensor::Sensor *s) { soc_ = s; }
  void set_load(sensor::Sensor *s) { load_ = s; }
  void set_pv(sensor::Sensor *s) { pv_ = s; }
  void set_output_priority_state(sensor::Sensor *s) { out_rb_ = s; }
  void set_charger_source_state(sensor::Sensor *s) { chg_rb_ = s; }
  void set_charge_current_state(sensor::Sensor *s) { cur_rb_ = s; }
  void set_float_voltage_state(sensor::Sensor *s) { float_rb_ = s; }
  void set_solar_today(sensor::Sensor *s) { solar_today_ = s; }
  void set_grid(binary_sensor::BinarySensor *b) { grid_ = b; }
  void set_floating(binary_sensor::BinarySensor *b) { floating_ = b; }
  void set_forecast_today(TemplatableValue<float> v) { fc_today_ = v; }
  void set_forecast_tomorrow(TemplatableValue<float> v) { fc_tomorrow_ = v; }
  void set_output_priority(select::Select *s) { sel_out_ = s; }
  void set_charger_source(select::Select *s) { sel_chg_ = s; }
  void set_charge_current(select::Select *s) { sel_cur_ = s; }
  void set_float_voltage(select::Select *s) { sel_float_ = s; }
  void set_number(autopilot_core::NumberId id, number::Number *n) { numbers_[id] = n; }
  void set_switch(autopilot_core::SwitchId id, switch_::Switch *s) { switches_[id] = s; }
  void add_tune_trigger(TuneTrigger *t) { tune_triggers_.push_back(t); }
  void add_notify_trigger(NotifyTrigger *t) { notify_triggers_.push_back(t); }

  // for lambdas: id(autopilot).status().reserve_sw, id(autopilot).link() ...
  void mark_data() { last_data_ms_ = millis(); }   // call on every inverter reply
  uint32_t last_data_ms() const { return last_data_ms_; }
  bool link() { return autopilot_core::Controller::link(this->clock_(), this->inputs_()); }
  bool sound_allowed(bool critical) { return autopilot_core::sound_allowed(this->settings_(), this->clock_(), critical); }
  autopilot_core::Status status() const { return ctl_.status(); }
  autopilot_core::Settings settings() { return this->settings_(); }

 protected:
  autopilot_core::Clock clock_();
  autopilot_core::Inputs inputs_();
  autopilot_core::Settings settings_();
  void run_(const autopilot_core::Actions &acts);
  void save_();

  autopilot_core::Controller ctl_;
  autopilot_core::AlarmConfig cfg_;
  uint32_t last_data_ms_ = 0;
  ESPPreferenceObject pref_;
  autopilot_core::Persist saved_;
  bool grid_seen_ = false, floating_prev_ = false;

  time::RealTimeClock *time_ = nullptr;
  sun::Sun *sun_ = nullptr;
  sensor::Sensor *soc_ = nullptr, *load_ = nullptr, *pv_ = nullptr, *out_rb_ = nullptr, *chg_rb_ = nullptr,
                 *cur_rb_ = nullptr, *float_rb_ = nullptr, *solar_today_ = nullptr;
  binary_sensor::BinarySensor *grid_ = nullptr, *floating_ = nullptr;
  TemplatableValue<float> fc_today_, fc_tomorrow_;
  select::Select *sel_out_ = nullptr, *sel_chg_ = nullptr, *sel_cur_ = nullptr, *sel_float_ = nullptr;
  number::Number *numbers_[autopilot_core::NUMBER_COUNT] = {};
  switch_::Switch *switches_[autopilot_core::SWITCH_COUNT] = {};
  std::vector<TuneTrigger *> tune_triggers_;
  std::vector<NotifyTrigger *> notify_triggers_;
};

class TuneTrigger : public Trigger<std::string, int, bool> {
 public:
  explicit TuneTrigger(SolarAutopilot *parent) { parent->add_tune_trigger(this); }
};

class NotifyTrigger : public Trigger<std::string> {
 public:
  explicit NotifyTrigger(SolarAutopilot *parent) { parent->add_notify_trigger(this); }
};

}  // namespace solar_autopilot
}  // namespace esphome
