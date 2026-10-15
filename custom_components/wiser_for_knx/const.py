"""Constants for the Wiser for KNX integration."""

from homeassistant.const import Platform

DOMAIN = "wiser_for_knx"

# Configuration keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_SSL = "ssl"
CONF_VERIFY_SSL = "verify_ssl"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_API_BASE = "api_base"

# Defaults
DEFAULT_PORT = 443
DEFAULT_SSL = True
DEFAULT_VERIFY_SSL = False
DEFAULT_SCAN_INTERVAL = 10  # seconds
DEFAULT_USERNAME = "admin"
DEFAULT_API_BASE = "/api/w4knx/3rdparty/v1"

# Management API (backups, device info) and backup settings
MGMT_API_BASE = "/api/management/v1"
CONF_BACKUP_PASSWORD = "backup_password"
CONF_BACKUP_INTERVAL = "backup_interval_hours"
CONF_BACKUP_KEEP = "backup_keep"
DEFAULT_BACKUP_INTERVAL = 24  # hours, 0 = scheduled backups disabled
DEFAULT_BACKUP_KEEP = 7
CONF_BACKUP_NOW = "backup_now"
DATA_INITIAL_BACKUP = f"{DOMAIN}_initial_backup"
BACKUP_DIR = "wiser_backups"
BACKUP_KINDS = {
    "system": "/flashsys/system/backupConfiguration",
    "project": "/scada-main/general/backup",
}
SERVICE_CREATE_BACKUP = "create_backup"

# Supported Home Assistant Platforms
PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.SWITCH,
    Platform.SENSOR,
]

# KNX IoT 3rd Party Function URNs
FCT_SWITCHING_LIGHT = "urn:knx:fct.switchingLight"
FCT_DIMMING = "urn:knx:fct.dimming"
FCT_SWITCHING_SOCKET = "urn:knx:fct.switchingSocket"
FCT_SWITCHING = "urn:knx:fct.switching"
FCT_BLINDS = "urn:knx:fct.blindsVertical"
FCT_TEMPERATURE_AIR_FAN = "urn:knx:fct.temperatureAirFan"
FCT_GENERIC_THERMOSTAT = "urn:knx:fct.genericThermostat"
FCT_VDC_THERMOSTAT = "urn:knx:fct.VDCThermostat"
FCT_ITRV = "urn:knx:fct.iTRV"
FCT_POWER = "urn:knx:fct.power"
FCT_AIR_QUALITY = "urn:knx:fct.airQuality"
FCT_WEATHER = "urn:knx:fct.weather"
FCT_GAUGE = "urn:knx:fct.gauge"
FCT_WINDOW_DOOR = "urn:knx:fct.windowDoorSensor"
FCT_MOVEMENT = "urn:knx:fct.movementDetector"
FCT_ALARM = "urn:knx:fct.alarm"
FCT_ALARM_DEW_POINT = "urn:knx:fct.alarmDewPoint"
FCT_ALARM_WATER = "urn:knx:fct.alarmWater"
