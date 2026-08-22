# Draft Agent v2 — 사실로 쓰고, 판정은 엔진이 낸다

_최종 갱신: 2026-08-22 · 상태: 구현 완료_

> **한 줄**: 초안 Agent가 **지어낼 수 없는 것은 전부 서버가 사실로 넣고**, 모델에게는
> 분류·목적·설명만 남긴다. 「보완요청될 것 같은가」는 LLM이 예측하지 않고
> **결정론적 엔진을 dry-run으로 돌려** 얻는다.

관련: [[draft-agent-plan]] · [[rule-engine]] · [[eval-context-guide]] · [[rule-flags]] ·
[[evidence-extraction-agent]] · [[decision-case-data]] · [[category-vocabulary]]

---

## 1. v1이 안고 있던 문제

| # | 문제 | 결과 |
|---|---|---|
| 1 | 외부 사실이 **업종·분류별 한도 둘뿐**이었다 | 나머지는 화면이 보낸 폼 값 = 사람이 타이핑한 값. 모델이 지어낼 자리가 넓었다 |
| 2 | 영수증은 **저장 후에야** 판독되는데 저장하면 모달이 닫혔다 | "기본 내역을 비전이 채운다"가 성립하지 않았다 |
| 3 | `read_receipt`가 읽은 **가맹점·금액·일시가 버려지고 있었다** | `evidence_extract`가 판정 사실(`extracted`)만 저장하고 사용내역은 폐기 |
| 4 | 판정 미리보기 통로가 **만들어져 있는데 호출부가 0건** | `orchestrator.judge(record=False)` — 주석에 용도까지 적혀 있었다 |
| 5 | 제출 시 문장 손질 경로가 없었다 | 대충 쓴 사유가 그대로 감사 기록·결정 사례가 됐다 |

---

## 2. 핵심 결정

### D-1. 룰 그래프를 LLM에 주고 예측시키지 않는다 ⚠️

이 문서에서 가장 중요한 결정이다.

「지금 제출하면 보완요청/반려될까」는 **결정론적 엔진이 이미 답을 갖고 있다.**
`orchestrator.judge(settlement, record=False)`가 `rule_hits`도 상태도 건드리지 않고
실제 판정을 돌려준다.

그래프 구조 + EvalContext를 프롬프트에 넣고 순회를 흉내내게 하면:

1. **틀린다** — JSON-Logic 평가 + severity 우선순위 선형 체인 + 미해소 가드까지 재현해야 한다.
2. **틀려도 티가 안 난다** — 자연어 안내라 검증할 곳이 없다.
3. 사용자에게는 **"AI가 통과라 했는데 반려됨"** 이 된다. 가장 나쁜 실패 모드다.

저장소의 기존 규율과도 같은 방향이다 — `narrate.py`(Django가 등급을 결정론적으로 정하고
LLM은 서술만), MCP `run_rule_engine`(LLM 미개입, Django 위임, FR-RA-06).

**→ 엔진이 결정하고 모델은 옮긴다.** 그래서 그래프 구조는 프롬프트에 아예 없다. 대신
「무엇이 걸렸는가」(플래그)와 그 등록 설명·심각도·해소주체가 들어간다(`flags.describe()`).

> 참고: `09bedb5`가 추가한 `/api/internal/agent-context/` 카탈로그는 **어휘**(DSL 문법·
> EvalContext 경로·플래그 레지스트리)를 내려주는 것이고 현재 ACTIVE 그래프 구조는 없다
> (`profiles.py`가 "P1에서 `graph.current`가 붙는다"고 적어둔 상태). Draft Agent는 그
> 카탈로그를 쓰지 않는다 — **필요한 게 어휘가 아니라 판정 결과**이기 때문이다.

### D-2. 모델이 낼 수 없는 것은 스키마에서 뺀다

`LLMSettlementDraftOutput`은 `category` · `purpose` · `reasoning` · `flagExplanations`
**넷뿐**이다. 가맹점·금액·일시·업종은 필드 자체가 없다. 지시로 막는 것과 스키마로 막는 것은
다르다 — 업종을 스키마에서 뺐던 것(`_resolve_industry`)과 같은 판단이다.

### D-3. 플래그 코드는 서버가 정하고 문장만 모델이 쓴다

`flagExplanations`의 `code`는 **주어진 목록 밖이면 버린다**. 모델이 사유를 만들어 안내하면
사용자는 있지도 않은 문제를 고치려 한다. 설명이 안 온 플래그는 등록된 `description`으로
채운다 — 빈손으로 두지 않는다(사유 코드를 펴는 것이지 지어내는 게 아니다).

### D-4. REVIEW로는 사람을 멈춰 세우지 않는다

`REVIEW`는 룰이 판단하지 않고 회계에 넘긴 것이라 지출자가 고칠 것이 없다. 여기서 경고를
띄우면 정상 건마다 사람이 멈춰 선다. 안내 등급은 `RETURN`/`REJECT`만 `blocker`,
`REVIEW`는 `info`다.

### D-5. 영수증이 읽은 사용내역은 「비어 있는 자리에만」

`_apply_receipt_basics()`가 거래 원장에 반영하되 **`basicsPending`인 거래에만** 넣는다.

- **ERP 수집 건은 카드사 원장이 정본**이다 — 부분취소·팁으로 금액이 다를 수 있고, 그때
  맞는 쪽은 원장이다.
- **사람이 친 값도 덮지 않는다** — 사용자가 보는 앞에서 값이 바뀌면 무엇이 사실인지 알 수 없다.
- 읽지 못한 항목은 그대로 둔다(빈 값으로 덮지 않는다). 날짜만 있고 시각이 없으면 **시각을
  지어내지 않는다**(정오로 밀면 심야 판정이 조용히 뒤집힌다).

### D-6. 저장이 먼저다 (S-01 흐름 전환)

```
[영수증 파일 선택]
    ↓ 즉시 저장 — Settlement(DRAFT) + Attachment(RECEIPT), 판독 예약
[판독 중…]        ← 모달 유지, EvidenceAttachments가 폴링
    ↓ 비전이 가맹점·금액·일시·품목을 읽는다
[초안 작성]        ← draft/settlement (판정 미리보기 포함)
    ↓
[사람 확인 → 팀에 올림]
```

「취소」 버튼을 두지 않는다 — 파일을 고른 시점에 이미 건이 생겼으므로 없애는 동작의 정확한
이름은 **삭제**다. 진행 상태는 단계(`saving`/`reading`/`drafting`)로 보여준다. 퍼센트를
꾸며내지 않는다 — 판독은 실제로 수십 초 걸리고, 90%에서 멈춘 진행 바는 고장으로 읽힌다.

### D-7. 추가 증빙이 붙으면 초안을 다시 쓴다

판독이 끝나면(`DONE`·`FAILED`·`SKIPPED`) 초안을 재실행한다. 사람이 별도 버튼을 눌러야 하면
아무도 안 누른다. **실패도 트리거다** — `DONE`만 기다리면 판독이 실패했을 때 화면이 영영
"판독 중"으로 남는다.

### D-8. 제출 시 문체는 조용히 다듬되, **사실이 늘었는지는 기계가 본다**

"사실을 추가하지 마라"고 지시하고 `addedFacts`를 물으면 모델은 대체로 `[]`라고 답한다.
이 문장은 감사 기록으로 남고 결정 사례로 인용되므로([[decision-case-data]]) 자기평가로
통과시킬 수 없다. 그래서 원문과 **기계적으로 대조**한다:

| 검사 | 잡는 것 |
|---|---|
| 원문에 없던 **수**가 생김 | "팀 회식" → "팀 회식 (참석 8명)" — 가장 흔한 환각 |
| 원문의 수가 **사라짐** | 정보 소실 |
| 길이가 **2배 초과 + 25자 이상** 증가 | 다듬기가 아니라 덧붙이기 |
| 결과가 **비었음** | 다듬기가 아니라 새로 쓰기 |

한글 수사(`세 명`→`3`)와 자릿수 쉼표(`1,200`→`1200`)는 같은 값으로 접는다 — 표기만 바뀐 것을
잡으면 정상적인 다듬기가 매번 걸린다.

선을 넘으면 **자동 적용하지 않고**(원문 유지) 사람에게 원문·다듬은 문장을 나란히 보여 준다.
모델의 `addedFacts`는 참고로만 싣는다(정본은 기계 대조 결과).

목적이 사실상 비어 있으면(공백 제거 6자 미만) LLM을 부르지 않고 안내만 한다 — **대신 채워
넣지 않는다.** 목적은 사람이 쓰는 것이고, 여기서 지어내면 그 문장이 감사 기록이 된다.

### D-9. 「멈춰 세울지」의 기준은 서버가 소유한다

`prepare-submit`이 `shouldConfirm`을 내려준다. 화면이 그 규칙을 갖고 있으면 곧 서버와 갈린다
(팝업 조건이 두 곳에 생기는 순간 어느 쪽이 맞는지 아무도 모른다). 기본 동작은 **조용히
다듬어 그대로 제출**이고, 여기 걸리는 건 셋뿐이다: 과하게 바뀐 문장 / 정보 부족 /
RETURN·REJECT 예상.

---

## 3. 흐름

```
        ┌──────────────────────── core ────────────────────────┐
        │  draft_context.build(settlement)                     │
        │    · basics      ERP 수집·영수증 비전·카드 원장       │
        │    · attachments 첨부가 실제로 읽어낸 것(+ 신뢰도)     │
        │    · facts       EvalContext(값 있는 것만 + 설명)     │
        │    · judgement   orchestrator.judge(record=False) ★  │
        │    · returnContext  왜 돌아왔는지(사유 + 처리자)       │
        └───────────────────────┬─────────────────────────────┘
                                │ GET /api/internal/settlement-draft-context/{id}/
        ┌───────────────────────▼─────────── ai ──────────────┐
        │  draft_facts.render(ctx)   사실 → 프롬프트 문장      │
        │  draft_agent.run_for_settlement()                   │
        │    출력: category · purpose · reasoning · 플래그 설명 │
        │    ※ 가맹점·금액·업종은 스키마에 없다                 │
        └───────────────────────┬─────────────────────────────┘
                                │ notices(코드는 서버, 문장은 모델)
                          [화면 AgentPanel]

  제출:  persistEdits → prepare-submit ─┬─ shouldConfirm=false → 조용히 제출
                                        └─ true → SubmitConfirmModal
```

---

## 4. 코드·테스트 위치

| 무엇 | 어디 |
|---|---|
| 사실 조립 + 판정 dry-run | `apps/core/domain/settlements/draft_context.py` |
| 내부 창구 | `GET /api/internal/settlement-draft-context/{id}/` |
| 영수증 → 거래 원장 반영 | `settlements/evidence_extract.py::_apply_receipt_basics` |
| 제출 준비(다듬기 + 멈춤 판단) | `settlements/submit_prep.py` · `POST /api/settlements/{id}/prepare-submit/` |
| 초안 프록시 | `POST /api/settlements/{id}/draft/` |
| 사실 렌더 | `apps/ai/app/agents/draft_facts.py` |
| 정산 모드 초안 | `agents/draft_agent.py::run_for_settlement` · `POST /agent/draft/settlement` |
| 문체 다듬기 + 대조 | `agents/submit_polish.py` · `POST /agent/draft/polish` |
| 화면 | `components/settlement/AgentPanel.tsx` · `SubmitConfirmModal.tsx` · `SettlementDetailModal.tsx` |
| 회귀 | core `tests/test_draft_context.py`(21) · ai `tests/test_draft_settlement.py`(20) |

---

## 5. 남은 것

- **폼 기반 옛 경로(`/agent/draft`)가 남아 있다** — 저장 전 상태에서만 쓰이고(자연어 지시),
  신규 등록이 저장 먼저로 바뀌면서 사실상 사용처가 거의 없다. 다음 정리 대상.
- **AI-LAB Draft 탭은 아직 폼 모드만** 실행한다. 정산 모드 탭 추가 필요.
- **금액 불일치 경고 없음** — 영수증 총액과 카드 결제액이 다를 때(부분취소·팁) 지금은
  조용히 원장을 따른다. 사실 불일치는 판정에 영향이 크므로 신호로 남기는 편이 낫다.
- **`prepare-submit`이 목적 문장만 다듬는다** — 분류가 명백히 어긋난 경우(예: 주류 포함
  영수증인데 `비품`)를 잡지 않는다. 그건 룰의 일인지 Agent의 일인지 미정.
