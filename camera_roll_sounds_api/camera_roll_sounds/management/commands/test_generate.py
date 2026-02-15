from __future__ import annotations

import base64
from pathlib import Path

from django.core.management.base import BaseCommand

from camera_roll_sounds_api.camera_roll_sounds.services.audio_generator import (
    generate_complete_audio,
)
from camera_roll_sounds_api.camera_roll_sounds.services.image_processor import (
    analyze_image,
)


class Command(BaseCommand):
    help = "Test the image-to-sound pipeline with a local image file"

    def add_arguments(self, parser):
        parser.add_argument("image_path", type=str, help="Path to an image file")
        parser.add_argument(
            "--duration",
            type=float,
            default=15.0,
            help="Duration of ambient sound in seconds",
        )

    def handle(self, *args, **options):
        image_path = Path(options["image_path"])
        duration = options["duration"]

        if not image_path.exists():
            self.stderr.write(self.style.ERROR(f"File not found: {image_path}"))
            return

        self.stdout.write(f"Loading image: {image_path}")

        # Read and encode image
        with open(image_path, "rb") as f:
            image_data = f.read()
        image_base64 = base64.b64encode(image_data).decode("utf-8")

        self.stdout.write(f"Image size: {len(image_data) / 1024:.1f}KB")
        self.stdout.write("Analyzing image with GPT-4o...")

        # Analyze image
        analysis = analyze_image(image_base64)

        self.stdout.write(self.style.SUCCESS("Analysis complete:"))
        self.stdout.write(f"  Scene: {analysis.scene_description}")
        self.stdout.write(f"  Quality: {analysis.quality_visualization}")
        self.stdout.write(f"  Sound effects ({len(analysis.sound_effects)}):")
        for i, effect in enumerate(analysis.sound_effects):
            self.stdout.write(f"    {i + 1}. {effect.prompt} ({effect.volume_db}dB)")
        self.stdout.write(f"  Meditation chunks ({len(analysis.meditation_chunks)}):")
        for i, chunk in enumerate(analysis.meditation_chunks):
            self.stdout.write(
                f"    {i + 1}. {chunk.text[:60]}... ({chunk.pause_after_ms}ms)"
            )

        self.stdout.write("\nGenerating audio...")

        # Generate audio
        audio_path = generate_complete_audio(
            sound_effects=analysis.sound_effects,
            meditation_chunks=analysis.meditation_chunks,
            duration_seconds=duration,
        )

        self.stdout.write(self.style.SUCCESS(f"\nAudio saved to: {audio_path}"))
        self.stdout.write(f"Play with: afplay {audio_path}")
