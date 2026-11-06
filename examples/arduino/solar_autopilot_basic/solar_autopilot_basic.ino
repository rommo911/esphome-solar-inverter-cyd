// Solar autopilot core on Arduino (ESP32). The inverter link is yours to provide:
// read_inverter() fills the readings, write_*() send the commands (PI30 over RS232).
// platformio.ini:  lib_deps = https://github.com/rommo911/esphome-solar-inverter-cyd.git
//                  (or copy components/solar_autopilot/ into lib/)
#include <Arduino.h>
#include <Preferences.h>
#include <WiFi.h>
#include <time.h>

#include "autopilot.h"

using namespace autopilot_core;

static Controller ctl;
static Settings settings;          // defaults; keep your own copy in Preferences / NVS
static Inputs in;
static Preferences prefs;

// ---- your inverter link (PI30): fill these in
static bool read_inverter(Inputs &in, float &grid_v) { (void) in; (void) grid_v; return false; }   // true = reply
static void write_output_priority(uint8_t v) { (void) v; }           // POP0x
static void write_charger_source(uint8_t v) { (void) v; }            // PCP0x
static void write_charge_current(int a) { (void) a; }                // MUCHGC0xxx
static void write_float_voltage(float v) { (void) v; }               // PBFT
// ---- your sun elevation (degrees) for the place, e.g. from a small solar-position routine
static double sun_elevation(time_t utc) { (void) utc; return NAN; }

static Clock make_clock() {
  Clock c;
  c.ms = millis();
  time_t now = time(nullptr);
  c.valid = now > 1700000000;      // SNTP synced
  if (c.valid) {
    struct tm lt;
    localtime_r(&now, &lt);
    c.epoch = (uint32_t) now;
    c.hour = lt.tm_hour;
    c.minute = lt.tm_min;
    c.sun_elevation = sun_elevation(now);
  }
  return c;
}

static void perform(const Actions &acts) {
  for (const Action &a : acts) {
    switch (a.type) {
      case ActionType::SET_OUTPUT_PRIORITY: write_output_priority(a.code); break;
      case ActionType::SET_CHARGER_SOURCE: write_charger_source(a.code); break;
      case ActionType::SET_CHARGE_CURRENT: write_charge_current((int) a.value); break;
      case ActionType::SET_FLOAT_VOLTAGE: write_float_voltage(a.value); break;
      case ActionType::TUNE:
        if (sound_allowed(settings, make_clock(), a.critical)) Serial.printf("sound %s\n", tune_name((Tune) a.code));
        break;
      case ActionType::NOTIFY:
      case ActionType::LOG: Serial.println(a.text); break;
    }
  }
}

static void save_persist() {
  static Persist last;
  const Persist p = ctl.persist();
  if (p != last) {
    prefs.putBytes("persist", &p, sizeof p);
    last = p;
  }
}

static GridDebounce grid;

void setup() {
  Serial.begin(115200);
  prefs.begin("autopilot");
  Persist p;
  if (prefs.getBytes("persist", &p, sizeof p) == sizeof p) ctl.restore(p);
  configTzTime("<+03>-3", "pool.ntp.org", "time.google.com");
  ctl.begin(millis());
}

void loop() {
  static uint32_t last_ctl = 0, last_min = 0;
  const uint32_t now = millis();
  static float grid_v = NAN;
  if (read_inverter(in, grid_v)) in.last_data_ms = now;
  // grid present: debounced 30 s, as on the CYD
  bool first = false;
  if (grid.update(!std::isnan(grid_v) && grid_v > 150, now, &first)) {
    in.grid_known = true;
    in.grid = grid.state();
    if (!first) {
      Actions a;
      ctl.grid_changed(in.grid, make_clock(), in, a);
      perform(a);
    }
  }
  if (now - last_ctl >= 2000) {
    last_ctl = now;
    Actions a;
    ctl.control(make_clock(), in, settings, a);
    perform(a);
    save_persist();
  }
  if (now - last_min >= 60000) {
    last_min = now;
    Actions a;
    ctl.minute(make_clock(), in, settings, a);
    perform(a);
  }
}
