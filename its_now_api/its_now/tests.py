from __future__ import annotations

from datetime import timedelta
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import SimpleTestCase, TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from payment.models import Subscription

from its_now_api.its_now.models import (
    FREE_MEDITATIONS_PER_MONTH,
    GenerationJob,
    ItsNowUser,
)
from its_now_api.its_now.services.image_processor import (
    ImageAnalysisResult,
    MeditationChunk,
    SoundEffect,
    analyze_image_sequence,
)

User = get_user_model()


class ItsNowUsageTests(TestCase):
    def setUp(self):
        stripe_patcher = patch(
            "users.models.stripe.Customer.create",
            return_value=SimpleNamespace(id="cus_test"),
        )
        stripe_patcher.start()
        self.addCleanup(stripe_patcher.stop)

        async_to_sync_patcher = patch(
            "its_now_api.its_now.views.async_to_sync",
            side_effect=lambda func: func,
        )
        async_to_sync_patcher.start()
        self.addCleanup(async_to_sync_patcher.stop)

        kiq_patcher = patch(
            "its_now_api.its_now.views.generate_audio_for_job.kiq",
            new=Mock(),
        )
        kiq_patcher.start()
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

        usage = ItsNowUser.objects.get(user=user)
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
        usage = ItsNowUser.objects.create(
            user=user,
            free_meditations_used_this_month=FREE_MEDITATIONS_PER_MONTH,
            usage_month_start=timezone.localdate().replace(day=1),
        )
        Subscription.objects.create(
            account=user.get_account(),
            subscription_type="prod_its_now",
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
        ItsNowUser.objects.create(
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

    def test_jobs_are_only_visible_to_their_owner(self):
        owner = self.create_user("owner@example.com")
        other_user = self.create_user("other@example.com")
        usage = ItsNowUser.objects.create(user=owner)
        job = GenerationJob.objects.create(
            its_now_user=usage,
            photo_inputs=[{"image_base64": "aGVsbG8=", "year": 2020}],
            status=GenerationJob.Status.COMPLETED,
            audio_filename="private.mp3",
        )

        self.authenticate(other_user)
        job_status_response = self.client.get(reverse("job-status", args=[job.public_id]))

        self.assertEqual(job_status_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_audio_is_public_when_the_unguessable_token_exists(self):
        owner = self.create_user("owner@example.com")
        usage = ItsNowUser.objects.create(user=owner)

        with TemporaryDirectory() as media_root:
            with override_settings(
                MEDIA_ROOT=media_root,
                STORAGES={
                    "default": {
                        "BACKEND": "django.core.files.storage.FileSystemStorage",
                    },
                    "staticfiles": {
                        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
                    },
                },
            ):
                storage_key = default_storage.save(
                    "its_now/generated_audio/private.mp3",
                    ContentFile(b"test audio"),
                )
                GenerationJob.objects.create(
                    its_now_user=usage,
                    photo_inputs=[{"image_base64": "aGVsbG8=", "year": 2020}],
                    status=GenerationJob.Status.COMPLETED,
                    audio_filename="private.mp3",
                    audio_storage_key=storage_key,
                )

                audio_response = self.client.get(
                    reverse("serve-audio", args=["private.mp3"])
                )

        self.assertEqual(audio_response.status_code, status.HTTP_200_OK)

    def test_multiple_images_can_be_submitted_in_one_job(self):
        user = self.create_user("multi@example.com")
        self.authenticate(user)

        response = self.client.post(
            self.process_image_url,
            {
                "photos": [
                    {"image": "data:image/jpeg;base64,aGVsbG8=", "year": 2019},
                    {"image": "Ymll", "year": 2021},
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["image_count"], 2)

        job = GenerationJob.objects.get(public_id=response.data["job_id"])
        self.assertEqual(
            job.photo_inputs,
            [
                {"image_base64": "aGVsbG8=", "year": 2019},
                {"image_base64": "Ymll", "year": 2021},
            ],
        )

    def test_photo_count_must_be_between_two_and_ten_for_multi_photo_payload(self):
        user = self.create_user("bounds@example.com")
        self.authenticate(user)

        response = self.client.post(
            self.process_image_url,
            {"photos": [{"image": "aGVsbG8=", "year": 2020}]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("between 2 and 10 photos", response.data["error"])

    def test_present_moment_context_is_stored_on_the_job(self):
        user = self.create_user("grounded@example.com")
        self.authenticate(user)

        response = self.client.post(
            self.process_image_url,
            {
                "photos": [
                    {"image": "aGVsbG8=", "year": 2018},
                    {"image": "Ymll", "year": 2020},
                ],
                "current_location": "Brooklyn, New York",
                "current_date_time": "April 24, 2026 at 5:30 PM",
                "user_name": "Gabe",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["has_present_moment_context"])

        job = GenerationJob.objects.get(public_id=response.data["job_id"])
        self.assertEqual(
            job.present_moment_context,
            {
                "current_location": "Brooklyn, New York",
                "current_date_time": "April 24, 2026 at 5:30 PM",
                "user_name": "Gabe",
            },
        )


class ImageSequenceAnalysisTests(SimpleTestCase):
    def test_subsequent_images_receive_previous_meditation_context(self):
        first_analysis = ImageAnalysisResult(
            scene_description="A quiet shoreline at sunrise.",
            sound_effects=[SoundEffect(prompt="gentle waves", volume_db=-4)],
            meditation_chunks=[
                MeditationChunk(
                    text="Notice the tide easing in and out beneath your breath.",
                    pause_after_ms=1500,
                )
            ],
            quality_visualization="warmth",
            continuity_summary="The meditation has settled into a soft tidal rhythm.",
        )
        second_analysis = ImageAnalysisResult(
            scene_description="A grove of trees moving in wind.",
            sound_effects=[SoundEffect(prompt="soft wind in leaves", volume_db=-5)],
            meditation_chunks=[
                MeditationChunk(
                    text="Let that same rhythm follow you into the trees.",
                    pause_after_ms=1500,
                )
            ],
            quality_visualization="openness",
            continuity_summary="The meditation opens from shore into sheltering branches.",
        )

        with patch(
            "its_now_api.its_now.services.image_processor.analyze_image",
            side_effect=[first_analysis, second_analysis],
        ) as mock_analyze_image:
            result = analyze_image_sequence(
                [
                    {"image_base64": "first-image", "year": 2014},
                    {"image_base64": "second-image", "year": 2019},
                ]
            )

        self.assertEqual(mock_analyze_image.call_count, 2)
        first_call = mock_analyze_image.call_args_list[0]
        self.assertEqual(first_call.kwargs["photo_year"], 2014)
        second_call = mock_analyze_image.call_args_list[1]
        self.assertEqual(second_call.kwargs["image_index"], 1)
        self.assertEqual(second_call.kwargs["total_images"], 2)
        self.assertEqual(second_call.kwargs["photo_year"], 2019)
        self.assertIn("A quiet shoreline at sunrise.", second_call.kwargs["previous_context"])
        self.assertIn(
            "The meditation has settled into a soft tidal rhythm.",
            second_call.kwargs["previous_context"],
        )
        self.assertIn(
            "Notice the tide easing in and out beneath your breath.",
            second_call.kwargs["previous_context"],
        )
        self.assertEqual(len(result.meditation_chunks), 2)
        self.assertEqual(result.quality_visualization, "warmth -> openness")

    def test_present_moment_closing_is_appended_to_the_sequence(self):
        image_analysis = ImageAnalysisResult(
            scene_description="Sunlight across a quiet room.",
            sound_effects=[SoundEffect(prompt="soft room tone", volume_db=-4)],
            meditation_chunks=[
                MeditationChunk(
                    text="Let the room soften around you.",
                    pause_after_ms=1500,
                )
            ],
            quality_visualization="ease",
            continuity_summary="The meditation settles into a quiet interior stillness.",
        )
        closing_chunks = [
            MeditationChunk(
                text="Gabe, feel yourself here in Brooklyn, New York, on April 24, 2026.",
                pause_after_ms=1500,
            ),
            MeditationChunk(
                text="Let your eyes open gently. What do you want to do now?",
                pause_after_ms=1000,
            ),
        ]

        with patch(
            "its_now_api.its_now.services.image_processor.analyze_image",
            return_value=image_analysis,
        ), patch(
            "its_now_api.its_now.services.image_processor.analyze_present_moment_closing",
            return_value=closing_chunks,
        ) as mock_closing:
            result = analyze_image_sequence(
                [{"image_base64": "first-image", "year": 2016}],
                present_moment_context={
                    "current_location": "Brooklyn, New York",
                    "current_date_time": "April 24, 2026 at 5:30 PM",
                    "user_name": "Gabe",
                },
            )

        self.assertEqual(len(result.meditation_chunks), 3)
        self.assertEqual(result.meditation_chunks[-1].text, closing_chunks[-1].text)
        self.assertIn("Present-moment grounding", result.scene_description)
        self.assertEqual(result.quality_visualization, "ease -> present awareness")
        self.assertEqual(
            mock_closing.call_args.kwargs["current_location"],
            "Brooklyn, New York",
        )
        self.assertEqual(
            mock_closing.call_args.kwargs["current_date_time"],
            "April 24, 2026 at 5:30 PM",
        )
