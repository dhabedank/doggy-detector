import pytest
import numpy as np

from src.direction import analyze_direction, DirectionResult


def test_louder_left_returns_left():
    # Left channel louder
    left = np.array([0.8, 0.9, 0.85, 0.7])
    right = np.array([0.2, 0.3, 0.25, 0.2])
    stereo = np.column_stack([left, right])

    result = analyze_direction(stereo)

    assert result.direction == "left"
    assert result.confidence > 0.5


def test_louder_right_returns_right():
    # Right channel louder
    left = np.array([0.2, 0.3, 0.25, 0.2])
    right = np.array([0.8, 0.9, 0.85, 0.7])
    stereo = np.column_stack([left, right])

    result = analyze_direction(stereo)

    assert result.direction == "right"
    assert result.confidence > 0.5


def test_equal_channels_returns_center():
    # Equal volume both channels
    left = np.array([0.5, 0.6, 0.55, 0.5])
    right = np.array([0.5, 0.6, 0.55, 0.5])
    stereo = np.column_stack([left, right])

    result = analyze_direction(stereo)

    assert result.direction == "center"


def test_slight_difference_low_confidence():
    # Slight difference
    left = np.array([0.5, 0.6, 0.55, 0.5])
    right = np.array([0.45, 0.55, 0.5, 0.45])
    stereo = np.column_stack([left, right])

    result = analyze_direction(stereo)

    assert result.confidence < 0.5
