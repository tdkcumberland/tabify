"""
tabify-live.py — Record guitar segments → MIDI for Guitar Pro 6
Usage: python tabify-live.py

Records from the default input device. Press Enter to start/stop each segment.
Outputs segment_001.mid, segment_002.mid, ... into ./segments/ (or --out-dir).

Inherits all Basic Pitch tuning flags from tabify.py.
"""

import sys
import argparse
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from tabify import (
    transcribe,
    ONSET_THRESHOLD,
    FRAME_THRESHOLD,
    MIN_NOTE_LENGTH,
    CHORD_WINDOW,
)

# ── Audio capture settings ────────────────────────────────────────────────────

SAMPLE_RATE = 44100   # Hz — standard for Basic Pitch
CHANNELS    = 1       # Mono

# ─────────────────────────────────────────────────────────────────────────────

GATE_THRESHOLD  = 0.01    # RMS below this = silence. Raise if mic picks up room noise.
GATE_CHUNK_MS   = 10      # Gate resolution in ms — smaller = tighter gating


def apply_noise_gate(audio: np.ndarray, threshold: float = GATE_THRESHOLD) -> np.ndarray:
    """
    Zero out chunks of audio whose RMS energy falls below threshold.
    Operates on 10ms chunks — fine enough to catch inter-note silence
    without chopping note tails.
    """
    chunk_size = int(SAMPLE_RATE * GATE_CHUNK_MS / 1000)
    result = audio.copy()
    for i in range(0, len(result), chunk_size):
        chunk = result[i:i + chunk_size]
        rms = np.sqrt(np.mean(chunk ** 2))
        if rms < threshold:
            result[i:i + chunk_size] = 0.0
    return result


def get_default_device_name() -> str:
    try:
        device_info = sd.query_devices(kind="input")
        return device_info["name"]
    except Exception:
        return "unknown"


def record_segment() -> np.ndarray:
    """Block until user presses Enter to stop. Returns recorded audio as numpy array."""
    buffer = []

    def callback(indata, _frames, _time_info, status):
        if status:
            print(f"  [!] {status}", flush=True)
        buffer.append(indata.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, callback=callback):
        # Elapsed time ticker runs in background
        start_time = time.time()
        ticker_stop = threading.Event()

        def tick():
            while not ticker_stop.is_set():
                elapsed = time.time() - start_time
                print(f"\r  Recording... {elapsed:.1f}s  (Press Enter to stop)", end="", flush=True)
                time.sleep(0.1)

        ticker_thread = threading.Thread(target=tick, daemon=True)
        ticker_thread.start()

        input()  # blocks until Enter

        ticker_stop.set()
        ticker_thread.join(timeout=0.5)
        print()  # newline after ticker

    if not buffer:
        return np.zeros((0, CHANNELS), dtype=np.float32)

    return np.concatenate(buffer, axis=0)


def main():
    parser = argparse.ArgumentParser(
        description="Record guitar segments → MIDI for Guitar Pro 6"
    )
    parser.add_argument("--out-dir",  type=str, default="segments",
                        help="Output directory for .mid files (default: ./segments)")
    parser.add_argument("--onset",    type=float, default=ONSET_THRESHOLD,
                        help=f"Onset threshold 0–1 (default {ONSET_THRESHOLD})")
    parser.add_argument("--frame",    type=float, default=FRAME_THRESHOLD,
                        help=f"Frame threshold 0–1 (default {FRAME_THRESHOLD})")
    parser.add_argument("--min-note", type=float, default=MIN_NOTE_LENGTH,
                        help=f"Min note length ms (default {MIN_NOTE_LENGTH}ms)")
    parser.add_argument("--no-bends", action="store_true",
                        help="Disable pitch bends (cleaner MIDI, less expressive)")
    parser.add_argument("--denoise",  action="store_true",
                        help="Apply spectral gating to remove background noise")
    parser.add_argument("--chord-window",  type=float, default=CHORD_WINDOW,
                        help=f"Chord quantization window ms (default {CHORD_WINDOW}ms). "
                             "Set to 0 to disable.")
    parser.add_argument("--no-dedup",        action="store_true",
                        help="Disable duplicate note removal")
    parser.add_argument("--no-fix-overlaps", action="store_true",
                        help="Disable same-pitch overlap resolution")
    parser.add_argument("--no-detect-tempo", action="store_true",
                        help="Disable BPM detection (MIDI will use default 120 BPM grid)")
    parser.add_argument("--no-gate", action="store_true",
                        help="Disable noise gate (on by default for mic input)")
    parser.add_argument("--gate-threshold", type=float, default=GATE_THRESHOLD,
                        help=f"Noise gate RMS threshold (default {GATE_THRESHOLD}). "
                             f"Raise (e.g. 0.02) if room noise bleeds through.")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

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
    }

    device_name = get_default_device_name()
    print(f"tabify-live  |  input: {device_name}  |  {SAMPLE_RATE}Hz mono")
    print(f"              output: {out_dir.resolve()}")
    print(f"              onset={params['onset']}  frame={params['frame']}  "
          f"min_note={params['min_note']}ms  bends={not params['no_bends']}")
    print("─" * 60)
    print("Ctrl+C to quit.\n")

    segment_index = 1

    try:
        while True:
            print(f"[Segment {segment_index:03d}]  Press Enter to start recording...")
            input()

            audio = record_segment()

            if audio.shape[0] < SAMPLE_RATE * 0.5:
                print("  [!] Recording too short (<0.5s), discarded.\n")
                continue

            # Noise gate (default on — mic input warrants it)
            if not args.no_gate:
                audio = apply_noise_gate(audio, threshold=args.gate_threshold)

            # Write temp wav
            temp_wav = out_dir / f".temp_segment_{segment_index:03d}.wav"
            sf.write(str(temp_wav), audio, SAMPLE_RATE)

            # Transcribe
            mid_path = out_dir / f"segment_{segment_index:03d}.mid"
            try:
                transcribe(temp_wav, mid_path, params)
            finally:
                if temp_wav.exists():
                    temp_wav.unlink()

            print()
            segment_index += 1

    except KeyboardInterrupt:
        saved = segment_index - 1
        print(f"\n\nDone. {saved} segment{'s' if saved != 1 else ''} saved to {out_dir.resolve()}")
        sys.exit(0)


if __name__ == "__main__":
    main()