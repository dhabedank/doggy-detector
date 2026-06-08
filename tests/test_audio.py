import pytest
import numpy as np
from collections import deque

from src.audio import RollingBuffer


def test_rolling_buffer_stores_samples():
    buffer = RollingBuffer(max_seconds=2.0, sample_rate=16000, channels=2)

    # Add 1 second of audio
    chunk = np.zeros((16000, 2), dtype=np.float32)
    buffer.add(chunk)

    assert buffer.duration_seconds == pytest.approx(1.0, rel=0.01)


def test_rolling_buffer_rolls_over():
    buffer = RollingBuffer(max_seconds=2.0, sample_rate=16000, channels=2)

    # Add 3 seconds of audio (should keep only last 2)
    for i in range(3):
        chunk = np.full((16000, 2), i, dtype=np.float32)
        buffer.add(chunk)

    assert buffer.duration_seconds == pytest.approx(2.0, rel=0.01)

    # Get all data - should be last 2 chunks
    data = buffer.get_all()
    assert data.shape == (32000, 2)


def test_rolling_buffer_get_last():
    buffer = RollingBuffer(max_seconds=5.0, sample_rate=16000, channels=2)

    # Add 3 seconds
    for i in range(3):
        chunk = np.full((16000, 2), i, dtype=np.float32)
        buffer.add(chunk)

    # Get last 1 second
    data = buffer.get_last(seconds=1.0)
    assert data.shape == (16000, 2)
    # Should be the last chunk (value 2)
    assert data[0, 0] == 2.0
