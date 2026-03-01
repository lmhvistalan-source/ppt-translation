import os
import subprocess
from pathlib import Path
from typing import Optional


def convert_with_libreoffice(input_path: str) -> Optional[str]:
    """
    Convert legacy .ppt/.doc to .pptx/.docx using LibreOffice `soffice`.
    Returns the converted file path or None on failure.
    """
    p = Path(input_path)
    ext = p.suffix.lower()
    if ext not in [".ppt", ".doc"]:
        return input_path
    outdir = p.parent
    from shutil import which
    if which("soffice") is None:
        return None
    # determine target
    target_ext = ".pptx" if ext == ".ppt" else ".docx"
    try:
        subprocess.run(["soffice", "--headless", "--convert-to", target_ext.lstrip('.'), str(p), "--outdir", str(outdir)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        converted = outdir / (p.stem + target_ext)
        if converted.exists():
            return str(converted)
    except Exception:
        return None
    return None
