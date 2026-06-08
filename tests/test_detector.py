import pytest
import numpy as np

from src.detector import BarkDetector, DetectionResult

# Check if TensorFlow is available
try:
    import tensorflow
    HAS_TF = True
except ImportError:
    HAS_TF = False


@pytest.fixture
def detector():
    return BarkDetector(threshold=0.5)


@pytest.mark.skipif(not HAS_TF, reason="TensorFlow not installed")
def test_detector_returns_result(detector):
    # Create 0.5 seconds of audio at 16kHz
    audio = np.random.randn(8000, 2).astype(np.float32) * 0.1

    result = detector.detect(audio)

    assert isinstance(result, DetectionResult)
    assert 0.0 <= result.score <= 1.0
    assert isinstance(result.is_bark, bool)


@pytest.mark.skipif(not HAS_TF, reason="TensorFlow not installed")
def test_detector_silence_low_score(detector):
    # Silent audio
    audio = np.zeros((8000, 2), dtype=np.float32)

    result = detector.detect(audio)

    assert result.score < 0.5
    assert result.is_bark is False


def test_detector_converts_stereo_to_mono():
    detector = BarkDetector(threshold=0.5)
    stereo = np.random.randn(8000, 2).astype(np.float32)

    mono = detector._to_mono(stereo)

    assert mono.ndim == 1
    assert len(mono) == 8000
