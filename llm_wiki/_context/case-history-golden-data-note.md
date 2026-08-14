# case_history 적재 상태 메모 (2026-08-14)

> `docs/RAG_전략_종합.md`(같은 날 신규 작성했다가, 팀원이 별도로 원본을 작성 중이라 중복/충돌
> 방지를 위해 삭제)에만 있던 내용 중 팀원 원본 병합 시 참고할 만한 부분을 남겨둔 메모.
> 이 파일은 AI가 관리하는 `_context/`(파생 컨텍스트)라 팀 원본 문서와 상충하면 팀 원본이 이긴다 —
> 원본이 이 내용을 이미 담고 있으면 이 파일은 지워도 된다.

## 핵심 사실

`case_history`(과거 승인/반려 유사 사례 컬렉션)는 **정기 배치로 실 결정이력을 적재하는 파이프라인이
없다.** `policy_docs`(103건)·`tax_refs`(730건)·`org_docs`(55건)는 전부 실 문서 기반으로 적재돼
있는데, `case_history`만 2026-08-14 기준 **수동으로 작성한 골든데이터 10건**이 전부다.

- 데이터 위치: `apps/ai/app/rag/golden_cases.py`(10건, 시연/개발용으로 명시된 예시 — 실제 회계
  담당자 결정이 아님)
- 적재 명령: `python -m app.rag.case_store --upsert` (컨테이너 내부, 운영 배치처럼 `--peek`도 지원)
- 이렇게 된 이유: `search_cases`(Risk Review 2차 RAG 검증이 근거로 쓰는 유사사례 검색)가 컬렉션이
  완전히 비어 있으면 항상 빈 리스트만 반환해 이 검증 경로가 "죽은 경로"가 된다 — 그걸 막기 위한
  임시조치였다. 근본 해결(실 `RiskReview`/`Settlement` 결정이력을 정기적으로 임베딩·upsert하는
  배치)은 미착수.
- 실 결정이력 적재 파이프라인이 생기면 `golden_cases.py`는 폐기 대상.

## 참고: 다른 3개 컬렉션 적재 현황 (같은 시점 실측)

| 컬렉션 | 건수 | 적재 경로 |
|---|---|---|
| `policy_docs` | 103건 | `app/rag/embedding/index.py`(운영 배치, docling 파싱 결과) |
| `tax_refs` | 730건 | 위와 동일 |
| `org_docs` | 55건 | 위와 동일 |
| `case_history` | 10건 | 위 "핵심 사실" 참조 — 수동 골든데이터 |

## 관련 코드

- `apps/ai/app/rag/case_store.py` — `case_history` 컬렉션 upsert/search 구현
- `apps/ai/app/rag/golden_cases.py` — 골든데이터 10건 원본
- `apps/ai/app/mcp/tools.py::search_cases` — 이 컬렉션을 실제로 호출하는 FastMCP tool
