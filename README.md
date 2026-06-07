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
python tabify.py song.wav --onset 0.6
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

| Flag | Tool | Default | When to change |
|---|---|---|---|
| `--onset` | both | 0.5 | Raise to 0.6+ if too many ghost notes |
| `--frame` | both | 0.4 | Raise if body percussion creates noise |
| `--min-note` | both | 100ms | Raise to 120ms for heavy percussion |
| `--no-bends` | both | off | Enable if GP6 shows excessive pitch bend noise |
| `--denoise` | both | off | Spectral gating for stationary background noise |
| `--no-gate` | live | off | Disable noise gate (on by default for mic input) |
| `--gate-threshold` | live | 0.01 | Raise to 0.02+ if room noise bleeds through |

## Workflow

### From a reference recording
1. Download audio, extract with ffmpeg
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