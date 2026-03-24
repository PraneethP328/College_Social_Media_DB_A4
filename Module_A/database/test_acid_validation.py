from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Module_A.database.table import Table


class TestModuleAAcidValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.table = Table(
            name="members",
            primary_key="id",
            schema=["id", "name", "credits"],
            bplustree_order=4,
        )

    def _assert_table_index_consistent(self, table: Table) -> None:
        # `all_rows` and B+ tree traversal should always represent identical data.
        self.assertEqual(table.all_rows(), table._index.get_all())

    def test_atomicity_rollback_on_failure(self) -> None:
        self.table.insert({"id": 1, "name": "Alice", "credits": 15})
        self.table.insert({"id": 2, "name": "Bob", "credits": 12})
        before = self.table.all_rows()

        def failing_operation() -> None:
            self.table.update(1, {"credits": 18})
            raise RuntimeError("simulated mid-operation failure")

        with self.assertRaises(RuntimeError):
            self.table.execute_atomic(failing_operation)

        self.assertEqual(self.table.all_rows(), before)
        self._assert_table_index_consistent(self.table)

    def test_consistency_validation_rejects_invalid_update(self) -> None:
        self.table.insert({"id": 10, "name": "Cara", "credits": 20})
        before = self.table.get(10)

        with self.assertRaises(ValueError):
            self.table.update(10, {"unknown_column": "x"})

        self.assertEqual(self.table.get(10), before)
        self._assert_table_index_consistent(self.table)

    def test_durability_committed_data_survives_restart(self) -> None:
        self.table.insert({"id": 101, "name": "Deep", "credits": 22})
        self.table.insert({"id": 102, "name": "Esha", "credits": 19})

        with tempfile.TemporaryDirectory() as tmp_dir:
            snapshot_path = Path(tmp_dir) / "members_snapshot.json"
            self.table.save_snapshot(snapshot_path)

            # Simulate process restart by recreating table from persisted snapshot.
            restarted_table = Table.load_snapshot(snapshot_path)

        self.assertEqual(restarted_table.get(101), {"id": 101, "name": "Deep", "credits": 22})
        self.assertEqual(restarted_table.get(102), {"id": 102, "name": "Esha", "credits": 19})
        self._assert_table_index_consistent(restarted_table)

    def test_committed_state_recovered_after_crash_simulation(self) -> None:
        self.table.insert({"id": 7, "name": "Gita", "credits": 17})

        with tempfile.TemporaryDirectory() as tmp_dir:
            snapshot_path = Path(tmp_dir) / "commit_snapshot.json"
            self.table.save_snapshot(snapshot_path)

            # Uncommitted changes after snapshot should be lost after crash/restart.
            self.table.update(7, {"credits": 99})
            self.table.insert({"id": 8, "name": "Hari", "credits": 9})

            recovered_table = Table.load_snapshot(snapshot_path)

        self.assertEqual(recovered_table.get(7), {"id": 7, "name": "Gita", "credits": 17})
        self.assertIsNone(recovered_table.get(8))
        self._assert_table_index_consistent(recovered_table)

    def test_fault_injection_mid_operation_rolls_back_every_change(self) -> None:
        self.table.insert({"id": 21, "name": "Ira", "credits": 11})
        self.table.insert({"id": 22, "name": "Jai", "credits": 13})
        before = self.table.all_rows()

        def operation_with_fault_injection() -> None:
            self.table.update(21, {"credits": 99})
            self.table.insert({"id": 23, "name": "Kia", "credits": 15})
            # Inject failure after partial writes to verify full rollback.
            raise RuntimeError("fault injected after partial updates")

        with self.assertRaises(RuntimeError):
            self.table.execute_atomic(operation_with_fault_injection)

        self.assertEqual(self.table.all_rows(), before)
        self.assertIsNone(self.table.get(23))
        self._assert_table_index_consistent(self.table)


if __name__ == "__main__":
    unittest.main(verbosity=2)
