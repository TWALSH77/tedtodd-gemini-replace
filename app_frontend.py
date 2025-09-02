import os
from pathlib import Path
import requests
import streamlit as st


API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")
PHOTO_BANK_DIR = Path(
    "/Users/tedwalsh/Desktop/research_2025_summer/tedtodd-nana-bananna/tedtodd-photo-bank"
)


def list_reference_images(folder: Path):
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    return [p for p in sorted(folder.glob("*")) if p.suffix.lower() in exts]


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

    # Sidebar for reference selection
    with st.sidebar:
        st.header("Reference Floor")
        refs = list_reference_images(PHOTO_BANK_DIR)
        if not refs:
            st.error(f"No refs found in {PHOTO_BANK_DIR}")
        ref_names = [p.name for p in refs]
        ref_choice = st.selectbox("Choose a floor product image", ref_names, index=0 if ref_names else None)
        selected_ref = PHOTO_BANK_DIR / ref_choice if ref_names else None
        st.write("Selected:", selected_ref)
        st.divider()
        st.header("Product Prompt (optional)")
        product_prompt = st.text_area(
            "Hints (e.g., 'Light natural oak, 200mm plank width, matte finish')",
            value="",
            height=120,
        )

    st.header("Upload Room Image")
    room = st.file_uploader("Room photo", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=False)
    if room:
        st.image(room.getvalue(), caption="Room input")

    if st.button("Generate"):
        if not room or not selected_ref:
            st.warning("Please select a reference and upload a room image.")
        else:
            with st.spinner("Calling backend..."):
                files = {"room_image": (room.name, room.getvalue(), room.type)}
                data = {"reference_path": str(selected_ref)}
                if product_prompt.strip():
                    data["product_prompt"] = product_prompt.strip()
                try:
                    resp = requests.post(f"{API_BASE}/api/generate-floor", files=files, data=data, timeout=120)
                except Exception as e:
                    st.error(f"Request failed: {e}")
                    return
                if not resp.ok:
                    st.error(f"Error {resp.status_code}: {resp.text}")
                    return
                payload = resp.json()
                out_paths = payload.get("output_paths", [])
                if not out_paths:
                    st.warning("No outputs returned")
                    return
                for path in out_paths:
                    url = f"{API_BASE}{path}"
                    st.image(url, caption=url)


if __name__ == "__main__":
    main()


