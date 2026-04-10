```json
{
  "selected_paths": [],
  "selected_roles": [],
  "selection_reasons": [],
  "rejected_candidates": [
    {
      "role": "core_beliefs",
      "candidate_path": "/Users/yeonsu/autoagent/cowork-pilot/docs/design-docs/core-beliefs.md",
      "reason": "medium 규모 SaaS에서 제품 원칙 문서는 유용할 수 있지만 canonical 파일이 디스크에 존재하지 않는다."
    },
    {
      "role": "data_model",
      "candidate_path": "/Users/yeonsu/autoagent/cowork-pilot/docs/design-docs/data-model.md",
      "reason": "auth/session/workspace/resource 관계를 정리할 추가 문서로 적합하지만 canonical 파일이 디스크에 존재하지 않는다."
    },
    {
      "candidate_path": "/Users/yeonsu/autoagent/cowork-pilot/docs/project-conventions.md",
      "reason": "하네스가 읽는 문서 구조 규약이며 target greenfield SaaS의 제품 요구나 도메인 설계를 설명하지 않는다."
    },
    {
      "candidate_path": "/Users/yeonsu/autoagent/cowork-pilot/docs/brief-template.md",
      "reason": "빈 템플릿이라 실제 target product 정보가 없어서 추가 read source로 가치가 없다."
    },
    {
      "candidate_path": "/Users/yeonsu/autoagent/cowork-pilot/docs/planning/change-request.md",
      "reason": "brownfield change-request 템플릿이며 현재 run은 greenfield planning이라 입력 성격이 맞지 않는다."
    },
    {
      "candidate_path": "/Users/yeonsu/autoagent/cowork-pilot/docs/generated/planning-runs/greenfield-cli-planning/planning-references/gap-analysis-criteria.md",
      "reason": "brownfield gap 분석 기준 레퍼런스라 현재 greenfield adaptive docs selection에 필요한 제품 문서가 아니다."
    },
    {
      "candidate_path": "/Users/yeonsu/autoagent/cowork-pilot/docs/generated/planning-runs/greenfield-cli-planning/planning-references/observation-format.md",
      "reason": "brownfield 코드 관찰 레퍼런스라 현재 target product에 대한 추가 설계 입력을 제공하지 않는다."
    },
    {
      "candidate_path_glob": "/Users/yeonsu/autoagent/cowork-pilot/docs/specs/*.md",
      "reason": "존재하는 spec 문서들은 cowork-pilot 구현과 planning engine 자체를 설명하며, classification_scope_note 기준 target login SaaS의 기존 설계 문서로 해석하면 안 된다."
    },
    {
      "candidate_path_glob": "/Users/yeonsu/autoagent/cowork-pilot/docs/superpowers/specs/*.md",
      "reason": "planning 파이프라인 내부 설계 문서이며 target product domain input이 아니다."
    },
    {
      "candidate_path_glob": "/Users/yeonsu/autoagent/cowork-pilot/docs/superpowers/plans/*.md",
      "reason": "planning 파이프라인 구현 계획 문서이며 현재 stage가 선별해야 하는 추가 제품 문서가 아니다."
    }
  ]
}
```

추가 선택 없음. `core-docs-check.md`에서 조건부로 남아 있는 역할은 `core_beliefs`, `data_model`뿐이지만, 현재 저장소에는 두 역할의 canonical 파일이 실제로 존재하지 않는다.

존재하는 다른 문서들은 대부분 cowork-pilot 자체 설계/운영 문서이거나 brownfield 전용 레퍼런스다. `classification-report.md`의 `classification_scope_note`에 따라 이 문서들을 target greenfield SaaS의 추가 입력 문서로 채택하지 않았다.

<!-- ORCHESTRATOR:DONE -->
