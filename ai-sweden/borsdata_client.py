"""Börsdata REST client. Never expose URLs containing authKey in exceptions."""
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://apiservice.borsdata.se/v1"
_last_call = 0.0


class BorsdataError(RuntimeError):
    pass


def get_json(path, **params):
    global _last_call
    key = os.environ.get("BORSDATA_API_KEY", "").strip()
    if not key:
        raise BorsdataError("BORSDATA_API_KEY is missing")
    query = {k: v for k, v in params.items() if v is not None}
    query["authKey"] = key
    request = Request(f"{BASE_URL}/{path.lstrip('/')}?{urlencode(query)}",
                      headers={"Accept": "application/json", "User-Agent": "Karlsarvet-AI-Sweden/1.0"})
    for attempt in range(4):
        time.sleep(max(0, 0.15 - (time.monotonic() - _last_call)))
        _last_call = time.monotonic()
        try:
            with urlopen(request, timeout=45) as response:
                return json.load(response)
        except HTTPError as exc:
            status = exc.code
            if status not in (429, 500, 502, 503, 504) or attempt == 3:
                raise BorsdataError(f"Börsdata HTTP {status}") from None
        except (URLError, TimeoutError, OSError):
            if attempt == 3:
                raise BorsdataError("Börsdata network request failed") from None
        except (ValueError, UnicodeError):
            raise BorsdataError("Börsdata returned invalid JSON") from None
        time.sleep(2 ** attempt)


def instruments():
    return get_json("instruments")


def stockprices(instrument_id, from_date=None, to_date=None):
    return get_json(f"instruments/{int(instrument_id)}/stockprices",
                    **{"from": from_date, "to": to_date, "maxcount": 20})


def reports(instrument_id):
    # The combined endpoint uses two count parameters, unlike /reports/r12.
    return get_json(f"instruments/{int(instrument_id)}/reports",
                    maxYearCount=20, maxR12QCount=40, original=0)
