"""
tabify.py — Solo fingerstyle guitar audio → MIDI
Usage: python tabify.py <input_audio> [output_midi]

Tuned for:
  - Single guitar recordings (no source separation needed)
  - Fingerstyle polyphony (simultaneous bass + melody)
  - Heavy effects (reverb, compression) — pitch detection is robust to these
  - Body percussion / thumps — filtered out via --min-note
"""

import sys
import argparse
import os
from pathlib import Path

# ── Basic Pitch defaults (tuned for solo fingerstyle) ─────────────────────────

ONSET_THRESHOLD   = 0.6     # Lower = more notes. Raise to 0.6+ to cut ghost notes.
FRAME_THRESHOLD   = 0.4     # Raise to 0.4+ if body percussion creates noise.
MIN_NOTE_LENGTH   = 100.0   # ms. Percussion hits are <40ms; real notes sustain longer.
MIN_FREQ          = 82.41   # Hz = E2 (open low E string)
MAX_FREQ          = 1318.5  # Hz = E6 (practical guitar ceiling)
CHORD_WINDOW      = 50.0    # ms. Notes within this window are snapped to the same onset.
                            # Collapses fast arpeggio sweeps into chords. 0 = disabled.
MAX_NOTE_BEATS    = 1.0     # beats. Maximum note duration relative to detected BPM.
                            # Prevents sustained notes from bleeding into subsequent bars.
                            # Falls back to 500ms if tempo detection is disabled.

# ─────────────────────────────────────────────────────────────────────────────


def quantize_chords(notes: list, window_ms: float) -> tuple:
    """Snap near-simultaneous notes to the same onset (chord grouping).

    Notes within window_ms of the first note in a group are snapped to that
    group's earliest onset. Collapses fast arpeggio sweeps into chords.

    Returns (modified notes list, number of groups collapsed).
    """
    if not notes or window_ms <= 0:
        return notes, 0

    window_sec = window_ms / 1000.0
    notes = sorted(notes, key=lambda n: n.start)

    i = 0
    groups_collapsed = 0
    while i < len(notes):
        group_start = notes[i].start
        j = i + 1
        while j < len(notes) and notes[j].start - group_start <= window_sec:
            notes[j].start = group_start
            j += 1
        if j > i + 1:
            groups_collapsed += 1
        i = j

    return notes, groups_collapsed


def remove_duplicates(notes: list) -> tuple:
    """Remove notes with identical (pitch, start) pairs.

    After chord quantization, fast arpeggios snapped to the same onset can
    produce duplicate pitch events. Keeps the first occurrence (highest
    velocity in a tie is irrelevant — GP6 renders both as one note anyway).

    Returns (deduplicated notes list, number of duplicates removed).
    """
    seen = set()
    unique = []
    dupes = 0
    for note in notes:
        key = (note.pitch, note.start)
        if key in seen:
            dupes += 1
        else:
            seen.add(key)
            unique.append(note)
    return unique, dupes


def resolve_overlaps(notes: list) -> tuple:
    """Truncate notes that overlap with the next note of the same pitch.

    A guitar string can only sustain one pitch at a time. If Basic Pitch
    detects the same pitch twice before the first ends (common with reverb
    bleed), the first note's end is clamped to the second note's start.

    Returns (modified notes list, number of overlaps resolved).
    """
    from collections import defaultdict

    by_pitch = defaultdict(list)
    for note in notes:
        by_pitch[note.pitch].append(note)

    resolved = 0
    for pitch_notes in by_pitch.values():
        pitch_notes.sort(key=lambda n: n.start)
        for i in range(len(pitch_notes) - 1):
            curr, nxt = pitch_notes[i], pitch_notes[i + 1]
            if curr.end > nxt.start:
                curr.end = nxt.start
                resolved += 1

    return notes, resolved


def clip_note_lengths(notes: list, bpm: float, max_beats: float) -> tuple:
    """Cap note duration to max_beats relative to detected BPM.

    Prevents sustained notes from bleeding into subsequent bars.
    max_duration_sec = (60 / bpm) * max_beats

    Returns (modified notes list, number of notes clipped).
    """
    max_sec = (60.0 / bpm) * max_beats
    clipped = 0
    for note in notes:
        if (note.end - note.start) > max_sec:
            note.end = note.start + max_sec
            clipped += 1
    return notes, clipped


def detect_tempo(audio_path: str) -> float:
    """Detect BPM from audio. Returns bpm as float."""
    import librosa
    y, sr = librosa.load(audio_path, sr=None, mono=True)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    return float(tempo)


def apply_tempo_to_midi(midi_data, bpm: float):
    """Rebuild PrettyMIDI with correct initial_tempo.

    Note times are in seconds so positions are unaffected —
    only the beat grid GP8 displays changes.
    """
    import pretty_midi
    new_midi = pretty_midi.PrettyMIDI(
        initial_tempo=bpm,
        resolution=midi_data.resolution,
    )
    new_midi.instruments = midi_data.instruments
    return new_midi


def transcribe(input_path: Path, output_path: Path, params: dict) -> None:
    from basic_pitch.inference import predict
    from basic_pitch import ICASSP_2022_MODEL_PATH
    import pretty_midi

    print(f"[1/3] Transcribing: {input_path.name}")
    print(f"      onset={params['onset']}  frame={params['frame']}  "
          f"min_note={params['min_note']}ms  pitch_bends={not params['no_bends']}")

    actual_audio_path = str(input_path)
    temp_path = None

    if params.get("denoise"):
        print("      Applying noise reduction (this takes a moment)...")
        import librosa
        import soundfile as sf
        import noisereduce as nr
        
        audio_data, rate = librosa.load(str(input_path), sr=None, mono=True)
        cleaned_audio = nr.reduce_noise(y=audio_data, sr=rate, prop_decrease=0.7, stationary=True)
        
        temp_path = input_path.with_name(f".temp_{input_path.stem}.wav")
        sf.write(str(temp_path), cleaned_audio, rate)
        actual_audio_path = str(temp_path)

    _, midi_data, note_events = predict(
        audio_path=actual_audio_path,
        model_or_model_path=ICASSP_2022_MODEL_PATH,
        onset_threshold=params["onset"],
        frame_threshold=params["frame"],
        minimum_note_length=params["min_note"],
        minimum_frequency=MIN_FREQ,
        maximum_frequency=MAX_FREQ,
        multiple_pitch_bends=not params["no_bends"],
        melodia_trick=True,
    )

    if temp_path and os.path.exists(temp_path):
        os.remove(temp_path)

    note_count = len(note_events) if note_events else 0
    print(f"      Detected {note_count} notes")

    # Create a single Acoustic Guitar track (Program 25 = Steel String)
    single_track = pretty_midi.Instrument(program=25)

    for inst in midi_data.instruments:
        single_track.notes.extend(inst.notes)

    single_track.notes.sort(key=lambda x: x.start)

    # ── Tempo detection (before post-processing so BPM is available) ─────────
    FALLBACK_BPM = 120.0
    if params["detect_tempo"]:
        bpm = detect_tempo(actual_audio_path)
    else:
        bpm = FALLBACK_BPM

    # ── Post-processing ───────────────────────────────────────────────────────
    print(f"[2/3] Post-processing...")

    # Chord quantization (always on — use --chord-window 0 to disable)
    single_track.notes, groups = quantize_chords(single_track.notes, params["chord_window"])
    if params["chord_window"] > 0:
        print(f"      chord quantization  → {groups} group(s) collapsed")

    # Duplicate removal
    if params["dedup"]:
        single_track.notes, dupes = remove_duplicates(single_track.notes)
        print(f"      duplicate removal   → {dupes} duplicate(s) removed")

    # Overlap resolution
    if params["fix_overlaps"]:
        single_track.notes, overlaps = resolve_overlaps(single_track.notes)
        print(f"      overlap resolution  → {overlaps} overlap(s) fixed")

    # Note length cap
    if params["max_note"]:
        max_beats = params.get("max_note_beats", MAX_NOTE_BEATS)
        single_track.notes, clipped = clip_note_lengths(single_track.notes, bpm, max_beats)
        print(f"      note length cap     → {clipped} note(s) clipped  "
              f"(max {max_beats} beat @ {bpm:.1f} BPM = "
              f"{(60.0 / bpm) * max_beats * 1000:.0f}ms)")

    # ─────────────────────────────────────────────────────────────────────────

    midi_data.instruments = [single_track]

    # Apply detected BPM to MIDI header
    if params["detect_tempo"]:
        midi_data = apply_tempo_to_midi(midi_data, bpm)
        print(f"      tempo              → {bpm:.1f} BPM")

    print(f"[3/3] Writing MIDI: {output_path.name}")
    midi_data.write(str(output_path))
    size_kb = output_path.stat().st_size / 1024
    print(f"\n✓  {output_path}  ({size_kb:.1f} KB)")
    print("   Import into GP6: File → Import → MIDI")
    print("   Tip: if noisy, re-run with --frame 0.4 or --min-note 100")
    print("   Tip: if chords are still spread out, raise --chord-window (e.g. 80)")


def main():
    parser = argparse.ArgumentParser(
        description="Solo guitar audio → MIDI for Guitar Pro 6"
    )
    parser.add_argument("input",  help="Input audio (.wav .mp3 .flac .m4a)")
    parser.add_argument("output", nargs="?", help="Output .mid (default: input name + .mid)")
    parser.add_argument("--onset",         type=float, default=ONSET_THRESHOLD,
                        help=f"Onset threshold 0–1 (default {ONSET_THRESHOLD})")
    parser.add_argument("--frame",         type=float, default=FRAME_THRESHOLD,
                        help=f"Frame threshold 0–1 (default {FRAME_THRESHOLD})")
    parser.add_argument("--min-note",      type=float, default=MIN_NOTE_LENGTH,
                        help=f"Min note length ms (default {MIN_NOTE_LENGTH}ms)")
    parser.add_argument("--no-bends",      action="store_true",
                        help="Disable pitch bends (cleaner MIDI, less expressive)")
    parser.add_argument("--denoise",       action="store_true",
                        help="Apply spectral gating to remove white background noise")
    parser.add_argument("--chord-window",  type=float, default=CHORD_WINDOW,
                        help=f"Chord quantization window ms (default {CHORD_WINDOW}ms). "
                             "Set to 0 to disable.")
    parser.add_argument("--no-dedup",        action="store_true",
                        help="Disable duplicate note removal")
    parser.add_argument("--no-fix-overlaps", action="store_true",
                        help="Disable same-pitch overlap resolution")
    parser.add_argument("--no-detect-tempo", action="store_true",
                        help="Disable BPM detection (MIDI will use default 120 BPM grid)")
    parser.add_argument("--no-max-note",     action="store_true",
                        help=f"Disable note length cap (default: {MAX_NOTE_BEATS} beat per note)")
    parser.add_argument("--max-note-beats",  type=float, default=MAX_NOTE_BEATS,
                        help=f"Max note duration in beats relative to detected BPM (default {MAX_NOTE_BEATS}). "
                             "Ignored if --no-max-note is set.")
    args = parser.parse_args()

    input_path  = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.with_suffix(".mid")

    if not input_path.exists():
        print(f"Error: file not found: {input_path}")
        sys.exit(1)

    params = {
        "onset":         args.onset,
        "frame":         args.frame,
        "min_note":      args.min_note,
        "no_bends":      args.no_bends,
        "denoise":       args.denoise,
        "chord_window":  args.chord_window,
        "dedup":         not args.no_dedup,
        "fix_overlaps":  not args.no_fix_overlaps,
        "detect_tempo":  not args.no_detect_tempo,
        "max_note":      not args.no_max_note,
        "max_note_beats": args.max_note_beats,
    }

    transcribe(input_path, output_path, params)


if __name__ == "__main__":
    main()