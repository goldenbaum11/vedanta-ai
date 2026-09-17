#!/usr/bin/env bash
# One-time setup for scripts/diarize_transcript.py (Linux / NVIDIA CUDA).
# Creates scripts/.venv-diarize with WhisperX — separate from both the
# backend's and training/'s Python environments.
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
echo "Using $($PYTHON --version) at $PYTHON"

"$PYTHON" -m venv .venv-diarize
./.venv-diarize/bin/pip install --upgrade pip

# whisperx's own dependency chain (pyannote-audio -> pytorch-lightning etc.)
# settles on an older torch (2.8.0) whose aarch64 PyPI wheel is CPU-only —
# confirmed empirically on this box. Pin torch to a newer version known to
# ship working CUDA support here (see constraints-diarize.txt) so pip
# resolves everything else around it instead of downgrading torch.
./.venv-diarize/bin/pip install -r requirements-diarize.txt -c constraints-diarize.txt
./.venv-diarize/bin/pip install torch==2.12.1 -c constraints-diarize.txt

echo
echo "Diarization environment ready: scripts/.venv-diarize"
echo "Remember: you still need a Hugging Face token with the"
echo "pyannote/speaker-diarization-3.1 license accepted at"
echo "https://huggingface.co/pyannote/speaker-diarization-3.1"
echo
echo "Then run, e.g.:"
echo "  ./.venv-diarize/bin/python diarize_transcript.py \\"
echo "      --input <video/audio file> --output <transcript.txt> \\"
echo "      --hf-token <your token>"
