from __future__ import annotations

import base64
from pathlib import Path

from django.core.management.base import BaseCommand

from its_now_api.its_now.services.audio_generator import generate_complete_audio
from its_now_api.its_now.services.image_processor import analyze_image_sequence


class Command(BaseCommand):
    help = "Test the multi-image meditation pipeline with one or more local image files"

    def add_arguments(self, parser):
        parser.add_argument(
            "image_paths",
            nargs="+",
            type=str,
            help="One or more paths to image files",
        )
        parser.add_argument(
            "--duration",
            type=float,
            default=15.0,
            help="Minimum duration of ambient sound in seconds",
        )
        parser.add_argument(
            "--photo-years",
            nargs="+",
            type=int,
            help="Years corresponding to each supplied photo, in order",
        )
        parser.add_argument("--current-location", type=str)
        parser.add_argument("--current-date-time", type=str)
        parser.add_argument("--user-name", type=str)

    def handle(self, *args, **options):
        image_paths = [Path(path) for path in options["image_paths"]]
        duration = options["duration"]
        present_moment_context = None
        photo_years = options.get("photo_years")

        if any(
            options.get(key)
            for key in ("current_location", "current_date_time", "user_name")
        ):
            missing_fields = [
                key
                for key in ("current_location", "current_date_time", "user_name")
                if not options.get(key)
            ]
            if missing_fields:
                self.stderr.write(
                    self.style.ERROR(
                        "Present-moment closing requires --current-location, "
                        "--current-date-time, and --user-name together."
                    )
                )
                return
            present_moment_context = {
                "current_location": options["current_location"],
                "current_date_time": options["current_date_time"],
                "user_name": options["user_name"],
            }

        if photo_years and len(photo_years) != len(image_paths):
            self.stderr.write(
                self.style.ERROR(
                    "The number of --photo-years entries must match the number of images."
                )
            )
            return

        for image_path in image_paths:
            if not image_path.exists():
                self.stderr.write(self.style.ERROR(f"File not found: {image_path}"))
                return

        photo_inputs: list[dict[str, str | int]] = []
        for index, image_path in enumerate(image_paths):
            self.stdout.write(f"Loading image: {image_path}")
            with image_path.open("rb") as handle:
                image_data = handle.read()
            photo_inputs.append(
                {
                    "image_base64": base64.b64encode(image_data).decode("utf-8"),
                    "year": (
                        photo_years[index]
                        if photo_years
                        else "unknown year"
                    ),
                }
            )

        self.stdout.write(f"Loaded {len(photo_inputs)} image(s)")
        self.stdout.write("Analyzing image sequence with GPT-4o...")

        analysis = analyze_image_sequence(
            photo_inputs,
            present_moment_context=present_moment_context,
        )

        self.stdout.write(self.style.SUCCESS("Analysis complete:"))
        self.stdout.write(f"  Combined scene: {analysis.scene_description}")
        self.stdout.write(f"  Quality path: {analysis.quality_visualization}")
        self.stdout.write(f"  Sound effects ({len(analysis.sound_effects)}):")
        for index, effect in enumerate(analysis.sound_effects):
            self.stdout.write(f"    {index + 1}. {effect.prompt} ({effect.volume_db}dB)")
        self.stdout.write(f"  Meditation chunks ({len(analysis.meditation_chunks)}):")
        for index, chunk in enumerate(analysis.meditation_chunks):
            self.stdout.write(
                f"    {index + 1}. {chunk.text[:60]}... ({chunk.pause_after_ms}ms)"
            )

        self.stdout.write("\nGenerating audio...")
        audio_path = generate_complete_audio(
            sound_effects=analysis.sound_effects,
            meditation_chunks=analysis.meditation_chunks,
            duration_seconds=duration,
        )

        self.stdout.write(self.style.SUCCESS(f"\nAudio saved to: {audio_path}"))
        self.stdout.write(f"Play with: afplay {audio_path}")
