"""Main entry point for Dog Detector MVP."""

import asyncio
import logging
import signal
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import uvicorn
from fastapi import FastAPI

from src.audio import AudioCapture, AudioConfig, IncidentRecorder
from src.config import Config, load_config
from src.detector import BarkDetector
from src.direction import analyze_direction
from src.incidents import Detection, IncidentTracker
from src.storage import Event, Storage
from src.weather import WeatherClient
from src.web.app import create_app

logger = logging.getLogger(__name__)


class DogDetector:
    """Main orchestrator for dog detection system."""

    def __init__(self, config: Config):
        """Initialize all components.

        Args:
            config: Configuration object with all settings
        """
        self.config = config
        self.storage = Storage(config.storage.data_dir)
        self.detector = BarkDetector(threshold=config.detection.threshold)
        self.incident_tracker = IncidentTracker(config.incidents)
        self.weather_client = WeatherClient()

        # Audio capture with 30 sec rolling buffer for pre-incident context
        self.audio_capture = AudioCapture(
            config=config.audio,
            chunk_callback=self._on_audio_chunk,
            buffer_seconds=30.0,  # 30 sec pre-incident context
        )

        # Incident recorder for writing long incidents to disk
        self.incident_recorder = IncidentRecorder(
            sample_rate=config.audio.sample_rate,
            channels=config.audio.channels,
        )

        # Async queue for thread-safe audio chunk passing
        self.audio_queue: asyncio.Queue = asyncio.Queue()
        self._running = False

        # Live status for dashboard
        self.status = {
            "last_score": 0.0,
            "audio_level": 0.0,  # RMS audio level (0-1)
            "is_barking": False,
            "active_incident": False,
            "chunks_processed": 0,
            "last_detection_time": None,
            "audio_error": None,
            "mono_mode": False,
        }

    async def start(self):
        """Start audio capture and processing loop."""
        logger.info("Starting Dog Detector")
        self._running = True

        # Start audio capture in background thread
        self.audio_capture.start()

        # Check for audio errors
        if self.audio_capture._error:
            self.status["audio_error"] = self.audio_capture._error
            logger.error(f"Audio capture failed: {self.audio_capture._error}")
        else:
            self.status["mono_mode"] = self.audio_capture._mono_mode
            if self.audio_capture._mono_mode:
                logger.warning("Running in MONO mode - direction detection will not work")

        # Start processing loop
        await self._process_loop()

    async def stop(self):
        """Stop capture and finalize any active incident."""
        logger.info("Stopping Dog Detector")
        self._running = False

        # Stop audio capture
        self.audio_capture.stop()

        # Finalize any active incident
        incident = self.incident_tracker.force_end()
        if incident:
            await self._save_incident(incident)
        else:
            # Cancel any partial recording that didn't become an incident
            self.incident_recorder.cancel()

        logger.info("Dog Detector stopped")

    def _on_audio_chunk(self, chunk: np.ndarray):
        """Callback for audio thread - puts chunk in async queue.

        Args:
            chunk: Audio chunk from capture thread
        """
        # Queue the chunk for processing
        try:
            self.audio_queue.put_nowait(chunk)
        except asyncio.QueueFull:
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

                # Add chunk to audio capture's rolling buffer
                self.audio_capture.buffer.add(chunk)
                self.status["chunks_processed"] += 1

                # If incident recording is active, add chunk to recorder
                if self.incident_recorder.is_recording:
                    self.incident_recorder.add_audio(chunk)

                # Calculate RMS audio level (0-1 scale)
                rms = np.sqrt(np.mean(chunk ** 2))
                self.status["audio_level"] = min(1.0, rms * 3)  # Scale up for visibility

                # Run bark detection on chunk
                try:
                    detection_result = self.detector.detect(chunk)
                    self.status["last_score"] = detection_result.score
                    self.status["is_barking"] = detection_result.is_bark

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

                        # Start recording if not already
                        if not self.incident_recorder.is_recording:
                            # Get pre-incident audio (last 10 sec) for context
                            pre_buffer = self.audio_capture.buffer.get_last(10.0)
                            self.incident_recorder.start(pre_buffer)
                            logger.info("Started incident recording")

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
                        )

                        # Process detection with incident tracker
                        incident = self.incident_tracker.process_detection(
                            detection
                        )
                        self.status["active_incident"] = self.incident_tracker.state.value == "active"

                        # If incident completed, save it
                        if incident:
                            await self._save_incident(incident)
                            self.status["active_incident"] = False

                except Exception as e:
                    logger.error(f"Error during detection: {e}")

                # Check for incident timeout
                incident = self.incident_tracker.check_timeout(datetime.now())
                if incident:
                    logger.info("Incident ended (silence timeout)")
                    await self._save_incident(incident)
                    self.status["active_incident"] = False

            except asyncio.TimeoutError:
                # Normal timeout, check for incident timeout
                incident = self.incident_tracker.check_timeout(datetime.now())
                if incident:
                    logger.info("Incident ended (silence timeout)")
                    await self._save_incident(incident)
                    self.status["active_incident"] = False

            except Exception as e:
                logger.error(f"Error in process loop: {e}")

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
                clip_path=clip_path,
                clip_hash=clip_hash,
                weather_temp_f=weather.temp_f if weather else None,
                weather_wind_mph=weather.wind_mph if weather else None,
                weather_conditions=weather.conditions if weather else None,
            )

            # Save Event to database
            event_id = self.storage.save_event(event)
            logger.info(f"Saved event {event_id}")

        except Exception as e:
            logger.error(f"Error saving incident: {e}")

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

    logger.info("Dog Detector starting")

    # Load config
    config_path = Path("config.yaml")
    if config_path.exists():
        config = load_config(config_path)
        logger.info(f"Loaded config from {config_path}")
    else:
        config = Config()
        logger.info("Using default config (config.yaml not found)")

    # Create detector
    detector = DogDetector(config)

    # Create FastAPI app
    app = create_app(config, detector.storage)
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
