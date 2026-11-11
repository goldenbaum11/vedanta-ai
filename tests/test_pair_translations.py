"""Portuguese translations on persona pairs (question_pt / answer_pt).

Covers the store side of the /review language switch: translations
round-trip, the `untranslated` filter, and the ALTER TABLE migration
for databases created before the columns existed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from backend import database
from backend.persona import store

pytestmark = pytest.mark.usefixtures("isolated_env")


async def test_translation_round_trip_and_untranslated_filter() -> None:
    await database.init_db()
    await store.insert_pairs(
        1,
        [
            {"question": "What is japa?", "answer": "Japa is repetition."},
            {"question": "Who is Ishvara?", "answer": "Ishvara is the whole."},
        ],
    )
    pairs = await store.list_pairs()
    assert [p["question_pt"] for p in pairs] == [None, None]
    assert await store.count_pairs(untranslated=True) == 2

    first = pairs[0]["id"]
    updated = await store.update_pair(
        first, question_pt="O que é japa?", answer_pt="Japa é repetição."
    )
    assert updated is not None
    assert updated["question_pt"] == "O que é japa?"
    # The English original used for training is untouched.
    assert updated["question"] == "What is japa?"
    assert updated["status"] == "pending"

    remaining = await store.list_pairs(untranslated=True)
    assert [p["id"] for p in remaining] == [pairs[1]["id"]]
    assert await store.count_pairs(untranslated=True) == 1


async def test_migration_adds_translation_columns_to_legacy_table() -> None:
    async with database.get_engine().begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE persona_pairs (id INTEGER PRIMARY KEY, "
                "transcript_id INTEGER NOT NULL, question TEXT NOT NULL, "
                "answer TEXT NOT NULL, kind VARCHAR(32) NOT NULL, segment INTEGER, "
                "status VARCHAR(32) NOT NULL DEFAULT 'pending', "
                "created_at VARCHAR(64) NOT NULL, reviewed_at VARCHAR(64))"
            )
        )
    await database.init_db()
    async with database.get_connection() as conn:
        cols = {
            row[1]
            for row in (await conn.execute(text("PRAGMA table_info(persona_pairs)")))
        }
    assert {"reviewed_by", "question_pt", "answer_pt"} <= cols
