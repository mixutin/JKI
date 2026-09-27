"""Publish this verified source proposal as a draft PR using an explicitly authorized local gh login.

Dry-run is the default. Nothing is pushed, forked, committed, or posted without --publish.
This is an optional local publishing helper. Prefer an existing pull request when continuing
work that has already been published.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import uuid

BASE = "9214e8df7db8ac7d1fbee8cccdafa129b4705fa9"
UPSTREAM = "ridjan-xhika/JKI"


def verified_files(source: Path) -> list[Path]:
    manifest = json.loads((source / "SOURCE-MANIFEST.json").read_text())
    if manifest.get("upstream_base") != BASE or not isinstance(manifest.get("files"), dict):
        raise ValueError("Invalid source manifest")
    files = []
    for name, expected in manifest["files"].items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts or ".git" in relative.parts:
            raise ValueError("Unsafe source path")
        path = source.joinpath(*relative.parts)
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(source.resolve()):
            raise ValueError(f"Source is not a regular contained file: {name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Source checksum mismatch: {name}")
        files.append(path)
    return files


def run(command: list[str], *, cwd: Path | None = None, capture: bool = False) -> str:
    result = subprocess.run(command, cwd=cwd, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true", help="Create/reuse your fork, push a new branch, open a draft PR")
    parser.add_argument("--expected-user", default="mixutin", help="Abort unless gh is authenticated as this account")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    files = verified_files(source)
    print(f"Verified {len(files)} files for {UPSTREAM}, base {BASE}.")
    if not args.publish:
        print("Dry run only. --publish explicitly authorizes fork/branch/commit/push/draft-PR creation.")
        return
    gh, git = shutil.which("gh"), shutil.which("git")
    if not gh or not git:
        parser.error("Install Git and GitHub CLI, authenticate gh, then run again")
    profile = json.loads(run([gh, "api", "user"], capture=True))
    owner = profile["login"]
    if owner.lower() != args.expected_user.lower():
        parser.error("The authenticated GitHub account does not match --expected-user; no write was made")
    remote_base = run([gh, "api", f"repos/{UPSTREAM}/commits/main", "--jq", ".sha"], capture=True)
    if remote_base != BASE:
        parser.error("Upstream main changed. Reconcile this proposal before publishing; no write was made")
    fork = f"{owner}/JKI"
    run([gh, "repo", "fork", UPSTREAM, "--clone=false"])
    metadata = json.loads(run([gh, "api", f"repos/{fork}"], capture=True))
    if metadata.get("parent", {}).get("full_name", "").lower() != UPSTREAM.lower():
        parser.error("Target repository is not the expected fork; nothing will be pushed")
    branch = "improve/voice-control-and-progress-" + uuid.uuid4().hex[:8]
    work = Path(tempfile.mkdtemp(prefix="jki-pr-"))
    print(f"Working checkout retained at {work}")
    run([git, "clone", "--no-checkout", metadata["clone_url"], str(work / "repo")])
    checkout = work / "repo"
    run([git, "fetch", "origin", BASE], cwd=checkout)
    run([git, "switch", "-c", branch, BASE], cwd=checkout)
    for path in files:
        destination = checkout / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    shutil.copyfile(source / "SOURCE-MANIFEST.json", checkout / "SOURCE-MANIFEST.json")
    run([git, "config", "user.name", owner], cwd=checkout)
    run([git, "config", "user.email", f"{profile['id']}+{owner}@users.noreply.github.com"], cwd=checkout)
    run([git, "add", "--all"], cwd=checkout)
    run([git, "diff", "--cached", "--check"], cwd=checkout)
    run([git, "commit", "-m", "Harden voice control, approvals and lifecycle; add factual spoken progress"], cwd=checkout)
    run([git, "push", "--set-upstream", "origin", branch], cwd=checkout)
    run([gh, "pr", "create", "--repo", UPSTREAM, "--base", "main", "--head", f"{owner}:{branch}",
         "--draft", "--title", "Harden voice control, approvals, setup and factual spoken progress",
         "--body-file", str(source / "docs" / "PR_DESCRIPTION.md")], cwd=checkout)


if __name__ == "__main__":
    main()
