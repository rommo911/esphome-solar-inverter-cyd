"""Solar autopilot: inverter controller (output priority, grid charging, alarms) as an ESPHome
component. The logic is the plain C++ core in this folder (ap_*.h / ap_*.cpp, no ESPHome);
this file and solar_autopilot.{h,cpp} only connect it to entities."""

from esphome import automation
import esphome.codegen as cg
from esphome.components import binary_sensor, http_request, number, select, sensor, sun, switch, time
import esphome.config_validation as cv
from esphome.const import CONF_ID, CONF_LATITUDE, CONF_LONGITUDE, CONF_TIME_ID, CONF_TRIGGER_ID

from .settings_keys import NUMBERS, SWITCHES

CODEOWNERS = ["@rommo911"]
DEPENDENCIES = ["time", "sun"]

solar_autopilot_ns = cg.esphome_ns.namespace("solar_autopilot")
SolarAutopilot = solar_autopilot_ns.class_("SolarAutopilot", cg.Component)
TuneTrigger = solar_autopilot_ns.class_(
    "TuneTrigger", automation.Trigger.template(cg.std_string, cg.int_, cg.bool_)
)
NotifyTrigger = solar_autopilot_ns.class_("NotifyTrigger", automation.Trigger.template(cg.std_string))

CONF_SOLAR_AUTOPILOT_ID = "solar_autopilot_id"
CONF_SUN_ID = "sun_id"
CONF_ALARM_SOC = "alarm_soc"
CONF_REPEAT_SOC = "alarm_repeat_soc"
CONF_SETTINGS = "settings"
CONF_ON_TUNE = "on_tune"
CONF_ON_NOTIFY = "on_notify"
CONF_FORECAST = "forecast"

# Forecast.Solar: fetched by the component (needs http_request:). The plane (kWp, tilt, azimuth)
# and the refresh interval are settings (pv_kwp, pv_tilt, pv_az, fc_interval_h).
FORECAST_SCHEMA = cv.Schema(
    {
        cv.GenerateID(http_request.CONF_HTTP_REQUEST_ID): cv.use_id(http_request.HttpRequestComponent),
        cv.Required(CONF_LATITUDE): cv.float_range(min=-90, max=90),
        cv.Required(CONF_LONGITUDE): cv.float_range(min=-180, max=180),
    }
)

# readings
SENSORS = {
    "soc": "set_soc",
    "load_power": "set_load",
    "pv_power": "set_pv",
    "output_priority_state": "set_output_priority_state",
    "charger_source_state": "set_charger_source_state",
    "charge_current_state": "set_charge_current_state",
    "float_voltage_state": "set_float_voltage_state",
    "solar_today": "set_solar_today",
}
REQUIRED_SENSORS = {"soc", "load_power", "output_priority_state"}
BINARY_SENSORS = {"grid": "set_grid", "floating": "set_floating"}
TEMPLATES = {"forecast_today": "set_forecast_today", "forecast_tomorrow": "set_forecast_tomorrow"}
# what it writes
SELECTS = {
    "output_priority": "set_output_priority",
    "charger_source": "set_charger_source",
    "charge_current": "set_charge_current",
    "float_voltage": "set_float_voltage",
}

SETTINGS_SCHEMA = cv.Schema(
    {**{cv.Optional(k): cv.use_id(number.Number) for k in NUMBERS},
     **{cv.Optional(k): cv.use_id(switch.Switch) for k in SWITCHES}}
)

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(SolarAutopilot),
        cv.GenerateID(CONF_TIME_ID): cv.use_id(time.RealTimeClock),
        cv.GenerateID(CONF_SUN_ID): cv.use_id(sun.Sun),
        cv.Optional(CONF_ALARM_SOC, default=30): cv.percentage_int,
        cv.Optional(CONF_REPEAT_SOC, default=20): cv.percentage_int,
        **{(cv.Required(k) if k in REQUIRED_SENSORS else cv.Optional(k)): cv.use_id(sensor.Sensor) for k in SENSORS},
        cv.Required("grid"): cv.use_id(binary_sensor.BinarySensor),
        cv.Optional("floating"): cv.use_id(binary_sensor.BinarySensor),
        cv.Optional(CONF_FORECAST): FORECAST_SCHEMA,
        # forecast from elsewhere instead (kWh), e.g. Home Assistant
        **{cv.Optional(k): cv.templatable(cv.float_) for k in TEMPLATES},
        cv.Required("output_priority"): cv.use_id(select.Select),
        cv.Optional("charger_source"): cv.use_id(select.Select),
        cv.Optional("charge_current"): cv.use_id(select.Select),
        cv.Optional("float_voltage"): cv.use_id(select.Select),
        cv.Optional(CONF_SETTINGS, default={}): SETTINGS_SCHEMA,
        cv.Optional(CONF_ON_TUNE): automation.validate_automation(
            {cv.GenerateID(CONF_TRIGGER_ID): cv.declare_id(TuneTrigger)}
        ),
        cv.Optional(CONF_ON_NOTIFY): automation.validate_automation(
            {cv.GenerateID(CONF_TRIGGER_ID): cv.declare_id(NotifyTrigger)}
        ),
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    cg.add(var.set_time(await cg.get_variable(config[CONF_TIME_ID])))
    cg.add(var.set_sun(await cg.get_variable(config[CONF_SUN_ID])))
    cg.add(var.set_alarm_config(config[CONF_ALARM_SOC], config[CONF_REPEAT_SOC]))   # percent, 0..100
    for table in (SENSORS, BINARY_SENSORS, SELECTS):
        for key, setter in table.items():
            if key in config:
                cg.add(getattr(var, setter)(await cg.get_variable(config[key])))
    if CONF_FORECAST in config:
        fc = config[CONF_FORECAST]
        cg.add_define("USE_SOLAR_AUTOPILOT_FORECAST")
        http = await cg.get_variable(fc[http_request.CONF_HTTP_REQUEST_ID])
        cg.add(var.set_forecast(http, fc[CONF_LATITUDE], fc[CONF_LONGITUDE]))
    for key, setter in TEMPLATES.items():
        if key in config:
            cg.add(getattr(var, setter)(await cg.templatable(config[key], [], cg.float_)))
    for key, value in config[CONF_SETTINGS].items():
        ent = await cg.get_variable(value)
        if key in NUMBERS:
            cg.add(var.set_number(cg.RawExpression(f"autopilot_core::N_{key}"), ent))
        else:
            cg.add(var.set_switch(cg.RawExpression(f"autopilot_core::S_{key}"), ent))
    for conf in config.get(CONF_ON_TUNE, []):
        trigger = cg.new_Pvariable(conf[CONF_TRIGGER_ID], var)
        await automation.build_automation(
            trigger, [(cg.std_string, "tune"), (cg.int_, "prio"), (cg.bool_, "critical")], conf
        )
    for conf in config.get(CONF_ON_NOTIFY, []):
        trigger = cg.new_Pvariable(conf[CONF_TRIGGER_ID], var)
        await automation.build_automation(trigger, [(cg.std_string, "message")], conf)
