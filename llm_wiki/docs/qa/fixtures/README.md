# QA 테스트 데이터 시드 (Django fixture, `dumpdata` 산출)

2026-08-22~24 라이브 QA에서 만든 DB 리소스를 재사용 가능한 형태로 남긴 것.
**2026-08-25 확인: 원본 DB 레코드는 이미 삭제됐다** — 이 fixture가 그 데이터의 유일한 남은
스냅샷이다(`llm_wiki/docs/qa/_summary.md` 참조). 재현하려면 아래 `loaddata` 절차를 쓴다.

## 파일 목록

| 파일 | 내용 | 건수 | 원본 PK |
|---|---|---|---|
| `qa_risk_review_transactions.json` | Risk Review Agent 테스트용 `Transaction` | 50 | id 728~777 |
| `qa_risk_review_settlements.json` | 같은 테스트용 `Settlement`(위 Transaction 참조) | 50 | id 476~525 |
| `qa_rule_agent_rulegraphs.json` | Rule Agent 테스트로 생성된 `RuleGraph`(DRAFT) | 51 | id 89~138, 141 |
| `qa_rule_agent_rulenodes.json` | 위 RuleGraph들의 `RuleNode` | 273 | (graph FK로 종속) |

## ⚠️ 전제 조건 — "아무 DB에나" 로드되지 않는다

`dumpdata --pks`로 뜬 raw PK 스냅샷이라 두 가지를 가정한다:

1. **참조 FK가 이미 존재해야 한다** — Settlement은 카드 41(`kim`의 개인카드)·팀 13(영업팀)·
   사용자 `kim`을 참조한다. 이 값들은 `seed --fresh`(또는 이 QA를 진행했던 시점과 동일한
   시딩 순서)로 만들어진 DB에서만 같은 PK로 존재한다. 다른 시드 조합(`seed_clean`,
   `seed_adopted`)이나 재시딩 이력이 다른 DB에는 그대로 안 맞을 수 있다.
2. **대상 PK 자리가 비어 있어야 한다** — 예를 들어 이미 `Settlement.id=476`이 다른 용도로
   존재하는 DB에 로드하면 충돌(덮어쓰기 또는 오류)한다.

즉 이 fixture는 "QA를 재현했던 바로 그 DB 상태"의 스냅샷이지, 범용 시드 스크립트(`seed.py`류)와
같은 이식성은 없다. 새 환경에서 처음부터 이 테스트를 재현하려면 fixture 로드보다
`llm_wiki/docs/qa/risk-review-agent-qa.md`(필드 설계 근거)를 참고해 관리 명령을
새로 짜는 편이 더 안전하다 — 이 fixture는 "지금 있는 걸 잃지 않기 위한 백업"이 1차 목적이다.

## 로드 방법

FK 순서를 지켜야 한다(Transaction → Settlement, RuleGraph → RuleNode):

```bash
docker compose exec core python manage.py loaddata \
  /app/../llm_wiki/docs/qa/fixtures/qa_risk_review_transactions.json
docker compose exec core python manage.py loaddata \
  /app/../llm_wiki/docs/qa/fixtures/qa_risk_review_settlements.json
docker compose exec core python manage.py loaddata \
  /app/../llm_wiki/docs/qa/fixtures/qa_rule_agent_rulegraphs.json
docker compose exec core python manage.py loaddata \
  /app/../llm_wiki/docs/qa/fixtures/qa_rule_agent_rulenodes.json
```

(컨테이너에 이 경로가 마운트 안 돼 있으면 파일을 core 컨테이너의 media/app 볼륨 아래로 복사한
뒤 그 경로로 `loaddata`를 호출한다 — `docker cp` 후 절대경로 지정.)

## 재사용 시나리오

- **지금 DB에서 원본이 지워진 뒤 되돌리고 싶을 때**: 위 순서대로 `loaddata`.
- **다른 개발자 환경에서 같은 QA를 재현하고 싶을 때**: 위 전제 조건이 맞는지 먼저 확인
  (`Card.objects.get(id=41).owner.username == "kim"` 등).
- **케이스 설계 자체를 참고하고 싶을 때**: 이 JSON보다 `risk-review-agent-qa.md`·
  `rule-agent-qa.md`가 사람이 읽기 좋다 — 필드 조합의 "왜"가 여기 없다.
