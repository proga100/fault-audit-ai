"""Create the Atlas Vector Search index on transactions.embedding.

Run AFTER embed_and_load.py (the field must exist). Idempotent. On Atlas M0/free tier
vector search indexes are supported (up to 3). The index takes ~1-2 min to build.

    python create_vector_index.py
"""

from __future__ import annotations

import json
import time

from pymongo import MongoClient
from pymongo.operations import SearchIndexModel

from faultaudit.config import REPO_ROOT, get_settings


def main() -> None:
    s = get_settings()
    spec = json.loads((REPO_ROOT / "vector_index.json").read_text())
    client = MongoClient(s.atlas_uri)
    coll = client[s.db_name][s.txn_collection]

    existing = {ix["name"] for ix in coll.list_search_indexes()}
    if spec["name"] in existing:
        print(f"Index '{spec['name']}' already exists.")
    else:
        coll.create_search_index(
            SearchIndexModel(definition=spec["definition"], name=spec["name"], type=spec["type"])
        )
        print(f"Created index '{spec['name']}'. Building …")

    # poll until queryable
    for _ in range(48):
        info = list(coll.list_search_indexes(spec["name"]))
        if info and info[0].get("queryable"):
            print("Index is QUERYABLE — vector search is live.")
            client.close()
            return
        time.sleep(5)
    print("Index created; still building. Check the Atlas UI (Search tab).")
    client.close()


if __name__ == "__main__":
    main()
