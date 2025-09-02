## TedTodd Floor Replace (Gemini)

Minimal app to upload room photos and batch-generate floor replacements across pre-saved floor references using Google Gemini.

### Setup
1. Create a Python venv.
2. Install deps:
```bash
pip install -r requirements.txt
```
3. Export your API key:
```bash
export GEMINI_API_KEY=YOUR_KEY
```

### Run the API (FastAPI)
```bash
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

Health check: `GET http://localhost:8000/api/health`

Generate endpoint (multipart):
```bash
curl -X POST \
  -F "room_image=@/absolute/path/to/room.jpg" \
  -F "reference_path=/Users/tedwalsh/Desktop/research_2025_summer/tedtodd-nana-bananna/tedtodd-photo-bank/Apian.jpg" \
  http://localhost:8000/api/generate-floor
```

Response:
```json
{ "output_paths": ["/outputs/room__Apian_0.png"] }
```
Open in browser: `http://localhost:8000/outputs/room__Apian_0.png`

### Run the Streamlit MVP
```bash
streamlit run app_frontend.py
```

Place floor references in `data/tedtodd_static_shots/` (png/jpg/webp). Upload room photo(s) and optionally a binary mask image of the floor.

### Notes
- Streamlit frontend posts to FastAPI and renders results.
- Uses `floor_replace/generator.py` wrapper around the Gemini client.
- Default model: `gemini-2.5-flash-image-preview`.
- Streams image results and shows downloads per floor.

### Notes on data
- Large assets are not committed. Place your local images under `tedtodd-photo-bank/` and `data/`.

