from __future__ import annotations

import logging
from importlib import import_module

logger = logging.getLogger(__name__)

broker = import_module("config.taskiq_config").broker


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

    job.audio_filename = audio_path.name
    job.status = GenerationJob.Status.COMPLETED
    await job.asave()

    logger.info(
        "Audio generation complete for job %s: %s", job.public_id, audio_path.name
    )
