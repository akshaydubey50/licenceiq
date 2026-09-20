"""Run a safe OpenAI OCR startup check from the backend directory."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.providers.openai_runtime import (  # noqa: E402
    OpenAIRuntimeCheckError,
    verify_openai_ocr_runtime,
)


def main() -> int:
    """Return a clear local exit code without exposing an API key or provider body."""
    try:
        result = verify_openai_ocr_runtime(Settings())
    except OpenAIRuntimeCheckError as error:
        print(f"OpenAI OCR preflight failed: {error}", file=sys.stderr)
        return 1

    print(f"OpenAI OCR preflight passed for {result.model}. No document was sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
