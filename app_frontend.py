import os
from io import BytesIO
from pathlib import Path
from typing import List, Tuple
import random

import requests
import streamlit as st
from PIL import Image
Image.MAX_IMAGE_PIXELS = 300_000_000  # Avoid PIL DecompressionBombWarning for large refs
import hashlib

from google.genai import types
from floor_replace.generator import FloorReplaceGenerator, _guess_mime, INSTRUCTION_TEXT
from floor_replace.image_utils import normalize_image_bytes


# Public S3 bucket hosting product images
S3_BUCKET = os.environ.get("S3_BUCKET", "tedtodd-karta-images")
S3_PREFIX = os.environ.get("S3_PREFIX", "")  # optional folder prefix within the bucket
S3_REGION = os.environ.get("S3_REGION", "us-east-2")

# Gemini API key is read from Streamlit Secrets or environment (no hardcoding)


DEFAULT_PRODUCT_FILES = [
    "Apian.jpg","Bowen.jpg","Bradshaw.jpg","Colton.jpg","Faden.jpg","Kozler.jpg",
    "Magnus.jpg","Miller.jpg","Mitchell.jpg","Newman.jpg","Nolin.jpg","Pearsall.jpg",
    "Robinson.jpg","Sanborn.jpg","Sanson.jpg","Saxton.jpg","Shepherd.jpg","Shumate.jpg",
    "Spence.jpg","Wyld.jpg"
]


def _s3_key_for(filename: str) -> str:
    prefix = (S3_PREFIX.strip("/") + "/") if S3_PREFIX and not S3_PREFIX.endswith("/") else S3_PREFIX
    return f"{prefix}{filename}" if prefix else filename


def s3_object_url(filename: str) -> str:
    key = _s3_key_for(filename)
    # Public regional URL (requires bucket/object to be public)
    return f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{key}"


@st.cache_data(show_spinner=False)
def list_products() -> List[str]:
    # For Cloud, list statically unless you add boto3 listing with credentials
    return DEFAULT_PRODUCT_FILES


@st.cache_data(show_spinner=False)
def fetch_image_bytes(url: str) -> bytes:
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.content


@st.cache_data(show_spinner=False)
def make_thumbnail_bytes_from_url(url: str, max_size: int = 256) -> bytes:
    try:
        data = fetch_image_bytes(url)
        with Image.open(BytesIO(data)) as im:
            im = im.convert("RGB")
            im.thumbnail((max_size, max_size))
            buffer = BytesIO()
            im.save(buffer, format="JPEG", quality=85)
            return buffer.getvalue()
    except Exception:
        # Return a tiny gray placeholder on fetch failure
        im = Image.new("RGB", (max_size, max_size), color=(200, 200, 200))
        buffer = BytesIO()
        im.save(buffer, format="JPEG", quality=70)
        return buffer.getvalue()


def render_gallery(products: List[str], selected: str | None) -> str | None:
    st.subheader("Choose a floor product")
    q = st.text_input("Search by name", value="", placeholder="Type to filter...")
    items = products
    if q:
        filtered = [name for name in items if q.lower() in name.lower()]
    else:
        filtered = items

    if not filtered:
        st.info("No matches. Try a different search.")
        return selected

    # Grid layout (no pagination)
    cols_per_row = 5
    rows = (len(filtered) + cols_per_row - 1) // cols_per_row
    new_selected = selected

    for r in range(rows):
        cols = st.columns(cols_per_row)
        for c in range(cols_per_row):
            idx = r * cols_per_row + c
            if idx >= len(filtered):
                continue
            name = filtered[idx]
            url = s3_object_url(name)
            thumb = make_thumbnail_bytes_from_url(url)
            with cols[c]:
                st.image(thumb, caption=None, use_container_width=True)
                is_current = selected is not None and name == selected
                label = f"✅ {name}" if is_current else name
                st.caption(label)
                disabled = is_current
                if st.button("Selected" if is_current else "Select", key=f"sel_{name}", disabled=disabled, use_container_width=True):
                    new_selected = name

    return new_selected


def main():
    st.set_page_config(page_title="TedTodd MVP", layout="wide")
    st.title("TedTodd Floor Replace - MVP")
    st.caption("Streamlit-only app (calls Gemini directly)")

    # Simple password gate (secrets > env > default)
    expected_password = None
    try:
        expected_password = st.secrets.get("app", {}).get("password")  # type: ignore[attr-defined]
    except Exception:
        expected_password = os.environ.get("APP_PASSWORD")
    if not expected_password:
        expected_password = "tedtoddswap"

    if "authed" not in st.session_state:
        st.session_state["authed"] = False

    if not st.session_state["authed"]:
        with st.form("login", clear_on_submit=False):
            pw = st.text_input("Password", type="password")
            submit = st.form_submit_button("Enter")
        if submit:
            if pw == expected_password:
                st.session_state["authed"] = True
                st.rerun()
            else:
                st.error("Incorrect password")
        st.stop()

    # Key helper and check
    def _get_api_key() -> str | None:
        # Prefer Streamlit Cloud secrets, then environment
        try:
            v = st.secrets.get("gcp", {}).get("gemini_api_key")  # type: ignore[attr-defined]
            if v:
                return v
        except Exception:
            pass
        return os.environ.get("GEMINI_API_KEY")

    api_key = _get_api_key()
    if not api_key:
        st.warning("GEMINI_API_KEY missing. Set in Secrets or hardcode in app_frontend.py.")

    # Load products from S3 and render gallery
    refs = list_products()
    if not refs:
        st.error("No products found")
        return

    selected_name = st.session_state.get("selected_name") if st.session_state.get("selected_name") else None
    selected_name = render_gallery(refs, selected_name)
    if selected_name:
        st.session_state["selected_name"] = selected_name

    # Show selected reference preview (no byte fetch to avoid 403s on public buckets)
    if "selected_name" in st.session_state:
        st.markdown("---")
        st.subheader("Selected reference")
        url = s3_object_url(st.session_state["selected_name"])
        st.image(url, caption=st.session_state["selected_name"])
        st.caption(url)

    st.sidebar.header("Product Prompt (optional)")
    product_prompt = st.sidebar.text_area(
        "Hints (e.g., 'Light natural oak, 200mm plank width, matte finish')",
        value="",
        height=120,
    )

    st.header("Upload Room Image")
    room = st.file_uploader("Room photo", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=False)
    if room:
        st.image(room.getvalue(), caption="Room input")

    # Local multi-ref generate using FloorReplaceGenerator
    def _generate_multi(generator: FloorReplaceGenerator,
                        room_bytes: bytes, room_mime: str,
                        references: List[Tuple[bytes, str]],
                        instruction_text: str,
                        seed: int | None) -> List[Tuple[str, bytes]]:
        parts: List[types.Part] = []
        parts.append(types.Part.from_text(text="BASE_IMAGE"))
        parts.append(types.Part.from_bytes(mime_type=room_mime, data=room_bytes))
        for idx, (rb, rm) in enumerate(references, start=1):
            parts.append(types.Part.from_text(text=f"REFERENCE_IMAGE_{idx}"))
            parts.append(types.Part.from_bytes(mime_type=rm, data=rb))
        parts.append(types.Part.from_text(text=instruction_text))

        contents = [types.Content(role="user", parts=parts)]
        config = types.GenerateContentConfig(
            temperature=generator.temperature,
            top_p=generator.top_p,
            response_modalities=["IMAGE", "TEXT"],
            seed=seed if seed is not None else generator.seed,
        )

        outputs: List[Tuple[str, bytes]] = []
        for chunk in generator.client.models.generate_content_stream(
            model=generator.model_name, contents=contents, config=config
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

    # Controls for fidelity
    st.sidebar.subheader("Quality controls")
    ui_temp = st.sidebar.slider("Temperature", 0.0, 1.0, 0.0, 0.05)
    ui_top_p = st.sidebar.slider("Top-p", 0.0, 1.0, 0.1, 0.05)
    ui_seed = st.sidebar.number_input("Seed", value=12345, step=1)

    st.sidebar.subheader("Optional second reference")
    ref2_input = st.sidebar.text_input(
        "Absolute path to reference2 (optional)",
        value="",
        help="For your Shepherd test: /Users/tedwalsh/Desktop/research_2025_summer/tedtodd-nana-bananna/tedtodd-photo-roomshots/Shepherd_room.png",
    )

    # Generate button (manual selection)
    if st.button("Generate", disabled=(room is None or "selected_name" not in st.session_state)):
        if not room or "selected_name" not in st.session_state:
            st.warning("Please select a reference and upload a room image.")
        else:
            with st.spinner("Generating..."):
                try:
                    # Prepare generator
                    gen = FloorReplaceGenerator(
                        api_key=api_key,
                        model_name="gemini-2.5-flash-image-preview",
                        temperature=ui_temp,
                        top_p=ui_top_p,
                        seed=int(ui_seed),
                    )

                    # Room normalization
                    room_bytes = room.getvalue()
                    room_bytes, room_mime, room_size = normalize_image_bytes(room_bytes, target_long_side=3000, out_format="JPEG")

                    # Primary product bytes from S3
                    name = st.session_state["selected_name"]
                    primary_url = s3_object_url(name)
                    primary_raw = fetch_image_bytes(primary_url)
                    primary_bytes, primary_mime, _ = normalize_image_bytes(primary_raw, target_long_side=3000, out_format="JPEG")

                    # On-the-fly texture crops from the primary image
                    with Image.open(BytesIO(primary_raw)) as im:
                        im = im.convert("RGB")
                        W, H = im.size
                        # center 512
                        s = 512
                        cx, cy = W // 2, H // 2
                        half = s // 2
                        crop1 = im.crop((max(0, cx - half), max(0, cy - half), min(W, cx + half), min(H, cy + half)))
                        b1 = BytesIO(); crop1.save(b1, format="JPEG", quality=92)
                        crop1_bytes = b1.getvalue()
                        # grid 0,0 crop
                        grid_w, grid_h = W // 2, H // 2
                        size = min(grid_w, grid_h, 1500)
                        crop2 = im.crop((0, 0, size, size))
                        b2 = BytesIO(); crop2.save(b2, format="JPEG", quality=92)
                        crop2_bytes = b2.getvalue()
                    references = [
                        (primary_bytes, primary_mime),
                        (crop1_bytes, "image/jpeg"),
                        (crop2_bytes, "image/jpeg"),
                    ]

                    # Instruction text (append optional product prompt)
                    instruction_text = INSTRUCTION_TEXT
                    if product_prompt.strip():
                        instruction_text = f"{INSTRUCTION_TEXT}\n\n# PRODUCT HINTS\n{product_prompt.strip()}"

                    outputs = _generate_multi(gen, room_bytes, room_mime, references, instruction_text, int(ui_seed))
                except Exception as e:
                    st.error(f"Request failed: {e}")
                    return
                if not outputs:
                    st.warning("No outputs returned")
                    return
                with st.expander("Call details (debug)", expanded=False):
                    st.json({
                        "primary": name,
                        "references_used": [name, "center_512 (generated)", "grid_0_0 (generated)"],
                        "temperature": ui_temp,
                        "top_p": ui_top_p,
                        "seed": int(ui_seed),
                    })
                for idx, (mime, data) in enumerate(outputs):
                    st.image(data, caption=f"Output {idx}")

    st.divider()
    st.subheader("Remix mode")
    st.caption("Upload once, then try random floors on the same photo.")

    # Cache uploaded room for remixing
    if room:
        st.session_state["_room_cached_name"] = room.name
        st.session_state["_room_cached_type"] = room.type
        st.session_state["_room_cached_bytes"] = room.getvalue()

    # Initialize remix state
    if "remix_used" not in st.session_state:
        st.session_state["remix_used"] = []
    if "remix_outputs" not in st.session_state:
        st.session_state["remix_outputs"] = []

    def _pick_random_unused(all_names: List[str]) -> str | None:
        used_names = set(st.session_state["remix_used"])  # type: ignore
        candidates = [n for n in all_names if n not in used_names]
        if not candidates:
            return None
        return random.choice(candidates)

    colA, colB = st.columns([1,1])
    with colA:
        auto_label = "Try random floor" if not st.session_state["remix_used"] else "Remix"
        run_remix = st.button(auto_label, disabled=("_room_cached_bytes" not in st.session_state))
    with colB:
        reset = st.button("Reset remix")

    if reset:
        st.session_state["remix_used"] = []
        st.session_state["remix_outputs"] = []

    if run_remix and "_room_cached_bytes" in st.session_state:
        # Build an UploadFile-like shim for cached bytes
        class _Shim:
            def __init__(self, name: str, typ: str, data: bytes):
                self.name = name
                self.type = typ
                self._data = data

            def getvalue(self):
                return self._data

        shim = _Shim(
            st.session_state["_room_cached_name"],
            st.session_state["_room_cached_type"],
            st.session_state["_room_cached_bytes"],
        )
        ref_name = _pick_random_unused(refs)
        if not ref_name:
            st.info("No more unique floors to try. Click Reset remix to start over.")
        else:
            with st.spinner(f"Remixing with {ref_name}..."):
                try:
                    gen = FloorReplaceGenerator(
                        api_key=api_key,
                        model_name="gemini-2.5-flash-image-preview",
                        temperature=ui_temp,
                        top_p=ui_top_p,
                        seed=int(ui_seed),
                    )
                    room_bytes = st.session_state["_room_cached_bytes"]
                    room_bytes, room_mime, _ = normalize_image_bytes(room_bytes, target_long_side=3000, out_format="JPEG")
                    primary_raw = fetch_image_bytes(s3_object_url(ref_name))
                    primary_bytes, primary_mime, _ = normalize_image_bytes(primary_raw, target_long_side=3000, out_format="JPEG")
                    with Image.open(BytesIO(primary_raw)) as im:
                        im = im.convert("RGB")
                        W, H = im.size
                        s = 512
                        cx, cy = W // 2, H // 2
                        half = s // 2
                        crop1 = im.crop((max(0, cx - half), max(0, cy - half), min(W, cx + half), min(H, cy + half)))
                        b1 = BytesIO(); crop1.save(b1, format="JPEG", quality=92)
                        crop1_bytes = b1.getvalue()
                        grid_w, grid_h = W // 2, H // 2
                        size = min(grid_w, grid_h, 1500)
                        crop2 = im.crop((0, 0, size, size))
                        b2 = BytesIO(); crop2.save(b2, format="JPEG", quality=92)
                        crop2_bytes = b2.getvalue()
                    references = [
                        (primary_bytes, primary_mime),
                        (crop1_bytes, "image/jpeg"),
                        (crop2_bytes, "image/jpeg"),
                    ]
                    instruction_text = INSTRUCTION_TEXT
                    if product_prompt.strip():
                        instruction_text = f"{INSTRUCTION_TEXT}\n\n# PRODUCT HINTS\n{product_prompt.strip()}"
                    outputs = _generate_multi(gen, room_bytes, room_mime, references, instruction_text, int(ui_seed))
                except Exception as e:
                    st.error(f"Remix failed: {e}")
                if outputs:
                    st.session_state["remix_used"].append(ref_name)
                    for idx, (mime, data) in enumerate(outputs):
                        st.session_state["remix_outputs"].append((ref_name, data))

    if st.session_state["remix_outputs"]:
        st.markdown("---")
        st.subheader("Remix results")
        for ref_name, data in st.session_state["remix_outputs"]:
            st.image(data, caption=f"{ref_name}")


if __name__ == "__main__":
    main()


