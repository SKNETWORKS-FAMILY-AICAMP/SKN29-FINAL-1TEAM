# 알림 — 메시지 + 이동할 페이지

_최종 갱신: 2026-08-22 · 상태: 구현 완료 (11종, 페이지 이동)_

관련: [[settlement-ui-rules]] · [[rule-engine]] · [[rag-ingestion]] · [[default-gate]]

---

## 1. 무엇을 알림으로 만드는가

상태가 바뀔 때마다 알리면 소음이 되고 아무도 안 본다. 자격 조건 5개:

1. **사람이 할 일이 생겼거나, 기다리던 결과가 나왔을 때만.** 상태 변화 ≠ 알림 —
   `SUBMITTED→RPA_JUDGED`는 기계가 지나간 자리다.
2. **한 사건 = 한 알림.** 한 번의 제출로 전이가 2~3회 일어나지만 사람에게는 하나다.
3. **본인이 한 일은 본인에게 안 알린다**(`actor == recipient`면 만들지 않는다).
   예외는 §4 — **오래 걸리는 작업의 완료**는 내가 눌렀어도 알림거리다.
4. **비동기 결과는 알림이 유일한 통로다.** 문서 적재·룰 생성은 수십 초~분이 걸리고
   그동안 사용자는 화면을 떠난다.
5. **묶을 수 있는 것은 묶는다.** 팀원이 10건을 올릴 때 알림 10개는 소음이다.

## 2. 목록 (11종)

| kind | 사건 | 수신자 | 이동 | 묶기 |
|---|---|---|---|---|
| `SETTLEMENT_RETURNED` | `→RETURNED` · `→TEAM_RETURNED` | 지출자 | `/my-expenses` | ✗ |
| `SETTLEMENT_REJECTED` | `→REJECT` · `→TEAM_REJECTED` | 지출자 | `/my-expenses` | ✗ |
| `TEAM_COLLECT_PENDING` | `→TEAM_COLLECTING` | `team_aggregate` ∩ 같은 팀 | `/team` | ○ 팀 단위 |
| `REVIEW_PENDING` | `→IN_REVIEW` · `→PENDING_CONFIRM` | `accounting_review` | `/review` | ○ 상태별 |
| `DOC_INGEST_DONE` / `_FAILED` | `PolicyDoc` 적재 종료 | 올린 사람 | `/policy-docs` | ✗ |
| `RULE_AUTO_CREATED` | 규정 → 룰 초안 생성 성공 | `accounting_review` 전체 | `/rules` | ✗ |
| `RULE_UPDATED` | 룰 생성·대화형 수정 완료 | 요청한 본인 | `/rules` | ✗ |
| `RULE_SIMULATION_DONE` | 검증 보고서 | 실행한 본인 | `/rules` | ✗ |
| `RULE_ACTIVATION_REQUESTED` | 활성화 승인 요청 | `rule_activate` | `/rules` | ✗ |
| `RULE_ACTIVATED` | 활성 룰 변경 | `accounting_review` 전체 | `/rules` | ✗ |

**보완요청·반려는 묶지 않는다** — 건마다 사유가 다르고, 묶으면 어느 건의 사유인지 알 수 없다.
**검토 대기와 확정 대기는 따로 묶는다** — 성격이 다른 일이라 한 줄로 합치면 무엇을 해야
하는지가 사라진다.

## 3. 결정

### D-1. 알림은 파생이 아니라 저장한다

이 저장소 규율은 「저장하는 건 사람의 결정뿐」([[settlement-ui-rules]] §7)인데 예외다:

- **읽음 여부는 사람의 행동**이다.
- **현재 상태에서 역산할 수 없다.** 보완요청을 받았다가 재제출하면 상태는 `SUBMITTED`가 되어
  「보완요청을 받았었다」를 만들 방법이 없다.
- **비동기 결과는 이벤트 소스가 아예 없다.** `SettlementEvent`는 정산 전이만 담는다.

### D-2. 수신자는 한 명 — 여러 명이면 N행

다:다로 두면 읽음 상태를 어디에 둘지가 다시 문제가 되고, 「나에게 온 것」 쿼리가 매번 조인이 된다.

### D-3. 링크는 서버가 완성한다

`link`는 `/review` 같은 완성된 상대 경로다. 화면이 「이 종류면 이 경로」를 알면 곧 갈린다 —
플래그 라벨을 프론트가 복사했다가 백엔드 27개 vs 프론트 9개로 어긋났던 자리와 같다.

**`link`를 종류에서 파생하지 않고 저장하는 이유**: 나중에 경로가 바뀌어도 과거 알림이 그때의
화면을 가리키는 편이, 없는 화면으로 보내는 것보다 낫다.

### D-4. 생성 지점은 한 곳

```
services.transition()  ──►  notifications.events.on_transition()
```

`transition()`이 상태 전이의 **유일한 통로**다. 뷰마다 각자 만들면 하나는 반드시 빠진다 —
`risk_review`가 `judge` 액션에만 있어서 제출 경로에서 통째로 안 돌던 것과 같은 실수다.

비동기 계열은 각 완료 지점에서 직접 부른다(`IngestCallbackView`, 룰 콘솔 액션 5곳).

### D-5. 알림 실패가 업무를 막지 않는다

`on_transition`·`notify`가 **예외를 흡수**한다. 알림 때문에 상태 전이가 롤백되면 안 된다.
다만 `on_commit`은 쓰지 않는다 — 알림은 DB write일 뿐 외부 I/O가 없으므로, 전이가 롤백되면
알림도 사라지는 게 맞다.

### D-6. 수신자는 역할이 아니라 Capability로

인가의 정본은 Capability이고(기술 §3.1a), `extra_capabilities`로만 능력을 가진 사람이 실재한다 —
역할로 거르면 그 사람이 빠진다. `extra_capabilities`가 JSONField라 SQL로 못 걸러서
`accounts/queries.py::users_with_capability()`가 후보를 좁혀 받아 Python에서 거른다.

### D-7. 「화면에 있으면 안 알린다」는 화면이 판단한다

「룰 수정 완료는 그래프 수정 화면을 벗어나 있을 때만」이라는 요구가 있는데, **서버는 화면이
어디 있는지 모른다.** 그래서 알림은 **항상 만들고 화면이 접는다** — 룰 콘솔이 그래프를 열면
`POST /api/notifications/read-target/`으로 그 대상의 알림을 읽음 처리한다.

트레이드오프: 화면에 있는 동안 만들어진 알림이 다음 폴링(30초) 전에 접히므로 벨은 대개
울리지 않는다. 아주 짧게 배지가 켜졌다 꺼질 수는 있다.

### D-8. `count`는 「읽은 뒤 쌓인 수」다

현재 대기 총량이 아니다. 총량은 파생값이라 알림에 굳히면 화면과 어긋난다 — 총량은 화면에
가서 본다. 읽고 나면 **새 행**이 생긴다(안 그러면 새 일이 생겨도 벨이 안 울린다).

### D-9. 폴링은 개수만

벨 배지는 30초마다 `unread-count`만 받고, 목록은 패널을 열 때 1회. 목록을 폴링하면 서버만
친다(`RiskReviewStatus`가 진행 중일 때만 폴링하는 것과 같은 규율). WebSocket/SSE는 기술명세서
§6.2 「별도 Job 큐 없음」과 같은 결의 과잉이다.

## 4. 자기 알림 금지의 예외

`RULE_UPDATED`·`RULE_SIMULATION_DONE`은 **본인에게** 간다. 「내가 누른 버튼의 결과」가 아니라
**오래 걸리는 작업이 끝났다**는 알림이기 때문이다(룰 생성은 최대 300초). 화면에 그대로 있으면
D-7이 접는다.

**만들지 않는 경우**도 명시했다:
- 대화가 그래프를 실제로 바꾸지 않았으면(`applied_changes`가 빔) 알리지 않는다 — 질문만 한
  대화("왜 이렇게 됐어?")까지 알리면 대화 한 줄마다 알림이 쌓인다.
- `narrate=false` 시뮬레이션은 알리지 않는다 — 검증셋 자동생성의 자체검증 루프가 노드마다
  내부 호출하는 경로라, 한 번의 생성으로 수십 개가 쌓인다.
- 룰 생성이 실패했으면(`NO_SOURCE` 등) 알리지 않는다 — 응답 본문에 그대로 뜨는 즉시 오류다.
- 룰 자동 생성 **실패**는 회계 전체에 뿌리지 않는다 — 사유는 문서 화면에 남는다.

## 5. 지금은 페이지 이동까지만

특정 건을 열거나 목록에서 하이라이트하는 **딥링크는 다음 단계**다. 받는 쪽 인프라가 저장소에
아직 없다 — `/rules?graph=`를 만드는 코드는 [PolicyDocuments.tsx:201]에 있는데 **읽는 코드가
없어서 이미 죽어 있었다**(전체 화면에서 `useSearchParams` 사용처 0건). 링크를 만들어도 받는
쪽이 없으면 사용자는 페이지에 떨어져 대상을 손으로 찾게 된다.

다음 단계에 필요한 것: `?open={id}` 소비(S-01·S-02·S-03), `?graph={id}` 소비(S-04),
`?doc={id}` 소비(S-05), 그리고 연 뒤 파라미터 제거(`replace: true`).

## 6. 넣지 않은 것

목업(`mock.ts`)에 있던 두 종류를 뺐다 — **지어내지 않고 왜 없는지 남긴다**:

| 항목 | 사유 |
|---|---|
| 예산 소진 경고 | 사용액이 **파생값**(집계)이라 발생 이벤트가 없다. 주기적 재계산이 필요한데 배치 스케줄러가 없다(기술 §6.2 「별도 Job 큐 없음」) |
| 제출 마감 임박 | 시간 경과가 트리거라 마찬가지로 배치가 필요하다. 임계값(`policy.settlement_deadline`)은 이미 별표에 있으니 배치만 붙으면 된다 |

둘 다 `manage.py` 커맨드 + 외부 스케줄러(cron / 작업 스케줄러) 결정이 선행돼야 한다.

## 7. 코드·테스트

| 무엇 | 어디 |
|---|---|
| 모델·종류·링크표 | `domain/notifications/models.py` |
| 생성(묶기·자기알림 금지) | `domain/notifications/services.py` |
| 사건 → 알림 매핑 | `domain/notifications/events.py` |
| API | `domain/notifications/views.py` → `/api/notifications/` |
| 수신자 조회 | `domain/accounts/queries.py::users_with_capability` |
| 훅 | `settlements/services.transition` · `policies/policy_doc_views.IngestCallbackView` · `policies/views`(activate·simulate·request-activation·generate·converse) |
| 화면 | `lib/notifications.ts` · `api/notificationService.ts` · `components/layout/{Sidebar,NotificationPanel}.tsx` |
| 회귀 | `domain/notifications/tests.py` (27건) |
