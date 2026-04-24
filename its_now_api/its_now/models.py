from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from config.fields import PublicIdField

FREE_MEDITATIONS_PER_MONTH = 3


def current_usage_month_start():
    return timezone.localdate().replace(day=1)


class ItsNowUser(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="its_now_user",
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
        return f"It's Now usage for {self.user}"


class GenerationJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    public_id = PublicIdField()
    its_now_user = models.ForeignKey(
        ItsNowUser,
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
    photo_inputs = models.JSONField(default=list)
    present_moment_context = models.JSONField(default=dict, blank=True)
    scene_description = models.TextField(blank=True)
    quality_visualization = models.CharField(max_length=255, blank=True)
    audio_filename = models.CharField(max_length=255, blank=True)
    audio_storage_key = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def image_count(self) -> int:
        return len(self.photo_inputs)
