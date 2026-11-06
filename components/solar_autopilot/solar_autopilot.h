// ESPHome adapter for the solar autopilot core: entities in, selects and triggers out.
#pragma once

#include "esphome/core/automation.h"
#include "esphome/core/component.h"
#include "esphome/core/defines.h"
#include "esphome/core/preferences.h"
#include "esphome/components/binary_sensor/binary_sensor.h"
#include "esphome/components/number/number.h"
#include "esphome/components/select/select.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/components/sun/sun.h"
#include "esphome/components/switch/switch.h"
#include "esphome/components/time/real_time_clock.h"
#ifdef USE_TEXT_SENSOR
#include "esphome/components/text_sensor/text_sensor.h"
#endif
#ifdef USE_SOLAR_AUTOPILOT_FORECAST
#include "esphome/components/http_request/http_request.h"
#endif
#ifdef USE_SOLAR_AUTOPILOT_PIPSOLAR
#include "esphome/components/pipsolar/pipsolar.h"
#endif

#include <string>
#include <vector>

#include "autopilot.h"

namespace esphome {
namespace solar_autopilot {

class TuneTrigger;
class NotifyTrigger;

// entities the component publishes (sensor.py / binary_sensor.py / text_sensor.py)
enum OutSensor : uint8_t {
  OUT_RESERVE_SWITCH, OUT_RESERVE_RETURN, OUT_FORECAST_USED, OUT_SOC_AT_SUN, OUT_BASE_LOAD,
  OUT_BATTERY_REMAINING, OUT_BATTERY_RUNTIME, OUT_FORECAST_TODAY, OUT_FORECAST_TOMORROW, OUT_FORECAST_NOW,
  OUT_SENSOR_COUNT
};
enum OutBinary : uint8_t { OUT_LINK, OUT_CLOUDY, OUT_CHARGING, OUT_FAULT, OUT_GRID, OUT_BINARY_COUNT };

class SolarAutopilot : public Component {
 public:
  void setup() override;
  void loop() override;
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
  void set_grid_voltage(sensor::Sensor *s, float min_v) {
    grid_v_ = s;
    grid_min_v_ = min_v;
  }
#ifdef USE_SOLAR_AUTOPILOT_PIPSOLAR
  void set_pipsolar(pipsolar::Pipsolar *p) { pipsolar_ = p; }
#endif
  void set_floating(binary_sensor::BinarySensor *b) { floating_ = b; }
  void set_forecast_today(TemplatableValue<float> v) { fc_today_ = v; }
  void set_forecast_tomorrow(TemplatableValue<float> v) { fc_tomorrow_ = v; }
  void set_output_priority(select::Select *s) { sel_out_ = s; }
  void set_charger_source(select::Select *s) { sel_chg_ = s; }
  void set_charge_current(select::Select *s) { sel_cur_ = s; }
  void set_float_voltage(select::Select *s) { sel_float_ = s; }
#ifdef USE_SOLAR_AUTOPILOT_FORECAST
  void set_forecast(http_request::HttpRequestComponent *http, float latitude, float longitude) {
    http_ = http;
    forecast_.set_location(latitude, longitude);
  }
#endif
  void set_number(autopilot_core::NumberId id, number::Number *n) { numbers_[id] = n; }
  void set_switch(autopilot_core::SwitchId id, switch_::Switch *s) { switches_[id] = s; }
  void set_out_sensor(OutSensor k, sensor::Sensor *s) { out_sensors_[k] = s; }
  void set_out_binary(OutBinary k, binary_sensor::BinarySensor *b) { out_binaries_[k] = b; }
#ifdef USE_TEXT_SENSOR
  void set_state_text(text_sensor::TextSensor *t) { state_text_ = t; }
  void set_forecast_text(text_sensor::TextSensor *t) { forecast_text_ = t; }
#endif
  void add_tune_trigger(TuneTrigger *t) { tune_triggers_.push_back(t); }
  void add_notify_trigger(NotifyTrigger *t) { notify_triggers_.push_back(t); }

  // for lambdas: id(autopilot).status().reserve_sw, id(autopilot).link() ...
  void mark_data() { last_data_ms_ = millis(); }   // every inverter reply (automatic: the SOC sensor's raw values)
  uint32_t last_data_ms() const { return last_data_ms_; }
  bool link() { return autopilot_core::Controller::link(this->clock_(), this->inputs_()); }
  bool sound_allowed(bool critical) { return autopilot_core::sound_allowed(this->settings_(), this->clock_(), critical); }
  autopilot_core::Status status() const { return ctl_.status(); }
  autopilot_core::Settings settings() { return this->settings_(); }
  // forecast().today_kwh(), .tomorrow_kwh(), .power_at(minute), .status(), .last_reply_ms()
  const autopilot_core::Forecast &forecast() const { return forecast_; }

 protected:
  autopilot_core::Clock clock_();
  autopilot_core::Inputs inputs_();
  autopilot_core::Settings settings_();
  void run_(const autopilot_core::Actions &acts);
  void save_();
  void write_(select::Select *sel, const std::string &option, const char *command);
  void grid_event_(bool state);
  void publish_(bool minute);
#ifdef USE_SOLAR_AUTOPILOT_FORECAST
  void forecast_minute_();
  void fetch_(autopilot_core::Forecast::Kind kind);
  bool room_for_tls_();
  http_request::HttpRequestComponent *http_ = nullptr;
#endif
  autopilot_core::Forecast forecast_;

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
  sensor::Sensor *grid_v_ = nullptr;   // grid from its voltage, debounced here (when no grid binary sensor)
  float grid_min_v_ = 150;
  autopilot_core::GridDebounce grid_debounce_;
#ifdef USE_SOLAR_AUTOPILOT_PIPSOLAR
  pipsolar::Pipsolar *pipsolar_ = nullptr;   // writes go straight to the inverter (no selects needed)
#endif
  TemplatableValue<float> fc_today_, fc_tomorrow_;
  select::Select *sel_out_ = nullptr, *sel_chg_ = nullptr, *sel_cur_ = nullptr, *sel_float_ = nullptr;
  number::Number *numbers_[autopilot_core::NUMBER_COUNT] = {};
  switch_::Switch *switches_[autopilot_core::SWITCH_COUNT] = {};
  sensor::Sensor *out_sensors_[OUT_SENSOR_COUNT] = {};
  binary_sensor::BinarySensor *out_binaries_[OUT_BINARY_COUNT] = {};
#ifdef USE_TEXT_SENSOR
  text_sensor::TextSensor *state_text_ = nullptr, *forecast_text_ = nullptr;
#endif
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
