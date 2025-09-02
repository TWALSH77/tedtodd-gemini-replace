import io
import os
from pathlib import Path
from typing import List

import streamlit as st

from floor_replace.generator import FloorReplaceGenerator, _guess_mime


st.set_page_config(page_title="TedTodd Floor Replace", layout="wide")


def load_presaved_floors(folder: Path) -> List[Path]:
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    return [p for p in sorted(folder.glob("*")) if p.suffix.lower() in exts]


def ensure_api_key():
    api = os.environ.get("GEMINI_API_KEY")
    if not api:
        st.warning("Set GEMINI_API_KEY in your environment before running.")
    return api


def main():
    st.title("Batch Floor Replacement (Gemini)")
    st.caption("Upload room photos; generate outputs across all pre-saved floors.")

    with st.sidebar:
        st.header("Settings")
        model = st.text_input("Model", value="gemini-2.5-flash-image-preview")
        temperature = st.slider("Temperature", 0.0, 1.0, 0.1, 0.05)
        top_p = st.slider("Top P", 0.0, 1.0, 0.5, 0.05)
        floors_dir = st.text_input(
            "Floors folder",
            value=str(Path("data/tedtodd_static_shots").resolve()),
        )
        mask_file = st.file_uploader(
            "Optional floor mask (binary)", type=["png", "jpg", "jpeg", "webp"],
        )

    api_key = ensure_api_key()

    uploaded_rooms = st.file_uploader(
        "Upload one or more room photos",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
    )

    floors_path = Path(floors_dir)
    if not floors_path.exists():
        st.error(f"Floors directory not found: {floors_path}")
        return
    floor_refs = load_presaved_floors(floors_path)
    st.write(f"Found {len(floor_refs)} pre-saved floors")

    run = st.button("Generate")
    if run:
        if not api_key:
            st.stop()
        if not uploaded_rooms:
            st.warning("Please upload at least one room image.")
            st.stop()
        if not floor_refs:
            st.warning("No floor references found in folder.")
            st.stop()

        gen = FloorReplaceGenerator(
            api_key=api_key, model_name=model, temperature=temperature, top_p=top_p
        )

        mask_bytes = None
        mask_mime = None
        if mask_file is not None:
            mask_bytes = mask_file.read()
            mask_mime = _guess_mime(mask_file.name)

        for room in uploaded_rooms:
            room_bytes = room.read()
            room_mime = _guess_mime(room.name)

            st.subheader(f"Room: {room.name}")
            cols = st.columns(3)
            cols[0].image(room_bytes, caption="Input room", use_container_width=True)

            for ref in floor_refs:
                with st.spinner(f"Rendering: {ref.name}"):
                    with open(ref, "rb") as rf:
                        ref_bytes = rf.read()
                    ref_mime = _guess_mime(str(ref))
                    outputs = gen.generate_single_ref(
                        room_bytes=room_bytes,
                        room_mime=room_mime,
                        reference_bytes=ref_bytes,
                        reference_mime=ref_mime,
                        mask_bytes=mask_bytes,
                        mask_mime=mask_mime,
                    )
                for (mime, data) in outputs:
                    cols[1].image(ref_bytes, caption=f"Ref: {ref.name}", use_container_width=True)
                    cols[2].image(data, caption=f"Output ({ref.name})", use_container_width=True)
                    st.download_button(
                        label=f"Download {ref.stem} result",
                        data=io.BytesIO(data),
                        file_name=f"{Path(room.name).stem}__{ref.stem}.png",
                        mime=mime,
                    )


if __name__ == "__main__":
    main()


