# Classification

```json
{
  "project_mode": "greenfield",
  "product_type": "webapp",
  "size_class": "medium",
  "core_user_flows": [
    "신규 사용자가 이메일과 비밀번호로 계정을 만들고 첫 로그인 세션을 시작한다.",
    "기존 사용자가 로그인한 뒤 아직 미정인 기본 이동 경로(예: 대시보드, 온보딩, 워크스페이스 선택)로 진입한다.",
    "로그인한 사용자가 보호된 메인 화면에서 SaaS의 핵심 업무 데이터나 리소스를 생성·조회·수정한다.",
    "사용자가 비밀번호를 재설정하거나 세션 만료 후 다시 인증해 서비스 접근을 복구한다.",
    "사용자가 프로필 또는 계정 설정을 변경하고 안전하게 로그아웃한다."
  ],
  "primary_entities": [
    "사용자 계정",
    "인증 자격 증명 또는 로그인 식별자",
    "세션",
    "계정 컨텍스트 또는 워크스페이스",
    "핵심 SaaS 도메인 리소스",
    "사용자 프로필 및 환경설정"
  ],
  "risks": [
    "로그인 후 기본 이동 경로가 미정이라 정보 구조, 온보딩, 첫 화면 요구사항이 바뀔 수 있다.",
    "SaaS의 핵심 도메인 기능이 정의되지 않아 핵심 리소스 모델과 우선순위가 아직 가변적이다.",
    "인증 범위가 이메일/비밀번호만인지, OAuth 또는 SSO까지 포함하는지 불확실하다.",
    "단일 사용자 구조인지 멀티테넌트 또는 워크스페이스 기반인지 미정이라 데이터 모델이 달라질 수 있다.",
    "보안 요구사항(이메일 인증, 비밀번호 정책, 세션 만료, 감사 로그) 수준이 아직 명시되지 않았다."
  ],
  "input_sources": {
    "provided": [
      "/Users/yeonsu/autoagent/cowork-pilot/docs/generated/planning-runs/greenfield-cli-planning/inputs/normalized-request.md",
      "/Users/yeonsu/autoagent/cowork-pilot/docs/generated/planning-runs/greenfield-cli-planning/inputs/request.md"
    ],
    "not_present_for_target_project": [
      "타깃 제품 README",
      "타깃 제품 설계 문서",
      "타깃 제품 기존 소스 코드"
    ]
  },
  "classification_scope_note": "현재 저장소에는 cowork-pilot 자체 소스 코드가 존재하지만, 분류 대상은 입력 문서가 설명하는 신규 로그인 SaaS 제품이다. 따라서 타깃 제품 관점에서 입력 소스를 판단했다.",
  "project_mode_rationale": "제공된 입력은 신규 SaaS를 계획해 달라는 요청뿐이며, 타깃 제품에 해당하는 기존 애플리케이션 소스나 README가 없다. 따라서 brownfield가 아니라 greenfield로 분류한다.",
  "product_type_candidates": [
    {
      "type": "webapp",
      "fit": "high",
      "reason": "로그인 후 화면 이동과 SaaS 사용 흐름이 언급되어 있어 사용자 대면형 웹 애플리케이션일 가능성이 가장 높다."
    },
    {
      "type": "api",
      "fit": "medium",
      "reason": "SaaS에 API가 포함될 수는 있지만, 현재 요청은 API 소비자보다 최종 사용자 로그인 경험에 초점이 있다."
    },
    {
      "type": "mobile",
      "fit": "low",
      "reason": "iOS/Android, 앱스토어, 푸시 알림 등 모바일 우선 신호가 없다."
    },
    {
      "type": "cli",
      "fit": "low",
      "reason": "CLI 제품이라면 로그인 이후의 화면 진입 경로보다 명령 흐름이 핵심이어야 한다."
    },
    {
      "type": "monorepo",
      "fit": "low",
      "reason": "복수 앱, 패키지, 서비스 분리 요구가 전혀 제시되지 않았다."
    }
  ],
  "product_type_selection_rationale": "webapp이 가장 타당하다. 현재 요청은 인증된 사용자가 로그인 후 어떤 화면으로 이동하는지에 관심이 있으며, 이는 사용자 인터페이스와 라우팅이 있는 SaaS 웹 제품의 전형적 요구다.",
  "size_class_rationale": {
    "estimated_feature_count": 7,
    "feature_groups_considered": [
      "회원가입",
      "로그인 및 로그아웃",
      "비밀번호 재설정",
      "세션 유지 및 보호된 접근 제어",
      "로그인 후 랜딩 또는 온보딩 쉘",
      "핵심 SaaS 작업 화면",
      "프로필 또는 계정 설정"
    ],
    "expected_file_count": "약 20~40개",
    "domain_complexity": "medium",
    "reason": "로그인 기능이 있는 SaaS는 인증만으로 끝나지 않고 보호된 앱 쉘과 최소 한 개의 핵심 업무 화면이 필요하므로 small(5개 이하)보다 크다. 다만 billing, admin 콘솔, 외부 통합, 복수 사용자 역할 등 대형 범위 신호는 없어 large까지는 아니다."
  }
}
```

입력 소스는 요청 원문과 정규화된 요청 두 개뿐이며, 타깃 제품에 대한 README·기존 구현·상세 스펙은 제공되지 않았다. 그래서 분류는 "새로 만드는 로그인 SaaS"라는 최소 전제에 기반한 보수적 추정이다.

`size_class=medium`은 감이 아니라 추정 기능군 7개, 예상 파일 수 20~40개, 인증과 보호된 화면 설계가 필요한 중간 수준 복잡도를 근거로 선택했다.

<!-- ORCHESTRATOR:DONE -->
