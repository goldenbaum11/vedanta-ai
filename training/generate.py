"""Generate one answer with a trained LoRA adapter (mlx-lm Python API).

Invoked by the admin "test model" endpoint as a subprocess. Prints
ONLY the generated text to stdout (logs go to stderr) so the caller
can return stdout verbatim.

Usage:
    python -m training.generate \\
        --base-model mlx-community/Qwen2.5-7B-Instruct-4bit \\
        --adapter-dir data/persona/adapters/jonas-v1 \\
        --system-prompt "You are Jonas..." \\
        --prompt "How do I deal with a restless mind?"
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--adapter-dir", required=True)
    parser.add_argument("--system-prompt", default="")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--max-tokens", type=int, default=400)
    args = parser.parse_args()

    try:
        from mlx_lm import generate, load
    except ImportError:
        print(
            "ERROR: mlx-lm not installed. Run: cd training && ./setup.sh",
            file=sys.stderr,
        )
        return 2

    print("loading model + adapter...", file=sys.stderr)
    model, tokenizer = load(args.base_model, adapter_path=args.adapter_dir)

    messages = []
    if args.system_prompt:
        messages.append({"role": "system", "content": args.system_prompt})
    messages.append({"role": "user", "content": args.prompt})
    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )

    text = generate(
        model,
        tokenizer,
        prompt=prompt,
        max_tokens=args.max_tokens,
        verbose=False,
    )
    print(text.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
