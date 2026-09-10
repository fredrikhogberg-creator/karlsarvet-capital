import os
import requests

BASE_URL = "https://apiservice.borsdata.se/v1"


def get_json(path, **params):
    key = os.environ.get("BORSDATA_API_KEY")
    if not key:
        raise RuntimeError("BORSDATA_API_KEY is missing")
    query = dict(params)
    query["authKey"] = key
    response = requests.get(f"{BASE_URL}/{path.lstrip('/')}" , params=query, timeout=30)
    response.raise_for_status()
    return response.json()


def instruments():
    return get_json("instruments")


def stockprices(instrument_id, from_date=None, to_date=None):
    return get_json(
        f"instruments/{instrument_id}/stockprices",
        **{"from": from_date, "to": to_date},
    )
