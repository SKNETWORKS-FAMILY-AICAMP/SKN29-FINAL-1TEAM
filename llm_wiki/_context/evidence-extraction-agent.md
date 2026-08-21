# 증빙자료 추출 Agent

> **파생 컨텍스트.** 정산에 첨부된 증빙 문서(사전승인 결재·회의록·출장계획서·영수증)에서
> **판정에 쓸 사실을 뽑아 EvalContext 경로로 돌려주는** 에이전트의 계약과 경계를 정의한다.
> 스키마·저장 구조는 `apps/core/domain/settlements/attachments.py`(구현 완료),
> 판정 사실의 출처 등급은 `_context/eval-context-sourcing.md` §9.
>
> 작성: 2026-08-11 · 최종 갱신: 2026-08-21 · 상태: **전 구간 구현 완료(E-1~E-6)**
>
> **갱신 경위**: 판독 로직(E-1~E-3, `app/vision/`)은 2026-08-18에 이미 구현돼 MCP 서버에
> `read_receipt`·`read_evidence_document`로 등록돼 있었다 — 이 문서가 그 사실을 반영하지
> 못한 채 "미착수"로 남아 있었다(2026-08-21 전수 점검에서 발견). 그러나 **아무도 그 도구를
> 부르지 않았다** — 업로드 API(E-4)도, 판정 반영 시 신뢰도 게이트(§6 결정 2)도 없어서
> 사실상 죽은 코드였다. 이번 세션에서 E-4~E-6과 문서 전체를 실제 사용 가능한 상태로 이었다.

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
    settlement, kind, file, file_ref, original_name, mime_type, uploaded_by, uploaded_at
    extraction_status                  # PENDING / RUNNING / DONE / FAILED / SKIPPED
    extracted          = JSONField     # EvalContext dot-path → 값   ← 핵심
    field_confidence   = JSONField     # 경로별 신뢰도
    evidence_spans     = JSONField     # 문서 내 근거 위치·인용
    extractor_version, extracted_at, error
```

`file`(FileField, `PolicyDoc.file`과 같은 패턴)은 2026-08-21에 추가됐다 — 그전엔 `file_ref`
(CharField)만 있어서 원본을 실제로 저장할 곳이 없었다(업로드 API 자체가 없었으니 당연했다).
`file.name`이 곧 `file_ref` 계약값이다.

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
| PDF/이미지 판독 | **`app/vision/client.py`** — PDF는 `pypdfium2`로 페이지를 이미지로 렌더(`chunk_pdf`의 텍스트 추출이 아니다 — 결재 도장·서명은 텍스트 레이어에 없어서 텍스트로는 "승인받았는가"를 판별할 수 없다는 게 근거, §5 원안 폐기 사유), 이미지는 그대로. 둘 다 같은 경로로 OpenAI 비전에 넘긴다(별도 OCR 없음, 설계 결정) |
| 저장·상태 | `Attachment`(구현 완료, `file`·`file_ref`·`extraction_status`·`extracted`·`field_confidence`·`evidence_spans`) |
| 조립 | `context_builder.collect_from_attachments`(신뢰도 게이트 포함) — `Attachment.extracted`를 EvalContext로 얹는다 |

## 5. 구현 계획 — ✅ 전 구간 완료 (2026-08-21)

| 단계 | 내용 | 산출물 | 상태 |
|---|---|---|---|
| E-1 | 종류별 추출 스펙 정의 — `kind` → 뽑을 EvalContext 경로 목록 + 프롬프트 | `apps/ai/app/vision/document.py::TARGETS`, `receipt.py::ALLOWED_FACT_PATHS` | ✅ (2026-08-18) |
| E-2 | 텍스트 추출 파이프라인 연결 | **텍스트가 아니라 이미지로 통일**(`app/vision/client.py::load_images` — PDF는 `pypdfium2`로 페이지 렌더, 이미지는 그대로). 결재 도장·서명은 텍스트 레이어에 없어서 텍스트 추출로는 "승인받았는가"를 판별할 수 없다는 게 근거(§4 원안의 `chunk_pdf` 계획은 이 이유로 폐기) | ✅ (2026-08-18) |
| E-3 | LLM 구조화 출력 → dot-path dict + 경로별 신뢰도 | `document.py::read_evidence_document`, `receipt.py::read_receipt` — strict JSON Schema, 관측 목록(array) 방식(§3.2) | ✅ (2026-08-18) |
| E-4 | Django 수신 API | `POST /api/settlements/{id}/attachments/`(업로드=추출 요청, 응답이 곧 결과) · `DELETE .../attachments/{id}/` · `POST .../attachments/{id}/re-extract/` (`settlements/views.py`), FastAPI 쪽 진입점 `POST /agent/extract`(`app/api/extract.py`) | ✅ (2026-08-21) |
| E-5 | 재추출 트리거 | 전량 자동 재추출은 하지 않음(§6 결정 4) — `re-extract` 액션으로 사람이 수동 실행 | ✅ 최소 구현 (2026-08-21) |
| E-6 | 저신뢰 경로를 검토 화면에 표시 | `SettlementDetailModal.tsx` 첨부 목록 — 경로별 확신도 배지, 임계값(0.6) 미만은 "판정에는 반영되지 않았습니다" 안내 | ✅ (2026-08-21) |

**왜 이전엔 "미착수"였나**: E-1~E-3(판독 로직 자체)은 2026-08-18에 이미 구현돼 `mcp/tools.py`에
`read_receipt`·`read_evidence_document`로 등록됐지만, **그 도구를 부르는 곳이 어디에도
없었다** — Django에 업로드 API가 없어 `Attachment`가 생성될 방법 자체가 없었고, `Attachment`가
없으니 `context_builder.collect_from_attachments`(조립기 쪽은 이미 있었다)도 항상 빈 쿼리셋을
돌았다. "판독 로직 있음 + 아무도 안 부름"은 사실상 미착수와 같은 결과라 이번에 E-4~E-6으로
실제 사용 경로를 이었다.

### 종류별 추출 대상 (구현대로 확정)

| kind | 뽑는 경로 | 산출물 |
|---|---|---|
| `PRE_APPROVAL` | `approval.pre_approval_obtained` | `document.py::TARGETS` |
| `MEETING_MINUTES` · `PARTICIPANT_LIST` | `participants.participant_count`, `external_participant_count`, `has_kickback_law_target` | 〃 |
| `TRIP_PLAN` | `trip.trip_type`, `trip.region_grade`, `trip.lodging_amount_per_night` | 〃 |
| `RECEIPT` | `category.item_type`, `dining.includes_alcohol`(+ 화면용 `tx.payment_time`, `participants.participant_count`) | `receipt.py::ALLOWED_FACT_PATHS` |

> `TRIP_PLAN` 대상 3개는 **출장 모델 없이도 추출만으로 채울 수 있는 유일한 경로**다.
> 출장비 그래프 활성화의 실질적 선행 조건이 여기다.

---

## 6. 판단이 필요한 것 — 결정 완료 (2026-08-21)

| # | 쟁점 | 결정 | 근거 |
|---|---|---|---|
| 1 | 추출 실행 시점 | **업로드 즉시, 동기** | 첨부 1건 판독은 최대 수십 초(`app/vision/client.py TIMEOUT=90`)라 문서 파싱(수십 초~분, docling)만큼 무겁지 않다. 응답이 곧 결과라 화면이 폴링할 필요가 없고, MVP 동기 REST 원칙(CLAUDE.md §1)과도 맞는다. `PolicyDoc`(비동기 폴링)과는 무게가 다르다 |
| 2 | 신뢰도 임계값 | **적용하지 않음**(미해소로 강등) — 임계값 `0.6`, `context_builder.ATTACHMENT_CONFIDENCE_THRESHOLD` | "적용하되 표시"는 저신뢰 오추출이 자동 통과를 만들 수 있다. 이 프로젝트 원칙(사람 확정·조용한 실패 금지)에 비추면 미달은 미해소로 남겨 REVIEW로 보내는 쪽이 일관된다. 값 자체는 `Attachment.extracted`에 그대로 남아 화면(E-6)엔 보인다 |
| 3 | 추출값의 감사 표기 | **origin 문자열로 남김** — `context_builder.collect_from_attachments`가 `merger.offer(path, value, RANK_EXTRACT, f"attachment:{id}({kind})")`를 호출, `RuleHit.eval_context`(스냅샷)와 `conflicts`에 그대로 보존 | 이미 있던 `FactMerger`의 origin 추적 메커니즘을 그대로 썼다 — 별도 표기 필드를 새로 만들 이유가 없었다 |
| 4 | 재추출 정책 | **전량 자동 재추출 안 함** — 사람이 `re-extract` 액션으로 수동 실행 | 참조되지 않는 첨부까지 스키마 버전이 바뀔 때마다 비전 호출을 태우면 비용만 나가고 아무도 안 본다. 최소 구현으로 시작하고, 배치가 필요해지면 그때 추가 |
| 5 | Draft Agent와의 통합 | **분리 유지** | Draft Agent(영수증 초안 필드)와 증빙자료 추출 Agent(`kind=RECEIPT`)는 둘 다 `read_receipt`를 호출할 수 있지만 지금은 각자 다른 경로에서 쓰인다(Draft는 `draft-suggest`, 추출은 `attachments/` 업로드) — 목적(초안 vs 판정 사실)이 다르다는 §1의 원래 구분을 유지. 두 경로가 같은 영수증을 두 번 판독하게 되는 상황이 실제로 생기면 그때 합친다 |

> **#2가 특히 중요하다.** "적용하되 표시"는 편하지만 저신뢰 오추출이 자동 통과를 만들 수 있다.
> 이 프로젝트의 원칙(사람 확정·조용한 실패 금지)에 비추면 **임계값 미달은 적용하지 않고
> 미해소로 남겨 REVIEW로 보내는 쪽**이 일관된다.
