from __future__ import annotations

from config.fields import PublicIdField
from django.db import models


class GenerationJob(models.Model):
    """🎵 Tracks async audio generation jobs."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    public_id = PublicIdField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    image_base64 = models.TextField()
    scene_description = models.TextField(blank=True)
    quality_visualization = models.CharField(max_length=100, blank=True)
    audio_filename = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
