# Golden Rules

> 절대 규칙. CLI 에이전트는 이 규칙을 절대 위반해서는 안 된다.
> 이 문서는 실제 Cowork 세션 데이터 분석 기반으로 작성됨.
> 프로젝트 진행하면서 오판단 발견 시 이 문서에 규칙을 추가한다.

---

## 1. ESCALATE 블랙리스트 — 자동 응답 금지 카테고리

아래 카테고리에 해당하는 질문은 **무조건 ESCALATE**. CLI 에이전트가 아무리 확신이 있어도 자동 응답하지 않는다.

### 1.1 돈·결제·과금
- 결제 정보 입력/변경
- 구독 플랜 선택/변경
- 과금 관련 승인
- 유료 서비스 활성화

### 1.2 외부 서비스 계정
- 계정 생성/삭제 (Firebase, AWS, GCP, Vercel 등)
- OAuth 연결/해제
- API 키 생성/삭제/입력
- 서비스 계정 권한 변경

### 1.3 시크릿·크레덴셜
- 비밀번호, 토큰, API 키 직접 입력 요청
- `.env` 파일에 실제 값 입력 (템플릿은 OK)
- SSH 키, 인증서 관련
- Firebase/AWS 크레덴셜 직접 입력

### 1.4 프로덕션·배포
- 프로덕션 배포 승인
- 도메인 설정 변경
- DNS 레코드 변경
- SSL 인증서 설치

### 1.5 데이터 삭제 (되돌릴 수 없는)
- 데이터베이스 드롭/트런케이트
- 사용자 데이터 삭제
- 백업 삭제
- git history 삭제/리베이스 (원격)
- MCP 파일 삭제 도구 (`allow_cowork_file_delete` 등) — 기본 ESCALATE
  - 예외: 프로젝트 `docs/golden-rules-override.md`에 "정리 허용 경로"가 명시된 경우 해당 경로만 allow 가능
  - 발견일: 2026-03-23
  - 원인: `mcp__cowork__allow_cowork_file_delete`를 CLI가 allow 판정함 (Bash `rm` 패턴만 체크하고 MCP 도구명을 무시)
  - 조치: MCP 삭제 도구를 ESCALATE 블랙리스트에 추가

### 1.6 권한·보안
- 파일 권한 변경 (chmod, chown)
- 방화벽 규칙 변경
- CORS 설정 변경
- 인증 방식 근본적 변경

---

## 2. 도구 승인 절대 거부 목록

아래 명령/패턴이 포함된 도구 승인은 **무조건 deny**:

### Bash 명령
```
npm install *                   # [TEST] 패키지 설치 차단 (테스트용 — 나중에 제거)
pip install *                   # [TEST] 패키지 설치 차단 (테스트용 — 나중에 제거)
rm -rf                          # 재귀 삭제
rm -r (프로젝트 외부)            # 프로젝트 외부 재귀 삭제
sudo *                          # 루트 권한 실행
git push --force                # 히스토리 덮어쓰기
git push --force-with-lease     # 히스토리 덮어쓰기 (약간 안전하지만 여전히 위험)
git reset --hard                # 작업 내용 파괴
> /dev/sda, dd if=              # 디스크 직접 조작
:(){ :|:& };:                   # 포크 폭탄
curl/wget + | bash              # 원격 스크립트 실행
eval "$(curl ...)"              # 원격 코드 실행
chmod 777                       # 과도한 권한 부여
ssh, scp (외부 서버)            # 원격 접근
```

### Write/Edit 경로
```
/etc/*                          # 시스템 설정
/usr/*                          # 시스템 바이너리
~/.ssh/*                        # SSH 키
~/.bashrc, ~/.zshrc             # 쉘 설정
~/.gitconfig                    # Git 전역 설정
/var/*                          # 시스템 데이터
```

### MCP 도구 — 이름에 파괴적 키워드 포함
```
*delete*, *remove*, *destroy*    # 삭제 계열 → ESCALATE (allow 아님, deny 아님)
*drop*, *purge*, *truncate*      # 데이터 파괴 계열 → ESCALATE
```
> MCP 도구는 Bash 명령과 달리 도구 이름으로만 판단해야 한다.
> 도구명에 위 키워드가 포함되면 기본 ESCALATE.
> 프로젝트 override에서 특정 경로/패턴을 허용할 수 있다.

### 환경 변수 패턴
```
*_KEY=실제값                     # API 키에 실제 값
*_SECRET=실제값                  # 시크릿에 실제 값
*_TOKEN=실제값                   # 토큰에 실제 값
*_PASSWORD=실제값                # 비밀번호에 실제 값
```

---

## 3. AskUserQuestion 판단 원칙

### 절대 하지 말 것
- **추측으로 시크릿/크레덴셜 관련 질문에 답하지 않는다** — 항상 ESCALATE
- **프로젝트 문서에 근거 없이 아키텍처 방향을 정하지 않는다** — 문서에 없으면 (권장) 옵션, 그것도 없으면 ESCALATE
- **multiSelect=true인 질문에서 전부 선택하지 않는다** — 최소 필요한 것만
- **"Other" 자유 텍스트를 길게 쓰지 않는다** — 간결하게, 필요하면 ESCALATE

### 항상 할 것
- **(권장) 표시가 있으면 강하게 고려한다** — Cowork가 분석 후 붙인 것
- **YAGNI (You Aren't Gonna Need It)** — 둘 다 합리적이면 더 단순한 쪽
- **기존 코드/패턴과의 일관성** — 이미 있는 패턴을 따름
- **되돌릴 수 있는 선택을 우선** — 나중에 바꿀 수 있는 쪽이 안전

---

## 4. 오판단 발견 시 절차

1. 오판단이 로그에서 발견되면
2. 이 문서에 새 규칙을 추가한다
3. 가능하면 `tests/` 에 해당 케이스의 fixture를 추가한다
4. decision-criteria.md도 함께 업데이트한다

### 규칙 추가 형식
```markdown
### N.N 카테고리명
- 구체적 규칙 설명
- 발견일: YYYY-MM-DD
- 원인: [어떤 오판단이 있었는지]
- 조치: [어떤 규칙을 추가했는지]
```

---

## 5. 예외: 프로젝트별 오버라이드

특정 프로젝트에서 위 규칙을 완화해야 할 경우, 프로젝트의 `docs/golden-rules-override.md`에 명시한다. 오버라이드는 이 문서보다 우선한다. 단, 섹션 1 (ESCALATE 블랙리스트)은 오버라이드할 수 없다.
