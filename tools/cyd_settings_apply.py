"""Regenerate the settings in inverter-cyd.yaml from cyd_settings.py:
the number: and switch: sections, the ui_sync_all script and the restore_defaults script.
The controller's settings are created by the solar_autopilot component itself (same ids and
names, see components/solar_autopilot/settings_keys.py); only the others go to number: / switch:.

  python3 cyd_settings_apply.py inverter-cyd.yaml

After adding a setting here, also give it a screen row in cyd_ui.py (if it should be on screen)
and re-run cyd_ui.py yaml/script + cyd_ui_inject.py.
"""
import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from cyd_settings import NUMBERS, SWITCHES, VIRTUAL_NIDS  # noqa: E402

_keys = {}
exec(open(__file__.rsplit("/", 1)[0] + "/../components/solar_autopilot/settings_keys.py").read(), _keys)
COMPONENT_IDS = {v[0] for v in _keys["NUMBERS"].values()} | {v[0] for v in _keys["SWITCHES"].values()}

path = sys.argv[1]
s = open(path).read()


def rep(old, new, count=1):
    global s
    if s.count(old) != count:
        sys.exit(f"expected {count} x {old[:90]!r}, found {s.count(old)}")
    s = s.replace(old, new)


def section_span(name):
    a = s.index("\n" + name + ":\n") + 1
    b = a + re.search(r"\n[a-z_]+:\n", s[a:]).start() + 1
    return a, b


def script_span(sid):
    """From '  - id: sid' to the next script, leaving that script's comment lines alone."""
    a = s.index(f"  - id: {sid}\n")
    m = re.search(r"\n  - id: |\n\S", s[a + 5:])
    b = a + 5 + m.start() + 1
    while True:            # step back over blank / comment lines that belong to the next item
        prev = s[:b - 1].rfind("\n") + 1
        line = s[prev:b - 1]
        if line.strip() == "" or line.lstrip().startswith("#"):
            b = prev
        else:
            return a, b


def drop_script(sid):
    global s
    a, b = script_span(sid)
    # also drop comment lines directly above
    while s[:a].endswith("\n") and s[:a].rstrip("\n").rsplit("\n", 1)[-1].lstrip().startswith("#"):
        a = s[:a].rstrip("\n").rfind("\n") + 1
    s = s[:a] + s[b:]


# ------------------------------------------------------------------ settings
def number_yaml(n):
    nid, name, unit, lo, hi, st, dv, label, fmt, kind = n
    y = f"""  - platform: template
    id: {nid}
    name: "{name}"
    entity_category: config
    unit_of_measurement: "{unit}"
    mode: box
    min_value: {lo}
    max_value: {hi}
    step: {st}
    initial_value: {dv}
    optimistic: true
    restore_value: true
"""
    if kind == "led":
        y += f"""    on_value:
      - lambda: 'id(led_{nid[-1]}).set_max_power(x / 100.0f);'
"""
    elif nid in VIRTUAL_NIDS:      # shown on the shared settings page: refresh its values
        y += """    on_value:
      - if:
          condition:
            lambda: 'return id(boot_ms) != 0;'
          then:
            - script.execute: { id: set_ui, what: 1, slot: 0, dir: 0 }
"""
    elif label:
        y += f"""    on_value:
      - if:
          condition:
            lambda: 'return id(boot_ms) != 0;'
          then:
            - lvgl.label.update: {{ id: lb_{nid}, text: !lambda 'return str_sprintf("{fmt}", x);' }}
"""
    return y


def switch_yaml(sw):
    sid, name, on, widget, icon, extra_off = sw
    y = f"""  - platform: template
    id: {sid}
    name: "{name}"
"""
    if icon:
        y += f"    icon: {icon}\n"
    y += f"""    entity_category: config
    optimistic: true
    restore_mode: RESTORE_DEFAULT_{'ON' if on else 'OFF'}
"""
    if widget:
        y += f"""    on_turn_on:
      - if:
          condition:
            lambda: 'return id(boot_ms) != 0;'
          then:
            - lvgl.widget.update: {{ id: {widget}, state: {{ checked: true }} }}
    on_turn_off:
      - if:
          condition:
            lambda: 'return id(boot_ms) != 0;'
          then:
            - lvgl.widget.update: {{ id: {widget}, state: {{ checked: false }} }}
{extra_off}"""
    return y


a, b = section_span("number")
s = s[:a] + ("number:\n  # Generated from tools/cyd_settings.py: display / LED settings. The controller's settings\n"
             "  # are created by solar_autopilot (on_setting_change refreshes the screen).\n"
             + "".join(number_yaml(n) for n in NUMBERS if n[0] not in COMPONENT_IDS) + "\n") + s[b:]
a, b = section_span("switch")
s = s[:a] + ("switch:\n  # Generated from tools/cyd_settings.py (the controller's switches: solar_autopilot).\n"
             + "".join(switch_yaml(w) for w in SWITCHES if w[0] not in COMPONENT_IDS) + "\n") + s[b:]

# ui_sync_all / restore_defaults
a, b = script_span("ui_sync_all")
sync = "  - id: ui_sync_all\n    then:\n"
sync += "      - script.execute: { id: set_ui, what: 1, slot: 0, dir: 0 }\n"
for n in NUMBERS:
    if n[7] and n[0] not in VIRTUAL_NIDS:
        sync += (f"      - lvgl.label.update: {{ id: lb_{n[0]}, text: !lambda "
                 f"'return str_sprintf(\"{n[8]}\", id({n[0]}).state);' }}\n")
for w in SWITCHES:
    if w[3]:
        sync += f"      - lvgl.widget.update: {{ id: {w[3]}, state: {{ checked: !lambda 'return id({w[0]}).state;' }} }}\n"
s = s[:a] + sync + s[b:]
a, b = script_span("restore_defaults")
rd = ("  - id: restore_defaults\n    then:\n"
      + "".join(f"      - number.set: {{ id: {n[0]}, value: {n[6]} }}\n" for n in NUMBERS if not n[9])
      + "".join(f"      - switch.turn_{'on' if w[2] else 'off'}: {w[0]}\n" for w in SWITCHES))
s = s[:a] + rd + s[b:]


open(path, "w").write(s)
print("settings regenerated")
