"""
library.py — Track library and playlist management.

All data files and media are stored *relative to this script's location*:
  <script_dir>/music/      ← final MP3 files
  <script_dir>/temp/       ← temporary download workspace
  <script_dir>/library.json
  <script_dir>/playlists.json
"""

import json
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent.resolve()
MUSIC_DIR    = SCRIPT_DIR / "music"
TEMP_DIR     = SCRIPT_DIR / "temp"
LIBRARY_FILE = SCRIPT_DIR / "library.json"
PLAYLIST_FILE = SCRIPT_DIR / "playlists.json"


class Library:
    """Manages the track library and playlists, persisted as JSON."""

    def __init__(self):
        MUSIC_DIR.mkdir(parents=True, exist_ok=True)
        TEMP_DIR.mkdir(parents=True, exist_ok=True)

        self._tracks: list[dict]        = _load_json(LIBRARY_FILE, [])
        self._playlists: dict[str, list] = _load_json(PLAYLIST_FILE, {})

    # ── tracks ────────────────────────────────────────────────────────────────

    def all_tracks(self) -> list[dict]:
        return list(self._tracks)

    def add_track(self, track: dict) -> None:
        """Add a track dict; silently skip duplicates by file_path."""
        fp = track.get("file_path", "")
        if any(t["file_path"] == fp for t in self._tracks):
            return
        self._tracks.append(track)
        self._persist()

    def remove_track(self, file_path: str) -> None:
        """Remove track from library (and all playlists).  Caller deletes file."""
        self._tracks = [t for t in self._tracks if t["file_path"] != file_path]
        for name in self._playlists:
            self._playlists[name] = [
                fp for fp in self._playlists[name] if fp != file_path
            ]
        self._persist()

    # ── playlists ─────────────────────────────────────────────────────────────

    def playlist_names(self) -> list[str]:
        return list(self._playlists.keys())

    def create_playlist(self, name: str) -> bool:
        """Returns False if name already exists."""
        if name in self._playlists:
            return False
        self._playlists[name] = []
        self._persist()
        return True

    def delete_playlist(self, name: str) -> None:
        self._playlists.pop(name, None)
        self._persist()

    def playlist_tracks(self, name: str) -> list[dict]:
        fps = set(self._playlists.get(name, []))
        return [t for t in self._tracks if t["file_path"] in fps]

    def add_to_playlist(self, name: str, file_path: str) -> None:
        if name in self._playlists and file_path not in self._playlists[name]:
            self._playlists[name].append(file_path)
            self._persist()

    def remove_from_playlist(self, name: str, file_path: str) -> None:
        if name in self._playlists:
            self._playlists[name] = [
                fp for fp in self._playlists[name] if fp != file_path
            ]
            self._persist()

    # ── persistence ───────────────────────────────────────────────────────────

    def _persist(self) -> None:
        _save_json(LIBRARY_FILE, self._tracks)
        _save_json(PLAYLIST_FILE, self._playlists)


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def fmt_duration(seconds) -> str:
    """Format integer seconds as m:ss."""
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "?:??"
    return f"{s // 60}:{s % 60:02d}"
