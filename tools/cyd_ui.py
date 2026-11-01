"""CYD UI: one layout description -> LVGL YAML, overlap/fit check, PNG previews.

  python3 ui.py yaml    FONTDIR          lvgl: section
  python3 ui.py script  FONTDIR          ui_refresh_values script (value chips on Home/Power/Info)
  python3 ui.py formats FONTDIR          number id <TAB> value format (for on_value / ui_sync_all)
  python3 ui.py check   FONTDIR          overlap / bounds / text-fit report
  python3 ui.py render  FONTDIR OUTDIR   PNG preview per page (needs Pillow)
FONTDIR holds LVGL's lv_font_montserrat_NN.c files.
"""
import os
import re
import sys

W, H, NAV_Y = 320, 240, 200          # content area is y < NAV_Y

# ------------------------------------------------------------------ palette (dark)
BG = 0x10161D          # page background
NAME = 0x9AA8B5        # setting / reading names
VAL = 0xFFCA28         # values (amber)
CHIP_BG = 0x1C2833     # value chip
CHIP_BORDER = 0x34506A
TITLE = 0x4FC3F7       # page titles
BTN = 0x26323F         # normal buttons
BTN_TXT = 0xECEFF1
BTN_PRESS = 0x1565C0
NAV_BG = 0x0A0F14
NAV_BTN = 0x1A2735
NAV_TXT = 0x90CAF9
GOOD, BAD = 0x43A047, 0xE53935
BATT_BTN, GRID_BTN = 0x2E7D32, 0xE65100
SW_OFF = 0x37474F
PV_COL, LOAD_COL = 0xFFB300, 0x29B6F6   # gauge rings: battery = GOOD (green)
RING = 14                                # ring width 10 + gap 4
PV_MAX_W, LOAD_MAX_W = 4000, 4000        # full scale of the solar / load rings
CHIP_PX, CHIP_PY = 7, 3   # chip padding (left/right, top/bottom)


# ------------------------------------------------------------------ font metrics
class Font:
    def __init__(self, path):
        src = open(path).read()
        self.lh = int(re.search(r"\.line_height = (\d+)", src).group(1))
        self.base = int(re.search(r"\.base_line = (\d+)", src).group(1))
        self.glyphs = [tuple(int(v) for v in m) for m in re.findall(
            r"\{\.bitmap_index = (\d+), \.adv_w = (\d+), \.box_w = (\d+), \.box_h = (\d+), "
            r"\.ofs_x = (-?\d+), \.ofs_y = (-?\d+)\}", src)]
        bm = src[src.index("glyph_bitmap[]"):]
        bm = bm[:bm.index("};")]
        self.bitmap = bytes(int(h, 16) for h in re.findall(r"0x([0-9a-fA-F]{1,2})\b", bm))
        lists = {}
        for name, body in re.findall(r"unicode_list_(\d+)\[\] = \{([^}]*)\}", src):
            lists[name] = [int(v, 16) for v in re.findall(r"0x([0-9a-fA-F]+)", body)]
        self.cmap = {}
        for rs, rl, gs, ul in re.findall(
                r"\.range_start = (\d+), \.range_length = (\d+), \.glyph_id_start = (\d+),\s*"
                r"\.unicode_list = (\w+)", src):
            rs, rl, gs = int(rs), int(rl), int(gs)
            if ul == "NULL":
                for i in range(rl):
                    self.cmap[rs + i] = gs + i
            else:
                for i, d in enumerate(lists[ul.split("_")[-1]]):
                    self.cmap[rs + d] = gs + i

    def glyph(self, ch):
        gid = self.cmap.get(ord(ch))
        return self.glyphs[gid] if gid is not None else None

    def adv(self, ch):
        g = self.glyph(ch)
        return g[1] / 16 if g else self.lh

    def width(self, line):
        return sum(self.adv(c) for c in line)


FONTS = {}


def load_fonts(d):
    for n in (14, 16, 18, 20, 28):
        FONTS[n] = Font(os.path.join(d, f"lv_font_montserrat_{n}.c"))


def u(s):
    """YAML-escaped symbols (\\uF053) -> real characters, for measuring."""
    return s.encode().decode("unicode_escape") if "\\u" in s else s


def wrap(text, font, width):
    out = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            cand = word if not line else line + " " + word
            if width is None or font.width(cand) <= width or not line:
                line = cand
            else:
                out.append(line)
                line = word
        out.append(line)
    return out


# ------------------------------------------------------------------ layout DSL
def label(x, y, text, font=14, w=None, id=None, sample=None, align="LEFT", wrap_=False,
          color=NAME, line_space=0, dots=False, chip=False):
    return dict(t="label", x=x, y=y, text=text, font=font, w=w, id=id, sample=sample or text,
                align=align, wrap=wrap_, color=color, ls=line_space, dots=dots, chip=chip)


def chip(x, y, w, id, sample, font=18, align="RIGHT", text="N/A", dots=False):
    """Highlighted value: amber text in a dark rounded box."""
    return label(x, y, text, font=font, w=w, id=id, sample=sample, align=align, color=VAL,
                 chip=True, dots=dots)


def bm(x, y, w, h, buttons, font=16, id=None, item_bg=None, item_txt=None):
    return dict(t="bm", x=x, y=y, w=w, h=h, buttons=buttons, font=font, id=id,
                item_bg=item_bg, item_txt=item_txt)


def button(x, y, w, h, text, actions, bg, font=18):
    return dict(t="button", x=x, y=y, w=w, h=h, text=text, actions=actions, bg=bg, font=font)


def switch(x, y, lvid, sw, w=56, h=30):
    return dict(t="switch", x=x, y=y, w=w, h=h, id=lvid, sw=sw)


def sw_cell(x, y, cw, ch, text, lvid, sw, font=16):
    sh = min(30, ch - 6)
    return [label(x, y + (ch - FONTS[font].lh) // 2, text, font=font, color=BTN_TXT),
            switch(x + cw - 56, y + (ch - sh) // 2, lvid, sw, h=sh)]


# setting name / value format (value goes in the chip): from cyd_settings.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cyd_settings import NUMBERS  # noqa: E402
FMT = {n[0]: (n[7], n[8]) for n in NUMBERS if n[7]}
MAXV = {n[0]: n[4] for n in NUMBERS}

NAME_W = 146                        # name column
CHIP_X, CHIP_W = 156, 86            # value chip
BTN_X, BTN_W = 246, 72              # - / + buttons


def num_rows(nids, y0=42, y1=NAV_Y - 2):
    """Rows of  name | [value] | [-][+]  spread over y0..y1, one font for the whole page."""
    out, n = [], len(nids)
    pitch = (y1 - y0) // n
    bh = min(pitch - 4, 50)

    def fits(f):
        for nid in nids:
            name, vf = FMT[nid]
            lines = wrap(name, FONTS[f], NAME_W)
            if len(lines) > 2 or len(lines) * FONTS[f].lh > pitch - 2:
                return False
            if any(FONTS[f].width(l) > NAME_W for l in lines):
                return False
        return True

    f = next(f for f in (18, 16, 14) if fits(f))
    vfont = next(v for v in (20, 18, 16, 14) if v <= f + 2 and all(
        FONTS[v].width(FMT[nid][1] % MAXV.get(nid, 60)) <= CHIP_W - 2 * CHIP_PX for nid in nids))
    for i, nid in enumerate(nids):
        y = y0 + i * pitch
        name, vf = FMT[nid]
        nl = len(wrap(name, FONTS[f], NAME_W))
        th = nl * FONTS[f].lh
        ch = FONTS[vfont].lh + 2 * CHIP_PY
        out.append(label(6, y + (pitch - th) // 2, name, font=f, w=NAME_W, wrap_=True))
        out.append(chip(CHIP_X, y + (pitch - ch) // 2, CHIP_W, "lb_" + nid,
                        vf % MAXV.get(nid, 60), font=vfont, align="CENTER", text="--"))
        out.append(bm(BTN_X, y + (pitch - bh) // 2, BTN_W, bh, [
            ("\\uF068", [f"number.decrement: {{ id: {nid}, cycle: false }}"]),
            ("\\uF067", [f"number.increment: {{ id: {nid}, cycle: false }}"])], font=16))
    return out


INFOG = ["page_i_power", "page_i_proj", "page_i_energy", "page_i_sys"]
SETUP = ["page_s_res", "page_s_plan", "page_s_rules", "page_s_sound", "page_s_disp"]
ADV = ["page_a_high1", "page_a_high2", "page_a_night1", "page_a_night2", "page_a_night3",
       "page_a_ovn1", "page_a_ovn2", "page_a_chg1", "page_a_chg2", "page_a_timing",
       "page_a_batt", "page_a_pv", "page_a_reset"]
TITLES = {
    "page_s_res": "Battery reserve", "page_s_plan": "Forecast & charging", "page_s_rules": "Rules",
    "page_s_sound": "Sound", "page_s_disp": "Display",
    "page_i_power": "Live power", "page_i_proj": "Projections", "page_i_energy": "Energy today",
    "page_i_sys": "System",
    "page_a_high1": "High load", "page_a_high2": "High load limits",
    "page_a_night1": "Night load on", "page_a_night2": "Night load off", "page_a_night3": "Night release 2",
    "page_a_ovn1": "Overnight", "page_a_ovn2": "Overnight sun delay",
    "page_a_chg1": "Grid charging", "page_a_chg2": "Charge current", "page_a_timing": "Timing",
    "page_a_batt": "Battery capacity", "page_a_pv": "Solar panels", "page_a_reset": "Restore defaults",
}


def header(pid):
    group, name = next((g, n) for g, n in ((INFOG, "INFO"), (SETUP, "SETUP"), (ADV, "ADVANCED"))
                       if pid in g)
    i = group.index(pid)
    return [label(6, 3, f"{name} {i + 1}/{len(group)}", font=14, color=NAME),
            label(6, 19, TITLES[pid], font=18, color=TITLE),
            bm(240, 2, 78, 36, [("\\uF053", [f"lvgl.page.show: {group[i - 1]}"]),
                                ("\\uF054", [f"lvgl.page.show: {group[(i + 1) % len(group)]}"])])]


GUARD = ("if:\n  condition: {{ binary_sensor.is_on: inv_link }}\n  then:\n"
         "    - switch.turn_off: auto_ctl\n"
         "    - select.set: {{ id: sel_output_source_priority, option: \"{opt}\" }}\n"
         "  else:\n    - script.execute: {{ id: toast, msg: \"No inverter link - not sent\" }}")

# value chips refreshed every 2 s: id -> (C++ value expr, printf format, gated by inverter link)
LIVE = {
    "v_load": ("id(s_load_power).state", "%.0f W", True),
    "v_pv": ("id(s_pv_power).state", "%.0f W", True),
    "v_batt": ("id(s_soc).state", "%.0f %%", True),
    "v_grid": ("id(grid_power).state", "%.0f W", True),
    "p_pv": ("id(s_pv_power).state", "%.0f W", True),
    "p_load": ("id(s_load_power).state", "%.0f W", True),
    "p_batt": ("id(batt_power).state", "%+.0f W", True),
    "p_grid": ("id(grid_power).state", "%.0f W", True),
    "p_solar": ("id(e_solar_today).state", "%.2f kWh", False),
    "p_bv": ("id(s_batt_v).state", "%.1f V", True),
    "p_soc": ("id(s_soc).state", "%.0f %%", True),
    "p_gv": ("id(s_grid_v).state", "%.0f V", True),
    "p_temp": ("id(s_heatsink).state", "%.0f °C", True),
    "i_rssi": ("id(s_rssi).state", "%.0f dBm", False),
    "e_solar": ("id(e_solar_today).state", "%.2f kWh", False),
    "e_load": ("id(e_load_today).state", "%.2f kWh", False),
    "e_grid": ("id(e_grid_today).state", "%.2f kWh", False),
    "e_chg": ("id(e_chg_today).state", "%.2f kWh", False),
    "e_dis": ("id(e_dis_today).state", "%.2f kWh", False),
}
_RT = ('float soc = id(s_soc).state, load = {load};\n'
       'if (!id(inv_link).state || isnan(soc) || isnan(load)) return std::string("N/A");\n'
       'float wh = std::max(0.0f, id(n_batt_kwh).state * 10.0f * (soc - id(n_empty_soc).state));\n'
       'float h = wh / std::max(load, 50.0f);\n'
       'if (h >= 99.0f) return std::string("> 99 h");\n'
       'return str_sprintf("%dh %02dm", (int) h, (int) ((h - (int) h) * 60));')
_FC = 'float v = id({g});\nreturn isnan(v) ? std::string("N/A") : str_sprintf("%.1f kWh", v);'
# Projections page values: id -> C++ returning std::string
PROJ = {
    "x_left": ('float soc = id(s_soc).state;\n'
               'if (!id(inv_link).state || isnan(soc)) return std::string("N/A");\n'
               'return str_sprintf("%.2f kWh", std::max(0.0f, id(n_batt_kwh).state * (soc - id(n_empty_soc).state) / 100.0f));'),
    "x_rt_now": _RT.format(load="id(s_load_power).state"),
    "x_rt_1h": _RT.format(load="id(s_load_1h).state"),
    "x_fc_now": ('const auto &c = id(fc_curve);\n'
                 'auto t = id(sntp_time).now();\n'
                 'if (c.empty() || !t.is_valid()) return std::string("N/A");\n'
                 'int m = t.hour * 60 + t.minute;\n'
                 'float v = 0;  // before the first / after the last point of the day = night\n'
                 'for (size_t i = 1; i < c.size(); i++) {\n'
                 '  if (m >= c[i - 1].first && m <= c[i].first) {\n'
                 '    float f = float(m - c[i - 1].first) / std::max(1, c[i].first - c[i - 1].first);\n'
                 '    v = c[i - 1].second + f * (c[i].second - c[i - 1].second);\n'
                 '    break;\n'
                 '  }\n'
                 '}\n'
                 'return str_sprintf("%.0f W", v);'),
    "x_fc_today": _FC.format(g="fc_today_kwh"),
    "x_fc_tmrw": _FC.format(g="fc_tomorrow_kwh"),
    "lbl_fc_upd": 'return id(fc_updated).empty() ? std::string("not fetched") : "updated " + id(fc_updated);',
}
# Info page rows: (name, id, sample, C++ returning std::string)
INFO = [
    ("Firmware", "i_fw", "ESPHome 2026.10.1", 'return std::string("ESPHome " ESPHOME_VERSION);'),
    ("Built", "i_built", "Nov 11 2026 23:59:59", 'return std::string(__DATE__ " " __TIME__);'),
    ("WiFi", "i_wifi", "MyNetworkName-5G", 'return id(t_ssid).has_state() ? id(t_ssid).state : std::string("--");'),
    ("IP", "i_ip", "192.168.100.100", 'return id(t_ip).has_state() ? id(t_ip).state : std::string("--");'),
    ("Signal", "i_rssi", "-100 dBm", None),
    ("Uptime", "i_up", "99d 23h 59m",
     'uint32_t s = millis() / 1000;\nreturn str_sprintf("%ud %02uh %02um", s / 86400, (s / 3600) % 24, (s / 60) % 60);'),
    ("Memory", "i_mem", "free 123 KB, block 99 KB",
     'return str_sprintf("free %u KB, block %u KB", (unsigned) (heap_caps_get_free_size(MALLOC_CAP_8BIT) / 1024),\n'
     '                   (unsigned) (heap_caps_get_largest_free_block(MALLOC_CAP_8BIT) / 1024));'),
]

RESET_ACTION = ("if:\n  condition:\n"
                "    lambda: 'return id(reset_armed) != 0 && millis() - id(reset_armed) < 5000;'\n"
                "  then:\n    - lambda: 'id(reset_armed) = 0;'\n    - script.execute: restore_defaults\n"
                "    - script.execute: { id: toast, msg: \"Defaults restored\" }\n"
                "  else:\n    - lambda: 'id(reset_armed) = millis();'\n"
                "    - script.execute: { id: toast, msg: \"Tap again within 5 s to restore defaults\" }")

PAGES = {}


def build():
    lh18, lh20 = FONTS[18].lh, FONTS[20].lh
    ch20 = lh20 + 2 * CHIP_PY
    # ---------------- Home
    # three concentric gauges: outer = battery %, middle = solar, inner = load
    p = [dict(t="arc", id="arc_soc", x=2, y=2, w=140, h=140, color=GOOD, max=100),
         dict(t="arc", id="arc_pv", x=2 + RING, y=2 + RING, w=140 - 2 * RING, h=140 - 2 * RING,
              color=PV_COL, max=100),
         dict(t="arc", id="arc_load", x=2 + 2 * RING, y=2 + 2 * RING, w=140 - 4 * RING,
              h=140 - 4 * RING, color=LOAD_COL, max=LOAD_MAX_W),
         label(2, 2 + 70 - FONTS[20].lh // 2, "N/A", font=20, w=140, id="lbl_soc",
               sample="100%", align="CENTER", color=0xFFFFFF)]
    for i, (nm, vid, smp, col) in enumerate([("Batt", "v_batt", "+12345 W", GOOD),
                                             ("PV", "v_pv", "12345 W", PV_COL),
                                             ("Load", "v_load", "12345 W", LOAD_COL),
                                             ("Grid", "v_grid", "12345 W", NAME)]):
        y = 4 + i * 35
        p += [label(150, y + (ch20 - lh18) // 2, nm, font=18, color=col),
              chip(202, y, 116, vid, smp, font=20)]
    p += [label(6, 146, "?", font=18, w=308, id="lbl_mode", dots=True, color=TITLE,
                sample="OBSERVE: SUB LOW HIGH NIGHT OVN CHG"),
          label(6, 175, "", font=16, id="lbl_status", sample="23:59  37/40%  sun 100%", color=NAME),
          label(212, 175, "INV", font=16, id="ic_inv", color=BAD),
          label(250, 175, "HA", font=16, id="ic_ha", color=BAD),
          label(292, 175, "\\uF1EB", font=16, id="ic_wifi", color=BAD, sample="")]
    PAGES["page_main"] = p

    # ---------------- Info 1/4: live power, 2 columns x 5 rows of  name [value]
    pw = header("page_i_power")
    left = [("PV", "p_pv", "12345 W"), ("Load", "p_load", "12345 W"), ("Batt", "p_batt", "+12345 W"),
            ("Grid", "p_grid", "12345 W"), ("Solar", "p_solar", "12.34 kWh")]
    right = [("Batt", "p_bv", "28.8 V"), ("SOC", "p_soc", "100 %"), ("Grid", "p_gv", "250 V"),
             ("Temp", "p_temp", "100 \u00b0C"), ("Data", "lbl_age", "99999s")]
    for i in range(5):
        y = 42 + i * 31
        nm, vid, smp = left[i]
        pw += [label(4, y + 4, nm, font=16), chip(52, y, 108, vid, smp, font=18)]
        nm, vid, smp = right[i]
        pw += [label(168, y + 4, nm, font=16), chip(220, y, 98, vid, smp, font=18)]
    PAGES["page_i_power"] = pw

    # ---------------- Info 2/4: projections (battery left | solar forecast)
    pr = header("page_i_proj")
    pr += [label(6, 42, "BATTERY", font=14, color=GOOD),
           label(166, 42, "SOLAR FORECAST", font=14, color=PV_COL)]
    for i, (nm, vid, smp) in enumerate([("Remaining", "x_left", "20.00 kWh"),
                                        ("Runtime at load now", "x_rt_now", "99h 59m"),
                                        ("Runtime at 1h avg", "x_rt_1h", "99h 59m")]):
        y = 58 + i * 47
        pr += [label(6, y, nm, font=14), chip(6, y + 16, 148, vid, smp, font=18, align="CENTER", text="--")]
    for i, (nm, vid, smp) in enumerate([("Now", "x_fc_now", "12345 W"), ("Today", "x_fc_today", "99.9 kWh"),
                                        ("Tomorrow", "x_fc_tmrw", "99.9 kWh")]):
        y = 58 + i * 47
        pr += [label(166, y, nm, font=14), chip(166, y + 16, 152, vid, smp, font=18, align="CENTER", text="--")]
    pr += [label(240, 58, "", font=14, w=78, id="lbl_fc_upd", align="RIGHT", sample="updated 23:59", dots=True)]
    PAGES["page_i_proj"] = pr

    # ---------------- Info 3/4: energy today (resets at midnight)
    en = header("page_i_energy")
    for i, (nm, vid, col) in enumerate([("Solar", "e_solar", PV_COL), ("Load", "e_load", LOAD_COL),
                                        ("Grid import", "e_grid", NAME), ("Batt charged", "e_chg", GOOD),
                                        ("Batt discharged", "e_dis", GOOD)]):
        y = 42 + i * 31
        en += [label(6, y + 4, nm, font=18, color=col), chip(178, y, 140, vid, "123.45 kWh", font=18)]
    PAGES["page_i_energy"] = en

    # ---------------- Info 4/4: system
    inf = header("page_i_sys")
    for i, (nm, iid, smp, _) in enumerate(INFO):
        y = 42 + i * 22
        inf += [label(6, y + CHIP_PY, nm, font=14),
                chip(78, y, 240, iid, smp, font=14, align="LEFT", text="--", dots=True)]
    PAGES["page_i_sys"] = inf

    # ---------------- Control
    c = sw_cell(6, 4, 148, 40, "Auto", "lv_auto_ctl", "auto_ctl", font=18)
    c += sw_cell(166, 4, 148, 40, "Observe", "lv_sw_observe", "sw_observe", font=18)
    c += [button(4, 50, 154, 50, "Battery (SBU)", [GUARD.format(opt="Battery first (SBU)")], BATT_BTN),
          button(162, 50, 154, 50, "Grid (SUB)", [GUARD.format(opt="Solar first (SUB)")], GRID_BTN),
          label(6, 112, "Mode", font=14),
          chip(68, 106, 250, "lbl_ctl_state", "Inverter SUB, plan SBU, cloudy", font=14, align="LEFT", text="--"),
          label(6, 144, "Charger", font=14),
          chip(68, 138, 250, "lbl_chg_state", "Grid charging, 20 A", font=14, align="LEFT", text="--"),
          label(6, 174, "Battery / Grid buttons turn Auto off.", font=14, w=312,
                dots=True)]
    PAGES["page_control"] = c

    # ---------------- Setup
    PAGES["page_s_res"] = header("page_s_res") + num_rows(
        ["n_sunny_sw", "n_sunny_ret", "n_cloudy_sw", "n_cloudy_ret"])
    PAGES["page_s_plan"] = header("page_s_plan") + num_rows(["n_cloudy_kwh", "n_chg_target"])
    r = header("page_s_rules")
    cells = [("Low batt", "lv_sw_rule_low", "sw_rule_low"),
             ("High load", "lv_sw_rule_high", "sw_rule_high"),
             ("Night load", "lv_sw_rule_night", "sw_rule_night"),
             ("Overnight", "lv_sw_rule_ovn", "sw_rule_ovn"),
             ("Charger", "lv_sw_rule_charge", "sw_rule_charge"),
             ("Float V", "lv_sw_rule_float", "sw_rule_float")]
    for i, (t, lv, sw) in enumerate(cells):
        r += sw_cell(6 if i % 2 == 0 else 166, 44 + (i // 2) * 52, 148, 50, t, lv, sw)
    PAGES["page_s_rules"] = r
    s = header("page_s_sound")
    s += sw_cell(6, 42, 148, 38, "Buzzer", "lv_sw_buzzer", "sw_buzzer")
    s += sw_cell(166, 42, 148, 38, "Quiet hrs", "lv_sw_quiet", "sw_quiet")
    s += num_rows(["n_quiet_start", "n_quiet_end"], y0=82, y1=156)
    s += [bm(4, 158, 312, 40, [
        ("\\uF028 Test tune", ["script.execute: { id: play_tune, tune: \"test\", prio: 1, critical: true }"]),
        ("\\uF026 Silence", ["rtttl.stop: { id: buzzer }", "lambda: 'id(tune_prio) = 0;'"])])]
    PAGES["page_s_sound"] = s
    d = header("page_s_disp")
    d += sw_cell(6, 42, 170, 32, "Auto bright", "lv_sw_autobl", "sw_autobl")
    d += [label(186, 49, "Light", font=14),
          chip(226, 44, 92, "lbl_ldr", "1.234 V", font=16, align="CENTER", text="--"),
          bm(4, 76, 312, 34, [
              ("Dark = now", ["number.set: { id: n_ldr_dark, value: !lambda 'return id(s_ldr).state;' }"]),
              ("Bright = now", ["number.set: { id: n_ldr_bright, value: !lambda 'return id(s_ldr).state;' }"])]),
          label(6, 113, "", font=14, w=312, id="lbl_ldr_cal", align="CENTER",
                sample="calibrated: dark 1.234 V, bright 1.234 V")]
    d += num_rows(["n_bl_min"], y0=130, y1=166)
    d += sw_cell(6, 166, 170, 32, "Touch dot", "lv_sw_touchdbg", "sw_touchdbg")
    PAGES["page_s_disp"] = d

    # ---------------- Advanced
    rows = {"page_a_high1": ["n_high_on_w", "n_high_on_s", "n_high_off_w", "n_high_off_s"],
            "page_a_high2": ["n_high_max_soc", "n_high_max_pv"],
            "page_a_night1": ["n_night_on_w", "n_night_on_s", "n_night_max_soc"],
            "page_a_night2": ["n_night_off_w", "n_night_off_s"],
            "page_a_night3": ["n_back_soc", "n_back_w", "n_back_s"],
            "page_a_ovn1": ["n_ovn_floor", "n_ovn_margin", "n_base_floor"],
            "page_a_ovn2": ["n_sun_delay_sunny", "n_sun_delay_cloudy"],
            "page_a_chg1": ["n_emerg_soc", "n_emerg_target", "n_fast_below"],
            "page_a_chg2": ["n_chg_fast_a", "n_chg_norm_a", "n_chg_margin"],
            "page_a_timing": ["n_low_delay", "n_min_sub", "n_float_v"],
            "page_a_batt": ["n_batt_kwh", "n_empty_soc"],
            "page_a_pv": ["n_pv_kwp", "n_pv_tilt", "n_pv_az"]}
    for pid in ADV[:-1]:
        PAGES[pid] = header(pid) + num_rows(rows[pid])
    PAGES["page_a_reset"] = header("page_a_reset") + [
        label(6, 46, "Sets every rule, threshold, sound and display setting back to its default.",
              font=16, w=308, wrap_=True, color=BTN_TXT),
        label(6, 86, "Keeps the touch and light-sensor calibration.", font=14, w=308, wrap_=True),
        button(40, 122, 240, 48, "Restore defaults", [RESET_ACTION], BAD),
        label(6, 176, "Tap twice within 5 s to confirm.", font=14, w=308, align="CENTER")]


NAV = [("\\uF015", "page_main"), ("\\uF0E7", "page_i_power"), ("\\uF011", "page_control"),
       ("\\uF013", "page_s_res"), ("\\uF0C9", "page_a_high1")]


# ------------------------------------------------------------------ geometry / check
def box(wd):
    if wd["t"] != "label":
        return wd["x"], wd["y"], wd["w"], wd["h"]
    f = FONTS[wd["font"]]
    pad_x = CHIP_PX if wd["chip"] else 0
    pad_y = CHIP_PY if wd["chip"] else 0
    inner = (wd["w"] - 2 * pad_x) if wd["w"] else None
    lines = wrap(u(wd["sample"]), f, inner if wd["wrap"] else None)
    if wd["dots"]:
        lines = lines[:1]
    w = wd["w"] if wd["w"] else max(f.width(l) for l in lines) + 2 * pad_x
    h = len(lines) * f.lh + (len(lines) - 1) * wd["ls"] + 2 * pad_y
    return wd["x"], wd["y"], w, h


BM_PAD, BM_GAP = 2, 4


def check():
    probs = []
    for pid, ws in PAGES.items():
        boxes = []
        for wd in ws:
            x, y, w, h = box(wd)
            name = wd.get("id") or u(wd.get("text", wd["t"]))[:18].replace("\n", "|")
            if x < 0 or y < 0 or x + w > W or y + h > NAV_Y:
                probs.append(f"{pid}: {name} out of area ({x},{y},{w:.0f},{h})")
            if wd["t"] == "label" and wd["w"]:
                f = FONTS[wd["font"]]
                inner = wd["w"] - (2 * CHIP_PX if wd["chip"] else 0)
                for l in wrap(u(wd["sample"]), f, inner if wd["wrap"] else None):
                    if f.width(l) > inner and not wd["dots"]:
                        probs.append(f"{pid}: {name} '{l}' {f.width(l):.0f}px > {inner}")
            if wd["t"] in ("bm", "button"):
                btns = wd["buttons"] if wd["t"] == "bm" else [(wd["text"], None)]
                n = len(btns)
                bw = (wd["w"] - 2 * BM_PAD - (n - 1) * BM_GAP) / n
                f = FONTS[wd["font"]]
                for t, _ in btns:
                    tw = f.width(u(t))
                    if tw > bw - 8:
                        probs.append(f"{pid}: button '{t}' {tw:.0f}px > {bw - 8:.0f}")
                if f.lh > wd["h"] - 2 * BM_PAD - 4:
                    probs.append(f"{pid}: button too low for font")
            boxes.append((name, x, y, w, h))
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if str(a[0]).startswith("arc_") or str(b[0]).startswith("arc_"):
                    continue
                if a[1] < b[1] + b[3] and b[1] < a[1] + a[3] and a[2] < b[2] + b[4] and b[2] < a[2] + a[4]:
                    probs.append(f"{pid}: OVERLAP {a[0]} {tuple(round(v) for v in a[1:5])} "
                                 f"x {b[0]} {tuple(round(v) for v in b[1:5])}")
    return probs


# ------------------------------------------------------------------ YAML
def hx(c):
    return f"0x{c:06X}"


def emit():
    o = []
    w = o.append

    def actions(acts, ind):
        for a in acts:
            lines = a.split("\n")
            w(" " * ind + "- " + lines[0])
            for l in lines[1:]:
                w(" " * (ind + 2) + l)

    def widget(wd, ind):
        p = " " * ind
        q = p + "    "
        t = wd["t"]
        if t == "label":
            w(f"{p}- label:")
            if wd["id"]:
                w(f"{q}id: {wd['id']}")
            w(f"{q}x: {wd['x']}")
            w(f"{q}y: {wd['y']}")
            if wd["w"]:
                w(f"{q}width: {wd['w']}")
            if wd["wrap"]:
                w(f"{q}long_mode: WRAP")
            if wd["dots"]:
                w(f"{q}long_mode: DOT")
            if wd["align"] != "LEFT":
                w(f"{q}text_align: {wd['align']}")
            if wd["chip"]:
                w(f"{q}styles: chip")
            if wd["font"] != 14:
                w(f"{q}text_font: montserrat_{wd['font']}")
            if wd["ls"]:
                w(f"{q}text_line_space: {wd['ls']}")
            if not wd["chip"] and wd["color"] != NAME:
                w(f"{q}text_color: {hx(wd['color'])}")
            txt = wd["text"].replace("\n", "\\n")
            w(f'{q}text: "{txt}"')
        elif t == "bm":
            w(f"{p}- buttonmatrix:")
            if wd.get("id"):
                w(f"{q}id: {wd['id']}")
            for k in ("x", "y"):
                w(f"{q}{k}: {wd[k]}")
            w(f"{q}width: {wd['w']}")
            w(f"{q}height: {wd['h']}")
            if wd["font"] != 16:
                w(f"{q}text_font: montserrat_{wd['font']}")
            if wd["item_bg"] is not None:
                w(f"{q}items:")
                w(f"{q}  bg_color: {hx(wd['item_bg'])}")
                w(f"{q}  text_color: {hx(wd['item_txt'])}")
            w(f"{q}rows:")
            w(f"{q}  - buttons:")
            for text, acts in wd["buttons"]:
                w(f'{q}      - text: "{text}"')
                w(f"{q}        on_click:")
                actions(acts, ind + 12)
        elif t == "button":
            w(f"""{p}- button:
{q}x: {wd['x']}
{q}y: {wd['y']}
{q}width: {wd['w']}
{q}height: {wd['h']}
{q}bg_color: {hx(wd['bg'])}
{q}widgets:
{q}  - label:
{q}      align: CENTER
{q}      text_font: montserrat_{wd['font']}
{q}      text_color: 0xFFFFFF
{q}      text: "{wd['text']}"
{q}on_click:""")
            actions(wd["actions"], ind + 6)
        elif t == "switch":
            w(f"{p}- switch:")
            w(f"{q}id: {wd['id']}")
            for k, v in (("x", wd["x"]), ("y", wd["y"]), ("width", wd["w"]), ("height", wd["h"])):
                w(f"{q}{k}: {v}")
            w(f"{q}on_change:")
            w(f"{q}  - if:")
            w(f"{q}      condition:")
            w(f"{q}        lambda: 'return x;'")
            w(f"{q}      then: [ switch.turn_on: {wd['sw']} ]")
            w(f"{q}      else: [ switch.turn_off: {wd['sw']} ]")
        elif t == "arc":
            w(f"""{p}- arc:
{q}id: {wd['id']}
{q}x: {wd['x']}
{q}y: {wd['y']}
{q}width: {wd['w']}
{q}height: {wd['h']}
{q}min_value: 0
{q}max_value: {wd['max']}
{q}value: 0
{q}adjustable: false
{q}clickable: false
{q}arc_width: 10
{q}indicator:
{q}  arc_color: {hx(wd['color'])}
{q}  arc_width: 10""")
        elif t == "dropdown":
            w(f"""{p}- dropdown:
{q}id: {wd['id']}
{q}x: {wd['x']}
{q}y: {wd['y']}
{q}width: {wd['w']}
{q}height: {wd['h']}
{q}text_font: montserrat_18
{q}text_color: {hx(VAL)}
{q}bg_color: {hx(CHIP_BG)}
{q}border_color: {hx(CHIP_BORDER)}
{q}options: ["2", "10", "20", "30", "40", "50", "60"]
{q}on_change:
{q}  - if:
{q}      condition: {{ binary_sensor.is_on: inv_link }}
{q}      then:
{q}        - select.set_index:
{q}            id: sel_max_ac_charging_current
{q}            index: !lambda 'return x;'
{q}      else:
{q}        - script.execute: {{ id: toast, msg: "No inverter link - not sent" }}
{q}        # snap back to the last value read from the inverter
{q}        - lvgl.dropdown.update:
{q}            id: dd_charge
{q}            selected_index: !lambda |-
{q}              static const int opts[] = {{2, 10, 20, 30, 40, 50, 60}};
{q}              float v = id(s_max_ac_charging_current).state;
{q}              for (int i = 0; i < 7; i++) if ((int) v == opts[i]) return i;
{q}              return 0;""")

    w(f"""lvgl:
  displays: [tft]
  touchscreens: [touch]
  buffer_size: 25%               # no PSRAM on the CYD
  # Layout generated by ui.py and checked against the real Montserrat glyph widths
  # (no overlaps, nothing outside the screen or under the nav bar).
  theme:
    dark_mode: true
    label:
      text_color: {hx(NAME)}
    buttonmatrix:
      bg_opa: TRANSP
      border_width: 0
      pad_all: {BM_PAD}
      pad_column: {BM_GAP}
      text_font: montserrat_16
      items:
        bg_color: {hx(BTN)}
        text_color: {hx(BTN_TXT)}
        radius: 8
        pressed:
          bg_color: {hx(BTN_PRESS)}
    button:
      radius: 10
      shadow_width: 0
      pressed:
        bg_color: {hx(BTN_PRESS)}
    switch:
      bg_color: {hx(SW_OFF)}
      indicator:
        checked:
          bg_color: {hx(GOOD)}
    arc:
      arc_color: {hx(BTN)}
      knob:
        bg_opa: TRANSP
        pad_all: 0
  style_definitions:
    - id: chip                   # highlighted value
      bg_color: {hx(CHIP_BG)}
      bg_opa: COVER
      border_color: {hx(CHIP_BORDER)}
      border_width: 1
      radius: 6
      pad_left: {CHIP_PX}
      pad_right: {CHIP_PX}
      pad_top: {CHIP_PY}
      pad_bottom: {CHIP_PY}
      text_color: {hx(VAL)}
  on_idle:
    - timeout: 90s
      then:
        - light.turn_on: {{ id: backlight, brightness: 15% }}
    - timeout: 10min
      then:
        - light.turn_off: backlight
  # Shown over every page: nav bar, alarm banner, short messages, touch-debug dot.
  top_layer:
    widgets:
      - obj:
          x: 0
          y: {NAV_Y}
          width: {W}
          height: {H - NAV_Y}
          bg_color: {hx(NAV_BG)}
          bg_opa: COVER
          border_width: 0
          radius: 0
          pad_all: 0
          scrollable: false""")
    widget(bm(0, NAV_Y, W, H - NAV_Y, [(s, [f"lvgl.page.show: {pg}"]) for s, pg in NAV],
              font=20, id="nav", item_bg=NAV_BTN, item_txt=NAV_TXT), 6)
    w(f"""      - label:
          id: lbl_alert
          hidden: true
          clickable: true
          align: CENTER
          y: -20
          width: 280
          long_mode: WRAP
          text_align: CENTER
          text_font: montserrat_18
          bg_color: 0xC62828
          bg_opa: COVER
          text_color: 0xFFFFFF
          radius: 10
          pad_all: 12
          text: ""
          on_click:                    # tap = silence and dismiss
            - rtttl.stop: {{ id: buzzer }}
            - lambda: 'id(tune_prio) = 0;'
            - lvgl.widget.hide: lbl_alert
      - label:
          id: lbl_toast
          hidden: true
          align: BOTTOM_MID
          y: -46
          width: 300
          long_mode: WRAP
          text_align: CENTER
          text_font: montserrat_16
          bg_color: 0x37474F
          bg_opa: COVER
          text_color: 0xFFFFFF
          pad_all: 8
          radius: 8
          text: ""
      - obj:
          id: touch_dot
          hidden: true
          clickable: false
          width: 10
          height: 10
          radius: 5
          bg_color: 0xFF1744
          bg_opa: COVER
          border_width: 0
  pages:""")
    for pid, ws in PAGES.items():
        w(f"    - id: {pid}")
        w(f"      scrollable: false")
        w(f"      bg_color: {hx(BG)}")
        w(f"      bg_opa: COVER")
        w(f"      widgets:")
        for wd in ws:
            widget(wd, 8)
    return "\n".join(o) + "\n"


def emit_script():
    """ui_refresh_values: fills the Home / Power / Info value chips (N/A without inverter data)."""
    o = ["  # Home / Power / Info value chips. Generated by ui.py. N/A when there is no fresh inverter data.",
         "  - id: ui_refresh_values",
         "    then:"]
    for vid, (expr, fmt, gated) in LIVE.items():
        cond = "!id(inv_link).state || isnan(v)" if gated else "isnan(v)"
        o += ["      - lvgl.label.update:",
              f"          id: {vid}",
              "          text: !lambda |-",
              f"            float v = {expr};",
              f'            return ({cond}) ? std::string("N/A") : str_sprintf("{fmt}", v);']
    for aid, expr in (("arc_pv", "id(s_pv_power).state / std::max(0.1f, id(n_pv_kwp).state) / 10.0f"),
                      ("arc_load", "id(s_load_power).state")):
        o += ["      - lvgl.arc.update:",
              f"          id: {aid}",
              f"          value: !lambda 'float v = {expr}; return (!id(inv_link).state || isnan(v)) ? 0 : (int) v;'"]
    o += ["      - lvgl.label.update:",
          "          id: lbl_age",
          "          text: !lambda |-",
          "            if (id(last_inverter_data) == 0) return std::string(\"never\");",
          "            return str_sprintf(\"%us\", (unsigned) ((millis() - id(last_inverter_data)) / 1000));"]
    for pid_, code in PROJ.items():
        o += ["      - lvgl.label.update:", f"          id: {pid_}", "          text: !lambda |-"]
        o += ["            " + l for l in code.split("\n")]
    for _, iid, _, code in INFO:
        if code is None:
            continue
        o += ["      - lvgl.label.update:",
              f"          id: {iid}",
              "          text: !lambda |-"]
        o += ["            " + l for l in code.split("\n")]
    return "\n".join(o) + "\n"


# ------------------------------------------------------------------ preview
def rgb(c):
    return ((c >> 16) & 255, (c >> 8) & 255, c & 255)


def render(outdir):
    from PIL import Image, ImageDraw
    os.makedirs(outdir, exist_ok=True)

    def text(img, x, y, s, f, color):
        px = img.load()
        for ch in s:
            g = f.glyph(ch)
            if not g:
                x += f.lh
                continue
            bi, adv, bw, bh, ox, oy = g
            top = f.lh - f.base - bh - oy
            for r in range(bh):
                for cidx in range(bw):
                    n = r * bw + cidx
                    byte = f.bitmap[bi + n // 2]
                    a = (byte >> 4) if n % 2 == 0 else (byte & 0xF)
                    if a:
                        X, Y = int(x + ox + cidx), int(y + top + r)
                        if 0 <= X < W and 0 <= Y < H:
                            bg = px[X, Y]
                            k = a / 15
                            px[X, Y] = tuple(int(bg[i] * (1 - k) + color[i] * k) for i in range(3))
            x += adv / 16

    def lbl(img, d, wd):
        f = FONTS[wd["font"]]
        x, y, w, h = box(wd)
        px_, py_ = (CHIP_PX, CHIP_PY) if wd["chip"] else (0, 0)
        if wd["chip"]:
            d.rounded_rectangle([x, y, x + w - 1, y + h - 1], 6, fill=rgb(CHIP_BG), outline=rgb(CHIP_BORDER))
        inner = w - 2 * px_
        lines = wrap(u(wd["sample"]), f, inner if wd["wrap"] else None)
        if wd["dots"]:
            lines = lines[:1]
        for i, l in enumerate(lines):
            lw = f.width(l)
            lx = x + px_ if wd["align"] == "LEFT" else (
                x + px_ + inner - lw if wd["align"] == "RIGHT" else x + px_ + (inner - lw) / 2)
            text(img, lx, y + py_ + i * (f.lh + wd["ls"]), l, f, rgb(wd["color"]))

    def buttons(img, d, wd, bg=BTN, fg=BTN_TXT):
        n = len(wd["buttons"])
        bw = (wd["w"] - 2 * BM_PAD - (n - 1) * BM_GAP) / n
        f = FONTS[wd["font"]]
        for i, (t, _) in enumerate(wd["buttons"]):
            bx = wd["x"] + BM_PAD + i * (bw + BM_GAP)
            by, bh = wd["y"] + BM_PAD, wd["h"] - 2 * BM_PAD
            d.rounded_rectangle([bx, by, bx + bw, by + bh], 8, fill=rgb(bg))
            s = u(t)
            text(img, bx + (bw - f.width(s)) / 2, by + (bh - f.lh) / 2, s, f, rgb(fg))

    for pid, ws in PAGES.items():
        img = Image.new("RGB", (W, H), rgb(BG))
        d = ImageDraw.Draw(img)
        for wd in ws:
            t = wd["t"]
            if t == "label":
                lbl(img, d, wd)
            elif t == "bm":
                buttons(img, d, wd, wd["item_bg"] or BTN, wd["item_txt"] or BTN_TXT)
            elif t == "button":
                d.rounded_rectangle([wd["x"], wd["y"], wd["x"] + wd["w"], wd["y"] + wd["h"]], 10, fill=rgb(wd["bg"]))
                f = FONTS[wd["font"]]
                text(img, wd["x"] + (wd["w"] - f.width(wd["text"])) / 2, wd["y"] + (wd["h"] - f.lh) / 2,
                     wd["text"], f, (255, 255, 255))
            elif t == "switch":
                d.rounded_rectangle([wd["x"], wd["y"], wd["x"] + wd["w"], wd["y"] + wd["h"]],
                                    wd["h"] // 2, fill=rgb(GOOD))
                d.ellipse([wd["x"] + wd["w"] - wd["h"] + 3, wd["y"] + 3, wd["x"] + wd["w"] - 3,
                           wd["y"] + wd["h"] - 3], fill=(255, 255, 255))
            elif t == "arc":
                bb = [wd["x"] + 5, wd["y"] + 5, wd["x"] + wd["w"] - 5, wd["y"] + wd["h"] - 5]
                d.arc(bb, 135, 405, fill=rgb(BTN), width=10)
                frac = {"arc_soc": 0.78, "arc_pv": 0.45, "arc_load": 0.2}[wd["id"]]
                d.arc(bb, 135, 135 + 270 * frac, fill=rgb(wd["color"]), width=10)
            elif t == "dropdown":
                d.rounded_rectangle([wd["x"], wd["y"], wd["x"] + wd["w"], wd["y"] + wd["h"]], 6,
                                    fill=rgb(CHIP_BG), outline=rgb(CHIP_BORDER), width=1)
                f = FONTS[18]
                text(img, wd["x"] + 12, wd["y"] + (wd["h"] - f.lh) / 2, "60", f, rgb(VAL))
                text(img, wd["x"] + wd["w"] - 26, wd["y"] + (wd["h"] - f.lh) / 2, "", f, rgb(BTN_TXT))
        d.rectangle([0, NAV_Y, W, H], fill=rgb(NAV_BG))
        buttons(img, d, bm(0, NAV_Y, W, H - NAV_Y, [(s, []) for s, _ in NAV], font=20), NAV_BTN, NAV_TXT)
        img.resize((W * 2, H * 2), Image.LANCZOS).save(os.path.join(outdir, pid + ".png"))


if __name__ == "__main__":
    cmd, fontdir = sys.argv[1], sys.argv[2]
    load_fonts(fontdir)
    build()
    if cmd == "yaml":
        sys.stdout.write(emit())
    elif cmd == "script":
        sys.stdout.write(emit_script())
    elif cmd == "formats":
        for k, (n, v) in FMT.items():
            print(f"{k}\t{v}")
    elif cmd == "check":
        pr = check()
        print("\n".join(pr) if pr else "no problems")
    elif cmd == "render":
        render(sys.argv[3])
