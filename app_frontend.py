import os
from io import BytesIO
from pathlib import Path
from typing import List
import random

import requests
import streamlit as st
from PIL import Image
Image.MAX_IMAGE_PIXELS = 300_000_000  # Avoid PIL DecompressionBombWarning for large refs
import hashlib


API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")
PHOTO_BANK_DIR = Path(
    "/Users/tedwalsh/Desktop/research_2025_summer/tedtodd-nana-bananna/tedtodd-photo-bank"
)


@st.cache_data(show_spinner=False)
def list_reference_images(folder: Path) -> List[Path]:
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    return [p for p in sorted(folder.glob("*")) if p.suffix.lower() in exts]


@st.cache_data(show_spinner=False)
def make_thumbnail_bytes(path: Path, max_size: int = 256) -> bytes:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((max_size, max_size))
        buffer = BytesIO()
        im.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()


def render_gallery(paths: List[Path], selected: Path | None) -> Path | None:
    st.subheader("Choose a floor product")
    q = st.text_input("Search by name", value="", placeholder="Type to filter...")
    if q:
        filtered = [p for p in paths if q.lower() in p.name.lower()]
    else:
        filtered = paths

    if not filtered:
        st.info("No matches. Try a different search.")
        return selected

    # Grid layout
    cols_per_row = 5
    rows = (len(filtered) + cols_per_row - 1) // cols_per_row
    new_selected = selected

    for r in range(rows):
        cols = st.columns(cols_per_row)
        for c in range(cols_per_row):
            idx = r * cols_per_row + c
            if idx >= len(filtered):
                continue
            ref = filtered[idx]
            thumb = make_thumbnail_bytes(ref)
            with cols[c]:
                st.image(thumb, caption=None, use_column_width=True)
                is_current = selected is not None and ref == selected
                label = f"✅ {ref.name}" if is_current else ref.name
                st.caption(label)
                disabled = is_current
                if st.button("Selected" if is_current else "Select", key=f"sel_{ref.name}", disabled=disabled, use_container_width=True):
                    new_selected = ref

    return new_selected


def main():
    st.set_page_config(page_title="TedTodd MVP", layout="wide")
    st.title("TedTodd Floor Replace - MVP")
    st.caption("Streamlit frontend calling FastAPI backend")

    # Health check
    try:
        r = requests.get(f"{API_BASE}/api/health", timeout=5)
        if r.ok:
            st.success("API healthy")
        else:
            st.warning(f"API health check failed: {r.status_code}")
    except Exception as e:
        st.error(f"API not reachable at {API_BASE}: {e}")

    # Load refs and render gallery
    refs = list_reference_images(PHOTO_BANK_DIR)
    if not refs:
        st.error(f"No refs found in {PHOTO_BANK_DIR}")
        return

    selected_ref_path = Path(st.session_state.get("selected_ref_path")) if st.session_state.get("selected_ref_path") else None
    selected_ref_path = render_gallery(refs, selected_ref_path)
    if selected_ref_path:
        st.session_state["selected_ref_path"] = str(selected_ref_path)

    # Show selected reference preview and details for verification
    if "selected_ref_path" in st.session_state:
        sel_path = Path(st.session_state["selected_ref_path"]) 
        st.markdown("---")
        st.subheader("Selected reference")
        try:
            st.image(str(sel_path), caption=sel_path.name)
            with open(sel_path, "rb") as _rf:
                sel_bytes = _rf.read()
            sel_sha = hashlib.sha256(sel_bytes).hexdigest()
            st.caption(f"{sel_path} | sha256: {sel_sha}")
        except Exception as _e:
            st.warning(f"Could not preview selected reference: {_e}")

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

    # Helper to call backend
    def _generate(room_file, ref_path: Path, prompt_text: str, temp: float, top_p: float, seed: int | None, ref2_path: Path | None = None):
        files = {"room_image": (room_file.name, room_file.getvalue(), room_file.type)}
        data = {"reference_path": str(ref_path)}
        if prompt_text.strip():
            data["product_prompt"] = prompt_text.strip()
        data["temperature"] = str(temp)
        data["top_p"] = str(top_p)
        if seed is not None:
            data["seed"] = str(seed)
        if ref2_path is not None:
            data["reference2_path"] = str(ref2_path)
        resp = requests.post(f"{API_BASE}/api/generate-floor", files=files, data=data, timeout=120)
        if not resp.ok:
            try:
                err = resp.json()
            except Exception:
                err = {"detail": resp.text}
            raise RuntimeError(f"Backend error {resp.status_code}: {err}")
        return resp.json()

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
    if st.button("Generate", disabled=(room is None or "selected_ref_path" not in st.session_state)):
        if not room or "selected_ref_path" not in st.session_state:
            st.warning("Please select a reference and upload a room image.")
        else:
            with st.spinner("Calling backend..."):
                try:
                    payload = _generate(
                        room,
                        Path(st.session_state["selected_ref_path"]),
                        product_prompt,
                        ui_temp,
                        ui_top_p,
                        int(ui_seed),
                        Path(ref2_input) if ref2_input.strip() else None,
                    )
                except Exception as e:
                    st.error(f"Request failed: {e}")
                    return
                out_paths = [f"{API_BASE}{p}" for p in payload.get("output_paths", [])]
                if not out_paths:
                    st.warning("No outputs returned")
                    return
                with st.expander("Call details (debug)", expanded=False):
                    st.json({
                        "reference_path": payload.get("reference_path"),
                        "reference_name": payload.get("reference_name"),
                        "reference_sha256": payload.get("reference_sha256"),
                        "prompt_used": payload.get("prompt_used"),
                    })
                for path in out_paths:
                    st.image(path, caption=path)

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

    def _pick_random_unused(all_paths: List[Path]) -> Path | None:
        used_names = set(st.session_state["remix_used"])  # type: ignore
        candidates = [p for p in all_paths if p.name not in used_names]
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
        ref = _pick_random_unused(refs)
        if not ref:
            st.info("No more unique floors to try. Click Reset remix to start over.")
        else:
            with st.spinner(f"Remixing with {ref.name}..."):
                payload = None
                try:
                    payload = _generate(
                        shim,
                        ref,
                        product_prompt,
                        ui_temp,
                        ui_top_p,
                        int(ui_seed),
                        Path(ref2_input) if ref2_input.strip() else None,
                    )
                except Exception as e:
                    st.error(f"Remix failed: {e}")
                out_urls = []
                if payload is not None:
                    out_urls = [f"{API_BASE}{p}" for p in payload.get("output_paths", [])]
            if out_urls:
                st.session_state["remix_used"].append(ref.name)
                for u in out_urls:
                    st.session_state["remix_outputs"].append((ref.name, u))

    if st.session_state["remix_outputs"]:
        st.markdown("---")
        st.subheader("Remix results")
        for ref_name, url in st.session_state["remix_outputs"]:
            st.image(url, caption=f"{ref_name}: {url}")


if __name__ == "__main__":
    main()


