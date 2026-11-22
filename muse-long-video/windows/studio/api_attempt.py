"""Submit once, retaining a safe distinction between rejection and lost receipts."""
import json
import re
import sys
from pathlib import Path

from paths import SKILL
sys.path.insert(0, str(SKILL / "scripts"))
import video_api as adapter


def rejected_http(exc):
    match = re.fullmatch(r"API HTTP (\d{3}); request not retried\.", str(exc))
    if match and int(match[1]) in {400, 401, 402, 403, 404, 405, 413, 415, 422, 429}:
        return match[1]


def main(profile, receipt, request, folder):
    config = adapter.read(profile)
    rejection = None
    def transport(method, url, *args, **kwargs):
        nonlocal rejection
        try:
            return adapter.http(method, url, *args, **kwargs)
        except adapter.ApiError as exc:
            if method == "POST" and url == adapter.endpoint(config, "submit"):
                rejection = rejected_http(exc)
            raise
    try:
        result = adapter.submit(config, adapter.read(receipt), adapter.read(request), folder, True, transport=transport)
    except (adapter.ApiError, ValueError, OSError):
        state = Path(folder) / "attempt.json"
        if rejection or (state.is_file() and adapter.read(state).get("status") in {"upload_failed", "prepared"}):
            print(rejection or "upload")
            return 3
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
