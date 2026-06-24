import pytest
import asyncio
import io
import numpy as np
import wave
from collections import deque

from src.audio import AudioCapture, AudioConfig, IncidentRecorder, RollingBuffer, encode_wav_bytes
from src.config import AudioConfig as AppAudioConfig, Config, StorageConfig
from src.main import DoggyDetector


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


@pytest.mark.asyncio
async def test_audio_callback_enqueues_threadsafe(tmp_path):
    detector = DoggyDetector(Config(storage=StorageConfig(data_dir=tmp_path)))
    detector._loop = asyncio.get_running_loop()
    chunk = np.zeros((8000, 2), dtype=np.float32)

    detector._on_audio_chunk(chunk)
    queued = await asyncio.wait_for(detector.audio_queue.get(), timeout=1.0)

    assert np.array_equal(queued, chunk)


def test_audio_queue_drop_count(tmp_path):
    detector = DoggyDetector(Config(storage=StorageConfig(data_dir=tmp_path)))
    detector.audio_queue = asyncio.Queue(maxsize=1)
    detector.audio_queue.put_nowait(np.zeros((8000, 2), dtype=np.float32))

    detector._enqueue_audio_chunk(np.ones((8000, 2), dtype=np.float32))

    assert detector.status["queue_drops"] == 1


def test_detector_records_incidents_in_compact_review_format(tmp_path):
    detector = DoggyDetector(Config(
        audio=AppAudioConfig(sample_rate=48000, channels=2),
        storage=StorageConfig(data_dir=tmp_path),
    ))

    assert detector.incident_recorder.sample_rate == 16000
    assert detector.incident_recorder.channels == 1
    assert detector.incident_recorder.input_sample_rate == 48000


class FakeStream:
    def __init__(self, fake_sd, **kwargs):
        self.fake_sd = fake_sd
        self.kwargs = kwargs
        self.fake_sd.streams.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        pass


class FakeSoundDevice:
    def __init__(self):
        self.streams = []

    def query_devices(self, device=None, kind=None):
        devices = [
            {"name": "Laptop Mic", "max_input_channels": 1, "hostapi": 0},
            {"name": "Mounted Yard Mic", "max_input_channels": 2, "hostapi": 0},
        ]
        if device is None and kind == "input":
            return devices[0]
        if device is None:
            return devices
        if device == "Mounted Yard Mic, Core Audio":
            return devices[1]
        raise ValueError("No matching device")

    def InputStream(self, **kwargs):
        return FakeStream(self, **kwargs)


def test_audio_capture_pins_configured_device_by_name(monkeypatch):
    fake_sd = FakeSoundDevice()
    monkeypatch.setattr("src.audio.sd", fake_sd)
    capture = AudioCapture(
        AudioConfig(device="Mounted Yard Mic, Core Audio", sample_rate=16000, channels=2),
        lambda chunk: None,
    )

    capture.start()

    assert capture._error is None
    assert fake_sd.streams[0].kwargs["device"] == "Mounted Yard Mic, Core Audio"
    assert fake_sd.streams[0].kwargs["channels"] == 2


def test_audio_capture_missing_pinned_device_does_not_fall_back(monkeypatch):
    fake_sd = FakeSoundDevice()
    monkeypatch.setattr("src.audio.sd", fake_sd)
    capture = AudioCapture(
        AudioConfig(device="Missing Yard Mic, Core Audio", sample_rate=16000, channels=2),
        lambda chunk: None,
    )

    capture.start()

    assert "Configured microphone is not available" in capture._error
    assert fake_sd.streams == []


def test_audio_capture_system_default_uses_default_input(monkeypatch):
    fake_sd = FakeSoundDevice()
    monkeypatch.setattr("src.audio.sd", fake_sd)
    capture = AudioCapture(
        AudioConfig(device=None, sample_rate=16000, channels=2),
        lambda chunk: None,
    )

    capture.start()

    assert capture._error is None
    assert fake_sd.streams[0].kwargs["device"] is None
    assert fake_sd.streams[0].kwargs["channels"] == 1
    assert capture._mono_mode is True


def test_incident_recorder_truncates_before_wav_header_overflow():
    recorder = IncidentRecorder(sample_rate=16000, channels=2)
    recorder.start()

    try:
        bytes_per_frame = recorder._bytes_per_frame
        max_data_bytes = recorder._max_data_bytes
        near_limit = max_data_bytes - bytes_per_frame

        # Initialize the wave header, then simulate a real long-running recording
        # whose RIFF data counter is one frame away from the 32-bit limit.
        recorder._wav_file.writeframes(b"\0" * bytes_per_frame)
        recorder._wav_file._datawritten = near_limit
        recorder._wav_file._datalength = near_limit
        recorder._bytes_written = near_limit
        recorder._sample_count = near_limit // bytes_per_frame

        recorder.add_audio(np.zeros((2, 2), dtype=np.float32))

        assert recorder.was_truncated is True
        assert recorder._bytes_written == max_data_bytes
        assert recorder._sample_count == max_data_bytes // bytes_per_frame
    finally:
        path = recorder.stop()
        if path:
            path.unlink(missing_ok=True)


def test_incident_recorder_can_store_compact_mono_wav():
    recorder = IncidentRecorder(sample_rate=16000, channels=1, input_sample_rate=48000)
    left = np.linspace(-0.5, 0.5, 48000, dtype=np.float32)
    right = np.linspace(0.5, -0.5, 48000, dtype=np.float32)
    chunk = np.column_stack([left, right])
    path = None
    recorder.start()

    try:
        recorder.add_audio(chunk)
        path = recorder.stop()
        assert path is not None
        with wave.open(str(path), "rb") as wav:
            assert wav.getnchannels() == 1
            assert wav.getframerate() == 16000
            assert wav.getnframes() == 16000
        assert path.stat().st_size < 40000
    finally:
        if recorder.is_recording:
            path = recorder.stop()
        if path:
            path.unlink(missing_ok=True)


def test_encode_wav_bytes_compacts_stereo_input_to_mono():
    chunk = np.ones((48000, 2), dtype=np.float32) * 0.25

    wav_data = encode_wav_bytes(
        chunk,
        input_sample_rate=48000,
        sample_rate=16000,
        channels=1,
    )

    with wave.open(io.BytesIO(wav_data), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == 16000
        assert wav.getnframes() == 16000
    assert len(wav_data) < 40000
