"""
downloader.py — YouTube search and audio download via yt_dlp + ffmpeg.

Flow:
  1. Audio is downloaded to a unique subfolder inside TEMP_DIR.
  2. yt_dlp's FFmpegExtractAudio post-processor converts it to 320 kbps MP3
     and removes the original file automatically.
  3. The resulting MP3 is moved to MUSIC_DIR.
  4. The temp subfolder is deleted.
"""

import shutil
import uuid
from pathlib import Path
from typing import Callable, Optional

try:
    import yt_dlp
except ImportError:
    raise ImportError(
        "yt_dlp is not installed.\n"
        "Run:  pip install yt_dlp"
    )

from library import MUSIC_DIR, TEMP_DIR, fmt_duration

ProgressCB = Optional[Callable[[int, str], None]]


# ── search ────────────────────────────────────────────────────────────────────

def search_youtube(query: str, max_results: int = 5) -> list[dict]:
    """
    Return up to *max_results* YouTube search results for *query*.
    Each result is a dict with keys: title, uploader, duration_str, url.
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        data = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)

    results = []
    for entry in data.get("entries") or []:
        if not entry:
            continue
        vid_id = entry.get("id") or ""
        url = (
            f"https://www.youtube.com/watch?v={vid_id}"
            if len(vid_id) == 11
            else entry.get("url", "")
        )
        results.append(
            {
                "title":        entry.get("title", "Unknown"),
                "uploader":     entry.get("uploader") or entry.get("channel", "Unknown"),
                "duration":     entry.get("duration", 0),
                "duration_str": fmt_duration(entry.get("duration", 0)),
                "url":          url,
            }
        )
    return results


# ── download ──────────────────────────────────────────────────────────────────

def download_track(url: str, progress_cb: ProgressCB = None) -> dict:
    """
    Download *url* as a 320 kbps MP3, move it to MUSIC_DIR, and return
    a track-metadata dict suitable for Library.add_track().

    *progress_cb(percent: int, message: str)* is called from the download
    thread — the caller must marshal UI updates to the main thread.
    """
    tmp = TEMP_DIR / uuid.uuid4().hex
    tmp.mkdir(parents=True, exist_ok=True)

    def _hook(d: dict) -> None:
        if not progress_cb:
            return
        status = d.get("status")
        if status == "downloading":
            raw = d.get("_percent_str", "0%").strip().rstrip("%")
            try:
                pct = int(float(raw) * 0.70)   # scale to 0–70 %
            except ValueError:
                pct = 0
            progress_cb(pct, f"Downloading…  {raw}%")
        elif status == "finished":
            progress_cb(75, "Converting to MP3…")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(tmp / "%(title)s.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }
        ],
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_hook],
        "restrictfilenames": True,   # keep filenames ASCII-safe
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    # Locate the freshly converted MP3
    mp3_files = list(tmp.glob("*.mp3"))
    if not mp3_files:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(
            "No MP3 found after conversion.\n"
            "Make sure ffmpeg is installed and available on PATH."
        )

    src  = mp3_files[0]
    dest = _unique_dest(MUSIC_DIR, src.name)

    shutil.move(str(src), str(dest))
    shutil.rmtree(tmp, ignore_errors=True)

    if progress_cb:
        progress_cb(100, "Done!")

    return {
        "title":    info.get("title") or src.stem,
        "artist":   info.get("uploader") or info.get("channel", "Unknown"),
        "duration": info.get("duration", 0),
        "file_path": str(dest),
        "quality":  "MP3 320kbps",
    }


def _unique_dest(directory: Path, filename: str) -> Path:
    """Return a Path that does not yet exist in *directory*."""
    dest = directory / filename
    stem, suffix = Path(filename).stem, Path(filename).suffix
    counter = 1
    while dest.exists():
        dest = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    return dest
