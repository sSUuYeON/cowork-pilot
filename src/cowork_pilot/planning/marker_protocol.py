from __future__ import annotations

import logging
from dataclasses import dataclass

EVENT_START = "<COWORK_PILOT_EVENT>"
EVENT_END = "</COWORK_PILOT_EVENT>"
_BLOCK_PREVIEW_CHARS = 240
_ASSUMPTION_ENUM_VALUES = {"low", "medium", "high"}
_HUMAN_LOOP_MARKER_TYPES = {"INPUT_REQUIRED", "APPROVAL_REQUIRED", "NEEDS_HUMAN"}
_REPEATABLE_BUNDLE_PREFIX_MARKER_TYPES = {"ASSUMPTION_LOG"}
_BUNDLE_TERMINAL_MARKER_TYPES = {"STAGE_COMPLETE", "APPROVAL_REQUIRED", "NEEDS_HUMAN"}
_WAITING_BUNDLE_ALLOWED_MARKER_TYPES = {
    "ASSUMPTION_LOG",
    "INPUT_REQUIRED",
    "APPROVAL_REQUIRED",
    "NEEDS_HUMAN",
}

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarkerEnvelope:
    type: str
    stage: str
    event_id: str
    reason: str
    payload: dict[str, object]


@dataclass(frozen=True)
class _InvalidMarkerBlock:
    declared_type: str
    reason: str
    raw_block: str


_TYPE_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "INPUT_REQUIRED": ("question", "options", "recommended", "blocking"),
    "ASSUMPTION_LOG": ("assumption", "confidence", "impact"),
    "APPROVAL_REQUIRED": ("subject", "proposed_decision", "blocking"),
    "STAGE_COMPLETE": ("summary", "outputs"),
    "NEEDS_HUMAN": ("issue", "why_ai_stopped", "suggested_next_action"),
}

def _strip_fenced_code_blocks(message: str) -> str:
    lines: list[str] = []
    in_fence = False

    for line in message.splitlines():
        if line.strip().startswith("```"):
            if not in_fence:
                lines.append("__COWORK_PILOT_FENCED_BLOCK__")
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append(line)

    return "\n".join(lines)


def _extract_blocks(message: str) -> list[tuple[int, int, str]]:
    blocks: list[tuple[int, int, str]] = []
    cursor = 0

    while True:
        start = message.find(EVENT_START, cursor)
        if start == -1:
            return blocks
        end = message.find(EVENT_END, start)
        if end == -1:
            return []
        end += len(EVENT_END)
        blocks.append((start, end, message[start:end]))
        cursor = end


def _find_last_contiguous_bundle(message: str) -> list[str]:
    blocks = _extract_blocks(message)
    if not blocks:
        return []

    tail_start, tail_end, tail_block = blocks[-1]
    if message[tail_end:].strip():
        return []

    bundle: list[str] = [tail_block]
    bundle_start = tail_start

    for start, end, block in reversed(blocks[:-1]):
        if message[end:bundle_start].strip():
            break
        bundle.insert(0, block)
        bundle_start = start

    return bundle


def _parse_simple_yaml_subset(block: str) -> dict[str, object]:
    body = block.removeprefix(EVENT_START).removesuffix(EVENT_END).strip()
    data: dict[str, object] = {}
    current_list_key = ""

    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if line.startswith("  - "):
            if not current_list_key:
                raise ValueError("list item without a current key")
            current_value = data.get(current_list_key)
            if not isinstance(current_value, list):
                raise ValueError("current key is not a list")
            current_value.append(_parse_scalar(line[4:]))
            continue

        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError(f"malformed line (no colon): {line!r}")

        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError("empty key")

        if value == "":
            current_list_key = key
            data[key] = []
            continue

        current_list_key = ""
        data[key] = _parse_scalar(value)

    return data


def _parse_scalar(value: str) -> object:
    if value == "true":
        return True
    if value == "false":
        return False
    return value


def _validate_type_specific_fields(marker_type: str, fields: dict[str, object]) -> bool:
    required = _TYPE_REQUIRED_FIELDS.get(marker_type)
    if required is None:
        return False
    return all(field in fields for field in required)


def _validate_type_specific_values(marker_type: str, fields: dict[str, object]) -> bool:
    if marker_type == "ASSUMPTION_LOG":
        return (
            fields.get("confidence") in _ASSUMPTION_ENUM_VALUES
            and fields.get("impact") in _ASSUMPTION_ENUM_VALUES
        )
    return True


def _validate_bundle_combination(types: tuple[str, ...]) -> bool:
    if not types:
        return False
    if len(types) == 1:
        return True

    # Waiting bundles are allowed to end in one or more human-loop markers.
    # This keeps the runtime tolerant when the model emits multiple blocking
    # questions even though the preferred contract is "one blocker per turn".
    if "STAGE_COMPLETE" not in types and any(
        marker_type in _HUMAN_LOOP_MARKER_TYPES for marker_type in types
    ):
        return all(
            marker_type in _WAITING_BUNDLE_ALLOWED_MARKER_TYPES
            for marker_type in types
        )

    terminal_type = types[-1]
    if terminal_type not in _BUNDLE_TERMINAL_MARKER_TYPES:
        return False

    return all(
        marker_type in _REPEATABLE_BUNDLE_PREFIX_MARKER_TYPES
        for marker_type in types[:-1]
    )


def _extract_declared_type(block: str) -> str:
    """Best-effort marker type lookup.

    If the block is too malformed to expose a `type:` line, return an empty
    string. Unknown type means salvage is not allowed.
    """
    body = block.removeprefix(EVENT_START).removesuffix(EVENT_END).strip()
    for raw_line in body.splitlines():
        key, separator, value = raw_line.partition(":")
        if separator and key.strip() == "type":
            return value.strip()
    return ""


def _truncate_block_preview(block: str, limit: int = _BLOCK_PREVIEW_CHARS) -> str:
    compact = " ".join(block.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _parse_marker_block(block: str) -> MarkerEnvelope:
    fields = _parse_simple_yaml_subset(block)
    if not all(required in fields for required in ("type", "stage", "event_id", "reason")):
        raise ValueError("missing required common fields")

    marker_type = str(fields["type"])
    if not _validate_type_specific_fields(marker_type, fields):
        raise ValueError(f"missing required fields for {marker_type}")
    if not _validate_type_specific_values(marker_type, fields):
        raise ValueError(f"invalid field values for {marker_type}")

    payload = {
        key: value
        for key, value in fields.items()
        if key not in {"type", "stage", "event_id", "reason"}
    }
    return MarkerEnvelope(
        type=marker_type,
        stage=str(fields["stage"]),
        event_id=str(fields["event_id"]),
        reason=str(fields["reason"]),
        payload=payload,
    )


def _parse_bundle_blocks(blocks: list[str]) -> tuple[list[MarkerEnvelope], list[_InvalidMarkerBlock]]:
    parsed: list[MarkerEnvelope] = []
    invalid: list[_InvalidMarkerBlock] = []
    for block in blocks:
        try:
            parsed.append(_parse_marker_block(block))
        except ValueError as exc:
            invalid.append(
                _InvalidMarkerBlock(
                    declared_type=_extract_declared_type(block),
                    reason=str(exc),
                    raw_block=block,
                )
            )
    return (parsed, invalid)


def _can_salvage_stage_complete(
    parsed: list[MarkerEnvelope],
    invalid_blocks: list[_InvalidMarkerBlock],
) -> bool:
    if not invalid_blocks:
        return False

    stage_complete_count = sum(marker.type == "STAGE_COMPLETE" for marker in parsed)
    if stage_complete_count != 1:
        return False

    for marker in parsed:
        if marker.type == "STAGE_COMPLETE":
            continue
        if marker.type in _HUMAN_LOOP_MARKER_TYPES:
            return False

    return all(block.declared_type == "ASSUMPTION_LOG" for block in invalid_blocks)


def _log_stage_complete_salvage(invalid_blocks: list[_InvalidMarkerBlock]) -> None:
    previews = [
        (
            f"type={block.declared_type or 'unknown'} "
            f"reason={block.reason} preview={_truncate_block_preview(block.raw_block)}"
        )
        for block in invalid_blocks
    ]
    logger.warning(
        "marker bundle salvage: kept STAGE_COMPLETE after dropping invalid ASSUMPTION_LOG blocks: %s",
        previews,
    )


def _extract_terminal_marker_bundle(
    message: str,
    *,
    allow_stage_complete_salvage: bool = False,
) -> tuple[MarkerEnvelope, ...]:
    stripped = _strip_fenced_code_blocks(message)
    blocks = _find_last_contiguous_bundle(stripped)
    if not blocks:
        return ()

    parsed, invalid_blocks = _parse_bundle_blocks(blocks)
    if invalid_blocks:
        if not allow_stage_complete_salvage:
            return ()
        if not _can_salvage_stage_complete(parsed, invalid_blocks):
            return ()
        _log_stage_complete_salvage(invalid_blocks)
        return tuple(parsed)

    bundle_types = tuple(marker.type for marker in parsed)
    if not _validate_bundle_combination(bundle_types):
        return ()

    return tuple(parsed)


def extract_terminal_marker_bundle(
    message: str,
    *,
    allow_stage_complete_salvage: bool = False,
) -> tuple[MarkerEnvelope, ...]:
    """Parse the final contiguous marker bundle at the end of a message.

    When `allow_stage_complete_salvage=True`, salvage is allowed only when the
    sole invalid blocks are ASSUMPTION_LOG entries and a valid STAGE_COMPLETE
    marker remains in the parsed bundle.
    """
    return _extract_terminal_marker_bundle(
        message,
        allow_stage_complete_salvage=allow_stage_complete_salvage,
    )
