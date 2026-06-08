"""Audio capture and rolling buffer."""

import asyncio
import threading
from collections import deque
from dataclasses import dataclass
from typing import Optional, Callable, Deque
import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None


class RollingBuffer:
    """Thread-safe rolling audio buffer."""

    def __init__(self, max_seconds: float, sample_rate: int, channels: int):
        self.max_samples = int(max_seconds * sample_rate)
        self.sample_rate = sample_rate
        self.channels = channels
        self._buffer: Deque[np.ndarray] = deque()
        self._total_samples = 0
        self._lock = threading.Lock()

    def add(self, chunk: np.ndarray):
        """Add audio chunk to buffer."""
        with self._lock:
            self._buffer.append(chunk.copy())
            self._total_samples += len(chunk)

            # Remove old chunks if over limit
            while self._total_samples > self.max_samples and self._buffer:
                removed = self._buffer.popleft()
                self._total_samples -= len(removed)

    @property
    def duration_seconds(self) -> float:
        with self._lock:
            return self._total_samples / self.sample_rate

    def get_all(self) -> np.ndarray:
        """Get all buffered audio."""
        with self._lock:
            if not self._buffer:
                return np.zeros((0, self.channels), dtype=np.float32)
            return np.vstack(list(self._buffer))

    def get_last(self, seconds: float) -> np.ndarray:
        """Get last N seconds of audio."""
        samples_needed = int(seconds * self.sample_rate)

        with self._lock:
            if not self._buffer:
                return np.zeros((0, self.channels), dtype=np.float32)

            all_data = np.vstack(list(self._buffer))
            if len(all_data) <= samples_needed:
                return all_data
            return all_data[-samples_needed:]

    def clear(self):
        """Clear buffer."""
        with self._lock:
            self._buffer.clear()
            self._total_samples = 0


@dataclass
class AudioConfig:
    device: Optional[str]
    sample_rate: int
    channels: int


class AudioCapture:
    """Capture audio from microphone in a background thread."""

    def __init__(
        self,
        config: AudioConfig,
        chunk_callback: Callable[[np.ndarray], None],
        buffer_seconds: float = 5.0,
    ):
        self.config = config
        self.chunk_callback = chunk_callback
        self.buffer = RollingBuffer(
            max_seconds=buffer_seconds,
            sample_rate=config.sample_rate,
            channels=config.channels,
        )
        self._stream: Optional["sd.InputStream"] = None
        self._running = False

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status):
        """Called by sounddevice for each audio chunk."""
        if status:
            print(f"Audio status: {status}")

        # Store in buffer
        self.buffer.add(indata)

        # Notify listener
        self.chunk_callback(indata.copy())

    def start(self):
        """Start audio capture."""
        if sd is None:
            raise RuntimeError("sounddevice not installed")

        self._running = True

        device = self.config.device
        if device is None:
            device = self._find_stereo_device()

        self._stream = sd.InputStream(
            device=device,
            channels=self.config.channels,
            samplerate=self.config.sample_rate,
            callback=self._audio_callback,
            blocksize=int(self.config.sample_rate * 0.1),  # 100ms chunks
        )
        self._stream.start()

    def stop(self):
        """Stop audio capture."""
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def _find_stereo_device(self) -> Optional[int]:
        """Find a stereo input device."""
        devices = sd.query_devices()
        for i, device in enumerate(devices):
            if device["max_input_channels"] >= 2:
                return i
        return None

    @property
    def is_running(self) -> bool:
        return self._running and self._stream is not None
