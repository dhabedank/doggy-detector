"""Direction detection from stereo audio."""

from dataclasses import dataclass
from typing import Literal
import numpy as np


@dataclass
class DirectionResult:
    direction: Literal["left", "right", "center"]
    confidence: float
    left_rms: float
    right_rms: float


def analyze_direction(stereo_audio: np.ndarray) -> DirectionResult:
    """
    Analyze stereo audio to determine direction.

    Args:
        stereo_audio: numpy array of shape (samples, 2) with left and right channels

    Returns:
        DirectionResult with direction, confidence, and RMS values
    """
    if stereo_audio.ndim != 2 or stereo_audio.shape[1] != 2:
        raise ValueError("Expected stereo audio with shape (samples, 2)")

    left_channel = stereo_audio[:, 0]
    right_channel = stereo_audio[:, 1]

    left_rms = np.sqrt(np.mean(left_channel ** 2))
    right_rms = np.sqrt(np.mean(right_channel ** 2))

    total_rms = left_rms + right_rms
    if total_rms < 1e-10:
        return DirectionResult(
            direction="center",
            confidence=0.0,
            left_rms=left_rms,
            right_rms=right_rms,
        )

    # Calculate ratio: 0 = all left, 1 = all right, 0.5 = center
    ratio = right_rms / total_rms

    # Calculate confidence based on how far from center
    # 0.5 ratio = 0 confidence, 0 or 1 ratio = 1 confidence
    confidence = abs(ratio - 0.5) * 2

    # Determine direction
    if confidence < 0.1:
        direction = "center"
    elif ratio < 0.5:
        direction = "left"
    else:
        direction = "right"

    return DirectionResult(
        direction=direction,
        confidence=confidence,
        left_rms=float(left_rms),
        right_rms=float(right_rms),
    )
