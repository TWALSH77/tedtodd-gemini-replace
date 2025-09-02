import os
import sys
import mimetypes
from pathlib import Path
from google import genai
from google.genai import types

MODEL_NAME = "gemini-2.5-flash-image-preview"
OUT_PREFIX = "output_"
TEMP = 0.1
TOP_P = 0.1
SEED = 12345  # for reproducibility

# ---------- PROMPT (high-quality, deterministic) ----------
INSTRUCTION_TEXT = """
You are performing a precise floor replacement edit.
You are performing a precise floor replacement edit.

# INPUT ROLES
- BASE_IMAGE: the room photo (keep everything outside the mask unchanged).
- MASK_IMAGE: if present, a binary mask of the floor region (edit ONLY inside this).
- REFERENCE_IMAGE_1 and REFERENCE_IMAGE_2: the same product under different lighting; they are the SOLE SOURCE of truth for grain, texture, and especially COLOUR.
- (Optional) COLOR_SWATCH: if provided, match this EXACTLY.

# PRODUCT (ANTIQUE collection — STRAIGHT PLANK)
- Species: Antique French Oak
- Finish: Naked Skin Lacquer Super Matt
- Texture: Hand-polished undulations, original patina
- Edge detail: Hand-rolled edges
- Grade: Genuine antique sourced
- Construction: 2-ply engineered
- Certification: UKTR
- Layout: STRAIGHT PLANK (no chevron/herringbone/panels)
- Board width: realistic within product spec (100–170 mm or 180–240 mm). KEEP TRUE SCALE across the floor plane.
- Board length: random lengths within spec (0.6–3 m). Stagger naturally.

# COLOUR REQUIREMENTS (STRICT — HIGHEST PRIORITY)
- REPRODUCE THE COLOUR EXACTLY from REFERENCE_IMAGE_1/2.  
- This means hue, saturation, brightness, and warmth must MATCH the references.  
- Do NOT shift towards lighter, darker, redder, or yellower tones.  
- Do NOT adapt the colour to “fit” room lighting; preserve original tone from references.  
- If in doubt, PRIORITISE REFERENCE COLOUR over room context.  
- Colour fidelity is more important than grain variation or lighting adaptation.

# OUTPUT REQUIREMENTS
1. Replace ONLY the masked floor with Antique French Oak straight planks at true scale.
2. Respect reference COLOUR exactly, even if it looks slightly different from the room’s lighting.
3. Preserve all original lighting effects (shadows/reflections) but OVERLAY them on the correct reference colour.
4. Maintain natural joints, bevels, and random staggering; no tiling artefacts.
5. Keep furniture, walls, and everything outside the mask identical and sharp.

# FAILURE MODES TO AVOID
- Do NOT adjust colour balance to “blend in.” The floor must keep the exact medium antique oak tone of the references.
- Do NOT brighten, wash out, or desaturate the floor.  
- Do NOT alter non-floor colours (walls, furniture).  
- Do NOT change pattern: straight planks ONLY.
""".strip()
# ---------------------------------------------------------

def part_from_path(path_str: str):
    p = Path(path_str).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
    with open(p, "rb") as f:
        data = f.read()
    return types.Part.from_bytes(mime_type=mime, data=data)

def save_inline_part(idx: int, part) -> bool:
    if getattr(part, "inline_data", None) and part.inline_data.data:
        ext = mimetypes.guess_extension(part.inline_data.mime_type) or ".bin"
        out_path = f"{OUT_PREFIX}{idx}{ext}"
        with open(out_path, "wb") as f:
            f.write(part.inline_data.data)
        print(f"Saved: {out_path}")
        return True
    return False

def main():
    # Args:
    # 1 = room_path
    # 2 = reference_floor_path_1
    # 3 = reference_floor_path_2
    # 4 = [optional mask_path]
    if "GEMINI_API_KEY" not in os.environ:
        print("Error: GEMINI_API_KEY env var not set.")
        sys.exit(1)

    if len(sys.argv) < 4:
        print("Usage:")
        print("  python run_floor_replace_two_refs.py <room_path> <ref1_path> <ref2_path> [optional_mask_path]")
        sys.exit(1)

    room_path = sys.argv[1]
    ref1_path = sys.argv[2]
    ref2_path = sys.argv[3]
    mask_path = sys.argv[4] if len(sys.argv) >= 5 else None

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    parts = []

    # Tag + base image
    parts.append(types.Part.from_text(text="BASE_IMAGE"))
    parts.append(part_from_path(room_path))

    # Optional mask
    if mask_path:
        parts.append(types.Part.from_text(text="MASK_IMAGE"))
        parts.append(part_from_path(mask_path))

    # Two references with explicit tags
    parts.append(types.Part.from_text(text="REFERENCE_IMAGE_1"))
    parts.append(part_from_path(ref1_path))
    parts.append(types.Part.from_text(text="REFERENCE_IMAGE_2"))
    parts.append(part_from_path(ref2_path))

    # Instruction last
    parts.append(types.Part.from_text(text=INSTRUCTION_TEXT))

    contents = [types.Content(role="user", parts=parts)]

    config = types.GenerateContentConfig(
        temperature=TEMP,
        top_p=TOP_P,
        response_modalities=["IMAGE", "TEXT"],
        seed=SEED,
    )

    file_index = 0
    for chunk in client.models.generate_content_stream(
        model=MODEL_NAME, contents=contents, config=config
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
                    print(part.text)

    if file_index == 0:
        print("No image returned. Check inputs and prompt/parameters.")

if __name__ == "__main__":
    main()
