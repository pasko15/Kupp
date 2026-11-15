import sqlite3
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from backend.kupp.config import DB_PATH
from backend.scripts.init_db import initialize


class DatabaseProtectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize()

    def setUp(self):
        self.db = sqlite3.connect(DB_PATH)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("SAVEPOINT db_protection_check")
        self.token = uuid4().hex
        item_id = f"__db_check_{self.token}"
        store_id = f"__db_check_{self.token}"
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            "INSERT INTO products(item_id, product_name, created_at) VALUES (?, ?, ?)",
            (item_id, "temporary protection check", now),
        )
        self.db.execute(
            "INSERT INTO stores(store_id, name) VALUES (?, ?)",
            (store_id, "temporary protection check"),
        )
        self.match_id = self.db.execute(
            """INSERT INTO product_matches
               (item_id, source, source_product_id, match_type, confidence)
               VALUES (?, 'test', ?, 'identical', 1.0) RETURNING id""",
            (item_id, self.token),
        ).fetchone()[0]
        self.store_id = store_id
        self.hash = f"db-protection-{self.token}"
        self.insert_observation()

    def tearDown(self):
        self.db.execute("ROLLBACK TO db_protection_check")
        self.db.execute("RELEASE db_protection_check")
        self.db.close()

    def insert_observation(self, content_hash=None):
        self.db.execute(
            """INSERT INTO price_observations (
                   product_match_id, store_id, price_minor, currency, observed_at,
                   retrieved_at, source_checked_at, source, price_type, is_promo,
                   content_hash, freshness
               ) VALUES (?, ?, 100, 'NOK', '2026-11-15', ?, NULL, 'test',
                         'unknown', NULL, ?, 'unknown')""",
            (
                self.match_id,
                self.store_id,
                datetime.now(timezone.utc).isoformat(),
                content_hash or self.hash,
            ),
        )

    def test_price_observation_update_is_blocked(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            self.db.execute(
                "UPDATE price_observations SET price_minor=200 WHERE content_hash=?",
                (self.hash,),
            )
        self.assertEqual(
            self.db.execute(
                "SELECT price_minor FROM price_observations WHERE content_hash=?", (self.hash,)
            ).fetchone()[0],
            100,
        )

    def test_price_observation_delete_is_blocked(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            self.db.execute("DELETE FROM price_observations WHERE content_hash=?", (self.hash,))
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM price_observations WHERE content_hash=?", (self.hash,)
            ).fetchone()[0],
            1,
        )

    def test_content_hash_is_unique(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, "content_hash"):
            self.insert_observation()

    def test_database_integrity(self):
        self.assertEqual(self.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")


if __name__ == "__main__":
    unittest.main()
