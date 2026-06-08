"""Bark detection using YAMNet."""

from dataclasses import dataclass
from typing import List, Optional
import numpy as np

try:
    import tensorflow as tf
    import tensorflow_hub as hub
except ImportError:
    tf = None
    hub = None


@dataclass
class DetectionResult:
    score: float
    is_bark: bool
    top_classes: List[str]


# YAMNet class indices for dog-related sounds
DOG_CLASSES = {
    "Dog": 74,
    "Bark": 75,
    "Howl": 76,
    "Bow-wow": 77,
    "Growling": 78,
    "Whimper (dog)": 79,
}


class BarkDetector:
    """Detect dog barks using YAMNet model."""

    MODEL_URL = "https://tfhub.dev/google/yamnet/1"

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold
        self._model = None
        self._class_names: Optional[List[str]] = None

    def _load_model(self):
        """Lazy-load YAMNet model."""
        if self._model is not None:
            return

        if tf is None or hub is None:
            raise RuntimeError("TensorFlow and tensorflow_hub required")

        self._model = hub.load(self.MODEL_URL)

        # Load class names
        class_map_path = self._model.class_map_path().numpy().decode("utf-8")
        with open(class_map_path) as f:
            # Skip header
            lines = f.readlines()[1:]
            self._class_names = [line.strip().split(",")[2] for line in lines]

    def detect(self, audio: np.ndarray) -> DetectionResult:
        """
        Detect if audio contains dog bark.

        Args:
            audio: numpy array of shape (samples,) or (samples, 2) at 16kHz

        Returns:
            DetectionResult with score, is_bark, and top classes
        """
        self._load_model()

        # Convert stereo to mono if needed
        if audio.ndim == 2:
            audio = self._to_mono(audio)

        # Ensure float32
        audio = audio.astype(np.float32)

        # Normalize
        if np.abs(audio).max() > 1.0:
            audio = audio / 32768.0

        # Run inference
        scores, embeddings, spectrogram = self._model(audio)
        scores = scores.numpy()

        # Get mean scores across time frames
        mean_scores = scores.mean(axis=0)

        # Get dog-related scores
        dog_scores = [mean_scores[idx] for idx in DOG_CLASSES.values()]
        max_dog_score = max(dog_scores) if dog_scores else 0.0

        # Get top 3 classes
        top_indices = np.argsort(mean_scores)[-3:][::-1]
        top_classes = [self._class_names[i] for i in top_indices]

        return DetectionResult(
            score=float(max_dog_score),
            is_bark=max_dog_score >= self.threshold,
            top_classes=top_classes,
        )

    def _to_mono(self, stereo: np.ndarray) -> np.ndarray:
        """Convert stereo to mono by averaging channels."""
        return stereo.mean(axis=1)
