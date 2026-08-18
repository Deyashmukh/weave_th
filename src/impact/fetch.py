"""Fetch PostHog PRs and ownership files from the GitHub API.

The repo is 6.4 GB, so cloning is not viable, and REST would need ~27k calls
against a 5,000/hr limit. GraphQL costs 4 points per 100 PRs, putting the whole
pull near 1,200 points.

Pagination walks merged PRs by UPDATED_AT descending and halts once a page's
oldest updatedAt precedes the cutoff. GitHub guarantees updatedAt >= mergedAt,
so that halt provably cannot skip a PR merged inside the window - which matters
because sorting by update time surfaces PRs merged as far back as 2020.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

CUTOFF = "2026-04-28T00:00:00Z"

PR_QUERY = """
query($cursor: String) {
  rateLimit { cost remaining }
  repository(owner: "PostHog", name: "posthog") {
    pullRequests(states: MERGED, first: 100, after: $cursor,
                 orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title body createdAt mergedAt updatedAt baseRefName
        additions deletions changedFiles
        author { login __typename }
        labels(first: 15) { nodes { name } }
        comments { totalCount }
        reviewThreads { totalCount }
        closingIssuesReferences(first: 5) { nodes { number } }
        reviews(first: 30) {
          totalCount
          nodes { state submittedAt body author { login __typename } }
        }
        files(first: 60) { totalCount nodes { path additions deletions } }
      }
    }
  }
}
"""


def _gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def fetch_ownership(dest: Path) -> int:
    """Pull CODEOWNERS and every distributed owners.yaml. Returns the owners count."""
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "CODEOWNERS").write_text(
        _gh(
            [
                "api",
                "repos/PostHog/posthog/contents/.github/CODEOWNERS",
                "-H",
                "Accept: application/vnd.github.raw",
            ]
        )
    )
    tree = json.loads(_gh(["api", "repos/PostHog/posthog/git/trees/master?recursive=1"]))
    owners_dir = dest / "owners"
    owners_dir.mkdir(exist_ok=True)
    count = 0
    for node in tree["tree"]:
        path = str(node["path"])
        if path.endswith("owners.yaml"):
            body = _gh(
                [
                    "api",
                    f"repos/PostHog/posthog/contents/{path}",
                    "-H",
                    "Accept: application/vnd.github.raw",
                ]
            )
            (owners_dir / path.replace("/", "__")).write_text(body)
            count += 1
    return count


def fetch_prs(dest: Path, cutoff: str = CUTOFF) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    query_file = dest.parent / "_query.graphql"
    query_file.write_text(PR_QUERY)
    cursor: str | None = None
    kept = 0
    with dest.open("w") as fh:
        while True:
            args = ["api", "graphql", "-F", f"query=@{query_file}"]
            args += ["-F", "cursor=null" if cursor is None else f"cursor={cursor}"]
            try:
                payload = json.loads(_gh(args))
            except subprocess.CalledProcessError:
                continue  # transient 502 on deep cursors; retry the same page
            conn = payload["data"]["repository"]["pullRequests"]
            nodes = conn["nodes"]
            for node in nodes:
                if node["mergedAt"] and node["mergedAt"] >= cutoff:
                    fh.write(json.dumps(node) + "\n")
                    kept += 1
            if min(n["updatedAt"] for n in nodes) < cutoff or not conn["pageInfo"]["hasNextPage"]:
                break
            cursor = conn["pageInfo"]["endCursor"]
    query_file.unlink(missing_ok=True)
    return kept


def main() -> None:
    root = Path("data")
    owners = fetch_ownership(root / "ownership")
    count = fetch_prs(root / "raw" / "prs.jsonl")
    print(f"fetched {count} PRs and {owners} owners.yaml files")


if __name__ == "__main__":
    main()
