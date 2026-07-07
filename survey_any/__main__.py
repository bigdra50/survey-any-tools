"""Entry point for ``python -m survey_any``."""

from __future__ import annotations

import sys

from survey_any.cli import main

if __name__ == "__main__":
    sys.exit(main())
