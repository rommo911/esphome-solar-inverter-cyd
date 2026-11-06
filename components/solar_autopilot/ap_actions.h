// What the controller asks the caller to do, in order. The caller performs the writes and the
// sounds; the controller sees the result in the read-back on a later call.
#pragma once

#include <cstdarg>
#include <cstdint>
#include <cstdio>

namespace autopilot_core {

enum class ActionType : uint8_t {
  NOTIFY,               // text: show / send a message
  TUNE,                 // code: Tune, prio, critical
  SET_OUTPUT_PRIORITY,  // code: OutputPriority
  SET_CHARGER_SOURCE,   // code: ChargerSource
  SET_CHARGE_CURRENT,   // value: A
  SET_FLOAT_VOLTAGE,    // value: V
  LOG,                  // text: a log line (warning level)
};

enum class Tune : uint8_t { GRID_LOST, GRID_BACK, TO_GRID_LOW, TO_GRID, ALARM_NO_GRID, WARN_MORNING };

inline const char *tune_name(Tune t) {
  switch (t) {
    case Tune::GRID_LOST: return "grid_lost";
    case Tune::GRID_BACK: return "grid_back";
    case Tune::TO_GRID_LOW: return "to_grid_low";
    case Tune::TO_GRID: return "to_grid";
    case Tune::ALARM_NO_GRID: return "alarm_no_grid";
    case Tune::WARN_MORNING: return "warn_morning";
  }
  return "";
}

struct Action {
  ActionType type;
  uint8_t code = 0;
  uint8_t prio = 0;
  bool critical = false;
  float value = 0;
  char text[104] = {0};
};

// Fixed-size queue (no heap). One controller call produces at most ~9 actions.
class Actions {
 public:
  static const uint8_t CAPACITY = 12;
  void clear() { n_ = 0; }
  uint8_t size() const { return n_; }
  const Action *begin() const { return items_; }
  const Action *end() const { return items_ + n_; }
  const Action &operator[](uint8_t i) const { return items_[i]; }
  uint32_t dropped() const { return dropped_; }

  Action *push(ActionType type) {
    if (n_ >= CAPACITY) {
      dropped_++;
      return nullptr;
    }
    Action *a = &items_[n_++];
    *a = Action{};
    a->type = type;
    return a;
  }
  void tune(Tune t, uint8_t prio, bool critical) {
    if (Action *a = push(ActionType::TUNE)) {
      a->code = (uint8_t) t;
      a->prio = prio;
      a->critical = critical;
    }
  }
  void set(ActionType type, uint8_t code, float value = 0) {
    if (Action *a = push(type)) {
      a->code = code;
      a->value = value;
    }
  }
  void text(ActionType type, const char *fmt, ...) __attribute__((format(printf, 3, 4))) {
    if (Action *a = push(type)) {
      va_list ap;
      va_start(ap, fmt);
      vsnprintf(a->text, sizeof a->text, fmt, ap);
      va_end(ap);
    }
  }

 private:
  Action items_[CAPACITY];
  uint8_t n_ = 0;
  uint32_t dropped_ = 0;
};

}  // namespace autopilot_core
