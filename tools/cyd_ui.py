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
ALERT_FONT, ALERT_PAD, ALERT_W = 16, 6, 316   # banner: two lines across the top
ICON_DIR = os.environ.get("CYD_ICONS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "icons"))
# every banner message the controller can send (longest values): must fit two banner lines
ALERTS = ["Battery low - switched to grid", "Inverter did not accept the output priority",
          "Inverter did not accept the charger setting", "No grid: battery lasts about 23 h 59 min",
          "No grid: battery may run out before the sun is up"]


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


def img(x, y, w, h, id, src, color, hidden=False, preview=True, click=None, alt=None):
    """Icon (white SVG from icons/, recoloured). hidden: starts hidden (shown by the refresh lambda);
    preview: drawn in the PNG previews; click: actions on tap; alt: group of alternatives that share
    one spot (only one is shown at a time, so they may overlap)."""
    return dict(t="img", x=x, y=y, w=w, h=h, id=id, src=src, color=color, hidden=hidden, preview=preview,
                click=click, alt=alt)


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
from cyd_settings import HELP, NUMBERS, VPAGES  # noqa: E402
FMT = {n[0]: (n[7], n[8]) for n in NUMBERS if n[7]}
MAXV = {n[0]: n[4] for n in NUMBERS}

INFO_X, NAME_X, NAME_W = 4, 24, 128   # (i) icon, name column
DEF = {n[0]: n[8] % n[6] for n in NUMBERS if n[8]}


def help_text(nid):
    return HELP[nid] + " Default " + DEF[nid].replace("%%", "%") + "."


def help_action(nid):
    return f"script.execute: {{ id: show_help, msg: {cstr(help_text(nid))} }}"
CHIP_X, CHIP_W = 156, 86            # value chip
BTN_X, BTN_W = 246, 72              # - / + buttons


ROWREC = {}          # virtual page id -> row layouts (for the shared settings page table)


def num_rows(nids, y0=42, y1=NAV_Y - 2, rec=None):
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
        iy = y + (pitch - 16) // 2
        out.append(img(INFO_X, iy, 16, 16, "inf_" + nid, "ico_info", TITLE, click=[help_action(nid)]))
        out.append(label(NAME_X, y + (pitch - th) // 2, name, font=f, w=NAME_W, wrap_=True))
        out.append(chip(CHIP_X, y + (pitch - ch) // 2, CHIP_W, "lb_" + nid,
                        vf % MAXV.get(nid, 60), font=vfont, align="CENTER", text="--"))
        out.append(bm(BTN_X, y + (pitch - bh) // 2, BTN_W, bh, [
            ("\\uF068", [f"number.decrement: {{ id: {nid}, cycle: false }}"]),
            ("\\uF067", [f"number.increment: {{ id: {nid}, cycle: false }}"])], font=16))
        if rec is not None:
            rec.append(dict(nid=nid, name=name, fmt=vf, ny=y + (pitch - th) // 2, nf=f, iy=iy, help=help_text(nid),
                            cy=y + (pitch - ch) // 2, cf=vfont, by=y + (pitch - bh) // 2, bh=bh))
    return out


INFOG = ["page_i_power", "page_i_proj", "page_i_energy", "page_i_sys"]
VIRT = [p for p, _, _, _ in VPAGES]              # shown on the shared page "page_set"
REAL_CODE = {"page_s_rules": -1, "page_s_sound": -2, "page_s_disp": -3, "page_a_reset": -4}


def goto(pid):
    """Action that opens a page; a virtual settings page goes through the set_ui script."""
    if pid in VIRT:
        return f"script.execute: {{ id: set_ui, what: 4, slot: {VIRT.index(pid)}, dir: 0 }}"
    return f"lvgl.page.show: {pid}"
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
    "page_a_batt": "Battery capacity", "page_a_pv": "Solar panels", "page_a_reset": "Reset & reboot",
}


def header(pid):
    group, name = next((g, n) for g, n in ((INFOG, "INFO"), (SETUP, "SETUP"), (ADV, "ADVANCED"))
                       if pid in g)
    i = group.index(pid)
    return [label(6, 3, f"{name} {i + 1}/{len(group)}", font=14, color=NAME),
            label(6, 19, TITLES[pid], font=18, color=TITLE),
            bm(240, 2, 78, 36, [("\\uF053", [goto(group[i - 1])]),
                                ("\\uF054", [goto(group[(i + 1) % len(group)])])])]


GUARD = ("if:\n  condition: {{ binary_sensor.is_on: inv_link }}\n  then:\n"
         "    - switch.turn_off: auto_ctl\n"
         "    - select.set: {{ id: sel_output_source_priority, option: \"{opt}\" }}\n"
         "  else:\n    - script.execute: {{ id: toast, msg: \"No inverter link - not sent\" }}")

# value chips refreshed every 2 s: id -> (C++ value expr, printf format, gated by inverter link)
LIVE = {
    "v_load": ("id(s_load_power).state", "%.0f W", True),
    "v_pv": ("id(s_pv_power).state", "%.0f W", True),
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
DASH0 = {"v_pv", "v_grid"}
# Home: icons and badges (C++, runs every 2 s in ui_refresh_values)
HOME_LAMBDA = r"""
auto show = [](lv_obj_t *o, bool v) { if (v) lv_obj_remove_flag(o, LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(o, LV_OBJ_FLAG_HIDDEN); };
auto tint = [](lv_obj_t *o, uint32_t c) { lv_obj_set_style_image_recolor(o, lv_color_hex(c), LV_PART_MAIN); };
const bool link = id(inv_link).state;
const auto st = id(autopilot).status();
const auto set = id(autopilot).settings();
const uint8_t r = st.reasons;
// where the house gets its power (read back from the inverter)
const bool sub = link && id(s_output_source_priority).state == 1.0f;
show(id(hm_path_batt), link && !sub);
show(id(hm_path_grid), sub && !st.charging);
show(id(hm_path_chg), sub && st.charging);
// badges, packed from the left
struct Badge { lv_obj_t *o; bool on; };
const Badge badges[] = {{id(hm_b_observe), set.auto_ctl && set.observe}, {id(hm_b_manual), !set.auto_ctl},
                        {id(hm_b_fault), st.fault}, {id(hm_b_low), link && (r & 1)}, {id(hm_b_high), link && (r & 2)},
                        {id(hm_b_night), link && (r & 4)}, {id(hm_b_ovn), link && (r & 8)}, {id(hm_b_chg), link && (r & 16)}};
int bx = 56;
for (const auto &b : badges) {
  show(b.o, b.on);
  if (b.on) { lv_obj_set_x(b.o, bx); bx += 22; }
}
// battery in the middle: charging / discharging / idle and its power (batt_power: + = discharge)
const float bw = id(batt_power).state;
const bool known = link && !isnan(bw);
show(id(hm_bat_plus), known && bw < -15);
show(id(hm_bat_minus), known && bw > 15);
show(id(hm_bat_idle), !known || fabsf(bw) <= 15);
lv_label_set_text(id(hm_bat_w), !known ? "" : str_sprintf("%+.0f W", -bw).c_str());
lv_obj_set_style_text_color(id(hm_bat_w), lv_color_hex(bw < -15 ? 0x43A047 : 0xFFB300), LV_PART_MAIN);
// grid: green present, red lost, grey unknown
tint(id(hm_ic_grid), !link || !id(bs_grid).has_state() ? 0x546E7A : id(bs_grid).state ? 0x43A047 : 0xE53935);
// battery runs out before the sun is useful: red empty battery + estimated hour ("~4am")
auto t = id(sntp_time).now();
const float soc = id(s_soc).state;
const bool empty = link && t.is_valid() && !isnan(st.soc_at_sun) && st.soc_at_sun < set.empty_soc && !isnan(soc) &&
                   st.base_load > 0;
show(id(hm_empty), empty);
show(id(hm_empty_t), empty);
if (empty) {
  const float hours = std::max(0.0f, set.batt_kwh * 1000.0f * (soc - set.empty_soc) / 100.0f / st.base_load);
  auto e = ESPTime::from_epoch_local(t.timestamp + (time_t) (hours * 3600.0f) + 1800);   // rounded to the hour
  const int h12 = e.hour % 12 == 0 ? 12 : e.hour % 12;
  lv_label_set_text(id(hm_empty_t), str_sprintf("~%d%s", h12, e.hour < 12 ? "am" : "pm").c_str());
}
// clock and status icons: inverter link, Home Assistant, internet
lv_label_set_text(id(lbl_clock), t.is_valid() ? t.strftime("%H:%M").c_str() : "--:--");
tint(id(ic_inv), link ? 0x43A047 : 0xE53935);
#ifdef USE_API
tint(id(ic_ha), api::global_api_server->is_connected() ? 0x43A047 : 0xE53935);
#else
tint(id(ic_ha), 0x37474F);   // API not compiled in
#endif
const uint32_t fc = id(autopilot).forecast().last_reply_ms();
const bool inet = (id(net_ok_ms) != 0 && millis() - id(net_ok_ms) < 11UL * 60000UL) || (fc != 0 && millis() - fc < 11UL * 60000UL);
tint(id(ic_wifi), !wifi::global_wifi_component->is_connected() ? 0xE53935 : inet ? 0x43A047 : 0xFDD835);
"""
_RT = ('float soc = id(s_soc).state, load = {load};\n'
       'if (!id(inv_link).state || isnan(soc) || isnan(load)) return std::string("N/A");\n'
       'float wh = std::max(0.0f, id(n_batt_kwh).state * 10.0f * (soc - id(n_empty_soc).state));\n'
       'float h = wh / std::max(load, 50.0f);\n'
       'if (h >= 99.0f) return std::string("> 99 h");\n'
       'return str_sprintf("%dh %02dm", (int) h, (int) ((h - (int) h) * 60));')
# Projections page values: id -> C++ returning std::string
PROJ = {
    "x_left": ('float soc = id(s_soc).state;\n'
               'if (!id(inv_link).state || isnan(soc)) return std::string("N/A");\n'
               'return str_sprintf("%.2f kWh", std::max(0.0f, id(n_batt_kwh).state * (soc - id(n_empty_soc).state) / 100.0f));'),
    "x_rt_now": _RT.format(load="id(s_load_power).state"),
    "x_rt_1h": _RT.format(load="id(s_load_1h).state"),
    "x_fc_now": 'auto t = id(sntp_time).now();\nconst float v = t.is_valid() ? id(autopilot).forecast().power_at(t.hour * 60 + t.minute) : NAN;\nreturn isnan(v) ? std::string("N/A") : str_sprintf("%.0f W", v);',
    "x_fc_today": 'float v = id(autopilot).forecast().today_kwh();\nreturn isnan(v) ? std::string("N/A") : str_sprintf("%.1f kWh", v);',
    "x_fc_tmrw": 'float v = id(autopilot).forecast().tomorrow_kwh();\nreturn isnan(v) ? std::string("N/A") : str_sprintf("%.1f kWh", v);',
    "lbl_fc_upd": 'return std::string(id(autopilot).forecast().status());',
}
# Info page rows: (name, id, sample, C++ returning std::string)
INFO = [
    ("Firmware", "i_fw", "ESPHome 2026.10.1", 'return std::string("ESPHome " ESPHOME_VERSION);'),
    ("Built", "i_built", "Nov 11 2026 23:59:59", 'return std::string(__DATE__ " " __TIME__);'),
    ("WiFi", "i_wifi", "MyNetworkName-5G", 'return id(t_ssid).has_state() ? id(t_ssid).state : std::string("--");'),
    ("IP", "i_ip", "192.168.100.100", 'return id(t_ip).has_state() ? id(t_ip).state : std::string("--");'),
    ("Signal", "i_rssi", "-100 dBm", None),
    ("Uptime", "i_up", "99d 23h 59m",
     'const unsigned s = millis() / 1000;\nreturn str_sprintf("%ud %02uh %02um", s / 86400, (s / 3600) % 24, (s / 60) % 60);'),
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

REBOOT_ACTION = ("if:\n  condition:\n"
                 "    lambda: 'return id(reboot_armed) != 0 && millis() - id(reboot_armed) < 5000;'\n"
                 "  then:\n    - lambda: 'id(reboot_armed) = 0;'\n"
                 "    - script.execute: { id: toast, msg: \"Rebooting...\" }\n"
                 "    - delay: 1s\n    - lambda: 'App.safe_reboot();'\n"
                 "  else:\n    - lambda: 'id(reboot_armed) = millis();'\n"
                 "    - script.execute: { id: toast, msg: \"Tap again within 5 s to reboot\" }")

PAGES = {}
# reason / mode badges on Home, in display order: (icon key, colour)
BADGES = [("observe", 0x9AA8B5), ("manual", 0xFFB300), ("fault", 0xE53935), ("low", 0xE53935),
          ("high", 0xFFB300), ("night", 0x9FA8DA), ("ovn", 0xFFB300), ("chg", 0x29B6F6)]


def build():
    lh18, lh20 = FONTS[18].lh, FONTS[20].lh
    ch20 = lh20 + 2 * CHIP_PY
    # ---------------- Home
    # three concentric gauges: outer = battery %, middle = solar, inner = load (% of inverter max)
    p = [dict(t="arc", id="arc_soc", x=2, y=2, w=140, h=140, color=GOOD, max=100),
         dict(t="arc", id="arc_pv", x=2 + RING, y=2 + RING, w=140 - 2 * RING, h=140 - 2 * RING,
              color=PV_COL, max=100),
         dict(t="arc", id="arc_load", x=2 + 2 * RING, y=2 + 2 * RING, w=140 - 4 * RING,
              h=140 - 4 * RING, color=LOAD_COL, max=100)]
    # middle of the gauges: battery charging (+) / discharging (-) / idle, SOC, battery power
    cy = 2 + 70
    soc_y = cy - lh20 // 2 + 4
    p += [img(59, soc_y - 27, 26, 26, f"hm_bat_{k}", f"ico_batt_{k}", c, hidden=k != "plus", preview=k == "plus",
              alt="bat")
          for k, c in (("plus", GOOD), ("minus", PV_COL), ("idle", NAME))]
    p += [label(2 + RING * 2 + 10, soc_y, "N/A", font=20, w=140 - 4 * RING - 20, id="lbl_soc", sample="100%",
                align="CENTER", color=0xFFFFFF),
          # below the rings' inner ends (they are open at the bottom)
          label(42, 104, "", font=14, w=60, id="hm_bat_w", sample="+1234 W", align="CENTER", color=GOOD)]
    # right column: icon + value (zero = dimmed dash)
    for i, (ico, iid, vid, smp, col) in enumerate([("ico_pv", "hm_ic_pv", "v_pv", "12345 W", PV_COL),
                                                  ("ico_load", "hm_ic_load", "v_load", "12345 W", LOAD_COL),
                                                  ("ico_grid", "hm_ic_grid", "v_grid", "12345 W", GOOD)]):
        y = 6 + i * 44
        p += [img(150, y + (ch20 - 24) // 2, 24, 24, iid, ico, col),
              chip(180, y, 138, vid, smp, font=20)]
    # status row: power path + reason badges (packed left by the refresh lambda) + "battery empty ~4am"
    p += [img(4, 148, 50, 23, f"hm_path_{k}", f"ico_path_{k}", c, hidden=k != "batt", preview=k == "batt",
              alt="path")
          for k, c in (("batt", GOOD), ("grid", GRID_BTN), ("chg", 0x29B6F6))]
    for i, (k, c) in enumerate(BADGES):
        p.append(img(56 + i * 22, 149, 22, 22, f"hm_b_{k}", f"ico_{k}", c, hidden=True, preview=k in ("low", "chg")))
    p += [img(234, 150, 20, 20, "hm_empty", "ico_empty", BAD, hidden=True),
          label(255, 151, "", font=16, w=63, id="hm_empty_t", sample="~12am", color=BAD)]
    # bottom row: clock | inverter, Home Assistant, WiFi
    p += [label(6, 177, "", font=16, id="lbl_clock", sample="23:59", color=NAME),
          img(252, 178, 18, 18, "ic_inv", "ico_inverter", BAD),
          img(276, 178, 18, 18, "ic_ha", "ico_ha", BAD),
          img(300, 178, 18, 18, "ic_wifi", "ico_wifi", BAD)]
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
    for pid, _, _, nids in VPAGES:          # virtual pages: laid out + checked here, shown on page_set
        ROWREC[pid] = []
        PAGES[pid] = header(pid) + num_rows(nids, rec=ROWREC[pid])
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

    # ---------------- Advanced (pure-settings pages come from VPAGES above)
    PAGES["page_a_reset"] = header("page_a_reset") + [
        label(6, 40, "Restore defaults: every rule, threshold, sound and display setting back to its default "
                     "(touch and light calibration are kept).", font=16, w=308, wrap_=True, color=BTN_TXT),
        button(6, 116, 152, 46, "Restore defaults", [RESET_ACTION], BAD, font=16),
        button(162, 116, 152, 46, "Reboot", [REBOOT_ACTION], GRID_BTN, font=18),
        label(6, 168, "Tap twice within 5 s to confirm. A reboot keeps all settings.", font=14, w=308,
              wrap_=True, align="CENTER")]


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
    f = FONTS[ALERT_FONT]
    for m in ALERTS:
        lines = wrap(m, f, ALERT_W - 2 * ALERT_PAD)
        if len(lines) > 2:
            probs.append(f"banner: '{m}' needs {len(lines)} lines")
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
            boxes.append((name, x, y, w, h, wd.get("alt")))
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if str(a[0]).startswith("arc_") or str(b[0]).startswith("arc_"):
                    continue
                if a[5] is not None and a[5] == b[5]:      # alternatives on one spot
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
        elif t == "img":
            w(f"{p}- image:")
            w(f"{q}id: {wd['id']}")
            w(f"{q}x: {wd['x']}")
            w(f"{q}y: {wd['y']}")
            w(f"{q}src: {wd['src']}")
            w(f"{q}image_recolor: {hx(wd['color'])}")
            w(f"{q}image_recolor_opa: COVER")
            if wd["hidden"]:
                w(f"{q}hidden: true")
            if wd["click"]:
                w(f"{q}clickable: true")
                w(f"{q}ext_click_area: 10")
                w(f"{q}on_click:")
                actions(wd["click"], ind + 6)
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
  buffer_size: 10%               # no PSRAM: draw in strips of 10 % of the screen (RAM for HTTPS)
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
  on_idle:                       # dim after 90 s untouched; the screen never goes off
    - timeout: 90s
      then:
        - light.turn_on: {{ id: backlight, brightness: 15% }}
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
    widget(bm(0, NAV_Y, W, H - NAV_Y, [(s, [goto(pg)]) for s, pg in NAV],
              font=20, id="nav", item_bg=NAV_BTN, item_txt=NAV_TXT), 6)
    ALERT_H = 2 * FONTS[ALERT_FONT].lh + 2 * ALERT_PAD
    w(f"""      - label:
          id: lbl_alert
          hidden: true
          clickable: true
          align: TOP_MID
          y: 2
          width: {ALERT_W}
          height: {ALERT_H}
          long_mode: WRAP
          text_align: CENTER
          text_font: montserrat_{ALERT_FONT}
          bg_color: 0xC62828
          bg_opa: COVER
          text_color: 0xFFFFFF
          radius: 8
          pad_all: {ALERT_PAD}
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
      - label:
          id: lbl_help
          hidden: true
          clickable: true
          align: CENTER
          y: -10
          width: 300
          long_mode: WRAP
          text_font: montserrat_14
          bg_color: 0x1C2833
          bg_opa: COVER
          border_color: 0x4FC3F7
          border_width: 1
          text_color: 0xECEFF1
          pad_all: 10
          radius: 8
          text: ""
          on_click:                    # tap = close
            - lvgl.widget.hide: lbl_help
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
    for pid, ws in list(PAGES.items()) + [("page_set", set_page_widgets())]:
        if pid in VIRT:
            continue
        w(f"    - id: {pid}")
        w(f"      scrollable: false")
        w(f"      bg_color: {hx(BG)}")
        w(f"      bg_opa: COVER")
        w(f"      widgets:")
        for wd in ws:
            widget(wd, 8)
    return "\n".join(o) + "\n"


SET_ACT = "script.execute: {{ id: set_ui, what: {what}, slot: {slot}, dir: {dir} }}"


def set_page_widgets():
    """The one shared settings page: header + 4 row slots, filled by the set_ui script."""
    ws = [label(6, 3, "", font=14, id="set_grp", sample="ADVANCED 12/13"),
          label(6, 19, "", font=18, id="set_title", color=TITLE, sample="Forecast & charging"),
          bm(240, 2, 78, 36, [("\\uF053", [SET_ACT.format(what=3, slot=0, dir=-1)]),
                              ("\\uF054", [SET_ACT.format(what=3, slot=0, dir=1)])])]
    for i in range(4):
        y = 42 + i * 39
        ws += [img(INFO_X, y + 10, 16, 16, f"set_i{i}", "ico_info", TITLE,
                   click=[SET_ACT.format(what=5, slot=i, dir=0)]),
               label(NAME_X, y, "", font=16, w=NAME_W, id=f"set_n{i}", wrap_=True, sample="-"),
               chip(CHIP_X, y, CHIP_W, f"set_v{i}", "-", font=18, align="CENTER", text="--"),
               bm(BTN_X, y, BTN_W, 35, [("\\uF068", [SET_ACT.format(what=2, slot=i, dir=-1)]),
                                        ("\\uF067", [SET_ACT.format(what=2, slot=i, dir=1)])], font=16,
                  id=f"set_b{i}")]
    return ws


def cstr(t):
    return '"' + t.replace("\\", "\\\\").replace('"', '\\"') + '"'


def emit_set_script():
    """set_ui(what, slot, dir): 0 show current, 1 refresh values, 2 step slot by dir,
    3 page by dir (may leave to a real page), 4 open virtual page `slot`, 5 help for row `slot`."""
    groups = {"SETUP": SETUP, "ADVANCED": ADV}
    rows_c = []
    for k, (pid, grp, title, _) in enumerate(VPAGES):
        g = groups[grp]
        rr = []
        for r in ROWREC[pid]:
            rr.append(f"{{id({r['nid']}), {cstr(r['name'])}, {cstr(r['fmt'])}, {cstr(r['help'])}, {r['ny']}, "
                      f"{r['cy']}, {r['by']}, {r['bh']}, {r['iy']}, &lv_font_montserrat_{r['nf']}, "
                      f"&lv_font_montserrat_{r['cf']}}}")
        rows_c.append(f"            {{{cstr(f'{grp} {g.index(pid) + 1}/{len(g)}')}, {cstr(title)}, {len(rr)}, {{{', '.join(rr)}}}}}")

    def seq(g):
        return ", ".join(str(VIRT.index(p)) if p in VIRT else str(REAL_CODE[p]) for p in g)
    n_setup_v = sum(1 for p in SETUP if p in VIRT)
    lines = f"""  # Shared settings page (generated by cyd_ui.py). One screen page shows the {len(VIRT)} settings
  # pages in turn, so their widgets exist only once in RAM.
  #   what: 0 show current, 1 refresh values, 2 step row `slot` by `dir`, 3 page by `dir`,
  #         4 open virtual page `slot`
  - id: set_ui
    mode: queued
    max_runs: 6
    parameters:
      what: int
      slot: int
      dir: int
    then:
      - lambda: |-
          struct Row {{ number::Number *n; const char *name, *fmt, *help; int16_t ny, cy, by, bh, iy; const lv_font_t *nf, *cf; }};
          struct Pg {{ const char *grp, *title; uint8_t nrows; Row r[4]; }};
          static const Pg P[] = {{
{(','+chr(10)).join(rows_c)}
          }};
          static const int8_t SEQ_S[] = {{{seq(SETUP)}}};    // <0 = real page: -1 rules, -2 sound, -3 display, -4 reset
          static const int8_t SEQ_A[] = {{{seq(ADV)}}};
          lv_obj_t *const N[4] = {{set_n0, set_n1, set_n2, set_n3}};
          lv_obj_t *const V[4] = {{set_v0, set_v1, set_v2, set_v3}};
          lv_obj_t *const B[4] = {{set_b0->obj, set_b1->obj, set_b2->obj, set_b3->obj}};
          lv_obj_t *const I[4] = {{set_i0, set_i1, set_i2, set_i3}};
          id(set_goto) = 0;
          int k = id(set_idx), w = what;
          if (w == 5) {{
            if (slot < P[k].nrows) id(show_help).execute(std::string(P[k].r[slot].help));
            return;
          }}
          if (w == 4) {{ k = slot; w = 0; id(set_goto) = 1; }}
          else if (w == 3) {{
            const bool setup = k < {n_setup_v};
            const int8_t *sq = setup ? SEQ_S : SEQ_A;
            const int n = setup ? (int) sizeof(SEQ_S) : (int) sizeof(SEQ_A);
            int pos = 0;
            for (int i = 0; i < n; i++) if (sq[i] == k) pos = i;
            const int8_t t = sq[(pos + dir + n) % n];
            if (t < 0) {{ id(set_goto) = t; return; }}
            k = t; w = 0;
          }} else if (w == 2) {{
            if (slot < P[k].nrows) {{
              auto c = P[k].r[slot].n->make_call();
              if (dir > 0) c.number_increment(false); else c.number_decrement(false);
              c.perform();                                // its on_value refreshes the values
            }}
            return;
          }}
          if (N[0] == nullptr) return;                    // screen not built yet
          id(set_idx) = k;
          const Pg &p = P[k];
          if (w == 0) {{
            lv_label_set_text(set_grp, p.grp);
            lv_label_set_text(set_title, p.title);
            for (int i = 0; i < 4; i++) {{
              if (i >= p.nrows) {{
                lv_obj_add_flag(N[i], LV_OBJ_FLAG_HIDDEN); lv_obj_add_flag(V[i], LV_OBJ_FLAG_HIDDEN);
                lv_obj_add_flag(B[i], LV_OBJ_FLAG_HIDDEN); lv_obj_add_flag(I[i], LV_OBJ_FLAG_HIDDEN);
                continue;
              }}
              const Row &r = p.r[i];
              lv_obj_remove_flag(N[i], LV_OBJ_FLAG_HIDDEN); lv_obj_remove_flag(V[i], LV_OBJ_FLAG_HIDDEN);
              lv_obj_remove_flag(B[i], LV_OBJ_FLAG_HIDDEN); lv_obj_remove_flag(I[i], LV_OBJ_FLAG_HIDDEN);
              lv_obj_set_y(I[i], r.iy);
              lv_label_set_text(N[i], r.name);
              lv_obj_set_style_text_font(N[i], r.nf, LV_PART_MAIN);
              lv_obj_set_y(N[i], r.ny);
              lv_obj_set_style_text_font(V[i], r.cf, LV_PART_MAIN);
              lv_obj_set_y(V[i], r.cy);
              lv_obj_set_y(B[i], r.by);
              lv_obj_set_height(B[i], r.bh);
            }}
          }}
          for (int i = 0; i < p.nrows; i++)
            lv_label_set_text(V[i], str_sprintf(p.r[i].fmt, p.r[i].n->state).c_str());
      - if:
          condition:
            lambda: 'return id(set_goto) == 1;'
          then: [ lvgl.page.show: page_set ]
"""
    for pid, code in REAL_CODE.items():
        lines += f"""      - if:
          condition:
            lambda: 'return id(set_goto) == {code};'
          then: [ lvgl.page.show: {pid} ]
"""
    lines += """  # Setting help (the (i) on a row): over any page, tap or 12 s to close.
  - id: show_help
    mode: restart
    parameters:
      msg: string
    then:
      - lvgl.label.update: { id: lbl_help, text: !lambda 'return msg;' }
      - lvgl.widget.show: lbl_help
      - delay: 12s
      - lvgl.widget.hide: lbl_help
"""
    return lines


def emit_script():
    return emit_ui_script() + "\n" + emit_set_script()


def emit_ui_script():
    """ui_refresh_values: fills the Home / Power / Info value chips (N/A without inverter data)."""
    o = ["  # Home / Power / Info value chips. Generated by ui.py. N/A when there is no fresh inverter data.",
         "  - id: ui_refresh_values",
         "    then:"]
    for vid, (expr, fmt, gated) in LIVE.items():
        cond = "!id(inv_link).state || isnan(v)" if gated else "isnan(v)"
        o += ["      - lvgl.label.update:",
              f"          id: {vid}",
              "          text: !lambda |-",
              f"            float v = {expr};"]
        if vid in DASH0:      # Home: nothing flowing = a dash, not "0 W"
            o += ["            if (!(" + cond + ") && fabsf(v) < 1.0f) return std::string(\"-\");"]
        o += [f'            return ({cond}) ? std::string("N/A") : str_sprintf("{fmt}", v);']
    for aid, expr in (("arc_pv", "id(s_pv_power).state / std::max(0.1f, id(n_pv_kwp).state) / 10.0f"),
                      ("arc_load", "id(s_load_power).state / std::max(100.0f, id(n_inv_max_w).state) * 100.0f")):
        o += ["      - lvgl.arc.update:",
              f"          id: {aid}",
              f"          value: !lambda 'float v = {expr}; return (!id(inv_link).state || isnan(v)) ? 0 : (int) v;'"]
    o += ["      - lambda: |-"] + ["          " + l for l in HOME_LAMBDA.strip("\n").split("\n")]
    o += ["      - lvgl.label.update:",
          "          id: lbl_age",
          "          text: !lambda |-",
          "            if (id(autopilot).last_data_ms() == 0) return std::string(\"never\");",
          "            return str_sprintf(\"%us\", (unsigned) ((millis() - id(autopilot).last_data_ms()) / 1000));"]
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

    srcs = dict(re.findall(r"- id: (\S+)\n  file: icons/(\S+)\.svg", open(os.path.join(ICON_DIR, "images.yaml")).read()))

    def icon(img, wd):
        import io
        import resvg_py
        png = bytes(resvg_py.svg_to_bytes(svg_path=os.path.join(ICON_DIR, srcs[wd["src"]] + ".svg"),
                                          width=wd["w"], height=wd["h"]))
        ic = Image.open(io.BytesIO(png)).convert("RGBA")
        solid = Image.new("RGBA", ic.size, rgb(wd["color"]) + (255,))
        solid.putalpha(ic.getchannel("A"))
        img.paste(solid, (wd["x"], wd["y"]), solid)

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
        bx = 56                      # badges shown in the preview are packed like on the device
        for wd in ws:
            if wd["t"] == "img" and str(wd["id"]).startswith("hm_b_") and wd["preview"]:
                wd["x"], bx = bx, bx + 22
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
            elif t == "img":
                if wd["preview"]:
                    icon(img, wd)
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
