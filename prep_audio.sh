#!/usr/bin/env bash
# prep_audio.sh — Strip audio, crop, and normalize format for tabify
# Usage: prep_audio.sh <input> [--start SECONDS] [--end SECONDS]

set -euo pipefail

# ── Usage ─────────────────────────────────────────────────────────────────────

usage() {
    echo "Usage: $(basename "$0") <input> [--start SECONDS] [--end SECONDS]"
    echo ""
    echo "  --start   Crop start time in seconds (optional)"
    echo "  --end     Crop end time in seconds (optional)"
    exit 1
}

# ── Argument parsing ──────────────────────────────────────────────────────────

INPUT=""
START=""
END=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --start)   START="$2"; shift 2 ;;
        --end)     END="$2";   shift 2 ;;
        -h|--help) usage ;;
        -*)        echo "Unknown option: $1"; usage ;;
        *)
            [[ -n "$INPUT" ]] && { echo "Error: unexpected argument: $1"; usage; }
            INPUT="$1"
            shift
            ;;
    esac
done

[[ -z "$INPUT" ]]  && { echo "Error: no input file specified"; usage; }
[[ ! -f "$INPUT" ]] && { echo "Error: file not found: $INPUT"; exit 1; }

# ── Probe ─────────────────────────────────────────────────────────────────────

HAS_VIDEO=$(ffprobe -v error -select_streams v:0 \
    -show_entries stream=codec_type -of csv=p=0 "$INPUT" 2>/dev/null || true)

AUDIO_CODEC=$(ffprobe -v error -select_streams a:0 \
    -show_entries stream=codec_name -of csv=p=0 "$INPUT" 2>/dev/null || true)

[[ -z "$AUDIO_CODEC" ]] && { echo "Error: no audio stream found in: $INPUT"; exit 1; }

SAMPLE_RATE=$(ffprobe -v error -select_streams a:0 \
    -show_entries stream=sample_rate -of csv=p=0 "$INPUT" 2>/dev/null || true)

BITS=$(ffprobe -v error -select_streams a:0 \
    -show_entries stream=bits_per_sample -of csv=p=0 "$INPUT" 2>/dev/null || true)

# ── Output format ─────────────────────────────────────────────────────────────

case "$AUDIO_CODEC" in
    pcm_*) OUT_EXT="wav" ;;
    mp3)   OUT_EXT="mp3" ;;
    *)     OUT_EXT="wav" ;;
esac

STEM="${INPUT%.*}"
OUTPUT="${STEM}_tabify_ready.${OUT_EXT}"

# ── Re-encode decision ────────────────────────────────────────────────────────

NEEDS_REENCODE=false
[[ -n "$HAS_VIDEO" ]]       && NEEDS_REENCODE=true
[[ -n "$START" || -n "$END" ]] && NEEDS_REENCODE=true

# ── Codec args ────────────────────────────────────────────────────────────────

CODEC_ARGS=()

if [[ "$NEEDS_REENCODE" == false ]]; then
    CODEC_ARGS+=(-c:a copy)
elif [[ "$OUT_EXT" == "wav" ]]; then
    if [[ -n "$BITS" && "$BITS" -gt 0 ]]; then
        CODEC_ARGS+=(-c:a "pcm_s${BITS}le")
    else
        CODEC_ARGS+=(-c:a pcm_s16le)
    fi
    [[ -n "$SAMPLE_RATE" ]] && CODEC_ARGS+=(-ar "$SAMPLE_RATE")
else
    # MP3
    MP3_BITRATE=$(ffprobe -v error -select_streams a:0 \
        -show_entries stream=bit_rate -of csv=p=0 "$INPUT" 2>/dev/null || true)
    if [[ -n "$MP3_BITRATE" && "$MP3_BITRATE" -gt 0 ]]; then
        CODEC_ARGS+=(-c:a libmp3lame -b:a "${MP3_BITRATE}")
    else
        CODEC_ARGS+=(-c:a libmp3lame -q:a 2)
    fi
    [[ -n "$SAMPLE_RATE" ]] && CODEC_ARGS+=(-ar "$SAMPLE_RATE")
fi

# ── Build ffmpeg command ──────────────────────────────────────────────────────

FFMPEG_ARGS=(-v warning -i "$INPUT")
[[ -n "$START" ]] && FFMPEG_ARGS+=(-ss "$START")
[[ -n "$END" ]]   && FFMPEG_ARGS+=(-to "$END")
FFMPEG_ARGS+=(-vn)
FFMPEG_ARGS+=("${CODEC_ARGS[@]}")
FFMPEG_ARGS+=(-y "$OUTPUT")

# ── Summary ───────────────────────────────────────────────────────────────────

echo "Input:   $INPUT"
[[ -n "$HAS_VIDEO" ]] && echo "         (video stream stripped)"
[[ -n "$START" ]]     && echo "Start:   ${START}s"
[[ -n "$END" ]]       && echo "End:     ${END}s"
echo "Codec:   ${CODEC_ARGS[*]}"
echo "Output:  $OUTPUT"
echo ""

# ── Run ───────────────────────────────────────────────────────────────────────

ffmpeg "${FFMPEG_ARGS[@]}"

SIZE_KB=$(du -k "$OUTPUT" | cut -f1)
echo ""
echo "✓  $OUTPUT  (${SIZE_KB} KB)"
echo "   Run: python tabify.py \"$OUTPUT\""