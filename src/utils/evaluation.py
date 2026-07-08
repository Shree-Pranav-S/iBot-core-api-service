"""Private helpers for recruiter-facing evaluation display and transcripts."""

from typing import Any

from src.schemas.candidate import TranscriptTurn


def _validated_violation_count(violation_summary: object) -> int:
    if not isinstance(violation_summary, dict):
        return 0
    raw_count = violation_summary.get("validated_violation_count", 0) or 0
    try:
        return int(raw_count)
    except (TypeError, ValueError):
        return 0


def _first_string(*values: object) -> str | None:
    for value in values:
        if value:
            return str(value)
    return None


def _safe_int(value: object, fallback: int) -> int:
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return fallback


def _safe_elapsed_secs(value: object) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(value))  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None


def _build_transcript_turn(
    raw_turn: dict[str, Any],
    fallback_turn_number: int,
) -> TranscriptTurn:
    metadata = raw_turn.get("metadata")
    parsed_metadata: dict[str, Any] = (
        dict(metadata) if isinstance(metadata, dict) else {}
    )
    return TranscriptTurn(
        turn_number=_safe_int(raw_turn.get("turn_number"), fallback_turn_number),
        turn_id=_first_string(raw_turn.get("turn_id")),
        speaker=str(raw_turn.get("speaker", "unknown")),
        text=str(raw_turn.get("text", "")),
        tone=raw_turn.get("tone"),
        timestamp=_first_string(raw_turn.get("timestamp")),
        elapsed_secs=_safe_elapsed_secs(parsed_metadata.get("elapsed_secs")),
        question_id=_first_string(
            raw_turn.get("question_id"),
            parsed_metadata.get("question_id"),
        ),
        section=_first_string(
            raw_turn.get("current_section"),
            raw_turn.get("section"),
            parsed_metadata.get("current_section"),
            parsed_metadata.get("section"),
        ),
        skill=_first_string(
            raw_turn.get("current_skill"),
            raw_turn.get("skill"),
            parsed_metadata.get("current_skill"),
            parsed_metadata.get("skill"),
        ),
        difficulty=_first_string(
            raw_turn.get("question_difficulty"),
            raw_turn.get("difficulty"),
            parsed_metadata.get("question_difficulty"),
            parsed_metadata.get("difficulty"),
        ),
        question_type=_first_string(
            raw_turn.get("question_type"),
            parsed_metadata.get("question_type"),
        ),
        response_type=_first_string(
            raw_turn.get("response_type"),
            parsed_metadata.get("response_type"),
        ),
    )
