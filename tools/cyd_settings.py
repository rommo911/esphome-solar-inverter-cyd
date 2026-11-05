"""Every user setting of the CYD controller, defined once.

Used by cyd_v2_patch.py (number:/switch: sections, ui_sync_all, restore_defaults) and by
cyd_ui.py (screen rows). All settings are exposed to Home Assistant (entity_category: config).
"""

# id, HA name, unit, min, max, step, default, screen label, value format, kind
#   kind: "" = normal, "calib" = hardware calibration (kept by Restore defaults), "led" = LED level
NUMBERS = [
    # --- reserve planner (handoff 4A)
    ("n_cloudy_kwh", "Cloudy Below", "kWh", 0, 20, 0.5, 5, "Cloudy if forecast below", "%.1f kWh", ""),
    ("n_sunny_sw", "Sunny Day Switch SOC", "%", 16, 37, 1, 18, "Sunny: grid below", "%.0f %%", ""),
    ("n_sunny_ret", "Sunny Day Return SOC", "%", 25, 40, 1, 25, "Sunny: battery above", "%.0f %%", ""),
    ("n_cloudy_sw", "Cloudy Day Switch SOC", "%", 16, 37, 1, 25, "Cloudy: grid below", "%.0f %%", ""),
    ("n_cloudy_ret", "Cloudy Day Return SOC", "%", 25, 40, 1, 30, "Cloudy: battery above", "%.0f %%", ""),
    # --- charger manager (handoff 4B)
    ("n_chg_target", "Grid Charge Target", "%", 20, 80, 1, 40, "Cloudy: grid-charge to", "%.0f %%", ""),
    ("n_chg_margin", "Grid Charge Restart Margin", "%", 3, 30, 1, 10, "Restart below target by", "%.0f %%", ""),
    ("n_emerg_soc", "Emergency Charge Below", "%", 5, 30, 1, 15, "Emergency charge below", "%.0f %%", ""),
    ("n_emerg_target", "Emergency Charge Target", "%", 15, 50, 1, 25, "...charge up to", "%.0f %%", ""),
    ("n_fast_below", "Fast Charge Below", "%", 5, 50, 1, 20, "Fast charge below", "%.0f %%", ""),
    ("n_chg_fast_a", "Fast Charge Current", "A", 2, 60, 1, 20, "Fast current", "%.0f A", ""),
    ("n_chg_norm_a", "Normal Charge Current", "A", 2, 60, 1, 10, "Normal current", "%.0f A", ""),
    # --- overnight rule (handoff 4C/4D)
    ("n_ovn_floor", "Overnight Floor SOC", "%", 5, 40, 1, 10, "Min SOC at sunrise", "%.0f %%", ""),
    ("n_ovn_margin", "Overnight Margin", "%", 1, 20, 1, 5, "Release margin", "%.0f %%", ""),
    ("n_base_floor", "Base Load Floor", "W", 50, 2000, 50, 300, "Base load at least", "%.0f W", ""),
    ("n_sun_delay_sunny", "Sun Useful Delay Sunny", "h", 0, 6, 0.5, 1.5, "Sun useful after (sunny)", "%.1f h", ""),
    ("n_sun_delay_cloudy", "Sun Useful Delay Cloudy", "h", 0, 8, 0.5, 3, "...after (cloudy)", "%.1f h", ""),
    # --- timing / float
    ("n_low_delay", "Low SOC Delay", "s", 0, 300, 5, 60, "SOC must hold for", "%.0f s", ""),
    ("n_min_sub", "Min Time On Grid", "min", 0, 30, 1, 3, "Min time on grid", "%.0f min", ""),
    ("n_float_v", "Float Voltage Target", "V", 24, 29.2, 0.1, 27, "Float voltage", "%.1f V", ""),
    # --- HIGH load
    ("n_high_on_w", "High Load On", "W", 1000, 4000, 100, 2500, "Grid when load above", "%.0f W", ""),
    ("n_high_on_s", "High Load On Delay", "s", 0, 60, 1, 6, "...for at least", "%.0f s", ""),
    ("n_high_off_w", "High Load Off", "W", 500, 3500, 100, 2000, "Release when load below", "%.0f W", ""),
    ("n_high_off_s", "High Load Off Delay", "s", 5, 300, 5, 45, "...for at least", "%.0f s", ""),
    ("n_high_max_soc", "High Load Max SOC", "%", 30, 100, 5, 80, "Only if SOC below", "%.0f %%", ""),
    ("n_high_max_pv", "High Load Max PV", "W", 0, 4000, 100, 1200, "Only if PV below", "%.0f W", ""),
    # --- NIGHT load
    ("n_night_on_w", "Night Load On", "W", 500, 3000, 100, 1600, "Grid when load above", "%.0f W", ""),
    ("n_night_on_s", "Night Load On Delay", "s", 0, 300, 5, 30, "...for at least", "%.0f s", ""),
    ("n_night_max_soc", "Night Max SOC", "%", 30, 100, 5, 70, "Only if SOC below", "%.0f %%", ""),
    ("n_night_off_w", "Night Load Off", "W", 100, 2000, 50, 600, "Release when load below", "%.0f W", ""),
    ("n_night_off_s", "Night Load Off Delay", "s", 10, 600, 10, 60, "...for at least", "%.0f s", ""),
    ("n_back_soc", "Night Release SOC", "%", 30, 100, 5, 60, "Or battery above", "%.0f %%", ""),
    ("n_back_w", "Night Release Load", "W", 200, 3000, 100, 1000, "...and load below", "%.0f W", ""),
    ("n_back_s", "Night Release Delay", "s", 0, 120, 5, 10, "...for at least", "%.0f s", ""),
    # --- battery / solar array
    ("n_batt_kwh", "Battery Capacity", "kWh", 1, 30, 0.1, 4.5, "Battery capacity", "%.1f kWh", ""),
    ("n_empty_soc", "Battery Empty At", "%", 0, 30, 1, 5, "Treat as empty at", "%.0f %%", ""),
    ("n_pv_kwp", "PV Array Size", "kWp", 0.5, 20, 0.1, 2.0, "Array size", "%.1f kWp", ""),
    ("n_pv_tilt", "PV Tilt", "°", 0, 90, 1, 40, "Tilt (0 = flat)", "%.0f°", ""),
    ("n_pv_az", "PV Azimuth", "°", -180, 180, 5, 0, "Facing (0=S -90=E 90=W)", "%.0f°", ""),
    # --- sound
    ("n_quiet_start", "Quiet Hours From", "h", 0, 23, 1, 1, "Quiet from", "%02.0f:00", ""),
    ("n_quiet_end", "Quiet Hours Until", "h", 0, 23, 1, 9, "Quiet until", "%02.0f:00", ""),
    # --- display / LED
    ("n_bl_min", "Backlight Min (auto)", "%", 5, 100, 5, 20, "Auto min brightness", "%.0f %%", ""),
    ("n_ldr_dark", "LDR Dark Reading", "V", 0, 1.2, 0.001, 0.3, None, None, "calib"),
    ("n_ldr_bright", "LDR Bright Reading", "V", 0, 1.2, 0.001, 0.0, None, None, "calib"),
    ("n_led_r", "LED Red Level", "%", 5, 100, 5, 100, None, None, "led"),
    ("n_led_g", "LED Green Level", "%", 5, 100, 5, 100, None, None, "led"),
    ("n_led_b", "LED Blue Level", "%", 5, 100, 5, 100, None, None, "led"),
]

# id, HA name, default on, screen widget id (None = HA only), icon, extra YAML for on_turn_off
SWITCHES = [
    ("auto_ctl", "Auto Control", True, "lv_auto_ctl", "mdi:robot", ""),
    ("sw_observe", "Observe Only", True, "lv_sw_observe", "mdi:eye", ""),
    ("sw_rule_low", "Rule Low Battery", True, "lv_sw_rule_low", "", ""),
    ("sw_rule_high", "Rule High Load", True, "lv_sw_rule_high", "", ""),
    ("sw_rule_night", "Rule Night Load", True, "lv_sw_rule_night", "", ""),
    ("sw_rule_ovn", "Rule Overnight", True, "lv_sw_rule_ovn", "", ""),
    ("sw_rule_charge", "Charger Manager", True, "lv_sw_rule_charge", "", ""),
    ("sw_rule_float", "Rule Float Voltage", True, "lv_sw_rule_float", "", ""),
    ("sw_buzzer", "Buzzer", True, "lv_sw_buzzer", "mdi:volume-high", ""),
    ("sw_quiet", "Buzzer Quiet Hours", True, "lv_sw_quiet", "mdi:volume-off", ""),
    ("sw_autobl", "Auto Brightness", False, "lv_sw_autobl", "mdi:brightness-auto", ""),
    ("sw_touchdbg", "Touch Debug", False, "lv_sw_touchdbg", "mdi:gesture-tap",
     "            - lvgl.widget.hide: touch_dot\n"),
]

BY_ID = {n[0]: n for n in NUMBERS}

# Settings pages that consist only of setting rows. On the device they are ONE screen page
# ("page_set") whose rows are refilled when you page through them (saves ~150 widgets of RAM).
# (page id, group, title, setting ids) - order = order on screen within the group.
VPAGES = [
    ("page_s_res", "SETUP", "Battery reserve", ["n_sunny_sw", "n_sunny_ret", "n_cloudy_sw", "n_cloudy_ret"]),
    ("page_s_plan", "SETUP", "Forecast & charging", ["n_cloudy_kwh", "n_chg_target"]),
    ("page_a_high1", "ADVANCED", "High load", ["n_high_on_w", "n_high_on_s", "n_high_off_w", "n_high_off_s"]),
    ("page_a_high2", "ADVANCED", "High load limits", ["n_high_max_soc", "n_high_max_pv"]),
    ("page_a_night1", "ADVANCED", "Night load on", ["n_night_on_w", "n_night_on_s", "n_night_max_soc"]),
    ("page_a_night2", "ADVANCED", "Night load off", ["n_night_off_w", "n_night_off_s"]),
    ("page_a_night3", "ADVANCED", "Night release 2", ["n_back_soc", "n_back_w", "n_back_s"]),
    ("page_a_ovn1", "ADVANCED", "Overnight", ["n_ovn_floor", "n_ovn_margin", "n_base_floor"]),
    ("page_a_ovn2", "ADVANCED", "Overnight sun delay", ["n_sun_delay_sunny", "n_sun_delay_cloudy"]),
    ("page_a_chg1", "ADVANCED", "Grid charging", ["n_emerg_soc", "n_emerg_target", "n_fast_below"]),
    ("page_a_chg2", "ADVANCED", "Charge current", ["n_chg_fast_a", "n_chg_norm_a", "n_chg_margin"]),
    ("page_a_timing", "ADVANCED", "Timing", ["n_low_delay", "n_min_sub", "n_float_v"]),
    ("page_a_batt", "ADVANCED", "Battery capacity", ["n_batt_kwh", "n_empty_soc"]),
    ("page_a_pv", "ADVANCED", "Solar panels", ["n_pv_kwp", "n_pv_tilt", "n_pv_az"]),
]
VIRTUAL_NIDS = {nid for _, _, _, nids in VPAGES for nid in nids}
