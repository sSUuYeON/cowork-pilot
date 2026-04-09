from pathlib import Path

from cowork_pilot.planning.models import ProjectMode
from cowork_pilot.planning.request_normalization import normalize_planning_request


STRUCTURED_CHANGE_REQUEST = """# Brownfield Change Request

## 변경 목표

로그인 후 기본 이동 경로를 dashboard로 바꾼다

## 배경

현재 기본 진입점은 홈이다

## in scope

- dashboard redirect

## out of scope

- billing

## 영향받는 영역

auth, routing

## 제약사항

기존 권한 체계는 유지한다

## 승인 기준

로그인 후 dashboard로 이동한다
"""


def test_greenfield_request_is_snapshotted_and_normalized(tmp_path: Path) -> None:
    result = normalize_planning_request(
        run_dir=tmp_path,
        project_mode=ProjectMode.GREENFIELD,
        raw_request_text="관리자용 대시보드와 사용자용 페이지를 기획한다",
        raw_change_request_text="",
    )

    assert result.waiting_for_change_request is False
    assert result.request_snapshot_path == tmp_path / "inputs" / "request.md"
    assert result.normalized_request_path == tmp_path / "inputs" / "normalized-request.md"
    assert result.request_snapshot_path.read_text(encoding="utf-8") == (
        "관리자용 대시보드와 사용자용 페이지를 기획한다\n"
    )
    assert "관리자용 대시보드와 사용자용 페이지를 기획한다" in result.normalized_request_path.read_text(
        encoding="utf-8"
    )


def test_brownfield_without_change_request_writes_template_and_waits(tmp_path: Path) -> None:
    result = normalize_planning_request(
        run_dir=tmp_path,
        project_mode=ProjectMode.BROWNFIELD,
        raw_request_text="현재 멤버 관리 흐름을 재설계하고 싶다",
        raw_change_request_text="",
    )

    assert result.waiting_for_change_request is True
    assert result.change_request_path == tmp_path / "inputs" / "change-request.md"
    assert (tmp_path / "docs" / "planning" / "change-request.md").exists()
    assert result.change_request_path == tmp_path / "inputs" / "change-request.md"
    change_request_text = result.change_request_path.read_text(encoding="utf-8")
    assert "## 변경 목표" in change_request_text
    assert "## 배경" in change_request_text
    assert "## in scope" in change_request_text
    assert "## out of scope" in change_request_text
    assert "## 영향받는 영역" in change_request_text
    assert "## 제약사항" in change_request_text
    assert "## 승인 기준" in change_request_text
    assert "unknown" in change_request_text or "needs confirmation" in change_request_text


def test_brownfield_with_change_request_writes_structured_doc(tmp_path: Path) -> None:
    result = normalize_planning_request(
        run_dir=tmp_path,
        project_mode=ProjectMode.BROWNFIELD,
        raw_request_text="현재 멤버 관리 흐름을 재설계하고 싶다",
        raw_change_request_text="로그인 후 기본 이동 경로를 dashboard로 바꾼다",
    )

    assert result.waiting_for_change_request is False
    assert result.change_request_path == tmp_path / "inputs" / "change-request.md"
    change_request_text = result.change_request_path.read_text(encoding="utf-8")
    assert (tmp_path / "docs" / "planning" / "change-request.md").exists()
    assert "## 변경 목표" in change_request_text
    assert "## 배경" in change_request_text
    assert "## in scope" in change_request_text
    assert "## out of scope" in change_request_text
    assert "## 영향받는 영역" in change_request_text
    assert "## 제약사항" in change_request_text
    assert "## 승인 기준" in change_request_text
    assert "dashboard" in change_request_text
    assert "unknown" in change_request_text or "needs confirmation" in change_request_text
    assert "아직 작성하지 않음" not in change_request_text
    assert "(empty)" not in change_request_text


def test_brownfield_empty_change_request_uses_existing_canonical_file(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    canonical_change_request = project_dir / "docs" / "planning" / "change-request.md"
    canonical_change_request.parent.mkdir(parents=True)
    canonical_change_request.write_text(STRUCTURED_CHANGE_REQUEST, encoding="utf-8")

    result = normalize_planning_request(
        run_dir=tmp_path / "run",
        project_mode=ProjectMode.BROWNFIELD,
        raw_request_text="현재 멤버 관리 흐름을 재설계하고 싶다",
        raw_change_request_text="",
        project_dir=project_dir,
    )

    assert result.waiting_for_change_request is False
    assert result.change_request_summary == "로그인 후 기본 이동 경로를 dashboard로 바꾼다"
    assert result.change_request_path == tmp_path / "run" / "inputs" / "change-request.md"
    assert result.change_request_path.read_text(encoding="utf-8") == STRUCTURED_CHANGE_REQUEST
    assert result.normalized_request_path.read_text(encoding="utf-8") == (
        "# Normalized Planning Request\n\n"
        "- project_mode: brownfield\n\n"
        "## Request\n\n"
        "현재 멤버 관리 흐름을 재설계하고 싶다\n\n"
        "## Change Request\n\n"
        + STRUCTURED_CHANGE_REQUEST
    )
    assert "(missing)" not in result.normalized_request_path.read_text(encoding="utf-8")
    assert canonical_change_request.read_text(encoding="utf-8") == STRUCTURED_CHANGE_REQUEST


def test_brownfield_structured_change_request_is_preserved_and_summarized_from_body(
    tmp_path: Path,
) -> None:
    result = normalize_planning_request(
        run_dir=tmp_path,
        project_mode=ProjectMode.BROWNFIELD,
        raw_request_text="현재 멤버 관리 흐름을 재설계하고 싶다",
        raw_change_request_text=STRUCTURED_CHANGE_REQUEST,
    )

    assert result.waiting_for_change_request is False
    assert result.change_request_summary == "로그인 후 기본 이동 경로를 dashboard로 바꾼다"
    change_request_text = result.change_request_path.read_text(encoding="utf-8")
    assert change_request_text == STRUCTURED_CHANGE_REQUEST
    assert change_request_text.count("# Brownfield Change Request") == 1
