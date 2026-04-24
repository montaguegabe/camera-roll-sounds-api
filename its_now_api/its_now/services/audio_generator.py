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
    from its_now_api.its_now.services.image_processor import MeditationChunk, SoundEffect

logger = logging.getLogger(__name__)

AUDIO_OUTPUT_DIR = Path(tempfile.gettempdir()) / "its_now_audio"
AUDIO_OUTPUT_DIR.mkdir(exist_ok=True)


class GeneratedAudio(NamedTuple):
    file_path: Path
    duration_ms: int


def get_elevenlabs_client() -> ElevenLabs:
    return ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))


def generate_multiple_sound_effects(
    sound_effects: list[SoundEffect],
    duration_seconds: float,
) -> GeneratedAudio:
    generation_duration = min(duration_seconds, 30.0)
    logger.info(
        "Generating %d layered sound effects (%.1fs, will loop to %.1fs)...",
        len(sound_effects),
        generation_duration,
        duration_seconds,
    )

    if not sound_effects:
        silence = AudioSegment.silent(duration=int(duration_seconds * 1000))
        output_path = AUDIO_OUTPUT_DIR / f"ambient_{uuid.uuid4().hex}.mp3"
        silence.export(output_path, format="mp3")
        return GeneratedAudio(file_path=output_path, duration_ms=len(silence))

    generated_audios: list[tuple[AudioSegment, int]] = []
    temp_paths: list[Path] = []
    client = get_elevenlabs_client()

    for index, effect in enumerate(sound_effects):
        logger.info(
            "Generating sound effect %d/%d: '%s' (volume: %ddB)",
            index + 1,
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

        with temp_path.open("wb") as handle:
            handle.writelines(result)

        audio = AudioSegment.from_mp3(temp_path)
        generated_audios.append((audio, effect.volume_db))

    base_audio, base_volume = generated_audios[0]
    combined = base_audio + base_volume

    for audio, volume_db in generated_audios[1:]:
        adjusted_audio = audio + volume_db
        if len(adjusted_audio) < len(combined):
            loops_needed = (len(combined) // len(adjusted_audio)) + 1
            adjusted_audio = adjusted_audio * loops_needed
        adjusted_audio = adjusted_audio[: len(combined)]
        combined = combined.overlay(adjusted_audio)

    target_duration_ms = int(duration_seconds * 1000)
    if len(combined) < target_duration_ms:
        loops_needed = (target_duration_ms // len(combined)) + 1
        combined = combined * loops_needed
        combined = combined[:target_duration_ms]

    output_path = AUDIO_OUTPUT_DIR / f"layered_{uuid.uuid4().hex}.mp3"
    combined.export(output_path, format="mp3")

    for temp_path in temp_paths:
        temp_path.unlink(missing_ok=True)

    return GeneratedAudio(file_path=output_path, duration_ms=len(combined))


def generate_chunked_narration(
    chunks: list[MeditationChunk],
    voice_id: str = "21m00Tcm4TlvDq8ikWAM",
) -> GeneratedAudio:
    logger.info("Generating chunked narration with %d chunks...", len(chunks))

    if not chunks:
        silence = AudioSegment.silent(duration=1000)
        output_path = AUDIO_OUTPUT_DIR / f"narration_{uuid.uuid4().hex}.mp3"
        silence.export(output_path, format="mp3")
        return GeneratedAudio(file_path=output_path, duration_ms=len(silence))

    combined = AudioSegment.empty()
    temp_paths: list[Path] = []
    client = get_elevenlabs_client()

    for index, chunk in enumerate(chunks):
        logger.info(
            "Generating chunk %d/%d: '%s' (pause: %dms)",
            index + 1,
            len(chunks),
            chunk.text[:40],
            chunk.pause_after_ms,
        )
        audio_generator = client.text_to_speech.convert(
            text=chunk.text,
            voice_id=voice_id,
            model_id="eleven_turbo_v2_5",
        )

        temp_path = AUDIO_OUTPUT_DIR / f"chunk_{uuid.uuid4().hex}.mp3"
        temp_paths.append(temp_path)

        with temp_path.open("wb") as handle:
            handle.writelines(audio_generator)

        chunk_audio = AudioSegment.from_mp3(temp_path)
        combined += chunk_audio

        if chunk.pause_after_ms > 0:
            combined += AudioSegment.silent(duration=chunk.pause_after_ms)

    output_path = AUDIO_OUTPUT_DIR / f"narration_{uuid.uuid4().hex}.mp3"
    combined.export(output_path, format="mp3")

    for temp_path in temp_paths:
        temp_path.unlink(missing_ok=True)

    return GeneratedAudio(file_path=output_path, duration_ms=len(combined))


def combine_audio(
    ambient_path: Path,
    narration_path: Path,
    ambient_reduction_db: int = 10,
) -> Path:
    ambient = AudioSegment.from_mp3(ambient_path)
    narration = AudioSegment.from_mp3(narration_path)

    if len(ambient) < len(narration):
        loops_needed = (len(narration) // len(ambient)) + 1
        ambient = ambient * loops_needed
        ambient = ambient[: len(narration)]

    ambient_reduced = ambient - ambient_reduction_db
    combined = ambient_reduced.overlay(narration)

    output_path = AUDIO_OUTPUT_DIR / f"combined_{uuid.uuid4().hex}.mp3"
    combined.export(output_path, format="mp3")
    return output_path


def generate_complete_audio(
    sound_effects: list[SoundEffect],
    meditation_chunks: list[MeditationChunk],
    duration_seconds: float = 30.0,
) -> Path:
    narration = generate_chunked_narration(meditation_chunks)
    ambient_duration = max(duration_seconds, narration.duration_ms / 1000 + 2)
    ambient = generate_multiple_sound_effects(sound_effects, ambient_duration)
    combined_path = combine_audio(ambient.file_path, narration.file_path)

    ambient.file_path.unlink(missing_ok=True)
    narration.file_path.unlink(missing_ok=True)
    return combined_path
