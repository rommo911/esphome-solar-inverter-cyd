"""Controller flags as binary sensors:  binary_sensor: - platform: solar_autopilot"""

import esphome.codegen as cg
from esphome.components import binary_sensor
import esphome.config_validation as cv
from esphome.const import DEVICE_CLASS_CONNECTIVITY, DEVICE_CLASS_POWER, DEVICE_CLASS_PROBLEM, ENTITY_CATEGORY_DIAGNOSTIC

from . import CONF_SOLAR_AUTOPILOT_ID, SolarAutopilot, solar_autopilot_ns

OutBinary = solar_autopilot_ns.enum("OutBinary")

BINARIES = {
    # fresh inverter data (reply < 30 s, SOC and load known): screens and HA automations go by this
    "link": ("OUT_LINK", dict(device_class=DEVICE_CLASS_CONNECTIVITY, entity_category=ENTITY_CATEGORY_DIAGNOSTIC)),
    "cloudy": ("OUT_CLOUDY", dict(icon="mdi:weather-cloudy")),
    "charging": ("OUT_CHARGING", dict(icon="mdi:transmission-tower-import")),
    "fault": ("OUT_FAULT", dict(device_class=DEVICE_CLASS_PROBLEM)),
    # grid present, debounced 30 s by the component (when it reads the grid voltage)
    "grid": ("OUT_GRID", dict(device_class=DEVICE_CLASS_POWER)),
}

CONFIG_SCHEMA = cv.Schema(
    {cv.GenerateID(CONF_SOLAR_AUTOPILOT_ID): cv.use_id(SolarAutopilot),
     **{cv.Optional(k): binary_sensor.binary_sensor_schema(**kw) for k, (_, kw) in BINARIES.items()}}
)


async def to_code(config):
    parent = await cg.get_variable(config[CONF_SOLAR_AUTOPILOT_ID])
    for key, (enum, _) in BINARIES.items():
        if key in config:
            b = await binary_sensor.new_binary_sensor(config[key])
            cg.add(parent.set_out_binary(getattr(OutBinary, enum), b))
