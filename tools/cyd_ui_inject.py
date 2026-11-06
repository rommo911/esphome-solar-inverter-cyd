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
for sid in ("set_ui", "show_help"):             # generated together with ui_refresh_values
    if f"  - id: {sid}\n" not in s:
        continue
    a0 = s.index(f"  - id: {sid}\n")
    while s[:a0].endswith("\n") and s[:a0].rstrip("\n").rsplit("\n", 1)[-1].lstrip().startswith("#"):
        a0 = s[:a0].rstrip("\n").rfind("\n") + 1
    b0 = s.index("\n  - id: ", s.index(f"  - id: {sid}\n") + 5) + 1
    s = s[:a0] + s[b0:]
start = s.index("  - id: ui_refresh_values\n")
b = s.index("\n  - id: ", start + 5) + 1          # end = next script
a = start
if s[:a].endswith("N/A when there is no fresh inverter data.\n"):     # its generated comment line
    a = s[:a - 1].rfind("\n") + 1
s = s[:a] + open(script_path).read() + "\n" + s[b:]
open(path, "w").write(s)
print("ok")
