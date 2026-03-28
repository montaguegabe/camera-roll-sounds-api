from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from asgiref.sync import async_to_sync
from django.db import transaction
from django.http import FileResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied

from camera_roll_sounds_api.camera_roll_sounds.models import (
    FREE_MEDITATIONS_PER_MONTH,
    CameraRollSoundsUser,
    GenerationJob,
)
from camera_roll_sounds_api.camera_roll_sounds.services.audio_generator import (
    AUDIO_OUTPUT_DIR,
)
from camera_roll_sounds_api.camera_roll_sounds.tasks.generate_audio import (
    generate_audio_for_job,
)
from payment.billing import user_has_active_subscription

if TYPE_CHECKING:
    from rest_framework.request import Request

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
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

    with transaction.atomic():
        camera_roll_sounds_user, _ = CameraRollSoundsUser.objects.get_or_create(
            user=request.user
        )
        camera_roll_sounds_user = CameraRollSoundsUser.objects.select_for_update().get(
            pk=camera_roll_sounds_user.pk
        )
        camera_roll_sounds_user.reset_monthly_usage_if_needed()

        is_subscriber = user_has_active_subscription(request.user)
        if not is_subscriber and camera_roll_sounds_user.free_meditations_remaining <= 0:
            raise PermissionDenied(
                detail=(
                    f"You have used all {FREE_MEDITATIONS_PER_MONTH} free meditations "
                    "for this month. An active subscription is required for more."
                )
            )

        used_free_generation = not is_subscriber
        camera_roll_sounds_user.total_meditations_generated += 1
        if used_free_generation:
            camera_roll_sounds_user.free_meditations_used_this_month += 1
        camera_roll_sounds_user.save(
            update_fields=[
                "usage_month_start",
                "free_meditations_used_this_month",
                "total_meditations_generated",
                "updated_at",
            ]
        )

        # Create job and queue the task
        job = GenerationJob.objects.create(
            camera_roll_sounds_user=camera_roll_sounds_user,
            image_base64=image_base64,
            used_free_generation=used_free_generation,
        )
    async_to_sync(generate_audio_for_job.kiq)(job.pk)

    logger.info("Created job %s", job.public_id)

    return Response(
        {
            "job_id": job.public_id,
            "status": job.status,
            "message": "Audio generation started",
            "usage": {
                "is_subscriber": is_subscriber,
                "free_meditations_per_month": FREE_MEDITATIONS_PER_MONTH,
                "free_meditations_used_this_month": (
                    camera_roll_sounds_user.free_meditations_used_this_month
                ),
                "free_meditations_remaining": (
                    camera_roll_sounds_user.free_meditations_remaining
                ),
                "used_free_generation": used_free_generation,
            },
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def job_status(request: Request, job_id: str) -> Response:
    """
    Check the status of an audio generation job.
    """
    job = GenerationJob.objects.filter(
        public_id=job_id,
        camera_roll_sounds_user__user=request.user,
    ).first()
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
@permission_classes([IsAuthenticated])
def serve_audio(request: Request, filename: str) -> FileResponse:
    """
    Serve a generated audio file.
    """
    job = GenerationJob.objects.filter(
        audio_filename=filename,
        status=GenerationJob.Status.COMPLETED,
        camera_roll_sounds_user__user=request.user,
    ).first()
    if not job:
        return Response({"error": "Audio file not found"}, status=404)

    audio_path = AUDIO_OUTPUT_DIR / filename
    if not audio_path.exists():
        return Response({"error": "Audio file not found"}, status=404)

    return FileResponse(
        open(audio_path, "rb"),
        content_type="audio/mpeg",
        as_attachment=False,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def usage_status(request: Request) -> Response:
    camera_roll_sounds_user, _ = CameraRollSoundsUser.objects.get_or_create(
        user=request.user
    )
    camera_roll_sounds_user.reset_monthly_usage_if_needed()
    camera_roll_sounds_user.save(
        update_fields=[
            "usage_month_start",
            "free_meditations_used_this_month",
            "updated_at",
        ]
    )

    return Response(
        {
            "is_subscriber": user_has_active_subscription(request.user),
            "free_meditations_per_month": FREE_MEDITATIONS_PER_MONTH,
            "free_meditations_used_this_month": (
                camera_roll_sounds_user.free_meditations_used_this_month
            ),
            "free_meditations_remaining": (
                camera_roll_sounds_user.free_meditations_remaining
            ),
            "total_meditations_generated": (
                camera_roll_sounds_user.total_meditations_generated
            ),
        }
    )
