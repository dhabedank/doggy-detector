"""Audio capture and rolling buffer."""

import asyncio
import io
import tempfile
import threading
import wave
from collections import deque
from dataclasses import dataclass
from pathlib import Path
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
    device: Optional[int | str]
    sample_rate: int
    channels: int


class AudioCapture:
    """Capture audio from microphone in a background thread."""

    def __init__(
        self,
        config: AudioConfig,
        chunk_callback: Callable[[np.ndarray], None],
        buffer_seconds: float = 5.0,
        block_seconds: float = 0.5,
    ):
        self.config = config
        self.chunk_callback = chunk_callback
        self.block_seconds = block_seconds
        self.buffer = RollingBuffer(
            max_seconds=buffer_seconds,
            sample_rate=config.sample_rate,
            channels=config.channels,
        )
        self._stream: Optional["sd.InputStream"] = None
        self._running = False
        self._mono_mode = False
        self._error: Optional[str] = None

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
        self._error = None
        self._mono_mode = False

        try:
            device, device_info = self._resolve_input_device(self.config.device)
        except Exception as e:
            self._error = str(e)
            print(f"Audio capture failed: {self._error}")
            self._running = False
            return

        max_channels = int(device_info.get("max_input_channels", 0))
        channels = min(self.config.channels, max_channels)
        if channels < 1:
            self._error = f"Selected input device has no input channels: {device_info.get('name', device)}"
            print(f"Audio capture failed: {self._error}")
            self._running = False
            return

        blocksize = max(1, int(self.config.sample_rate * self.block_seconds))
        callback = self._audio_callback_mono if channels == 1 else self._audio_callback
        try:
            self._stream = sd.InputStream(
                device=device,
                channels=channels,
                samplerate=self.config.sample_rate,
                callback=callback,
                blocksize=blocksize,
            )
            self._stream.start()
            self._mono_mode = channels == 1
            mode = "MONO" if self._mono_mode else "stereo"
            print(f"Audio capture started: device={device_info.get('name', device)}, channels={channels} ({mode})")
        except Exception as e:
            # Try mono on the same selected/default device if stereo open fails.
            if channels == 2:
                print(f"Stereo failed ({e}), trying mono...")
                try:
                    self._stream = sd.InputStream(
                        device=device,
                        channels=1,
                        samplerate=self.config.sample_rate,
                        callback=self._audio_callback_mono,
                        blocksize=blocksize,
                    )
                    self._stream.start()
                    self._mono_mode = True
                    print(f"Audio capture started in MONO mode: device={device_info.get('name', device)}")
                except Exception as e2:
                    self._error = f"Failed to open selected audio device {device_info.get('name', device)}: {e2}"
                    print(f"Audio capture failed: {self._error}")
                    self._running = False
            else:
                self._error = f"Failed to open audio: {e}"
                print(f"Audio capture failed: {self._error}")
                self._running = False

    def _audio_callback_mono(self, indata: np.ndarray, frames: int, time_info, status):
        """Callback for mono audio - duplicates to stereo."""
        if status:
            print(f"Audio status: {status}")

        # Duplicate mono to stereo for compatibility
        stereo_data = np.column_stack([indata[:, 0], indata[:, 0]])
        self.buffer.add(stereo_data)
        self.chunk_callback(stereo_data.copy())

    def stop(self):
        """Stop audio capture."""
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def _resolve_input_device(self, configured_device: Optional[int | str]):
        """Resolve the configured input device without silently switching devices."""
        if configured_device is None:
            return None, sd.query_devices(kind="input")

        if isinstance(configured_device, int):
            devices = sd.query_devices()
            if configured_device < 0 or configured_device >= len(devices):
                raise RuntimeError(f"Configured microphone id {configured_device} is not available")
            device_info = devices[configured_device]
            if device_info["max_input_channels"] <= 0:
                raise RuntimeError(f"Configured microphone id {configured_device} is not an input device")
            return configured_device, device_info

        configured_name = configured_device.strip()
        if not configured_name:
            return None, sd.query_devices(kind="input")

        try:
            return configured_name, sd.query_devices(configured_name, kind="input")
        except Exception as exc:
            raise RuntimeError(f"Configured microphone is not available: {configured_name}") from exc

    @property
    def is_running(self) -> bool:
        return self._running and self._stream is not None


class IncidentRecorder:
    """Records audio to disk during an active incident.

    Handles arbitrarily long incidents by writing directly to a temp file
    instead of keeping everything in memory.
    """

    def __init__(self, sample_rate: int = 16000, channels: int = 2):
        self.sample_rate = sample_rate
        self.channels = channels
        self._temp_file: Optional[tempfile.NamedTemporaryFile] = None
        self._wav_file: Optional[wave.Wave_write] = None
        self._recording = False
        self._lock = threading.Lock()
        self._sample_count = 0

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def duration_seconds(self) -> float:
        return self._sample_count / self.sample_rate

    def start(self, pre_buffer: np.ndarray = None):
        """Start recording a new incident.

        Args:
            pre_buffer: Optional audio data to prepend (for context before first bark)
        """
        with self._lock:
            if self._recording:
                return

            # Create temp file
            self._temp_file = tempfile.NamedTemporaryFile(
                suffix=".wav", delete=False, mode="wb"
            )

            # Open as WAV
            self._wav_file = wave.open(self._temp_file, "wb")
            self._wav_file.setnchannels(self.channels)
            self._wav_file.setsampwidth(2)  # 16-bit
            self._wav_file.setframerate(self.sample_rate)

            self._sample_count = 0
            self._recording = True

            # Write pre-buffer if provided
            if pre_buffer is not None and len(pre_buffer) > 0:
                self._write_samples(pre_buffer)

    def add_audio(self, chunk: np.ndarray):
        """Add audio chunk to the recording.

        Args:
            chunk: Audio data as float32 array
        """
        with self._lock:
            if not self._recording:
                return
            self._write_samples(chunk)

    def _write_samples(self, chunk: np.ndarray):
        """Write samples to WAV file (must hold lock)."""
        # Convert float32 to int16
        audio_int16 = (chunk * 32767).astype(np.int16)
        self._wav_file.writeframes(audio_int16.tobytes())
        self._sample_count += len(chunk)

    def stop(self) -> Optional[Path]:
        """Stop recording and return path to the WAV file.

        Returns:
            Path to the recorded WAV file, or None if not recording
        """
        with self._lock:
            if not self._recording:
                return None

            self._recording = False

            # Close WAV file
            if self._wav_file:
                self._wav_file.close()
                self._wav_file = None

            # Get the path before closing temp file handle
            path = Path(self._temp_file.name) if self._temp_file else None

            if self._temp_file:
                self._temp_file.close()
                self._temp_file = None

            self._sample_count = 0
            return path

    def cancel(self):
        """Cancel recording and delete temp file."""
        with self._lock:
            self._recording = False

            if self._wav_file:
                self._wav_file.close()
                self._wav_file = None

            if self._temp_file:
                path = Path(self._temp_file.name)
                self._temp_file.close()
                self._temp_file = None
                # Delete the temp file
                try:
                    path.unlink()
                except:
                    pass

            self._sample_count = 0
