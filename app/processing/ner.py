"""
Rule-based Named Entity Recognition (NER) — no ML models.

Recognised entity types
───────────────────────
  DATE          — ISO, European, American, and Hebrew-month written dates
  TIME          — HH:MM and HH:MM:SS (24-hour and 12-hour)
  EMAIL         — RFC-5321-like email addresses
  PHONE         — Israeli (+972 / 05x) and international E.164 formats
  IP_ADDRESS    — IPv4 dotted-quad and IPv6 (full / abbreviated)
  URL           — http / https / ftp URLs
  HEBREW_NAME   — matched against a dictionary of common Hebrew first & last names
  ENGLISH_NAME  — matched against a dictionary of common English first & last names
  ISRAELI_ID    — 9-digit Israeli ID number (Luhn-like check digit validated)
  HASHTAG       — #word tokens
  MENTION       — @word tokens

All functions operate on str input and return a list of Entity objects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


# ── Entity dataclass ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Entity:
    type:  str
    value: str
    start: int   # character offset in the input string
    end:   int


# ── Dictionaries ──────────────────────────────────────────────────────────────

_HEBREW_FIRST_NAMES: frozenset[str] = frozenset({
    "אדר", "אביב", "אביגיל", "אבי", "אורן", "אורי", "אורית", "אסף", "אסתר",
    "איתי", "איתן", "אילן", "אילת", "אלון", "אלה", "אלי", "אמיר", "אנה",
    "בר", "בן", "בנימין", "ברק", "גל", "גלי", "גיא", "גיל", "דן", "דנה",
    "דניאל", "דפנה", "דרור", "הדר", "הילה", "זיו", "זוהר", "חן", "חנה",
    "טל", "טלי", "יאיר", "יהונתן", "יהלי", "יואב", "יוסף", "יוני", "יותם",
    "יעל", "יעקב", "ינאי", "כרמל", "לי", "ליאב", "ליאור", "ליאת", "לילי",
    "לירן", "מאיה", "מור", "מיה", "מיכל", "מירב", "מירי", "נועה", "נועם",
    "נטע", "ניר", "נמרוד", "ספיר", "עומר", "עמית", "עינב", "פלג", "צור",
    "קרן", "ראם", "ראובן", "רון", "רונן", "רועי", "רחל", "רינת", "רם",
    "שי", "שירה", "שני", "שרון", "תמר", "תומר",
})

_HEBREW_LAST_NAMES: frozenset[str] = frozenset({
    "אזולאי", "אברהם", "אדרי", "אוחיון", "אלוש", "אלמוג", "אמסלם", "ביטון",
    "בן-דוד", "בן-דוד", "בנימין", "ברוך", "גולן", "גל", "גרוס", "דהן",
    "דוד", "הרוש", "זוהר", "חביב", "חזן", "חיים", "טוביה", "יוסף",
    "כהן", "לוי", "מזרחי", "מלכה", "משה", "נחום", "סבג", "סיטון",
    "פרץ", "פרידמן", "צדוק", "קהן", "רוזן", "שаль", "שושן", "שיר",
    "שמיר", "שמעון", "תורג'מן",
})

_ENGLISH_FIRST_NAMES: frozenset[str] = frozenset({
    "Aaron", "Adam", "Alex", "Alice", "Amir", "Andrew", "Anna", "Ben",
    "Brian", "Charles", "Charlotte", "Chris", "Daniel", "David", "Diana",
    "Edward", "Elizabeth", "Emma", "Eric", "Eva", "George", "Hannah",
    "Henry", "Jack", "Jacob", "James", "Jane", "Jennifer", "Jessica",
    "John", "Jonathan", "Joseph", "Joshua", "Julia", "Kate", "Kevin",
    "Laura", "Lauren", "Liam", "Lisa", "Lucas", "Luke", "Mark", "Mary",
    "Matthew", "Michael", "Michelle", "Nathan", "Nicholas", "Noah",
    "Olivia", "Patrick", "Paul", "Peter", "Rachel", "Robert", "Ryan",
    "Samuel", "Sarah", "Sophia", "Stephen", "Susan", "Thomas", "William",
})

_ENGLISH_LAST_NAMES: frozenset[str] = frozenset({
    "Adams", "Anderson", "Baker", "Brown", "Campbell", "Carter", "Clark",
    "Collins", "Davis", "Edwards", "Evans", "Garcia", "Green", "Hall",
    "Harris", "Hill", "Jackson", "Johnson", "Jones", "King", "Lee",
    "Lewis", "Martin", "Martinez", "Miller", "Mitchell", "Moore",
    "Morgan", "Nelson", "Parker", "Patel", "Phillips", "Roberts",
    "Robinson", "Rodriguez", "Scott", "Smith", "Taylor", "Thomas",
    "Thompson", "Turner", "Walker", "White", "Williams", "Wilson",
    "Wright", "Young",
})


# ── Compiled regex patterns ───────────────────────────────────────────────────

_EN_MONTHS = (
    r"(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
)
_HE_MONTHS = (
    r"(?:ינואר|פברואר|מרץ|אפריל|מאי|יוני|יולי|אוגוסט|"
    r"ספטמבר|אוקטובר|נובמבר|דצמבר|"
    r"בינואר|בפברואר|במרץ|באפריל|במאי|ביוני|"
    r"ביולי|באוגוסט|בספטמבר|באוקטובר|בנובמבר|בדצמבר)"
)

_RE_DATE = re.compile(
    r"\b(?:"
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"                   # ISO: 2024-05-01
    r"|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}"               # EU:  01.05.2024
    r"|\d{1,2}\s+" + _EN_MONTHS + r"(?:\s+\d{2,4})?"  # Written EN: 1 May 2024
    r"|\d{1,2}\s+" + _HE_MONTHS + r"(?:\s+\d{2,4})?"  # Written HE
    r")\b"
)

_RE_TIME = re.compile(
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:\s?[AP]M)?\b",
    re.IGNORECASE,
)

_RE_EMAIL = re.compile(
    r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"
)

_RE_PHONE = re.compile(
    r"(?:"
    r"\+972[-\s]?(?:[23489]|5[0-9]|77)[-\s]?\d{3}[-\s]?\d{4}"  # Israeli intl
    r"|0(?:[23489]|5[0-9]|77)[-\s]?\d{3}[-\s]?\d{4}"            # Israeli local
    r"|\+[1-9]\d{1,3}[-\s]?\(?\d+\)?[-\s]?\d+[-\s]?\d+"         # Intl E.164
    r")"
)

_RE_IPV4 = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
)

_RE_IPV6 = re.compile(
    r"\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}\b"
)

_RE_URL = re.compile(
    r"\bhttps?://[^\s\"'<>]+|\bftp://[^\s\"'<>]+"
)

_RE_ISRAELI_ID = re.compile(r"\b\d{9}\b")

_RE_HASHTAG  = re.compile(r"(?<!\w)#[\w֐-׿]+")
_RE_MENTION  = re.compile(r"(?<!\w)@[\w֐-׿]+")


# ── Israeli ID check-digit validation (Luhn-like) ────────────────────────────

def _valid_israeli_id(id_str: str) -> bool:
    if len(id_str) != 9:
        return False
    total = 0
    for i, ch in enumerate(id_str):
        digit = int(ch) * (1 if i % 2 == 0 else 2)
        total += digit - 9 if digit > 9 else digit
    return total % 10 == 0


# ── Name matching ─────────────────────────────────────────────────────────────

_RE_WORD_BOUNDARY = re.compile(
    r"(?:^|(?<=[\s,.()\[\]\"']))"
    r"([֐-׿]{2,}|[A-Z][a-z]+)"
    r"(?=$|[\s,.()\[\]\"'])",
    re.MULTILINE,
)


def _match_names(
    text: str,
    first_names: frozenset,
    last_names:  frozenset,
    entity_type: str,
) -> list[Entity]:
    entities: list[Entity] = []
    for m in _RE_WORD_BOUNDARY.finditer(text):
        token = m.group(1)
        if token in first_names or token in last_names:
            entities.append(Entity(entity_type, token, m.start(1), m.end(1)))
    return entities


# ── Main extraction function ──────────────────────────────────────────────────

def extract_entities(text: str) -> list[Entity]:
    """
    Extract all recognised entities from *text*.
    Returns a list of Entity objects sorted by start offset.
    """
    entities: list[Entity] = []

    def _add(pattern: re.Pattern, etype: str, validator: Callable[[str], bool] | None = None):
        for m in pattern.finditer(text):
            val = m.group()
            if validator and not validator(val):
                continue
            entities.append(Entity(etype, val, m.start(), m.end()))

    _add(_RE_DATE,       "DATE")
    _add(_RE_TIME,       "TIME")
    _add(_RE_EMAIL,      "EMAIL")
    _add(_RE_PHONE,      "PHONE")
    _add(_RE_IPV4,       "IP_ADDRESS")
    _add(_RE_IPV6,       "IP_ADDRESS")
    _add(_RE_URL,        "URL")
    _add(_RE_HASHTAG,    "HASHTAG")
    _add(_RE_MENTION,    "MENTION")
    _add(_RE_ISRAELI_ID, "ISRAELI_ID", _valid_israeli_id)

    entities += _match_names(text, _HEBREW_FIRST_NAMES,  _HEBREW_LAST_NAMES,  "HEBREW_NAME")
    entities += _match_names(text, _ENGLISH_FIRST_NAMES, _ENGLISH_LAST_NAMES, "ENGLISH_NAME")

    entities.sort(key=lambda e: e.start)
    return entities


# ── Context enrichment ────────────────────────────────────────────────────────

def enrich_match(
    text:        str,
    byte_offset: int,
    pattern_len: int,
    context_chars: int = 120,
) -> dict:
    """
    For a single search match (byte offset), extract surrounding context and
    run NER on that context window.

    Returns a dict with keys: position, snippet, entities.
    """
    # Convert byte offset to character offset (UTF-8)
    text_bytes = text.encode("utf-8")
    char_offset = len(text_bytes[:byte_offset].decode("utf-8", errors="replace"))

    ctx_start = max(0, char_offset - context_chars)
    ctx_end   = min(len(text), char_offset + pattern_len + context_chars)
    snippet   = text[ctx_start:ctx_end]

    entities = extract_entities(snippet)
    # Shift entity offsets to be relative to the full text
    adjusted = [
        Entity(e.type, e.value, e.start + ctx_start, e.end + ctx_start)
        for e in entities
    ]

    return {
        "byte_offset": byte_offset,
        "char_offset": char_offset,
        "snippet":     snippet,
        "entities":    [{"type": e.type, "value": e.value,
                         "start": e.start, "end": e.end}
                        for e in adjusted],
    }
