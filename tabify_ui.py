"""
tabify_ui.py — Desktop GUI for tabify.py
Usage: python tabify_ui.py

Wraps tabify.py's transcribe() function with sliders, presets, and a live
log. No new dependencies — tkinter ships with the standard Python install.

Note: the "Max note length (beats)" slider only has an effect once tabify.py
exposes a --max-note-beats flag and reads params["max_note_beats"] in
transcribe(). Until then it's accepted but silently ignored.
"""

import os
import sys
import json
import queue
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from tabify import (
    transcribe,
    ONSET_THRESHOLD,
    FRAME_THRESHOLD,
    MIN_NOTE_LENGTH,
    CHORD_WINDOW,
    MAX_NOTE_BEATS,
)

AUDIO_FILETYPES = [
    ("Audio files", "*.wav *.mp3 *.flac *.m4a"),
    ("All files", "*.*"),
]

# key, label, min, max, decimals, default, info text
TUNE_SPECS = [
    ("onset", "Onset threshold", 0.0, 1.0, 2, ONSET_THRESHOLD,
     "Gates whether a note is detected at all. Lower (e.g. 0.5) catches soft "
     "interior voices, harmonics, and lightly plucked notes, but also picks "
     "up more ghost notes and body-percussion transients. Higher (0.7+) is "
     "cleaner but can drop quiet inner chord voices. Tune this first — "
     "everything else is downstream of it."),
    ("frame", "Frame threshold", 0.0, 1.0, 2, FRAME_THRESHOLD,
     "Once a note's onset is accepted, this controls how long it keeps "
     "being tracked. Lower (e.g. 0.3) preserves long nylon-string decay and "
     "sustained bass tails. Higher (0.5+) drops notes sooner — useful if "
     "body percussion or room noise is making notes look longer than they "
     "were actually played."),
    ("min_note", "Min note length (ms)", 0, 300, 0, MIN_NOTE_LENGTH,
     "Any detected note shorter than this is discarded entirely. "
     "Percussion hits and palm slaps usually resolve in under 40ms; real "
     "fretted notes sustain 60-80ms or more. 100ms (default) filters "
     "percussion while keeping fast runs. Lower toward 40-60ms for "
     "classical tremolo or flamenco picado; raise toward 120ms+ for heavy "
     "body percussion."),
    ("chord_window", "Chord window (ms)", 0, 150, 0, CHORD_WINDOW,
     "Notes whose onsets fall within this window of each other are snapped "
     "to the same timestamp, turning a fast arpeggio sweep into a single "
     "chord event — the highest-impact post-processing parameter for "
     "fingerstyle. Raise (80-100ms) if slow strums still render as "
     "spread-out eighth notes in GP8. Lower (20-30ms) if fast single-note "
     "runs are being wrongly grouped into chords. 0 disables grouping "
     "entirely. Tune this last, after onset and frame."),
    ("max_note_beats", "Max note length (beats)", 0.1, 4.0, 1, MAX_NOTE_BEATS,
     "Caps any note's duration to this many beats at the detected BPM, so "
     "reverb tails don't render as long notes tied across bar lines. "
     "1 beat = 500ms at 120 BPM, 750ms at 80 BPM. Has no effect when "
     "'No max note' below is checked."),
]

# key, label, default, info text
OPTION_SPECS = [
    ("no_bends", "No bends", False,
     "Disables pitch-bend MIDI events. Basic Pitch otherwise writes bends "
     "for slides, vibrato, and string bends, which render as pitch curves "
     "in GP8. Turn on for classical/flamenco (no western bends), or if "
     "heavy reverb is registering as false bends."),
    ("denoise", "Denoise", False,
     "Applies spectral noise reduction before transcription — attenuates "
     "stationary hiss, hum, or room tone. Adds processing time and can "
     "subtly alter harmonic content, so it's off by default. Use it for "
     "untreated-room recordings with audible background noise; skip it for "
     "clean or studio audio."),
    ("no_dedup", "No dedup", False,
     "Disables duplicate-note removal. After chord quantization snaps two "
     "notes of the same pitch to one onset, you can get a stacked "
     "duplicate with no musical value. Leave this unchecked (dedup on) "
     "unless you're diagnosing a specific issue."),
    ("no_fix_overlaps", "No fix overlaps", False,
     "Disables overlap resolution. A guitar string can only sustain one "
     "pitch at a time — if reverb makes Basic Pitch 'see' a note still "
     "ringing when the same pitch strikes again, the first note's end is "
     "normally clamped to the second note's start. Disable only for "
     "diagnostic comparison."),
    ("no_detect_tempo", "No detect tempo", False,
     "Skips librosa BPM detection. By default the detected tempo is "
     "written into the MIDI header so GP8 lays notes on the correct beat "
     "grid. Disable if the detected BPM is clearly wrong (rubato, "
     "freely-played sections) or you'd rather set tempo manually in GP8 — "
     "MIDI will then use a flat 120 BPM grid."),
    ("no_max_note", "No max note", False,
     "Disables the note-length cap above entirely, letting notes sustain "
     "their full detected duration — including reverb tails. Disable only "
     "if you're transcribing a slow, sustained piece where long note "
     "durations are musically correct."),
]

DEFAULT_PRESETS = {
    "Classical":   {"onset": 0.5,  "frame": 0.3,  "min_note": 60, "chord_window": 30, "no_bends": True},
    "Flamenco":    {"onset": 0.65, "frame": 0.45, "min_note": 40, "chord_window": 20, "no_bends": True},
    "Fingerstyle": {"onset": 0.6,  "frame": 0.4,  "min_note": 80, "chord_window": 50, "no_bends": False},
}


def _presets_path() -> Path:
    """presets.json lives next to the script, or next to the .exe once frozen
    via PyInstaller — __file__ points into a temp dir for a onefile build,
    which would silently lose saved presets between runs."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent
    return base / "presets.json"


def load_presets() -> dict:
    path = _presets_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    save_presets(DEFAULT_PRESETS)
    return dict(DEFAULT_PRESETS)


def save_presets(presets: dict) -> None:
    path = _presets_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(presets, f, indent=2)


class QueueWriter:
    """Redirect print() output from the worker thread into a thread-safe queue."""

    def __init__(self, q):
        self.q = q

    def write(self, text):
        if text:
            self.q.put(("log", text))

    def flush(self):
        pass


class TabifyUI:
    def __init__(self, root):
        self.root = root
        root.title("tabify")
        root.geometry("640x800")
        root.minsize(560, 700)

        self.input_path = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.output_dir_customized = False

        self.log_queue = queue.Queue()
        self.running = False

        self.tune_vars = {}   # key -> {"value", "text", "lo", "hi", "decimals", "scale", "entry"}
        self.opt_vars = {}    # key -> BooleanVar
        self.presets = load_presets()

        self.info_var = tk.StringVar(
            value="Click the ⓘ next to any parameter to see what it does."
        )

        self._build_ui()
        self.root.after(100, self._poll_queue)

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}

        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        # Input file
        row = ttk.Frame(main)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="Input file", width=12).pack(side="left")
        ttk.Entry(row, textvariable=self.input_path, state="readonly").pack(
            side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(row, text="Browse…", command=self._browse_input).pack(side="left")

        # Output dir
        row = ttk.Frame(main)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="Output dir", width=12).pack(side="left")
        out_entry = ttk.Entry(row, textvariable=self.output_dir)
        out_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        out_entry.bind("<KeyRelease>", lambda e: self._mark_output_customized())
        ttk.Button(row, text="Browse…", command=self._browse_output).pack(side="left", padx=(0, 4))
        ttk.Button(row, text="Reset", command=self._reset_output).pack(side="left")

        ttk.Separator(main).pack(fill="x", pady=8)

        # Presets
        row = ttk.Frame(main)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="Presets", width=12).pack(side="left")
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(
            row, textvariable=self.preset_var, state="readonly", width=24)
        self.preset_combo.pack(side="left")
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)
        ttk.Button(row, text="Save as new preset…", command=self._open_save_preset_dialog).pack(
            side="left", padx=(10, 0))
        self._refresh_preset_list()

        ttk.Label(main, text="Tunable parameters", foreground="#666666").pack(
            anchor="w", padx=10, pady=(10, 2))

        for spec in TUNE_SPECS:
            self._build_tune_row(main, spec)

        ttk.Separator(main).pack(fill="x", pady=8)
        ttk.Label(main, text="Options", foreground="#666666").pack(
            anchor="w", padx=10, pady=(0, 2))

        opt_grid = ttk.Frame(main)
        opt_grid.pack(fill="x", padx=10)
        for i, spec in enumerate(OPTION_SPECS):
            self._build_option(opt_grid, spec, row=i // 2, col=i % 2)

        ttk.Separator(main).pack(fill="x", pady=8)

        # Info panel
        info_frame = ttk.LabelFrame(main, text="Details")
        info_frame.pack(fill="x", padx=10, pady=4)
        ttk.Label(info_frame, textvariable=self.info_var, wraplength=560,
                  justify="left").pack(fill="x", padx=8, pady=8)

        # Run + status
        run_row = ttk.Frame(main)
        run_row.pack(fill="x", padx=10, pady=(8, 4))
        self.run_button = ttk.Button(run_row, text="Run", command=self._on_run)
        self.run_button.pack(side="left")
        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(run_row, textvariable=self.status_var, foreground="#666666").pack(
            side="left", padx=10)

        # Log
        log_frame = ttk.Frame(main)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.log_text = tk.Text(log_frame, height=12, wrap="word", state="disabled")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _build_tune_row(self, parent, spec):
        key, label, lo, hi, decimals, default, info_text = spec
        value_var = tk.DoubleVar(value=default)
        text_var = tk.StringVar(value=self._fmt(default, decimals))
        self.tune_vars[key] = {
            "value": value_var, "text": text_var,
            "lo": lo, "hi": hi, "decimals": decimals,
        }

        row = ttk.Frame(parent)
        row.pack(fill="x", padx=10, pady=3)

        top = ttk.Frame(row)
        top.pack(fill="x")
        ttk.Label(top, text=label).pack(side="left")
        ttk.Button(top, text="ⓘ", width=3,
                   command=lambda t=info_text: self.info_var.set(t)).pack(side="left", padx=4)

        ctrl = ttk.Frame(row)
        ctrl.pack(fill="x")
        scale = ttk.Scale(ctrl, from_=lo, to=hi, orient="horizontal",
                           command=lambda v, k=key: self._on_scale(k, v))
        scale.set(default)
        scale.pack(side="left", fill="x", expand=True, padx=(0, 8))
        entry = ttk.Entry(ctrl, textvariable=text_var, width=8)
        entry.pack(side="left")
        entry.bind("<Return>", lambda e, k=key: self._on_entry_commit(k))
        entry.bind("<FocusOut>", lambda e, k=key: self._on_entry_commit(k))

        self.tune_vars[key]["scale"] = scale
        self.tune_vars[key]["entry"] = entry

    def _build_option(self, parent, spec, row, col):
        key, label, default, info_text = spec
        var = tk.BooleanVar(value=default)
        self.opt_vars[key] = var

        cell = ttk.Frame(parent)
        cell.grid(row=row, column=col, sticky="w", padx=6, pady=2)
        ttk.Checkbutton(cell, text=label, variable=var).pack(side="left")
        ttk.Button(cell, text="ⓘ", width=3,
                   command=lambda t=info_text: self.info_var.set(t)).pack(side="left", padx=4)

        if key == "no_max_note":
            var.trace_add("write", lambda *a: self._toggle_max_note_beats())

    # ── slider/entry sync ─────────────────────────────────────────────

    def _fmt(self, value, decimals):
        return f"{value:.{decimals}f}"

    def _on_scale(self, key, raw_value):
        state = self.tune_vars[key]
        v = round(float(raw_value), state["decimals"])
        state["value"].set(v)
        state["text"].set(self._fmt(v, state["decimals"]))

    def _on_entry_commit(self, key):
        state = self.tune_vars[key]
        try:
            v = float(state["text"].get())
        except ValueError:
            v = state["value"].get()
        v = max(state["lo"], min(state["hi"], v))
        v = round(v, state["decimals"])
        state["value"].set(v)
        state["text"].set(self._fmt(v, state["decimals"]))
        state["scale"].set(v)

    def _toggle_max_note_beats(self):
        disabled = self.opt_vars["no_max_note"].get()
        widget_state = "disabled" if disabled else "normal"
        row = self.tune_vars["max_note_beats"]
        row["scale"].configure(state=widget_state)
        row["entry"].configure(state=widget_state)

    def _apply_preset(self, name):
        preset = self.presets[name]
        for key, val in preset.items():
            if key in self.tune_vars:
                state = self.tune_vars[key]
                v = round(val, state["decimals"])
                state["value"].set(v)
                state["text"].set(self._fmt(v, state["decimals"]))
                state["scale"].set(v)
            elif key in self.opt_vars:
                self.opt_vars[key].set(val)
        self.info_var.set(f"Applied '{name}' preset.")

    def _refresh_preset_list(self):
        self.preset_combo.configure(values=list(self.presets.keys()))

    def _on_preset_selected(self, event=None):
        name = self.preset_var.get()
        if name:
            self._apply_preset(name)

    def _snapshot_current_params(self) -> dict:
        snapshot = {key: state["value"].get() for key, state in self.tune_vars.items()}
        snapshot.update({key: var.get() for key, var in self.opt_vars.items()})
        return snapshot

    def _open_save_preset_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Save Preset")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.grab_set()

        ttk.Label(dialog, text="Preset name:").pack(padx=12, pady=(12, 4), anchor="w")
        name_var = tk.StringVar()
        entry = ttk.Entry(dialog, textvariable=name_var, width=30)
        entry.pack(padx=12, pady=(0, 12), fill="x")
        entry.focus_set()

        btn_row = ttk.Frame(dialog)
        btn_row.pack(padx=12, pady=(0, 12), fill="x")

        def confirm():
            name = name_var.get().strip()
            if not name:
                messagebox.showerror("Save Preset", "Enter a preset name.", parent=dialog)
                return
            if name in self.presets and not messagebox.askyesno(
                    "Save Preset", f"A preset named '{name}' already exists. Overwrite?",
                    parent=dialog):
                return
            self.presets[name] = self._snapshot_current_params()
            save_presets(self.presets)
            self._refresh_preset_list()
            self.preset_var.set(name)
            dialog.destroy()

        def cancel():
            dialog.destroy()

        ttk.Button(btn_row, text="Cancel", command=cancel).pack(side="right")
        ttk.Button(btn_row, text="Save", command=confirm).pack(side="right", padx=(0, 6))

        entry.bind("<Return>", lambda e: confirm())
        dialog.bind("<Escape>", lambda e: cancel())

    # ── file & dir handling ────────────────────────────────────────────

    def _browse_input(self):
        path = filedialog.askopenfilename(title="Select audio file", filetypes=AUDIO_FILETYPES)
        if not path:
            return
        self.input_path.set(path)
        if not self.output_dir_customized:
            self.output_dir.set(str(Path(path).parent))

    def _browse_output(self):
        path = filedialog.askdirectory(title="Select output directory")
        if path:
            self.output_dir.set(path)
            self.output_dir_customized = True

    def _mark_output_customized(self):
        self.output_dir_customized = True

    def _reset_output(self):
        self.output_dir_customized = False
        if self.input_path.get():
            self.output_dir.set(str(Path(self.input_path.get()).parent))
        else:
            self.output_dir.set("")

    # ── run ────────────────────────────────────────────────────────────

    def _on_run(self):
        if self.running:
            return

        in_path = self.input_path.get()
        if not in_path or not Path(in_path).exists():
            messagebox.showerror("tabify", "Select a valid input audio file first.")
            return

        out_dir_str = self.output_dir.get().strip()
        if not out_dir_str:
            messagebox.showerror("tabify", "Output directory is empty.")
            return

        out_dir = Path(out_dir_str)
        ok, msg = self._validate_output_dir(out_dir)
        if not ok:
            messagebox.showerror("tabify", msg)
            return

        params = self._collect_params()
        output_path = out_dir / (Path(in_path).stem + ".mid")

        self.running = True
        self.run_button.configure(state="disabled")
        self.status_var.set("Running…")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

        thread = threading.Thread(
            target=self._worker, args=(Path(in_path), output_path, params), daemon=True
        )
        thread.start()

    def _validate_output_dir(self, out_dir: Path):
        if not out_dir.exists():
            return False, f"Output directory does not exist:\n{out_dir}"
        if not out_dir.is_dir():
            return False, f"Output path is not a directory:\n{out_dir}"
        if not os.access(str(out_dir), os.W_OK):
            return False, f"Output directory is not writable:\n{out_dir}"
        return True, ""

    def _collect_params(self):
        def v(key):
            return self.tune_vars[key]["value"].get()

        def o(key):
            return self.opt_vars[key].get()

        return {
            "onset":          v("onset"),
            "frame":          v("frame"),
            "min_note":       v("min_note"),
            "no_bends":       o("no_bends"),
            "denoise":        o("denoise"),
            "chord_window":   v("chord_window"),
            "dedup":          not o("no_dedup"),
            "fix_overlaps":   not o("no_fix_overlaps"),
            "detect_tempo":   not o("no_detect_tempo"),
            "max_note":       not o("no_max_note"),
            "max_note_beats": v("max_note_beats"),
        }

    def _worker(self, input_path, output_path, params):
        old_stdout = sys.stdout
        sys.stdout = QueueWriter(self.log_queue)
        try:
            transcribe(input_path, output_path, params)
            self.log_queue.put(("done", str(output_path)))
        except Exception as e:
            self.log_queue.put(("log", traceback.format_exc()))
            self.log_queue.put(("error", str(e)))
        finally:
            sys.stdout = old_stdout

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "log":
                    self.log_text.configure(state="normal")
                    self.log_text.insert("end", payload)
                    self.log_text.see("end")
                    self.log_text.configure(state="disabled")
                elif kind == "done":
                    self.running = False
                    self.run_button.configure(state="normal")
                    self.status_var.set("Done")
                    messagebox.showinfo("tabify", f"MIDI written:\n{payload}")
                elif kind == "error":
                    self.running = False
                    self.run_button.configure(state="normal")
                    self.status_var.set("Error")
                    messagebox.showerror("tabify", f"Transcription failed:\n{payload}")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)


def main():
    root = tk.Tk()
    TabifyUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()