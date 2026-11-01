"""Replace the lvgl: section and the ui_refresh_values script in inverter-cyd.yaml with the
output of cyd_ui.py (`yaml` and `script` commands).

  python3 cyd_ui_inject.py inverter-cyd.yaml LVGL_YAML SCRIPT_YAML
"""
import sys

path, lvgl_path, script_path = sys.argv[1:4]
s = open(path).read()
a = s.index("\nlvgl:\n") + 1
b = s.index("# -----------------------------------------------------------------------------\n# SENSORS")
s = s[:a] + open(lvgl_path).read() + "\n" + s[b:]
start = s.index("  - id: ui_refresh_values\n")
b = s.index("\n  - id: ", start + 5) + 1          # end = next script
a = start
if s[:a].endswith("N/A when there is no fresh inverter data.\n"):     # its generated comment line
    a = s[:a - 1].rfind("\n") + 1
s = s[:a] + open(script_path).read() + "\n" + s[b:]
open(path, "w").write(s)
print("ok")
