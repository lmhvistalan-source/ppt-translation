import os
import shutil
import tempfile
import uuid
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from starlette.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from app.translator import get_translator
from app.utils import convert_with_libreoffice

app = FastAPI(title="Internal Document Translator")
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")

# When `SHOW_ERRORS`=1 the app will render full exception traces in the UI.
# Disabled by default to avoid leaking sensitive information in production.
SHOW_ERRORS = os.getenv("SHOW_ERRORS", "0") == "1"

translator = get_translator()

# Simple in-memory progress tracker: {request_id: {"status": "uploading|translating|completed", "progress": 0-100}}
progress_tracker = {}


import traceback
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
        # For HTTPExceptions, let FastAPI handle them as usual
        from fastapi import HTTPException
        if isinstance(exc, HTTPException):
                raise exc

        # Log the exception
        tb = traceback.format_exc()
        print("[ERROR]", tb)

        if SHOW_ERRORS:
                # Render error and traceback in a simple HTML page for debugging
                html = f"""
                <html>
                    <head><title>Internal Server Error</title></head>
                    <body>
                        <h2>Internal Server Error</h2>
                        <h3>Exception:</h3>
                        <pre>{str(exc)}</pre>
                        <h3>Traceback:</h3>
                        <pre>{tb}</pre>
                    </body>
                </html>
                """
                return HTMLResponse(content=html, status_code=500)

        # Generic message when SHOW_ERRORS is not enabled
        return HTMLResponse(content="<h2>Internal Server Error</h2><p>An unexpected error occurred.</p>", status_code=500)

TOP_LANGUAGES = [
    ("en", "English"),
    ("zh-Hans", "Chinese (Simplified)"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("pt", "Portuguese"),
    ("ru", "Russian"),
    ("it", "Italian"),
]

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = Path(__file__).resolve().parent / "static" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/progress/{request_id}")
async def get_progress(request_id: str):
    """Get translation progress for a specific request."""
    if request_id in progress_tracker:
        return progress_tracker[request_id]
    return {"status": "unknown", "progress": 0}


@app.post("/translate")
async def translate(file: UploadFile = File(...), target_lang: str = Form(...)):
    # Create a unique ID for this translation request
    request_id = str(uuid.uuid4())
    progress_tracker[request_id] = {"status": "uploading", "progress": 0}
    
    if target_lang not in [c for c, _ in TOP_LANGUAGES]:
        raise HTTPException(status_code=400, detail="Unsupported language")

    tmpdir = Path(tempfile.mkdtemp())
    try:
        # Save uploaded file
        in_path = tmpdir / file.filename
        with in_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        
        # Update progress: upload complete, starting translation
        progress_tracker[request_id] = {"status": "translating", "progress": 10}

        # If legacy formats, convert to modern Office formats
        lower = in_path.suffix.lower()
        if lower in [".ppt", ".doc"]:
            converted = convert_with_libreoffice(str(in_path))
            if converted is None:
                raise HTTPException(status_code=500, detail="Conversion failed (please install LibreOffice)")
            working_path = Path(converted)
        else:
            working_path = in_path

        # Try document-level translation first (preserves formatting)
        out_path = None
        try:
            if hasattr(translator, 'translate_file'):
                out_path_str = translator.translate_file(str(working_path), target_lang)
                out_path = Path(out_path_str)
                print(f"✓ Document translation succeeded: {out_path}")
        except NotImplementedError:
            pass  # fallback to text-based translation
        except Exception as e:
            print(f"⚠ Document translation failed: {e}")

        # If document translation didn't work, fall back to text-based translation
        if out_path is None:
            print(f"⚠ Using text-based fallback translation")
            out_path = tmpdir / (working_path.stem + f"_translated_{target_lang}{working_path.suffix}")
            
            # Handle PPTX
            if working_path.suffix.lower() == ".pptx":
                from pptx import Presentation
                from pptx.enum.shapes import MSO_SHAPE_TYPE
                prs = Presentation(str(working_path))
                runs = []
                texts = []
                for slide in prs.slides:
                    for shape in slide.shapes:
                        # Handle regular text shapes
                        if hasattr(shape, "text_frame"):
                            for paragraph in shape.text_frame.paragraphs:
                                for run in paragraph.runs:
                                    runs.append(run)
                                    texts.append(run.text or "")
                        # Handle tables
                        if shape.shape_type == MSO_SHAPE_TYPE.TABLE:
                            table = shape.table
                            for row in table.rows:
                                for cell in row.cells:
                                    for paragraph in cell.text_frame.paragraphs:
                                        for run in paragraph.runs:
                                            runs.append(run)
                                            texts.append(run.text or "")

                # Batch translate
                translations = translator.translate_texts(texts, target_lang)
                for run, t in zip(runs, translations):
                    run.text = t
                prs.save(str(out_path))

            # Handle DOCX
            elif working_path.suffix.lower() == ".docx":
                from docx import Document
                doc = Document(str(working_path))
                runs = []
                texts = []
                for para in doc.paragraphs:
                    for run in para.runs:
                        runs.append(run)
                        texts.append(run.text or "")
                # also tables
                for table in doc.tables:
                    for row in table.rows:
                        for cell in row.cells:
                            for para in cell.paragraphs:
                                for run in para.runs:
                                    runs.append(run)
                                    texts.append(run.text or "")

                translations = translator.translate_texts(texts, target_lang)
                for run, t in zip(runs, translations):
                    run.text = t
                doc.save(str(out_path))
            else:
                raise HTTPException(status_code=400, detail="Unsupported file type")

        # Read file into memory to avoid deletion race condition
        with open(out_path, "rb") as f:
            file_content = f.read()
        
        print(f"✓ Translation complete, serving {len(file_content)} bytes")
        
        # Clean up temp directory after reading file
        try:
            shutil.rmtree(str(tmpdir))
        except Exception as e:
            print(f"Warning: cleanup failed: {e}")
        
        # Build a Content-Disposition that is safe for non-ASCII filenames.
        # Starlette will attempt to encode header values as latin-1, which fails
        # for many Unicode characters. Use an ASCII fallback plus RFC5987
        # `filename*=` with percent-encoded UTF-8 so the header is ASCII-only.
        from urllib.parse import quote
        filename = out_path.name
        try:
            # If the filename is encodable to latin-1, use it directly
            filename.encode("latin-1")
            content_disp = f'attachment; filename="{filename}"'
        except UnicodeEncodeError:
            # ASCII fallback: replace non-ASCII with underscore
            ascii_fallback = ''.join(c if ord(c) < 128 else '_' for c in filename)
            utf8_quoted = quote(filename, safe='')
            content_disp = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{utf8_quoted}"

        return Response(
            content=file_content,
            media_type=("application/vnd.openxmlformats-officedocument.presentationml.presentation"
                        if out_path.suffix.lower() == ".pptx"
                        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            headers={"Content-Disposition": content_disp}
        )
    finally:
        # Clean up temp directory (may have already been cleaned above)
        if tmpdir and tmpdir.exists():
            try:
                shutil.rmtree(str(tmpdir))
            except Exception:
                pass
