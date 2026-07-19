# Vishva Vidya × Vedanta AI — data request

- **From**: Vedanta AI engineering
- **To**: Jonas Masetti (and Vishva Vidya tech lead, if applicable)
- **Date**: 2026-05-27
- **Status**: Draft, awaiting your go-ahead
- **Partnership level**: Level 3 — full partnership

---

## TL;DR (for Jonas)

We've already ingested your library *catalog* (211 texts from
[vedanta.com.br/biblioteca](https://vedanta.com.br/biblioteca)) into the AI.
It can now answer "do you have Tattvabodha?" with the right
recommendation and a link back to your site.

To make the AI actually **quote and explain** the verses — not just
point at them — we need the verse content itself. Below is the
shortest path to get there. **You don't need to do all of it.** Pick
the option that's least painful for your team and the priority list
that matches your study calendar.

---

## What we need, in one schema

Per text, one row per verse (or per sūtra / paragraph for prose texts):

| Field                 | Type    | Required? | Example                                                                                  |
|-----------------------|---------|-----------|------------------------------------------------------------------------------------------|
| `text_slug`           | string  | yes       | `"tattvabodha"`                                                                          |
| `text_title`          | string  | yes       | `"Tattvabodha"`                                                                          |
| `chapter`             | string  | optional  | `"2"`                                                                                    |
| `verse`               | string  | yes       | `"47"` — or `"1.4"` if there's no chapter notion                                         |
| `sanskrit_devanagari` | string  | preferred | `"कर्मण्येवाधिकारस्ते मा फलेषु कदाचन..."`                                                |
| `sanskrit_iast`       | string  | preferred | `"karmaṇy evādhikāras te mā phaleṣu kadācana..."`                                        |
| `translation_pt`      | string  | preferred | `"Tens direito apenas à ação, nunca aos frutos..."`                                      |
| `translation_en`      | string  | optional  | `"Your right is to action alone, never to its fruits..."`                                |
| `commentary_pt`       | string  | optional  | `"Śrī Śaṅkara explica que karmādhikāra significa..."`                                    |
| `commentary_en`       | string  | optional  | `"Śaṅkara explains that karmādhikāra means..."`                                          |
| `commentary_author`   | string  | optional  | `"Śrī Ādi Śaṅkarācārya"`                                                                 |
| `translation_status`  | enum    | preferred | `"reliable"` / `"ai_assisted"` / `"none"` — matches your "Tradução confiável" labels     |
| `source_url`          | string  | optional  | `"https://vedanta.com.br/biblioteca/tattvabodha#v45"`                                    |

**Anything is better than nothing.** If a text has only Sanskrit and
no translation, send the Sanskrit. If you only have PT and no EN, send
PT. The AI handles missing layers gracefully — it just won't fabricate
the missing ones.

JSON Lines (`.jsonl`) is the easiest format for us to consume — one
record per line. CSV with the same columns works too. If your CMS
already exports something different, send that and we'll write the
adapter on our side.

---

## Three ways to deliver the data — pick the cheapest for you

### Option A — One-shot export (lowest effort, fine for v1)

Your dev exports the Library content as a single archive (JSONL/CSV/SQL
dump). We ingest it once. Refresh every 3–6 months by re-running the
same export.

- ✅ No infrastructure changes on your side
- ❌ Stale between refreshes — fine for sacred texts (they don't move),
  awkward for the Glossary and Blog which you update regularly

### Option B — Per-text JSON files (medium effort)

Add a `?format=json` query parameter (or a `/api/v1/library/<slug>` endpoint)
to each text's page that returns the verse data in the schema above.
We poll the catalog and pull whichever texts changed.

- ✅ We always have the latest, no manual refresh
- ✅ Lets us pull a single text without re-downloading the world
- ❌ Requires a small backend change

### Option C — Direct DB read replica (highest trust, lowest effort once set up)

You give us read-only Postgres/MySQL credentials (over Tailscale or a
VPN) to a replica of the Library DB. We pull whatever we need on a
schedule. This is what we'd recommend if Vishva Vidya is willing —
it's the same trust level as letting us hold the data anyway, and
it's the smallest amount of work for your team.

- ✅ Zero ongoing dev work on your side
- ✅ Schema evolves naturally — we adapt on our side
- ❌ Requires a moment of trust + infrastructure setup

---

## What we promise back (Level-3 partnership terms)

1. **Attribution**: every quoted verse, translation, and commentary in
   the AI's answers cites Vishva Vidya by name and links back to the
   matching page on `vedanta.com.br/biblioteca/<slug>`.
2. **Takedown**: 48-hour SLA. You email a list of `text_slug`s to
   remove; we purge them from Chroma + Postgres + on-disk snapshots
   and confirm in writing.
3. **Scope**: the ingested data is used **only** within the Vedanta
   AI project (Jonas's onpremises and authorised cloud instances). No
   resale, no third-party API exposure, no model fine-tuning that
   would memorise your translations.
4. **Retention**: full snapshots on our side every quarter so we can
   roll back if anything breaks. Snapshots are AES-encrypted at rest.
5. **Audit log**: every retrieval that surfaces Vishva Vidya content
   is logged with the user id and the matched chunk id. You get
   read-access to this log on request.
6. **Refresh cadence**: weekly for Option B/C, on-demand or quarterly
   for Option A.
7. **No silent drift**: if our ingest sees a text removed or replaced
   upstream, we surface that in a sync report rather than silently
   serving stale content.

---

## Priority list — what we need first

If the answer is "Tattvabodha first, the rest later," that's totally fine.

### Tier 1 — first wave (highest student impact)

These are the texts beginners ask about most. Roughly 700 verses total.

| # | Text                                  | Verses | Author        | Existing translation | Why first |
|---|---------------------------------------|-------:|---------------|----------------------|-----------|
| 1 | Tattvabodha                           |     45 | Śaṅkara       | reliable PT          | First text in your Turma Regular — most-asked |
| 2 | Ātmabodha                             |     68 | Śaṅkara       | none                 | Classic Advaita primer — students need it |
| 3 | Vivekacūḍāmaṇi                        |    581 | Śaṅkara       | AI-assisted PT       | Most cited prakaraṇa in our test queries |
| 4 | Sādhanā Pañcakam                      |      5 | Śaṅkara       | none                 | Tiny, foundational, easy to ship |

### Tier 2 — Prasthānatrayī (core Vedānta canon)

The three foundational texts every Vedanta school teaches.

| # | Text                                  | Verses  | Author        | Existing translation |
|---|---------------------------------------|--------:|---------------|----------------------|
| 5 | Bhagavad Gītā Bhāṣya                  |   1,339 | Śaṅkara       | none                 |
| 6 | Brahmasūtra Bhāṣya                    |     267 | Śaṅkara       | none                 |
| 7 | Māṇḍūkya Upaniṣad + Kārikās Gauḍapāda |     232 | Śruti+Gauḍapāda | AI-assisted PT     |

We already have a public-domain Gītā (Gambirananda + Sivananda) and a
partial Upaniṣad set in our corpus. Your Bhāṣya layer fills the gap
that no public-domain dataset offers.

### Tier 3 — the ten Principal Upaniṣads + Bhāṣyas

| Text                          | Bhāṣya verses | Translation status |
|-------------------------------|--------------:|--------------------|
| Aitareya Upaniṣad Bhāṣya      |           148 | none               |
| Bṛhadāraṇyaka Upaniṣad Bhāṣya |            80 | none               |
| Chāndogya Upaniṣad Bhāṣya     |           104 | none               |
| Īśāvāsya Upaniṣad Bhāṣya      |            18 | none               |
| Kaṭha Upaniṣad Bhāṣya         |           546 | none               |
| Kena Upaniṣad Bhāṣya (Pāda)   |            35 | none               |
| Kena Upaniṣad Bhāṣya (Vākya)  |            39 | none               |
| Māṇḍūkya Upaniṣad Bhāṣya      |           232 | none               |
| Muṇḍaka Upaniṣad Bhāṣya       |           197 | none               |
| Praśna Upaniṣad Bhāṣya        |            67 | none               |
| Taittirīya Upaniṣad Bhāṣya    |           826 | none               |

### Tier 4 — Vyākhyā (sub-commentaries) and Stotras

Lower priority. Useful for advanced students. We can wait until the
upper tiers are landed and the system is in regular use.

### Out of scope for now

The full Veda Saṃhitās (Ṛgveda 10 maṇḍalas, Atharvaveda 20 kāṇḍas,
Śukla Yajurveda 40 adhyāyas, etc.) are large and untranslated. The
catalog rows already let the AI know they exist and link users to
your site. We'll come back to these in a later phase.

---

## Adjacent data we'd also love (lower priority)

These are part of the Level-3 scope but not blocking the verse-content work.

| Resource          | Why we want it | What format works |
|-------------------|----------------|-------------------|
| **Glossário**     | The AI can answer "what does *adhyāsa* mean?" with your tradition's definitions instead of Wikipedia's | JSON with `term`, `definition_pt`, `definition_en`, `references` |
| **VedantaCast**   | Cross-reference episodes to verses so the AI can say "Jonas covers this in episode 47 at 12:03" | RSS feed + permission to transcribe locally with Whisper |
| **Blog**          | Lets the AI cite Jonas's recent essays | RSS or sitemap is fine |
| **Study App**     | Eventually, surface the same exercises in the chat UI | Schema TBD — let's discuss when ready |

---

## Open questions for you

1. Which delivery option (A/B/C) fits your team best?
2. Who's the right technical contact on your side?
3. Is there a preferred sync cadence (we'll work around it)?
4. Are there texts in the Library you'd rather we **not** ingest
   (e.g. drafts, work in progress, restricted material)?
5. Any branding constraints we should follow in the UI when surfacing
   Vishva Vidya content? (Currently the AI says "Source: Vishva Vidya,
   vedanta.com.br/biblioteca/<slug>".)

---

## Next concrete step

A 30-minute call with whoever owns the Library backend. Goals:

1. Look at the schema above together and confirm what's easy / hard
   on their side.
2. Pick A / B / C.
3. Agree on a first delivery — start with **Tier 1 (4 texts, ~700
   verses)** as a proof of concept.
4. Set a date to revisit once Tier 1 is live in the AI.

Happy to attend in PT or EN.

— Vedanta AI engineering team
