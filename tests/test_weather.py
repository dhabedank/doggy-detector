import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.weather import WeatherClient, WeatherData


@pytest.mark.asyncio
async def test_fetch_weather_returns_data():
    """Test that fetch returns correct weather data when API call succeeds."""
    # Mock the AsyncClient context manager
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "current": {
            "temperature_2m": 72.0,
            "wind_speed_10m": 5.0,
            "weather_code": 0,
        }
    }
    mock_response.raise_for_status = MagicMock(return_value=None)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("src.weather.httpx.AsyncClient", return_value=mock_client):
        client = WeatherClient()
        result = await client.fetch(lat=34.05, lon=-118.24)

        assert result is not None
        assert result.temp_f == 72.0
        assert result.wind_mph == 5.0
        assert result.conditions == "clear"


@pytest.mark.asyncio
async def test_fetch_weather_handles_none_location():
    client = WeatherClient()
    result = await client.fetch(lat=None, lon=None)

    assert result is None


def test_weather_code_to_conditions():
    client = WeatherClient()

    assert client._code_to_conditions(0) == "clear"
    assert client._code_to_conditions(1) == "partly cloudy"
    assert client._code_to_conditions(2) == "partly cloudy"
    assert client._code_to_conditions(3) == "cloudy"
    assert client._code_to_conditions(61) == "rain"
    assert client._code_to_conditions(95) == "thunderstorm"
