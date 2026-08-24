# Draft Agent 구현 기획 — 역할 분담 & v0/v1 로드맵

> 파생 컨텍스트. 권위 규범 = `요구사항_명세서.md` §5.1(FR-DA-01~09), `기술명세서.md` §4.1. 코드 수준 스펙은 `_context/draft-agent-v0.2.md`.

## 진행 현황(2026-08-10) — B-1~B-6 전체 완료

| 단계 | 상태 | 비고 |
|---|---|---|
| v0(생성 모드) | ✅ | `apps/ai/app/api/draft.py`, `apps/ai/app/agents/draft_agent.py` |
| B-1·B-2(프롬프트 개선 + 응답 형식 강제) | ✅ | OpenAI Structured Output(strict)로 전환 — 6개 분류·필드 타입을 API 단에서 강제, 사후 clamp 로직 불필요해짐 |
| B-3(`get_policy` 실연동) | ✅ | Django `PolicyLookupView`(`/api/internal/policies/<category>/`) 신설 + 실 Postgres 조회. 시드값(6개 분류, 3만원)은 임시값(§7) |
| B-4(수정 모드) | ✅ | `ReviseRequest`(`{instruction, current:{...}}` 중첩 구조) 처리 추가 |
| B-5(Django↔FastAPI 연결) | ✅ | `draft_suggest` 액션이 FastAPI `/agent/draft`를 우선 호출, 실패 시 로컬 폴백 |
| B-6(엔드투엔드) | ✅ | Docker로 db·core·ai·web 전부 기동, 화면에서 생성·수정 모드 모두 실제 응답 확인 |
| Policy 고도화(RAG 연동 등) | ⏸ 보류 | 이번 범위에서 제외. §7 오픈이슈로 유지 |

**지금 상태**: 화면(`localhost:5173`, `VITE_USE_MOCK=false`)에서 실제로 눌러볼 수 있다. 코드는 전부 작성 완료됐으나 **git 커밋은 아직 하지 않음**.

---

## 1. 목표

`apps/ai`의 Draft Agent를 stub에서 **실제 LLM 호출**로 구현한다. 화면(React)과 Django 시리얼라이저는 건드리지 않는다 — §3 계약만 지키면 된다.

RAG(임베딩·청킹)와는 무관하다. Draft Agent는 `Policy` 테이블의 숫자 한도값만 조회하며 벡터 검색(Chroma)에 의존하지 않으므로, RAG 파이프라인 완료를 기다리지 않고 독립적으로 진행한다.

---

## 2. 아키텍처에서의 위치

```
① 사용자가 지출 등록(S-01)
        │
② [Draft Agent] 가맹점/금액 → 분류·사유·정책힌트 초안 생성     ← 이 문서의 범위
        │
③ 사용자가 화면에서 초안 확인·수정 → 팀 취합 → 회계 제출
        │
④ [Rule Agent] 결정론적 규칙 1차 판정                          (별도 작업)
        │
⑤ [Risk Review Agent] 이상탐지 + RAG 내규검증                  (별도 작업)
        │
⑥ 회계 담당자 최종 확정
```

```
[Django "draft-suggest" 액션] --(httpx, 실패 시 폴백)--> [FastAPI /agent/draft]
        │ 배관                                                  │ LLM 로직
   기존 폴백 로직 유지                                  OpenAI Structured Output
                                                                 │
                                                  [get_policy] --(Django 내부 read API)--> Policy 테이블
```

Django `draft_suggest` 액션(`settlements/views.py`)은 아직 FastAPI를 호출하지 않는다. 지금은 Django 플레이스홀더 함수(`domain/settlements/draft_agent.py`의 `suggest_draft`/`revise_draft`)를 그 자리에서 직접 호출한다. 위 다이어그램의 실제 연결은 B-5(v1) 작업이다.

---

## 3. 계약(Contract) — 절대 바꾸지 않는 부분

프론트(`SettlementDetailModal.tsx`)와 Django 시리얼라이저가 이미 이 모양을 소비한다. **두뇌만 교체하고 모양은 유지**한다.

### 3-1 생성 모드 입력

`instruction` 없이 호출. 실제 프론트 호출(`suggestDraft`)은 아래 필드를 flat하게 보낸다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `merchant` | string | ✅ | 가맹점명 |
| `amount` | number | ✅ | 결제 금액(원) |
| `date` / `ts` | string | ✅ | 결제 일시 |
| `cardType` | string | ✅ | `PERSONAL`/`TEAM`/`SHARED`/`POST_PAID`/`PREPAID` |
| `evidence` | string | - | `OK`/`MISSING` |
| `headcount` | number | - | 참석 인원. **실제 프론트는 생성 모드에서 이 필드를 보내지 않는다** — 미전달 시 기본값 0으로 처리 |
| `receipt_image` | string(base64) | - | v0/v1 범위 밖. 필드 자리만 열어둠(§7) |

### 3-2 수정 모드 입력

`instruction`이 있는 호출. **생성 모드와 다른 중첩 구조**로 온다(`settlementService.ts`의 `reviseDraft()` 기준):

```jsonc
{
  "instruction": "자연어 지시",
  "current": { "merchant": "...", "amount": 0, "category": "...", "aiCategory": "...",
               "purpose": "...", "evidence": "OK", "headcount": 0 }
}
```

수정 모드용 요청 스키마(`ReviseRequest`)는 생성 모드용 `DraftRequest`와 별도로 설계해야 한다(v1, B-4).

### 3-3 출력 (생성/수정 모드 공통)

```jsonc
{
  "mode": "create" | "revise",
  "draft": {
    "merchant": "...", "amount": 0, "category": "식대",
    "aiCategory": "식대", "aiSuggested": true,
    "merchantIndustry": "...", "purpose": "...",
    "evidence": "OK", "headcount": 0
  },
  "confidence": 0.0,
  "comments": [{ "icon": "ocr" | "ai" | "doc", "text": "AI가 왜 이렇게 채웠는지 근거 문장" }],
  "policyHints": [{ "level": "warn" | "info", "clause": "...", "text": "...", "status": "..." }]
}
```

- `category`는 반드시 6개 중 하나: `회식`/`회의`/`식대`/`출장`/`접대`/`비품`(2026-08-14: `업무활성`은 폐지되고 `회식`이 그 자리를 대체 — 개념은 다르다. `업무활성`이 맡던 미분류 캐치올은 `비품`으로 흡수됐다)
- `aiSuggested: true` = 확신이 낮아 사람 확인이 필요하다는 뜻(화면에서 강조 표시)

---

## 4. 역할 분담

#### Draft Agent
- v0 초안 작성 @김정민
- v0 고도화 → v1 완성 @이지현

성숙 단계 기준으로 나눈다: 김정민님이 "일단 되는" v0을 만들고, 지현님이 이어받아 프롬프트 품질·정책 연동·Django 배선까지 v1로 완성한다.

### 4-1 v0 착수 조건

| 항목 | 결정 내용 |
|---|---|
| 계약 | §3-1(생성 모드)만 대상. 수정 모드(§3-2)는 v1 범위 |
| 코드 위치 | `apps/ai/app/agents/draft_agent.py`(로직), `apps/ai/app/api/draft.py`(요청 스키마). 두 파일 모두 현재 `settlement_id: int`만 받는 stub이라 **전면 교체**가 필요(신규 작성이 아님) |
| 실행 방법 | `apps/ai` 단독 `uvicorn app.main:app --reload --port 9000` 후 `POST /agent/draft` 직접 호출 — Django·화면 없이 검증 가능 |
| `OPENAI_API_KEY` | `.env`에 등록 완료, 바로 사용 가능 |
| `get_policy`(정책 조회) | v0는 **더미 dict 하드코딩**으로 대체(예: `{"limit": 30000, "required_evidence": ["영수증"]}`). 실제 Django 연동은 v1(B-3) |
| 참고할 기존 코드 | Django 플레이스홀더(`domain/settlements/draft_agent.py`)의 `_guess_category`/`_policy_hints` — "뭘 반영해야 하는지" 아이디어만 참고, 규칙 코드를 그대로 옮기지 않는다 |
| 이미지 입력 | v0 범위 아님 |

**Definition of Done** ("일단 되면 끝" — 완성도 기준 아님)
- [ ] `POST /agent/draft`에 거래 1건을 보내면 200 응답
- [ ] `mode`, `draft.category`, `draft.purpose`, `confidence`, `comments`가 채워짐
- [ ] `draft.category`가 6개 분류 중 하나
- [ ] `policyHints`가 더미 정책값 기준으로 최소 1개 로직 동작(예: 금액 > 더미 한도면 warn)

**검증용 샘플 3건**
1. 스타벅스 강남점 / 8,400원 / 카드구분: 개인
2. 한우마을 / 320,000원 / 카드구분: 팀, headcount 4 (실제 트래픽엔 안 오지만 DoD 검증용으로 의도적으로 포함)
3. KTX 서울-부산 / 59,800원 / 카드구분: 후정산

### 4-2 v0 작업 — @김정민

| # | 작업 | 산출물 |
|---|---|---|
| A-1 | §4-1 기준 FastAPI 요청/응답 스키마 작성 | `apps/ai/app/api/draft.py` |
| A-2 | 시스템 프롬프트 초안 작성 | 프롬프트 텍스트 |
| A-3 | OpenAI 호출 함수 구현(Structured Output 엄격 강제는 v1) | `apps/ai/app/agents/draft_agent.py` |
| A-4 | 검증용 샘플 3건으로 직접 호출해 확인 | 응답 로그 3건 |

인계 시: DoD 4개 통과 + 샘플 3건 응답 로그 + 애매했던 판단은 코드 주석으로.

### 4-3 v1 작업 — @이지현

| # | 작업 | 산출물 |
|---|---|---|
| B-1 | 프롬프트 품질 개선(§5 기준) | 프롬프트 v1 |
| B-2 | Structured Output(JSON Schema strict)로 응답 형식 강제 | `agents/draft_agent.py` |
| B-3 | `get_policy` 실제 연동(더미 제거) | `mcp/tools.py`, Django `/api/internal/policies/...` |
| B-4 | 수정 모드 추가 — §3-2 중첩 구조 기준 `ReviseRequest` 신설 | 동일 함수 내 분기 |
| B-5 | Django `draft_suggest` 액션에 FastAPI 호출 연결 + 실패 시 폴백 유지 | `apps/core/domain/settlements/views.py` |
| B-6 | 화면에서 엔드투엔드 확인 | 데모 캡처 |

---

## 5. 프롬프트 설계 원칙 (v1 고도화 기준)

| 원칙 | 이유 |
|---|---|
| 분류는 6개 중 하나로 강제(Structured Output `enum`) | Django `Category` TextChoices와 정확히 일치해야 저장 가능 |
| 가맹점 업종은 참고용 힌트, 세무 판단 근거 아님을 명시 | FR-DA-03c 위반 방지 |
| `policyHints`는 LLM이 지어내지 않고 `get_policy()` 숫자만 근거로 생성 | 감사 가능성 — 규정 위반 판단은 결정론적 데이터 기반이어야 함 |
| 참석 인원 정보가 없으면 언급하지 않음 | 실제로 `headcount`가 거의 항상 0으로 온다 — 없는 인원수를 지어내는 걸 방지 |
| 확신 낮으면 `aiSuggested=true` + `confidence` 낮게 | 화면에서 사람 확인 필요 표시 |
| `comments`는 판단 근거 문장 | 사람이 AI 판단을 신뢰하고 확정할 근거 |

### 최소 골격

```
[System]
당신은 법인카드 정산 초안 작성 보조입니다.
분류는 반드시 다음 6개 중 하나만 선택하세요: 회식, 회의, 식대, 출장, 접대, 비품.
가맹점 업종은 참고용 힌트일 뿐이며 세무 판단 근거로 사용하지 마세요.
판단 확신이 낮으면 aiSuggested=true로 표시하고 confidence를 낮게 주세요.
참석 인원 정보가 없으면(0명) 언급하지 말고 목적만 작성하세요.
아래 제공되는 정책 한도를 벗어나는 경우에만 policyHints에 warn 레벨로 안내하세요(직접 계산해서 지어내지 마세요).

[User]
가맹점: {merchant}, 금액: {amount}원, 일시: {ts}, 카드구분: {card_type}, 증빙: {evidence}
정책 정보: {policy_from_get_policy}
(instruction이 있는 경우) 사용자 지시: {instruction}
```

---

## 6. 검증 방법

1. **v0**: `apps/ai` 단독 실행 + 검증용 샘플 3건을 `POST /agent/draft`로 직접 호출, DoD 확인
2. **v1**: 케이스 확장(6개 분류 전체) + `get_policy` 실연동 후 재검증
3. **엔드투엔드**: Django 화면에서 지출 등록 → 초안 자동완성 → 실제 LLM 응답 확인(B-5 이후)

---

## 7. 오픈 이슈

| 이슈 | 현재 상태 | 필요 결정 |
|---|---|---|
| 영수증 이미지 업로드/저장 | `Receipt.file_ref`가 문자열 경로일 뿐 실제 파일 저장 로직 없음 | v0/v1은 텍스트 필드만, 이미지는 별도 작업으로 분리 |
| `evidence`/`headcount` 저장처 부재 | Django `Settlement` 모델에 두 컬럼이 없다. `SettlementSerializer.get_evidence`는 항상 `"OK"` 하드코딩 반환, `headcount`는 시리얼라이저에 없음 | Draft Agent 출력을 실제로 DB에 반영하려면 스키마 확장(마이그레이션) 필요 여부 결정 |
| Policy 테이블 실제 값 | 더미/시드 값이 정확한 규정값인지 미확인 | 「법인카드 사용 규정」 원문 대조 |
| ⚠️ Policy 모델 자체가 폐기 대상 | 다른 팀원이 설계한 `_context/policy-domain.md`(2026-08-10)가 지금 Draft Agent가 쓰는 `Policy` 모델(`limit_amount` 등)을 **폐기**하고 `PolicyTable`+`ctx.policy.*` 카탈로그 체계로 교체하기로 결정함(설계 확정, **구현은 아직 미착수**이므로 지금 당장 영향 없음) | `PolicyTable` 체계가 실제로 구현되면 `get_policy` 연동을 그쪽으로 재연결해야 함. 그 전까지는 현행 유지 |
| RAG 연동 시점 | Draft Agent는 Chroma 미사용 | Risk Review Agent 단계에서 RAG 작업과 합류 |
