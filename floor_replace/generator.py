import os
import mimetypes
from typing import List, Optional, Tuple

from google import genai
from google.genai import types


# Keep this file focused and < 200 lines; single responsibility: programmatic generation

INSTRUCTION_TEXT = """SYSTEM — UNIVERSAL FLOOR REPLACEMENT (Room → Target Floor)

GOAL
Replace ONLY the pixels inside FLOOR_MASK in ROOM_IMAGE with the TARGET_FLOOR product so the final image is seamless, photorealistic, and physically consistent with the original scene.

INPUTS
- ROOM_IMAGE: the original interior photo.
- FLOOR_MASK: binary mask; 1 = floor region to replace, 0 = everything else. The edit scope is strictly limited to this mask.
- REFERENCE_IMAGES: one or more target floor references (e.g., swatch, product close-ups, installed photos).
- PRODUCT_METADATA (optional JSON): may include { pattern, plank_width_mm, tile_size_mm, gloss_level, color_tags, grain_direction_hint, bevel/grout width, orientation_deg, tone/warmth notes }.

EDIT SCOPE (STRICT)
- Modify ONLY pixels where FLOOR_MASK=1; no changes outside the mask (walls, skirting/trim, furniture, rugs, reflections on non-floor surfaces, etc.).
- Preserve all occlusions: objects that overlap the floor remain unchanged above the new floor.
- Edges at skirting/thresholds must be clean, without halos, bleeding, or misalignment.

Replace ONLY the masked floor in this room with the provided reference floor.
Do not introduce new colours, patterns, or furniture.
Ensure the floor looks natural, seamless, and photorealistic.
COLOUR FIDELITY (HIGHEST PRIORITY — STRICT)
MATCH the product COLOUR from REFERENCE_IMAGE_1 EXACTLY (hue, saturation, brightness, warmth).
Do NOT lighten, darken, or shift towards red/yellow unless present in the reference.
Preserve room lighting/shadows by overlaying them on the CORRECT reference colour.
Do NOT change white balance or colours outside the mask.
OUTPUT REQUIREMENTS
Replace ONLY the floor region with straight planks at true scale.
Preserve original lighting, shadows, reflections and all occlusions from furniture/objects.
Keep walls, skirting and all non-floor elements identical and sharp.
Produce a seamless, photorealistic floor with natural joints and subtle bevels; avoid tiling artefacts.
FAILURE MODES TO AVOID
Do NOT edit outside the masked region.
Do NOT introduce chevron/herringbone/panel patterns.
Do NOT alter global colour/contrast of the room.
Do NOT miniaturise or overscale planks relative to true scale.
"""


def _part_from_bytes(data: bytes, mime_type: str) -> types.Part:
    return types.Part.from_bytes(mime_type=mime_type, data=data)


def _guess_mime(path: str) -> str:
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


class FloorReplaceGenerator:
    """
    High-level wrapper around Gemini image generation for floor replacement.
    USED BY: streamlit UI `app.py` | DEPENDS ON: google-genai client, GEMINI_API_KEY

    Parameters are conservative for colour fidelity; adjust in UI.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-2.5-flash-image-preview",
        temperature: float = 0.1,
        top_p: float = 0.5,
        seed: Optional[int] = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY not set and no api_key provided.")
        self.client = genai.Client(api_key=self.api_key)
        self.model_name = model_name
        self.temperature = temperature
        self.top_p = top_p
        self.seed = seed

    def generate_single_ref(
        self,
        room_bytes: bytes,
        room_mime: str,
        reference_bytes: bytes,
        reference_mime: str,
        mask_bytes: Optional[bytes] = None,
        mask_mime: Optional[str] = None,
        instruction_text: str = INSTRUCTION_TEXT,
    ) -> List[Tuple[str, bytes]]:
        """
        Generate edited image(s) replacing the floor using one reference image.
        RETURNS: list of (mime_type, data) results; may include multiple images from stream.
        """
        parts: List[types.Part] = []
        # Explicitly tag parts to align with prompt references
        parts.append(types.Part.from_text(text="BASE_IMAGE"))
        parts.append(_part_from_bytes(room_bytes, room_mime))
        if mask_bytes and mask_mime:
            parts.append(types.Part.from_text(text="MASK_IMAGE"))
            parts.append(_part_from_bytes(mask_bytes, mask_mime))
        parts.append(types.Part.from_text(text="REFERENCE_IMAGE_1"))
        parts.append(_part_from_bytes(reference_bytes, reference_mime))
        parts.append(types.Part.from_text(text=instruction_text))

        contents = [types.Content(role="user", parts=parts)]
        config = types.GenerateContentConfig(
            temperature=self.temperature,
            top_p=self.top_p,
            response_modalities=["IMAGE", "TEXT"],
            seed=self.seed,
        )

        outputs: List[Tuple[str, bytes]] = []
        for chunk in self.client.models.generate_content_stream(
            model=self.model_name, contents=contents, config=config
        ):
            if (
                getattr(chunk, "candidates", None)
                and chunk.candidates[0].content
                and chunk.candidates[0].content.parts
            ):
                for part in chunk.candidates[0].content.parts:
                    if getattr(part, "inline_data", None) and part.inline_data.data:
                        outputs.append((part.inline_data.mime_type, part.inline_data.data))
        return outputs

    def generate_two_refs(
        self,
        room_bytes: bytes,
        room_mime: str,
        ref1_bytes: bytes,
        ref1_mime: str,
        ref2_bytes: bytes,
        ref2_mime: str,
        mask_bytes: Optional[bytes] = None,
        mask_mime: Optional[str] = None,
        instruction_text: str = INSTRUCTION_TEXT,
        seed: Optional[int] = 12345,
    ) -> List[Tuple[str, bytes]]:
        """
        Variant using two reference images for stronger colour guidance.
        RETURNS: list of (mime_type, data) results.
        """
        parts: List[types.Part] = []
        parts.append(types.Part.from_text(text="BASE_IMAGE"))
        parts.append(_part_from_bytes(room_bytes, room_mime))
        if mask_bytes and mask_mime:
            parts.append(types.Part.from_text(text="MASK_IMAGE"))
            parts.append(_part_from_bytes(mask_bytes, mask_mime))
        parts.append(types.Part.from_text(text="REFERENCE_IMAGE_1"))
        parts.append(_part_from_bytes(ref1_bytes, ref1_mime))
        parts.append(types.Part.from_text(text="REFERENCE_IMAGE_2"))
        parts.append(_part_from_bytes(ref2_bytes, ref2_mime))
        parts.append(types.Part.from_text(text=instruction_text))

        contents = [types.Content(role="user", parts=parts)]
        config = types.GenerateContentConfig(
            temperature=self.temperature,
            top_p=self.top_p,
            response_modalities=["IMAGE", "TEXT"],
            seed=seed,
        )

        outputs: List[Tuple[str, bytes]] = []
        for chunk in self.client.models.generate_content_stream(
            model=self.model_name, contents=contents, config=config
        ):
            if (
                getattr(chunk, "candidates", None)
                and chunk.candidates[0].content
                and chunk.candidates[0].content.parts
            ):
                for part in chunk.candidates[0].content.parts:
                    if getattr(part, "inline_data", None) and part.inline_data.data:
                        outputs.append((part.inline_data.mime_type, part.inline_data.data))
        return outputs


