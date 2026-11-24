#!/usr/bin/env python3
"""Publish one advisory review using line anchors from the captured GitHub diff."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from collect_context import ApiError, Config, _request

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def changed_lines(patch: str) -> set[tuple[str, int]]:
    """Return changed line anchors from complete hunks, including deletions."""
    anchors: set[tuple[str, int]] = set()
    hunk: set[tuple[str, int]] = set()
    old_left = new_left = 0
    for row in patch.split("\n"):
        match = _HUNK.match(row)
        if match:
            old_start, old_count, new_start, new_count = match.groups()
            old_line, new_line = int(old_start), int(new_start)
            old_left = int(old_count or "1")
            new_left = int(new_count or "1")
            hunk = set()
            continue

        if not (old_left or new_left) or row.startswith("\\"):
            continue
        if row.startswith("-") and old_left:
            hunk.add(("LEFT", old_line))
            old_line += 1
            old_left -= 1
        elif row.startswith("+") and new_left:
            hunk.add(("RIGHT", new_line))
            new_line += 1
            new_left -= 1
        elif row.startswith(" ") and old_left and new_left:
            old_line += 1
            new_line += 1
            old_left -= 1
            new_left -= 1
        else:
            old_left = new_left = 0
            continue

        if not (old_left or new_left):
            anchors.update(hunk)
    return anchors


def _read_result(path: Path) -> Any:
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[len("```json\n") : -len("\n```")]
    return json.loads(text)


def build_review(
    result: Any, files: list[dict[str, Any]], head_sha: str
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ValueError("review output must be a JSON object")
    summary = result.get("summary")
    findings = result.get("findings")
    gaps = result.get("evidence_gaps")
    if (
        not isinstance(summary, str)
        or not summary.strip()
        or not isinstance(findings, list)
        or not isinstance(gaps, list)
        or any(not isinstance(gap, str) or not gap.strip() for gap in gaps)
    ):
        raise ValueError(
            "review output requires a summary, findings, and evidence gaps"
        )

    diff_lines = {
        file["filename"]: changed_lines(file["patch"])
        for file in files
        if isinstance(file.get("filename"), str) and isinstance(file.get("patch"), str)
    }
    comments = []
    unanchored = []
    counts = {"blocking": 0, "non-blocking": 0}
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("each finding must be an object")
        severity = finding.get("severity")
        body = finding.get("body")
        if not isinstance(severity, str) or severity not in counts:
            raise ValueError(
                "each finding requires a blocking or non-blocking severity"
            )
        if not isinstance(body, str) or not body.strip():
            raise ValueError("each finding requires a comment body")
        counts[severity] += 1
        body = f"**{severity.capitalize()}**\n\n{body.strip()}"

        location = finding.get("location")
        if isinstance(location, dict):
            path = location.get("path")
            line = location.get("line")
            side = location.get("side")
            if (
                isinstance(path, str)
                and type(line) is int
                and isinstance(side, str)
                and (side, line) in diff_lines.get(path, ())
            ):
                comments.append(
                    {"path": path, "line": line, "side": side, "body": body}
                )
                continue
        unanchored.append(body)

    sections = [
        "## AI PR Review",
        f"Head SHA: `{head_sha}`",
        "### Verdict",
        f"**Finding count:** B={counts['blocking']}, N={counts['non-blocking']}, G={len(gaps)}",
        summary.strip(),
    ]
    if unanchored:
        sections.extend(["### Findings without an inline location", *unanchored])
    if gaps:
        sections.extend(["### Evidence gaps", "\n".join(f"- {gap}" for gap in gaps)])
    sections.append("AI review is advisory. Maintainer review and CI still apply.")
    return {
        "commit_id": head_sha,
        "event": "COMMENT",
        "body": "\n\n".join(sections),
        "comments": comments,
    }


def publish(config: Config, head_sha: str, result: Path, comment_id: int) -> None:
    snapshot = json.loads((config.output_dir / "pr.json").read_text(encoding="utf-8"))
    if snapshot["number"] != config.pr_number or snapshot["head"]["sha"] != head_sha:
        raise ValueError("the captured context does not match the reviewed PR head")
    files = json.loads((config.output_dir / "files.json").read_text(encoding="utf-8"))
    review = build_review(_read_result(result), files, head_sha)

    pull_path = f"repos/{config.repo_slug}/pulls/{config.pr_number}"
    current = _request(config, pull_path)
    if (
        current["head"]["sha"] != head_sha
        or current["base"]["sha"] != snapshot["base"]["sha"]
        or current["base"]["ref"] != snapshot["base"]["ref"]
    ):
        print("Skipped review publication because the PR head or base changed.")
        return

    response = _request(config, f"{pull_path}/reviews", payload=review)
    print(f"Published advisory review {response['id']}.")

    reaction_path = f"repos/{config.repo_slug}/issues/comments/{comment_id}/reactions"
    _request(config, reaction_path, payload={"content": "rocket"})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--comment-id", type=int, required=True)
    parser.add_argument("--context", type=Path, default=Path("context"))
    parser.add_argument("--result", type=Path, default=Path("review.json"))
    args = parser.parse_args()

    owner, repo = os.environ["GITHUB_REPOSITORY"].split("/", 1)
    config = Config(
        owner,
        repo,
        args.pr,
        args.context,
        os.environ["GITHUB_TOKEN"],
        os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    )
    try:
        publish(config, args.head_sha, args.result, args.comment_id)
    except (ApiError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
