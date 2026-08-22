# AI-LAB — AI 기능 독립 실행 화면 (관리자)

> 파생 컨텍스트. 권위 스펙(요구사항·기술·기획)에 없는 **개발/운영 도구**이며, 정산 상태머신·판정 결과에
> 아무 영향을 주지 않는다. 화면설계서 S-01~06 밖의 부가 화면이다.

## 1. 왜 만들었나

AI 기능(Draft Agent·RAG 검색·임베딩)을 확인하려면 지금까지는 **정산 등록 화면을 타고 들어가야** 했다.
그러면 두 가지가 섞인다 — 기능이 잘못된 것인지, 그 앞의 입력·상태·권한이 잘못된 것인지.
AI-LAB은 그 앞단을 전부 걷어내고 **AI 기능만 단독으로** 돌린다.

원칙 셋:

1. **운영과 같은 코드를 부른다.** 실험 전용 구현을 두지 않는다 — 결과가 갈리는 순간 실험이 값을 잃는다.
2. **결과가 아니라 근거를 보여준다.** 모델·프롬프트 전문·LLM 원본 출력·토큰·지연·정책 조회 출처,
   검색이면 점수·인용·메타데이터·부모 확장까지 그대로 편다.
3. **실패를 감추지 않는다.** 정산 경로의 `draft-suggest`는 폴백이 목적이지만(사용자는 초안을 받아야 한다),
   여기서는 진단이 목적이므로 상태코드·오류 문구를 그대로 올린다.

## 2. 구성

| 탭 | 무엇을 하나 | 호출 |
|---|---|---|
| 상태 점검 | OpenAI 키·Chroma 적재량·Core 연결·이상탐지 모델 학습 여부 | `GET /lab/status` |
| ① Draft Agent | 생성/수정 모드 단독 실행. 폼 또는 요청 JSON 직접 편집, 세션 실행 이력, 생성→수정 연쇄 | `POST /lab/draft/run` |
| ② Rule Agent | RAG→LLM 노드 초안→결정론적 조립을 단독 실행. **부작용 있음**(Django에 실제 RuleGraph DRAFT 생성 — dry-run 경로 없음, 실행 전 확인 팝업으로 고지) | `POST /lab/rule/generate` |
| ③ Risk Review | 1차 이상탐지(`get_tx_features`+`ml_infer`) → 2차 RAG 내규 검증을 정산 id로 단독 실행. 부작용 없음(FastAPI는 Postgres에 쓰지 않는다) | `POST /lab/risk/run` |
| 증빙자료 추출 | 첨부 문서(사전승인·회의록·출장계획서·영수증) 판독을 단독 실행. **새 파일을 직접 올릴 수 없다**(ai 컨테이너는 media 볼륨을 읽기전용 마운트) — 이미 업로드된 파일의 `fileRef`를 입력받는다 | `POST /lab/extract/run` |
| RAG 검색 | 질의 → 조문 단위 히트. top-K·부모 확장·질의 접두(Q_ctx) on/off | `POST /lab/rag/search` |
| 임베딩 인스펙터 | 문장 → 벡터·cosine 유사도 행렬. "임베딩 문제인가 적재 문제인가"를 가른다 | `POST /lab/rag/embed` |
| 적재 현황 | 컬렉션별 건수·임베딩 신원(혼입 경고), 적재된 청크 원본 열람 | `GET /lab/rag/collections[/{name}/sample]` |

**미착수 기능 없음(2026-08-21)** — Draft·Rule·Risk Review·증빙자료 추출 4개 Agent 모두 단독
실행 탭을 갖췄다. Rule Agent·증빙자료 추출은 원칙 ①("운영과 같은 코드를 부른다")을 지키다 보니
다른 탭과 성격이 다르다: **Rule Agent는 부작용이 있고**(그 자체가 "그래프 저장"이라 dry-run이
없다), **증빙자료 추출은 이 화면에서 파일을 직접 못 올린다**(media 볼륨 읽기전용 — RAG 검색
탭의 "Chroma 적재가 선행돼야 한다"와 같은 종류의 제약). 새 기능이 stub 상태로 남으면 그때
"예정" 표시를 다시 쓴다.

## 3. 경로와 인가

```
브라우저 → Django  /api/ai-lab/<subpath>   (AiLabProxyView · Capability `ai_lab`)
        → FastAPI /lab/<subpath>          (app/api/lab.py)
```

FastAPI는 내부 전용이므로 관리자 화면도 Django를 거친다(CLAUDE.md §1). 프록시는 **인가와 전달만** 하고
응답을 가공하지 않는다 — 화면이 보는 것과 FastAPI가 낸 것이 달라지면 도구로서 값을 잃는다.

인가는 새 Capability **`ai_lab`**. 프롬프트·모델 내부가 그대로 보이고 LLM 호출 비용이 나가므로
역할 기본값은 **회계팀장(ACCOUNTANT_LEAD)** 만 갖고, 나머지는 Django admin의 `extra_capabilities`로
개별 부여한다(슈퍼유저는 항상 보유). `Capability`는 모델 필드가 아니라 JSON 리스트의 값이라 마이그레이션이 없다.

## 4. 실행 추적(trace)은 어떻게 모으나

`draft_agent.run/revise(req, trace=None)` — **선택적 dict 인자**로 받는다. 반환값에 섞지 않는 이유는
운영 응답 셰이프를 건드리지 않기 위해서다. `trace`가 None이면 수집 코드는 전부 무동작이라 운영 경로는 그대로다.

수집 항목: `model`·`temperature`·`systemPrompt`·`userPrompt`(실제 전송값)·`rawOutput`(Structured Output
원본 JSON 문자열)·`refusal`·`finishReason`·`usage`(토큰)·`latencyMs`(LLM)·`totalMs`(전체)·
`policy`(Django 실조회인지 폴백인지 + 이유)·`error`/`fallbackUsed`.

## 5. 기능을 추가하려면

1. `apps/ai/app/api/lab.py`에 `/lab/<기능>/...` 라우트를 더한다(운영 코드를 호출, 실패는 `_fail()`로 문장화).
2. `apps/web/src/screens/ai-lab/`에 패널 컴포넌트를 만들고 `AiLab.tsx`의 `MODULES` 배열에 한 줄 추가한다.
3. 호출은 `data/labApi.ts`에 추가한다(경로는 `/ai-lab/...` — Django 프록시가 그대로 흘린다).
4. Django는 손댈 필요가 없다(프록시가 subpath를 통과시킨다).

## 6. 알려진 한계

- **mock 모드 없음.** 실제 core·ai가 떠 있어야 한다(`VITE_USE_MOCK=true`여도 실 API를 호출한다).
- **비용이 나간다.** Draft 실행·임베딩·검색 질의는 매번 OpenAI를 부른다. 캐시하지 않는다(같은 입력의
  재현성을 보려면 같은 값이 다시 나오는지 봐야 하므로).
- **RAG 탭은 Chroma 적재가 선행**되어야 한다. 비어 있으면 히트 0건이 정상 동작이다 —
  `python -m app.rag.embedding.index --dump ../../docling_eval/output`(관리자 배치)이 아직 미착수 상태다.
- 검색·임베딩은 적재된 벡터와 **차원이 같아야** 하므로 모델·차원 스위치는 노출하지 않는다(질의 접두만 토글).
