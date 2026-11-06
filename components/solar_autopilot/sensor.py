"""Values the controller computes, as sensors:  sensor: - platform: solar_autopilot"""

import esphome.codegen as cg
from esphome.components import sensor
import esphome.config_validation as cv
from esphome.const import (
    DEVICE_CLASS_POWER,
    STATE_CLASS_MEASUREMENT,
    UNIT_HOUR,
    UNIT_KILOWATT_HOURS,
    UNIT_PERCENT,
    UNIT_WATT,
)

from . import CONF_SOLAR_AUTOPILOT_ID, SolarAutopilot, solar_autopilot_ns

OutSensor = solar_autopilot_ns.enum("OutSensor")

# key: (C++ enum, schema)
SENSORS = {
    "reserve_switch": ("OUT_RESERVE_SWITCH", dict(unit_of_measurement=UNIT_PERCENT, accuracy_decimals=0,
                                                  icon="mdi:battery-arrow-down")),
    "reserve_return": ("OUT_RESERVE_RETURN", dict(unit_of_measurement=UNIT_PERCENT, accuracy_decimals=0,
                                                  icon="mdi:battery-arrow-up")),
    "forecast_used": ("OUT_FORECAST_USED", dict(unit_of_measurement=UNIT_KILOWATT_HOURS, accuracy_decimals=1,
                                                icon="mdi:weather-partly-cloudy")),
    "soc_at_sun": ("OUT_SOC_AT_SUN", dict(unit_of_measurement=UNIT_PERCENT, accuracy_decimals=0,
                                          icon="mdi:weather-sunset-up")),
    "base_load": ("OUT_BASE_LOAD", dict(unit_of_measurement=UNIT_WATT, accuracy_decimals=0,
                                        device_class=DEVICE_CLASS_POWER, state_class=STATE_CLASS_MEASUREMENT)),
    "battery_remaining": ("OUT_BATTERY_REMAINING", dict(unit_of_measurement=UNIT_KILOWATT_HOURS, accuracy_decimals=2,
                                                        icon="mdi:battery", state_class=STATE_CLASS_MEASUREMENT)),
    "battery_runtime": ("OUT_BATTERY_RUNTIME", dict(unit_of_measurement=UNIT_HOUR, accuracy_decimals=1,
                                                    icon="mdi:timer-sand", state_class=STATE_CLASS_MEASUREMENT)),
}

CONFIG_SCHEMA = cv.Schema(
    {cv.GenerateID(CONF_SOLAR_AUTOPILOT_ID): cv.use_id(SolarAutopilot),
     **{cv.Optional(k): sensor.sensor_schema(**kw) for k, (_, kw) in SENSORS.items()}}
)


async def to_code(config):
    parent = await cg.get_variable(config[CONF_SOLAR_AUTOPILOT_ID])
    for key, (enum, _) in SENSORS.items():
        if key in config:
            s = await sensor.new_sensor(config[key])
            cg.add(parent.set_out_sensor(getattr(OutSensor, enum), s))
