import os
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from floor_replace.generator import FloorReplaceGenerator, _guess_mime, INSTRUCTION_TEXT


OUTPUTS_DIR = Path("outputs").resolve()
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


class GenerateResponse(BaseModel):
    output_paths: List[str]


def create_app() -> FastAPI:
    app = FastAPI(title="TedTodd Floor Replace API")

    # CORS: allow local dev frontends; adjust as needed
    allowed_origins = os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173,http://localhost:8501,http://127.0.0.1:8501",
    ).split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in allowed_origins if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Static mount for outputs so frontend can display via URL
    app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")

    @app.post("/api/generate-floor", response_model=GenerateResponse)
    async def generate_floor(
        room_image: UploadFile = File(..., description="User room photo"),
        reference_path: str = Form(..., description="Absolute or project-local path to reference floor image"),
        mask_image: UploadFile | None = File(
            default=None, description="Optional mask image for floor region"
        ),
        product_prompt: str | None = Form(
            default=None,
            description="Optional product-specific prompt hints (tone, gloss, plank width, etc.)",
        ),
    ) -> GenerateResponse:
        # Validate GEMINI key
        if not os.environ.get("GEMINI_API_KEY"):
            raise HTTPException(status_code=500, detail="GEMINI_API_KEY not set on server")

        # Resolve and validate reference file path
        ref_path = Path(reference_path).expanduser()
        if not ref_path.is_file():
            raise HTTPException(status_code=400, detail=f"reference_path not found: {ref_path}")

        # Read uploads into memory (MVP). Later: persist uploads if needed.
        room_bytes = await room_image.read()
        room_mime = room_image.content_type or _guess_mime(room_image.filename or "room.png")

        with open(ref_path, "rb") as f:
            ref_bytes = f.read()
        ref_mime = _guess_mime(str(ref_path))

        mask_bytes = None
        mask_mime = None
        if mask_image is not None:
            mask_bytes = await mask_image.read()
            mask_mime = mask_image.content_type or _guess_mime(mask_image.filename or "mask.png")

        # Compose instruction text
        instruction_text = INSTRUCTION_TEXT
        if product_prompt:
            instruction_text = f"{INSTRUCTION_TEXT}\n\n# PRODUCT HINTS\n{product_prompt}"

        # Run generation
        try:
            generator = FloorReplaceGenerator()
            outputs = generator.generate_single_ref(
                room_bytes=room_bytes,
                room_mime=room_mime,
                reference_bytes=ref_bytes,
                reference_mime=ref_mime,
                mask_bytes=mask_bytes,
                mask_mime=mask_mime,
                instruction_text=instruction_text,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

        if not outputs:
            raise HTTPException(status_code=502, detail="Model returned no image output")

        # Save outputs and return URLs
        saved_paths: List[str] = []
        base_name = (Path(room_image.filename or "room").stem + "__" + ref_path.stem)
        base_name = base_name.replace(" ", "_")
        for idx, (mime, data) in enumerate(outputs):
            ext = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/webp": ".webp",
            }.get(mime, ".png")
            file_name = f"{base_name}_{idx}{ext}"
            out_path = OUTPUTS_DIR / file_name
            with open(out_path, "wb") as f:
                f.write(data)
            # URL path (FastAPI static mount)
            saved_paths.append(f"/outputs/{file_name}")

        return GenerateResponse(output_paths=saved_paths)

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()


