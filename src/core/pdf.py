"""Turn an HTML report into a PDF with the browser already on the computer (Edge ships with Windows).

A browser lays out Persian (right-to-left) text and fonts exactly as on screen, which pure-Python PDF
libraries do not do reliably, and it needs nothing extra installed.
"""

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

_CANDIDATES = [
    os.environ.get("VETCLINIC_PDF_BROWSER", ""),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def find_browser() -> str | None:
    for path in _CANDIDATES:
        if path and Path(path).is_file():
            return path
    for name in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def html_to_pdf(html: str, timeout: int = 60) -> bytes:
    """Render `html` to PDF bytes. Raises RuntimeError when no browser is found or printing fails."""
    browser = find_browser()
    if browser is None:
        raise RuntimeError("Microsoft Edge or Google Chrome is needed to make PDFs. (برای ساخت PDF مرورگر Edge یا Chrome لازم است)")
    # Edge's helper processes can still hold files in the profile folder for a moment after it exits, so a
    # folder that cannot be deleted yet is left for Windows to clear instead of failing a finished PDF.
    with tempfile.TemporaryDirectory(prefix="vetclinic_pdf_", ignore_cleanup_errors=True) as tmp:
        source, target = Path(tmp) / "report.html", Path(tmp) / "report.pdf"
        source.write_text(html, encoding="utf-8")
        command = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--no-pdf-header-footer",
            # A separate profile, so an Edge/Chrome window the user already has open is not involved.
            f"--user-data-dir={Path(tmp) / 'profile'}",
            f"--print-to-pdf={target}",
            source.as_uri(),
        ]
        deadline = time.monotonic() + timeout
        try:
            subprocess.run(command, capture_output=True, timeout=timeout, check=False,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Making the PDF took too long. (ساخت PDF بیش از حد طول کشید)") from exc
        # When an Edge window is already open, msedge.exe hands the job to a background process and returns
        # at once, so the file appears a moment later. Wait until it is completely written.
        while time.monotonic() < deadline:
            data = target.read_bytes() if target.is_file() else b""
            if data.rstrip().endswith(b"%%EOF"):
                return data
            time.sleep(0.2)
        raise RuntimeError("The PDF could not be created. (ساخت PDF ناموفق بود)")
