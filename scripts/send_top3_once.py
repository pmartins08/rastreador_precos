"""Compatibility stub for completed one-shot Top 3 requests.

The production workflow still invokes this path for backwards compatibility.
Keeping a harmless no-op avoids coupling operational cleanup to a workflow
rewrite. No notification is ever sent from this module.
"""

from __future__ import annotations


def main() -> None:
    print("ONE_SHOT_TOP3_RETIRED: no notification sent")


if __name__ == "__main__":
    main()
