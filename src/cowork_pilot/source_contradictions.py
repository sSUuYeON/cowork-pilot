from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


CONTRADICTIONS_DIRNAME = "contradictions"
CONTRADICTION_RESOLUTIONS_DIRNAME = "contradiction-resolutions"

_SOURCE_TAG_RE = re.compile(
    r"<!--\s*SOURCE:\s*(?P<file>[^#]+)#(?P<section>[^>]+?)\s*-->",
)


@dataclass(frozen=True)
class ContradictionClaim:
    source_file: str
    source_section: str
    excerpt: str
    facet: str
    normalized_value: str


@dataclass(frozen=True)
class DetectedContradiction:
    contradiction_id: str
    domain: str
    feature: str
    facet: str
    severity: str
    question: str
    options: list[str]
    recommended: str | None
    claims: list[ContradictionClaim]


@dataclass
class ContradictionReport:
    blocking: list[DetectedContradiction] = field(default_factory=list)
    warnings: list[DetectedContradiction] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "blocking": [asdict(item) for item in self.blocking],
            "warnings": [asdict(item) for item in self.warnings],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ContradictionReport:
        def _load_item(raw: object) -> DetectedContradiction:
            item = dict(raw) if isinstance(raw, dict) else {}
            raw_claims = item.get("claims", [])
            claims = [
                ContradictionClaim(**dict(claim))
                for claim in raw_claims
                if isinstance(claim, dict)
            ]
            return DetectedContradiction(
                contradiction_id=str(item.get("contradiction_id", "")),
                domain=str(item.get("domain", "")),
                feature=str(item.get("feature", "")),
                facet=str(item.get("facet", "")),
                severity=str(item.get("severity", "blocking")),
                question=str(item.get("question", "")),
                options=[str(option) for option in item.get("options", [])],
                recommended=(
                    str(item.get("recommended"))
                    if item.get("recommended") is not None
                    else None
                ),
                claims=claims,
            )

        raw_blocking = data.get("blocking", [])
        raw_warnings = data.get("warnings", [])
        return cls(
            blocking=[
                _load_item(item)
                for item in raw_blocking
                if isinstance(item, dict)
            ],
            warnings=[
                _load_item(item)
                for item in raw_warnings
                if isinstance(item, dict)
            ],
        )


@dataclass(frozen=True)
class _FacetRule:
    facet: str
    patterns: tuple[tuple[str, str], ...]


_FACET_RULES: tuple[_FacetRule, ...] = (
    _FacetRule(
        facet="edit_window",
        patterns=(
            (r"잠금 전까지.+편집", "before_closed"),
            (r"draft.+1회 편집 허용", "draft_once"),
        ),
    ),
    _FacetRule(
        facet="editable_fields",
        patterns=(
            (r"질문/보기 텍스트 편집", "question_options_text"),
            (r"onlyAllowedFieldsChanged\(\['status', 'closedAt'\]\)", "status_closedAt_only"),
        ),
    ),
    _FacetRule(
        facet="delete_mode",
        patterns=(
            (r"hard delete|하드 삭제|즉시 hard delete", "hard_delete"),
            (r"soft delete|소프트 삭제|deleted 상태", "soft_delete"),
        ),
    ),
    _FacetRule(
        facet="permission_scope",
        patterns=(
            (r"hostUid.+권한", "host_uid_only"),
            (r"호스트만.+삭제 가능", "host_delete_only"),
            (r"status.+closedAt.+onlyAllowedFieldsChanged", "status_closedAt_only"),
        ),
    ),
)


def contradictions_dir(generated_dir: Path) -> Path:
    return generated_dir / CONTRADICTIONS_DIRNAME


def contradiction_index_path(generated_dir: Path) -> Path:
    return contradictions_dir(generated_dir) / "index.json"


def contradiction_item_json_path(generated_dir: Path, contradiction_id: str) -> Path:
    return contradictions_dir(generated_dir) / f"{contradiction_id}.json"


def contradiction_item_md_path(generated_dir: Path, contradiction_id: str) -> Path:
    return contradictions_dir(generated_dir) / f"{contradiction_id}.md"


def contradiction_resolution_path(generated_dir: Path, contradiction_id: str) -> Path:
    return generated_dir / CONTRADICTION_RESOLUTIONS_DIRNAME / f"{contradiction_id}.md"


def _feature_extract_files(extracts_root: Path) -> list[tuple[str, str, Path]]:
    items: list[tuple[str, str, Path]] = []
    if not extracts_root.exists():
        return items
    for domain_dir in sorted(path for path in extracts_root.iterdir() if path.is_dir()):
        for feature_path in sorted(domain_dir.glob("*.md")):
            if feature_path.name == "_overview.md":
                continue
            items.append((domain_dir.name, feature_path.stem, feature_path))
    return items


def _match_claims(path: Path, rule: _FacetRule) -> list[ContradictionClaim]:
    claims: list[ContradictionClaim] = []
    current_source_file = path.name
    current_source_section = ""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return claims

    for line in lines:
        tag_match = _SOURCE_TAG_RE.search(line)
        if tag_match:
            current_source_file = tag_match.group("file").strip()
            current_source_section = tag_match.group("section").strip()
            continue

        stripped = line.strip()
        if not stripped:
            continue

        for pattern, normalized_value in rule.patterns:
            if re.search(pattern, stripped):
                claims.append(
                    ContradictionClaim(
                        source_file=current_source_file,
                        source_section=current_source_section,
                        excerpt=stripped,
                        facet=rule.facet,
                        normalized_value=normalized_value,
                    )
                )
                break

    return claims


def _question_contract(
    *,
    domain: str,
    feature: str,
    facet: str,
) -> tuple[str, list[str], str | None]:
    label = f"`{domain}/{feature}`"
    if facet == "edit_window":
        options = [
            f"오타 수정형 (Recommended): {label}은 공유 전 `draft` 상태에서만 질문/보기 문구 수정을 허용하고, 공유 후(`open`)에는 수정하지 않는다",
            f"운영 조정형: {label}은 `closed` 전까지 질문/보기 문구 수정을 허용해 발표 중 운영 변경도 지원한다",
            f"혼합형: {label}은 기본은 공유 전 수정이지만, `open` 상태에서도 제한적으로 문구 수정 허용 여부를 명시한다",
        ]
        return (
            f"{label}의 수정 허용 시점을 어떻게 확정할까요?",
            options,
            options[0],
        )
    if facet == "editable_fields":
        options = [
            f"텍스트 한정형 (Recommended): {label}은 질문/보기 텍스트만 수정 가능하고, 상태 전이(`status`, `closedAt`)는 별도 액션으로 유지한다",
            f"혼합 수정형: {label}은 질문/보기 텍스트와 일부 운영 필드도 같은 편집 흐름에서 다룬다",
            f"직접 정의: {label}의 수정 가능 필드를 직접 적어 준다",
        ]
        return (
            f"{label}의 수정 가능 필드를 무엇으로 확정할까요?",
            options,
            options[0],
        )
    if facet == "delete_mode":
        options = [
            f"하드 삭제형 (Recommended): {label}은 문서를 즉시 삭제하고 기존 링크는 곧바로 무효화한다",
            f"소프트 삭제형: {label}은 `deleted` 상태를 두고 데이터는 남긴 채 접근만 차단한다",
            f"직접 정의: {label}의 삭제 방식을 직접 적어 준다",
        ]
        return (
            f"{label}의 삭제 방식을 어떻게 확정할까요?",
            options,
            options[0],
        )
    if facet == "permission_scope":
        options = [
            f"보수적 권한형 (Recommended): {label}은 `hostUid` 소유자만 허용하고, 수정/삭제 가능한 필드는 액션별로 명시 분리한다",
            f"통합 권한형: {label}은 호스트 소유자에게 넓은 update 권한을 주고 UI에서 제약한다",
            f"직접 정의: {label}의 권한 범위를 직접 적어 준다",
        ]
        return (
            f"{label}의 권한 범위를 어떻게 확정할까요?",
            options,
            options[0],
        )

    options = [
        f"보수형 (Recommended): {label}은 더 좁고 안전한 해석으로 확정한다",
        f"확장형: {label}은 더 넓은 기능 해석으로 확정한다",
        f"직접 정의: {label}의 해석을 직접 적어 준다",
    ]
    return (
        f"{label}의 상충하는 요구사항을 어떤 해석으로 확정할까요?",
        options,
        options[0],
    )


def detect_source_contradictions(generated_dir: Path) -> ContradictionReport:
    """Detect source contradictions from generated extracts.

    v1 intentionally uses a narrow facet-rule table. The implementation is
    replaceable later without changing the public report contract.
    """
    extracts_root = generated_dir / "domain-extracts"
    shared_path = extracts_root / "shared.md"
    report = ContradictionReport()

    for domain, feature, feature_path in _feature_extract_files(extracts_root):
        candidate_paths = [feature_path]
        if shared_path.exists():
            candidate_paths.insert(0, shared_path)

        for rule in _FACET_RULES:
            claims: list[ContradictionClaim] = []
            for path in candidate_paths:
                claims.extend(_match_claims(path, rule))

            distinct_values = sorted({claim.normalized_value for claim in claims})
            if len(distinct_values) < 2:
                continue

            question, options, recommended = _question_contract(
                domain=domain,
                feature=feature,
                facet=rule.facet,
            )
            report.blocking.append(
                DetectedContradiction(
                    contradiction_id=f"{domain}--{feature}--{rule.facet}",
                    domain=domain,
                    feature=feature,
                    facet=rule.facet,
                    severity="blocking",
                    question=question,
                    options=options,
                    recommended=recommended,
                    claims=claims,
                )
            )

    return report


def _render_contradiction_markdown(item: DetectedContradiction) -> str:
    lines = [
        f"# Source Contradiction: `{item.domain}/{item.feature}` `{item.facet}`",
        "",
        f"- contradiction_id: `{item.contradiction_id}`",
        f"- severity: `{item.severity}`",
        "",
        "## Resolution Question",
        item.question,
        "",
        "## Options",
    ]
    for index, option in enumerate(item.options, start=1):
        suffix = " (recommended)" if item.recommended == option else ""
        lines.append(f"{index}. {option}{suffix}")
    lines.extend(
        [
            "",
            "## Conflicting Claims",
        ]
    )
    for claim in item.claims:
        lines.append(
            f"- `{claim.source_file}#{claim.source_section}`: "
            f"{claim.excerpt} (`{claim.normalized_value}`)"
        )
    lines.append("")
    lines.append("<!-- ORCHESTRATOR:DONE -->")
    return "\n".join(lines)


def write_contradiction_report(generated_dir: Path, report: ContradictionReport) -> None:
    root = contradictions_dir(generated_dir)
    root.mkdir(parents=True, exist_ok=True)

    index_path = contradiction_index_path(generated_dir)
    index_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for item in report.blocking + report.warnings:
        contradiction_item_json_path(generated_dir, item.contradiction_id).write_text(
            json.dumps(asdict(item), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        contradiction_item_md_path(generated_dir, item.contradiction_id).write_text(
            _render_contradiction_markdown(item),
            encoding="utf-8",
        )


def load_contradiction_report(generated_dir: Path) -> ContradictionReport:
    index_path = contradiction_index_path(generated_dir)
    if not index_path.exists():
        return ContradictionReport()
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ContradictionReport()
    if not isinstance(data, dict):
        return ContradictionReport()
    return ContradictionReport.from_dict(data)
