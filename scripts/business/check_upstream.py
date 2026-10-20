"""Read only: report public upstream HEAD versus the manually accepted business base."""

import json
import re
import urllib.request
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[2]
    accepted = json.loads((root / "UPSTREAM.json").read_text(encoding="utf-8"))
    request = urllib.request.Request(
        "https://api.github.com/repos/google-research/harness2/commits/main",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "harness2-business-readonly"},
    )
    # No token, no checkout, no PR or issue, no model and no write-back to accepted state.
    with urllib.request.urlopen(request, timeout=30) as response:
        candidate = json.load(response)["sha"]
    if not isinstance(candidate, str) or not re.fullmatch("[a-f0-9]{40}", candidate):
        raise ValueError("Public upstream returned an invalid commit")
    print(json.dumps({"accepted": accepted["accepted_upstream_commit"],
                      "candidate": candidate,
                      "changed": candidate != accepted["accepted_upstream_commit"],
                      "promotion": "manual_review_only"}, indent=2))


if __name__ == "__main__":
    main()
