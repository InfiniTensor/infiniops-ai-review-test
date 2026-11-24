import json
from io import BytesIO

import pytest

import collect_context
import publish_review
from collect_context import ApiError, Config

HEAD = "a" * 40
BASE = "b" * 40
FILE = "src/example.h"
PULL_PATH = "repos/owner/repo/pulls/7"
PATCH = """@@ -5,4 +5,4 @@
 same
-before
+after
 keep
 tail"""
FILES = [{"filename": FILE, "previous_filename": "src/old.h", "patch": PATCH}]


def finding(line, side="RIGHT", path=FILE, body="Check the output layout."):
    return {
        "severity": "blocking",
        "body": body,
        "location": {"path": path, "line": line, "side": side},
    }


def result(*findings):
    return {
        "summary": "Check the layout contract.",
        "findings": list(findings),
        "evidence_gaps": ["Target device coverage is unknown."],
    }


def pull(head=HEAD, base=BASE, ref="master"):
    return {"number": 7, "head": {"sha": head}, "base": {"sha": base, "ref": ref}}


def test_anchors_come_from_complete_hunks():
    truncated = "\n@@ -20,3 +20,3 @@\n-old\n+new"
    assert publish_review.changed_lines(PATCH + truncated) == {
        ("LEFT", 6),
        ("RIGHT", 6),
    }
    assert publish_review.changed_lines("@@ -0,0 +1 @@\n+new") == {("RIGHT", 1)}
    assert publish_review.changed_lines("@@ -1 +0,0 @@\n-old") == {("LEFT", 1)}


def test_review_keeps_findings_without_valid_anchors():
    review = publish_review.build_review(
        result(
            finding(6),
            finding(6, "LEFT"),
            finding(7, body="Context line finding."),
            finding(6, path="src/old.h", body="Old name finding."),
            finding(True, body="Invalid line number."),
        ),
        FILES,
        HEAD,
    )

    assert review["commit_id"] == HEAD
    assert review["event"] == "COMMENT"
    assert [(c["line"], c["side"]) for c in review["comments"]] == [
        (6, "RIGHT"),
        (6, "LEFT"),
    ]
    assert "B=5, N=0, G=1" in review["body"]
    assert "Context line finding." in review["body"]
    assert "Old name finding." in review["body"]
    assert "Invalid line number." in review["body"]
    assert "Target device coverage is unknown." in review["body"]


@pytest.mark.parametrize(
    "current",
    [pull(), pull(head="c" * 40), pull(base="c" * 40), pull(ref="develop")],
    ids=["current", "new-head", "new-base", "retargeted"],
)
def test_publish_checks_snapshot_before_posting(monkeypatch, tmp_path, current):
    output = tmp_path / "review.json"
    output.write_text(json.dumps(result(finding(6))), encoding="utf-8")
    (tmp_path / "pr.json").write_text(json.dumps(pull()), encoding="utf-8")
    (tmp_path / "files.json").write_text(json.dumps(FILES), encoding="utf-8")
    calls = []

    def request(config, path, *, payload=None):
        calls.append((path, payload))
        return current if path == PULL_PATH else {"id": 1}

    monkeypatch.setattr(publish_review, "_request", request)
    config = Config("owner", "repo", 7, tmp_path, None, "https://api.example.com")
    publish_review.publish(config, HEAD, output, 42)

    assert calls[0] == (PULL_PATH, None)
    if current != pull():
        assert len(calls) == 1
        return

    assert [item[0] for item in calls[1:]] == [
        f"{PULL_PATH}/reviews",
        "repos/owner/repo/issues/comments/42/reactions",
    ]
    assert len(calls[1][1]["comments"]) == 1
    assert calls[2][1] == {"content": "rocket"}


def test_capture_rejects_head_change_after_reading_the_diff(monkeypatch, tmp_path):
    snapshots = iter([pull(), pull(head="c" * 40)])
    monkeypatch.setattr(collect_context, "_request", lambda *args: next(snapshots))
    monkeypatch.setattr(collect_context, "_paginated", lambda *args: iter(()))
    config = Config("owner", "repo", 7, tmp_path, None, "https://api.example.com", HEAD)

    with pytest.raises(
        ApiError, match="PR head or base changed during context capture"
    ):
        collect_context.collect(config)

    assert not (tmp_path / "files.json").exists()


def test_github_api_helper_sends_a_json_post(monkeypatch, tmp_path):
    body = {"commit_id": HEAD, "event": "COMMENT", "comments": []}

    def urlopen(request, *, timeout):
        assert request.get_method() == "POST"
        assert request.full_url == f"https://api.example.com/{PULL_PATH}/reviews"
        assert request.headers["Content-type"] == "application/json"
        assert json.loads(request.data) == body
        return BytesIO(b'{"id": 42}')

    monkeypatch.setattr(collect_context, "urlopen", urlopen)
    config = Config("owner", "repo", 7, tmp_path, None, "https://api.example.com")

    assert collect_context._request(config, f"{PULL_PATH}/reviews", payload=body) == {
        "id": 42
    }
