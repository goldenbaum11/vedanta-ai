"""Translate persona Q&A pairs into Portuguese for the /review page.

Uses the project's own self-hosted LLM (backend.models.llm_client, i.e.
llama.cpp / Ollama per .env) — never a cloud API. Talks to the pairs
review API over HTTP, so it can fill translations on the live site
(vedanta.review) from any machine that can reach both the API and the
local model.

Only pairs with no Portuguese text yet are translated, so the script is
safe to re-run; it picks up where it left off.

Usage:
    export REVIEW_EMAIL=admin@example.com REVIEW_PASSWORD=...
    python3 scripts/translate_pairs.py --api https://vedanta.review
    python3 scripts/translate_pairs.py --api http://localhost:8000 --limit 20
    python3 scripts/translate_pairs.py --dry-run --limit 3   # print, don't save
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.models.llm_client import get_llm_client  # noqa: E402

SYSTEM_PROMPT = """\
You translate question-and-answer pairs from a Vedanta teacher's classes \
from English into Brazilian Portuguese.

Rules:
- Translate faithfully. Do not summarize, shorten, explain, or add anything.
- Keep the teacher's spoken, conversational tone and his examples.
- Keep Sanskrit terms as they are (e.g. Brahman, ātmā, mokṣa, japa, Gītā).
- Use the conventions of Brazilian Vedanta teaching (e.g. "Ishvara",
  "conhecimento", "o eu") and address the student naturally.

Return ONLY a JSON object, no markdown fences, no commentary:
{"question": "...", "answer": "..."}
"""


# Walks backslash pairs left to right so a valid escaped backslash is never
# split. A stray backslash (e.g. before "ā") is dropped, keeping the letter.
_ESCAPE_PAIR = re.compile(r"\\(.?)", re.S)


def _fix_escapes(body: str) -> str:
    return _ESCAPE_PAIR.sub(
        lambda m: m.group(0) if m.group(1) and m.group(1) in '"\\/bfnrtu' else m.group(1),
        body,
    )

# One attempt per temperature: a JSON failure at 0.1 tends to repeat
# verbatim, so later attempts add a little randomness.
_TEMPERATURES = (0.1, 0.4, 0.7)


async def _translate(llm, user: str) -> dict[str, str]:
    last: Exception | None = None
    for temp in _TEMPERATURES:
        try:
            return _parse(await llm.complete(SYSTEM_PROMPT, user, temperature=temp))
        except Exception as exc:  # noqa: BLE001 - try the next temperature
            last = exc
    assert last is not None
    raise last


async def _api(http: httpx.AsyncClient, method: str, url: str, **kw) -> httpx.Response:
    """HTTP call that rides out short network drops instead of quitting."""
    for attempt in range(8):
        try:
            r = await http.request(method, url, **kw)
            if r.status_code < 500:
                r.raise_for_status()
                return r
        except httpx.TransportError as exc:
            print(f"  network error ({exc!r}); retrying")
        await asyncio.sleep(min(2 ** attempt, 120))
    r = await http.request(method, url, **kw)
    r.raise_for_status()
    return r


def _parse(raw: str) -> dict[str, str]:
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
    start, end = raw.find("{"), raw.rfind("}")
    body = raw[start : end + 1]
    try:
        # strict=False tolerates raw newlines/tabs inside strings.
        data = json.loads(body, strict=False)
    except json.JSONDecodeError:
        # The model sometimes emits invalid escapes next to Sanskrit
        # diacritics (e.g. "\ā"); drop any backslash that doesn't start
        # a valid JSON escape and try once more.
        data = json.loads(_fix_escapes(body), strict=False)
    q, a = str(data.get("question", "")).strip(), str(data.get("answer", "")).strip()
    if not q or not a:
        raise ValueError("empty translation")
    return {"question_pt": q, "answer_pt": a}


async def _login(http: httpx.AsyncClient, email: str, password: str) -> str:
    r = await http.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    r.raise_for_status()
    return r.json()["access_token"]


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api", default="http://localhost:8000", help="backend base URL")
    ap.add_argument("--status", default="", help="only pairs with this status")
    ap.add_argument("--limit", type=int, default=0, help="max pairs (0 = all)")
    ap.add_argument("--dry-run", action="store_true", help="print, don't save")
    args = ap.parse_args()

    email = os.environ.get("REVIEW_EMAIL")
    password = os.environ.get("REVIEW_PASSWORD")
    if not email or not password:
        print("Set REVIEW_EMAIL and REVIEW_PASSWORD (an admin or reviewer account).")
        return 2

    llm = get_llm_client()
    if not await llm.is_available():
        print("Local LLM is not reachable; check LLM settings in .env.")
        return 1

    done = failed = 0
    async with httpx.AsyncClient(base_url=args.api, timeout=60) as http:
        token = await _login(http, email, password)
        http.headers["Authorization"] = f"Bearer {token}"
        # Pairs that failed (or were only printed) this run. They stay in the
        # "untranslated" list, always ahead of the untouched ones since we go
        # in id order, so paging with offset=len(skip) steps past them.
        skip: set[int] = set()
        while True:
            params: dict[str, object] = {
                "untranslated": "true",
                "limit": 50,
                "offset": len(skip),
            }
            if args.status:
                params["status"] = args.status
            r = await _api(http, "GET", "/api/v1/admin/pairs", params=params)
            body = r.json()
            batch = [p for p in body["pairs"] if p["id"] not in skip]
            if not batch:
                break
            for pair in batch:
                if args.limit and done + failed >= args.limit:
                    break
                user = json.dumps(
                    {"question": pair["question"], "answer": pair["answer"]},
                    ensure_ascii=False,
                )
                try:
                    patch = await _translate(llm, user)
                except Exception as exc:  # noqa: BLE001 - keep going
                    failed += 1
                    skip.add(pair["id"])
                    print(f"#{pair['id']}: FAILED ({exc})")
                    continue
                if args.dry_run:
                    skip.add(pair["id"])
                    print(f"#{pair['id']} Q: {patch['question_pt']}\n   A: {patch['answer_pt'][:200]}…\n")
                else:
                    await _api(http, "PATCH", f"/api/v1/admin/pairs/{pair['id']}", json=patch)
                    print(f"#{pair['id']}: ok")
                done += 1
            if args.limit and done + failed >= args.limit:
                break

    print(f"Translated {done}, failed {failed}.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
