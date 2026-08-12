# 증빙자료 추출 Agent

> **파생 컨텍스트.** 정산에 첨부된 증빙 문서(사전승인 결재·회의록·출장계획서·영수증)에서
> **판정에 쓸 사실을 뽑아 EvalContext 경로로 돌려주는** 에이전트의 계약과 경계를 정의한다.
> 스키마·저장 구조는 `apps/core/domain/settlements/attachments.py`(구현 완료),
> 판정 사실의 출처 등급은 `_context/eval-context-sourcing.md` §9.
>
> 작성: 2026-08-11 · 상태: **저장 구조(틀) 구현 완료 / 추출 로직 미착수**

---

## 0. 왜 필요한가

판정에 필요한 사실의 상당수는 **사람이 타이핑할 값이 아니라 문서 안에 있다.**

| 필요한 사실 | 어디에 있나 |
|---|---|
| 사전승인 여부·승인자 | 사전승인 결재 캡처/PDF |
| 참석자 수·소속 | 회의록, 참석자 명단 |
| 출장 구분·지역등급·숙박비 | 출장계획서 |
| 봉사료·품목 | 영수증 상세 |

S-01 입력 폼에 칸을 계속 늘리면 **입력 부담이 자동화의 이점을 잡아먹는다.** 정산 담당자는 이미
그 문서들을 첨부하고 있으므로, 첨부에서 읽어내는 편이 자연스럽다.

---

## 1. 경계 — 3-Agent와의 관계

| Agent | 하는 일 | 이 Agent와의 차이 |
|---|---|---|
| **Draft Agent** | 영수증 **비전 판독** → 초안 필드(가맹점·금액·분류·사유) 자동 완성 | 대상이 **영수증 1종**, 목적은 **초안 작성**(사람이 고칠 값) |
| **증빙자료 추출 Agent** | 첨부 **다종 문서** → **판정 사실**(EvalContext 경로) | 대상이 **여러 종류**, 목적은 **룰 판정 입력**(감사 대상 값) |
| **Rule Agent** | 규정 문서 → 룰 그래프 **생성** | 문서에서 **룰**을 뽑음 (이쪽은 **사실**을 뽑음) |
| **Risk Review Agent** | 이상탐지 + RAG 내규 검증 | 추출된 사실을 **소비**하는 쪽 |

> 겹쳐 보이지만 산출물이 다르다. Draft는 "초안을 채워 사람이 확인"하고, 추출 Agent는
> "판정 근거를 만들어 엔진이 비교"한다. **후자는 틀리면 오판정으로 직결**되므로 신뢰도와
> 근거 위치를 반드시 남긴다.

---

## 2. 저장 구조 (구현 완료)

`Receipt`(거래-영수증 매칭 전용, 종류 구분 없음)와 별개로 `Attachment`를 둔다.

```python
class Attachment:                      # domain/settlements/attachments.py
    settlement, kind, file_ref, original_name, mime_type, uploaded_by, uploaded_at
    extraction_status                  # PENDING / RUNNING / DONE / FAILED / SKIPPED
    extracted          = JSONField     # EvalContext dot-path → 값   ← 핵심
    field_confidence   = JSONField     # 경로별 신뢰도
    evidence_spans     = JSONField     # 문서 내 근거 위치·인용
    extractor_version, extracted_at, error
```

`kind`: `RECEIPT` · `PRE_APPROVAL` · `MEETING_MINUTES` · `PARTICIPANT_LIST` · `TRIP_PLAN` ·
`CONTRACT` · `OTHER`

**`extracted`가 dot-path 형태인 이유**: `RuleTestCase.facts`와 같은 모양이라 조립기가
`apply_facts()`로 그대로 얹는다. 변환 계층이 없다.

---

## 3. 계약

### 3.1 입력 / 출력

```jsonc
// 입력
{ "attachment_id": 12, "kind": "MEETING_MINUTES",
  "file_ref": "attachments/12.pdf", "mime_type": "application/pdf",
  "settlement": { "category": "접대", "amount": 452000 } }   // 힌트용 컨텍스트

// 출력
{ "extracted": { "participants.participant_count": 4,
                 "participants.external_participant_count": 2 },
  "field_confidence": { "participants.participant_count": 0.94,
                        "participants.external_participant_count": 0.71 },
  "evidence_spans": [ { "path": "participants.participant_count",
                        "page": 1, "quote": "참석자: 김영업, 박거래, 이고객, 최담당" } ],
  "extractor_version": "extract-v1" }
```

### 3.2 **관측 계약 — 이 문서에서 가장 중요한 규칙**

| 상황 | 써야 할 값 | 이유 |
|---|---|---|
| 문서를 읽었고 해당 항목이 **없음을 확인** | 명시값(`0` / `false`) | **부재를 관측**했으므로 사실이다 |
| 문서에 그 항목이 다뤄지지 않음 / 첨부 없음 | **경로를 넣지 않는다** | 관측하지 않았으므로 모른다 |
| 읽었으나 판독 실패 | **경로를 넣지 않는다** + `error` 기록 | 추측값을 넣으면 오판정이 된다 |

경로를 넣지 않으면 EvalContext에서 `None`으로 남고 **미해소 가드가 REVIEW로 강등**한다.
「관측했는데 없음」과 「안 봤음」을 섞으면 이 프로젝트가 겪은 **"조용한 False"** 가 재발한다.

### 3.3 우선순위

```
첨부 추출값  <  화면 입력(Settlement 컬럼)
```

사람이 확정한 값이 이긴다. 단 **컬럼이 비어 있으면(모름) 추출값을 지우지 않는다**
(`context_builder._set_known`). 구현·테스트 완료.

### 3.4 스키마 밖 경로는 조용히 버린다

추출기가 `trip.flight_class`처럼 v3에서 제거된 경로를 보내도 `apply_facts`가 무시한다.
**추출기가 스키마보다 앞서 나가도 판정이 깨지지 않는다** — 나중에 필드를 되살리면 자동 반영된다.

---

## 4. 재사용할 인프라

| 필요 | 이미 있는 것 |
|---|---|
| PDF 파싱·청킹 | **`chunk_pdf`**(`apps/ai/app/rag/parsing/`) — 규정 문서용으로 만들었지만 회의록·출장계획서에 그대로 쓴다 |
| 이미지 판독 | **OpenAI 비전 직접 판독** (설계 결정, 별도 OCR 없음) |
| 스캔 문서 | OCR 경로는 열려 있으나 **기본 비활성** (`parsers/ocr.py`) |
| 저장·상태 | `Attachment` (구현 완료) |

**새로 만들 것은 "문서 종류별로 무엇을 뽑을지" 정의와 LLM 호출부뿐이다.**

---

## 5. 구현 계획 (미착수)

| 단계 | 내용 | 산출물 |
|---|---|---|
| E-1 | 종류별 추출 스펙 정의 — `kind` → 뽑을 EvalContext 경로 목록 + 프롬프트 | `apps/ai/app/agents/extract_agent.py` 상수 |
| E-2 | 텍스트 추출 파이프라인 연결 (PDF=`chunk_pdf`, 이미지=비전) | 〃 |
| E-3 | LLM 구조화 출력 → dot-path dict + 경로별 신뢰도 | 〃 |
| E-4 | Django 수신 API (`POST /api/internal/attachments/<id>/extracted/`) | `settlements/views.py` |
| E-5 | 재추출 트리거 (스키마 v↑·추출기 v↑ 시 `extractor_version` 비교) | 관리자 배치 |
| E-6 | 저신뢰 경로를 검토 화면(S-03)에 표시 | 프론트 |

### 종류별 추출 대상 (초안)

| kind | 뽑을 경로 |
|---|---|
| `PRE_APPROVAL` | `approval.pre_approval_obtained` |
| `MEETING_MINUTES` · `PARTICIPANT_LIST` | `participants.participant_count`, `external_participant_count`, `has_kickback_law_target` |
| `TRIP_PLAN` | `trip.trip_type`, `trip.region_grade`, `trip.lodging_amount_per_night` |
| `RECEIPT` | `category.item_type`, `dining.includes_alcohol` |

> `TRIP_PLAN` 대상 3개는 **출장 모델 없이도 추출만으로 채울 수 있는 유일한 경로**다.
> 출장비 그래프 활성화의 실질적 선행 조건이 여기다.

---

## 6. 판단이 필요한 것

| # | 쟁점 | 선택지 |
|---|---|---|
| 1 | 추출 실행 시점 | 업로드 즉시(동기) vs 제출 시 배치 vs 관리자 온디맨드 |
| 2 | 신뢰도 임계값 | 저신뢰 값을 **적용하되 표시** vs **적용하지 않음**(→ 미해소로 강등) |
| 3 | 추출값의 감사 표기 | `RuleHit.eval_context`에 "이 값은 추출됨" 표시를 남길지 |
| 4 | 재추출 정책 | 스키마 v↑ 시 전량 재추출 vs 참조되는 경로만 |
| 5 | Draft Agent와의 통합 | 영수증은 Draft가 이미 읽는다 — **중복 판독**을 합칠지 분리 유지할지 |

> **#2가 특히 중요하다.** "적용하되 표시"는 편하지만 저신뢰 오추출이 자동 통과를 만들 수 있다.
> 이 프로젝트의 원칙(사람 확정·조용한 실패 금지)에 비추면 **임계값 미달은 적용하지 않고
> 미해소로 남겨 REVIEW로 보내는 쪽**이 일관된다.
