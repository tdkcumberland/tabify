# tabify

Solo fingerstyle guitar audio → MIDI for Guitar Pro 6 import.

## Setup

```bat
cd E:\github\tabify

rem basic-pitch caps tensorflow<2.15.1 which doesn't exist on Python 3.12.
rem --no-deps bypasses the stale constraint; everything works at runtime.
uv pip install basic-pitch==0.4.0 --no-deps
uv pip install -r requirements.txt

rem tabify-live only — mic/audio capture
uv pip install sounddevice
```

## Usage

### tabify.py — file → MIDI

```bash
# Basic — output MIDI next to the input file
python tabify.py song.wav

# Explicit output path
python tabify.py song.wav tabs\song.mid

# Tune for heavy body percussion (raise thresholds)
python tabify.py song.wav --frame 0.4 --min-note 100

# Disable pitch bends if MIDI looks noisy in GP6
python tabify.py song.wav --no-bends

# Getting too many ghost notes? Raise onset threshold
python tabify.py song.wav --onset 0.7

# Arpeggios still spreading instead of chording? Widen the window
python tabify.py song.wav --chord-window 80

# Disable chord quantization entirely
python tabify.py song.wav --chord-window 0

# Apply spectral noise reduction (stationary background noise)
python tabify.py song.wav --denoise

# Skip BPM detection — use default 120 BPM grid
python tabify.py song.wav --no-detect-tempo
```

### tabify-live.py — mic → MIDI segments

```bash
# Basic — records to ./segments/
python tabify-live.py

# Custom output directory
python tabify-live.py --out-dir tabs\session1

# Louder room / noisy mic — raise gate threshold
python tabify-live.py --gate-threshold 0.02

# Disable noise gate (e.g. quiet room, clean signal)
python tabify-live.py --no-gate

# Combine with denoise for extra cleanup
python tabify-live.py --denoise

# All tuning flags work the same as tabify.py
python tabify-live.py --onset 0.6 --no-bends --min-note 100
```

## Parameters

### Transcription (both tools)

| Flag | Default | When to change |
|---|---|---|
| `--onset` | 0.6 | Raise to 0.7+ to cut ghost notes; lower to 0.5 to capture more |
| `--frame` | 0.4 | Raise if body percussion or noise floor bleeds through |
| `--min-note` | 100ms | Raise to 120ms+ for recordings with heavy body percussion |
| `--no-bends` | off | Enable if GP6 shows excessive pitch bend noise |
| `--denoise` | off | Spectral gating via `noisereduce` — for stationary background noise |

### Post-processing (both tools)

| Flag | Default | When to change |
|---|---|---|
| `--chord-window` | 50ms | Raise (e.g. 80ms) if fast arpeggios still spread; set to 0 to disable |
| `--no-dedup` | off | Disable duplicate removal (same pitch + onset after quantization) |
| `--no-fix-overlaps` | off | Disable same-pitch overlap truncation (reverb bleed artifact) |
| `--no-detect-tempo` | off | Skip BPM detection — MIDI uses default 120 BPM grid |

### Live capture (tabify-live only)

| Flag | Default | When to change |
|---|---|---|
| `--out-dir` | `./segments` | Change output directory for `.mid` files |
| `--no-gate` | off | Disable noise gate (enabled by default for mic input) |
| `--gate-threshold` | 0.01 | Raise to 0.02+ if room noise bleeds between notes |

## Workflow

### From a reference recording
1. Download audio, extract with ffmpeg (or use `prep_audio.sh`)
2. Run `tabify.py` → MIDI → import into GP6
3. Study melody, chords, bass lines

### Learning by ear (tabify-live)
1. Run `tabify-live.py`
2. Press Enter → play a segment → press Enter to stop
3. MIDI file saved automatically
4. Import into GP6, use reference MIDI to fill gaps
5. Repeat per section

## Notes

- No cloud, no LLM, fully local
- Works best on clean single-guitar recordings
- Reverb and compression are handled well by Basic Pitch
- Body percussion is filtered by `--min-note` threshold
- First run downloads the Basic Pitch model (~20MB, cached after that)
- USB condenser mic works well — noise gate is on by default to clean inter-note silence