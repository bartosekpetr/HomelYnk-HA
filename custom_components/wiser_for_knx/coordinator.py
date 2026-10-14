"""DataUpdateCoordinator for Wiser for KNX IoT 3rd Party API."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import WiserKnxAuthError, WiserKnxClient
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FCT_AIR_QUALITY,
    FCT_ALARM,
    FCT_ALARM_DEW_POINT,
    FCT_ALARM_WATER,
    FCT_BLINDS,
    FCT_DIMMING,
    FCT_GAUGE,
    FCT_GENERIC_THERMOSTAT,
    FCT_ITRV,
    FCT_MOVEMENT,
    FCT_POWER,
    FCT_SWITCHING,
    FCT_SWITCHING_LIGHT,
    FCT_SWITCHING_SOCKET,
    FCT_TEMPERATURE_AIR_FAN,
    FCT_VDC_THERMOSTAT,
    FCT_WEATHER,
    FCT_WINDOW_DOOR,
)

_LOGGER = logging.getLogger(__name__)


class WiserKnxDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching KNX IoT data (locations, functions, datapoints) from Wiser."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: WiserKnxClient,
        update_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialize the coordinator."""
        self.client = client
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch locations, functions, and datapoints from Wiser."""
        try:
            # 1. Fetch locations
            locations = await self.client.get_locations()

            # 2. Fetch functions
            functions = await self.client.get_functions()

            # 3. Fetch datapoints
            datapoints = await self.client.get_datapoints()

            # 4. Associate datapoints to functions and locations
            for dp_id, dp in datapoints.items():
                p_func_id = dp.get("parent_function_id")
                if p_func_id and p_func_id in functions:
                    functions[p_func_id]["datapoints"][dp_id] = dp

                p_loc_id = dp.get("parent_location_id")
                if p_loc_id and p_func_id and p_func_id in functions and not functions[p_func_id].get("location_id"):
                    functions[p_func_id]["location_id"] = p_loc_id

            return {
                "locations": locations,
                "functions": functions,
                "datapoints": datapoints,
            }
        except WiserKnxAuthError as err:
            raise UpdateFailed(f"Authentication error communicating with Wiser: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Error fetching data from Wiser for KNX: {err}") from err

    async def async_write_datapoint(self, datapoint_id: str, value: Any) -> bool:
        """Write value to datapoint and optimistically update local state."""
        success = await self.client.write_datapoint_value(datapoint_id, value)
        if success and self.data and "datapoints" in self.data:
            if datapoint_id in self.data["datapoints"]:
                self.data["datapoints"][datapoint_id]["value"] = str(value)
                self.async_update_listeners()
        return success

    @staticmethod
    def classify_function(func_dict: dict[str, Any]) -> str:
        """Classify a function into light, switch, cover, climate, or sensor."""
        types = func_dict.get("types", [])
        title = (func_dict.get("title") or "").lower()

        # 1. Dimmers
        if any(t == FCT_DIMMING or "dimming" in t.lower() for t in types):
            return "light"

        # 2. Switching lights
        if any(t == FCT_SWITCHING_LIGHT or "switchinglight" in t.lower() for t in types):
            return "light"

        # 3. Switches and sockets
        if any(
            t in (FCT_SWITCHING_SOCKET, FCT_SWITCHING) or "switch" in t.lower() or "socket" in t.lower()
            for t in types
        ):
            return "switch"

        # 4. Blinds / Covers
        if any(t == FCT_BLINDS or "blind" in t.lower() or "shutter" in t.lower() for t in types):
            return "cover"

        # 5. Climate / HVAC / Thermostats
        if any(
            t in (FCT_TEMPERATURE_AIR_FAN, FCT_GENERIC_THERMOSTAT, FCT_VDC_THERMOSTAT, FCT_ITRV)
            or "thermostat" in t.lower()
            or "climate" in t.lower()
            for t in types
        ):
            return "climate"

        # 6. Sensors
        if any(
            t in (FCT_POWER, FCT_AIR_QUALITY, FCT_WEATHER, FCT_GAUGE, FCT_WINDOW_DOOR, FCT_MOVEMENT, FCT_ALARM, FCT_ALARM_DEW_POINT, FCT_ALARM_WATER)
            or "sensor" in t.lower()
            or "alarm" in t.lower()
            or "power" in t.lower()
            for t in types
        ):
            return "sensor"

        # Heuristic fallbacks on title
        if any(w in title for w in ["dimm", "light", "lamp", "spot", "led", "eclairage"]):
            return "light"
        if any(w in title for w in ["switch", "socket", "prise", "plug"]):
            return "switch"
        if any(w in title for w in ["blind", "shutter", "volet", "curtain"]):
            return "cover"
        if any(w in title for w in ["thermostat", "temp", "heating", "cooling", "chauffage"]):
            return "climate"

        return "sensor"
