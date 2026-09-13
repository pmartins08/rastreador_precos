"""Compatibility stub for the completed 2026-09-13 one-shot campaign.

The historical Top 3 / Diamond replay request has been completed.  The
production workflow still invokes this path for backwards compatibility, so
keeping a harmless no-op avoids coupling repository cleanup to a workflow
rewrite.  No notification is ever sent from this module.
"""

from __future__ import annotations


def main() -> None:
    print("ONE_SHOT_CAMPAIGN_RETIRED: no notification sent")


if __name__ == "__main__":
    main()
