"""Main entry point for Doggy Detector MVP."""

import asyncio
import logging
import signal
import wave
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import uvicorn

from src.audio import AudioCapture, AudioConfig, IncidentRecorder
from src.config import Config, load_runtime_config
from src.detector import BarkDetector
from src.deterrence import DeterrenceController
from src.direction import analyze_direction
from src.incidents import Detection, IncidentState, IncidentTracker
from src.storage import Event, Storage
from src.weather import WeatherClient
from src.web.app import create_app

logger = logging.getLogger(__name__)

ROLLING_BUFFER_SECONDS = 30.0
DETECTOR_SAMPLE_RATE = 16000


def resample_audio(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Resample audio with linear interpolation for detector input."""
    if source_rate == target_rate or len(audio) == 0:
        return audio

    target_samples = max(1, int(round(len(audio) * target_rate / source_rate)))
    source_positions = np.arange(len(audio), dtype=np.float64)
    target_positions = np.linspace(0, len(audio) - 1, target_samples, dtype=np.float64)

    if audio.ndim == 1:
        return np.interp(target_positions, source_positions, audio).astype(np.float32)

    channels = [
        np.interp(target_positions, source_positions, audio[:, channel])
        for channel in range(audio.shape[1])
    ]
    return np.column_stack(channels).astype(np.float32)


class DoggyDetector:
    """Main orchestrator for dog detection system."""

    def __init__(self, config: Config):
        """Initialize all components.

        Args:
            config: Configuration object with all settings
        """
        self.config = config
        self.storage = Storage(config.storage.data_dir)
        if config.storage.retention_days > 0:
            result = self.storage.prune_retention(config.storage.retention_days)
            logger.info(
                "Retention prune complete: %s events, %s clips deleted",
                result["events_deleted"],
                result["clips_deleted"],
            )

        self.detector = BarkDetector(threshold=config.detection.threshold)
        self.deterrence_controller = DeterrenceController(config.deterrence, self.storage)
        self.incident_tracker = IncidentTracker(config.incidents)
        self.weather_client = WeatherClient()

        # Audio capture with 30 sec rolling buffer for pre-incident context
        self.audio_capture = AudioCapture(
            config=config.audio,
            chunk_callback=self._on_audio_chunk,
            buffer_seconds=ROLLING_BUFFER_SECONDS,
            block_seconds=config.detection.window_sec,
        )

        # Incident recorder for writing long incidents to disk
        self.incident_recorder = IncidentRecorder(
            sample_rate=config.audio.sample_rate,
            channels=config.audio.channels,
        )

        # Async queue for thread-safe audio chunk passing
        self.audio_queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._retention_task: Optional[asyncio.Task] = None
        self._running = False

        # Live status for dashboard
        self.status = {
            "startup_at": None,
            "last_score": 0.0,
            "audio_level": 0.0,  # RMS audio level (0-1)
            "left_level": None,
            "right_level": None,
            "clipping": False,
            "is_barking": False,
            "active_incident": False,
            "chunks_processed": 0,
            "last_detection_time": None,
            "last_audio_chunk_at": None,
            "audio_error": None,
            "mono_mode": False,
            "queue_drops": 0,
        }

    async def start(self):
        """Start audio capture and processing loop."""
        logger.info("Starting Doggy Detector")
        self._running = True
        self._loop = asyncio.get_running_loop()
        self.status["startup_at"] = datetime.now(timezone.utc).isoformat()

        # Start audio capture in background thread
        try:
            self.audio_capture.start()
        except Exception as e:
            self.status["audio_error"] = str(e)
            logger.error("Audio capture failed: %s", e)

        # Check for audio errors
        if self.audio_capture._error:
            self.status["audio_error"] = self.audio_capture._error
            logger.error(f"Audio capture failed: {self.audio_capture._error}")
        else:
            self.status["mono_mode"] = self.audio_capture._mono_mode
            if self.audio_capture._mono_mode:
                logger.warning("Running in MONO mode - direction detection will not work")

        self._retention_task = asyncio.create_task(self._retention_loop())

        # Start processing loop
        await self._process_loop()

    async def stop(self):
        """Stop capture and finalize any active incident."""
        logger.info("Stopping Doggy Detector")
        self._running = False

        # Stop audio capture
        self.audio_capture.stop()

        if self._retention_task:
            self._retention_task.cancel()
            try:
                await self._retention_task
            except asyncio.CancelledError:
                pass
            self._retention_task = None

        # Finalize any active incident
        incident = self.incident_tracker.force_end()
        if incident:
            await self._save_incident(incident)
        else:
            # Cancel any partial recording that didn't become an incident
            self.incident_recorder.cancel()

        logger.info("Doggy Detector stopped")

    def _on_audio_chunk(self, chunk: np.ndarray):
        """Callback for audio thread - puts chunk in async queue.

        Args:
            chunk: Audio chunk from capture thread
        """
        if self._loop is None or self._loop.is_closed():
            self.status["queue_drops"] += 1
            return

        try:
            self._loop.call_soon_threadsafe(self._enqueue_audio_chunk, chunk.copy())
        except RuntimeError:
            self.status["queue_drops"] += 1

    def _enqueue_audio_chunk(self, chunk: np.ndarray):
        try:
            self.audio_queue.put_nowait(chunk)
        except asyncio.QueueFull:
            self.status["queue_drops"] += 1
            logger.warning("Audio queue full, dropping chunk")

    async def _process_loop(self):
        """Main processing loop.

        Gets chunks from queue, runs bark detection, processes incidents.
        """
        logger.info("Starting process loop")
        logger.info("Listening for barks... (barks will be logged here)")

        while self._running:
            try:
                # Get chunk from queue with 1 second timeout
                chunk = await asyncio.wait_for(
                    self.audio_queue.get(), timeout=1.0
                )

                self.status["chunks_processed"] += 1
                self.status["last_audio_chunk_at"] = datetime.now(timezone.utc).isoformat()

                # If incident recording is active, add chunk to recorder
                if self.incident_recorder.is_recording:
                    self.incident_recorder.add_audio(chunk)

                # Calculate RMS audio level (0-1 scale)
                rms = np.sqrt(np.mean(chunk ** 2))
                self.status["audio_level"] = min(1.0, rms * 3)  # Scale up for visibility
                self._update_channel_status(chunk)

                # Run bark detection on chunk
                try:
                    detector_chunk = resample_audio(
                        chunk,
                        self.config.audio.sample_rate,
                        DETECTOR_SAMPLE_RATE,
                    )
                    detection_result = self.detector.detect(detector_chunk)
                    self.status["last_score"] = detection_result.score
                    self.status["is_barking"] = bool(detection_result.is_bark)

                    # Debug: log what the model hears every ~5 seconds (10 chunks)
                    if self.status["chunks_processed"] % 10 == 0:
                        audio_lvl = self.status["audio_level"]
                        logger.info(
                            f"[DEBUG] Input={audio_lvl:.2f} Score={detection_result.score:.3f} "
                            f"Hearing: {detection_result.top_classes}"
                        )

                    if detection_result.is_bark:
                        self.status["last_detection_time"] = datetime.now().isoformat()
                        logger.info(
                            f"BARK DETECTED! score={detection_result.score:.2f} "
                            f"(threshold={self.config.detection.threshold})"
                        )
                        deterrence_events = self.deterrence_controller.handle_bark_detection(
                            score=detection_result.score,
                            audio_level=self.status["audio_level"],
                        )
                        for deterrence_event in deterrence_events:
                            logger.info(
                                "Deterrence %s %s via %s",
                                deterrence_event.status,
                                deterrence_event.mode,
                                deterrence_event.source,
                            )

                        # Analyze direction from stereo audio
                        direction_result = analyze_direction(chunk)
                        logger.info(
                            f"  Direction: {direction_result.direction} "
                            f"(confidence={direction_result.confidence:.2f})"
                        )

                        # Create Detection object
                        detection = Detection(
                            timestamp=datetime.now(),
                            score=detection_result.score,
                            direction=direction_result.direction,
                            direction_score=direction_result.confidence,
                            threshold=self.detector.threshold,
                            audio_level=self.status["audio_level"],
                        )

                        # Process detection with incident tracker
                        incident = self.incident_tracker.process_detection(
                            detection
                        )
                        self.status["active_incident"] = self.incident_tracker.state in {
                            IncidentState.ACTIVE,
                            IncidentState.COOLDOWN,
                        }

                        # If incident completed, save it
                        if incident:
                            await self._save_incident(incident)
                            self.deterrence_controller.reset_incident()
                            self.status["active_incident"] = self.incident_tracker.state in {
                                IncidentState.ACTIVE,
                                IncidentState.COOLDOWN,
                            }

                        self._cancel_discarded_incident_recording()

                        if self.incident_tracker.state == IncidentState.ACTIVE and not self.incident_recorder.is_recording:
                            # Get pre-incident audio for context. The callback already
                            # added the current chunk to the rolling buffer.
                            pre_buffer = self.audio_capture.buffer.get_last(self.config.incidents.pre_roll_sec)
                            self.incident_recorder.start(pre_buffer)
                            logger.info("Started incident recording")

                except Exception as e:
                    logger.error(f"Error during detection: {e}")

                # Check for incident timeout
                incident = self.incident_tracker.check_timeout(datetime.now())
                self.status["active_incident"] = self.incident_tracker.state in {
                    IncidentState.ACTIVE,
                    IncidentState.COOLDOWN,
                }
                self._cancel_discarded_incident_recording()
                if incident:
                    logger.info("Incident ended (silence timeout)")
                    await self._save_incident(incident)
                    self.deterrence_controller.reset_incident()
                    self.status["active_incident"] = False
                elif self.incident_tracker.state == IncidentState.MONITORING and not self.incident_tracker.detections:
                    self.deterrence_controller.reset_incident()

            except asyncio.TimeoutError:
                # Normal timeout, check for incident timeout
                incident = self.incident_tracker.check_timeout(datetime.now())
                self.status["active_incident"] = self.incident_tracker.state in {
                    IncidentState.ACTIVE,
                    IncidentState.COOLDOWN,
                }
                self._cancel_discarded_incident_recording()
                if incident:
                    logger.info("Incident ended (silence timeout)")
                    await self._save_incident(incident)
                    self.deterrence_controller.reset_incident()
                    self.status["active_incident"] = False
                elif self.incident_tracker.state == IncidentState.MONITORING and not self.incident_tracker.detections:
                    self.deterrence_controller.reset_incident()

            except Exception as e:
                logger.error(f"Error in process loop: {e}")

    def _cancel_discarded_incident_recording(self):
        reason = getattr(self.incident_tracker, "last_discard_reason", None)
        if reason and self.incident_recorder.is_recording:
            logger.info("Canceled incident recording after discarded incident: %s", reason)
            self.incident_recorder.cancel()

    async def _save_incident(self, incident):
        """Save completed incident to storage.

        Args:
            incident: Completed Incident object
        """
        recording_duration = self.incident_recorder.duration_seconds
        logger.info(
            f"Saving incident: {incident.bark_count} barks, "
            f"duration={incident.duration_sec:.1f}s, "
            f"recording={recording_duration:.1f}s"
        )

        try:
            clip_path = None
            clip_hash = None

            # Stop the incident recorder and get the WAV file
            if recording_duration > self._max_expected_recording_duration(incident):
                logger.warning(
                    "Discarding stale incident recording: incident=%.1fs recording=%.1fs",
                    incident.duration_sec,
                    recording_duration,
                )
                self.incident_recorder.cancel()
                temp_wav_path = None
            else:
                temp_wav_path = self.incident_recorder.stop()

            if temp_wav_path and temp_wav_path.exists():
                try:
                    # Read the WAV file
                    with open(temp_wav_path, "rb") as f:
                        wav_buffer = f.read()

                    # Save clip via storage
                    clip_path, clip_hash = self.storage.save_clip(
                        wav_buffer, incident.started_at
                    )
                    logger.info(f"Saved clip: {clip_path} ({len(wav_buffer) / 1024:.1f} KB)")

                    # Clean up temp file
                    temp_wav_path.unlink()

                except Exception as e:
                    logger.error(f"Error saving clip: {e}")
                    # Try to clean up temp file
                    try:
                        temp_wav_path.unlink()
                    except:
                        pass
            else:
                logger.warning("No recording available for incident")

            # Fetch weather data
            weather = await self.weather_client.fetch(
                self.config.location.lat, self.config.location.lon
            )

            # Create Event object
            event = Event(
                started_at=incident.started_at,
                ended_at=incident.ended_at,
                duration_sec=incident.duration_sec,
                bark_count=incident.bark_count,
                peak_score=incident.peak_score,
                avg_score=incident.avg_score,
                direction=incident.direction,
                direction_score=incident.direction_score,
                detection_threshold=incident.detection_threshold,
                peak_audio_level=incident.peak_audio_level,
                avg_audio_level=incident.avg_audio_level,
                clip_path=clip_path,
                clip_hash=clip_hash,
                weather_temp_f=weather.temp_f if weather else None,
                weather_wind_mph=weather.wind_mph if weather else None,
                weather_conditions=weather.conditions if weather else None,
            )

            # Save Event to database
            try:
                event_id = self.storage.save_event_with_retry(event)
                logger.info(f"Saved event {event_id}")
            except Exception as e:
                logger.error(f"Error saving event to DB after retry: {e}")
                try:
                    pending_path = self.storage.save_pending_event(event, e)
                    logger.error(f"Pending event metadata written to {pending_path}")
                except Exception as pending_error:
                    logger.error(f"Could not write pending event metadata: {pending_error}")

        except Exception as e:
            logger.error(f"Error saving incident: {e}")

    def _max_expected_recording_duration(self, incident) -> float:
        return (
            self.config.incidents.pre_roll_sec
            + incident.duration_sec
            + self.config.incidents.gap_sec
            + self.config.incidents.merge_within_sec
            + max(1.0, self.config.detection.window_sec * 2)
        )

    def _update_channel_status(self, chunk: np.ndarray):
        """Update lightweight audio channel health metrics."""
        max_abs = float(np.max(np.abs(chunk))) if len(chunk) else 0.0
        self.status["clipping"] = max_abs >= 0.98

        if chunk.ndim == 2 and chunk.shape[1] >= 2:
            left = float(np.sqrt(np.mean(chunk[:, 0] ** 2)))
            right = float(np.sqrt(np.mean(chunk[:, 1] ** 2)))
            self.status["left_level"] = left
            self.status["right_level"] = right
        else:
            self.status["left_level"] = None
            self.status["right_level"] = None

    async def _retention_loop(self):
        """Run retention pruning once per day."""
        while self._running:
            await asyncio.sleep(24 * 60 * 60)
            if self.config.storage.retention_days > 0:
                result = self.storage.prune_retention(self.config.storage.retention_days)
                logger.info(
                    "Retention prune complete: %s events, %s clips deleted",
                    result["events_deleted"],
                    result["clips_deleted"],
                )

    def _create_wav_buffer(self, audio_data: np.ndarray, sample_rate: int) -> bytes:
        """Convert audio data to WAV format bytes.

        Args:
            audio_data: int16 audio array of shape (samples, 2)
            sample_rate: Sample rate in Hz

        Returns:
            WAV file as bytes
        """
        import io

        buffer = io.BytesIO()

        # WAV parameters for stereo int16
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(2)  # stereo
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)

            # Write audio data
            wav_file.writeframes(audio_data.tobytes())

        buffer.seek(0)
        return buffer.read()


async def main():
    """Main entry point."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("Doggy Detector starting")

    # Load SQLite-backed runtime config, migrating config.yaml once if present
    config, settings_store, generated_credentials = load_runtime_config()

    # Create detector
    detector = DoggyDetector(config)

    # Create FastAPI app
    app = create_app(
        config,
        detector.storage,
        settings_store,
        generated_credentials,
        detector.deterrence_controller,
    )
    app.state.detector = detector  # For live status access

    # Setup signal handlers for graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down")
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start detector task
    detector_task = asyncio.create_task(detector.start())

    # Start uvicorn server as async task
    config_obj = uvicorn.Config(
        app,
        host=config.web.host,
        port=config.web.port,
        log_level="info",
    )
    server = uvicorn.Server(config_obj)
    server_task = asyncio.create_task(server.serve())

    logger.info(f"Web server starting on {config.web.host}:{config.web.port}")

    # Wait for shutdown signal
    try:
        await shutdown_event.wait()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")

    # Stop detector and server gracefully
    logger.info("Shutting down...")
    await detector.stop()

    # Shutdown server
    server.should_exit = True
    await server_task

    logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
