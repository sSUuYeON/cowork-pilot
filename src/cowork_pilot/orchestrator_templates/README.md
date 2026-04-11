## "출력 파일:" 섹션 규약

- 각 bullet은 반드시 `- <path>` 형태여야 한다.
- 경로 뒤에 공백, 설명, 괄호, 주석을 두지 않는다.
- 경로에는 공백이 포함될 수 없다.
- 파일/디렉토리 구분은 trailing slash로만 표현한다.
  - 파일: `- {{ project_dir }}/docs/generated/phase1/overview.md`
  - 디렉토리: `- {{ project_dir }}/docs/generated/domain-extracts/`
- 설명이 필요하면 bullet 위/아래의 일반 문장으로 둔다.
  (`domain-extracts/`에는 도메인별/기능별 파일이 들어간다.) 처럼.

이 규약을 어기면 docs_orchestrator._parse_expected_files()가 경로를 잘못
파싱해 phase가 무한 재실행된다.
