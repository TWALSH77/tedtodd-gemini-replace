Core Idea

User can create a rendered room with a chosen floor style by either:

Selecting a sample room photo (from a preset library), or

Uploading their own room photo.

The floor styles are fixed — 25 high-quality floor products (each with its own metadata + swatch image). These are applied to whichever room photo the user picks or uploads.

Content Libraries
1. Rooms

Source:

~20 pre-saved “sample” room shots (living room, kitchen, etc.) for quick demos.

OR user upload (1–3 photos).

Metadata per sample room:

id (string)

name (e.g., “Modern Living Room 01”)

image_path (e.g., rooms/samples/living_01.jpg)

metadata: { room_type, lighting, angle, resolution, floor_visibility_pct }

created_at

2. Floors (Products)

Fixed library of 25 floors, each one is a “product” with a canonical set of images.

Each floor product has:

id (string / slug)

name (e.g., “TedTodd Oak Wide Matte”)

swatch_path (thumbnail to show in UI)

images (array of high-res product photos, textures, herringbone/horizontal, etc.)

prompt (text hints for the model: “Wide natural oak planks, matte finish, no shine”)

metadata: { tone, gloss, plank_width_mm, colour_tags[], brand }

created_at

Note: these floor products are the source of truth for what gets “laid” in the room shot.

User Flow

Pick a Floor Product

Browse grid of 25 products (name + swatch).

Select one.

Choose Room Photo

Either:

Pick one from the pre-saved library (sample rooms), or

Upload their own (drag & drop, up to 3).

Generate

App sends: (room photo, floor product image(s), floor prompt) → nano-banana model.

Model returns: room with that floor applied.

Result Gallery

For each input (sample or uploaded room), show output.

User can download.

API / Data Changes
GET /api/floors

Returns 25 floor product records.

Swatch for UI.

Metadata for context.

GET /api/rooms

Returns 20 sample room records.

POST /api/upload

For user-uploaded photos → returns paths.

POST /api/jobs

Body:

{
  "floor_id": "oak-wide-matte",
  "source": "upload" | "sample",
  "input_paths": ["uploads/abc.jpg"] | ["rooms/samples/living_03.jpg"]
}

GET /api/jobs/{id}

Returns job JSON with output image paths.

Job Record (JSON on disk)
{
  "id": "job123",
  "status": "DONE",
  "floor_id": "oak-wide-matte",
  "floor_meta": { "name": "Oak Wide Matte", "brand": "TedTodd" },
  "source": "sample",
  "input_images": [
    {
      "id": "0",
      "path": "rooms/samples/living_03.jpg",
      "status": "DONE",
      "output_path": "outputs/job123_0.jpg"
    }
  ],
  "created_at": "...",
  "updated_at": "..."
}

Prompting Strategy

System base prompt:
“Replace the existing floor in this room with the selected floor product. Keep the room’s lighting, shadows, furniture, and walls intact.”

Floor product-specific hints:
Each product in /floors/floors.json has a prompt with detail like:

“Natural oak, 200mm wide planks, matte finish, subtle grain”

“Herringbone oak, medium brown, satin gloss”

This ensures the model applies the right “look & feel” of the chosen product.

Architecture (still ultra-simple)

One backend:

Serves floor & room JSON metadata + static assets.

Accepts uploads.

Runs background task calling nano-banana.

Saves outputs to /outputs/.

Static UI:

Grid of floors → pick one.

Grid of rooms OR upload section.

“Generate” button → call job API.

Poll until done → show results.

Storage:

/floors → 25 products (metadata + swatches + high-res reference images).

/rooms → ~20 sample room images.

/uploads → user photos.

/outputs → generated results.

/jobs → job JSON state.

✅ This keeps the separation very clean:

Rooms = canvas (sample or uploaded).

Floors = product library (25 SKUs).

The app’s job is to apply one floor product onto one or more rooms.




Great—let’s lock the architecture and how prompts/Endpoints fit together (no code).

High-level architecture

Frontend (React)

Shows the 25 floor products (from metadata) and 20–25 sample rooms.

Lets the user upload their own room photos.

Starts a generation job and polls for results.

Displays outputs.

Storage (S3)

Buckets/folders:

floors/ → swatches + product reference images.

rooms/ → sample room library.

uploads/ → user uploads (via presigned PUT).

outputs/ → generated results.

Optional metadata/ → floors.json, rooms.json.

Backend (FastAPI)

Serves floor & room metadata.

Issues presigned URLs for upload.

Creates jobs (in-memory or JSON-on-disk).

Downloads inputs from S3, calls Gemini, writes outputs to S3.

Exposes job status/results.

Prompting strategy — per-image vs general

Short answer: Use a layered prompt that is general, but composed per image at call time.

Base “system” prompt (static, shared across all images)
One carefully written instruction set that never changes:

“Replace only the floor with the selected product. Preserve room geometry, lighting, shadows, reflections and furniture. Respect perspective and realistic plank scale. No artifacts, no warping walls.”

Product-specific prompt (varies by floor product)
Pulled from floors.json (e.g., tone, gloss, pattern, plank width, color tags).
Example: “Light natural oak, 200mm wide planks, matte finish, subtle grain; avoid yellow cast.”

Optional per-image hints (dynamic)
If you have room metadata (e.g., “herringbone orientation left→right”, “strong window light from left”), include it. For user uploads you can omit, or infer basics later.

How it’s applied:
Every image inference call to Gemini includes:

the base prompt (constant),

the chosen product’s prompt (varies by floor), and

optional per-image details (if present).

So practically, the prompt is composed per image from reusable parts. This keeps quality consistent and lets you tune products independently.

Data that flows into Gemini

Room image: S3 object (downloaded by backend or streamed).

Floor product inputs: at minimum the swatch; optionally one or two high-quality reference images of the product to better guide texture/pattern.

Prompt: composed string as above.

Endpoints (what they do, inputs/outputs, who calls them)
1) GET /health

Purpose: simple readiness check.

Called by: you, monitoring.

Returns: { "ok": true }

2) GET /api/floors

Purpose: list the 25 floor products to display in the frontend.

Backend does: reads floors.json (or DB later), returns lightweight fields:

id, name, swatch_url, prompt, metadata (tone, gloss, plank width, tags), and (optionally) reference_image_urls.

Called by: frontend on page load.

Returns: [{ id, name, swatch_url, prompt, metadata, reference_image_urls[] }]

3) GET /api/rooms

Purpose: list sample room shots.

Backend does: reads rooms.json, returns entries with:

id, name, image_url, optional metadata (room type, lighting, angle).

Called by: frontend when the user selects “Use sample room”.

Returns: [{ id, name, image_url, metadata }]

4) POST /api/uploads/presign

Purpose: let the browser upload directly to S3 (no large files through your server).

Input: { count: number } or implicit by selected files.

Backend does: creates presigned PUT URLs for uploads/ and (optionally) public GET URLs (or you can derive GET by stripping query).

Called by: frontend before uploading files.

Returns: [{ put_url, get_url }] per file.

5) (Frontend action, not an endpoint) Upload to S3

Purpose: browser PUTs the files to S3 using the presigned URLs.

Result: browser now knows the input S3 GET URLs (or stable keys to later resolve).

6) POST /api/jobs

Purpose: create a generation job for one floor product and one or more room images (sample or uploaded).

Input:

{
  "floor_id": "oak-wide-matte",
  "source": "sample" | "upload",
  "input_urls": [
    "https://s3.../rooms/samples/living_03.jpg",
    ...
  ]
}


(If you keep only keys, send keys; backend resolves to S3 URLs.)

Backend does:

Validates the floor exists and URLs are allowed.

Creates a job_id, writes initial job state (PENDING).

Starts background processing (sequential):

For each image: download → (optional resize) → call Gemini with (room image + product swatch/reference + composed prompt) → write output to outputs/ in S3 → update per-image status/path.

Sets job → DONE or ERROR.

Called by: frontend on “Generate”.

Returns: { "job_id": "..." }

7) GET /api/jobs/{job_id}

Purpose: poll job status and get outputs.

Backend does: returns the current job JSON.

Called by: frontend every ~2s until finished.

Returns:

{
  "id": "job_123",
  "status": "PENDING|RUNNING|DONE|ERROR",
  "floor_id": "oak-wide-matte",
  "items": [
    {
      "input_url": "https://s3.../uploads/a.jpg" | sample URL,
      "status": "DONE|ERROR",
      "output_url": "https://s3.../outputs/job_123_0.jpg",
      "error": null | "string"
    },
    ...
  ],
  "created_at": "...",
  "updated_at": "...",
  "error": null | "string"
}

(Optional) 8) POST /api/cleanup

Purpose: maintenance hook to purge outputs/uploads older than N days (or use a cron job/Lambda instead).

Called by: admin/cron.

Frontend flow (step-by-step)

Load libraries

GET /api/floors → render 25 floor cards.

GET /api/rooms → render sample room grid (hidden until “Use sample room” selected).

User selection

Pick one floor.

Choose room source:

Sample: select one or more sample room images (or keep it to 1 for MVP).

Upload: call POST /api/uploads/presign → PUT files to S3 → collect public GET URLs.

Create job

POST /api/jobs with { floor_id, source, input_urls }.

Poll

GET /api/jobs/{id} until DONE|ERROR.

Render outputs

Show output images from S3 (outputs/), with download buttons.

Where prompts live & how they’re versioned

Base prompt: keep in backend config (e.g., PROMPT_BASE_v1).

Product prompts: stored in floors.json per product.

Versioning: add prompt_version in responses and job records. When you tweak prompts, bump versions. This lets you A/B test or roll back.

S3 & security notes (practical MVP)

Presigned PUT for uploads; keep object ACL private.

For serving images back to the browser:

Either use presigned GET (short TTL) returned via job status, or

Put outputs behind a static site/CDN bucket with public GET; if so, avoid sensitive metadata and set a cleanup policy.

CORS: allow your frontend origin; allow GET, POST, PUT; allow Content-Type.

Never expose your Gemini API key to the browser—only the backend calls Gemini.

Error handling (what each endpoint should communicate)

/api/uploads/presign: reject if count > limit; include max size/type constraints in response (for UX).

/api/jobs: 400 if floor_id not found or inputs empty; 413 if image too large (if backend validates); 422 for invalid URLs.

/api/jobs/{id}: 404 for unknown job; include per-image errors so partial success still returns useful results.

Minimal sequencing to build

Wire /api/floors and /api/rooms returning your S3 URLs + metadata.

Implement /api/uploads/presign and test a direct PUT from the browser.

Implement /api/jobs with a mock processor (copy input → output) to validate flow.

Swap the mock for Gemini inference (compose prompt per image, download inputs from S3, upload outputs back).

Frontend polls and renders the gallery.

That’s the whole loop—clean, testable, and ready to improve quality iteratively.