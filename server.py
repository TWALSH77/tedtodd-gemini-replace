import os
import time
import uuid
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import logging
from dotenv import load_dotenv
import hashlib

from floor_replace.generator import FloorReplaceGenerator, _guess_mime, INSTRUCTION_TEXT


# Load .env if present (robust local configuration)
load_dotenv(dotenv_path=Path(".env"))

# Basic logging
logging.basicConfig(level=logging.INFO)

OUTPUTS_DIR = Path("outputs").resolve()
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


class GenerateResponse(BaseModel):
    output_paths: List[str]
    reference_path: str
    reference_name: str
    reference_sha256: str
    prompt_used: str
    reference2_path: str | None = None
    reference2_name: str | None = None
    reference2_sha256: str | None = None


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
        reference2_path: str | None = Form(default=None, description="Optional second reference image path"),
        mask_image: UploadFile | None = File(
            default=None, description="Optional mask image for floor region"
        ),
        product_prompt: str | None = Form(
            default=None,
            description="Optional product-specific prompt hints (tone, gloss, plank width, etc.)",
        ),
        temperature: float = Form(default=0.0, description="Model temperature 0-1 (lower = faithful)"),
        top_p: float = Form(default=0.1, description="Top-p nucleus sampling (lower = faithful)"),
        seed: int | None = Form(default=12345, description="Deterministic seed"),
    ) -> GenerateResponse:
        # Validate GEMINI key
        if not os.environ.get("GEMINI_API_KEY"):
            raise HTTPException(status_code=500, detail="GEMINI_API_KEY not set on server")

        # Resolve and validate reference file path (restrict to project tree)
        try:
            ref_path = Path(reference_path).expanduser().resolve()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid reference_path")
        project_root = Path(__file__).resolve().parent
        allowed_roots = [
            project_root / "tedtodd-photo-bank",
            project_root / "data" / "tedtodd_static_shots",
            project_root / "tedtodd-photo-roomshots",
        ]
        ref_allowed = any(str(ref_path).startswith(str(ar.resolve())) for ar in allowed_roots)
        if not ref_allowed:
            raise HTTPException(status_code=400, detail="reference_path must be inside an allowed folder")
        if not ref_path.is_file():
            raise HTTPException(status_code=400, detail=f"reference_path not found: {ref_path}")

        # Read uploads into memory (MVP). Later: persist uploads if needed.
        room_bytes = await room_image.read()
        room_mime = room_image.content_type or _guess_mime(room_image.filename or "room.png")
        if not room_bytes:
            raise HTTPException(status_code=400, detail="Empty room_image upload")

        with open(ref_path, "rb") as f:
            ref_bytes = f.read()
        ref_mime = _guess_mime(str(ref_path))
        if not ref_bytes:
            raise HTTPException(status_code=400, detail="Empty reference image file")
        ref_sha256 = hashlib.sha256(ref_bytes).hexdigest()

        # Optional second reference
        ref2_bytes = None
        ref2_mime = None
        ref2_sha256 = None
        ref2_name = None
        ref2_path_resolved: Path | None = None
        if reference2_path:
            try:
                ref2_path_resolved = Path(reference2_path).expanduser().resolve()
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid reference2_path")
            ref2_allowed = any(str(ref2_path_resolved).startswith(str(ar.resolve())) for ar in allowed_roots)
            if not ref2_allowed:
                raise HTTPException(status_code=400, detail="reference2_path must be inside an allowed folder")
            if not ref2_path_resolved.is_file():
                raise HTTPException(status_code=400, detail=f"reference2_path not found: {ref2_path_resolved}")
            with open(ref2_path_resolved, "rb") as f2:
                ref2_bytes = f2.read()
            ref2_mime = _guess_mime(str(ref2_path_resolved))
            if not ref2_bytes:
                raise HTTPException(status_code=400, detail="Empty reference2 image file")
            ref2_sha256 = hashlib.sha256(ref2_bytes).hexdigest()
            ref2_name = ref2_path_resolved.name

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
            generator = FloorReplaceGenerator(temperature=temperature, top_p=top_p, seed=seed)
            if ref2_bytes and ref2_mime:
                outputs = generator.generate_two_refs(
                    room_bytes=room_bytes,
                    room_mime=room_mime,
                    ref1_bytes=ref_bytes,
                    ref1_mime=ref_mime,
                    ref2_bytes=ref2_bytes,
                    ref2_mime=ref2_mime,
                    mask_bytes=mask_bytes,
                    mask_mime=mask_mime,
                    instruction_text=instruction_text,
                    seed=seed,
                )
            else:
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
            logging.exception("Generation failed")
            # Try to surface meaningful API error info
            err_text = str(e)
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Generation failed",
                    "api_error": err_text,
                    "room_size_bytes": len(room_bytes),
                    "ref_size_bytes": len(ref_bytes),
                    "has_mask": bool(mask_bytes),
                },
            )

        if not outputs:
            raise HTTPException(status_code=502, detail="Model returned no image output")

        # Save outputs and return URLs
        saved_paths: List[str] = []
        timestamp = int(time.time())
        unique = uuid.uuid4().hex[:8]
        base_name = (Path(room_image.filename or "room").stem + "__" + ref_path.stem)
        base_name = base_name.replace(" ", "_") + f"__{timestamp}_{unique}"
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

        return GenerateResponse(
            output_paths=saved_paths,
            reference_path=str(ref_path),
            reference_name=ref_path.name,
            reference_sha256=ref_sha256,
            prompt_used=instruction_text,
            reference2_path=str(ref2_path_resolved) if ref2_path_resolved else None,
            reference2_name=ref2_name,
            reference2_sha256=ref2_sha256,
        )

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()


