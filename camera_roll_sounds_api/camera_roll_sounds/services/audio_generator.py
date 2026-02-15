from __future__ import annotations

import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from elevenlabs import ElevenLabs
from pydub import AudioSegment

if TYPE_CHECKING:
    from camera_roll_sounds_api.camera_roll_sounds.services.image_processor import (
        MeditationChunk,
        SoundEffect,
    )

logger = logging.getLogger(__name__)

client = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))

AUDIO_OUTPUT_DIR = Path(tempfile.gettempdir()) / "camera_roll_sounds_audio"
AUDIO_OUTPUT_DIR.mkdir(exist_ok=True)


class GeneratedAudio(NamedTuple):
    file_path: Path
    duration_ms: int


def generate_ambient_sound(
    prompt: str, duration_seconds: float = 10.0
) -> GeneratedAudio:
    """
    Generate ambient sound effects using ElevenLabs.
    """
    logger.info(
        "Generating ambient sound: '%s' (%ss)...", prompt[:50], duration_seconds
    )
    result = client.text_to_sound_effects.convert(
        text=prompt,
        duration_seconds=duration_seconds,
    )

    output_path = AUDIO_OUTPUT_DIR / f"ambient_{uuid.uuid4().hex}.mp3"

    with open(output_path, "wb") as f:
        f.writelines(result)

    audio = AudioSegment.from_mp3(output_path)
    logger.info("Ambient sound generated: %dms", len(audio))

    return GeneratedAudio(file_path=output_path, duration_ms=len(audio))


def generate_multiple_sound_effects(
    sound_effects: list[SoundEffect],
    duration_seconds: float,
) -> GeneratedAudio:
    """
    Generate multiple sound effects and layer them together.
    Sound effects are generated at max 30s and looped to target duration.
    """
    # ElevenLabs sound effects have a 30-second max limit
    generation_duration = min(duration_seconds, 30.0)
    logger.info(
        "Generating %d layered sound effects (%.1fs, will loop to %.1fs)...",
        len(sound_effects),
        generation_duration,
        duration_seconds,
    )

    if not sound_effects:
        # Return silence if no sound effects
        silence = AudioSegment.silent(duration=int(duration_seconds * 1000))
        output_path = AUDIO_OUTPUT_DIR / f"ambient_{uuid.uuid4().hex}.mp3"
        silence.export(output_path, format="mp3")
        return GeneratedAudio(file_path=output_path, duration_ms=len(silence))

    # Generate each sound effect
    generated_audios: list[tuple[AudioSegment, int]] = []
    temp_paths: list[Path] = []

    for i, effect in enumerate(sound_effects):
        logger.info(
            "Generating sound effect %d/%d: '%s' (volume: %ddB)",
            i + 1,
            len(sound_effects),
            effect.prompt[:40],
            effect.volume_db,
        )
        result = client.text_to_sound_effects.convert(
            text=effect.prompt,
            duration_seconds=generation_duration,
        )

        temp_path = AUDIO_OUTPUT_DIR / f"effect_{uuid.uuid4().hex}.mp3"
        temp_paths.append(temp_path)

        with open(temp_path, "wb") as f:
            f.writelines(result)

        audio = AudioSegment.from_mp3(temp_path)
        generated_audios.append((audio, effect.volume_db))

    # Layer all sound effects together
    # Start with the first audio as base
    base_audio, base_volume = generated_audios[0]
    combined = base_audio + base_volume  # Apply volume adjustment

    # Overlay remaining audio tracks
    for audio, volume_db in generated_audios[1:]:
        adjusted_audio = audio + volume_db
        # Ensure tracks are same length by looping shorter ones
        if len(adjusted_audio) < len(combined):
            loops_needed = (len(combined) // len(adjusted_audio)) + 1
            adjusted_audio = adjusted_audio * loops_needed
        adjusted_audio = adjusted_audio[: len(combined)]
        combined = combined.overlay(adjusted_audio)

    # Loop the combined audio to reach target duration if needed
    target_duration_ms = int(duration_seconds * 1000)
    if len(combined) < target_duration_ms:
        loops_needed = (target_duration_ms // len(combined)) + 1
        combined = combined * loops_needed
        combined = combined[:target_duration_ms]

    output_path = AUDIO_OUTPUT_DIR / f"layered_{uuid.uuid4().hex}.mp3"
    combined.export(output_path, format="mp3")
    logger.info("Layered sound effects generated: %dms", len(combined))

    # Cleanup temp files
    for temp_path in temp_paths:
        temp_path.unlink(missing_ok=True)

    return GeneratedAudio(file_path=output_path, duration_ms=len(combined))


def generate_narration(
    text: str, voice_id: str = "21m00Tcm4TlvDq8ikWAM"
) -> GeneratedAudio:
    """
    Generate TTS narration using ElevenLabs.
    Default voice is Rachel (21m00Tcm4TlvDq8ikWAM).
    """
    logger.info("Generating TTS narration: '%s'...", text[:50])
    audio_generator = client.text_to_speech.convert(
        text=text,
        voice_id=voice_id,
        model_id="eleven_turbo_v2_5",
    )

    output_path = AUDIO_OUTPUT_DIR / f"narration_{uuid.uuid4().hex}.mp3"

    with open(output_path, "wb") as f:
        f.writelines(audio_generator)

    audio = AudioSegment.from_mp3(output_path)
    logger.info("TTS narration generated: %dms", len(audio))

    return GeneratedAudio(file_path=output_path, duration_ms=len(audio))


def generate_chunked_narration(
    chunks: list[MeditationChunk],
    voice_id: str = "21m00Tcm4TlvDq8ikWAM",
) -> GeneratedAudio:
    """
    Generate TTS narration for multiple chunks with pauses between them.
    """
    logger.info("Generating chunked narration with %d chunks...", len(chunks))

    if not chunks:
        silence = AudioSegment.silent(duration=1000)
        output_path = AUDIO_OUTPUT_DIR / f"narration_{uuid.uuid4().hex}.mp3"
        silence.export(output_path, format="mp3")
        return GeneratedAudio(file_path=output_path, duration_ms=len(silence))

    combined = AudioSegment.empty()
    temp_paths: list[Path] = []

    for i, chunk in enumerate(chunks):
        logger.info(
            "Generating chunk %d/%d: '%s' (pause: %dms)",
            i + 1,
            len(chunks),
            chunk.text[:40],
            chunk.pause_after_ms,
        )

        # Generate TTS for this chunk
        audio_generator = client.text_to_speech.convert(
            text=chunk.text,
            voice_id=voice_id,
            model_id="eleven_turbo_v2_5",
        )

        temp_path = AUDIO_OUTPUT_DIR / f"chunk_{uuid.uuid4().hex}.mp3"
        temp_paths.append(temp_path)

        with open(temp_path, "wb") as f:
            f.writelines(audio_generator)

        chunk_audio = AudioSegment.from_mp3(temp_path)

        # Add the chunk audio
        combined += chunk_audio

        # Add pause after the chunk
        if chunk.pause_after_ms > 0:
            combined += AudioSegment.silent(duration=chunk.pause_after_ms)

    output_path = AUDIO_OUTPUT_DIR / f"narration_{uuid.uuid4().hex}.mp3"
    combined.export(output_path, format="mp3")
    logger.info("Chunked narration generated: %dms", len(combined))

    # Cleanup temp files
    for temp_path in temp_paths:
        temp_path.unlink(missing_ok=True)

    return GeneratedAudio(file_path=output_path, duration_ms=len(combined))


def combine_audio(
    ambient_path: Path,
    narration_path: Path,
    ambient_reduction_db: int = 10,
) -> Path:
    """
    Combine ambient sound and narration, reducing ambient volume during narration.
    """
    logger.info("Combining audio tracks...")
    ambient = AudioSegment.from_mp3(ambient_path)
    narration = AudioSegment.from_mp3(narration_path)

    # Ensure ambient is at least as long as narration
    if len(ambient) < len(narration):
        # Loop ambient to match narration length
        loops_needed = (len(narration) // len(ambient)) + 1
        ambient = ambient * loops_needed
        ambient = ambient[: len(narration)]

    # Reduce ambient volume
    ambient_reduced = ambient - ambient_reduction_db

    # Overlay narration on ambient
    combined = ambient_reduced.overlay(narration)

    output_path = AUDIO_OUTPUT_DIR / f"combined_{uuid.uuid4().hex}.mp3"
    combined.export(output_path, format="mp3")
    logger.info("Combined audio exported: %dms", len(combined))

    return output_path


def generate_complete_audio(
    sound_effects: list[SoundEffect],
    meditation_chunks: list[MeditationChunk],
    duration_seconds: float = 30.0,
) -> Path:
    """
    Generate complete audio with layered sound effects and chunked narration.
    """
    logger.info("=== Starting complete audio generation ===")

    # Generate chunked narration first to determine minimum ambient duration
    narration = generate_chunked_narration(meditation_chunks)

    # Ensure ambient is long enough for the full narration
    ambient_duration = max(duration_seconds, narration.duration_ms / 1000 + 2)

    # Generate layered sound effects
    ambient = generate_multiple_sound_effects(sound_effects, ambient_duration)

    # Combine ambient and narration
    combined_path = combine_audio(ambient.file_path, narration.file_path)

    # Cleanup temp files
    ambient.file_path.unlink(missing_ok=True)
    narration.file_path.unlink(missing_ok=True)
    logger.info("=== Audio generation complete ===")

    return combined_path
