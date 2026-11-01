"""Check every simulated scenario against what the v2 controller promises (handoff section 4).

  python3 check.py RESULTS_DIR      (RESULTS_DIR holds <scenario>.jsonl from ./sim <scenario>)
"""
import glob
import json
import os
import sys

QUIET = (1, 9)
NONCRIT = {"gridlost", "gridback", "togridlow", "togrid"}
MIN_SUB_S = 180


def hhmm(clock_min):
    m = int(clock_min) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def check(ev):
    start = next(e for e in ev if e["ev"] == "start")
    t0 = start["start_min"]
    clock = lambda t: hhmm(t0 + t / 60)
    name = start["scenario"]
    samples = [e for e in ev if e["ev"] == "sample"]
    allw = [e for e in ev if e["ev"] == "write" and e["sel"] != "float_voltage"]
    outw = [e for e in allw if e["sel"] == "output_priority"]
    chgw = [e for e in allw if e["sel"] in ("charger_source", "ac_charge_current")]
    tunes = [e for e in ev if e["ev"] == "tune"]
    notes = [e for e in ev if e["ev"] == "notify"]
    res = []

    def ok(label, cond, detail=""):
        res.append(("PASS" if cond else "FAIL", label, detail))

    # ================= general rules (every scenario)
    ok("nothing written in the first 30 s after boot", not any(w["t"] < 31 for w in allw))
    ok("nothing written while inverter data is stale", not any(not w["link"] for w in allw))
    if name in ("manual_mode", "observe"):
        ok("Auto off / observe-only: never writes to the inverter", not allw, f"{len(allw)} writes")
    # LOW promise: grid available + SOC below the planner's switch level longer than delay -> on grid
    below, late = None, []
    for s in samples:
        refusing = name == "write_fail" and s["t"] < (20 + 6) * 60     # inverter refuses writes (+1 retry)
        cond = (s["grid"] and s["link"] and s["soc_r"] < s["res_sw"] and s["t"] > 120
                and name not in ("manual_mode", "observe") and not refusing)
        below = (below if below is not None else s["t"]) if cond else None
        if below is not None and s["t"] - below > 60 + 60 + 30 and s["mode"] != "SUB":
            late.append(s)
    ok("on grid whenever SOC < switch level (grid available) longer than the delay", not late,
       f"first at {hhmm(late[0]['clock'])} SOC {late[0]['soc_r']:.0f} % < {late[0]['res_sw']:.0f}" if late else "")
    grew = [b for a, b in zip(samples, samples[1:]) if b["grid"] and a["grid"] and b["unmet_wh"] > a["unmet_wh"]]
    ok("no blackout while grid available", not grew)
    short = [f"{clock(a['t'])}->{clock(b['t'])}" for a, b in zip(outw, outw[1:])
             if a["opt"].startswith("Solar") and b["opt"].startswith("Battery") and a["taken"]
             and b["t"] - a["t"] < MIN_SUB_S]
    ok("at least 3 min on grid before going back to battery", not short, ", ".join(short[:4]))
    days = max(1, (samples[-1]["t"] - samples[0]["t"]) / 86400)
    ok("at most 12 output changes per day", len(outw) / days <= 12, f"{len(outw)} writes")
    loud = [f"{t['name']} {clock(t['t'])}" for t in tunes if t["name"] in NONCRIT and QUIET[0] <= t["hour"] < QUIET[1]]
    ok("no non-critical tune in quiet hours", not loud, ", ".join(loud))
    # charger: back to "Solar only" + normal current within 2 min of not charging (when active)
    if name not in ("manual_mode", "observe"):
        stuck, idle_since = [], None
        for s in samples:
            idle = not s["charging"] and s["link"]
            idle_since = (idle_since if idle_since is not None else s["t"]) if idle else None
            if (idle_since is not None and s["t"] - idle_since > 120 and s["t"] > 180
                    and (s["chg_src"] != "Solar only" or float(s["chg_a"]) != start["norm_a"])):
                stuck.append(s)
        ok("charger back to 'Solar only' + normal current when not charging", not stuck,
           f"{hhmm(stuck[0]['clock'])}: {stuck[0]['chg_src']} {stuck[0]['chg_a']} A" if stuck else "")
    # no-grid alarms
    nogrid_low = [s for s in samples if not s["grid"] and s["link"] and s["soc_r"] < start["alarm"] and s["t"] > 120]
    if nogrid_low:
        alarms = [t["t"] for t in tunes if t["name"] == "alarm"]
        first = nogrid_low[0]["t"]
        ok("alarm within 2 min of no grid + SOC < 30 %", any(a <= first + 120 for a in alarms),
           "alarms at " + ", ".join(clock(a) for a in alarms[:4]))
        b20 = [s["t"] for s in nogrid_low if s["soc_r"] < 20]
        if b20:
            gaps = [b - a for a, b in zip(alarms, alarms[1:]) if a >= b20[0] - 600 and b <= b20[-1] + 60]
            ok("alarm repeats at least every 10 min below 20 %", all(g <= 660 for g in gaps) and len(alarms) >= 2,
               f"{len(alarms)} alarms")

    # ================= scenario expectations
    sub_w = [w for w in outw if w["opt"].startswith("Solar")]
    reasons = lambda bit: any(s["reasons"] & bit for s in samples)
    changes = [w for w in outw if not (w["t"] < 40 and w["opt"].startswith("Battery"))]
    if name == "sunny_full":
        ok("sunny forecast -> sunny reserve 18/25 %", all(s["res_sw"] == 18 and s["res_ret"] == 25 for s in samples[2:]))
        night_heater = [x for x in samples if hhmm(x["clock"]) == "20:05"]
        ok("2 kW heater at 20:00: NIGHT only if SOC < 70 % (here " +
           (f"{night_heater[0]['soc']:.0f} %" if night_heater else "?") + ")",
           bool(night_heater) and bool(night_heater[0]["reasons"] & 4) == (night_heater[0]["soc_r"] < 70))
        ok("no grid-charging on a sunny day above 15 %", not any(s["charging"] for s in samples))
    if name == "cloudy_charge":
        ok("cloudy forecast -> cloudy reserve 25/30 %", all(s["cloudy"] and s["res_sw"] == 25 for s in samples[2:]))
        ok("grid-charges (Solar and utility) because cloudy and SOC < 37 %",
           any(w["opt"] == "Solar and utility" for w in chgw), ", ".join(f"{clock(w['t'])} {w['opt']}" for w in chgw[:3]))
        top = max((s["soc"] for s in samples if s["charging"]), default=0)
        ok("stops grid-charging at the 40 % target", 39 <= top <= 42, f"max SOC while charging {top:.1f} %")
    if name == "emergency":
        ok("LOW -> grid", reasons(1) and bool(sub_w))
        ok("emergency charge starts (< 15 %) at fast current 20 A",
           any(w["opt"] == "20" for w in chgw), ", ".join(f"{clock(w['t'])} {w['opt']}" for w in chgw[:4]))
        top = max((s["soc"] for s in samples if s["charging"]), default=0)
        ok("emergency charge stops at 25 %", 24 <= top <= 27, f"max SOC while charging {top:.1f} %")
    if name == "overnight":
        ok("overnight rule engages at night", reasons(8),
           f"first OVN {next((hhmm(s['clock']) for s in samples if s['reasons'] & 8), '-')}")
        last_ovn = max((s["t"] for s in samples if s["reasons"] & 8), default=None)
        ok("overnight rule releases before the morning", last_ovn is not None and
           hhmm(t0 + last_ovn / 60) < "06:50", f"last OVN {hhmm(t0 + last_ovn / 60) if last_ovn else '-'}")
        morning = [s for s in samples if hhmm(s["clock"]) == "08:20"]
        ok("battery >= floor (10 %) when the sun becomes useful", bool(morning) and morning[0]["soc"] >= 10,
           f"SOC at 08:20 {morning[0]['soc']:.1f} %" if morning else "")
        ok("battery did not hit LOW overnight", not reasons(1))
    if name == "heavy_load_day":
        ok("2.8 kW with SOC < 80 % and PV < 1.2 kW -> grid after 6 s (HIGH)",
           any(w["opt"].startswith("Solar") and 4 * 3600 + 6 <= w["t"] <= 4 * 3600 + 15 for w in outw),
           ", ".join(f"{clock(w['t'])} {w['opt'][:5]}" for w in changes[:4]))
        ok("back to battery 45 s after the load drops (min 3 min on grid already met)",
           any(w["opt"].startswith("Battery") and 4 * 3600 + 600 + 45 <= w["t"] <= 4 * 3600 + 600 + 62 for w in outw))
    if name == "grid_outage":
        ok("grid-lost / alarm tune at 19:00", any(t["name"] in ("gridlost", "alarm") and 3600 <= t["t"] <= 3700 for t in tunes))
        ok("runtime or morning warning shown without grid",
           any("battery" in n["msg"] for n in notes), next((n["msg"] for n in notes if "battery" in n["msg"]), ""))
    if name in ("soc_glitch", "sunny_dishwasher"):
        ok("stays on battery the whole time", not changes, ", ".join(f"{clock(w['t'])} {w['opt']}" for w in changes[:4]))
    if name == "soc_glitch":
        ok("30 s 0 % glitch: no grid switch, no emergency charge", not sub_w and not any(s["charging"] for s in samples))
    if name == "link_loss":
        ok("nothing written during the 3 h link loss", not [w for w in allw if 120 * 60 <= w["t"] < 300 * 60])
    if name == "no_clock":
        ok("no clock: NIGHT and OVERNIGHT stay off", not reasons(4) and not reasons(8))
        ok("no clock: battery still protected (LOW or grid-charge)", reasons(1) or reasons(16))
    if name == "boot_low":
        ok("SOC 12 % at boot -> grid after 30 s settle + 60 s delay", bool(sub_w) and 85 <= sub_w[0]["t"] <= 125,
           f"first SUB at t={sub_w[0]['t']:.0f}s" if sub_w else "never")
    if name == "observe":
        ok("observe-only still decides (would go to grid)", any(s["want_sub"] for s in samples))
    if name == "write_fail":
        ignored = [w for w in outw if not w["taken"]]
        ok("retries once 30 s after an ignored write", len(ignored) >= 2 and 29 <= ignored[1]["t"] - ignored[0]["t"] <= 33,
           ", ".join(clock(w["t"]) for w in ignored[:4]))
        ok("fault alarm after the retry also failed", any("did not accept" in n["msg"] for n in notes))
        ok("recovers when the inverter accepts again (fault clears, on grid)",
           samples[-1]["mode"] == "SUB" and not samples[-1]["fault"])
    if name == "no_internet":
        first = samples[2]
        ok("no forecast + no history -> treated as cloudy", first["cloudy"] and first["res_sw"] == 25)
        later = [s for s in samples if hhmm(s["clock"]) == "16:00"]
        ok("after 15:00 uses today's measured solar (sunny day -> sunny reserve)",
           bool(later) and not later[0]["cloudy"] and later[0]["res_sw"] == 18,
           f"plan_fc {later[0]['plan_fc']:.1f} kWh" if later else "")
    end = next(e for e in ev if e["ev"] == "end")
    return name, start["desc"], res, end, len(outw), len(chgw)


def main():
    total = fails = 0
    for path in sorted(glob.glob(os.path.join(sys.argv[1], "*.jsonl"))):
        ev = [json.loads(l) for l in open(path) if l.startswith("{")]
        name, desc, res, end, nw, nc = check(ev)
        print(f"\n== {name}: {desc}")
        print(f"   end SOC {end['soc']:.0f} %, grid {end['grid_wh'] / 1000:.2f} kWh, blackout {end['unmet_wh']:.0f} Wh, "
              f"{nw} output writes, {nc} charger writes")
        for status, label, detail in res:
            total += 1
            fails += status == "FAIL"
            print(f"   [{status}] {label}" + (f"  ({detail})" if detail else ""))
    print(f"\nTOTAL: {total - fails}/{total} checks passed, {fails} failed")


main()
