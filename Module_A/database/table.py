from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .bplustree import BPlusTree


class Table:
    """In-memory table abstraction backed by a B+ Tree primary-key index."""

    def __init__(
        self,
        name: str,
        primary_key: str = "id",
        schema: Optional[Iterable[str]] = None,
        bplustree_order: int = 4,
    ) -> None:
        if not name or not name.strip():
            raise ValueError("Table name must be a non-empty string")

        self.name = name.strip()
        self.primary_key = primary_key
        self.schema = set(schema) if schema else None
        self._index = BPlusTree(order=bplustree_order)

        if self.schema is not None and self.primary_key not in self.schema:
            self.schema.add(self.primary_key)

    def insert(self, row: Dict[str, Any]) -> None:
        """Insert a new row; raises if primary key already exists."""
        key = self._extract_and_validate_key(row)
        if self._index.search(key) is not None:
            raise KeyError(f"Duplicate primary key {key} in table '{self.name}'")

        validated = self._validate_row_shape(row)
        self._index.insert(key, deepcopy(validated))

    def upsert(self, row: Dict[str, Any]) -> None:
        """Insert or replace a row using its primary key."""
        key = self._extract_and_validate_key(row)
        validated = self._validate_row_shape(row)
        self._index.insert(key, deepcopy(validated))

    def get(self, key: int) -> Optional[Dict[str, Any]]:
        row = self._index.search(self._validate_key_type(key))
        return deepcopy(row) if row is not None else None

    def update(self, key: int, updates: Dict[str, Any]) -> bool:
        """Patch an existing row using partial updates."""
        if not isinstance(updates, dict):
            raise TypeError("updates must be a dictionary")

        key = self._validate_key_type(key)
        existing = self._index.search(key)
        if existing is None:
            return False

        if self.primary_key in updates and updates[self.primary_key] != key:
            raise ValueError("Primary key cannot be changed during update")

        merged = deepcopy(existing)
        merged.update(updates)
        merged[self.primary_key] = key
        validated = self._validate_row_shape(merged)
        return self._index.update(key, deepcopy(validated))

    def delete(self, key: int) -> bool:
        return self._index.delete(self._validate_key_type(key))

    def range_query(self, start_key: int, end_key: int) -> List[Tuple[int, Dict[str, Any]]]:
        results = self._index.range_query(self._validate_key_type(start_key), self._validate_key_type(end_key))
        return [(k, deepcopy(v)) for k, v in results]

    def all_rows(self) -> List[Tuple[int, Dict[str, Any]]]:
        rows = self._index.get_all()
        return [(k, deepcopy(v)) for k, v in rows]

    def select(
        self,
        predicate: Optional[Callable[[Dict[str, Any]], bool]] = None,
        columns: Optional[Iterable[str]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Return rows matching predicate, with optional projection and limit."""
        if predicate is not None and not callable(predicate):
            raise TypeError("predicate must be callable or None")
        if limit is not None and (not isinstance(limit, int) or limit < 0):
            raise ValueError("limit must be a non-negative integer or None")

        selected_columns: Optional[List[str]] = None
        if columns is not None:
            selected_columns = list(columns)
            if self.schema is not None:
                unknown = set(selected_columns) - self.schema
                if unknown:
                    raise ValueError(f"Unknown columns for table '{self.name}': {sorted(unknown)}")

        results: List[Dict[str, Any]] = []
        for _, row in self._index.get_all():
            if predicate is not None and not predicate(row):
                continue

            if selected_columns is None:
                out = deepcopy(row)
            else:
                out = {col: deepcopy(row.get(col)) for col in selected_columns}

            results.append(out)
            if limit is not None and len(results) >= limit:
                break

        return results

    def aggregate(
        self,
        operation: str,
        column: Optional[str] = None,
        predicate: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> Any:
        """Compute simple aggregations: count, sum, min, max, avg."""
        if predicate is not None and not callable(predicate):
            raise TypeError("predicate must be callable or None")
        if not isinstance(operation, str) or not operation.strip():
            raise ValueError("operation must be a non-empty string")

        op = operation.strip().lower()
        supported = {"count", "sum", "min", "max", "avg"}
        if op not in supported:
            raise ValueError(f"Unsupported operation '{operation}'. Supported: {sorted(supported)}")

        if op != "count" and not column:
            raise ValueError("column is required for sum/min/max/avg")

        if column is not None and self.schema is not None and column not in self.schema:
            raise ValueError(f"Unknown column '{column}' for table '{self.name}'")

        rows = self.select(predicate=predicate)

        if op == "count":
            if column is None:
                return len(rows)
            return sum(1 for row in rows if row.get(column) is not None)

        values = [row.get(column) for row in rows if row.get(column) is not None]

        if op in {"sum", "avg"}:
            non_numeric = [v for v in values if not isinstance(v, (int, float)) or isinstance(v, bool)]
            if non_numeric:
                raise TypeError(f"Column '{column}' contains non-numeric values, cannot compute {op}")

        if op == "sum":
            return sum(values)
        if op == "min":
            return min(values) if values else None
        if op == "max":
            return max(values) if values else None
        if op == "avg":
            return (sum(values) / len(values)) if values else None

        return None

    def count(self) -> int:
        return len(self._index.get_all())

    def truncate(self) -> None:
        # Reinitialize the index to clear all rows.
        self._index = BPlusTree(order=self._index.order)

    def _extract_and_validate_key(self, row: Dict[str, Any]) -> int:
        if not isinstance(row, dict):
            raise TypeError("row must be a dictionary")
        if self.primary_key not in row:
            raise KeyError(f"Row must contain primary key '{self.primary_key}'")
        return self._validate_key_type(row[self.primary_key])

    def _validate_key_type(self, key: Any) -> int:
        if not isinstance(key, int) or isinstance(key, bool):
            raise TypeError("Primary key must be an integer for B+ Tree indexing")
        return key

    def _validate_row_shape(self, row: Dict[str, Any]) -> Dict[str, Any]:
        if self.schema is None:
            return row

        unknown = set(row.keys()) - self.schema
        if unknown:
            raise ValueError(f"Unknown columns for table '{self.name}': {sorted(unknown)}")

        return row
