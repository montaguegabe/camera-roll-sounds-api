from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from asgiref.sync import async_to_sync
from django.http import FileResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from camera_roll_sounds_api.camera_roll_sounds.models import GenerationJob
from camera_roll_sounds_api.camera_roll_sounds.services.audio_generator import (
    AUDIO_OUTPUT_DIR,
)
from camera_roll_sounds_api.camera_roll_sounds.tasks.generate_audio import (
    generate_audio_for_job,
)

if TYPE_CHECKING:
    from rest_framework.request import Request

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([AllowAny])
def process_image(request: Request) -> Response:
    """
    Start async audio generation for an image.

    Expects JSON body with:
    - image: base64-encoded image data

    Returns a job_id to poll for status.
    """
    image_base64 = request.data.get("image")
    if not image_base64:
        logger.warning("No image provided in request")
        return Response({"error": "No image provided"}, status=400)

    # Remove data URL prefix if present
    if "," in image_base64:
        image_base64 = image_base64.split(",", 1)[1]

    logger.info("Received image (%d bytes base64), creating job...", len(image_base64))

    # Create job and queue the task
    job = GenerationJob.objects.create(image_base64=image_base64)
    async_to_sync(generate_audio_for_job.kiq)(job.pk)

    logger.info("Created job %s", job.public_id)

    return Response(
        {
            "job_id": job.public_id,
            "status": job.status,
            "message": "Audio generation started",
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def job_status(request: Request, job_id: str) -> Response:
    """
    Check the status of an audio generation job.
    """
    job = GenerationJob.objects.filter(public_id=job_id).first()
    if not job:
        msg = "Job not found"
        raise NotFound(msg)

    response_data = {
        "job_id": job.public_id,
        "status": job.status,
    }

    if job.status == GenerationJob.Status.COMPLETED:
        audio_url = request.build_absolute_uri(
            f"/api/camera_roll_sounds/audio/{job.audio_filename}"
        )
        response_data.update(
            {
                "audio_url": audio_url,
                "description": job.scene_description,
                "quality_visualization": job.quality_visualization,
            }
        )
    elif job.status == GenerationJob.Status.FAILED:
        response_data["error"] = job.error_message

    return Response(response_data)


@api_view(["GET"])
@permission_classes([AllowAny])
def serve_audio(request: Request, filename: str) -> FileResponse:
    """
    Serve a generated audio file.
    """
    audio_path = AUDIO_OUTPUT_DIR / filename
    if not audio_path.exists():
        return Response({"error": "Audio file not found"}, status=404)

    return FileResponse(
        open(audio_path, "rb"),
        content_type="audio/mpeg",
        as_attachment=False,
    )
