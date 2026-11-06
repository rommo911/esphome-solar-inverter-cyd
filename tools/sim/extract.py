"""Pull the automation lambdas and setting defaults out of inverter-cyd.yaml, verbatim,
and write gen/lambdas.inc + gen/entities.inc for the C++ simulator (sim.cpp).

Lambdas are found by their first line marker "// @sim:<name>"; a few small ones by location.

  python3 extract.py ../../inverter-cyd.yaml OUTDIR
"""
import os
import re
import sys

import yaml

src_path, out = sys.argv[1], sys.argv[2]
text = open(src_path).read()

subs = dict(re.findall(r'^  (\w+): "?([^"#\n]*?)"?\s*(?:#.*)?$',
                       text[text.index("substitutions:"):text.index("\nesphome:")], re.M))
text = re.sub(r"\$\{(\w+)\}", lambda m: subs[m.group(1)], text)


class Loader(yaml.SafeLoader):
    pass


class Lambda(str):
    pass


Loader.add_constructor("!lambda", lambda l, n: Lambda(l.construct_scalar(n)))
for tag in ("!secret", "!include"):
    Loader.add_constructor(tag, lambda l, n: l.construct_scalar(n))
cfg = yaml.load(text, Loader=Loader)

lambdas = {}


def walk(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "lambda" and isinstance(v, str):
                m = re.match(r"\s*// @sim:(\w+)", v)
                if m:
                    lambdas[m.group(1)] = v
            walk(v)
    elif isinstance(node, list):
        for v in node:
            walk(v)


walk(cfg)
core = "solar_autopilot" in cfg          # logic in the C++ core: only the YAML-side lambdas remain


def grab(name, fn):
    try:
        lambdas[name] = fn()
    except (StopIteration, KeyError, IndexError, TypeError):
        pass


bsg = next(b for b in cfg["binary_sensor"] if b.get("id") == "bs_grid")
grab("grid_raw", lambda: bsg["lambda"])
grab("grid_cond", lambda: bsg["on_release"][0]["if"]["condition"]["lambda"])
pip_bs = next(b for b in cfg["binary_sensor"] if b.get("platform") == "pipsolar")
grab("float_cond", lambda: pip_bs["charging_to_floating_mode"]["on_press"][0]["if"]["condition"]["lambda"])
inv = next(b for b in cfg["binary_sensor"] if b.get("id") == "inv_link")
grab("inv_link", lambda: inv["lambda"])

SIGS = {
    "controller": "void L_controller()", "planner": "void L_planner()", "alarms": "void L_alarms()",
    "alarm_soc": "void L_alarm_soc()",
    "play_tune": "void L_play_tune(std::string tune, int prio, bool critical)",
    "grid_lost": "void L_grid_lost()", "grid_raw": "bool L_grid_raw()", "grid_cond": "bool L_grid_cond()",
    "float_cond": "bool L_float_cond()", "inv_link": "bool L_inv_link()",
}
if core:
    SIGS = {k: v for k, v in SIGS.items() if k in ("play_tune", "grid_raw")}
missing = set(SIGS) - set(lambdas)
assert not missing, f"not found in YAML: {missing}"
with open(os.path.join(out, "lambdas.inc"), "w") as f:
    f.write("// GENERATED from inverter-cyd.yaml by extract.py - do not edit\n")
    for k, sig in SIGS.items():
        f.write(f"{sig} {{\n{lambdas[k]}\n}}\n\n")

with open(os.path.join(out, "entities.inc"), "w") as f:
    f.write("// GENERATED from inverter-cyd.yaml by extract.py - do not edit\n")
    for n in cfg["number"]:
        f.write(f"Num {n['id']}{{{float(n['initial_value'])}f}};\n")
    for s in cfg["switch"]:
        on = str(s.get("restore_mode", "")).endswith("_ON")
        f.write(f"Sw {s['id']}{{{'true' if on else 'false'}}};\n")
    for g in cfg["globals"]:
        init = g.get("initial_value")
        f.write(f"{g['type']} {g['id']}" + (f" = {init};\n" if init is not None else "{};\n"))
print("extracted:", ", ".join(sorted(SIGS)), "(core mode)" if core else "")
