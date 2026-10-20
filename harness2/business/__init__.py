"""Portable, offline business replay. No sender or production credentials."""

import os

# Must precede imports of upstream config, which otherwise loads the checkout .env.
os.environ["HARNESS2_NO_DOTENV"] = "1"
