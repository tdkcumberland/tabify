# Tuning Guide

Heuristics for getting the best transcription out of `tabify.py` across different guitar styles.

---

## Technique Glossary

Proper names for the techniques that affect transcription behavior.

### Classical
- **Natural harmonics** — lightly touching a string at a node (12th, 7th, 5th fret) produces a bell-like overtone
- **Artificial harmonics** — left hand frets normally; right index touches the node, right ring finger plucks
- **Tremolo** — rapid repeated plucking of a single note (typically p-a-m-i pattern), creating the illusion of sustain
- **Arpeggiation** — broken chord patterns played string by string; fast wide-skip arpeggios are the hardest case for chord detection
- **Position shifts** — large left-hand jumps up/down the neck; pitch content changes drastically between phrases

### Flamenco
- **Rasgueado** — characteristic flamenco strum; fingers fan out one at a time (not a single sweep)
- **Golpe** — percussive tap on the guitar body (tap plate / golpeador); not a string strike
- **Picado** — single-note runs using alternating index and middle fingers
- **Alzapúa** — thumb technique: down-up-up pattern mixing melody and strumming

### Fingerstyle
- **Percussive slap / palm mute thump** — right palm strikes strings near the bridge, simultaneous with or before a fretted note; the defining rhythmic technique in modern fingerstyle
- **Thumb slap** — percussive thumb strike on the low strings
- **Tapping** — right hand fingers fret notes directly on the neck (electric technique applied to acoustic)
- **Polyphonic fingerstyle** — simultaneous independent bass, chord, and melody voices on one guitar

---

## Baseline Arguments by Style

### Classical (nylon string)

```bash
python tabify.py song.wav \
  --onset 0.5 \
  --frame 0.3 \
  --min-note 60 \
  --chord-window 30 \
  --no-bends
```

| Param | Value | Why |
|---|---|---|
| `--onset` | 0.5 | Harmonics have weak attack transients — lower onset catches them |
| `--frame` | 0.3 | Nylon sustains long; lower threshold preserves note tails |
| `--min-note` | 60ms | Tremolo notes are very short and real — don't filter them out |
| `--chord-window` | 30ms | Arpeggios are intentionally spread; too wide collapses them wrongly |
| `--no-bends` | on | Classical has no bends; vibrato is subtle enough to discard |

**Tremolo:** Four notes per beat at tempo — Basic Pitch may merge or drop alternating ones. Expect manual cleanup on tremolo passages.

**Harmonics:** Natural harmonics at the 12th fret transcribe reasonably. Artificial harmonics often register an octave off or are missed entirely — flag for manual correction in GP6.

---

### Flamenco (nylon string)

```bash
python tabify.py song.wav \
  --onset 0.65 \
  --frame 0.45 \
  --min-note 40 \
  --chord-window 20 \
  --no-bends
```

| Param | Value | Why |
|---|---|---|
| `--onset` | 0.65 | Rasgueado produces dense rapid onsets — raise to avoid note avalanche |
| `--frame` | 0.45 | Flamenco timbre is bright and dry; shorter sustain means less frame bleed |
| `--min-note` | 40ms | Picado and rasgueado notes are very short; don't filter real ones |
| `--chord-window` | 20ms | Rasgueado is deliberately arpeggiated — don't collapse it into chords |
| `--no-bends` | on | No bends in the western sense |

**Golpe:** Body strike, not a string note. Basic Pitch may hallucinate pitches from the transient. If you see isolated very-short low notes that don't belong, they're likely golpe artifacts.

**Rasgueado:** Will transcribe as a spray of rapid notes — some correct, many phantom. Hardest style for any pitch detector. Treat output as a rough skeleton only.

---

### Fingerstyle (steel string)

```bash
python tabify.py song.wav \
  --onset 0.6 \
  --frame 0.4 \
  --min-note 80 \
  --chord-window 50
```

| Param | Value | Why |
|---|---|---|
| `--onset` | 0.6 | Steel string has clear attack transients — standard threshold works |
| `--frame` | 0.4 | Rich sustain; default threshold handles it well |
| `--min-note` | 80ms | Lower than default 100ms to preserve tapped notes (short duration) |
| `--chord-window` | 50ms | Default; works well for simultaneous bass + melody hits |

**Palm slap / thump:** Body hits produce low-frequency transients Basic Pitch may pitch-detect. Spurious notes in the E1–A1 range are almost always slap artifacts. `--min-note 80` helps; raise toward 100 if still noisy.

**Tapping:** Right-hand taps have normal note character — Basic Pitch handles these well. `--min-note 80` is the lowest safe floor before percussion bleeds back in.

---

### Quick Reference

| | Classical | Flamenco | Fingerstyle |
|---|---|---|---|
| `--onset` | 0.5 | 0.65 | 0.6 |
| `--frame` | 0.3 | 0.45 | 0.4 |
| `--min-note` | 60ms | 40ms | 80ms |
| `--chord-window` | 30ms | 20ms | 50ms |
| `--no-bends` | ✓ | ✓ | — |
| Biggest hazard | Tremolo / harmonics | Golpe / rasgueado | Palm slap artifacts |

---

## Tuning for Polyphonic Interior Notes

The melody and bass lines are the easiest to recover. The interior polyphonic voices — inner chord tones, passing notes, the notes that establish timing and pattern — are what make an arrangement and are the hardest for Basic Pitch to catch.

The core tension: **lower thresholds catch more interior notes but also more garbage.** The goal is to find the floor before noise overwhelms usefulness.

### Why Interior Voices Are Hard

- Their onset energy is genuinely weaker (lighter finger pressure, shorter duration)
- They share frequency space with bass harmonics and melody undertones
- Basic Pitch is a monophonic-biased model extended for polyphony — dense fingerstyle/classical polyphony is its hardest case

### Tuning Order

Work one variable at a time, in this sequence:

**1. `--onset` first — primary gate**

Controls whether a note is detected at all. Interior voices have weak attacks; this is the main reason they're missed.

- Drop in 0.05 increments: 0.6 → 0.55 → 0.5
- Stop when obvious phantom notes appear

**2. `--frame` second — sustain sensitivity**

Once onset lets a note in, frame determines how long it's tracked.

- Drop in 0.05 increments: 0.4 → 0.35 → 0.3
- Watch for notes extending past their real duration, or merging with adjacent notes

**3. `--min-note` third — duration floor**

Interior notes are often short — passing tones, inner voice movements.

- Try 60ms for classical, 70ms for fingerstyle
- Below 60ms risks body resonance and string noise registering as notes

**4. `--chord-window` last — grouping only**

Only relevant once the notes are detected. Adjust if inner voices that should land on the same onset aren't grouping with the bass/melody, or if the window is collapsing distinct inner voice movements.

### Tuning Ladder

Run the same 15–20 second dense polyphonic excerpt repeatedly. Compare in GP6 after each step.

```bash
# Baseline
python tabify.py excerpt.wav --onset 0.6 --frame 0.4 --min-note 80

# Step 1 — loosen onset
python tabify.py excerpt.wav --onset 0.5 --frame 0.4 --min-note 80

# Step 2 — loosen both
python tabify.py excerpt.wav --onset 0.5 --frame 0.35 --min-note 80

# Step 3 — allow shorter notes
python tabify.py excerpt.wav --onset 0.5 --frame 0.35 --min-note 60

# Step 4 — go further only if still missing notes (noise will increase)
python tabify.py excerpt.wav --onset 0.45 --frame 0.3 --min-note 60
```