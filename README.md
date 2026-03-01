# Internal Document Translator (MVP)

Small FastAPI application to translate Office documents (`.pptx`, `.ppt`, `.docx`, `.doc`).

Features:
- Upload `.pptx`, `.ppt`, `.docx`, `.doc` and select target language (top 10 supported).
- Uses a pluggable translation provider. Default is a local `mock` provider for testing.
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
- The repository uses a `mock` translator by default. I'll add real Azure/Google integration once you confirm provider and credentials.
- For production, serve behind your internal network (VPN/intranet) and enable private endpoints for cloud providers.

## Optional Dependencies

If you plan to use the `huggingface` provider you will need extra packages:

  pip install torch transformers sentencepiece

These are intentionally **not** in requirements.txt to avoid build problems on free hosts like Render.

