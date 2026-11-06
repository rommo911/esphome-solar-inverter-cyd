// Solar forecast from Forecast.Solar (free API, https GET, no key): when to fetch, the URLs,
// reading the replies, and the values the planner and the screen use. No HTTP and no JSON
// library here: the caller does the GET and hands the reply body in.
#pragma once

#include <cstddef>
#include <cstdint>

#include "ap_settings.h"
#include "ap_types.h"

namespace autopilot_core {

class Forecast {
 public:
  static const uint8_t MAX_POINTS = 64;   // power curve points kept for today (the API gives ~25)
  static const uint32_t RETRY_MS = 60000, RATE_LIMIT_MS = 15UL * 60000UL, START_MS = 60000;

  void set_location(float latitude, float longitude) {
    lat_ = latitude;
    lon_ = longitude;
  }
  // Day totals (today + tomorrow) or today's power curve, for the plane in the settings.
  enum Kind : uint8_t { DAY_TOTALS, WATTS };
  void url(Kind kind, const Settings &s, char *buf, size_t len) const;

  // Every minute: is a fetch due? After a good fetch every "Forecast Refresh" hours, after a
  // failure every minute (15 min after HTTP 429). Sets the status when it cannot fetch.
  bool due(uint32_t now, const Settings &s, bool wifi_ok, bool clock_ok);
  void fetch_started(uint32_t now);           // call right before the first GET
  void skipped(const char *status, const char *detail);   // e.g. not enough memory

  // Replies. date: local "YYYY-MM-DD" of today and tomorrow, hhmm: local "HH:MM" now.
  // Return true if the reply was good. A day-totals reply of any kind proves the internet works.
  bool day_totals(int http_status, const char *body, size_t len, const char *today, const char *tomorrow,
                  const char *hhmm, uint32_t now);
  bool watts(int http_status, const char *body, size_t len, const char *today);
  void connect_failed(const char *what);

  // Every minute: shifts tomorrow -> today when the local day changes.
  void tick(const Clock &c);

  float today_kwh() const { return today_kwh_; }
  float tomorrow_kwh() const { return tomorrow_kwh_; }
  bool ok() const { return ok_; }
  uint8_t points() const { return n_; }
  float power_at(int minute_of_day) const;   // W, interpolated; NAN without a curve
  const char *status() const { return status_; }   // short, for a screen: "updated 14:05"
  const char *detail() const { return detail_; }   // full sentence, for the log and HA
  uint32_t last_reply_ms() const { return last_reply_; }   // 0 = never (internet check)

 private:
  void set_(const char *status, const char *fmt, ...) __attribute__((format(printf, 3, 4)));

  float lat_ = NAN, lon_ = NAN;
  float today_kwh_ = NAN, tomorrow_kwh_ = NAN;
  uint16_t minute_[MAX_POINTS] = {};
  float watt_[MAX_POINTS] = {};
  uint8_t n_ = 0;
  bool ok_ = false;
  uint32_t last_try_ = 0, wait_ = RETRY_MS, last_reply_ = 0;
  int prev_hour_ = -1;
  char status_[24] = "not fetched";
  char detail_[200] = "not fetched yet";
};

// Reads the "result": {"key": number, ...} object of a Forecast.Solar reply, calling
// fn(key, key_len, value, ctx) for each pair. Returns false if there is no such object.
// Tolerates a reply cut short (pairs before the cut are still delivered).
bool scan_result(const char *body, size_t len, void (*fn)(const char *, size_t, double, void *), void *ctx);

}  // namespace autopilot_core
