"""Generate one answer with a trained LoRA adapter (Unsloth / CUDA).

Invoked by the admin "test model" endpoint as a subprocess (see
`backend/persona/jobs.py::test_model` — that caller is unchanged; only
this script's internals moved from MLX to Unsloth). Prints ONLY the
generated text to stdout (logs go to stderr) so the caller can return
stdout verbatim.

Usage:
    python -m training.generate \\
        --base-model unsloth/Qwen3.8-27B \\
        --adapter-dir data/persona/adapters/jonas-v1 \\
        --system-prompt "You are Jonas..." \\
        --prompt "How do I deal with a restless mind?"
"""

from __future__ import annotations

import argparse
import sys

MAX_SEQ_LENGTH = 2048


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--adapter-dir", required=True)
    parser.add_argument("--system-prompt", default="")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--max-tokens", type=int, default=400)
    args = parser.parse_args()

    try:
        from unsloth import FastLanguageModel
    except ImportError:
        print(
            "ERROR: unsloth not installed. Run: cd training && ./setup.sh",
            file=sys.stderr,
        )
        return 2

    from peft import PeftModel

    print("loading base model...", file=sys.stderr)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base_model,
        max_seq_length=MAX_SEQ_LENGTH,
        dtype=None,
        load_in_4bit=True,
    )

    print(f"attaching adapter from {args.adapter_dir}...", file=sys.stderr)
    model = PeftModel.from_pretrained(model, args.adapter_dir)
    FastLanguageModel.for_inference(model)

    messages = []
    if args.system_prompt:
        messages.append({"role": "system", "content": args.system_prompt})
    messages.append({"role": "user", "content": args.prompt})
    prompt_text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )

    inputs = tokenizer(prompt_text, return_tensors="pt").to(model.device)
    output_ids = model.generate(
        **inputs,
        max_new_tokens=args.max_tokens,
        do_sample=True,
        temperature=0.7,
        top_p=0.9,
    )
    generated = output_ids[0][inputs["input_ids"].shape[1] :]
    text = tokenizer.decode(generated, skip_special_tokens=True)
    print(text.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
