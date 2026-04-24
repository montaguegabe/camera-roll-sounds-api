from __future__ import annotations

import os
import logging
from textwrap import dedent
from typing import NamedTuple

from openai import OpenAI
from pydantic import BaseModel

logger = logging.getLogger(__name__)


def dedent_strip(text: str) -> str:
    return dedent(text).strip()


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
    continuity_summary: str


class ImageAnalysisResult(NamedTuple):
    scene_description: str
    sound_effects: list[SoundEffect]
    meditation_chunks: list[MeditationChunk]
    quality_visualization: str
    continuity_summary: str


class ImageSequenceAnalysisResult(NamedTuple):
    scene_description: str
    sound_effects: list[SoundEffect]
    meditation_chunks: list[MeditationChunk]
    quality_visualization: str


def get_openai_client() -> OpenAI:
    return OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


class PresentMomentClosing(BaseModel):
    meditation_chunks: list[MeditationChunk]


def build_continuity_context(previous_analysis: ImageAnalysisResult) -> str:
    last_chunk = (
        previous_analysis.meditation_chunks[-1].text
        if previous_analysis.meditation_chunks
        else ""
    )
    return dedent_strip(
        f"""\
        Previous scene: {previous_analysis.scene_description}
        Quality carried forward so far: {previous_analysis.quality_visualization}
        Summary of the emotional and sensory arc so far: {previous_analysis.continuity_summary}
        Last spoken beat from the previous segment: {last_chunk}
        Continue naturally from that emotional and sensory arc instead of restarting.
        Let one sensory element from the previous scene transform into the next scene.
        """
    )


def get_segment_guidance(*, image_index: int, total_images: int) -> str:
    if total_images == 1:
        return dedent_strip(
            """\
            Create a complete guided scene in 4-6 chunks with a gentle opening,
            sensory immersion, body-based quality visualization, and a closing.
            Do not refer to "the meditation" or describe what you are doing structurally.
            """
        )

    if image_index == 0:
        return dedent_strip(
            """\
            This is the opening segment of a stitched multi-photo sequence.
            Create 3-4 chunks that settle the listener, open the first scene,
            and leave them ready to move forward without fully closing.
            Do not refer to "the meditation" or describe the structure out loud.
            """
        )

    if image_index == total_images - 1:
        return dedent_strip(
            """\
            This is the final photo-based segment of a stitched multi-photo sequence.
            Create 3-4 chunks that transition smoothly from what came before,
            immerse the listener in this scene, and bring the overall experience
            to a gentle closing.
            The transition should feel like one place slowly becoming another,
            not like a scene cut. Avoid phrases like "now the meditation moves."
            """
        )

    return dedent_strip(
        """\
        This is a middle segment of a stitched multi-photo sequence.
        Create 3-4 chunks that transition from the prior segment, deepen the
        sensory experience of this new scene, and keep the meditation moving
        without resetting the listener.
        Let the previous scene dissolve into this one through shared texture,
        sound, light, weather, or body feeling. Avoid phrases like
        "now the meditation moves" or "in this meditation."
        """
    )


def build_system_prompt(*, image_index: int, total_images: int) -> str:
    segment_guidance = get_segment_guidance(
        image_index=image_index,
        total_images=total_images,
    )
    return dedent_strip(
        f"""\
        You are an expert at creating immersive, meditative audio experiences
        from images.

        {segment_guidance}

        Provide:

        1. SCENE DESCRIPTION:
           A brief description of the scene in this image, naturally anchored
           to the photo's year.

        2. SOUND EFFECTS:
           Generate 1-2 ambient sound effect prompts that would blend well into
           a single stitched meditation soundscape.
           Each sound effect needs:
           - prompt: A detailed description for sound generation
           - volume_db: Relative volume adjustment (-10 to 0)

        3. MEDITATION CHUNKS:
           Each chunk should be 2-4 sentences, vivid and emotionally coherent.
           For continuation segments, carry forward the existing emotional and
           sensory state without repeating the full opening breath instruction.
           When a photo year is provided, explicitly weave that year into the
           scene so the listener feels when this memory took place.
           Never say phrases like "the meditation", "this meditation", or
           "now the meditation moves". The listener should feel a continuous
           inner experience, not hear structural commentary.
           Transitions between scenes should feel organic:
           - echo a sensory detail from the previous scene
           - let that detail transform into the next one
           - avoid abrupt reset language
           Each chunk needs:
           - text: The meditation text
           - pause_after_ms: Silence after this chunk (1000-4000ms)

        4. QUALITY VISUALIZATION:
           A short phrase describing the quality moving through the body in this
           segment.

        5. CONTINUITY SUMMARY:
           One or two sentences summarizing the imagery, tone, and emotional arc
           that the next segment should continue from.

        Be evocative, specific, and smoothly connective.
        """
    )


def analyze_image(
    image_base64: str,
    *,
    photo_year: int | str,
    image_index: int,
    total_images: int,
    previous_context: str | None = None,
) -> ImageAnalysisResult:
    logger.info(
        "Sending image %d/%d to GPT-4o for meditation analysis...",
        image_index + 1,
        total_images,
    )

    user_text = (
        "Analyze this image and write the next spoken scene in a stitched sequence.\n\n"
        f"The photo is from the year {photo_year}. Mention that year naturally in "
        "the spoken scene."
    )
    if previous_context:
        user_text = (
            f"{user_text}\n\nContext carried forward from the earlier scenes:\n"
            f"{previous_context}"
        )

    response = get_openai_client().beta.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": build_system_prompt(
                    image_index=image_index,
                    total_images=total_images,
                ),
            },
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
                        "text": user_text,
                    },
                ],
            },
        ],
        response_format=ImageAnalysis,
    )

    analysis = response.choices[0].message.parsed
    return ImageAnalysisResult(
        scene_description=analysis.scene_description,
        sound_effects=analysis.sound_effects,
        meditation_chunks=analysis.meditation_chunks,
        quality_visualization=analysis.quality_visualization,
        continuity_summary=analysis.continuity_summary,
    )


def select_sound_effects(
    analyses: list[ImageAnalysisResult],
    *,
    max_layers: int = 4,
) -> list[SoundEffect]:
    selected: list[SoundEffect] = []
    seen_prompts: set[str] = set()

    for analysis in analyses:
        for effect in analysis.sound_effects:
            normalized_prompt = effect.prompt.strip().lower()
            if normalized_prompt in seen_prompts:
                continue
            seen_prompts.add(normalized_prompt)
            selected.append(effect)
            if len(selected) >= max_layers:
                return selected

    return selected


def analyze_present_moment_closing(
    *,
    current_location: str,
    current_date_time: str,
    user_name: str,
    previous_context: str | None,
) -> list[MeditationChunk]:
    system_prompt = dedent_strip(
        """\
        You are writing the final grounded closing of a guided sequence.

        Create exactly 2 meditation chunks totaling roughly 30 seconds of spoken
        narration. This closing must:
        - bring the listener into the present moment
        - remind them who they are, where they are, and what date and time it is
        - guide them gently through opening their eyes
        - feel like a natural continuation of what came before
        - end with the exact final sentence: "What do you want to do now?"

        Use the provided user name, location, and date/time explicitly.
        Keep the language warm, grounding, and direct.
        Do not say "the meditation" or describe the structure out loud.
        """
    )

    context_lines = [
        f"User name: {user_name}",
        f"Current location: {current_location}",
        f"Current date and time: {current_date_time}",
    ]
    if previous_context:
        context_lines.append(f"Context carried forward so far:\n{previous_context}")

    response = get_openai_client().beta.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": "\n\n".join(context_lines),
            },
        ],
        response_format=PresentMomentClosing,
    )

    closing = response.choices[0].message.parsed
    return closing.meditation_chunks


def analyze_image_sequence(
    photo_inputs: list[dict[str, str | int]],
    *,
    present_moment_context: dict[str, str] | None = None,
) -> ImageSequenceAnalysisResult:
    if not photo_inputs:
        msg = "At least one photo is required"
        raise ValueError(msg)

    analyses: list[ImageAnalysisResult] = []
    previous_context: str | None = None

    for index, photo in enumerate(photo_inputs):
        analysis = analyze_image(
            str(photo["image_base64"]),
            photo_year=photo["year"],
            image_index=index,
            total_images=len(photo_inputs),
            previous_context=previous_context,
        )
        analyses.append(analysis)
        previous_context = build_continuity_context(analysis)

    scene_description = "\n\n".join(
        f"Photo {index + 1} ({photo_inputs[index]['year']}): {analysis.scene_description}"
        for index, analysis in enumerate(analyses)
    )
    meditation_chunks = [
        chunk
        for analysis in analyses
        for chunk in analysis.meditation_chunks
    ]
    quality_visualization = " -> ".join(
        dict.fromkeys(analysis.quality_visualization for analysis in analyses)
    )
    closing_scene_description = ""

    if present_moment_context:
        closing_chunks = analyze_present_moment_closing(
            current_location=present_moment_context["current_location"],
            current_date_time=present_moment_context["current_date_time"],
            user_name=present_moment_context["user_name"],
            previous_context=previous_context,
        )
        meditation_chunks.extend(closing_chunks)
        closing_scene_description = dedent_strip(
            f"""\
            Present-moment grounding: {present_moment_context["user_name"]} is in
            {present_moment_context["current_location"]} on
            {present_moment_context["current_date_time"]}.
            """
        )
        quality_visualization = (
            f"{quality_visualization} -> present awareness"
            if quality_visualization
            else "present awareness"
        )

    combined_scene_description = scene_description
    if closing_scene_description:
        combined_scene_description = (
            f"{scene_description}\n\n{closing_scene_description}"
        )

    return ImageSequenceAnalysisResult(
        scene_description=combined_scene_description,
        sound_effects=select_sound_effects(analyses),
        meditation_chunks=meditation_chunks,
        quality_visualization=quality_visualization,
    )
