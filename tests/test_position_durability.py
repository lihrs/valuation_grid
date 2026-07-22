import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import positions


class PositionDurabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="valuation-grid-positions-")
        root = Path(self.temp_dir.name)
        self._original_paths = {
            "DATA_DIR": positions.DATA_DIR,
            "POS_FILE": positions.POS_FILE,
            "POS_BACKUP_FILE": positions.POS_BACKUP_FILE,
            "POS_HISTORY_DIR": positions.POS_HISTORY_DIR,
            "POS_LOCK_FILE": positions.POS_LOCK_FILE,
            "POS_MIRROR_FILE": positions.POS_MIRROR_FILE,
            "POS_MIRROR_HISTORY_DIR": positions.POS_MIRROR_HISTORY_DIR,
        }
        positions.DATA_DIR = root / "workspace-data"
        positions.POS_FILE = positions.DATA_DIR / "positions.json"
        positions.POS_BACKUP_FILE = positions.DATA_DIR / "positions.backup.json"
        positions.POS_HISTORY_DIR = positions.DATA_DIR / "positions_history"
        positions.POS_LOCK_FILE = positions.DATA_DIR / ".positions.lock"
        positions.POS_MIRROR_FILE = root / "external-store" / "positions.json"
        positions.POS_MIRROR_HISTORY_DIR = positions.POS_MIRROR_FILE.parent / "history"

    def tearDown(self):
        for name, value in self._original_paths.items():
            setattr(positions, name, value)
        self.temp_dir.cleanup()

    def _save_fund(self, amount=100):
        data = positions.load_positions()
        data["funds"]["TEST__owner"] = {
            "fund_name": "test",
            "max_position": 5000,
            "batches": [{"id": "b1", "amount": amount}],
        }
        positions.save_positions(data)
        return positions.POS_FILE.read_bytes()

    def test_successful_save_writes_primary_and_external_mirror(self):
        self._save_fund()

        self.assertEqual(positions.POS_FILE.read_bytes(), positions.POS_MIRROR_FILE.read_bytes())
        self.assertEqual(positions.load_positions()["storage_revision"], 1)

    def test_git_style_primary_rollback_is_recovered_from_newer_mirror(self):
        old_raw = self._save_fund(amount=100)
        data = positions.load_positions()
        data["funds"]["TEST__owner"]["batches"].append({"id": "b2", "amount": 200})
        positions.save_positions(data)
        new_raw = positions.POS_MIRROR_FILE.read_bytes()

        positions.POS_FILE.write_bytes(old_raw)
        recovered = positions.load_positions()

        self.assertEqual(len(recovered["funds"]["TEST__owner"]["batches"]), 2)
        self.assertEqual(positions.POS_FILE.read_bytes(), new_raw)

    def test_corrupt_primary_is_recovered_from_mirror(self):
        self._save_fund()
        expected = positions.POS_MIRROR_FILE.read_bytes()
        positions.POS_FILE.write_text("Bad Gateway", encoding="utf-8")

        recovered = positions.load_positions()

        self.assertIn("TEST__owner", recovered["funds"])
        self.assertEqual(positions.POS_FILE.read_bytes(), expected)

    def test_stale_writer_cannot_overwrite_newer_trade(self):
        self._save_fund()
        first = positions.load_positions()
        stale = positions.load_positions()
        first["funds"]["TEST__owner"]["batches"].append({"id": "b2", "amount": 200})
        positions.save_positions(first)
        stale["funds"]["TEST__owner"]["batches"].append({"id": "stale", "amount": 999})

        with self.assertRaises(positions.PositionConflictError):
            positions.save_positions(stale)

        current_ids = [b["id"] for b in positions.load_positions()["funds"]["TEST__owner"]["batches"]]
        self.assertEqual(current_ids, ["b1", "b2"])

    def test_each_update_keeps_workspace_and_external_history(self):
        self._save_fund()
        data = positions.load_positions()
        data["funds"]["TEST__owner"]["max_position"] = 6000
        positions.save_positions(data)

        self.assertGreaterEqual(len(list(positions.POS_HISTORY_DIR.glob("positions-*.json"))), 1)
        self.assertGreaterEqual(len(list(positions.POS_MIRROR_HISTORY_DIR.glob("positions-*.json"))), 1)

    def test_buy_and_sell_survive_reopen_from_same_store(self):
        batch = positions.add_batch(
            "TRADE__owner", amount=1000, nav=2.0, buy_date="2026-07-20"
        )
        positions.sell_batch(
            "TRADE__owner", batch["id"], sell_shares=125,
            sell_nav=2.2, sell_date="2026-07-22",
        )

        reopened = positions.load_positions()["funds"]["TRADE__owner"]

        self.assertEqual(reopened["batches"][0]["shares"], 375)
        self.assertEqual(reopened["sell_records"][0]["sell_shares"], 125)
        self.assertEqual(positions.POS_FILE.read_bytes(), positions.POS_MIRROR_FILE.read_bytes())

    def test_concurrent_buys_are_serialized_without_lost_updates(self):
        def add(index):
            return positions.add_batch(
                "CONCURRENT__owner", amount=100 + index, nav=2.0,
                buy_date=f"2026-07-{index + 1:02d}",
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            batches = list(executor.map(add, range(20)))

        reopened = positions.load_positions()["funds"]["CONCURRENT__owner"]
        self.assertEqual(len(reopened["batches"]), 20)
        self.assertEqual(len({batch["id"] for batch in batches}), 20)
        self.assertEqual(positions.POS_FILE.read_bytes(), positions.POS_MIRROR_FILE.read_bytes())

    def test_retried_trade_request_is_applied_exactly_once(self):
        first_buy = positions.add_batch(
            "RETRY__owner", amount=1000, nav=2.0, buy_date="2026-07-20",
            request_id="buy-request-1",
        )
        retried_buy = positions.add_batch(
            "RETRY__owner", amount=1000, nav=2.0, buy_date="2026-07-20",
            request_id="buy-request-1",
        )
        first_sell = positions.sell_batch(
            "RETRY__owner", first_buy["id"], 125, sell_nav=2.2,
            sell_date="2026-07-22", request_id="sell-request-1",
        )
        retried_sell = positions.sell_batch(
            "RETRY__owner", first_buy["id"], 125, sell_nav=2.2,
            sell_date="2026-07-22", request_id="sell-request-1",
        )

        reopened = positions.load_positions()["funds"]["RETRY__owner"]
        self.assertEqual(first_buy["id"], retried_buy["id"])
        self.assertEqual(first_sell["sell_record_id"], retried_sell["sell_record_id"])
        self.assertEqual(len(reopened["batches"]), 1)
        self.assertEqual(len(reopened["sell_records"]), 1)
        self.assertEqual(reopened["batches"][0]["shares"], 375)

    def test_retried_fifo_sell_is_applied_exactly_once(self):
        positions.add_batch("FIFO__owner", 400, nav=2.0, buy_date="2026-07-19")
        positions.add_batch("FIFO__owner", 600, nav=2.0, buy_date="2026-07-20")
        first = positions.sell_fifo(
            "FIFO__owner", 250, sell_nav=2.2, sell_date="2026-07-22",
            request_id="fifo-request-1",
        )
        retried = positions.sell_fifo(
            "FIFO__owner", 250, sell_nav=2.2, sell_date="2026-07-22",
            request_id="fifo-request-1",
        )

        reopened = positions.load_positions()["funds"]["FIFO__owner"]
        self.assertEqual(first, retried)
        self.assertEqual(len(reopened["sell_records"]), 2)
        self.assertEqual(sum(r["sell_shares"] for r in reopened["sell_records"]), 250)


if __name__ == "__main__":
    unittest.main()
