# -*- coding: utf-8 -*-
"""Run an isolated Firestore backup and restore drill.

The script creates a temporary schedule school, verifies an immutable backup
can replace a changed shared draft, then removes every temporary document.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid

from google.cloud import firestore
from google.oauth2.credentials import Credentials


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from schedule_store import FirestoreScheduleStore  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an isolated schedule restore drill.")
    parser.add_argument("--project", required=True, help="Google Cloud project ID")
    return parser.parse_args()


def build_client(project_id: str) -> firestore.Client:
    access_token = os.getenv("GOOGLE_OAUTH_ACCESS_TOKEN", "").strip()
    if access_token:
        return firestore.Client(
            project=project_id,
            credentials=Credentials(token=access_token),
        )
    return firestore.Client(project=project_id)


def delete_temporary_school(store: FirestoreScheduleStore) -> bool:
    collections = (
        store._teachers,
        store._drafts,
        store._history,
        store._backups,
        store._school.collection("state"),
    )
    for collection in collections:
        for document in collection.stream():
            document.reference.delete()
    store._school.delete()
    return all(not list(collection.limit(1).stream()) for collection in collections)


def main() -> int:
    args = parse_args()
    drill_id = f"restore-drill-{uuid.uuid4().hex[:12]}"
    operator = "automated-restore-drill@local"
    started_at = datetime.now(timezone.utc).isoformat()
    client = build_client(args.project)
    store = FirestoreScheduleStore(args.project, drill_id, client=client)
    result = {
        "status": "FAILED",
        "project": args.project,
        "temporary_school_id": drill_id,
        "started_at": started_at,
        "cleanup_verified": False,
    }

    baseline = {
        "label": "還原演練基準案件",
        "data": {
            "classes": [{"code": "1甲", "grade": 1}],
            "roster": {"T01": {"name": "演練教師"}},
            "subjects": {"國語文": {"hours": {"1": 1}}},
        },
        "schedule": {"1甲": {"1-1": {"subject": "國語文", "teacher": "T01"}}},
        "overlay": [],
        "schedule_ready": True,
    }

    try:
        first_draft = store.save_draft(baseline, operator)
        backup = store.create_backup(
            baseline,
            operator,
            source_draft_revision=first_draft["draft_revision"],
        )

        changed = deepcopy(baseline)
        changed["label"] = "故意修改後的案件"
        changed["data"]["classes"].append({"code": "9測", "grade": 9})
        changed_draft = store.save_draft(
            changed,
            operator,
            expected_draft_revision=first_draft["draft_revision"],
        )

        stored_backup = store.get_backup(backup["backup_id"])
        if not stored_backup:
            raise RuntimeError("找不到剛建立的案件還原點")
        restored_draft = store.save_draft(
            stored_backup["snapshot"],
            operator,
            expected_draft_revision=changed_draft["draft_revision"],
        )
        loaded = store.get_draft(operator)
        if loaded["snapshot"] != baseline:
            raise RuntimeError("還原後資料與基準案件不一致")
        if restored_draft["draft_revision"] == changed_draft["draft_revision"]:
            raise RuntimeError("還原後未建立新的草稿版本")

        result.update({
            "status": "PASSED",
            "backup_id": backup["backup_id"],
            "source_draft_revision": first_draft["draft_revision"],
            "changed_draft_revision": changed_draft["draft_revision"],
            "restored_draft_revision": restored_draft["draft_revision"],
            "restored_label": loaded["snapshot"]["label"],
            "backup_count": len(store.list_backups()),
        })
    finally:
        result["cleanup_verified"] = delete_temporary_school(store)
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0 if result["status"] == "PASSED" and result["cleanup_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
