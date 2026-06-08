"""Weather data from Open-Meteo API."""

from dataclasses import dataclass
from typing import Optional
import httpx


@dataclass
class WeatherData:
    temp_f: float
    wind_mph: float
    conditions: str


class WeatherClient:
    BASE_URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def fetch(self, lat: Optional[float], lon: Optional[float]) -> Optional[WeatherData]:
        """Fetch current weather for coordinates."""
        if lat is None or lon is None:
            return None

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.BASE_URL,
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current": "temperature_2m,wind_speed_10m,weather_code",
                        "temperature_unit": "fahrenheit",
                        "wind_speed_unit": "mph",
                    },
                    timeout=10.0,
                )
                response.raise_for_status()
                data = response.json()

                current = data.get("current", {})
                return WeatherData(
                    temp_f=current.get("temperature_2m", 0.0),
                    wind_mph=current.get("wind_speed_10m", 0.0),
                    conditions=self._code_to_conditions(current.get("weather_code", 0)),
                )
        except Exception:
            return None

    def _code_to_conditions(self, code: int) -> str:
        """Convert WMO weather code to human-readable conditions."""
        if code == 0:
            return "clear"
        elif code in (1, 2):
            return "partly cloudy"
        elif code == 3:
            return "cloudy"
        elif code in (45, 48):
            return "fog"
        elif code in (51, 53, 55, 56, 57):
            return "drizzle"
        elif code in (61, 63, 65, 66, 67, 80, 81, 82):
            return "rain"
        elif code in (71, 73, 75, 77, 85, 86):
            return "snow"
        elif code in (95, 96, 99):
            return "thunderstorm"
        else:
            return "unknown"
