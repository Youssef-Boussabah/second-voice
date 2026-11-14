"""Tiny in-memory async Mongo stand-in for Lane D unit tests (no Atlas needed)."""
from __future__ import annotations

import copy
from typing import Any


def _get(doc: dict, path: str) -> Any:
    value: Any = doc
    for part in path.split("."):
        if isinstance(value, list):  # Mongo array traversal: "open_threads.id"
            value = [item[part] for item in value if isinstance(item, dict) and part in item]
            continue
        if not isinstance(value, dict) or part not in value:
            return _MISSING
        value = value[part]
    return value


class _Missing:
    pass


_MISSING = _Missing()


def _match_value(value: Any, cond: Any) -> bool:
    if isinstance(cond, dict) and cond and all(key.startswith("$") for key in cond):
        for op, arg in cond.items():
            if op == "$in":
                if isinstance(value, list):
                    if not set(value) & set(arg):
                        return False
                elif value not in arg:
                    return False
            elif op == "$nin":
                if isinstance(value, list) and set(value) & set(arg):
                    return False
                if not isinstance(value, list) and value in arg:
                    return False
            elif op == "$ne":
                if value == arg or (isinstance(value, list) and arg in value):
                    return False
            elif op == "$exists":
                if (value is not _MISSING) != bool(arg):
                    return False
            elif op == "$gt":
                if value is _MISSING or value is None or not value > arg:
                    return False
            elif op == "$gte":
                if value is _MISSING or value is None or not value >= arg:
                    return False
            elif op == "$lt":
                if value is _MISSING or value is None or not value < arg:
                    return False
            else:
                raise NotImplementedError(op)
        return True
    if isinstance(value, list) and not isinstance(cond, list):
        return cond in value
    if value is _MISSING:
        return cond is None
    return value == cond


def matches(doc: dict, flt: dict) -> bool:
    for key, cond in flt.items():
        if key == "$or":
            if not any(matches(doc, sub) for sub in cond):
                return False
        elif key == "$and":
            if not all(matches(doc, sub) for sub in cond):
                return False
        elif not _match_value(_get(doc, key), cond):
            return False
    return True


class _Cursor:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def sort(self, key, direction=None):
        keys = key if isinstance(key, list) else [(key, direction or 1)]
        for field, order in reversed(keys):
            self._docs.sort(key=lambda d: (_get(d, field) is _MISSING, str(_get(d, field))), reverse=order == -1)
        return self

    def limit(self, n: int):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length=None):
        return self._docs if length is None else self._docs[:length]

    def __aiter__(self):
        self._iter = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class _Result:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeCollection:
    def __init__(self):
        self.docs: list[dict] = []

    def find(self, flt: dict | None = None, projection: dict | None = None):
        return _Cursor([copy.deepcopy(d) for d in self.docs if matches(d, flt or {})])

    async def find_one(self, flt: dict | None = None, projection: dict | None = None):
        for d in self.docs:
            if matches(d, flt or {}):
                return copy.deepcopy(d)
        return None

    async def count_documents(self, flt: dict) -> int:
        return sum(1 for d in self.docs if matches(d, flt))

    async def insert_one(self, doc: dict):
        if any(d["_id"] == doc["_id"] for d in self.docs):
            from pymongo.errors import DuplicateKeyError
            raise DuplicateKeyError(f"dup {doc['_id']}")
        self.docs.append(copy.deepcopy(doc))
        return _Result(inserted_id=doc["_id"])

    def _apply(self, d: dict, update: dict) -> None:
        for key, value in update.get("$set", {}).items():
            d[key] = copy.deepcopy(value)
        for key, value in update.get("$inc", {}).items():
            d[key] = d.get(key, 0) + value

    async def update_one(self, flt: dict, update: dict, upsert: bool = False):
        for d in self.docs:
            if matches(d, flt):
                self._apply(d, update)
                return _Result(matched_count=1, modified_count=1)
        return _Result(matched_count=0, modified_count=0)

    async def replace_one(self, flt: dict, replacement: dict):
        for index, d in enumerate(self.docs):
            if matches(d, flt):
                self.docs[index] = copy.deepcopy(replacement) | {"_id": d["_id"]}
                return _Result(matched_count=1, modified_count=1)
        return _Result(matched_count=0, modified_count=0)

    async def update_many(self, flt: dict, update: dict):
        hits = [d for d in self.docs if matches(d, flt)]
        for d in hits:
            self._apply(d, update)
        return _Result(matched_count=len(hits), modified_count=len(hits))

    async def delete_many(self, flt: dict):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not matches(d, flt)]
        return _Result(deleted_count=before - len(self.docs))


class FakeDB(dict):
    def __missing__(self, name: str) -> FakeCollection:
        self[name] = FakeCollection()
        return self[name]
