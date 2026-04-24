from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from asgiref.sync import async_to_sync
from django.core.files.storage import default_storage
from django.db import transaction
from django.http import FileResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from payment.billing import user_has_active_subscription

from its_now_api.its_now.models import (
    FREE_MEDITATIONS_PER_MONTH,
    GenerationJob,
    ItsNowUser,
)
from its_now_api.its_now.services.audio_generator import AUDIO_OUTPUT_DIR
from its_now_api.its_now.tasks.generate_audio import generate_audio_for_job

if TYPE_CHECKING:
    from rest_framework.request import Request

logger = logging.getLogger(__name__)


def _normalize_image(image_base64: str) -> str:
    normalized = image_base64.strip()
    if "," in normalized:
        normalized = normalized.split(",", 1)[1]
    return normalized


def _extract_photos(request: Request) -> list[dict[str, str | int]]:
    raw_photos = request.data.get("photos")
    raw_images = request.data.get("images")
    raw_image = request.data.get("image")

    if raw_photos is None and raw_images is None and raw_image is None:
        msg = "No photos provided"
        raise ValueError(msg)

    if raw_photos is not None:
        if not isinstance(raw_photos, list):
            msg = "'photos' must be a list of photo objects"
            raise ValueError(msg)
        photos: list[dict[str, str | int]] = []
        for photo in raw_photos:
            if not isinstance(photo, dict):
                msg = "Each photo must be an object with image and year"
                raise ValueError(msg)
            image = photo.get("image")
            year = photo.get("year")
            if not isinstance(image, str) or not image.strip():
                msg = "Each photo must include a base64-encoded image"
                raise ValueError(msg)
            try:
                normalized_year = int(year)
            except (TypeError, ValueError) as exc:
                msg = "Each photo must include a valid year"
                raise ValueError(msg) from exc
            photos.append(
                {
                    "image_base64": _normalize_image(image),
                    "year": normalized_year,
                }
            )
    elif raw_images is None:
        photos = [{"image_base64": _normalize_image(raw_image), "year": ""}]
    elif isinstance(raw_images, list):
        photos = [
            {"image_base64": _normalize_image(image), "year": ""}
            for image in raw_images
            if isinstance(image, str) and image.strip()
        ]
    else:
        msg = "'images' must be a list of base64-encoded images"
        raise ValueError(msg)

    if not photos:
        msg = "No valid photos provided"
        raise ValueError(msg)
    if raw_photos is not None and not 2 <= len(photos) <= 10:
        msg = "You must provide between 2 and 10 photos"
        raise ValueError(msg)
    return photos


def _extract_present_moment_context(request: Request) -> dict[str, str]:
    nested_context = request.data.get("present_moment")
    if nested_context is not None and not isinstance(nested_context, dict):
        msg = "'present_moment' must be an object"
        raise ValueError(msg)

    current_location = (
        nested_context.get("current_location")
        if nested_context
        else request.data.get("current_location")
    )
    current_date_time = (
        nested_context.get("current_date_time")
        if nested_context
        else request.data.get("current_date_time")
    )
    if not current_date_time:
        current_date_time = (
            nested_context.get("current_date")
            if nested_context
            else request.data.get("current_date")
        )
    user_name = (
        nested_context.get("user_name")
        if nested_context
        else request.data.get("user_name")
    )

    provided_values = {
        "current_location": current_location,
        "current_date_time": current_date_time,
        "user_name": user_name,
    }
    provided_keys = [key for key, value in provided_values.items() if value]
    if not provided_keys:
        return {}

    missing_keys = [key for key, value in provided_values.items() if not value]
    if missing_keys:
        msg = (
            "Present moment grounding requires current_location, current_date_time, "
            "and user_name."
        )
        raise ValueError(msg)

    return {
        "current_location": str(current_location).strip(),
        "current_date_time": str(current_date_time).strip(),
        "user_name": str(user_name).strip(),
    }


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def process_image(request: Request) -> Response:
    try:
        photos = _extract_photos(request)
        present_moment_context = _extract_present_moment_context(request)
    except ValueError as exc:
        return Response({"error": str(exc)}, status=400)

    logger.info("Received %d photo(s), creating generation job...", len(photos))

    with transaction.atomic():
        its_now_user, _ = ItsNowUser.objects.get_or_create(user=request.user)
        its_now_user = ItsNowUser.objects.select_for_update().get(pk=its_now_user.pk)
        its_now_user.reset_monthly_usage_if_needed()

        is_subscriber = user_has_active_subscription(request.user)
        if not is_subscriber and its_now_user.free_meditations_remaining <= 0:
            raise PermissionDenied(
                detail=(
                    f"You have used all {FREE_MEDITATIONS_PER_MONTH} free meditations "
                    "for this month. An active subscription is required for more."
                )
            )

        used_free_generation = not is_subscriber
        its_now_user.total_meditations_generated += 1
        if used_free_generation:
            its_now_user.free_meditations_used_this_month += 1
        its_now_user.save(
            update_fields=[
                "usage_month_start",
                "free_meditations_used_this_month",
                "total_meditations_generated",
                "updated_at",
            ]
        )

        job = GenerationJob.objects.create(
            its_now_user=its_now_user,
            photo_inputs=photos,
            present_moment_context=present_moment_context,
            used_free_generation=used_free_generation,
        )

    async_to_sync(generate_audio_for_job.kiq)(job.pk)
    logger.info("Created job %s with %d photo(s)", job.public_id, len(photos))

    return Response(
        {
            "job_id": job.public_id,
            "status": job.status,
            "message": "Audio generation started",
            "image_count": len(photos),
            "has_present_moment_context": bool(present_moment_context),
            "usage": {
                "is_subscriber": is_subscriber,
                "free_meditations_per_month": FREE_MEDITATIONS_PER_MONTH,
                "free_meditations_used_this_month": (
                    its_now_user.free_meditations_used_this_month
                ),
                "free_meditations_remaining": its_now_user.free_meditations_remaining,
                "used_free_generation": used_free_generation,
            },
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def job_status(request: Request, job_id: str) -> Response:
    job = GenerationJob.objects.filter(
        public_id=job_id,
        its_now_user__user=request.user,
    ).first()
    if not job:
        msg = "Job not found"
        raise NotFound(msg)

    response_data = {
        "job_id": job.public_id,
        "status": job.status,
        "image_count": job.image_count,
    }

    if job.status == GenerationJob.Status.COMPLETED:
        audio_url = request.build_absolute_uri(
            f"/api/its_now/audio/{job.audio_filename}"
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
    job = GenerationJob.objects.filter(
        audio_filename=filename,
        status=GenerationJob.Status.COMPLETED,
    ).first()
    if not job:
        return Response({"error": "Audio file not found"}, status=404)

    if job.audio_storage_key:
        if not default_storage.exists(job.audio_storage_key):
            return Response({"error": "Audio file not found"}, status=404)

        return FileResponse(
            default_storage.open(job.audio_storage_key, "rb"),
            content_type="audio/mpeg",
            as_attachment=False,
        )

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
    its_now_user, _ = ItsNowUser.objects.get_or_create(user=request.user)
    its_now_user.reset_monthly_usage_if_needed()
    its_now_user.save(
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
                its_now_user.free_meditations_used_this_month
            ),
            "free_meditations_remaining": its_now_user.free_meditations_remaining,
            "total_meditations_generated": its_now_user.total_meditations_generated,
        }
    )
