"""
app.py — Music player UI (tkinter + pygame).

Usage:
    python app.py

Dependencies:
    pip install yt_dlp pygame
    system: ffmpeg  (brew install ffmpeg  /  choco install ffmpeg  /  apt install ffmpeg)
"""

import os
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

# ── audio back-end ─────────────────────────────────────────────────────────
try:
    import pygame
    pygame.mixer.pre_init(44100, -16, 2, 2048)
    pygame.mixer.init()
    AUDIO_OK = True
except Exception:
    AUDIO_OK = False

from downloader import download_track, search_youtube
from library import Library, fmt_duration

# ── palette ────────────────────────────────────────────────────────────────
BG       = "#0f0f0f"
SURFACE  = "#181818"
CARD     = "#202020"
HOVER    = "#2a2a2a"
ACCENT   = "#4f8ef7"
RED      = "#e05252"
GREEN    = "#4caf7d"
TEXT     = "#efefef"
DIM      = "#888888"
BORDER   = "#2c2c2c"
FONT     = "Helvetica"


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Reusable helpers                                                        ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def _set_bg_tree(widget, color: str) -> None:
    """Recursively set background colour on a widget and all descendants."""
    try:
        widget.configure(bg=color)
    except tk.TclError:
        pass
    for child in widget.winfo_children():
        _set_bg_tree(child, color)


class ScrollFrame(tk.Frame):
    """A vertically-scrollable container.  Children go inside self.inner."""

    def __init__(self, parent, bg=BG, **kw):
        super().__init__(parent, bg=bg, **kw)
        self._canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self._sb     = ttk.Scrollbar(self, orient="vertical",
                                     command=self._canvas.yview)
        self.inner   = tk.Frame(self._canvas, bg=bg)

        self._win = self._canvas.create_window((0, 0), window=self.inner,
                                               anchor="nw")
        self._canvas.configure(yscrollcommand=self._sb.set)

        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.inner.bind("<Configure>", self._on_inner)
        self._canvas.bind("<Configure>", self._on_canvas)
        # Mouse-wheel (cross-platform)
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self._canvas.bind(seq, self._scroll)
            self.inner.bind(seq, self._scroll)

    def _on_inner(self, _):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas(self, e):
        self._canvas.itemconfig(self._win, width=e.width)

    def _scroll(self, e):
        if e.num == 4:
            self._canvas.yview_scroll(-1, "units")
        elif e.num == 5:
            self._canvas.yview_scroll(1, "units")
        else:
            self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Track row — used in All Songs and Playlist views                       ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class TrackRow(tk.Frame):
    """
    A single song row.
    Buttons shown depend on *show_remove_from_playlist* flag:
      False  →  library view: [title | artist | duration | + | ×]
      True   →  playlist view: [title | artist | duration | −]
    """

    def __init__(self, parent, track: dict, app, playlist_name: str = None,
                 on_refresh=None, bg=CARD):
        super().__init__(parent, bg=bg, cursor="hand2")
        self._track   = track
        self._app     = app
        self._pl_name = playlist_name
        self._refresh = on_refresh
        self._bg      = bg

        self._build(bg)
        self._hover_binds()

    def _build(self, bg):
        # Play on double-click
        self.bind("<Double-Button-1>", lambda _: self._app.play_track(self._track))

        pad = dict(padx=6, pady=10)

        # ▶ icon
        tk.Label(self, text="▶", bg=bg, fg=DIM,
                 font=(FONT, 11)).pack(side=tk.LEFT, **pad)

        # Title
        title = (self._track.get("title") or "Unknown")[:60]
        tk.Label(self, text=title, bg=bg, fg=TEXT,
                 font=(FONT, 11), anchor="w").pack(side=tk.LEFT, **pad)

        # Artist (right-aligned flex)
        artist = (self._track.get("artist") or "")[:40]
        tk.Label(self, text=artist, bg=bg, fg=DIM,
                 font=(FONT, 10), anchor="w").pack(side=tk.LEFT, expand=True,
                                                    padx=6)

        # Duration
        dur = fmt_duration(self._track.get("duration", 0))
        tk.Label(self, text=dur, bg=bg, fg=DIM,
                 font=(FONT, 10), width=5).pack(side=tk.LEFT, **pad)

        if self._pl_name:
            # Remove from playlist
            _btn(self, "−", RED, self._remove_from_playlist).pack(
                side=tk.RIGHT, padx=(2, 8))
        else:
            # Add to playlist
            _btn(self, "+", GREEN, self._add_to_playlist).pack(
                side=tk.RIGHT, padx=2)
            # Delete
            _btn(self, "×", RED, self._delete).pack(
                side=tk.RIGHT, padx=(2, 8))

    # ── actions ───────────────────────────────────────────────────────────

    def _delete(self):
        title = self._track.get("title", "this track")
        if not messagebox.askyesno(
            "Delete track",
            f"Remove \"{title}\" from your library and delete the file?",
            parent=self._app,
        ):
            return
        fp = self._track["file_path"]
        self._app.library.remove_track(fp)
        try:
            if os.path.exists(fp):
                os.remove(fp)
        except OSError as exc:
            messagebox.showerror("Error", f"Could not delete file:\n{exc}",
                                 parent=self._app)
        if self._refresh:
            self._refresh()

    def _add_to_playlist(self):
        names = self._app.library.playlist_names()
        if not names:
            messagebox.showinfo("No playlists",
                                "Create a playlist first using the + button "
                                "in the sidebar.",
                                parent=self._app)
            return
        _PickPlaylistDialog(self._app, names,
                            lambda n: self._do_add(n))

    def _do_add(self, name: str):
        self._app.library.add_to_playlist(name, self._track["file_path"])
        self._app.sidebar.refresh_playlists()

    def _remove_from_playlist(self):
        self._app.library.remove_from_playlist(
            self._pl_name, self._track["file_path"]
        )
        if self._refresh:
            self._refresh()

    # ── hover highlight ───────────────────────────────────────────────────

    def _hover_binds(self):
        self.bind("<Enter>", lambda _: _set_bg_tree(self, HOVER))
        self.bind("<Leave>", lambda _: _set_bg_tree(self, self._bg))


def _btn(parent, label: str, color: str, cmd) -> tk.Button:
    return tk.Button(
        parent, text=label, bg=color, fg=TEXT,
        font=(FONT, 11, "bold"), bd=0, padx=6, pady=3,
        cursor="hand2", relief="flat", activebackground=color,
        command=cmd,
    )


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Pick-playlist dialog                                                   ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class _PickPlaylistDialog(tk.Toplevel):
    def __init__(self, parent, names: list[str], callback):
        super().__init__(parent)
        self.title("Add to Playlist")
        self.configure(bg=BG)
        self.resizable(False, False)

        tk.Label(self, text="Select a playlist", bg=BG, fg=TEXT,
                 font=(FONT, 12, "bold")).pack(pady=(14, 8), padx=20)

        for name in names:
            tk.Button(
                self, text=name, bg=CARD, fg=TEXT,
                font=(FONT, 11), bd=0, padx=14, pady=7,
                cursor="hand2", relief="flat",
                activebackground=HOVER,
                command=lambda n=name: self._pick(n, callback),
            ).pack(fill=tk.X, padx=20, pady=3)

        tk.Button(self, text="Cancel", bg=SURFACE, fg=DIM,
                  font=(FONT, 10), bd=0, padx=10, pady=6,
                  cursor="hand2", relief="flat",
                  command=self.destroy).pack(pady=(6, 14))

        self.grab_set()
        self.transient(parent)

    def _pick(self, name: str, callback):
        callback(name)
        self.destroy()


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Views                                                                  ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class AllSongsView(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self._app = app
        self._scroll = None
        self._build_static()

    def _build_static(self):
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill=tk.X, padx=30, pady=(28, 12))

        tk.Label(hdr, text="All Songs", bg=BG, fg=TEXT,
                 font=(FONT, 22, "bold")).pack(side=tk.LEFT)

        self._count_var = tk.StringVar()
        tk.Label(hdr, textvariable=self._count_var, bg=BG, fg=DIM,
                 font=(FONT, 11)).pack(side=tk.LEFT, padx=14)

        # Column headers
        cols = tk.Frame(self, bg=SURFACE)
        cols.pack(fill=tk.X, padx=30)
        lbl_title = tk.Label(cols, text="TITLE", bg=SURFACE, fg=DIM,
                             font=(FONT, 9), anchor="w")
        lbl_title.pack(side=tk.LEFT, padx=8, pady=6, fill=tk.X, expand=True)
        lbl_artist = tk.Label(cols, text="ARTIST", bg=SURFACE, fg=DIM,
                              font=(FONT, 9), anchor="w")
        lbl_artist.pack(side=tk.LEFT, padx=8, pady=6, fill=tk.X, expand=True)
        lbl_dur = tk.Label(cols, text="DURATION", bg=SURFACE, fg=DIM,
                           font=(FONT, 9), anchor="w", width=10)
        lbl_dur.pack(side=tk.LEFT, padx=8, pady=6)

        self._list_area = tk.Frame(self, bg=BG)
        self._list_area.pack(fill=tk.BOTH, expand=True, padx=30, pady=(4, 0))

    def refresh(self):
        # Destroy old scroll frame
        for w in self._list_area.winfo_children():
            w.destroy()

        tracks = self._app.library.all_tracks()
        self._count_var.set(f"{len(tracks)} track{'s' if len(tracks) != 1 else ''}")

        if not tracks:
            tk.Label(self._list_area,
                     text="No songs yet.\nUse 🔍 Search to download some!",
                     bg=BG, fg=DIM, font=(FONT, 13),
                     justify=tk.CENTER).pack(pady=60)
            return

        sf = ScrollFrame(self._list_area, bg=BG)
        sf.pack(fill=tk.BOTH, expand=True)

        for i, track in enumerate(tracks):
            bg = CARD if i % 2 == 0 else SURFACE
            row = TrackRow(sf.inner, track, self._app,
                           on_refresh=self.refresh, bg=bg)
            row.pack(fill=tk.X, pady=1)


# ─────────────────────────────────────────────────────────────────────────────

class SearchView(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self._app         = app
        self._search_var  = tk.StringVar()
        self._results: list[dict] = []
        self._dl_active   = False
        self._build()

    def _build(self):
        tk.Label(self, text="Search YouTube", bg=BG, fg=TEXT,
                 font=(FONT, 22, "bold")).pack(pady=(28, 16), padx=30,
                                               anchor="w")

        # Input row
        row = tk.Frame(self, bg=BG)
        row.pack(fill=tk.X, padx=30, pady=(0, 18))

        entry = tk.Entry(row, textvariable=self._search_var, bg=CARD, fg=TEXT,
                         insertbackground=TEXT, font=(FONT, 12),
                         relief="flat", bd=8)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)
        entry.bind("<Return>", lambda _: self._do_search())
        self._entry = entry

        tk.Button(row, text="Search", bg=ACCENT, fg=TEXT, font=(FONT, 11),
                  bd=0, padx=16, pady=6, relief="flat",
                  cursor="hand2", activebackground=ACCENT,
                  command=self._do_search).pack(side=tk.LEFT, padx=(8, 0))

        # Status label
        self._status_var = tk.StringVar()
        tk.Label(self, textvariable=self._status_var, bg=BG, fg=DIM,
                 font=(FONT, 10)).pack(anchor="w", padx=30)

        # Results area
        self._results_frame = tk.Frame(self, bg=BG)
        self._results_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=8)

    def focus_entry(self):
        self._entry.focus_set()

    def _do_search(self):
        query = self._search_var.get().strip()
        if not query:
            return
        self._status_var.set("Searching…")
        self._clear_results()

        def run():
            try:
                results = search_youtube(query)
                self.after(0, lambda: self._show_results(results))
            except Exception as exc:
                self.after(0, lambda: self._status_var.set(f"Error: {exc}"))

        threading.Thread(target=run, daemon=True).start()

    def _clear_results(self):
        for w in self._results_frame.winfo_children():
            w.destroy()

    def _show_results(self, results: list[dict]):
        self._results = results
        self._clear_results()
        if not results:
            self._status_var.set("No results found.")
            return
        self._status_var.set(f"Top {len(results)} results:")

        for idx, r in enumerate(results):
            self._build_result_row(idx, r)

    def _build_result_row(self, idx: int, result: dict):
        bg = CARD if idx % 2 == 0 else SURFACE
        row = tk.Frame(self._results_frame, bg=bg)
        row.pack(fill=tk.X, pady=1)

        # Info side
        info = tk.Frame(row, bg=bg)
        info.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10, pady=8)

        tk.Label(info, text=result["title"][:70], bg=bg, fg=TEXT,
                 font=(FONT, 11), anchor="w").pack(anchor="w")
        tk.Label(info,
                 text=f"{result['uploader']}  •  {result['duration_str']}",
                 bg=bg, fg=DIM, font=(FONT, 9), anchor="w").pack(anchor="w")

        # Download button / progress container
        btn_area = tk.Frame(row, bg=bg, width=160)
        btn_area.pack(side=tk.RIGHT, padx=10, pady=8)
        btn_area.pack_propagate(False)

        dl_btn = tk.Button(
            btn_area, text="⬇  Download", bg=ACCENT, fg=TEXT,
            font=(FONT, 10), bd=0, padx=10, pady=5, relief="flat",
            cursor="hand2", activebackground=ACCENT,
        )
        dl_btn.pack(fill=tk.X)

        prog_var   = tk.IntVar(value=0)
        msg_var    = tk.StringVar(value="")
        prog_bar   = ttk.Progressbar(btn_area, variable=prog_var, maximum=100,
                                     mode="determinate", length=140)
        msg_label  = tk.Label(btn_area, textvariable=msg_var, bg=bg, fg=DIM,
                              font=(FONT, 8))

        def start_download(r=result, db=dl_btn, pb=prog_bar, ml=msg_label,
                           pv=prog_var, mv=msg_var):
            if self._dl_active:
                messagebox.showinfo("Busy",
                                    "Please wait for the current download to finish.",
                                    parent=self._app)
                return
            self._dl_active = True
            db.pack_forget()
            pb.pack(fill=tk.X)
            ml.pack()

            def progress(pct, msg):
                self.after(0, lambda: (pv.set(pct), mv.set(msg)))

            def run():
                try:
                    track = download_track(r["url"], progress_cb=progress)
                    self._app.library.add_track(track)
                    self.after(0, lambda: self._on_done(track["title"]))
                except Exception as exc:
                    self.after(0, lambda: self._on_error(str(exc),
                                                         db, pb, ml, pv, mv))
                finally:
                    self._dl_active = False

            threading.Thread(target=run, daemon=True).start()

        dl_btn.configure(command=start_download)

    def _on_done(self, title: str):
        self._status_var.set(f"✓  Downloaded: {title}")
        self._app.sidebar.refresh_playlists()
        # Refresh all-songs view in background so it's ready
        self._app.all_songs_view.refresh()

    def _on_error(self, msg, btn, pb, ml, pv, mv):
        pb.pack_forget()
        ml.pack_forget()
        btn.configure(text="⬇  Retry")
        btn.pack(fill=tk.X)
        messagebox.showerror("Download failed", msg, parent=self._app)


# ─────────────────────────────────────────────────────────────────────────────

class PlaylistView(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self._app  = app
        self._name = ""
        self._build_static()

    def _build_static(self):
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill=tk.X, padx=30, pady=(28, 12))

        self._title_var = tk.StringVar()
        tk.Label(hdr, textvariable=self._title_var, bg=BG, fg=TEXT,
                 font=(FONT, 22, "bold")).pack(side=tk.LEFT)

        tk.Button(hdr, text="Delete playlist", bg=RED, fg=TEXT,
                  font=(FONT, 9), bd=0, padx=10, pady=4, relief="flat",
                  cursor="hand2", activebackground=RED,
                  command=self._delete_playlist).pack(side=tk.RIGHT)

        self._list_area = tk.Frame(self, bg=BG)
        self._list_area.pack(fill=tk.BOTH, expand=True, padx=30)

    def load(self, name: str):
        self._name = name
        self._title_var.set(f"📋  {name}")
        self.refresh()

    def refresh(self):
        for w in self._list_area.winfo_children():
            w.destroy()

        tracks = self._app.library.playlist_tracks(self._name)
        if not tracks:
            tk.Label(self._list_area,
                     text="Playlist is empty.\nAdd songs from All Songs → +",
                     bg=BG, fg=DIM, font=(FONT, 13),
                     justify=tk.CENTER).pack(pady=60)
            return

        sf = ScrollFrame(self._list_area, bg=BG)
        sf.pack(fill=tk.BOTH, expand=True)

        for i, track in enumerate(tracks):
            bg = CARD if i % 2 == 0 else SURFACE
            row = TrackRow(sf.inner, track, self._app,
                           playlist_name=self._name,
                           on_refresh=self.refresh, bg=bg)
            row.pack(fill=tk.X, pady=1)

    def _delete_playlist(self):
        if not messagebox.askyesno("Delete playlist",
                                   f"Delete playlist \"{self._name}\" ?",
                                   parent=self._app):
            return
        self._app.library.delete_playlist(self._name)
        self._app.sidebar.refresh_playlists()
        self._app.show_all_songs()


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Sidebar                                                                ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class Sidebar(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=SURFACE, width=200)
        self.pack_propagate(False)
        self._app = app
        self._build()

    def _build(self):
        tk.Label(self, text="LIBRARY", bg=SURFACE, fg=DIM,
                 font=(FONT, 8, "bold")).pack(
            anchor="w", padx=16, pady=(24, 4)
        )

        tk.Button(
            self, text="🎵  All Songs", bg=SURFACE, fg=TEXT,
            font=(FONT, 11), bd=0, anchor="w", padx=16, pady=8,
            relief="flat", cursor="hand2", activebackground=HOVER,
            command=self._app.show_all_songs,
        ).pack(fill=tk.X)

        # Playlists section
        pl_hdr = tk.Frame(self, bg=SURFACE)
        pl_hdr.pack(fill=tk.X, padx=16, pady=(16, 4))

        tk.Label(pl_hdr, text="PLAYLISTS", bg=SURFACE, fg=DIM,
                 font=(FONT, 8, "bold")).pack(side=tk.LEFT)

        tk.Button(
            pl_hdr, text="+", bg=SURFACE, fg=ACCENT,
            font=(FONT, 14, "bold"), bd=0, pady=0, padx=4,
            relief="flat", cursor="hand2", activebackground=SURFACE,
            command=self._create_playlist,
        ).pack(side=tk.RIGHT)

        self._pl_frame = tk.Frame(self, bg=SURFACE)
        self._pl_frame.pack(fill=tk.BOTH, expand=True)
        self.refresh_playlists()

    def refresh_playlists(self):
        for w in self._pl_frame.winfo_children():
            w.destroy()
        for name in self._app.library.playlist_names():
            tk.Button(
                self._pl_frame, text=f"  📋  {name}",
                bg=SURFACE, fg=TEXT, font=(FONT, 10),
                bd=0, anchor="w", padx=16, pady=6,
                relief="flat", cursor="hand2", activebackground=HOVER,
                command=lambda n=name: self._app.show_playlist(n),
            ).pack(fill=tk.X)

    def _create_playlist(self):
        name = simpledialog.askstring("New Playlist", "Playlist name:",
                                       parent=self._app)
        if not name or not name.strip():
            return
        name = name.strip()
        if not self._app.library.create_playlist(name):
            messagebox.showinfo("Exists", f'Playlist "{name}" already exists.',
                                parent=self._app)
            return
        self.refresh_playlists()


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Player bar                                                             ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class PlayerBar(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=SURFACE, height=88)
        self.pack_propagate(False)
        self._app     = app
        self._dur     = 0        # duration in seconds
        self._elapsed = 0.0      # seconds played
        self._t0      = 0.0      # time.time() when play() / unpause() called
        self._paused  = False
        self._build()

    # ── build ─────────────────────────────────────────────────────────────

    def _build(self):
        tk.Frame(self, bg=BORDER, height=1).pack(fill=tk.X)

        inner = tk.Frame(self, bg=SURFACE)
        inner.pack(fill=tk.BOTH, expand=True, padx=18)

        # Track info
        info = tk.Frame(inner, bg=SURFACE, width=240)
        info.pack(side=tk.LEFT, fill=tk.Y)
        info.pack_propagate(False)

        self._title_var  = tk.StringVar(value="No track selected")
        self._artist_var = tk.StringVar(value="Double-click a song to play")

        tk.Label(info, textvariable=self._title_var, bg=SURFACE, fg=TEXT,
                 font=(FONT, 11, "bold"), anchor="w").pack(anchor="w",
                                                           pady=(18, 2))
        tk.Label(info, textvariable=self._artist_var, bg=SURFACE, fg=DIM,
                 font=(FONT, 9), anchor="w").pack(anchor="w")

        # Centre controls
        ctrl = tk.Frame(inner, bg=SURFACE)
        ctrl.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)

        btn_row = tk.Frame(ctrl, bg=SURFACE)
        btn_row.pack(pady=(14, 4))

        self._play_btn = tk.Button(
            btn_row, text="▶", bg=ACCENT, fg=TEXT,
            font=(FONT, 14), bd=0, width=3, pady=4,
            relief="flat", cursor="hand2", activebackground=ACCENT,
            command=self._toggle,
        )
        self._play_btn.pack()

        # Seek row
        seek = tk.Frame(ctrl, bg=SURFACE)
        seek.pack(fill=tk.X)

        self._pos_var = tk.StringVar(value="0:00")
        self._dur_var = tk.StringVar(value="0:00")

        tk.Label(seek, textvariable=self._pos_var, bg=SURFACE, fg=DIM,
                 font=(FONT, 9), width=4).pack(side=tk.LEFT)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Player.Horizontal.TScale",
                        background=SURFACE, troughcolor=BORDER,
                        sliderthickness=10, sliderrelief="flat")

        self._seek_var = tk.DoubleVar()
        self._seek = ttk.Scale(seek, from_=0, to=100, variable=self._seek_var,
                               orient=tk.HORIZONTAL,
                               style="Player.Horizontal.TScale")
        self._seek.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        tk.Label(seek, textvariable=self._dur_var, bg=SURFACE, fg=DIM,
                 font=(FONT, 9), width=4).pack(side=tk.LEFT)

        # Volume
        vol_frm = tk.Frame(inner, bg=SURFACE, width=160)
        vol_frm.pack(side=tk.RIGHT, fill=tk.Y)
        vol_frm.pack_propagate(False)

        vol_inner = tk.Frame(vol_frm, bg=SURFACE)
        vol_inner.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, pady=30)

        tk.Label(vol_inner, text="🔊", bg=SURFACE, fg=TEXT,
                 font=(FONT, 12)).pack(side=tk.LEFT)

        self._vol_var = tk.DoubleVar(value=70)
        ttk.Scale(vol_inner, from_=0, to=100, variable=self._vol_var,
                  orient=tk.HORIZONTAL,
                  style="Player.Horizontal.TScale").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 10)
        )
        self._vol_var.trace_add("write", self._on_vol)

    # ── playback ──────────────────────────────────────────────────────────

    def start(self, track: dict):
        if not AUDIO_OK:
            messagebox.showerror("Audio unavailable",
                                 "pygame is not installed.\n"
                                 "Run: pip install pygame",
                                 parent=self._app)
            return
        fp = track.get("file_path", "")
        if not os.path.exists(fp):
            messagebox.showerror("File not found",
                                 f"Cannot find:\n{fp}", parent=self._app)
            return

        pygame.mixer.music.load(fp)
        pygame.mixer.music.play()
        pygame.mixer.music.set_volume(self._vol_var.get() / 100)

        self._dur     = track.get("duration", 0) or 0
        self._t0      = time.time()
        self._elapsed = 0.0
        self._paused  = False

        self._title_var.set(track.get("title", "Unknown"))
        self._artist_var.set(track.get("artist", ""))
        self._play_btn.configure(text="⏸")
        self._dur_var.set(fmt_duration(self._dur))

    def _toggle(self):
        if not AUDIO_OK:
            return
        if not pygame.mixer.music.get_busy() and not self._paused:
            return
        if self._paused:
            pygame.mixer.music.unpause()
            self._t0      = time.time() - self._elapsed
            self._paused  = False
            self._play_btn.configure(text="⏸")
        else:
            self._elapsed = time.time() - self._t0
            pygame.mixer.music.pause()
            self._paused  = True
            self._play_btn.configure(text="▶")

    def tick(self):
        """Called every 500 ms from the main loop."""
        if not AUDIO_OK or self._paused:
            return
        if not pygame.mixer.music.get_busy():
            return
        self._elapsed = time.time() - self._t0
        m, s = divmod(int(self._elapsed), 60)
        self._pos_var.set(f"{m}:{s:02d}")
        if self._dur > 0:
            self._seek_var.set(min(100, (self._elapsed / self._dur) * 100))

    def _on_vol(self, *_):
        if AUDIO_OK:
            pygame.mixer.music.set_volume(self._vol_var.get() / 100)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Main application window                                                ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class MusicApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Music Player")
        self.geometry("1180x740")
        self.minsize(860, 580)
        self.configure(bg=BG)

        self.library = Library()
        self._build()
        self._tick()

    # ── layout ────────────────────────────────────────────────────────────

    def _build(self):
        # ─ top bar ─
        top = tk.Frame(self, bg=SURFACE, height=54)
        top.pack(fill=tk.X)
        top.pack_propagate(False)
        tk.Frame(top, bg=BORDER, height=1).pack(side=tk.BOTTOM, fill=tk.X)

        tk.Label(top, text="♪  Music", bg=SURFACE, fg=TEXT,
                 font=(FONT, 16, "bold")).pack(side=tk.LEFT, padx=20)

        tk.Button(
            top, text="🔍  Search", bg=ACCENT, fg=TEXT,
            font=(FONT, 11), bd=0, padx=14, pady=6,
            relief="flat", cursor="hand2", activebackground=ACCENT,
            command=self.show_search,
        ).pack(side=tk.RIGHT, padx=18, pady=10)

        # ─ body ─
        body = tk.Frame(self, bg=BG)
        body.pack(fill=tk.BOTH, expand=True)

        self.sidebar = Sidebar(body, self)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)

        tk.Frame(body, bg=BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y)

        content = tk.Frame(body, bg=BG)
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Views stacked on top of each other
        self.all_songs_view  = AllSongsView(content, self)
        self.search_view     = SearchView(content, self)
        self.playlist_view   = PlaylistView(content, self)

        for v in (self.all_songs_view, self.search_view, self.playlist_view):
            v.place(relx=0, rely=0, relwidth=1, relheight=1)

        # ─ player bar ─
        self.player_bar = PlayerBar(self, self)
        self.player_bar.pack(fill=tk.X, side=tk.BOTTOM)

        self.show_all_songs()

    # ── navigation ────────────────────────────────────────────────────────

    def show_all_songs(self):
        self.all_songs_view.refresh()
        self.all_songs_view.lift()

    def show_search(self):
        self.search_view.lift()
        self.search_view.focus_entry()

    def show_playlist(self, name: str):
        self.playlist_view.load(name)
        self.playlist_view.lift()

    # ── playback ──────────────────────────────────────────────────────────

    def play_track(self, track: dict):
        self.player_bar.start(track)

    # ── timer ─────────────────────────────────────────────────────────────

    def _tick(self):
        self.player_bar.tick()
        self.after(500, self._tick)


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = MusicApp()
    app.mainloop()
