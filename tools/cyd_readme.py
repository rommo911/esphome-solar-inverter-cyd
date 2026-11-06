"""Regenerate the settings tables in README.md from cyd_settings.py (between the markers
<!-- settings:begin --> and <!-- settings:end -->), so the documented defaults and ranges are
always the ones in the firmware.

  python3 tools/cyd_readme.py README.md
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cyd_settings import NUMBERS, SWITCHES  # noqa: E402

# (group title, first id of the group) in the order of cyd_settings.NUMBERS
GROUPS = [
    ("Reserve planner and forecast", "n_cloudy_kwh"),
    ("Charger manager", "n_chg_target"),
    ("Overnight rule", "n_ovn_floor"),
    ("Timing and float voltage", "n_low_delay"),
    ("High-load rule", "n_high_on_w"),
    ("Night-load rule", "n_night_on_w"),
    ("Battery and solar array", "n_batt_kwh"),
    ("Sound", "n_quiet_start"),
    ("Display (calibration)", "n_bl_min"),
]


def fmt(v):
    return f"{v:g}"


def tables():
    starts = {first: title for title, first in GROUPS}
    out, rows = [], []
    for n in NUMBERS:
        nid, name, unit, lo, hi, st, dv, label, _, kind = n
        if nid in starts:
            if rows:
                out += rows + [""]
            rows = [f"**{starts[nid]}**", "",
                    "| Setting (HA name) | Default | Range | Step | On screen | Kept by Restore defaults |",
                    "|---|---|---|---|---|---|"]
        unit_s = f" {unit}" if unit and unit != "°" else unit
        rows.append(f"| {name} | {fmt(dv)}{unit_s} | {fmt(lo)} to {fmt(hi)} | {fmt(st)} | "
                    f"{'yes' if label else 'no (HA only)'} | {'yes' if kind else 'no'} |")
    out += rows + ["", "**Switches**", "",
                   "| Switch (HA name) | Default | On screen |", "|---|---|---|"]
    for sid, name, on, widget, _, _ in SWITCHES:
        out.append(f"| {name} | {'on' if on else 'off'} | {'yes' if widget else 'no'} |")
    return "\n".join(out)


path = sys.argv[1]
s = open(path).read()
a = s.index("<!-- settings:begin -->") + len("<!-- settings:begin -->")
b = s.index("<!-- settings:end -->")
s = s[:a] + "\n" + tables() + "\n" + s[b:]
open(path, "w").write(s)
print("settings tables regenerated")
