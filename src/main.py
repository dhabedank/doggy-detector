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

from src.audio import AudioCapture, AudioConfig
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

        # Audio capture
        self.audio_capture = AudioCapture(
            config=config.audio,
            chunk_callback=self._on_audio_chunk,
            buffer_seconds=5.0,
        )

        # Async queue for thread-safe audio chunk passing
        self.audio_queue: asyncio.Queue = asyncio.Queue()
        self._running = False

    async def start(self):
        """Start audio capture and processing loop."""
        logger.info("Starting Dog Detector")
        self._running = True

        # Start audio capture in background thread
        self.audio_capture.start()

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

        while self._running:
            try:
                # Get chunk from queue with 1 second timeout
                chunk = await asyncio.wait_for(
                    self.audio_queue.get(), timeout=1.0
                )

                # Add chunk to audio capture's rolling buffer
                self.audio_capture.buffer.add(chunk)

                # Run bark detection on chunk
                try:
                    detection_result = self.detector.detect(chunk)

                    if detection_result.is_bark:
                        logger.debug(
                            f"Bark detected: score={detection_result.score:.3f}"
                        )

                        # Analyze direction from stereo audio
                        direction_result = analyze_direction(chunk)

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

                        # If incident completed, save it
                        if incident:
                            await self._save_incident(incident)

                except Exception as e:
                    logger.error(f"Error during detection: {e}")

                # Check for incident timeout
                incident = self.incident_tracker.check_timeout(datetime.now())
                if incident:
                    await self._save_incident(incident)

            except asyncio.TimeoutError:
                # Normal timeout, check for incident timeout
                incident = self.incident_tracker.check_timeout(datetime.now())
                if incident:
                    await self._save_incident(incident)

            except Exception as e:
                logger.error(f"Error in process loop: {e}")

    async def _save_incident(self, incident):
        """Save completed incident to storage.

        Args:
            incident: Completed Incident object
        """
        logger.info(
            f"Saving incident: {incident.bark_count} barks, "
            f"duration={incident.duration_sec:.1f}s"
        )

        try:
            # Get audio from rolling buffer
            # Use duration + 2 second buffer for context
            duration_with_buffer = incident.duration_sec + 2.0
            audio_data = self.audio_capture.buffer.get_last(
                duration_with_buffer
            )

            clip_path = None
            clip_hash = None

            # Convert to WAV if we have audio
            if len(audio_data) > 0:
                try:
                    # Convert float32 to int16
                    audio_int16 = (audio_data * 32767).astype(np.int16)

                    # Create WAV bytes
                    wav_buffer = self._create_wav_buffer(
                        audio_int16, self.config.audio.sample_rate
                    )

                    # Save clip via storage
                    clip_path, clip_hash = self.storage.save_clip(
                        wav_buffer, incident.started_at
                    )
                    logger.debug(f"Saved clip: {clip_path}")

                except Exception as e:
                    logger.error(f"Error saving clip: {e}")

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
