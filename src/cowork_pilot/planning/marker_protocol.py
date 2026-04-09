from __future__ import annotations

from dataclasses import dataclass

EVENT_START = "<COWORK_PILOT_EVENT>"
EVENT_END = "</COWORK_PILOT_EVENT>"


@dataclass(frozen=True)
class MarkerEnvelope:
    type: str
    stage: str
    event_id: str
    reason: str
    payload: dict[str, object]


_TYPE_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "INPUT_REQUIRED": ("question", "options", "recommended", "blocking"),
    "ASSUMPTION_LOG": ("assumption", "confidence", "impact"),
    "APPROVAL_REQUIRED": ("subject", "proposed_decision", "blocking"),
    "STAGE_COMPLETE": ("summary", "outputs"),
    "NEEDS_HUMAN": ("issue", "why_ai_stopped", "suggested_next_action"),
}

_ALLOWED_BUNDLE_SEQUENCES: tuple[tuple[str, ...], ...] = (
    ("ASSUMPTION_LOG", "STAGE_COMPLETE"),
    ("ASSUMPTION_LOG", "APPROVAL_REQUIRED"),
    ("ASSUMPTION_LOG", "NEEDS_HUMAN"),
)


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


def _validate_bundle_combination(types: tuple[str, ...]) -> bool:
    if len(types) <= 1:
        return True
    return types in _ALLOWED_BUNDLE_SEQUENCES


def extract_terminal_marker_bundle(message: str) -> tuple[MarkerEnvelope, ...]:
    stripped = _strip_fenced_code_blocks(message)
    blocks = _find_last_contiguous_bundle(stripped)
    if not blocks:
        return ()

    parsed: list[MarkerEnvelope] = []
    for block in blocks:
        try:
            fields = _parse_simple_yaml_subset(block)
        except ValueError:
            return ()

        if not all(required in fields for required in ("type", "stage", "event_id", "reason")):
            return ()

        marker_type = str(fields["type"])
        if not _validate_type_specific_fields(marker_type, fields):
            return ()

        payload = {
            key: value
            for key, value in fields.items()
            if key not in {"type", "stage", "event_id", "reason"}
        }
        parsed.append(
            MarkerEnvelope(
                type=marker_type,
                stage=str(fields["stage"]),
                event_id=str(fields["event_id"]),
                reason=str(fields["reason"]),
                payload=payload,
            )
        )

    bundle_types = tuple(marker.type for marker in parsed)
    if not _validate_bundle_combination(bundle_types):
        return ()

    return tuple(parsed)
