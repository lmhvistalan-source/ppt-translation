# Internal Document Translator (MVP)

Small FastAPI application to translate Office documents (`.pptx`, `.ppt`, `.docx`, `.doc`).

Features:
- Upload `.pptx`, `.ppt`, `.docx`, `.doc` and select target language (top 10 supported).
- Uses a pluggable translation provider. Default is `google`.
- Converts legacy `.ppt`/`.doc` via LibreOffice (`soffice`) if installed.
- Deletes uploaded files immediately after processing.

Quick start (Python 3.11+ recommended):

1. Create a virtualenv and install:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. (Optional) Install LibreOffice to support `.ppt`/`.doc` conversion.

3. Run the app:

```bash
uvicorn app.main:app --reload
```

4. Open http://127.0.0.1:8000 in your browser.

Configuration:
- To integrate a real provider (Azure/Google), set `TRANSLATOR_PROVIDER` and provider-specific env vars. See `app/translator.py` for the provider interface.

Notes & next steps:
- The repository defaults to Google Translate (`TRANSLATOR_PROVIDER=google`).
- For production, serve behind your internal network (VPN/intranet) and enable private endpoints for cloud providers.

## Deployment on Render

### Using the Web Dashboard

1. Push this repo to GitHub and sign up at https://render.com (free tier works).
2. Create a **new Web Service** and connect it to your repository.
3. When Render asks for a Start Command, do **not** use the naive `uvicorn ... --port $PORT` line; `$PORT` will not expand and your service will exit with status 1. Instead either
   ```bash
   bash -lc "uvicorn app.main:app --host 0.0.0.0 --port \$PORT"
   ```
   or rely on the provided `Procfile` which already wraps the command in `bash -lc`.
4. Ensure `runtime.txt` is set to `python-3.11.4` and that `requirements.txt` is pinned as shown.
5. Optionally configure `TRANSLATOR_PROVIDER` and other env vars via Render's dashboard.

The build should now succeed without installing heavy transformer packages, and the startup command will expand the port properly.

### Using the Render CLI

Render's current CLI is best for deploy/restart/log workflows. For first-time service provisioning, keep a `render.yaml` Blueprint in this repo, then create/sync the service from Render once.

1. Install the CLI:

```bash
curl -fsSL https://cdn.rndr.com/cli/install.sh | sh
# or: brew install render
```

2. Authenticate and set workspace:

```bash
render login
render workspaces
render workspace set <workspace-id-or-name>
```

3. Validate this repo's Blueprint:

```bash
render blueprints validate render.yaml
```

4. Create/sync the service in Render using this repo's `render.yaml` (one-time setup in Dashboard/Blueprint flow).

5. Trigger deploys from CLI:

```bash
git push origin main
render services                     # interactive picker
render deploys create <service-id> --wait
```

For CI/non-interactive mode:

```bash
export RENDER_API_KEY=...
render deploys create <service-id> --wait --confirm -o text
```

To look up IDs in scripts:

```bash
render services -o json
```

> **Important:** keep the start command wrapped in `bash -lc` (or use the Procfile) so `$PORT` is expanded correctly.

## Optional Dependencies

If you plan to use the `huggingface` provider you will need extra packages:

  pip install torch transformers sentencepiece

These are intentionally **not** in requirements.txt to avoid build problems on free hosts like Render.
