"""Audio capture and rolling buffer."""

import asyncio
import io
import logging
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

logger = logging.getLogger(__name__)

SAMPLE_WIDTH_BYTES = 2
WAV_UINT32_MAX = 0xFFFFFFFF
WAV_HEADER_OVERHEAD_BYTES = 36
WAV_MAX_DATA_BYTES = WAV_UINT32_MAX - WAV_HEADER_OVERHEAD_BYTES


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


def prepare_audio_for_wav(
    chunk: np.ndarray,
    *,
    input_sample_rate: int,
    sample_rate: int,
    channels: int,
) -> np.ndarray:
    """Convert input chunks to a WAV storage/playback format."""
    if chunk.ndim == 1:
        prepared = chunk.astype(np.float32, copy=False)
        if channels > 1:
            prepared = np.repeat(prepared[:, None], channels, axis=1)
    elif channels == 1:
        prepared = np.mean(chunk, axis=1).astype(np.float32, copy=False)
    elif chunk.shape[1] == channels:
        prepared = chunk.astype(np.float32, copy=False)
    elif chunk.shape[1] > channels:
        prepared = chunk[:, :channels].astype(np.float32, copy=False)
    else:
        repeats = [chunk[:, -1:]] * (channels - chunk.shape[1])
        prepared = np.hstack([chunk, *repeats]).astype(np.float32, copy=False)

    if input_sample_rate != sample_rate:
        prepared = _resample_audio(prepared, input_sample_rate, sample_rate)
    return prepared


def encode_wav_bytes(
    chunk: np.ndarray,
    *,
    input_sample_rate: int,
    sample_rate: int = 16000,
    channels: int = 1,
) -> bytes:
    """Encode an audio chunk as 16-bit PCM WAV bytes."""
    prepared = prepare_audio_for_wav(
        chunk,
        input_sample_rate=input_sample_rate,
        sample_rate=sample_rate,
        channels=channels,
    )
    audio_int16 = (np.clip(prepared, -1.0, 1.0) * 32767).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_int16.tobytes())
    return buffer.getvalue()


def _resample_audio(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or len(audio) == 0:
        return audio

    target_samples = max(1, int(round(len(audio) * target_rate / source_rate)))
    source_positions = np.arange(len(audio), dtype=np.float64)
    target_positions = np.linspace(0, len(audio) - 1, target_samples, dtype=np.float64)

    if audio.ndim == 1:
        return np.interp(target_positions, source_positions, audio).astype(np.float32)

    resampled_channels = [
        np.interp(target_positions, source_positions, audio[:, channel])
        for channel in range(audio.shape[1])
    ]
    return np.column_stack(resampled_channels).astype(np.float32)


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

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 2,
        input_sample_rate: Optional[int] = None,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.input_sample_rate = input_sample_rate or sample_rate
        self._bytes_per_frame = self.channels * SAMPLE_WIDTH_BYTES
        self._max_data_bytes = WAV_MAX_DATA_BYTES - (
            WAV_MAX_DATA_BYTES % self._bytes_per_frame
        )
        self._temp_file: Optional[tempfile.NamedTemporaryFile] = None
        self._wav_file: Optional[wave.Wave_write] = None
        self._recording = False
        self._lock = threading.Lock()
        self._sample_count = 0
        self._bytes_written = 0
        self._truncated = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def was_truncated(self) -> bool:
        return self._truncated

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
            self._bytes_written = 0
            self._truncated = False
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
        if self._wav_file is None or len(chunk) == 0:
            return

        prepared = self._prepare_chunk(chunk)
        if len(prepared) == 0:
            return

        audio_int16 = (np.clip(prepared, -1.0, 1.0) * 32767).astype(np.int16)
        data = audio_int16.tobytes()

        remaining_bytes = self._max_data_bytes - self._bytes_written
        if remaining_bytes <= 0:
            self._mark_truncated()
            return

        if len(data) > remaining_bytes:
            allowed_bytes = remaining_bytes - (remaining_bytes % self._bytes_per_frame)
            if allowed_bytes <= 0:
                self._mark_truncated()
                return
            data = data[:allowed_bytes]
            self._mark_truncated()

        frames_written = len(data) // self._bytes_per_frame
        if frames_written == 0:
            return

        self._wav_file.writeframes(data)
        self._bytes_written += len(data)
        self._sample_count += frames_written

    def _prepare_chunk(self, chunk: np.ndarray) -> np.ndarray:
        return prepare_audio_for_wav(
            chunk,
            input_sample_rate=self.input_sample_rate,
            sample_rate=self.sample_rate,
            channels=self.channels,
        )

    def _mark_truncated(self):
        if self._truncated:
            return

        self._truncated = True
        max_duration = self._max_data_bytes / self._bytes_per_frame / self.sample_rate
        logger.warning(
            "Incident recording reached the WAV size limit after %.1f seconds; "
            "additional audio will be omitted from this clip",
            max_duration,
        )

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
            self._bytes_written = 0
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
            self._bytes_written = 0
            self._truncated = False
