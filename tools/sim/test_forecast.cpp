// Unit test of the forecast part of the core (components/solar_autopilot/ap_forecast.*):
// scheduler, Forecast.Solar replies (as the API sends them), midnight shift, interpolation.
//   built and run by run.sh
#include <cstdio>
#include <cstring>

#include "ap/ap_forecast.h"

using namespace autopilot_core;

static int fails = 0, checks = 0;
#define CHECK(cond)                                                \
  do {                                                             \
    checks++;                                                      \
    if (!(cond)) {                                                 \
      fails++;                                                     \
      printf("   [FAIL] line %d: %s\n", __LINE__, #cond);          \
    }                                                              \
  } while (0)
static bool near(float a, float b) { return std::fabs(a - b) < 0.01f; }

static const char DAY[] =
    "{\"result\":{\"2026-11-06\":7341,\"2026-11-07\":4012},\"message\":{\"code\":0,\"type\":\"success\","
    "\"text\":\"\",\"info\":{\"latitude\":36.15,\"longitude\":36.73,\"place\":\"x\",\"timezone\":\"Asia/Damascus\"},"
    "\"ratelimit\":{\"period\":3600,\"limit\":12,\"remaining\":10}}}";
static const char WATTS[] =
    "{\"result\":{\"2026-11-06 06:51:12\":0,\"2026-11-06 07:00:00\":60,\"2026-11-06 08:00:00\":420,"
    "\"2026-11-06 12:00:00\":1500,\"2026-11-06 17:39:40\":0,\"2026-11-07 06:52:01\":0,"
    "\"2026-11-07 12:00:00\":1100},\"message\":{\"code\":0}}";
static const char LIMIT[] = "{\"result\":null,\"message\":{\"code\":429,\"type\":\"error\",\"text\":\"Rate limit\"}}";

int main() {
  Settings s;
  Forecast f;
  f.set_location(36.15f, 36.73f);

  char u[160];
  f.url(Forecast::DAY_TOTALS, s, u, sizeof u);
  CHECK(strcmp(u, "https://api.forecast.solar/estimate/watthours/day/36.1500/36.7300/40/0/2.0") == 0);
  f.url(Forecast::WATTS, s, u, sizeof u);
  CHECK(strcmp(u, "https://api.forecast.solar/estimate/watts/36.1500/36.7300/40/0/2.0") == 0);

  // scheduler
  CHECK(!f.due(30000, s, true, true));                       // first minute after boot
  CHECK(!f.due(61000, s, false, true) && !strcmp(f.status(), "no WiFi"));
  CHECK(!f.due(61000, s, true, false) && !strcmp(f.status(), "no clock"));
  CHECK(f.due(61000, s, true, true));
  f.fetch_started(61000);
  CHECK(!strcmp(f.status(), "fetching"));
  f.connect_failed("day totals");
  CHECK(!strcmp(f.status(), "no connect"));
  CHECK(!f.due(61000 + 59000, s, true, true));              // failed: retry after 1 min
  CHECK(f.due(61000 + 60000, s, true, true));

  // HTTP 429: back off 15 min
  f.fetch_started(200000);
  CHECK(!f.day_totals(429, LIMIT, strlen(LIMIT), "2026-11-06", "2026-11-07", "14:05", 200000));
  CHECK(!strcmp(f.status(), "HTTP 429"));
  CHECK(f.last_reply_ms() == 200000);                       // a reply all the same: internet works
  CHECK(!f.due(200000 + 14 * 60000, s, true, true));
  CHECK(f.due(200000 + 15 * 60000, s, true, true));

  // good day totals
  f.fetch_started(1200000);
  CHECK(f.day_totals(200, DAY, strlen(DAY), "2026-11-06", "2026-11-07", "14:05", 1200000));
  CHECK(near(f.today_kwh(), 7.341f) && near(f.tomorrow_kwh(), 4.012f) && f.ok());
  CHECK(!strcmp(f.status(), "updated 14:05"));
  CHECK(!f.due(1200000 + 2 * 3600000 - 1000, s, true, true));   // ok: next after Forecast Refresh (2 h)
  CHECK(f.due(1200000 + 2 * 3600000, s, true, true));
  s.fc_interval_h = 8;
  CHECK(!f.due(1200000 + 2 * 3600000, s, true, true));

  // a reply for another day: bad data, values kept
  f.fetch_started(2000000);
  CHECK(!f.day_totals(200, DAY, strlen(DAY), "2026-11-09", "2026-11-10", "14:05", 2000000));
  CHECK(!strcmp(f.status(), "bad data") && near(f.today_kwh(), 7.341f));

  // power curve: only today's points; interpolation; night = 0; no curve = NAN
  CHECK(std::isnan(f.power_at(600)));
  CHECK(f.watts(200, WATTS, strlen(WATTS), "2026-11-06"));
  CHECK(f.points() == 5);
  CHECK(near(f.power_at(7 * 60 + 30), 240));                // between 60 W at 07:00 and 420 W at 08:00
  CHECK(near(f.power_at(12 * 60), 1500) && near(f.power_at(5 * 60), 0) && near(f.power_at(20 * 60), 0));
  // a reply cut short keeps the points before the cut
  Forecast g;
  CHECK(g.watts(200, WATTS, 80, "2026-11-06") && g.points() == 2);   // cut inside the 3rd key
  CHECK(g.watts(200, WATTS, 59, "2026-11-06") && g.points() == 1);   // cut inside "60": dropped
  CHECK(!g.watts(500, "oops", 4, "2026-11-06"));

  // midnight: tomorrow becomes today, curve cleared
  Clock c;
  c.valid = true;
  c.hour = 23;
  f.tick(c);
  c.hour = 0;
  f.tick(c);
  CHECK(near(f.today_kwh(), 4.012f) && std::isnan(f.tomorrow_kwh()) && f.points() == 0);

  printf("forecast unit test: %d/%d checks passed\n", checks - fails, checks);
  return fails != 0;
}
