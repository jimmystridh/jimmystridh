#!/usr/bin/env python3
"""Fetch all repos for the authenticated GitHub user and write repos-data.json."""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

PAGE_SIZE = 50

QUERY = """
query($cursor: String) {
  viewer {
    repositories(
      first: %d
      after: $cursor
      orderBy: {field: UPDATED_AT, direction: DESC}
      ownerAffiliations: OWNER
    ) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        createdAt
        description
        forkCount
        isFork
        isPrivate
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node {
              name
            }
          }
        }
        name
        primaryLanguage {
          name
        }
        stargazerCount
        updatedAt
        url
        defaultBranchRef {
          target {
            ... on Commit {
              history(first: 1) {
                totalCount
                nodes {
                  committedDate
                }
              }
            }
          }
        }
      }
    }
  }
}
""" % PAGE_SIZE


def run_query(cursor: str | None = None, retries: int = 3) -> dict:
    cmd = ["gh", "api", "graphql", "-f", f"query={QUERY}"]
    if cursor:
        cmd += ["-f", f"cursor={cursor}"]

    for attempt in range(retries):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return json.loads(result.stdout)
        print(f"  Attempt {attempt + 1} failed: {result.stderr.strip()}", file=sys.stderr)
        if attempt < retries - 1:
            time.sleep(2 ** attempt)

    print("Failed after retries, aborting.", file=sys.stderr)
    sys.exit(1)


def transform_repo(node: dict) -> dict:
    branch_ref = node.get("defaultBranchRef") or {}
    target = branch_ref.get("target") or {}
    history = target.get("history") or {}

    commit_count = history.get("totalCount", 0)
    commits = history.get("nodes") or []
    last_commit_date = commits[0]["committedDate"] if commits else None

    return {
        "createdAt": node["createdAt"],
        "description": node["description"] or "",
        "forkCount": node["forkCount"],
        "isFork": node["isFork"],
        "isPrivate": node["isPrivate"],
        "languages": node["languages"]["edges"],
        "name": node["name"],
        "primaryLanguage": node["primaryLanguage"],
        "stargazerCount": node["stargazerCount"],
        "updatedAt": node["updatedAt"],
        "url": node["url"],
        "commitCount": commit_count,
        "lastCommitDate": last_commit_date,
    }


def update_html(base_dir: Path, repos: list[dict]):
    html_path = base_dir / "repo-catalog.html"
    html = html_path.read_text()
    inline_json = json.dumps(repos, separators=(",", ":"))
    replacement = f"const repos = {inline_json};"
    html, count = re.subn(
        r"const repos = \[.*?\];",
        lambda _: replacement,
        html,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        print("Warning: could not find 'const repos = [...]' in repo-catalog.html", file=sys.stderr)
        return
    html_path.write_text(html)
    print(f"Updated {html_path}", file=sys.stderr)


def main():
    repos = []
    cursor = None

    while True:
        data = run_query(cursor)
        page = data["data"]["viewer"]["repositories"]
        repos.extend(transform_repo(node) for node in page["nodes"])

        print(f"Fetched {len(repos)} repos...", file=sys.stderr)

        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    base_dir = Path(__file__).parent
    json_path = base_dir / "repos-data.json"
    json_path.write_text(json.dumps(repos, indent=2) + "\n")
    print(f"Wrote {len(repos)} repos to {json_path}", file=sys.stderr)

    update_html(base_dir, repos)


if __name__ == "__main__":
    main()
