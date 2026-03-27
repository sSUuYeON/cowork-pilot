---
name: vm-install
description: >
  VM에서 빌드/테스트용 툴체인을 설치해야 할 때 반드시 이 스킬을 사용하라.
  rustup, cargo, npm install, pip install, apt install 등 VM 디스크에 무언가를
  설치하는 모든 경우에 해당한다. 이 스킬 없이 툴체인을 설치하면 VM 디스크가
  복구 불가능하게 차오른다. cargo test, cargo build, npm run build 등
  빌드/테스트 명령을 실행하기 위해 설치가 필요한 상황에서 트리거된다.
---

# VM Install — 안전한 툴체인 설치 + 자동 정리

## 왜 이 스킬이 필요한가

Cowork VM은 9.6GB 디스크를 여러 세션이 공유한다. 각 세션은 서로 다른 리눅스 유저로 실행되기 때문에, 한 세션이 설치한 파일을 다른 세션에서 삭제할 수 없다. 자동 정리 메커니즘도 없다. 따라서 세션마다 Rust 툴체인(~600MB), node_modules, pip 패키지 등을 설치하면 디스크가 금방 찬다. 한번 차면 복구할 방법이 없어서 VM 자체를 재생성해야 한다.

이 스킬은 "설치 → 작업 → 정리"를 하나의 원자적 흐름으로 묶어서 이 문제를 방지한다.

## 핵심 원칙

1. **설치 전 용량 체크** — 여유 공간이 부족하면 설치하지 않고 사용자에게 로컬 실행을 안내한다.
2. **설치 경로 기록** — 무엇을 어디에 설치했는지 manifest에 남긴다.
3. **작업 완료 후 즉시 삭제** — 빌드/테스트가 끝나면 manifest에 기록된 경로를 전부 삭제한다.
4. **삭제 확인** — 삭제 후 `df -h`로 용량이 회복됐는지 확인한다.

## 절차

### Step 1: 디스크 용량 체크

```bash
df -h / | tail -1
```

여유 공간을 확인한다:
- **1GB 이상**: 설치 진행 가능
- **500MB~1GB**: 경고 출력 후 사용자에게 확인 요청. 사용자가 동의하면 진행
- **500MB 미만**: 설치 중단. 사용자에게 로컬 실행을 안내

### Step 2: Manifest 생성

설치할 경로들을 기록한다. manifest 파일 위치: `/tmp/vm-install-manifest.txt`

```bash
echo "" > /tmp/vm-install-manifest.txt
```

### Step 3: 설치 + 경로 기록

툴체인별 설치 명령과 기록할 경로:

| 툴체인 | 설치 명령 | 기록할 경로 |
|--------|----------|------------|
| Rust | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh -s -- -y` | `$HOME/.rustup`, `$HOME/.cargo` |
| Node.js 패키지 | `npm install` | 해당 `node_modules/` 디렉토리 |
| Python 패키지 | `pip install --break-system-packages <pkg>` | `pip show <pkg>`로 Location 확인 후 기록 |
| apt 패키지 | `sudo apt install -y <pkg>` (sudo 가능한 경우) | 패키지명 기록 |

설치 후 경로를 manifest에 추가:

```bash
echo "$HOME/.rustup" >> /tmp/vm-install-manifest.txt
echo "$HOME/.cargo" >> /tmp/vm-install-manifest.txt
```

Rust의 경우 설치 후 환경 로드:

```bash
source "$HOME/.cargo/env"
```

### Step 4: 빌드/테스트 실행

필요한 빌드/테스트 명령을 실행한다. 예시:

```bash
cargo test
cargo check
npm run build
```

결과를 기록해둔다 (성공/실패 여부, 에러 메시지 등).

### Step 5: 정리 (필수)

**빌드/테스트가 성공하든 실패하든 반드시 정리한다.**

manifest에 기록된 경로를 모두 삭제:

```bash
while IFS= read -r path; do
  [ -n "$path" ] && rm -rf "$path" 2>/dev/null
done < /tmp/vm-install-manifest.txt
rm -f /tmp/vm-install-manifest.txt
```

### Step 6: 용량 확인

```bash
df -h / | tail -1
```

삭제 전/후 용량을 비교하여 사용자에게 보고한다.

## 주의사항

- 이 스킬의 Step 5(정리)를 건너뛰는 것은 절대 허용되지 않는다. 빌드 실패, 테스트 실패, 에러 발생 등 어떤 상황에서도 정리는 반드시 수행한다.
- 사용자가 "빌드만 해줘"라고 해도 정리까지 포함해서 수행한다. 정리를 안 하면 다음 세션이 피해를 본다.
- 설치 없이 실행 가능한 경우(이미 설치되어 있는 경우)에는 이 스킬이 필요 없다. 설치가 필요한지 먼저 확인(`which cargo`, `which node` 등)하고, 이미 있으면 그냥 실행한다.
