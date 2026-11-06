// Simulator for the CYD inverter controller (v2).
// The automation code is NOT re-written here: gen/lambdas.inc is extracted verbatim from
// inverter-cyd.yaml by extract.py. This file is only the world around it: time, sun, PV, house
// load, battery, grid, the Axpert's behaviour, and stand-ins for the ESPHome objects.
// Output: one JSON object per line (events + 1-minute samples) for check.py.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <functional>
#include <random>
#include <string>
#include <vector>

// ------------------------------------------------------------------ ESPHome stand-ins
static uint32_t SIM_MS = 0;
static double SIM_T0_MIN = 0;            // local clock at sim start, minutes after midnight
static bool TIME_VALID = true;
static const uint32_t EPOCH_DAY0 = 1793000000u - (1793000000u % 86400u);   // a local midnight
uint32_t millis() { return SIM_MS; }
static double clock_min() { return SIM_T0_MIN + SIM_MS / 60000.0; }       // can exceed 1440
#define id(x) x
static void emit(const char *fmt, ...) {
  va_list ap; va_start(ap, fmt);
  printf("{\"t\":%.1f,", SIM_MS / 1000.0); vprintf(fmt, ap); printf("}\n");
  va_end(ap);
}
static void logw(const char *tag, const char *fmt, ...) {
  char buf[300]; va_list ap; va_start(ap, fmt); vsnprintf(buf, sizeof buf, fmt, ap); va_end(ap);
  for (char *p = buf; *p; p++) if (*p == '"') *p = '\'';
  emit("\"ev\":\"log\",\"tag\":\"%s\",\"msg\":\"%s\"", tag, buf);
}
#define ESP_LOGW(tag, fmt, ...) logw(tag, fmt, ##__VA_ARGS__)
std::string str_sprintf(const char *fmt, ...) {
  char buf[300]; va_list ap; va_start(ap, fmt); vsnprintf(buf, sizeof buf, fmt, ap); va_end(ap);
  return buf;
}
using std::isnan;
using std::to_string;

struct Num { float state; };
struct Sw { bool state; };
struct Sensor { float state = NAN; bool has_state() const { return !std::isnan(state); } };
struct BinSensor { bool state = false; bool has = false; bool has_state() const { return has; } };
struct ESPTime {
  bool valid; int hour, minute; uint32_t timestamp;
  bool is_valid() const { return valid; }
};
struct Clock {
  ESPTime now() const {
    double cm = clock_min();
    int m = (int) fmod(cm, 1440.0);
    return {TIME_VALID, m / 60, m % 60, EPOCH_DAY0 + (uint32_t) (cm * 60)};
  }
} sntp_time;

// Sun at ~36 N, early November, local time UTC+3: sunrise 06:50, noon 12:15, sunset 17:40
static const double SUNRISE = 410, SUNSET = 1060, DAYLEN = SUNSET - SUNRISE;
struct Sun {
  double elevation() const {
    double m = fmod(clock_min(), 1440.0);
    if (m >= SUNRISE && m <= SUNSET) return 40.0 * sin(M_PI * (m - SUNRISE) / DAYLEN);
    double n = m > SUNSET ? m - SUNSET : m + 1440 - SUNSET;
    return -40.0 * sin(M_PI * n / (1440 - DAYLEN));
  }
} sun_c;

// selects: the controller writes here; the inverter applies them unless it is ignoring writes
static bool LINK_UP = true, INV_IGNORES = false;
struct Sel;
struct Call {
  Sel *s; std::string opt;
  Call &set_option(const std::string &o) { opt = o; return *this; }
  void perform();
};
struct Sel {
  const char *name; std::string inverter;          // what the inverter really has
  Call make_call() { return Call{this, ""}; }
};
void Call::perform() {
  emit("\"ev\":\"write\",\"sel\":\"%s\",\"opt\":\"%s\",\"link\":%s,\"taken\":%s", s->name, opt.c_str(),
       LINK_UP ? "true" : "false", (LINK_UP && !INV_IGNORES) ? "true" : "false");
  if (LINK_UP && !INV_IGNORES) s->inverter = opt;
}

struct Buzzer {
  uint32_t until = 0;
  bool is_playing() const { return SIM_MS < until; }
  void stop() { until = 0; }
  void play(const char *r) {
    until = SIM_MS + 2500;
    char name[32]; sscanf(r, "%31[^:]", name);
    emit("\"ev\":\"tune\",\"name\":\"%s\",\"hour\":%d", name, sntp_time.now().hour);
  }
} buzzer;

template <typename... A> struct Script {
  std::function<void(A...)> fn;
  void execute(A... a) { fn(a...); }
  bool is_running() const { return false; }
};

// ------------------------------------------------------------------ entities from the YAML
#include "gen/entities.inc"
Sensor s_soc, s_load_power, s_pv_power, s_grid_v, s_battery_float_voltage, s_output_source_priority,
    s_charger_source_priority, s_max_ac_charging_current, e_solar_today;
BinSensor bs_grid, inv_link;
Sel sel_output_source_priority{"output_priority", "Battery first (SBU)"};
Sel sel_charger_source_priority{"charger_source", "Solar first"};      // factory default
Sel sel_max_ac_charging_current{"ac_charge_current", "30"};
Sel sel_battery_float_voltage{"float_voltage", "27.0"};
Script<std::string, int, bool> play_tune;
Script<std::string> notify;

#ifdef USE_CORE
// The controller logic is the C++ core (components/solar_autopilot); this is its adapter,
// the same job the ESPHome component does on the device.
#include "ap/autopilot.h"
static float sim_fc_today = NAN, sim_fc_tomorrow = NAN;   // the forecast the world "fetched"
struct SimAutopilot {
  autopilot_core::Controller ctl;
  uint32_t last_data = 0;
  autopilot_core::Settings set;   // the component's settings: defaults (= the entities' defaults)
  autopilot_core::Settings settings() const { return set; }
  autopilot_core::Clock clock() const {
    autopilot_core::Clock c;
    const ESPTime t = sntp_time.now();
    c.ms = millis(); c.valid = t.is_valid();
    if (c.valid) { c.epoch = t.timestamp; c.hour = t.hour; c.minute = t.minute; c.sun_elevation = sun_c.elevation(); }
    return c;
  }
  autopilot_core::Inputs inputs() const {
    autopilot_core::Inputs in;
    in.soc = s_soc.state; in.load_w = s_load_power.state; in.pv_w = s_pv_power.state;
    in.last_data_ms = last_data;
    in.grid_known = bs_grid.has_state(); in.grid = bs_grid.state;
    in.output_priority = s_output_source_priority.state; in.charger_source = s_charger_source_priority.state;
    in.charge_current = s_max_ac_charging_current.state; in.float_voltage = s_battery_float_voltage.state;
    in.solar_today_kwh = e_solar_today.state;
    in.forecast_today_kwh = sim_fc_today; in.forecast_tomorrow_kwh = sim_fc_tomorrow;
    return in;
  }
  void run(const autopilot_core::Actions &acts);
  void control() { autopilot_core::Actions a; ctl.control(clock(), inputs(), settings(), a); run(a); }
  void minute() { autopilot_core::Actions a; ctl.minute(clock(), inputs(), settings(), a); run(a); }
  void grid_changed(bool g) { autopilot_core::Actions a; ctl.grid_changed(g, clock(), inputs(), a); run(a); }
  void float_entered() { autopilot_core::Actions a; ctl.float_entered(inputs(), settings(), a); run(a); }
  bool link() const { return autopilot_core::Controller::link(clock(), inputs()); }
  bool sound_allowed(bool critical) const { return autopilot_core::sound_allowed(settings(), clock(), critical); }
} autopilot_sim;
void SimAutopilot::run(const autopilot_core::Actions &acts) {
  using autopilot_core::ActionType;
  static const char *OUT[] = {"Utility first (USB)", "Solar first (SUB)", "Battery first (SBU)"};
  static const char *CHG[] = {"Utility first", "Solar first", "Solar and utility", "Solar only"};
  for (const auto &a : acts) {
    switch (a.type) {
      case ActionType::NOTIFY: notify.execute(std::string(a.text)); break;
      case ActionType::TUNE: play_tune.execute(autopilot_core::tune_name((autopilot_core::Tune) a.code), a.prio, a.critical); break;
      case ActionType::SET_OUTPUT_PRIORITY: sel_output_source_priority.make_call().set_option(OUT[a.code % 3]).perform(); break;
      case ActionType::SET_CHARGER_SOURCE: sel_charger_source_priority.make_call().set_option(CHG[a.code % 4]).perform(); break;
      case ActionType::SET_CHARGE_CURRENT: sel_max_ac_charging_current.make_call().set_option(to_string((int) a.value)).perform(); break;
      case ActionType::SET_FLOAT_VOLTAGE:
        sel_battery_float_voltage.make_call().set_option(str_sprintf("%.1f", a.value)).perform();
        s_battery_float_voltage.state = a.value;     // the inverter takes it
        break;
      case ActionType::LOG: ESP_LOGW("ctl", "%s", a.text); break;
    }
  }
}
#define autopilot autopilot_sim        // the YAML lambdas call id(autopilot).sound_allowed(...)
#endif

#include "gen/lambdas.inc"
#ifdef USE_CORE
#undef autopilot
#endif

// ------------------------------------------------------------------ the world
struct Scenario {
  const char *name, *desc;
  double start_min, hours, soc0, pv_peak_w, cloud;
  std::vector<double> fc;                        // forecast kWh per day (index 0 = start day), NAN = none
  std::function<double(double)> extra_load;      // W on top of the house load, by local minute
  std::function<bool(double)> grid_up;           // by sim minute
  std::function<bool(double)> link_up;           // RS232 link, by sim minute
  std::function<double(double, double)> soc_reading;
  bool time_valid = true, auto_on = true, observe = false, sunrise_known = true;
  double yday_kwh = NAN;                         // restored "yesterday's solar"
  std::function<bool(double)> inv_ignores = [](double) { return false; };
};

static double day_min(double m) { return fmod(m, 1440.0); }
static bool between(double m, double a, double b) { m = day_min(m); return m >= a && m < b; }

// house: ~200 W idle (router, standby, fridge average) + fridge compressor, lights, kitchen
static double house_load(double m, std::mt19937 &rng) {
  double w = 150;
  if (fmod(m, 35.0) < 15.0) w += 110;                    // fridge compressor 15 of 35 min
  if (between(m, 17.5 * 60, 23 * 60)) w += 180;          // lights + TV
  if (between(m, 6.5 * 60, 8 * 60)) w += 250;            // morning
  if (between(m, 7 * 60, 7 * 60 + 4)) w += 2000;         // kettle
  if (between(m, 19 * 60, 19 * 60 + 3)) w += 2000;       // kettle
  if (between(m, 13 * 60, 13 * 60 + 2)) w += 1800;       // microwave
  std::uniform_real_distribution<double> n(-15, 15);
  return w + n(rng);
}

static double pv_power(const Scenario &sc, double m, std::mt19937 &rng) {
  double d = day_min(m);
  if (d <= SUNRISE || d >= SUNSET) return 0;
  double p = sc.pv_peak_w * pow(sin(M_PI * (d - SUNRISE) / DAYLEN), 1.3);
  double wave = 0.5 + 0.5 * sin(m / 23.0) * sin(m / 7.0);
  std::uniform_real_distribution<double> n(0, 1);
  double cloud = sc.cloud * (0.6 + 0.4 * wave) + (sc.cloud > 0 ? 0.1 * n(rng) : 0);
  return std::max(0.0, p * (1 - std::min(0.95, cloud)));
}

int main(int argc, char **argv) {
  const double CAP_WH = 4500, CUTOFF = 3.0;
  std::vector<Scenario> S;
  auto none = [](double) { return 0.0; };
  auto always = [](double) { return true; };
  auto exact = [](double s, double) { return s; };
  const double FC_SUNNY = 9.0, FC_CLOUDY = 1.5;   // fake forecasts (kWh/day)

  S.push_back({"sunny_full", "2 kW PV clear, battery full 06:00, 2 kW heater 20:00-21:00", 6 * 60, 42, 100, 2000, 0.05,
               {FC_SUNNY, FC_SUNNY, FC_SUNNY}, [](double m) { return between(m, 20 * 60, 21 * 60) ? 2000.0 : 0.0; },
               always, always, exact});
  S.push_back({"cloudy_charge", "overcast day (forecast 1.5 kWh), SOC 35 at 06:00: cloudy reserve + grid-charge to 40 %",
               6 * 60, 30, 35, 2000, 0.85, {FC_CLOUDY, FC_CLOUDY}, none, always, always, exact});
  S.push_back({"emergency", "SOC 12 % at 21:00, sunny forecast: LOW + emergency charge (fast) to 25 %",
               21 * 60, 12, 12, 2000, 0.1, {FC_SUNNY, FC_SUNNY}, none, always, always, exact});
  S.push_back({"overnight", "SOC 60 at 17:00, sunny tomorrow: overnight rule keeps enough for the morning",
               17 * 60, 18, 60, 2000, 0.1, {FC_SUNNY, FC_SUNNY}, none, always, always, exact});
  S.push_back({"heavy_load_day", "SOC 45, 2 kW PV overcast, 2.8 kW 14:00-14:10, 2 kW 15:00-16:00", 10 * 60, 10, 45, 2000,
               0.8, {3.0}, [](double m) {
                 return between(m, 14 * 60, 14 * 60 + 10) ? 2800.0 : between(m, 15 * 60, 16 * 60) ? 2000.0 : 0.0; },
               always, always, exact});
  S.push_back({"grid_outage", "SOC 40 at 18:00, grid lost 19:00-02:00, 2 kW heater 20:00-21:00", 18 * 60, 14, 40,
               2000, 0.2, {FC_SUNNY, FC_SUNNY}, [](double m) { return between(m, 20 * 60, 21 * 60) ? 2000.0 : 0.0; },
               [](double sm) { return !(sm >= 60 && sm < 8 * 60); }, always, exact});
  S.push_back({"soc_glitch", "SOC 60, reading jumps to 0 % for 30 s at 11:00", 10 * 60, 3, 60, 2000, 0.3, {FC_SUNNY}, none,
               always, always, [](double s, double sm) { return (sm >= 60 && sm < 60.5) ? 0.0 : s; }});
  S.push_back({"link_loss", "RS232 link drops 20:00-23:00 while the battery is low", 18 * 60, 8, 22, 2000, 0.2,
               {FC_SUNNY, FC_SUNNY}, none, always, [](double sm) { return !(sm >= 120 && sm < 300); }, exact});
  S.push_back({"no_clock", "no time after a power cut: SOC 30 at 17:00, 2 kW at 20:00", 17 * 60, 16, 30, 2000, 0.2,
               {NAN, NAN}, [](double m) { return between(m, 20 * 60, 21 * 60) ? 2000.0 : 0.0; }, always, always, exact});
  S.back().time_valid = false;
  S.push_back({"kettle_flap", "SOC 22 %, kettle 2.6 kW 2 min every 6 min at night", 19 * 60, 4, 22, 2000, 0.2,
               {FC_SUNNY, FC_SUNNY}, [](double m) { return fmod(m, 6.0) < 2.0 ? 2600.0 : 0.0; }, always, always, exact});
  S.push_back({"manual_mode", "Auto control off: SOC 18 falling at night", 20 * 60, 6, 18, 2000, 0.2, {FC_SUNNY, FC_SUNNY},
               none, always, always, exact});
  S.back().auto_on = false;
  S.push_back({"boot_low", "board boots with SOC 12 % at 21:00", 21 * 60, 2, 12, 2000, 0.2, {FC_SUNNY, FC_SUNNY}, none,
               always, always, exact});
  S.push_back({"observe", "observe-only: SOC 14 % at night, cloudy - decides but never writes", 21 * 60, 6, 14, 2000,
               0.2, {FC_CLOUDY, FC_CLOUDY}, none, always, always, exact});
  S.back().observe = true;
  S.push_back({"write_fail", "inverter ignores writes for the first 20 min while LOW wants grid", 21 * 60, 2, 15, 2000, 0.2,
               {FC_SUNNY, FC_SUNNY}, none, always, always, exact});
  S.back().inv_ignores = [](double sm) { return sm < 20; };
  S.push_back({"no_internet", "no forecast, no history: unknown = cloudy reserve; next day uses measured solar",
               6 * 60, 36, 50, 2000, 0.05, {NAN, NAN}, none, always, always, exact});
  S.push_back({"sunny_dishwasher", "SOC 95, 2 kW PV clear, 2 kW dishwasher 12:00-13:00", 9 * 60, 8, 95, 2000, 0.05,
               {FC_SUNNY}, [](double m) { return between(m, 12 * 60, 13 * 60) ? 2000.0 : 0.0; }, always, always, exact});

  if (argc < 2) {
    for (auto &s : S) printf("%s\t%s\n", s.name, s.desc);
    return 0;
  }
  Scenario *scp = nullptr;
  for (auto &s : S) if (!strcmp(s.name, argv[1])) scp = &s;
  if (!scp) { fprintf(stderr, "unknown scenario\n"); return 1; }
  Scenario &sc = *scp;

  play_tune.fn = [](std::string t, int p, bool c) { L_play_tune(t, p, c); };
  notify.fn = [](std::string m) { emit("\"ev\":\"notify\",\"msg\":\"%s\"", m.c_str()); };

  std::mt19937 rng(42);
  SIM_T0_MIN = sc.start_min;
  TIME_VALID = sc.time_valid;
#ifdef USE_CORE
  autopilot_sim.set.auto_ctl = sc.auto_on;
  autopilot_sim.set.observe = sc.observe;         // default is ON; tests run with it off
#else
  auto_ctl.state = sc.auto_on;
  sw_observe.state = sc.observe;                  // YAML default is ON; tests run with it off
#endif
  uint32_t sunrise0 = 0;
  if (sc.sunrise_known && TIME_VALID) {           // restored from the previous day
    double d0 = floor(sc.start_min / 1440.0) * 1440;
    sunrise0 = EPOCH_DAY0 + (uint32_t) ((d0 + SUNRISE - (sc.start_min - d0 < SUNRISE ? 1440 : 0)) * 60);
  }
#ifdef USE_CORE
  {
    autopilot_core::Persist p;                         // = the YAML globals' initial values
    p.solar_yesterday_kwh = (float) sc.yday_kwh;
    p.sunrise_ts = sunrise0;
    autopilot_sim.ctl.restore(p);
  }
#else
  sol_yday_kwh = (float) sc.yday_kwh;
  sunrise_ts = sunrise0;
#endif
  double energy = CAP_WH * sc.soc0 / 100, soc = sc.soc0, solar_today_wh = 0;
  bool float_prev = false;
#ifdef USE_CORE
  autopilot_core::GridDebounce grid_debounce;
#else
  bool grid_raw_prev = false; uint32_t grid_change_ms = 0;
#endif
  double unmet_wh = 0, grid_wh = 0;
  emit("\"ev\":\"start\",\"scenario\":\"%s\",\"desc\":\"%s\",\"start_min\":%.0f,\"alarm\":30,\"norm_a\":%.0f",
       sc.name, sc.desc, sc.start_min,
#ifdef USE_CORE
       autopilot_sim.set.chg_norm_a);
#else
       n_chg_norm_a.state);
#endif

  const uint32_t END = (uint32_t) (sc.hours * 3600 * 1000);
  for (SIM_MS = 0; SIM_MS <= END; SIM_MS += 1000) {
    if (SIM_MS == 1000) boot_ms = std::max<uint32_t>(millis(), 1);    // on_boot
#ifdef USE_CORE
    if (SIM_MS == 1000) autopilot_sim.ctl.begin(millis());
#endif
    const double sm = SIM_MS / 60000.0, m = clock_min();
    const int day = (int) (m / 1440.0);
    const bool grid = sc.grid_up(sm);
    LINK_UP = sc.link_up(sm);
    INV_IGNORES = sc.inv_ignores(sm);
    auto fc_of = [&](int d) { return d < (int) sc.fc.size() ? sc.fc[d] : sc.fc.back(); };
#ifdef USE_CORE
    sim_fc_today = (float) fc_of(day);
    sim_fc_tomorrow = (float) fc_of(day + 1);
#else
    fc_today_kwh = (float) fc_of(day);
    fc_tomorrow_kwh = (float) fc_of(day + 1);
#endif

    // --- physics (1 s): Axpert. SUB + grid: grid feeds the load; "Solar and utility" also charges from grid.
    const bool sub = sel_output_source_priority.inverter == "Solar first (SUB)";
    const bool ac_chg_ok = grid && sub && sel_charger_source_priority.inverter == "Solar and utility";
    double load = house_load(m, rng) + sc.extra_load(m), pv = pv_power(sc, m, rng);
    double surplus = pv - load, from_grid = 0;
    if (surplus >= 0) {
      energy += std::min({surplus, 1500.0, (CAP_WH - energy) * 3600}) * 0.95 / 3600;
    } else {
      double need = -surplus;
      if (sub && grid) from_grid = need;
      else if (soc > CUTOFF) energy -= need / 0.92 / 3600;
      else if (grid) from_grid = need;                   // inverter's own low-battery fallback
      else unmet_wh += need / 3600;                      // blackout
    }
    if (ac_chg_ok) {
      double a = atof(sel_max_ac_charging_current.inverter.c_str());
      double p = std::min(a * 27.0, (CAP_WH - energy) * 3600);
      energy += p * 0.9 / 3600; from_grid += p;
    }
    energy = std::clamp(energy, 0.0, CAP_WH);
    soc = 100 * energy / CAP_WH;
    grid_wh += from_grid / 3600;
    solar_today_wh += std::min(pv, load + 1500) / 3600;
    const bool new_minute = fmod(SIM_MS / 1000.0, 60) == 0;
#ifndef USE_CORE                                       // the core keeps yesterday's solar itself
    if (TIME_VALID && new_minute && (int) fmod(m, 1440.0) == 23 * 60 + 59 && !isnan(e_solar_today.state))
      sol_yday_kwh = e_solar_today.state;               // on_time 23:59
#endif
    if ((int) fmod(m, 1440.0) == 0 && new_minute) {   // midnight
      solar_today_wh = 0;
#ifndef USE_CORE
      fc_curve.clear();
#endif
    }

    // --- inverter readings every 2 s (pipsolar). on_raw_value refreshes the data watchdog.
    if (LINK_UP && SIM_MS % 2000 == 0) {
      s_soc.state = (float) std::round(sc.soc_reading(soc, sm));
      s_load_power.state = (float) load;
      s_pv_power.state = (float) pv;
      s_grid_v.state = grid ? 230.0f : 0.0f;
      auto &o = sel_output_source_priority.inverter;
      s_output_source_priority.state = o == "Solar first (SUB)" ? 1 : o == "Battery first (SBU)" ? 2 : 0;
      auto &c = sel_charger_source_priority.inverter;
      s_charger_source_priority.state = c == "Utility first" ? 0 : c == "Solar first" ? 1 : c == "Solar and utility" ? 2 : 3;
      s_max_ac_charging_current.state = (float) atof(sel_max_ac_charging_current.inverter.c_str());
      if (isnan(s_battery_float_voltage.state)) s_battery_float_voltage.state = 27.0f;
#ifdef USE_CORE
      autopilot_sim.last_data = millis();
#else
      last_inverter_data = millis();
#endif
    }
    e_solar_today.state = TIME_VALID ? (float) (solar_today_wh / 1000.0) : NAN;
#ifdef USE_CORE
    inv_link.state = autopilot_sim.link(); inv_link.has = true;
#else
    inv_link.state = L_inv_link(); inv_link.has = true;
#endif

#ifdef USE_CORE
    // --- Grid Available: the component's GridDebounce (voltage > 150 V for 30 s), as on the device
    {
      bool first = false;
      if (grid_debounce.update(!isnan(s_grid_v.state) && s_grid_v.state > 150, SIM_MS, &first)) {
        bs_grid.has = true; bs_grid.state = grid_debounce.state();
        emit("\"ev\":\"grid\",\"on\":%s", bs_grid.state ? "true" : "false");
        if (!first) autopilot_sim.grid_changed(bs_grid.state);
      }
    }
#else
    // --- Grid Available: template lambda + delayed_on/off 30 s, then on_press / on_release
    bool raw = L_grid_raw();
    if (raw != grid_raw_prev) { grid_raw_prev = raw; grid_change_ms = SIM_MS; }
    if ((!bs_grid.has || raw != bs_grid.state) && SIM_MS - grid_change_ms >= 30000) {
      bool first = !bs_grid.has;
      bs_grid.has = true; bs_grid.state = raw;
      emit("\"ev\":\"grid\",\"on\":%s", raw ? "true" : "false");
      if (!first && L_grid_cond()) {
        if (raw) play_tune.execute("grid_back", 1, false);
        else L_grid_lost();
      }
    }

#endif

    // --- float rule (pipsolar "charging to floating" on_press)
    bool floating = energy >= CAP_WH * 0.995;
#ifdef USE_CORE
    if (floating && !float_prev) autopilot_sim.float_entered();
#else
    if (floating && !float_prev && L_float_cond()) {
      auto c = sel_battery_float_voltage.make_call();
      c.set_option(str_sprintf("%.1f", n_float_v.state)); c.perform();
      s_battery_float_voltage.state = n_float_v.state;
    }
#endif
    float_prev = floating;

    // --- the automations at their YAML intervals
#ifdef USE_CORE
    if (SIM_MS % 2000 == 0) autopilot_sim.control();
    if (SIM_MS % 60000 == 0) autopilot_sim.minute();
    const auto st = autopilot_sim.ctl.status();
    const uint8_t sub_reasons = st.reasons;
    const bool want_sub = st.want_sub, cloudy = st.cloudy, charging = st.charging, ctl_fault = st.fault;
    const float reserve_sw = st.reserve_sw, reserve_ret = st.reserve_ret, plan_fc = st.plan_fc,
                soc_at_sun = st.soc_at_sun, base_load = st.base_load;
#else
    if (SIM_MS % 2000 == 0) L_controller();
    if (SIM_MS % 60000 == 0) { L_planner(); L_alarms(); L_alarm_soc(); }
#endif

    if (SIM_MS % 60000 == 0)
      emit("\"ev\":\"sample\",\"clock\":%.0f,\"soc\":%.2f,\"soc_r\":%.0f,\"load\":%.0f,\"pv\":%.0f,\"grid\":%s,"
           "\"mode\":\"%s\",\"reasons\":%d,\"want_sub\":%s,\"night\":%s,\"link\":%s,\"res_sw\":%.0f,\"res_ret\":%.0f,"
           "\"cloudy\":%s,\"plan_fc\":%.2f,\"charging\":%s,\"chg_src\":\"%s\",\"chg_a\":\"%s\",\"soc_sun\":%.1f,"
           "\"base\":%.0f,\"fault\":%s,\"unmet_wh\":%.1f",
           m, soc, s_soc.state, load, pv, grid ? "true" : "false", sub ? "SUB" : "SBU", sub_reasons,
           want_sub ? "true" : "false", sun_c.elevation() < -0.833 ? "true" : "false", LINK_UP ? "true" : "false",
           reserve_sw, reserve_ret, cloudy ? "true" : "false", isnan(plan_fc) ? -1.0f : plan_fc,
           charging ? "true" : "false", sel_charger_source_priority.inverter.c_str(),
           sel_max_ac_charging_current.inverter.c_str(), isnan(soc_at_sun) ? -999.0f : soc_at_sun, base_load,
           ctl_fault ? "true" : "false", unmet_wh);
  }
  emit("\"ev\":\"end\",\"soc\":%.1f,\"grid_wh\":%.0f,\"unmet_wh\":%.1f", soc, grid_wh, unmet_wh);
  return 0;
}
