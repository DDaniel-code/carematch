"""Parsing and geometry helpers.

Adapted from the feature/search branch of Sa1kyo121/carematch-india (Charlie's search MVP):
JSON-array field parsing, URL extraction, coordinate validation and haversine distance.
"""
import hashlib
import json
import math
import re
import unicodedata
from urllib.parse import urlsplit

EMPTY_STRINGS = {'', '[]', 'null', 'none', 'nan'}


def text(value):
    return '' if value is None else str(value).strip()


def normalize(value):
    """Unicode-normalize, casefold and collapse whitespace."""
    return ' '.join(unicodedata.normalize('NFKC', text(value)).casefold().split())


def is_empty(value):
    return normalize(value) in EMPTY_STRINGS


def split_camel(value):
    """'obstetricsAndGynecology' -> 'obstetrics And Gynecology'."""
    return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', text(value))


def stable_id(value, length=16):
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:length]


def audit_source_rows(rows):
    """Split facility rows into (accepted, quarantined). Nothing is repaired and the source is not changed.

    A few source rows are column-shifted: a description fragment sits in `unique_id` and a number, a JSON null or a
    GeoJSON point sits in `specialties`. `specialties` is an array<string> stored as JSON text, so a row whose
    `specialties` is neither empty (SQL NULL) nor a JSON list of strings is such a row. It is set aside and counted
    instead of being indexed as a facility. Same rule as audit_source_rows in Sa1kyo121/carematch-india, so both
    pipelines quarantine the same rows.
    """
    accepted, quarantined = [], []
    for row in rows:
        raw = row.get('specialties')
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            valid = True
        else:
            try:
                parsed = raw if isinstance(raw, (list, tuple)) else json.loads(raw)
                valid = isinstance(parsed, (list, tuple)) and all(x is None or isinstance(x, str) for x in parsed)
            except (ValueError, TypeError):
                valid = False
        if valid:
            accepted.append(row)
        else:
            quarantined.append({'source_record_id': 'record-' + stable_id(row, 24), 'unique_id_raw': row.get('unique_id'),
                                'reason': 'specialties_not_json_string_array'})
    return accepted, quarantined


def fragments(value):
    """Return the string items of a JSON-array-as-string field; never JSON object keys.

    Null elements and empty strings are dropped; exact duplicates are removed in order.
    """
    out = []

    def walk(v):
        if v is None:
            return
        if isinstance(v, dict):
            for item in v.values():
                walk(item)
            return
        if isinstance(v, (list, tuple)):
            for item in v:
                walk(item)
            return
        if isinstance(v, (bool, int, float)):
            return  # numbers inside JSON are not evidence text
        raw = text(v)
        if is_empty(raw):
            return
        if raw[:1] in '[{"':
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                parsed = raw
            if parsed != raw:
                walk(parsed)
                return
        out.append(raw)

    walk(value)
    seen, unique = set(), []
    for item in out:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def source_urls(value):
    """Explicit http(s) URLs only; no inferred domains, no network calls."""
    urls = set()
    for part in fragments(value):
        for url in re.findall(r'https?://[^\s<>"\',;\]\}]+', part):
            url = url.rstrip(').')
            try:
                parsed = urlsplit(url)
            except ValueError:
                continue
            if parsed.hostname and not parsed.username and not parsed.password:
                urls.add(url)
    return sorted(urls)


def valid_coords(lat, lon):
    """(lat, lon) floats if finite and inside a generous India bounding box, else None."""
    try:
        if isinstance(lat, bool) or isinstance(lon, bool):
            return None
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    if not (6.0 <= lat <= 37.5 and 68.0 <= lon <= 98.5):
        return None
    return lat, lon


def haversine_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, h))))
