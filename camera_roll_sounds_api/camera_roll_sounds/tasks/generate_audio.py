from __future__ import annotations

import logging
from importlib import import_module
from pathlib import Path

from asgiref.sync import sync_to_async
from django.core.files.base import File
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)

broker = import_module("config.taskiq_config").broker

AUDIO_STORAGE_PREFIX = "camera_roll_sounds/generated_audio"


def store_generated_audio(audio_path: Path) -> str:
    storage_key = f"{AUDIO_STORAGE_PREFIX}/{audio_path.name}"
    with audio_path.open("rb") as audio_file:
        saved_key = default_storage.save(
            storage_key,
            File(audio_file, name=audio_path.name),
        )
    audio_path.unlink(missing_ok=True)
    return saved_key


@broker.task
async def generate_audio_for_job(job_pk: int) -> None:
    from camera_roll_sounds_api.camera_roll_sounds.models import GenerationJob
    from camera_roll_sounds_api.camera_roll_sounds.services.audio_generator import (
        generate_complete_audio,
    )
    from camera_roll_sounds_api.camera_roll_sounds.services.image_processor import (
        analyze_image,
    )

    job = await GenerationJob.objects.aget(pk=job_pk)

    logger.info("Starting audio generation for job %s", job.public_id)

    job.status = GenerationJob.Status.PROCESSING
    await job.asave()

    # Analyze the image
    logger.info("Analyzing image...")
    analysis = analyze_image(job.image_base64)

    job.scene_description = analysis.scene_description
    job.quality_visualization = analysis.quality_visualization
    await job.asave()

    # Generate audio
    logger.info("Generating audio...")
    audio_path = generate_complete_audio(
        sound_effects=analysis.sound_effects,
        meditation_chunks=analysis.meditation_chunks,
    )
    audio_storage_key = await sync_to_async(store_generated_audio)(audio_path)

    job.audio_filename = audio_path.name
    job.audio_storage_key = audio_storage_key
    job.status = GenerationJob.Status.COMPLETED
    await job.asave()

    logger.info(
        "Audio generation complete for job %s: %s", job.public_id, audio_path.name
    )
