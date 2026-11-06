"""The controller's state in words:  text_sensor: - platform: solar_autopilot"""

import esphome.codegen as cg
from esphome.components import text_sensor
import esphome.config_validation as cv

from . import CONF_SOLAR_AUTOPILOT_ID, SolarAutopilot

CONFIG_SCHEMA = cv.Schema(
    {cv.GenerateID(CONF_SOLAR_AUTOPILOT_ID): cv.use_id(SolarAutopilot),
     cv.Optional("state"): text_sensor.text_sensor_schema(icon="mdi:robot")}
)


async def to_code(config):
    parent = await cg.get_variable(config[CONF_SOLAR_AUTOPILOT_ID])
    if "state" in config:
        cg.add(parent.set_state_text(await text_sensor.new_text_sensor(config["state"])))
