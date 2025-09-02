import os
import sys
import mimetypes
from pathlib import Path
from google import genai
from google.genai import types

# ------------- CONFIG YOU CAN EDIT QUICKLY -------------
MODEL_NAME = "gemini-2.5-flash-image-preview"
OUT_PREFIX = "output_"
TEMP = 0.1
TOP_P = 0.5
# -------------------------------------------------------

INSTRUCTION_TEXT = """Replace ONLY the masked floor in this room with the provided reference floor.

Do not introduce new colours, patterns, or furniture.
Ensure the floor looks natural, seamless, and photorealistic.

 PRODUCT (STRAIGHT PLANK — SUPERWIDE / European Oak)
- Species: European Oak
- Finish: Burnished Hardwax Oil Matt
- Surface: Brushed
- Edge: Beveled Edges
- Layout for this render: STRAIGHT PLANK (no chevron/herringbone/panels)
- Board width: use a realistic value from the spec ranges; KEEP TRUE SCALE across the floor plane.
- Board length: random lengths within the spec; stagger end joints naturally.

# COLOUR FIDELITY (HIGHEST PRIORITY — STRICT)
- MATCH the product COLOUR from REFERENCE_IMAGE_1 EXACTLY (hue, saturation, brightness, warmth).
- Do NOT lighten, darken, or shift towards red/yellow unless present in the reference.
- Preserve room lighting/shadows by overlaying them on the CORRECT reference colour.
- Do NOT change white balance or colours outside the mask.

# OUTPUT REQUIREMENTS
1) Replace ONLY the floor region with straight planks at true scale.
2) Preserve original lighting, shadows, reflections and all occlusions from furniture/objects.
3) Keep walls, skirting and all non-floor elements identical and sharp.
4) Produce a seamless, photorealistic floor with natural joints and subtle bevels; avoid tiling artefacts.

# FAILURE MODES TO AVOID
- Do NOT edit outside the masked region.
- Do NOT introduce chevron/herringbone/panel patterns.
- Do NOT alter global colour/contrast of the room.
- Do NOT miniaturise or overscale planks relative to true scale.
"""

def part_from_path(path_str: str):
    """Load a local file as a genai Part.from_bytes"""
    p = Path(path_str).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
    with open(p, "rb") as f:
        data = f.read()
    return types.Part.from_bytes(mime_type=mime, data=data)

def save_inline_part(index: int, part):
    """Save the first inline image/text part from a streamed chunk."""
    if getattr(part, "inline_data", None) and part.inline_data.data:
        ext = mimetypes.guess_extension(part.inline_data.mime_type) or ".bin"
        out_path = f"{OUT_PREFIX}{index}{ext}"
        with open(out_path, "wb") as f:
            f.write(part.inline_data.data)
        print(f"Saved: {out_path}")
        return True
    return False

def main():
    if "GEMINI_API_KEY" not in os.environ:
        print("Error: GEMINI_API_KEY env var not set.")
        sys.exit(1)

    if len(sys.argv) < 3:
        print("Usage:")
        print("  python run_floor_replace.py <room_path> <reference_floor_path> [optional_mask_path]")
        sys.exit(1)

    room_path = sys.argv[1]
    reference_path = sys.argv[2]
    mask_path = sys.argv[3] if len(sys.argv) >= 4 else None

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    # Build the content parts (order matters: base image, optional mask, reference image, then instruction text)
    parts = []
    parts.append(part_from_path(room_path))

    if mask_path:
        parts.append(part_from_path(mask_path))

    parts.append(part_from_path(reference_path))
    parts.append(types.Part.from_text(text=INSTRUCTION_TEXT))

    contents = [
        types.Content(
            role="user",
            parts=parts
        )
    ]

    config = types.GenerateContentConfig(
        temperature=TEMP,
        top_p=TOP_P,
        response_modalities=["IMAGE", "TEXT"],
    )

    file_index = 0
    # Stream the response so we catch images as they arrive
    for chunk in client.models.generate_content_stream(
        model=MODEL_NAME,
        contents=contents,
        config=config,
    ):
        if (
            chunk.candidates
            and chunk.candidates[0].content
            and chunk.candidates[0].content.parts
        ):
            for part in chunk.candidates[0].content.parts:
                if save_inline_part(file_index, part):
                    file_index += 1
                elif getattr(part, "text", None):
                    # The model may also emit some text status; print it.
                    print(part.text)

    if file_index == 0:
        print("No image returned by the model (check inputs and prompt).")

if __name__ == "__main__":
    main()
