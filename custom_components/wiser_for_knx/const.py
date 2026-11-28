"""Constants for the Wiser for KNX integration."""

from homeassistant.const import Platform

DOMAIN = "wiser_for_knx"

# Configuration keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_SSL = "ssl"
CONF_VERIFY_SSL = "verify_ssl"
CONF_PLAIN_HTTP = "plain_http"  # form-only inverse of ssl
CONF_CERT_FINGERPRINT = "certificate_fingerprint"  # pinned SHA-256, hex
CONF_SKIP_VERIFY = "skip_verify"  # form-only inverse of verify_ssl
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_API_BASE = "api_base"

# Defaults
DEFAULT_PORT = 443
DEFAULT_SSL = True
DEFAULT_VERIFY_SSL = True  # new entries are verified unless the user opts out
DEFAULT_SCAN_INTERVAL = 10  # seconds
# Locations and functions only change when the KNX project is reconfigured, so they are
# fetched once and refreshed on this slow cadence instead of on every datapoint poll.
STATIC_REFRESH_INTERVAL = 3600  # seconds
# After a failed static refresh (cache kept) wait this long before trying again.
STATIC_RETRY_INTERVAL = 300  # seconds
# A cache older than this with refreshes still failing is no longer trusted: the update
# fails and entities go unavailable rather than silently serving stale structure forever.
STATIC_MAX_AGE = 3 * STATIC_REFRESH_INTERVAL  # seconds
DEFAULT_USERNAME = "admin"
DEFAULT_API_BASE = "/api/w4knx/3rdparty/v1"
# This controller build answers HTTP 500 on /datapoints and /functions now and then,
# most often while it recomputes which group objects to export after a config change.
# /datapoints is the one request the whole entity graph is built from, so a single
# unretried 500 makes every entity unavailable; retry briefly before giving up.
COLLECTION_RETRIES = 3
COLLECTION_RETRY_BACKOFF = 0.5  # seconds before the second attempt, doubled after that
# Consecutive failed datapoint polls before the log explains the known controller-side
# cause (see docs/controller-api.md). At the default scan interval this is about 30 s.
SERVER_ERROR_HINT_AFTER = 3

ISSUE_INSECURE_TLS = "insecure_tls_{entry_id}"
ISSUE_INSECURE_HTTP = "insecure_http_{entry_id}"

# Push: the controller's HTTP callback channel (POST /subscribe). On by default;
# the poll never goes away, it slows down to PUSH_BACKSTOP_INTERVAL while callbacks
# are arriving, because push fails silent and nothing on the controller restarts the
# daemon that delivers it (docs/controller-api.md §3b).
CONF_PUSH = "push"
DEFAULT_PUSH = True
SUBSCRIBE_PATH = "subscribe"
SUBSCRIPTIONS_PATH = "subscriptions"
# The poll's cadence while callbacks are proving themselves. Long enough to stop
# re-transferring the whole datapoint collection every few seconds (the collections
# are not pageable), short enough to be a real backstop.
PUSH_BACKSTOP_INTERVAL = 300  # seconds
# Wait before re-asserting a subscription the controller refused, doubling up to the
# cap. The controller never re-establishes delivery by itself, so this never stops.
PUSH_RETRY_INTERVAL = 60  # seconds
PUSH_RETRY_MAX_INTERVAL = 1800  # seconds
# Datapoints whose value changed between two backstop polls without a callback
# reporting them. One can be the race between a poll response and a callback in
# flight, so one is confirmed over two polls while two in a single poll is taken as
# delivery having stopped.
PUSH_MISS_THRESHOLD = 2
# Shortest gap between two subscription re-asserts, so a controller that keeps
# changing its exported set cannot turn every poll into a re-subscribe.
PUSH_RESUBSCRIBE_DEBOUNCE = 60  # seconds
# No cap on datapoints per subscribe body has been measured. The whole set is sent
# as one body; only if the controller refuses it is it retried in batches of this
# size, so the size is a fallback and not a prediction.
PUSH_SUBSCRIBE_CHUNK = 100

# Values of the "Push" diagnostic sensor.
# None of these may be one of Home Assistant's reserved state strings. `failed`
# read `unavailable` through v0.9.0, which was a mistake worth remembering: a state
# of "unavailable" is how Home Assistant renders an entity that is *not being
# provided at all*, so a push channel that had merely failed to register looked
# exactly like a broken entity - and the two want opposite responses. Worse, the
# reason it had failed was in `extra_state_attributes`, which Home Assistant
# drops for a genuinely unavailable entity, so the reader could not even tell
# which case they were in from the attributes. Measured against HA 2026.2.3:
# `Entity.__async_calculate_state` keeps extra attributes only when `available`.
PUSH_STATUS_OFF = "off"  # turned off in the options
PUSH_STATUS_FAILED = "failed"  # could not be set up; polling at full speed
PUSH_STATUS_PENDING = "pending"  # subscribed, no callback seen yet
PUSH_STATUS_LIVE = "live"  # callbacks arriving; the poll is the slow backstop
PUSH_STATUS_DEGRADED = "degraded"  # delivery stopped; polling at full speed again
# Home Assistant renders these two itself; a sensor must never report one as a value.
HA_RESERVED_STATES = ("unavailable", "unknown")

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
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.LIGHT,
    Platform.LOCK,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

# KNX IoT 3rd Party function URNs measured on real controllers. Classification
# matches on substrings of the whole URN (widgets.py), because vendor types such as
# `urn:knx:fct.schneider.logicThermostat.type.thermostat` exist; these constants are
# the inventory, not the matcher.
FCT_SWITCHING_LIGHT = "urn:knx:fct.switchingLight"
FCT_DIMMING = "urn:knx:fct.dimming"
FCT_DIMMING_DALI = "urn:knx:fct.dimmingDali"
FCT_COLOR_RGB = "urn:knx:fct.colorRGB"
FCT_COLOR_RGBW = "urn:knx:fct.colorRGBW"
FCT_SWITCHING_SOCKET = "urn:knx:fct.switchingSocket"
FCT_SWITCHING = "urn:knx:fct.switching"
FCT_SWITCHING_AC = "urn:knx:fct.switchingAC"
FCT_SWITCHING_FAN = "urn:knx:fct.switchingFan"
FCT_BLINDS = "urn:knx:fct.blindsVertical"
FCT_BLINDS_HORIZONTAL = "urn:knx:fct.blindsHorizontal"
FCT_SHADING_ROTARY = "urn:knx:fct.shadingRotary"
FCT_BLINDS_PLAIN = "urn:knx:fct.blinds"
FCT_TEMPERATURE_AIR_FAN = "urn:knx:fct.temperatureAirFan"
FCT_TEMPERATURE_AIR = "urn:knx:fct.temperatureAir"
FCT_TEMPERATURE_FLOOR = "urn:knx:fct.temperatureFloor"
FCT_GENERIC_THERMOSTAT = "urn:knx:fct.genericThermostat"
FCT_VDC_THERMOSTAT = "urn:knx:fct.VDCThermostat"
FCT_ITRV = "urn:knx:fct.iTRV"
FCT_SE8000 = "urn:knx:fct.se8000"
FCT_AIRZONE = "urn:knx:fct.airzone"
FCT_SMART_LOCK = "urn:knx:fct.smartLock"
FCT_SCENE = "urn:knx:fct.scene"
FCT_POWER = "urn:knx:fct.power"
FCT_AIR_QUALITY = "urn:knx:fct.airQuality"
FCT_GAS_SENSOR = "urn:knx:fct.gasSensor"
FCT_PARTICLE_SENSOR = "urn:knx:fct.particleSensor"
FCT_WEATHER = "urn:knx:fct.weather"
FCT_GAUGE = "urn:knx:fct.gauge"
FCT_INFO = "urn:knx:fct.info"
FCT_CONTENT = "urn:knx:fct.content"
FCT_WINDOW_DOOR = "urn:knx:fct.windowDoorSensor"
FCT_WINDOOR_DOOR = "urn:knx:fct.schneider.windoor.type.door"
FCT_MOVEMENT = "urn:knx:fct.movementDetector"
FCT_ALARM = "urn:knx:fct.alarm"
FCT_ALARM_FIRE = "urn:knx:fct.alarmFire"
FCT_ALARM_GAS = "urn:knx:fct.alarmGas"
FCT_ALARM_LIGHT = "urn:knx:fct.alarmLight"
FCT_ALARM_TEMP = "urn:knx:fct.alarmTemp"
FCT_ALARM_WIND = "urn:knx:fct.alarmWind"
FCT_ALARM_DEW_POINT = "urn:knx:fct.alarmDewPoint"
FCT_ALARM_WATER = "urn:knx:fct.alarmWater"
FCT_ALARM_AUTOMATION = "urn:knx:fct.alarmAutomation"
