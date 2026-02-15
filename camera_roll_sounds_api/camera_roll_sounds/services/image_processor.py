from __future__ import annotations

import logging
from typing import NamedTuple

from openai import OpenAI
from pydantic import BaseModel
from utils import dedent_strip

logger = logging.getLogger(__name__)

client = OpenAI()


class SoundEffect(BaseModel):
    prompt: str
    volume_db: int


class MeditationChunk(BaseModel):
    text: str
    pause_after_ms: int


class ImageAnalysis(BaseModel):
    scene_description: str
    sound_effects: list[SoundEffect]
    meditation_chunks: list[MeditationChunk]
    quality_visualization: str


class ImageAnalysisResult(NamedTuple):
    scene_description: str
    sound_effects: list[SoundEffect]
    meditation_chunks: list[MeditationChunk]
    quality_visualization: str


def analyze_image(image_base64: str) -> ImageAnalysisResult:
    """
    Analyze an image using GPT-4o and generate sound effects and meditation content.
    """
    logger.info("Sending image to GPT-4o for analysis...")
    system_prompt = dedent_strip(
        """\
        You are an expert at creating immersive, meditative audio experiences from
        images. Analyze the image and provide:

        1. SCENE DESCRIPTION: A brief description of the scene.

        2. SOUND EFFECTS (1-4 layered sounds):
           Generate 1-4 distinct ambient sound effect prompts that layer well
           together to create an immersive soundscape. Examples:
           - A beach scene might have: gentle waves, seagulls, distant wind
           - A forest might have: rustling leaves, bird songs, creek water
           Each sound effect needs:
           - prompt: A detailed description for sound generation (e.g., "gentle
             ocean waves lapping on sandy shore")
           - volume_db: Relative volume adjustment (-10 to 0, where 0 is loudest).
             Use -10 for subtle background layers, 0 for primary sounds.

        3. MEDITATION CHUNKS (4-6 chunks):
           Create a guided meditation in 4-6 chunks. Each chunk should be 2-4
           sentences, verbose and descriptive. Structure:
           - Chunk 1: Opening breath awareness - invite the listener to take deep
             breaths and settle into the present moment
           - Chunk 2: Scene observation - describe what they see in vivid detail
           - Chunk 3: Sensory immersion - sounds, textures, temperature, smells
           - Chunk 4: Body scan with quality flowing through body - have the
             listener notice a quality (warmth, peace, light, calm) entering their
             body and flowing from head to toes
           - Chunk 5: Deepening - allow the quality to settle and expand
           - Chunk 6: Closing/gratitude - gently bring awareness back, express
             gratitude for this moment
           Each chunk needs:
           - text: The meditation text (2-4 sentences, rich and evocative)
           - pause_after_ms: Silence after this chunk (1000-4000ms). Use longer
             pauses (3000-4000) after breathing instructions, shorter (1000-2000)
             for transitions.

        4. QUALITY VISUALIZATION: A single word describing the quality that flows
           through the body during the meditation (e.g., "warmth", "light",
           "peace", "calm", "serenity", "golden light").

        Be verbose and evocative in the meditation. Paint pictures with words.
        """
    )

    response = client.beta.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}",
                        },
                    },
                    {
                        "type": "text",
                        "text": "Analyze this image and create a meditative audio experience.",
                    },
                ],
            },
        ],
        response_format=ImageAnalysis,
    )

    analysis = response.choices[0].message.parsed
    logger.info("GPT-4o analysis complete")
    logger.info("Sound effects: %d", len(analysis.sound_effects))
    logger.info("Meditation chunks: %d", len(analysis.meditation_chunks))

    return ImageAnalysisResult(
        scene_description=analysis.scene_description,
        sound_effects=analysis.sound_effects,
        meditation_chunks=analysis.meditation_chunks,
        quality_visualization=analysis.quality_visualization,
    )
