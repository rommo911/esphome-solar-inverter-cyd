#include "ap_forecast.h"

#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace autopilot_core {

void Forecast::url(Kind kind, const Settings &s, char *buf, size_t len) const {
  snprintf(buf, len, "https://api.forecast.solar/estimate/%s/%.4f/%.4f/%.0f/%.0f/%.1f",
           kind == DAY_TOTALS ? "watthours/day" : "watts", lat_, lon_, s.pv_tilt, s.pv_az, s.pv_kwp);
}

void Forecast::set_(const char *status, const char *fmt, ...) {
  snprintf(status_, sizeof status_, "%s", status);
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(detail_, sizeof detail_, fmt, ap);
  va_end(ap);
}

bool Forecast::due(uint32_t now, const Settings &s, bool wifi_ok, bool clock_ok) {
  if (now < START_MS) return false;   // let WiFi and the clock settle after boot
  if (!wifi_ok) {
    set_("no WiFi", "waiting for WiFi");
    return false;
  }
  if (!clock_ok) {
    set_("no clock", "waiting for the clock (SNTP)");
    return false;
  }
  const uint32_t wait = ok_ ? (uint32_t) (s.fc_interval_h * 3600000.0f) : wait_;
  return last_try_ == 0 || now - last_try_ >= wait;
}

void Forecast::fetch_started(uint32_t now) {
  last_try_ = now;
  ok_ = false;   // back to true only by a good day-totals reply
  wait_ = RETRY_MS;
  set_("fetching", "fetching");
}

void Forecast::skipped(const char *status, const char *detail) { set_(status, "skipped: %s", detail); }

void Forecast::connect_failed(const char *what) { set_("no connect", "%s: connection / TLS failed", what); }

namespace {
struct DayCtx {
  const char *today, *tomorrow;
  double today_wh = NAN, tomorrow_wh = NAN;
};
void day_pair(const char *k, size_t n, double v, void *p) {
  DayCtx *c = static_cast<DayCtx *>(p);
  if (n == 10 && strncmp(k, c->today, 10) == 0) c->today_wh = v;
  if (n == 10 && strncmp(k, c->tomorrow, 10) == 0) c->tomorrow_wh = v;
}
struct WattCtx {
  const char *today;
  uint16_t *minute;
  float *watt;
  uint8_t n, max;
};
void watt_pair(const char *k, size_t n, double v, void *p) {
  WattCtx *c = static_cast<WattCtx *>(p);
  int hh, mm;   // "YYYY-MM-DD HH:MM:SS"
  if (n < 16 || strncmp(k, c->today, 10) != 0 || sscanf(k + 11, "%2d:%2d", &hh, &mm) != 2 || c->n >= c->max) return;
  const uint16_t m = (uint16_t) (hh * 60 + mm);
  uint8_t i = c->n++;   // insertion sort: the API sends them in order, so this is cheap
  while (i > 0 && c->minute[i - 1] > m) {
    c->minute[i] = c->minute[i - 1];
    c->watt[i] = c->watt[i - 1];
    i--;
  }
  c->minute[i] = m;
  c->watt[i] = (float) v;
}
}  // namespace

bool Forecast::day_totals(int code, const char *body, size_t len, const char *today, const char *tomorrow,
                          const char *hhmm, uint32_t now) {
  last_reply_ = std::max<uint32_t>(now, 1);   // got a reply: internet works
  if (code != 200) {
    set_("", "day totals: HTTP %d: %.*s", code, (int) std::min<size_t>(len, 150), body);
    snprintf(status_, sizeof status_, "HTTP %d", code);
    if (code == 429) wait_ = RATE_LIMIT_MS;   // rate limited: back off
    return false;
  }
  DayCtx c{today, tomorrow};
  const bool parsed = scan_result(body, len, day_pair, &c);
  if (std::isnan(c.today_wh)) {
    set_("bad data", "day totals: %s, no value for %.10s: %.*s", parsed ? "reply ok" : "reply not readable", today,
         (int) std::min<size_t>(len, 150), body);
    return false;
  }
  today_kwh_ = (float) (c.today_wh / 1000.0);
  if (!std::isnan(c.tomorrow_wh)) tomorrow_kwh_ = (float) (c.tomorrow_wh / 1000.0);
  ok_ = true;
  char st[sizeof status_];
  snprintf(st, sizeof st, "updated %.5s", hhmm);
  set_(st, "ok %.5s: today %.1f kWh, tomorrow %.1f kWh", hhmm, today_kwh_, tomorrow_kwh_);
  return true;
}

bool Forecast::watts(int code, const char *body, size_t len, const char *today) {
  if (code != 200) {
    snprintf(detail_, sizeof detail_, "power curve: HTTP %d: %.*s", code, (int) std::min<size_t>(len, 150), body);
    return false;
  }
  uint16_t minute[MAX_POINTS];
  float watt[MAX_POINTS];
  WattCtx c{today, minute, watt, 0, MAX_POINTS};
  scan_result(body, len, watt_pair, &c);
  if (c.n == 0) {
    snprintf(detail_, sizeof detail_, "power curve: no points for %.10s", today);
    return false;
  }
  memcpy(minute_, minute, sizeof minute);
  memcpy(watt_, watt, sizeof watt);
  n_ = c.n;
  return true;
}

void Forecast::tick(const Clock &c) {
  if (!c.valid) return;
  if (prev_hour_ >= 0 && c.hour < prev_hour_) {   // midnight: tomorrow is today, refreshed by the next fetch
    today_kwh_ = tomorrow_kwh_;
    tomorrow_kwh_ = NAN;
    n_ = 0;
  }
  prev_hour_ = c.hour;
}

float Forecast::power_at(int m) const {
  if (n_ == 0) return NAN;
  for (uint8_t i = 1; i < n_; i++) {
    if (m >= minute_[i - 1] && m <= minute_[i]) {
      const float f = float(m - minute_[i - 1]) / std::max(1, minute_[i] - minute_[i - 1]);
      return watt_[i - 1] + f * (watt_[i] - watt_[i - 1]);
    }
  }
  return 0;   // before the first / after the last point of the day = night
}

bool scan_result(const char *s, size_t len, void (*fn)(const char *, size_t, double, void *), void *ctx) {
  const char *end = s + len;
  const char *p = s;
  const char key[] = "\"result\"";
  for (;; p++) {   // find "result"
    if (end - p < (ptrdiff_t) sizeof key - 1) return false;
    if (memcmp(p, key, sizeof key - 1) == 0) break;
  }
  p += sizeof key - 1;
  auto ws = [&]() {
    while (p < end && (*p == ' ' || *p == '\n' || *p == '\r' || *p == '\t')) p++;
  };
  ws();
  if (p >= end || *p != ':') return false;
  p++;
  ws();
  if (p >= end || *p != '{') return false;
  p++;
  for (;;) {
    ws();
    if (p >= end || *p == '}') return true;
    if (*p != '"') return true;   // not a key: stop (nothing nested is expected)
    const char *k = ++p;
    while (p < end && *p != '"') p++;
    if (p >= end) return true;    // reply cut short
    const size_t kn = (size_t) (p - k);
    p++;
    ws();
    if (p >= end || *p != ':') return true;
    p++;
    ws();
    char num[24];
    size_t nn = 0;
    while (p < end && nn < sizeof num - 1 && (strchr("+-.eE", *p) != nullptr || (*p >= '0' && *p <= '9')))
      num[nn++] = *p++;
    if (nn == 0 || p >= end) return true;   // not a number, or cut in the middle of one
    num[nn] = 0;
    fn(k, kn, strtod(num, nullptr), ctx);
    ws();
    if (p < end && *p == ',') p++;
  }
}

}  // namespace autopilot_core
