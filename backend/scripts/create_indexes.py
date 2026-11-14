"""Create every MongoDB index Second Voice needs. Idempotent. SHARED + FROZEN.

    cd backend && python scripts/create_indexes.py

Exactly 3 Atlas Search/Vector indexes (free-tier limit), plus regular + TTL indexes.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pymongo import ASCENDING, DESCENDING, MongoClient  # noqa: E402
from pymongo.operations import SearchIndexModel  # noqa: E402

from app import db as names  # noqa: E402
from app.config import settings  # noqa: E402

SEARCH_INDEXES = [
    (names.PEOPLE, SearchIndexModel(
        name=names.IDX_PEOPLE_VOICE, type="vectorSearch",
        definition={"fields": [
            {"type": "vector", "path": "voice_centroid",
             "numDimensions": settings.voice_embed_dim, "similarity": "cosine"},
            {"type": "filter", "path": "user_id"},
        ]})),
    (names.MEMORIES, SearchIndexModel(
        name=names.IDX_MEMORIES_VECTOR, type="vectorSearch",
        definition={"fields": [
            {"type": "vector", "path": "embedding",
             "numDimensions": settings.embed_dim, "similarity": "cosine"},
            {"type": "filter", "path": "user_id"},
            {"type": "filter", "path": "person_id"},
            {"type": "filter", "path": "kind"},
            {"type": "filter", "path": "status"},
        ]})),
    (names.MEMORIES, SearchIndexModel(
        name=names.IDX_MEMORIES_TEXT, type="search",
        definition={"mappings": {"dynamic": False, "fields": {
            "text": {"type": "string", "analyzer": "lucene.english"},
            "user_id": {"type": "token"},
            "person_id": {"type": "token"},
            "kind": {"type": "token"},
            "status": {"type": "token"},
        }}})),
]

REGULAR_INDEXES = {
    names.UTTERANCES: [[("session_id", ASCENDING), ("created_at", ASCENDING)]],
    names.SUGGESTION_SETS: [[("session_id", ASCENDING), ("created_at", DESCENDING)]],
    names.EVENTS: [
        [("user_id", ASCENDING), ("type", ASCENDING), ("relationship", ASCENDING)],
        [("user_id", ASCENDING), ("type", ASCENDING), ("person_id", ASCENDING)],
    ],
    names.BOUNDARIES: [[("user_id", ASCENDING), ("status", ASCENDING)]],
    names.MEMORIES: [[("user_id", ASCENDING), ("person_id", ASCENDING), ("kind", ASCENDING),
                      ("created_at", DESCENDING)]],
    names.PEOPLE: [[("user_id", ASCENDING)]],
}


def main() -> None:
    client = MongoClient(settings.mongodb_uri)
    database = client[settings.mongodb_db]
    existing_colls = set(database.list_collection_names())

    for coll in {c for c, _ in SEARCH_INDEXES} | set(REGULAR_INDEXES) | {names.AUDIO_CLIPS}:
        if coll not in existing_colls:
            database.create_collection(coll)
            print(f"created collection {coll}")

    for coll, keys_list in REGULAR_INDEXES.items():
        for keys in keys_list:
            print(f"index {coll}: {database[coll].create_index(keys)}")
    database[names.AUDIO_CLIPS].create_index("created_at", expireAfterSeconds=3600)
    print("TTL index audio_clips.created_at (1h)")

    for coll, model in SEARCH_INDEXES:
        current = {ix["name"] for ix in database[coll].list_search_indexes()}
        name = model.document["name"]
        if name in current:
            print(f"search index {coll}.{name} exists")
            continue
        database[coll].create_search_index(model)
        print(f"search index {coll}.{name} requested")

    print("waiting for search indexes to become queryable…")
    for _ in range(60):
        statuses = {
            ix["name"]: ix.get("queryable", False)
            for coll in {c for c, _ in SEARCH_INDEXES}
            for ix in database[coll].list_search_indexes()
        }
        if statuses and all(statuses.values()):
            print("all search indexes READY:", statuses)
            return
        time.sleep(5)
    print("still building, check the Atlas UI:", statuses)


if __name__ == "__main__":
    main()
