from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from camera_roll_sounds_api.camera_roll_sounds.models import (
    FREE_MEDITATIONS_PER_MONTH,
    CameraRollSoundsUser,
    GenerationJob,
)
from payment.models import Subscription

User = get_user_model()


class CameraRollSoundsUsageTests(TestCase):
    def setUp(self):
        stripe_patcher = patch(
            "users.models.stripe.Customer.create",
            return_value=SimpleNamespace(id="cus_test"),
        )
        self.mock_stripe_customer_create = stripe_patcher.start()
        self.addCleanup(stripe_patcher.stop)

        async_to_sync_patcher = patch(
            "camera_roll_sounds_api.camera_roll_sounds.views.async_to_sync",
            side_effect=lambda func: func,
        )
        async_to_sync_patcher.start()
        self.addCleanup(async_to_sync_patcher.stop)

        kiq_patcher = patch(
            "camera_roll_sounds_api.camera_roll_sounds.views.generate_audio_for_job.kiq",
            new=Mock(),
        )
        self.mock_kiq = kiq_patcher.start()
        self.addCleanup(kiq_patcher.stop)

        Site.objects.update_or_create(
            id=1,
            defaults={"domain": "testserver", "name": "testserver"},
        )

        self.client = APIClient()
        self.process_image_url = reverse("process-image")
        self.usage_url = reverse("usage-status")

    def create_user(self, email: str) -> User:
        return User.objects.create_user(email=email, password="password123")

    def authenticate(self, user: User) -> None:
        self.client.force_authenticate(user=user)

    def test_free_users_are_limited_to_three_meditations_per_month(self):
        user = self.create_user("free-user@example.com")
        self.authenticate(user)

        for _ in range(FREE_MEDITATIONS_PER_MONTH):
            response = self.client.post(
                self.process_image_url,
                {"image": "aGVsbG8="},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        usage = CameraRollSoundsUser.objects.get(user=user)
        self.assertEqual(
            usage.free_meditations_used_this_month,
            FREE_MEDITATIONS_PER_MONTH,
        )

        blocked_response = self.client.post(
            self.process_image_url,
            {"image": "aGVsbG8="},
            format="json",
        )
        self.assertEqual(blocked_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("free meditations", str(blocked_response.data["detail"]).lower())

    def test_subscribers_can_generate_after_free_limit(self):
        user = self.create_user("subscriber@example.com")
        usage = CameraRollSoundsUser.objects.create(
            user=user,
            free_meditations_used_this_month=FREE_MEDITATIONS_PER_MONTH,
            usage_month_start=timezone.localdate().replace(day=1),
        )
        Subscription.objects.create(
            account=user.get_account(),
            subscription_type="prod_camera_roll_sounds",
            expiration_date=timezone.now() + timedelta(days=30),
            platform_data={},
        )

        self.authenticate(user)
        response = self.client.post(
            self.process_image_url,
            {"image": "aGVsbG8="},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        usage.refresh_from_db()
        self.assertEqual(
            usage.free_meditations_used_this_month,
            FREE_MEDITATIONS_PER_MONTH,
        )
        self.assertEqual(usage.total_meditations_generated, 1)
        self.assertFalse(response.data["usage"]["used_free_generation"])

    def test_usage_resets_when_a_new_month_starts(self):
        user = self.create_user("reset-user@example.com")
        previous_month = (timezone.localdate().replace(day=1) - timedelta(days=1)).replace(
            day=1
        )
        CameraRollSoundsUser.objects.create(
            user=user,
            free_meditations_used_this_month=FREE_MEDITATIONS_PER_MONTH,
            usage_month_start=previous_month,
            total_meditations_generated=5,
        )

        self.authenticate(user)
        response = self.client.get(self.usage_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["free_meditations_used_this_month"], 0)
        self.assertEqual(
            response.data["free_meditations_remaining"],
            FREE_MEDITATIONS_PER_MONTH,
        )
        self.assertEqual(response.data["total_meditations_generated"], 5)

    def test_jobs_and_audio_are_only_visible_to_their_owner(self):
        owner = self.create_user("owner@example.com")
        other_user = self.create_user("other@example.com")
        usage = CameraRollSoundsUser.objects.create(user=owner)
        job = GenerationJob.objects.create(
            camera_roll_sounds_user=usage,
            image_base64="aGVsbG8=",
            status=GenerationJob.Status.COMPLETED,
            audio_filename="private.mp3",
        )

        self.authenticate(other_user)
        job_status_response = self.client.get(reverse("job-status", args=[job.public_id]))
        audio_response = self.client.get(reverse("serve-audio", args=["private.mp3"]))

        self.assertEqual(job_status_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(audio_response.status_code, status.HTTP_404_NOT_FOUND)
