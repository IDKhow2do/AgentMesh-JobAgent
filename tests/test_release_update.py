from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from jobagent.infra.release_update import _archive_sha256


def _run(root: Path, *args: str) -> bytes:
    return subprocess.run(
        list(args),
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def test_archive_hash_ignores_machine_git_archive_configuration(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-q")
    _run(repo, "git", "config", "user.name", "Job Agent Test")
    _run(repo, "git", "config", "user.email", "test@localhost")
    (repo / "file.txt").write_text("canonical release\n", encoding="utf-8")
    _run(repo, "git", "add", "file.txt")
    _run(repo, "git", "commit", "-qm", "fixture")
    commit = _run(repo, "git", "rev-parse", "HEAD").decode().strip()

    external_attributes = tmp_path / "global-attributes"
    external_attributes.write_text("* export-ignore\n", encoding="utf-8")
    _run(repo, "git", "config", "tar.umask", "077")
    _run(repo, "git", "config", "core.attributesFile", str(external_attributes))

    env = os.environ.copy()
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_ATTR_NOSYSTEM"] = "1"
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    canonical = subprocess.run(
        [
            "git",
            "-c",
            "tar.umask=002",
            "-c",
            f"core.attributesFile={os.devnull}",
            "archive",
            "--format=tar",
            commit,
        ],
        cwd=repo,
        env=env,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout

    assert _archive_sha256(repo, commit) == hashlib.sha256(canonical).hexdigest()
    assert _archive_sha256(repo, commit) != hashlib.sha256(
        _run(repo, "git", "archive", "--format=tar", commit)
    ).hexdigest()
