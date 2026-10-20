"""The app runs as user `kb`: every /data volume it writes must exist in the image owned by kb
(Docker gives a new named volume the image folder's owner; otherwise it is root-owned and
uploads fail with "permission denied" — seen with dictation, 2026-10-20)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_data_volumes_are_created_and_owned_by_the_app_user():
    compose = (ROOT / "docker-compose.yml").read_text()
    dockerfile = (ROOT / "docker" / "Dockerfile").read_text()
    targets = set(
        re.findall(r"^\s*- [\w-]+:(/data/[\w/-]+|/models)(?::rw)?\s*(?:#.*)?$", compose, re.M)
    )
    assert {"/data/telegram", "/data/dictations", "/data/audio"} <= targets
    run = dockerfile[dockerfile.index("useradd") : dockerfile.index("USER kb")]
    for target in targets:
        assert re.search(rf"mkdir -p [^&]*{re.escape(target)}\b", run), f"{target} not created"
        assert re.search(rf"chown kb:kb [^&]*{re.escape(target)}\b", run), (
            f"{target} not owned by kb"
        )
