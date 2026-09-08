from __future__ import annotations

import scraper
from price_guard import VERSION, install


install(scraper)

import tracker


tracker.VERSION = VERSION
tracker.COMPATIBLE_STATE_VERSIONS.add(VERSION)

main = tracker.main


if __name__ == "__main__":
    main()
