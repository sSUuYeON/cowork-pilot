# SUBSCRIBE v2 + cowork-pilot Integration — Design Spec

**Status:** Proposed
**Date:** 2026-03-28
**Author:** Skudy + Claude

## 1. Overview

SUBSCRIBE는 꿈담의 월 구독형 외주 개발 서비스 플랫폼이다. 고객사(Organization)가 요구사항을 제출하면, 꿈담 팀이 개발 기획서를 작성하고 고객 승인을 받아 개발을 진행한다.

이 설계는 기존 SUBSCRIBE v2 아키텍처에 cowork-pilot을 연동하여, 기획서 승인 후 개발 실행을 자동화하는 통합 플랫폼을 정의한다.

### 1.1. 핵심 변경 (v2 원본 대비)

- 기획서 작성 주체: SUBSCRIBE 웹 → Cowork에서 작성, SUBSCRIBE에 업로드
- Task 관리: Gemini 자동 생성 → cowork-pilot exec-plan의 Chunk와 1:1 동기화
- 변경 요청 처리: developer 수동 → cowork-pilot이 자동 분석/반영
- DB: Firestore → Supabase (PostgreSQL)
- Auth: Firebase Auth 유지 (Google OAuth)

### 1.2. 시스템 역할 분담

| 시스템 | 역할 |
|--------|------|
| SUBSCRIBE (웹) | 고객 커뮤니케이션, 요청 관리, 기획서 열람/승인, 진행 상황 대시보드, 리포트, 채팅 |
| cowork-pilot (로컬) | 기획서 작성(Cowork), docs/ 구조 생성, exec-plan 실행, 변경 요청 분석/반영 |

### 1.3. 프로젝트 페이징

이 문서는 Phase 1(SUBSCRIBE v2 코어 + Sync API 설계)을 다룬다.

| Phase | 범위 |
|-------|------|
| Phase 1 | SUBSCRIBE v2 코어 (본 문서) |
| Phase 2 | cowork-pilot 브릿지 + 상태 동기화 |
| Phase 3 | 개발자 협업 도구 (칸반, 실행 모니터링) |
| Phase 4 | 변경 요청 자동화 (AI 영향 분석) |

## 2. Tech Stack

| 영역 | 기술 |
|------|------|
| Framework | Next.js (App Router) |
| Auth | Firebase Authentication (Google OAuth) |
| Database | Supabase (PostgreSQL) |
| Realtime | Supabase Realtime |
| Storage | Supabase Storage (첨부파일) |
| AI | Google Gemini (리포트 생성) |
| GitHub | Octokit (커밋 기반 리포트) |
| Email | Nodemailer + Gmail SMTP 또는 Resend |
| Deployment | Vercel |

인증 흐름:
- 웹 사용자: Firebase Auth 로그인 → ID Token → Server Action → Supabase
- cowork-pilot: API Key → Sync API → Supabase (admin client)

## 3. User Roles & Permissions

v2 원본과 동일. 변경 없음.

### 3.1. 역할 정의

| 역할 | 스코프 | 설명 |
|------|--------|------|
| `admin` | 글로벌 | 꿈담 관리자. 조직/프로젝트 관리, 리포트 생성/발행, 전체 권한 |
| `developer` | 프로젝트 단위 | 꿈담 개발자. 기획서 업로드, Task 모니터링, 요청 검토/승인 |
| `customer` | 조직 단위 | 클라이언트. 요구사항/변경 요청 제출, 기획서 승인, 리포트 열람 |

### 3.2. 권한 매트릭스

| 행위 | admin | developer | customer |
|------|-------|-----------|----------|
| 기획서 업로드 | O | O | X |
| 기획서 승인/거절 | X | X | O |
| Request 생성 | X | X | O |
| Request 승인/반려 | O | O | X |
| Task 열람 | O | O | O |
| Task 상태 변경 (수동) | O | O | X |
| 리포트 생성/수정/발행 | O | X | X |
| 리포트 열람 | O | O | O |
| 채팅 (일반) | O | O | O |
| 채팅 (내부 메모) | O | O | X (안 보임) |
| 조직/프로젝트 관리 | O | X | X |
| Sync API 호출 | — | — | — (API Key 인증) |

## 4. Data Model

### 4.1. Entity Relationship

```
Organization (고객사)
  └── Project (1:N)
        ├── Specification (기획서, 1:1 + 버전 관리)
        │     └── SpecificationVersion (1:N)
        ├── Task (exec-plan Chunk와 동기화, 1:N)
        ├── Request (고객 변경 요청, 1:N)
        ├── Message (채팅, 1:N)
        └── CopilotProject (cowork-pilot 연동 정보, 1:1)

User (사용자)
WeeklyReport (주간 리포트)
Notification (알림)
Inquiry (문의)
SyncApiKey (API Key)
```

### 4.2. PostgreSQL 테이블 정의

#### users

```sql
CREATE TABLE users (
  uid TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin', 'developer', 'customer')),
  organization_id UUID REFERENCES organizations(id),
  profile_image TEXT,
  phone_number TEXT,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### organizations

```sql
CREATE TABLE organizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  contact_email TEXT NOT NULL,
  contact_phone TEXT,
  business_number TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'cancelled')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### projects

```sql
CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organizations(id),
  name TEXT NOT NULL,
  description TEXT,
  github_repo_url TEXT,
  preview_url TEXT,
  assigned_developers TEXT[] NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived', 'maintenance')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### specifications

```sql
CREATE TABLE specifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL UNIQUE REFERENCES projects(id),
  content TEXT NOT NULL,
  current_version INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'pending_approval', 'approved')),
  source TEXT NOT NULL DEFAULT 'cowork' CHECK (source IN ('cowork', 'manual')),
  uploaded_at TIMESTAMPTZ,
  approved_at TIMESTAMPTZ,
  approved_by TEXT REFERENCES users(uid),
  created_by TEXT NOT NULL REFERENCES users(uid),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### specification_versions

```sql
CREATE TABLE specification_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  version INTEGER NOT NULL,
  content TEXT NOT NULL,
  change_summary TEXT NOT NULL,
  related_request_id UUID REFERENCES requests(id),
  created_by TEXT NOT NULL REFERENCES users(uid),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(project_id, version)
);
```

#### tasks

```sql
CREATE TABLE tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  specification_version_id UUID REFERENCES specification_versions(id),
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'in_progress', 'done')),
  assigned_to TEXT REFERENCES users(uid),
  priority TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high')),
  "order" INTEGER NOT NULL DEFAULT 0,
  planned_week TEXT,
  copilot_chunk_id TEXT,
  copilot_synced BOOLEAN NOT NULL DEFAULT false,
  copilot_last_sync_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### requests

```sql
CREATE TABLE requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  type TEXT NOT NULL CHECK (type IN ('initial', 'change_request')),
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  attachments JSONB NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted', 'under_review', 'approved', 'rejected')),
  rejection_reason TEXT,
  reviewed_by TEXT REFERENCES users(uid),
  reviewed_at TIMESTAMPTZ,
  copilot_synced BOOLEAN NOT NULL DEFAULT false,
  copilot_synced_at TIMESTAMPTZ,
  copilot_analysis TEXT,
  created_by TEXT NOT NULL REFERENCES users(uid),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### messages

```sql
CREATE TABLE messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  author_id TEXT NOT NULL REFERENCES users(uid),
  author_name TEXT NOT NULL,
  author_role TEXT NOT NULL CHECK (author_role IN ('admin', 'developer', 'customer')),
  content TEXT NOT NULL,
  is_internal BOOLEAN NOT NULL DEFAULT false,
  mentions JSONB NOT NULL DEFAULT '[]',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### weekly_reports

```sql
CREATE TABLE weekly_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id),
  project_id UUID NOT NULL REFERENCES projects(id),
  organization_name TEXT NOT NULL,
  project_name TEXT NOT NULL,
  year INTEGER NOT NULL,
  week_number INTEGER NOT NULL,
  week_start_date DATE NOT NULL,
  week_end_date DATE NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
  sections JSONB NOT NULL DEFAULT '{}',
  ai_generated_content TEXT,
  sent_at TIMESTAMPTZ,
  sent_to TEXT[],
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(project_id, year, week_number)
);
```

#### notifications

```sql
CREATE TABLE notifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES users(uid),
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  link TEXT NOT NULL,
  is_read BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### inquiries

```sql
CREATE TABLE inquiries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_name TEXT NOT NULL,
  email TEXT NOT NULL,
  description TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'received' CHECK (status IN ('received', 'consulting', 'contracted', 'rejected')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### copilot_projects

```sql
CREATE TABLE copilot_projects (
  project_id UUID PRIMARY KEY REFERENCES projects(id),
  local_path TEXT NOT NULL,
  last_sync_at TIMESTAMPTZ,
  sync_status TEXT NOT NULL DEFAULT 'idle' CHECK (sync_status IN ('idle', 'syncing', 'error')),
  sync_error_message TEXT,
  active_exec_plan TEXT,              -- 현재 실행 중인 exec-plan 파일명 (예: "01-core-setup.md")
  completed_chunks INTEGER NOT NULL DEFAULT 0,
  total_chunks INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### sync_api_keys

```sql
CREATE TABLE sync_api_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  api_key TEXT NOT NULL UNIQUE,
  is_active BOOLEAN NOT NULL DEFAULT true,
  last_used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 4.3. RLS 정책

```sql
-- projects: admin은 전체, developer는 assigned_developers에 포함, customer는 org_id 일치
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;

CREATE POLICY "admin_all_projects" ON projects
  FOR ALL USING (
    EXISTS (SELECT 1 FROM users WHERE uid = auth.uid() AND role = 'admin')
  );

CREATE POLICY "developer_assigned_projects" ON projects
  FOR SELECT USING (
    auth.uid() = ANY(assigned_developers)
  );

CREATE POLICY "customer_org_projects" ON projects
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM users
      WHERE uid = auth.uid()
        AND role = 'customer'
        AND organization_id = projects.org_id
    )
  );

-- messages: is_internal=true면 customer에게 안 보임
CREATE POLICY "hide_internal_from_customer" ON messages
  FOR SELECT USING (
    NOT is_internal
    OR EXISTS (SELECT 1 FROM users WHERE uid = auth.uid() AND role IN ('admin', 'developer'))
  );
```

## 5. Core Workflows

### 5.1. Specification Workflow (변경)

```
1. Cowork에서 기획서 작성 (Markdown)
2. cowork-pilot → Sync API POST /api/sync/specification → 업로드
   또는 developer가 웹에서 md파일 직접 업로드
3. status: "draft"
4. admin이 "pending_approval"로 변경 → customer에게 알림
5. customer가 열람 → 승인 또는 거절
   - 승인: status → "approved", specification_versions에 스냅샷 저장
   - 거절: status → "draft", 거절 사유 채팅에 남김
6. 승인 시 cowork-pilot에 알림 (다음 sync에서 감지)
```

기획서 거절 플로우, 버전 번호 규칙은 v2 원본과 동일하다.

### 5.2. Request Workflow (소폭 변경)

상태 흐름은 동일: `submitted → under_review → approved / rejected`

승인 이후 분기 변경:
- `type: "initial"` + 승인 → 기획서 작성 시작 (Cowork에서)
- `type: "change_request"` + 승인 → `copilot_synced: false` 설정
  → cowork-pilot이 다음 sync 시 `GET /api/sync/requests/pending`으로 가져감
  → 영향 분석 → docs/ 업데이트 → 새 exec-plan 생성

거절된 요청은 cowork-pilot에 전달되지 않는다 (`copilot_synced`는 승인된 요청에만 적용).

### 5.3. Task Workflow (대폭 변경)

기존 Gemini Task 자동 생성 제거. cowork-pilot의 exec-plan이 Task의 source of truth.

```
1. 기획서 승인 → cowork-pilot이 docs-restructurer로 docs/ + exec-plan 생성
2. Sync API POST /api/sync/tasks/bulk → exec-plan Chunk를 Task로 일괄 생성
   - specification_version_id는 bulk 생성 시점의 current_version에 해당하는 버전
3. cowork-pilot harness 실행:
   - Chunk 시작 → PATCH /api/sync/tasks/{id}/status (in_progress)
   - Chunk 완료 → PATCH /api/sync/tasks/{id}/status (done)
4. developer는 SUBSCRIBE 웹에서 진행 상황 모니터링
5. copilot_projects 테이블로 전체 진행률 추적
```

**상태 전이 규칙:** `todo → in_progress → done`. 역방향(`done → in_progress`)은 허용하되 `done → todo`는 불가.

**수동 편집:** developer가 웹에서 Task를 수동 수정할 수 있지만, cowork-pilot 다음 sync 시 copilot_synced 필드가 있는 Task는 exec-plan 기준으로 상태가 덮어씌워진다. 수동 편집은 copilot_synced=false인 Task(수동 생성)에만 권장.

**cowork-pilot 크래시 시:** Task가 in_progress 상태로 남는다. copilot_projects.sync_status가 'error'로 전환되고 sync_error_message에 에러 내용 기록. developer에게 copilot_escalation 알림 발송.

### 5.4. Report Workflow (소폭 확장)

v2 원본과 동일한 구조. 추가 데이터 소스:
- copilot_projects의 진행률 (completed_chunks / total_chunks)
- cowork-pilot 실행 로그

### 5.5. Chat Workflow — 변경 없음

## 6. Sync API

cowork-pilot ↔ SUBSCRIBE 간 통신을 위한 REST API.

### 6.1. 인증

모든 Sync API는 `Authorization: Bearer <api_key>` 헤더로 인증.
프로젝트별 API Key를 `sync_api_keys` 테이블에서 관리.

### 6.2. 엔드포인트 — cowork-pilot → SUBSCRIBE (Push)

| Method | Path | 용도 |
|--------|------|------|
| POST | `/api/sync/specification` | 기획서(md) 업로드 |
| PATCH | `/api/sync/tasks/{taskId}/status` | Task 상태 업데이트 |
| POST | `/api/sync/tasks/bulk` | exec-plan 기반 Task 일괄 생성 |
| POST | `/api/sync/tasks/batch-status` | 여러 Task 상태 일괄 업데이트 |
| PATCH | `/api/sync/copilot-project/{projectId}` | 실행 상태 업데이트 |
| PATCH | `/api/sync/requests/{requestId}/synced` | 요청 동기화 완료 마킹 |
| POST | `/api/sync/requests/{requestId}/analysis` | 변경 요청 영향 분석 결과 업로드 |

### 6.3. 엔드포인트 — SUBSCRIBE → cowork-pilot (Pull)

| Method | Path | 용도 |
|--------|------|------|
| GET | `/api/sync/requests/pending` | 승인됐지만 미동기화 요청 목록 |
| GET | `/api/sync/specification/{projectId}/latest` | 최신 승인 기획서 |
| GET | `/api/sync/specification/{projectId}/status` | 기획서 승인 상태 확인 (폴링용) |
| GET | `/api/sync/project/{projectId}/config` | 프로젝트 설정 |
| GET | `/api/sync/tasks?copilot_chunk_id={chunkId}` | Chunk ID로 Task 조회 |

### 6.4. 주요 요청/응답 스키마

**POST /api/sync/specification**
```json
{
  "project_id": "uuid",
  "content": "# 기획서 마크다운 본문...",
  "source": "cowork"
}
// → 201: { "id": "uuid", "status": "draft" }
```

**POST /api/sync/tasks/bulk**
```json
{
  "project_id": "uuid",
  "specification_version_id": "uuid",
  "tasks": [
    {
      "title": "Chunk 1: 데이터 모델",
      "description": "User, Project 테이블 생성...",
      "copilot_chunk_id": "chunk-1",
      "priority": "high",
      "order": 1
    }
  ]
}
// → 201: { "created": 5, "task_ids": ["uuid", ...] }
```

**PATCH /api/sync/tasks/{taskId}/status**
```json
{ "status": "in_progress" }
// → 200: { "id": "uuid", "status": "in_progress" }
```
상태 전이 규칙: `todo → in_progress → done`. 역방향 전이(`done → in_progress`)는 허용하되 `done → todo`는 불가.

**POST /api/sync/tasks/batch-status**
```json
{
  "updates": [
    { "task_id": "uuid", "status": "done" },
    { "task_id": "uuid", "status": "in_progress" }
  ]
}
// → 200: { "updated": 2 }
```

**PATCH /api/sync/copilot-project/{projectId}**
```json
{
  "sync_status": "syncing",
  "active_exec_plan": "01-core-setup.md",
  "completed_chunks": 3,
  "total_chunks": 8
}
// → 200: { "project_id": "uuid", "sync_status": "syncing" }
```

**PATCH /api/sync/requests/{requestId}/synced**
```json
{}
// → 200: { "id": "uuid", "copilot_synced": true, "copilot_synced_at": "..." }
```

**GET /api/sync/requests/pending**
```json
// → 200:
{
  "requests": [
    {
      "id": "uuid",
      "type": "change_request",
      "title": "결제 기능 추가",
      "description": "...",
      "attachments": [...],
      "approved_at": "2026-03-28T..."
    }
  ]
}
```

### 6.5. 로컬 저장 규약

cowork-pilot이 가져온 요청의 로컬 저장 구조:

```
project-root/
├── docs/                    # 기존 cowork-pilot 구조
├── requests/                # SUBSCRIBE에서 가져온 고객 요청
│   ├── pending/             # 아직 처리 안 된 요청
│   │   ├── REQ-001-initial-요구사항.md
│   │   └── REQ-002-변경요청-결제기능추가.md
│   ├── processed/           # 처리 완료 (docs/에 반영됨)
│   └── rejected/            # SUBSCRIBE에서 거절된 요청
```

## 7. Authentication & Authorization

### 7.1. 인증 흐름

- 클라이언트 사이드: Firebase Auth (Google OAuth 로그인/로그아웃)
- 서버 사이드: cookies()에서 Firebase session token → Admin SDK verifyIdToken 검증
- Sync API: Authorization 헤더의 API Key → sync_api_keys 테이블 조회

### 7.2. 권한 미들웨어

v2 원본과 동일:

```
withAuth(action)                           — 인증만 확인
withRole(action, ["admin", "developer"])   — 인증 + 역할 확인
withProjectAccess(action, projectId)       — 인증 + 프로젝트 접근 권한
withApiKey(handler)                        — Sync API용 API Key 검증 (신규)
```

### 7.3. withProjectAccess 판단 로직

- admin → 항상 접근 가능
- developer → projects.assigned_developers에 uid 포함 시
- customer → users.organization_id = projects.org_id 시

## 8. Code Architecture

### 8.1. 디렉토리 구조

```
app/
├── (public)/              # 공개 페이지
│   ├── page.tsx           # 랜딩
│   ├── login/
│   ├── register/
│   └── reports/[id]/      # 리포트 공개 링크
├── (dashboard)/           # customer 대시보드
│   ├── dashboard/
│   │   ├── projects/[id]/
│   │   │   ├── specification/
│   │   │   ├── chat/
│   │   │   ├── requests/
│   │   │   └── reports/
│   │   └── notifications/
├── (admin)/               # admin/developer
│   ├── admin/
│   │   ├── organizations/
│   │   ├── projects/[id]/
│   │   │   ├── specification/
│   │   │   ├── tasks/
│   │   │   ├── chat/
│   │   │   ├── requests/
│   │   │   └── reports/
│   │   └── settings/
├── api/sync/              # Sync API
│   ├── specification/route.ts
│   ├── tasks/route.ts
│   ├── requests/route.ts
│   └── copilot-project/route.ts
└── actions/               # Server Actions

lib/
├── services/
│   ├── specification-service.ts
│   ├── task-service.ts
│   ├── request-service.ts
│   ├── report-service.ts
│   ├── chat-service.ts
│   ├── notification-service.ts
│   └── sync-service.ts        # cowork-pilot 동기화 로직
├── repositories/              # Supabase CRUD
├── auth/
│   ├── firebase-admin.ts      # Firebase Admin SDK (토큰 검증만)
│   ├── with-auth.ts
│   └── with-api-key.ts        # Sync API용
├── supabase/
│   ├── client.ts
│   ├── server.ts
│   └── admin.ts
└── types/
    └── database.ts            # supabase gen types 자동 생성
```

### 8.2. 레이어 원칙

- Server Action: 인증 + 서비스 호출만
- Service: 비즈니스 로직만
- Repository: Supabase CRUD만
- Sync API: API Key 인증 + sync-service 호출

## 9. Route Structure

v2 원본과 동일. 변경 없음.

### 9.1. 공개

```
/                           ← 랜딩
/login
/register
/forgot-password
/reports/{id}               ← 리포트 공개 링크
/preview/{token}            ← 샘플 프리뷰
```

### 9.2. Customer 대시보드

```
/dashboard
/dashboard/projects/{id}
/dashboard/projects/{id}/specification
/dashboard/projects/{id}/chat
/dashboard/projects/{id}/requests
/dashboard/projects/{id}/requests/new
/dashboard/projects/{id}/reports
/dashboard/notifications
/dashboard/profile
```

### 9.3. Admin/Developer

```
/admin
/admin/organizations
/admin/organizations/{id}
/admin/projects/{id}
/admin/projects/{id}/specification    ← 업로드 + 열람 (작성은 Cowork)
/admin/projects/{id}/tasks            ← exec-plan 동기화 뷰
/admin/projects/{id}/chat
/admin/projects/{id}/requests
/admin/projects/{id}/reports
/admin/settings
```

## 10. Full Data Flow Summary

### 10.1. 프로젝트 시작

```
1. admin이 Organization 생성 + customer 초대
2. admin이 Project 생성 + API Key 발급
3. customer가 초기 요구사항(Request type: "initial") 제출
4. admin/developer가 검토 → 승인
5. Cowork에서 기획서 작성 → Sync API로 SUBSCRIBE에 업로드
6. customer가 기획서 승인
7. cowork-pilot이 docs-restructurer로 docs/ + exec-plan 생성
8. Sync API로 Task 일괄 생성 → harness 모드로 자동 실행
```

### 10.2. 개발 진행 중

```
- cowork-pilot harness가 Chunk별 자동 실행
- Chunk 시작/완료 시 Sync API로 Task 상태 업데이트
- 채팅에서 소통 (내부 메모 가능)
- 매주 자동 리포트 생성 → admin 검토 → 발행 → 이메일
```

### 10.3. 변경 요청 발생

```
1. customer가 변경 요청(change_request) 제출
2. admin/developer가 검토 → 승인 or 반려
   - 반려: rejectionReason 포함, 끝. 로컬에 전달 안 됨.
   - 승인: copilot_synced = false
3. cowork-pilot이 다음 sync 시 pending 요청 풀링
4. 영향 분석 → docs/ 업데이트 가능 여부 판단
5. 가능하면: docs/ 수정 + 새 exec-plan chunk 생성 → 자동 실행
6. 어려우면: ESCALATE → developer에게 알림
```

## 11. Removed / Changed Features (v2 원본 대비)

| 기능 | 변경 내용 |
|------|----------|
| 기획서 웹 작성 (WYSIWYG) | 제거. Cowork에서 작성, 업로드만. |
| Gemini Task 자동 생성 | 제거. cowork-pilot exec-plan이 대체. |
| Task 수동 상태 변경 | 유지하되 주로 cowork-pilot이 자동 변경. |
| Antigravity 채팅 동기화 | 제거 (v2 원본에서 이미 제거) |
| 타임 로그 | 제거 (v2 원본에서 이미 제거) |

## 12. Notification Triggers

| 이벤트 | 수신자 | 알림 타입 |
|--------|--------|-----------|
| Request 제출됨 | admin, 해당 프로젝트 developer | `request_submitted` |
| Request 승인됨 | 요청 작성자 (customer) | `request_approved` |
| Request 반려됨 | 요청 작성자 (customer) | `request_rejected` |
| 기획서 승인 요청 (pending_approval) | 해당 조직 customer 전체 | `spec_pending_approval` |
| 기획서 승인됨 | admin, 해당 프로젝트 developer | `spec_approved` |
| Task 상태 변경 (copilot sync) | 해당 프로젝트 developer | `task_status_changed` |
| 리포트 발행됨 | 해당 조직 customer 전체 | `report_published` |
| 채팅 메시지 | 프로젝트 참여자 (is_internal이면 admin/developer만) | `chat_message` |
| cowork-pilot ESCALATE | admin, 해당 프로젝트 developer | `copilot_escalation` |

알림 생성은 Service 레이어에서 해당 이벤트 처리 시 notification-service를 호출하여 수행한다.

## 13. Report Generation

**자동 생성:**
- 매주 월요일 KST 09:00, Vercel Cron Job으로 트리거
- 지난 주(월~일) 기간의 데이터 수집
- 같은 project + year + week_number 조합이 이미 있으면 스킵

**데이터 소스:**
- tasks: 이번 주 done 처리된 것, 현재 in_progress인 것
- copilot_projects: 진행률 (completed_chunks / total_chunks)
- GitHub commits: Octokit으로 프로젝트 repo의 해당 주간 커밋 조회
- specification_versions: 이번 주 새 버전이 있으면 change_summary 포함

**발행 플로우:**
1. AI(Gemini)가 데이터 기반 draft 생성
2. admin이 검토/수정
3. 발행 → published, 인앱 알림 + 이메일 발송
4. 이메일 발송 실패 시 에러 로그만, 리포트 상태는 published 유지

## 14. Database Indexes

```sql
CREATE INDEX idx_projects_org_id ON projects(org_id);
CREATE INDEX idx_tasks_project_id_status ON tasks(project_id, status);
CREATE INDEX idx_tasks_copilot_chunk_id ON tasks(copilot_chunk_id);
CREATE INDEX idx_requests_project_id_status ON requests(project_id, status);
CREATE INDEX idx_requests_copilot_synced ON requests(copilot_synced) WHERE status = 'approved';
CREATE INDEX idx_messages_project_id_created ON messages(project_id, created_at);
CREATE INDEX idx_notifications_user_id_read ON notifications(user_id, is_read);
CREATE INDEX idx_weekly_reports_project_week ON weekly_reports(project_id, year, week_number);
```

## 15. Deferred Decisions

- cowork-pilot 동기화 주기 (실시간 vs 폴링 간격)
- Sync API 인증 방식 고도화 (API Key → JWT)
- Phase 3 칸반 보드 UI 상세 설계
- Phase 4 변경 요청 자동 분석에 사용할 AI 모델/프롬프트
- 기획서 diff 시각화 (v1 ↔ v2 비교 뷰)
- 이메일 서비스 선택 (Nodemailer vs Resend)
- Task 뷰 방식 (칸반 vs 리스트)
- 첨부파일 업로드 세부사항 (크기, 타입 제한)
- 채팅 멘션 문법
- 페이지네이션 전략
- 데이터 보관/삭제 정책
- 결제 시스템 (Stripe 등)
- Organization 플랜 티어
