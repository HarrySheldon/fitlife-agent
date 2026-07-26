from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import unicodedata
from typing import Literal, Mapping


SegmentKind = Literal["food", "strength", "cardio", "unknown"]
MealContext = Literal["breakfast", "lunch", "dinner", "snack", "other"]

PARSER_VERSION = "smart-entry-parser-v1"


class SmartEntryDomainError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ParsedSegment:
    id: str
    kind: SegmentKind
    raw_text: str
    normalized_text: str
    subject_text: str
    issues: tuple[str, ...]
    meal_context: MealContext | None = None
    food_amount: float | None = None
    food_unit: str | None = None
    set_count: int | None = None
    reps: int | None = None
    load_kg: float | None = None
    bodyweight: bool = False
    duration_min: float | None = None
    device_calories: float | None = None


@dataclass(frozen=True)
class ParsedEntry:
    raw_text: str
    segments: tuple[ParsedSegment, ...]
    parser_version: str = PARSER_VERSION


@dataclass(frozen=True)
class CatalogChoice:
    id: str
    name: str
    source: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedCandidate:
    id: str
    kind: SegmentKind
    raw_text: str
    normalized_text: str
    subject_text: str
    meal_context: MealContext | None
    selected: bool
    selected_catalog_id: str | None
    catalog_choices: tuple[CatalogChoice, ...]
    issues: tuple[str, ...]
    values: dict[str, object]
    provenance: dict[str, object]
    assumptions: tuple[str, ...] = ()
    agent_estimate_accepted: bool = False


_MEAL_LABELS: dict[str, MealContext] = {
    "\u65e9\u9910": "breakfast",
    "\u65e9\u996d": "breakfast",
    "breakfast": "breakfast",
    "\u5348\u9910": "lunch",
    "\u5348\u996d": "lunch",
    "lunch": "lunch",
    "\u665a\u9910": "dinner",
    "\u665a\u996d": "dinner",
    "dinner": "dinner",
    "\u52a0\u9910": "snack",
    "\u96f6\u98df": "snack",
    "snack": "snack",
}
_STRENGTH_LABELS = {
    "\u529b\u91cf",
    "\u529b\u91cf\u8bad\u7ec3",
    "strength",
    "weights",
}
_CARDIO_LABELS = {
    "\u6709\u6c27",
    "\u6709\u6c27\u8bad\u7ec3",
    "cardio",
}
_CARDIO_TERMS = (
    "\u8dd1\u6b65",
    "\u6b65\u884c",
    "\u9a91\u884c",
    "\u6e38\u6cf3",
    "\u5212\u8239",
    "run",
    "walk",
    "bike",
    "cycle",
    "swim",
    "row",
    "cardio",
)
_AGENT_ALLOWED_FIELDS: dict[SegmentKind, frozenset[str]] = {
    "food": frozenset(
        {
            "canonical_name",
            "calories",
            "carbs",
            "protein",
            "fat",
            "basis",
            "serving_assumption",
            "ranges",
            "assumptions",
        }
    ),
    "strength": frozenset(
        {
            "canonical_name",
            "exercise_type",
            "primary_muscle",
            "secondary_muscles",
            "met",
            "assumptions",
        }
    ),
    "cardio": frozenset(
        {
            "canonical_name",
            "exercise_type",
            "primary_muscle",
            "secondary_muscles",
            "met",
            "assumptions",
        }
    ),
    "unknown": frozenset(),
}
_OBSERVED_FIELDS = frozenset(
    {
        "food_amount",
        "food_unit",
        "set_count",
        "sets",
        "reps",
        "load",
        "load_kg",
        "bodyweight",
        "duration",
        "duration_min",
        "device_calories",
    }
)


def parse_entry_text(text: str) -> ParsedEntry:
    if not isinstance(text, str):
        raise SmartEntryDomainError("SMART_ENTRY_TEXT_INVALID")
    raw = text.strip()
    segments: list[ParsedSegment] = []
    for block in _blocks(raw):
        label, content = _label_and_content(block)
        meal_context = _MEAL_LABELS.get(label)
        kind_hint = _label_kind(label)
        parts = _meal_parts(content) if meal_context is not None else [content]
        for part in parts:
            cleaned = part.strip(" ,;")
            if not cleaned:
                continue
            normalized = _normalize(cleaned)
            kind = kind_hint or _infer_kind(normalized)
            amount, unit = _food_amount(normalized)
            set_count, reps = _strength_volume(normalized)
            load_kg = _load(normalized) if kind == "strength" else None
            bodyweight = (
                _contains_any(
                    normalized,
                    ("\u81ea\u91cd", "bodyweight", "body weight"),
                )
                if kind == "strength"
                else False
            )
            duration_min = _duration(normalized) if kind == "cardio" else None
            device_calories = (
                _device_calories(normalized) if kind == "cardio" else None
            )
            segment = ParsedSegment(
                id=_segment_id(len(segments), normalized),
                kind=kind,
                raw_text=cleaned,
                normalized_text=normalized,
                subject_text=_subject_text(normalized, kind),
                issues=_issues(
                    kind=kind,
                    food_amount=amount,
                    food_unit=unit,
                    set_count=set_count,
                    reps=reps,
                    duration_min=duration_min,
                ),
                meal_context=meal_context,
                food_amount=amount if kind == "food" else None,
                food_unit=unit if kind == "food" else None,
                set_count=set_count if kind == "strength" else None,
                reps=reps if kind == "strength" else None,
                load_kg=load_kg,
                bodyweight=bodyweight,
                duration_min=duration_min,
                device_calories=device_calories,
            )
            segments.append(segment)
    return ParsedEntry(raw_text=raw, segments=tuple(segments))


def validate_agent_patch(
    segment: ParsedSegment,
    patch: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(patch, Mapping):
        raise SmartEntryDomainError("SMART_ENTRY_AGENT_PATCH_INVALID")
    fields = frozenset(patch)
    if fields & _OBSERVED_FIELDS:
        raise SmartEntryDomainError("SMART_ENTRY_AGENT_OBSERVED_FIELD_FORBIDDEN")
    if not fields <= _AGENT_ALLOWED_FIELDS[segment.kind]:
        raise SmartEntryDomainError("SMART_ENTRY_AGENT_PATCH_FIELD_FORBIDDEN")
    return dict(patch)


def _blocks(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text)
    return [
        value.strip()
        for value in re.split(r"[\r\n;]+", normalized)
        if value.strip()
    ]


def _label_and_content(value: str) -> tuple[str, str]:
    match = re.match(r"^\s*([^:]{1,16})\s*:\s*(.+)$", value)
    if match is None:
        return "", value
    return _normalize(match.group(1)), match.group(2)


def _label_kind(label: str) -> SegmentKind | None:
    if label in _MEAL_LABELS:
        return "food"
    if label in _STRENGTH_LABELS:
        return "strength"
    if label in _CARDIO_LABELS:
        return "cardio"
    return None


def _meal_parts(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _infer_kind(value: str) -> SegmentKind:
    if _strength_volume(value) != (None, None):
        return "strength"
    if _contains_any(value, _CARDIO_TERMS) and _duration(value) is not None:
        return "cardio"
    if _food_amount(value) != (None, None):
        return "food"
    return "unknown"


def _food_amount(value: str) -> tuple[float | None, str | None]:
    match = re.search(
        r"(?<![\dx])(\d+(?:\.\d+)?)\s*"
        r"(kg|g|ml|\u6beb\u5347|\u514b|\u4efd|servings?|cups?)",
        value,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None, None
    unit = match.group(2).lower()
    normalized_unit = {
        "\u514b": "g",
        "\u6beb\u5347": "ml",
        "\u4efd": "serving",
        "serving": "serving",
        "servings": "serving",
        "cup": "cup",
        "cups": "cup",
    }.get(unit, unit)
    amount = float(match.group(1))
    if normalized_unit == "kg":
        return amount * 1000, "g"
    return amount, normalized_unit


def _strength_volume(value: str) -> tuple[int | None, int | None]:
    compact = re.search(r"\b(\d{1,3})\s*[x\u00d7]\s*(\d{1,4})\b", value)
    if compact is not None:
        return int(compact.group(1)), int(compact.group(2))
    chinese = re.search(
        r"(\d{1,3})\s*\u7ec4"
        r"(?:\s*[,x\u00d7]?\s*(?:\u6bcf\u7ec4)?)?\s*"
        r"(\d{1,4})\s*\u6b21",
        value,
    )
    if chinese is not None:
        return int(chinese.group(1)), int(chinese.group(2))
    english = re.search(
        r"(\d{1,3})\s*sets?\s*(?:of\s*)?"
        r"(\d{1,4})(?:\s*reps?)?",
        value,
        flags=re.IGNORECASE,
    )
    if english is not None:
        return int(english.group(1)), int(english.group(2))
    return None, None


def _load(value: str) -> float | None:
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:kg|\u516c\u65a4|\u5343\u514b)",
        value,
    )
    return float(match.group(1)) if match is not None else None


def _duration(value: str) -> float | None:
    hours = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:\u5c0f\u65f6|hours?|hrs?)",
        value,
        flags=re.IGNORECASE,
    )
    if hours is not None:
        return float(hours.group(1)) * 60
    minutes = re.search(
        r"(\d+(?:\.\d+)?)\s*"
        r"(?:\u5206\u949f|\u5206|min|mins|minute|minutes)",
        value,
        flags=re.IGNORECASE,
    )
    return float(minutes.group(1)) if minutes is not None else None


def _device_calories(value: str) -> float | None:
    patterns = (
        r"(?:\u8bbe\u5907(?:\u6d88\u8017)?|"
        r"\u5668\u68b0(?:\u6d88\u8017)?|device)"
        r"\D{0,12}(\d+(?:\.\d+)?)\s*(?:\u5343\u5361|kcal)",
        r"(?:\u6d88\u8017|burned?)\D{0,8}"
        r"(\d+(?:\.\d+)?)\s*(?:\u5343\u5361|kcal)",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match is not None:
            return float(match.group(1))
    return None


def _subject_text(value: str, kind: SegmentKind) -> str:
    subject = value
    if kind == "food":
        subject = re.sub(
            r"\s*\d+(?:\.\d+)?\s*"
            r"(?:kg|g|ml|\u6beb\u5347|\u514b|\u4efd|servings?|cups?)",
            "",
            subject,
            flags=re.IGNORECASE,
        )
    elif kind == "strength":
        subject = re.sub(
            r"\s*\d{1,3}\s*[x\u00d7]\s*\d{1,4}\b",
            "",
            subject,
            flags=re.IGNORECASE,
        )
        subject = re.sub(
            r"\s*\d+(?:\.\d+)?\s*(?:kg|\u516c\u65a4|\u5343\u514b)",
            "",
            subject,
            flags=re.IGNORECASE,
        )
        subject = re.sub(
            r"\s*\d{1,3}\s*sets?\s*(?:of\s*)?"
            r"\d{1,4}(?:\s*reps?)?",
            "",
            subject,
            flags=re.IGNORECASE,
        )
    elif kind == "cardio":
        subject = re.sub(
            r"\s*\d+(?:\.\d+)?\s*"
            r"(?:\u5c0f\u65f6|hours?|hrs?|\u5206\u949f|\u5206|"
            r"min|mins|minute|minutes)",
            "",
            subject,
            flags=re.IGNORECASE,
        )
        subject = re.sub(
            r"[, ]*(?:\u8bbe\u5907(?:\u6d88\u8017)?|"
            r"\u5668\u68b0(?:\u6d88\u8017)?|device|"
            r"\u6d88\u8017|burned?)\D{0,12}"
            r"\d+(?:\.\d+)?\s*(?:\u5343\u5361|kcal)",
            "",
            subject,
            flags=re.IGNORECASE,
        )
    return re.sub(r"\s+", " ", subject).strip(" ,")


def _issues(
    *,
    kind: SegmentKind,
    food_amount: float | None,
    food_unit: str | None,
    set_count: int | None,
    reps: int | None,
    duration_min: float | None,
) -> tuple[str, ...]:
    if kind == "unknown":
        return ("SMART_ENTRY_KIND_UNRESOLVED",)
    if kind == "food" and (food_amount is None or food_unit is None):
        return ("SMART_ENTRY_FOOD_AMOUNT_REQUIRED",)
    if kind == "strength" and (set_count is None or reps is None):
        return ("SMART_ENTRY_STRENGTH_VOLUME_REQUIRED",)
    if kind == "cardio" and duration_min is None:
        return ("SMART_ENTRY_CARDIO_DURATION_REQUIRED",)
    return ()


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.translate(str.maketrans({"\uff0c": ",", "\uff1b": ";"}))
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def _contains_any(value: str, options: tuple[str, ...]) -> bool:
    return any(option.casefold() in value for option in options)


def _segment_id(index: int, normalized: str) -> str:
    identity = re.sub(r"\s*([,:;x\u00d7])\s*", r"\1", normalized)
    digest = hashlib.sha256(
        f"{index}:{identity}".encode("utf-8")
    ).hexdigest()[:16]
    return f"segment-{digest}"
