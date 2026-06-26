"""Docker HEALTHCHECK — API up (200 hoặc 401 khi bật auth)."""
from __future__ import annotations

import sys
import urllib.error
import urllib.request


def main() -> None:
    try:
        urllib.request.urlopen("http://127.0.0.1:8080/api/config", timeout=4)
    except urllib.error.HTTPError as exc:
        sys.exit(0 if exc.code in (200, 401) else 1)
    except Exception:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
