from __future__ import annotations

from django.conf import settings
from config.fields import PublicIdField
from django.db import models
from django.utils import timezone

FREE_MEDITATIONS_PER_MONTH = 3


def current_usage_month_start():
    return timezone.localdate().replace(day=1)


class CameraRollSoundsUser(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="camera_roll_sounds_user",
    )
    free_meditations_used_this_month = models.PositiveIntegerField(default=0)
    usage_month_start = models.DateField(default=current_usage_month_start)
    total_meditations_generated = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def reset_monthly_usage_if_needed(self):
        month_start = current_usage_month_start()
        if self.usage_month_start != month_start:
            self.usage_month_start = month_start
            self.free_meditations_used_this_month = 0

    @property
    def free_meditations_remaining(self):
        return max(
            0,
            FREE_MEDITATIONS_PER_MONTH - self.free_meditations_used_this_month,
        )

    def __str__(self):
        return f"Camera Roll Sounds usage for {self.user}"


class GenerationJob(models.Model):
    """🎵 Tracks async audio generation jobs."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    public_id = PublicIdField()
    camera_roll_sounds_user = models.ForeignKey(
        CameraRollSoundsUser,
        on_delete=models.CASCADE,
        related_name="generation_jobs",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    used_free_generation = models.BooleanField(default=False)
    image_base64 = models.TextField()
    scene_description = models.TextField(blank=True)
    quality_visualization = models.CharField(max_length=100, blank=True)
    audio_filename = models.CharField(max_length=255, blank=True)
    audio_storage_key = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
