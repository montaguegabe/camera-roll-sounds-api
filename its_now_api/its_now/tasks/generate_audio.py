from __future__ import annotations

import logging
from importlib import import_module
from pathlib import Path

from asgiref.sync import sync_to_async
from django.core.files.base import File
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)

broker = import_module("config.taskiq_config").broker

AUDIO_STORAGE_PREFIX = "its_now/generated_audio"


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
    from its_now_api.its_now.models import GenerationJob
    from its_now_api.its_now.services.audio_generator import generate_complete_audio
    from its_now_api.its_now.services.image_processor import analyze_image_sequence

    job = await GenerationJob.objects.aget(pk=job_pk)

    logger.info("Starting audio generation for job %s", job.public_id)
    job.status = GenerationJob.Status.PROCESSING
    await job.asave(update_fields=["status", "updated_at"])

    try:
        analysis = analyze_image_sequence(
            job.photo_inputs,
            present_moment_context=job.present_moment_context,
        )
        job.scene_description = analysis.scene_description
        job.quality_visualization = analysis.quality_visualization
        await job.asave(
            update_fields=[
                "scene_description",
                "quality_visualization",
                "updated_at",
            ]
        )

        audio_path = generate_complete_audio(
            sound_effects=analysis.sound_effects,
            meditation_chunks=analysis.meditation_chunks,
        )
        audio_storage_key = await sync_to_async(store_generated_audio)(audio_path)

        job.audio_filename = audio_path.name
        job.audio_storage_key = audio_storage_key
        job.status = GenerationJob.Status.COMPLETED
        job.error_message = ""
        await job.asave(
            update_fields=[
                "audio_filename",
                "audio_storage_key",
                "status",
                "error_message",
                "updated_at",
            ]
        )
    except Exception as exc:
        logger.exception("Audio generation failed for job %s", job.public_id)
        job.status = GenerationJob.Status.FAILED
        job.error_message = str(exc)
        await job.asave(update_fields=["status", "error_message", "updated_at"])
        raise
