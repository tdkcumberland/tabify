# tabify

Solo fingerstyle guitar audio → MIDI for Guitar Pro 8 import.

## Setup

```bat
cd E:\github\tabify

rem basic-pitch caps tensorflow<2.15.1 which doesn't exist on Python 3.11 via uv.
rem --no-deps bypasses the stale constraint; everything works at runtime.
uv pip install basic-pitch==0.4.0 --no-deps
uv pip install -r requirements.txt
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

# Disable pitch bends if MIDI looks noisy in GP8
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

# Disable note length cap (let notes sustain fully)
python tabify.py song.wav --no-max-note
```

## Parameters

All features are on by default unless noted. Flags prefixed `--no-` disable a feature.

### Transcription

#### `--onset` · default `0.6`

Controls how confident Basic Pitch must be before calling something a note onset — the moment a note starts. Internally, the model produces a probability score for each time-frequency frame; this threshold gates which scores count as real onsets.

- **Lower values (e.g. 0.5):** more permissive — catches soft interior voices, harmonics, and lightly plucked notes. Also catches more ghost notes and body percussion transients.
- **Higher values (e.g. 0.7+):** more selective — only strong, clear attacks register. Cleaner output but may drop quiet notes, especially inner chord voices.

Start here first when tuning. It is the primary gate on note detection — everything else is downstream of it.

#### `--frame` · default `0.4`

Controls how confident Basic Pitch must be to continue tracking a note that has already started. After onset detection lets a note in, frame threshold determines how long it is sustained in the output.

- **Lower values (e.g. 0.3):** notes are tracked longer even as their energy fades. Useful for nylon string guitars with long decays, or for recovering the tail end of sustained bass notes.
- **Higher values (e.g. 0.5+):** notes are dropped sooner as sustain confidence falls. Useful when body percussion or room noise is causing notes to appear extended. Raise this if you see notes bleeding past where they were actually played.

#### `--min-note` · default `100ms`

Sets the minimum duration a detected note must sustain to be kept. Any note shorter than this threshold is discarded entirely before the MIDI is written.

- Body percussion hits, palm slaps, and string noise typically resolve in under 40ms.
- Real fretted notes — even very short ones in fast runs — almost always sustain for at least 60–80ms.
- At 100ms (default), all percussion noise is filtered while preserving fast melodic runs.
- Raise to 120ms+ if you are working with recordings that have particularly loud or complex body percussion. Lower to 60ms for classical tremolo or fast flamenco picado passages.

#### `--no-bends`

Disables pitch bend detection. By default, Basic Pitch writes pitch bend MIDI events to represent slides, vibrato, and string bends. In Guitar Pro, these render as smooth pitch curves on individual notes.

Enable `--no-bends` if:
- Your GP8 import looks cluttered with excessive bend notation
- The recording has heavy reverb that is causing pitch smearing to register as false bends
- You are working on a classical or flamenco piece where western bends are not used

Leave bends on if you want slides and bends represented in the MIDI for reference during your arrangement.

#### `--denoise`

Applies spectral noise reduction via `noisereduce` before transcription. Processes the audio to attenuate stationary background noise — consistent hiss, hum, room tone — before passing it to Basic Pitch.

This is opt-in because it adds processing time and can subtly alter the harmonic content of the recording. Use it when:
- There is audible background noise between notes (fan, HVAC, mic hiss)
- The recording was made in an untreated room

Do not use it on professionally recorded or studio-mastered audio — it will not help and may introduce artifacts.

---

### Post-processing

These steps run after Basic Pitch transcription, on the raw note list before the MIDI is written.

#### `--chord-window` · default `50ms` · set to `0` to disable

After transcription, notes whose onsets fall within this time window are snapped to the same timestamp, turning a fast arpeggio sweep into a chord event. This is the most impactful post-processing parameter for fingerstyle guitar.

- Fingerstyle arpeggios that span a single beat often spread across 20–80ms of real time. Basic Pitch detects each string pluck individually as a separate onset.
- A 50ms window collapses those into a single chord onset that GP8 can render as a strummed chord.
- **Raise (e.g. 80–100ms)** if slow strums are still rendering as spread-out eighth notes in GP8.
- **Lower (e.g. 20–30ms)** if fast single-note runs are being wrongly collapsed into chords.
- **Set to 0** to disable entirely and preserve every onset as detected.

Tune this last — after onset and frame — since it operates on already-detected notes.

#### `--no-dedup`

After chord quantization snaps notes to the same onset, it is possible for the same pitch to appear twice at the exact same timestamp (e.g. an arpeggio that revisits a string). These duplicates render as stacked notes in GP8 with no musical value. Duplicate removal keeps the first occurrence and discards the rest.

Disable only if you suspect legitimate repeated notes are being dropped — which would be unusual given the 50ms chord window.

#### `--no-fix-overlaps`

A guitar string can physically only sustain one pitch at a time. When the same pitch appears twice before the first instance ends — common with reverb bleed causing Basic Pitch to "see" a note ringing past a new strike — the first note's end time is clamped to the second note's start time.

This makes the tab physically accurate: no note on the same pitch can overlap with the next. Disable only for diagnostic purposes.

#### `--no-detect-tempo`

By default, librosa analyses the audio to detect the song's BPM. That value is written into the MIDI header so GP8 lays notes on the correct beat grid. Without it, GP8 defaults to 120 BPM, which will misalign notes for any song that is not exactly 120 BPM.

Disable if:
- The detected BPM is clearly wrong (common with rubato or freely-played sections)
- You prefer to set BPM manually in GP8
- You want faster processing

#### `--no-max-note` · default cap: `1 beat at detected BPM`

Caps the maximum duration of any individual note to one beat relative to the detected BPM. This directly addresses reverb-sustained notes bleeding across bars and rendering as long tied notes in GP8.

The cap is BPM-relative so it scales correctly with tempo:
- At 120 BPM → cap is 500ms per note
- At 80 BPM → cap is 750ms per note
- At 160 BPM → cap is 375ms per note

If `--no-detect-tempo` is also set, the cap falls back to a fixed 500ms.

Disable if you are transcribing a slow, sustained piece where long note durations are musically correct and you want them preserved.

---

## Workflow

### From a reference recording
1. Strip audio with `prep_audio.sh` (or any ffmpeg command)
2. Run `tabify.py` → MIDI → import into GP8
3. Study melody, chords, bass lines

### Learning by ear (tabify-live)
1. Run `tabify-live.py`
2. Press Enter → play a segment → press Enter to stop
3. MIDI saved automatically
4. Import into GP8, use as reference to fill gaps
5. Repeat per section

## Notes

- No cloud, no LLM, fully local
- Works best on clean single-guitar recordings
- Reverb and compression are handled well by Basic Pitch
- Body percussion is filtered by `--min-note` threshold
- First run downloads the Basic Pitch model (~20MB, cached after that)
- USB condenser mic works well for tabify-live — noise gate is on by default