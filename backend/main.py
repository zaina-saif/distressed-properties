"""Scraper command line (the API is app.main): `python main.py scrape nj`, see pipeline.cli."""
import sys

from pipeline.cli import main

if __name__ == "__main__":
    sys.exit(main())
