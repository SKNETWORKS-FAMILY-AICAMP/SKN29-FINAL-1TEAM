# 규정 문서 적재 파이프라인 — 구현 캐논

> 최종 갱신: 2026-08-16 · 상태: **적재·룰 자동 생성 트리거 모두 구현 완료**
> (트리거는 `feature/rule-agent-v1`에서 실구현됐다 — 상세 `rule-agent-v1-implementation.md`)
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
   │ POST {AI}/embeddings/ingest {policyDocId, filePath, name, ruleScope, isReindex}
   ▼ 202 즉시 반환                                  ↑ create=false / reembed=true
[ai]  BackgroundTasks
   │  ① 파싱   engine.convert(pdf)            docling + pypdfium2 2단 폴백
   │  ② 교정   corrections.pipeline.run(doc)  C1~C7, 프로파일별 계획
   │  ③ 청킹   chunk_document(doc)            조(條) 단위, 표는 독립 청크
   │  ④ 임베딩 store.upsert_chunks(...)       3-large@1024, 프로파일→컬렉션 라우팅
   │  ⑤ 트리거 rule_trigger.trigger(...)      rule_agent.generate() 실호출(최초 적재 한정)
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

## 3. 룰 자동 생성 트리거 — 구현 완료

`rag/rule_trigger.py`가 적재 완료 후 `rule_agent.generate()`를 **실제로 호출**한다.
결과(성공이든 실패든)는 `PolicyDoc.rule_trigger`에 저장돼 규정 문서 화면에 그대로 뜬다.

**순서 의존이 이 자리의 존재 이유다**: 적재가 끝난 뒤에 불려야 한다. 그 전이면
`search_policy`가 0건이라 Rule Agent가 `NO_SOURCE`로 조용히 끝난다. 적재와 같은
백그라운드 태스크가 체인 전체를 소유하므로 순서가 공짜로 보장된다 — 이벤트로 각자
구독했다면 순서 보장이 곧 우리 문제가 됐을 것이다.

**미결이던 2건은 이렇게 확정됐다** (`rule-agent-v1-implementation.md` §0.1 항목2):

| 결정 | 값 | 왜 |
|---|---|---|
| 생성 범위 | **업로드 시 고른 scope 1개만** | 문서에서 탐지된 전 scope를 만들면 LLM 호출이 곱절이 되고 아무도 요청하지 않은 DRAFT가 쌓인다. scope 미지정이면 `SKIPPED_NO_SCOPE`로 건너뛴다 |
| 재색인 | **자동 생성 안 함** (`SKIPPED_REINDEX`) | 같은 문서를 다시 넣을 때마다 새 계열이 생기면 룰 콘솔이 초안으로 뒤덮인다. 기존 계열에 버전을 얹는 경로가 아직 없다 |

최초 업로드인지 재색인인지는 Django가 안다 — `policy_doc_views._dispatch(doc, is_reindex=)`가
`create`/`reembed` 경로를 보고 `isReindex`로 넘기고, ai의 `IngestRequest.isReindex`가 받는다.

**트리거 실패는 적재를 실패로 만들지 않는다.** 문서는 이미 검색 가능한 상태이고, 룰 생성은
룰 콘솔에서 수동으로 다시 시도할 수 있다. 상태값은 뭉개지 않고 `generate()`의 것
(`DRAFT_SAVED`/`NO_SOURCE`/`NO_VALID_NODES_EXHAUSTED`/`STRUCTURE_INVALID_EXHAUSTED`)을 그대로 노출한다.

---

## 3a. 조항(Clause) 도메인 — 화면이 보는 단위

목업 S-05 v4가 요구한 것은 "문서 목록"이 아니라 **조(條)별로 무엇이 규칙과 연결됐고
무엇을 확인해야 하는가**다. 그래서 적재가 끝나면 청크를 조 단위로 다시 모아
`PolicyClause`로 저장한다(`ingest.build_clauses`).

| 무엇 | 어디 | 왜 |
|---|---|---|
| 조항 본문·인용 | Postgres `policy_clauses` | Chroma에도 있지만 그건 **검색용 사본**이다. 조항은 사람이 "규칙으로 만들지 않겠다"고 **결정을 내리는 대상**이라 그 결정을 붙일 자리가 SoR에 있어야 한다 |
| 본문 원천 | 부모 청크(조 전문) 우선, 없으면 잎 이어붙임 | 잎만 이으면 항이 잘린 자리의 문맥이 어긋난다 |
| 조에 안 속한 청크(별표 등) | 조항 행이 되지 않음 | 검색에는 그대로 걸린다. 몇 개가 그랬는지 경고로 세어 노출(조용한 누락 방지) |

**상태는 저장하지 않는다.** `LINKED / SKIPPED / NEEDS_REVIEW` 중 둘이 파생이다:

```
LINKED       ← RuleNode.action.source_clause == clause.citation 인 노드가 있다
SKIPPED      ← 사람이 decision=SKIP + 사유를 남겼다   (유일한 저장값)
NEEDS_REVIEW ← 그 외
```

룰은 나중에 생기고 나중에 지워진다. 상태를 컬럼에 굳히면 곧 실제와 어긋나므로
`PolicyClause.rule_status()`가 조회 시점에 계산한다. 연결을 FK가 아니라 **인용 문자열
매칭**으로 찾는 이유도 같다 — 룰 노드는 Agent가 만들 수도 사람이 만들 수도 있고,
조항 행이 생기기 전에 만들어졌을 수도 있다.

**재색인은 사람의 결정을 지운다 → 안 지우게 했다.** 조 라벨이 같으면 같은 조항으로 보고
`decision`·사유·결정자를 옮긴다(`_replace_clauses`). 재색인은 흔한 일이라(청킹 전략 변경·
파싱 개선) 그때마다 판단이 날아가면 같은 검토를 반복하게 된다.

**`SKIP`은 사유가 필수다.** 나중에 "왜 이 조항엔 규칙이 없지"를 묻는 사람이 반드시
나오고, 그때 답이 없으면 검토를 처음부터 다시 한다.

### 문서 유형(`profile`) = 사용자가 지정할 수 있는 유일한 라우팅 축

파서가 자동 판정하지만 **업로드 시 지정하면 그 값이 이긴다**(`PolicyDoc.profile_hint` →
`ingest_pdf(profile_hint=)`). 교정·청킹이 프로파일별로 갈리므로 교정 **전에** 덮어쓰고,
덮어썼다는 사실은 적재 경고로 남아 화면에 뜬다.

지정을 열어 둔 이유는 이 값이 곧 **컬렉션 라우팅**이고, 컬렉션이 "판정에 인용되는가"를
정하기 때문이다 — `DIAGRAM`으로 잘못 잡히면 그 규정은 `org_docs`로 가서 정산 판정이
영원히 못 본다. 파서가 도해 위주 문서에서 실제로 흔들린다는 실측도 있다(파싱 전략 §회귀).

### 폴더(`PolicyFolder`) — 검색과 무관한 사람용 분류

만들기·이름 변경·삭제·문서 드래그 이동을 지원한다. **삭제는 비어 있을 때만** 허용한다 —
문서는 `SET_NULL`이라 미분류로 살아남지만 하위 폴더는 `CASCADE`라, 한 번의 클릭으로
정리해 둔 분류가 통째로 사라지는 걸 막는다. 폴더 액션은 `POST /policy-docs/folders/{id}/`
(이름 변경)·`DELETE`다 — PATCH를 열면 ViewSet의 `partial_update`까지 함께 열려 문서 필드가
검토 없이 수정 가능해진다.

### 원본 PDF 서빙 — `GET /api/policy-docs/{id}/file/`

`MEDIA_URL`로 직접 노출하지 않는다. 이유가 둘이고 **둘 다 독립적으로 충분하다**:
① 목록·조항이 `rule_view`를 요구하는데 원본만 무인증으로 열리면 그 통제가 무의미하다
(규정 원문은 사내 문서다). ② nginx는 `/`를 web(SPA)으로 보내고 core로 가는 건 `/api/`뿐이라
`MEDIA_URL`을 열어도 브라우저에서 core에 닿지 않는다.

기본 `inline`(「원본 보기」가 **새 탭**으로 열어 브라우저 내장 뷰어에 맡긴다 — 페이지 이동·
확대·검색·인쇄가 거기 다 있어 우리가 다시 만들 이유가 없다), `?download=1`이면 `attachment`.
파일이 볼륨에서 사라진 경우 빈 화면 대신 404 + 사유를 준다.

**`inline` + 사용자 업로드 파일은 저장형 XSS의 고전 조합**이라 두 겹으로 막았다:
① 업로드 시 **매직바이트 검사**(`%PDF-`) — 확장자는 이름일 뿐이라 `.pdf`로 위장한 HTML이
들어올 수 있다. ② 응답에 **`X-Content-Type-Options: nosniff`** — 브라우저가 우리가 보낸
Content-Type을 무시하고 내용을 스니핑해 HTML로 렌더하면 그 스크립트가 **이 앱의 오리진**에서
돈다. 남은 위험은 §4 참조.

### 화면 (S-05 v4)

좌: 폴더 트리(`PolicyFolder`, 자기참조) / 우: 선택 문서의 조항 아코디언.
목업 **하단의 "확인 필요(3)" 노란 박스는 제외**했다 — 같은 정보가 우측 조항 카드에
이미 있고(확인 필요 배지 + 결정 버튼), 두 곳에서 같은 결정을 내릴 수 있으면 어느 쪽이
최신인지 알 수 없게 된다.

「규칙 생성하기」는 여기서 룰을 만들지 않고 **룰 콘솔로 넘긴다** — 생성의 주인은 룰
콘솔이고, 두 번째 생성 경로를 만들면 생성 이력·검증 흐름이 갈라진다.

---

## 3b. docling 모킹 (`DOCLING_MOCK`) — 개발 전용 스위치

docling은 모델을 올리고(문서당 수십 초~분) 버전 드리프트에 민감하다. 파싱이 깨지면 그
뒤 체인(교정→청킹→임베딩→적재→조항→룰 트리거) **전체를 시험할 방법이 없어진다.**
`DOCLING_MOCK=1`이면 **파싱 단계만** 미리 떠둔 덤프(`docling_eval/output`, 11종 4,388요소)로
대체한다.

```
DOCLING_MOCK=1
DOCLING_MOCK_DUMP=/data/docling_eval/output     # 기본값. compose가 :ro로 마운트한다
```

**왜 이 모킹이 위험하지 않은가 — 새 코드 경로가 아니다.** `dump.load_all()`은 이미
`ParsedDoc`을 돌려주고(운영 `engine.convert()`와 **같은 타입**), 관리자 CLI
(`embedding/index.py`)가 이미 그 경로로 청킹·임베딩을 돌린다. 그래서 갈아끼우는 지점은
`ingest.ingest_pdf()`의 **분기 한 곳**이고, 파싱 이후는 운영과 같은 코드를 지난다.
모든 로직은 `rag/parsing/mock.py` 한 파일에 격리돼 있어 스위치를 지우면 통째로 사라진다.

**진짜 위험은 파싱이 아니라 "켜둔 걸 잊는 것"** 이라 거기에 방어를 걸었다:

| 안전장치 | 내용 |
|---|---|
| 매번 WARNING 로그 | 어떤 요청이 어떤 덤프로 갔는지 `logs/ai.log`에 남는다 |
| 화면 배너 | 경고가 `PolicyDoc.error`로 흘러 규정 문서 화면에 노란 배너로 뜬다(경고 목록 **맨 앞**에 넣어 잘리지 않게) |
| `dump:` doc_id | 모킹 벡터는 `dump:<문서명>`, 실물은 파일 해시 — Chroma에서 눈으로 구분되고 나중에 골라낼 수 있다 |
| **넘겨짚기 금지** | 이름이 정확히 안 맞으면 **실패**시킨다. 실제 docling으로 조용히 폴백하지 않고, 접두사·부분 일치도 쓰지 않는다 — 넘겨짚으면 A 문서 내용이 B 레코드에 적재되는 **조용한 오염**이 된다. 실패 메시지가 고를 수 있는 이름 11종을 알려준다 |
| 정규화만 허용 | NFC 통일 + 공백/대소문자만 정규화한다(macOS 한글 파일명 NFD 함정). 유사도 매칭이 아니다 |

⚠️ 모킹 중에는 **업로드한 파일 내용이 무시된다** — 이름만 보고 덤프를 고른다. 그게 목적이지만
운영에서 켜면 안 되는 이유이기도 하다. 기본값은 꺼짐이고, `0`/`false`/`no`/빈 값 전부 꺼짐이다.

📏 실측(모킹 경로로 조항 추출까지): 법인카드_사용규정 25청크·**20조항** / 회식_운영규정
31청크·**14조항** / 법인세법 425청크·**207조항**(LAW→`tax_refs` 라우팅 확인).
회귀 `apps/ai/tests/test_docling_mock.py`(덤프 없으면 skip).

---

## 4. 남은 것

| 갭 | 내용 |
|---|---|
| 개정판 구청크 정리 | 파일이 바뀌면 `doc_id`가 바뀌어 옛 청크가 Chroma에 남는다. `PolicyDoc` 삭제·재업로드 시 이전 `doc_id`의 청크를 지우는 경로 필요 |
| 문서 삭제 시 벡터 미삭제 | `DELETE /api/policy-docs/{id}/`는 메타·파일만 지운다(화면에도 명시). Chroma 삭제는 위 항목과 함께 |
| 진행률 | `PARSING`/`INDEXING` 두 단계만 안다. 페이지·청크 단위 진행률은 없다 |
| 재시작 유실 복구 | 멈춘 문서를 자동으로 되살리지 않는다(사람이 재색인). 시작 시 `PARSING`/`INDEXING` 잔류 건을 `FAILED`로 내리는 정리 작업이 있으면 더 명확해진다 |
| 동시 업로드 | docling 컨버터는 프로세스당 하나를 공유(락)한다. 여러 문서를 동시에 올리면 순차 처리된다 — 의도된 동작이지만 대기 시간이 화면에 안 보인다 |
| 폴더 자동 분류 없음 | `PolicyFolder`는 사람이 만들고 옮긴다(admin 또는 `POST /folders/`·`/move/`). 업로드 시 폴더를 고르는 UI는 아직 없다 — 지금은 업로드 후 이동 |
| `superseded_by` 미배선 | 모델·배지("이전 버전")는 있으나 개정판 업로드 시 구판을 가리키는 UI·API가 없다. 지금은 admin에서 지정 |
| **원본 서빙 — 같은 오리진** | PDF는 그 자체가 실행 가능한 포맷이다(임베디드 JS·자동 링크). 내장 뷰어가 샌드박싱하지만, 별도 오리진(`files.example.com`)이나 `Content-Security-Policy: sandbox`로 한 겹 더 떼어놓는 게 정석이다. CSP를 잘못 걸면 뷰어 렌더가 깨질 수 있어 실측 없이 넣지 않았다 |
| **원본 서빙 — 문서 단위 인가 없음** | `rule_view`만 있으면 **모든 문서**를 읽는다. 규정은 전사 공통 문서라 현재는 맞지만, 팀·부서 한정 문서가 생기면 문서 단위 스코프가 필요하다 |
| **원본 서빙 — Django가 바이트를 흘린다** | `FileResponse`가 워커를 점유한다. 운영에서는 nginx `X-Accel-Redirect`(internal location)로 넘겨 인가만 Django가 하고 전송은 nginx가 하는 게 맞다. 50MB 업로드를 허용해 뒀으므로 더 그렇다 |
| 조항 ↔ 룰 연결이 문자열 매칭 | `RuleNode.action.source_clause`와 `citation` 문자열이 정확히 같아야 연결된다. Rule Agent가 `search_policy`의 citation을 그대로 복사하도록 프롬프트가 지시하고 있어 현재는 맞지만, 사람이 손으로 쓴 노드는 어긋날 수 있다 |
