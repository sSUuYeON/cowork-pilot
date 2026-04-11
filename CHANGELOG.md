# Changelog

All notable changes to Cowork Pilot are documented in this file.

## Unreleased

### Changed
- `domain/_overview.md` is now a conditional Phase 1 artifact. Whether it is generated is
  governed by a new `Domain Overview Decisions` table that every `analysis-report.md` must
  contain. Phase 2 and Phase 3 templates now read `_overview.md` only when the file exists
  on disk.
- The Phase 1 quality gate splits the former monolithic "missing files" check into three
  independent categories: `missing_shared` (hard fail), `missing_features` (hard fail), and
  `missing_overviews` (warning only). `shared.md` and `_overview.md` are no longer counted
  as "features" by the feature detector, and the `references/` directory is excluded as
  well.
- Phase 2/3 prompt rendering now computes an `available_extracts` structure from the
  filesystem. Templates gate every `_overview.md` reference behind a Jinja `{% if %}` block
  driven by this structure, so overview files that do not exist on disk are silently
  skipped rather than producing broken read instructions.

### Migration
- Existing projects that predate the decision table continue to run without hard failures.
  New Phase 1 runs populate the decision table automatically; re-running Phase 1 on a
  legacy project is the supported migration path.
- Pre-existing `_overview.md` files on disk remain valid and are picked up by the new
  filesystem scan. No manual cleanup is required.

### Rules
- `shared.md`: 2개 이상 도메인이 참조하는 전역 공통 정보. 항상 필수.
- `domain/_overview.md`: 한 도메인의 2개 이상 feature가 실제로 공유하는 맥락이 있을 때만 생성. 조건부(optional).
- `domain/{feature}.md`: 단일 feature 전용 정보. 항상 필수.
