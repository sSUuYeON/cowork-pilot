```json
{
  "project_mode": "greenfield",
  "product_type": "webapp",
  "size_class": "medium",
  "required_doc_roles": [
    "agents",
    "spec_index",
    "design_guide",
    "architecture",
    "security",
    "spec_documents"
  ],
  "conditional_doc_roles": [
    "core_beliefs",
    "data_model"
  ],
  "resolved_existing_paths": [],
  "missing_roles": [
    "agents",
    "spec_index",
    "design_guide",
    "architecture",
    "security",
    "spec_documents"
  ],
  "conditional_missing_roles": [
    "core_beliefs",
    "data_model"
  ],
  "substitutions": []
}
```

분류 결과의 `classification_scope_note`와 `input_sources.not_present_for_target_project`를 기준으로, 현재 저장소의 `AGENTS.md`와 `docs/specs/*.md`는 cowork-pilot 자체 문서로 보고 타깃 greenfield SaaS의 existing core docs로는 해석하지 않았다.

따라서 `medium` 규모 `webapp`에 필요한 필수 core doc role 6개와 조건부 role 2개는 모두 타깃 프로젝트 기준으로 미존재 상태로 기록했다.
<!-- ORCHESTRATOR:DONE -->
