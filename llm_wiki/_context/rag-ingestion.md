# 규정 문서 적재 파이프라인 — 구현 캐논

> 최종 갱신: 2026-08-14 · 상태: **적재 구현 완료 / 룰 자동 생성 트리거는 틀만**
> 권위 스펙: `docs/기술명세서.md §4.2·§6.1·§6.2` · 전략 캐논 `pdf_parsing_strategy.md` ·
> `chunking-strategy.md` · `embedding-strategy.md`

사용자가 자사 규정 PDF를 올리면 AI가 검색할 수 있게 만드는 경로. **Rule Agent의 앞단**이다
(룰은 사전 탑재하지 않고 고객 규정에서 생성한다 — CLAUDE.md §2).

---

## 1. 흐름

```
[브라우저] 규정 문서 관리 화면 (capability rule_view)
   │ multipart POST /api/policy-docs/   (PDF)
   ▼
[core] 파일 저장(media) + PolicyDoc(status=PENDING) 생성
   │ POST {AI}/embeddings/ingest {policyDocId, filePath, name, ruleScope}
   ▼ 202 즉시 반환
[ai]  BackgroundTasks
   │  ① 파싱   engine.convert(pdf)            docling + pypdfium2 2단 폴백
   │  ② 교정   corrections.pipeline.run(doc)  C1~C7, 프로파일별 계획
   │  ③ 청킹   chunk_document(doc)            조(條) 단위, 표는 독립 청크
   │  ④ 임베딩 store.upsert_chunks(...)       3-large@1024, 프로파일→컬렉션 라우팅
   │  ⑤ 트리거 rule_trigger.trigger(...)      ← 지금은 "개발 중" 안내만
   │ POST /api/internal/policy-docs/{id}/ingest-result/   (서비스 계정 JWT)
   ▼
[core] PolicyDoc.status = DONE|FAILED + 청크수·컬렉션·오류·트리거결과
   ▲
[브라우저] 목록 폴링(4초) — 진행 중 문서가 있을 때만
```

**컬렉션 라우팅**은 파서가 판정한 프로파일이 정한다(`embedding/config.COLLECTION_OF`):
`REGULATION|GENERIC → policy_docs` · `LAW → tax_refs` · `DIAGRAM → org_docs`.
`org_docs`는 **판정 근거로 검색되지 않는다** — 조직도가 정산 판정에 인용되면 안 되고,
결재선의 SoR은 문서가 아니라 Django다. 화면은 이 경우 "판정 미인용"을 표시한다.

---

## 2. 설계 결정

| # | 결정 | 근거 |
|---|---|---|
| I-1 | **파이프라인은 함수 하나**(`rag/ingest.py: ingest_pdf`) | 단계 로직은 이미 다 있었는데 **디스크 파일로만 이어져 있었다** — 파싱 CLI가 JSON을 떨구고 임베딩 CLI가 그걸 읽는 구조라 업로드된 파일 하나를 끝까지 밀 수 없었다. 사본을 만들지 않고 기존 함수를 호출만 한다(CLI 경로와 결과가 갈라지지 않게) |
| I-2 | **동기 아님 · 큐도 아님 — `BackgroundTasks` + 상태 폴링** | 동기는 불가: docling이 모델을 올리고 문서당 수십 초~분이라 브라우저(와 nginx)가 먼저 끊는다. 큐는 과함: 실제 부하가 "관리자가 가끔 규정 몇 종"인데 브로커+워커 컨테이너를 들이고 기술명세서 §6.2 "동기 REST · 별도 Job 큐 없음"을 뒤집어야 한다. 대신 진행 상태를 DB에 둬 화면이 실제 상태를 본다 |
| I-3 | **파일은 볼륨 공유, 바이트를 HTTP로 넘기지 않는다** | docling이 파일 경로를 요구한다. core의 `media` 볼륨을 ai에 `:ro`로 마운트(`RAG_MEDIA_ROOT=/data/media`) — 파싱 덤프를 `/data/docling_eval:ro`로 넘기는 기존 관례와 같다. **파일의 SoR은 Django**이고 ai는 읽기만 한다 |
| I-4 | **콜백은 인증된 쓰기** | 다른 내부 API(`PolicyLookupView`·`RuleContextView`)는 AllowAny지만 그건 read다. 적재 결과 회신은 쓰기라 열어두면 외부에서 상태를 조작할 수 있다 → 룰 에이전트와 같은 서비스 계정 JWT. 토큰 발급·갱신을 `clients/core_auth.py`로 공용화 |
| I-5 | **인가는 `rule_view`** | 규정은 룰의 원천이고, 적재는 임베딩 비용을 쓰면서 **모든 판정이 인용하는 코퍼스**를 바꾼다. 회계 담당자(`acc`)·회계팀장(`acclead`) 모두 역할 기본으로 갖는다 |
| I-6 | **PDF만 접수** | 파싱 파이프라인이 PDF 전용이다. 다른 확장자를 받아 두면 적재가 백그라운드에서 조용히 실패한다 — 접수 단계에서 막아 사용자가 즉시 안다 |
| I-7 | **실패해도 파일은 남긴다** | ai가 안 떠 있다고 업로드를 되돌리면 사용자는 올린 걸 또 올려야 한다. `FAILED`로 두고 "재색인"으로 복구 |
| I-8 | **경고는 실패가 아니지만 보여준다** | 판정 미인용 컬렉션·파싱 경고 등을 `error` 필드에 담아 화면에 띄운다. 조용히 삼키면 "왜 검색이 안 되지"가 된다 |

### 알고 쓰는 한계

`BackgroundTasks`는 ai 프로세스 안에서 돈다. **uvicorn이 재시작되면 진행 중 적재는 사라지고**
문서는 `PARSING`/`INDEXING`에 멈춘다(dev는 `--reload`라 파일 저장만 해도). 복구는 사람이
"재색인"을 누르는 것이고, 관리자 온디맨드 배치라는 전제와 일관된 회복 경로다. 규모가 커지면
`_run`을 큐 작업으로 바꾸면 된다 — 호출 계약(`POST /embeddings/ingest`)은 그대로 둘 수 있다.

`doc_id`가 **파일 내용 해시**라 같은 파일 재색인은 같은 ID로 덮어쓴다(멱등). 다만 **파일이
바뀌면 doc_id도 바뀌므로 옛 청크가 Chroma에 남는다** — 개정판을 올릴 때 구판 청크 정리는
아직 없다(아래 §4).

---

## 3. 룰 자동 생성 트리거 — 틀만 있는 상태

`rag/rule_trigger.py`. 호출은 되고 **"개발 중" 안내를 반환**하며, 그 값이
`PolicyDoc.rule_trigger`에 저장돼 화면에 그대로 뜬다.

**순서 의존이 이 자리의 존재 이유다**: 적재가 끝난 뒤에 불려야 한다. 그 전이면
`search_policy`가 0건이라 Rule Agent가 `NO_SOURCE`로 조용히 끝난다. 적재와 같은
백그라운드 태스크가 체인 전체를 소유하므로 순서가 공짜로 보장된다 — 이벤트로 각자
구독했다면 순서 보장이 곧 우리 문제가 됐을 것이다.

**켤 때 정해야 할 것 2가지** (둘 다 제품 판단이라 코드로 정하지 않았다):
1. **범위** — 업로드 시 고른 scope 1개만? 문서에서 탐지된 전 scope? 후자는 LLM 호출이
   곱절이 되고 아무도 요청하지 않은 DRAFT가 쌓인다.
2. **재색인 때도 돌릴지** — 매번 새 계열이 생기면 룰 콘솔이 초안으로 뒤덮인다. 기존
   계열에 버전을 얹는 경로(`POST /api/rules/{id}/versions` 오케스트레이션)가 선행돼야 한다.

켜는 방법은 `rule_trigger.py` docstring에 코드 스니펫으로 남겨뒀다.

---

## 4. 남은 것

| 갭 | 내용 |
|---|---|
| 개정판 구청크 정리 | 파일이 바뀌면 `doc_id`가 바뀌어 옛 청크가 Chroma에 남는다. `PolicyDoc` 삭제·재업로드 시 이전 `doc_id`의 청크를 지우는 경로 필요 |
| 문서 삭제 시 벡터 미삭제 | `DELETE /api/policy-docs/{id}/`는 메타·파일만 지운다(화면에도 명시). Chroma 삭제는 위 항목과 함께 |
| 진행률 | `PARSING`/`INDEXING` 두 단계만 안다. 페이지·청크 단위 진행률은 없다 |
| 재시작 유실 복구 | 멈춘 문서를 자동으로 되살리지 않는다(사람이 재색인). 시작 시 `PARSING`/`INDEXING` 잔류 건을 `FAILED`로 내리는 정리 작업이 있으면 더 명확해진다 |
| 동시 업로드 | docling 컨버터는 프로세스당 하나를 공유(락)한다. 여러 문서를 동시에 올리면 순차 처리된다 — 의도된 동작이지만 대기 시간이 화면에 안 보인다 |
