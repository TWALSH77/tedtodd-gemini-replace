import os
import mimetypes
from typing import List, Optional, Tuple

from google import genai
from google.genai import types


# Keep this file focused and < 200 lines; single responsibility: programmatic generation

INSTRUCTION_TEXT = """{
  "task": "universal_wood_floor_replacement",
  "goal": "Do not generate a new floor. Take the REFERENCE_IMAGE exactly as provided and project it into the FLOOR_MASK region of the ROOM_IMAGE. The only valid action is to map/tile/warp this exact image so it fits the room’s perspective, scale, and lighting. Nothing else is allowed.",
  "inputs": {
    "room_image": "original interior photo",
    "floor_mask": "binary mask (1 = floor region to replace, 0 = everything else)",
    "reference_image": "high-quality scan of the wooden floor (this IS the floor to apply, not inspiration)",
    "product_metadata": {
      "optional": 
      "examples": {
        "plank_width_mm":
        "tile_size_mm":
        "gloss_level": "
        "tone": "warm ",
        "grain_direction_hint": 
        "orientation_deg": 0
      }
    }
  },
  "rules": {
    "fundamental": [
      "Do NOT invent, generate, or hallucinate any floor texture.",
      "The REFERENCE_IMAGE must be used directly — no substitutes, no approximations.",
      "Apply only geometric and photometric adjustments (warp, tile, scale, blend for lighting)."
    ],
    "strict_scope": [
      "Modify ONLY pixels where FLOOR_MASK = 1.",
      "Do not touch walls, skirting, furniture, rugs, reflections, or any non-floor surfaces.",
      "Preserve occlusions: objects above the floor remain unchanged on top of the new surface.",
      "Edges at skirting/thresholds must be sharp, aligned, and free of halos or bleed."
    ],
    "colour_texture_fidelity": [
      "Colours, tone, grain, and texture must match the REFERENCE_IMAGE exactly (1:1).",
      "No colour shifts (hue, saturation, brightness, warmth) unless present in the reference.",
      "No invented grain, plank lines, or surface details.",
      "Overlay and preserve natural room lighting/shadows from the ROOM_IMAGE onto the new floor.",
      "Do not alter global white balance or colours outside the mask."
    ]
  },
  "output": {
    "appearance": "The REFERENCE_IMAGE appears as the installed floor in the room.",
    "quality": "Seamless, natural, photorealistic result that looks physically consistent with the scene.",
    "operations": [
      "Tile or repeat REFERENCE_IMAGE only as needed to cover the masked area.",
      "Warp and align to correct room perspective and geometry.",
      "Scale floor features according to product_metadata (if provided).",
      "Blend room lighting and shadows realistically onto the new floor.",
      "Preserve reflections and occlusions from ROOM_IMAGE."
    ]
  },
  "failure_modes": [
    "❌ Do not generate or invent wood textures.",
    "❌ Do not approximate the reference — the REFERENCE_IMAGE itself must be used.",
    "❌ Do not alter or distort colours, contrast, or brightness of the reference.",
    "❌ Do not change plank layout, pattern, or style beyond what exists in the reference.",
    "❌ Do not overscale or underscale the texture unrealistically.",
    "❌ Do not edit any pixels outside the FLOOR_MASK region.",
    "❌ Do not change global image balance, colour, or exposure."
  ]
}



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


