# CLAUDE.md — 팀 공용 컨텍스트

> Hybrid AI 기반 **법인카드 정산 자동화 플랫폼** (가상기업 "타이거 주식회사" 페르소나).
> 정산 업무(입력→검토→확정→정책결정)를 3개 AI Agent(초안 작성 / Rule / Risk Review) + 사람 최종 확정으로 자동화한다.
> 이 파일은 매 세션 자동 로드된다. **간결하게 유지**하고, 큰 변경 시 아래 "상태 보드"를 갱신할 것.

---

## 1. 저장소 구조

```
apps/
  web/      React + Vite + TS (SPA) — 6개 역할별 화면
  core/     Django + DRF — System of Record(SoR): 도메인·상태머신·RBAC·ERP전표(안)
  ai/       FastAPI — AI Orchestrator: 3-Agent + 단일 FastMCP 서버 + 비지도 이상탐지
infra/nginx/  리버스 프록시(/ → web, /api → core)
logs/         컨테이너 로그 바인드(core.log·ai.log) — git 미추적, 디버깅 시 여기부터 본다
docker-compose.yml  로컬 개발 오케스트레이션 (db·chroma·core·ai·web·nginx)
llm_wiki/     설계·기획 산출물(아래 §4)
tiger_inc/    RAG 소스 데이터 — §5 열람 규칙 주의
daily_scrum/  주차별 진행 보고
```

아키텍처 원칙(기술명세서 기준): **SoR은 Postgres 하나**(AI는 "제안"만, 확정은 Django 서비스 레이어) · **관계형=Django 경유 / 벡터=Chroma 직접**(LLM/Tool의 Postgres 직접 SQL 금지) · **FastAPI는 내부 전용**(사용자 트래픽은 Django만) · **동기 REST(MVP)**, 무거운 작업은 관리자 온디맨드 배치.

---

## 2. 핵심 설계 결정 (변경 시 세 문서 + 화면 모두 동기화)

- **Risk Review = MVP 2단계**: ① 단순 이상거래 탐지(비지도, anomaly_score) → ② RAG 내규 검증(이상 후보 한정). 지도학습(`review_probability`)·자동 재학습 피드백 루프는 **post-MVP 확장**. (콜드스타트/라벨부족 대응)
- **상태머신(FR-ST-01)** — 4단계: **① 개인 보유(`DRAFT`) → ② 팀 취합(`TEAM_COLLECTING`/`TEAM_RETURNED`/`TEAM_REJECTED`) → ③ 회계 제출·룰엔진(`SUBMITTED`/`RPA_JUDGED`) → ④ 회계 검토·확정(`PENDING_CONFIRM`/`RETURNED`/`IN_REVIEW`/`REJECT`/`CONFIRMED`/`ERP_VOUCHER_DRAFTED`)**. **팀 수준(`TEAM_*`, 팀장)과 회계 수준(`RETURNED`/`REJECT`, 회계)은 별개 상태**이고 `REJECT`=최종반려(재제출 불가). 제출은 2단계(`raise_to_team` → `submit`)이며 1인 팀도 같은 경로. 전이는 `settlements/services.py`에서만 하고 `SettlementEvent`+`audit_logs`에 남긴다. 🚧 `/submit` 팀 동일성 배치 강제는 미착수(요구사항 Open #8). (기술 §3.3)
- **예산·정책은 통제(차단)가 아니라 지표·추천으로만** 반영.
- **사람 확정 원칙**: 확신 통과 건도 회계 담당자 확정 없이는 CONFIRMED 불가.
- 영수증은 별도 OCR 없이 **OpenAI 비전**으로 직접 판독. Rule 적용은 결정론적 엔진, LLM은 Rule 생성 단계에서만.
- **가맹점 업종 = 정본 1곳**: 캐시(TTL 30일) → 카카오 원시조회 → **LLM이 우리 서비스 어휘로 재분류**(카카오 group code는 장소·마케팅 분류라 그대로 안 쓴다). 어휘 정본은 `domain/transactions/industry.py` 15종이고 ai는 미러 — 이 라벨이 곧 판정 사실 `merchant.merchant_type`이라 룰 DSL·금지업종 별표와 **같은 표기**여야 한다. **접히지 않으면 `기타`가 아니라 미확정**(`기타`로 밀면 별표가 "금지 아님"으로 단정한다). 비용분류 **보조 힌트**일 뿐 세무 판단이 아니고, MCC는 post-MVP. → `_context/merchant-industry-vocabulary.md` / 기술 §7-1
- **룰은 사전 탑재하지 않는다 — 기본 게이트 1개 + 문서에서 생성**: 제품이 미리 준비해 제공하는 것은 **`DEFAULT GATE` 하나**뿐이며, 특정 회사 규정에 종속되지 않는 **범용 default 룰**로 고도화한다. **카테고리별 세부 룰은 고객이 자사 규정 문서를 업로드하면 Rule Agent가 생성**한다(RAG 조항 추출 → 초안 → 시뮬레이션 → ACTIVE 승인). `docs/RULE_명세서.md`의 76 RULE과 `seed_rules`의 4개 계열 그래프는 **참고용 예시·시연용**이지 기본 제공물이 아니다.
- **룰 도메인 = 그래프(트리)**: 단건 룰은 `condition+action+next_routings` 노드, 조립된 **룰 그래프(RuleGraph)** 가 최종 상태 도메인. **ACTIVE·버전관리·시뮬레이션·롤백은 그래프 단위**. (기술 §3.1·§4.2 / 요구사항 FR-RB·FR-RV·FR-RA)
- **룰엔진 = 3단 파이프라인**: ① `build_rule_context(tx_id)`로 **EvalContext(facts 스냅샷)** 조립(모든 I/O·데이터 접근은 여기서만) → ② 그래프 선택(**필수 게이트 GLOBAL → 계정과목별 scope**) → ③ **결정론적 순회**(엔진은 EvalContext만 참조, 외부 I/O 0). 조건은 **JSON-Logic류 DSL**(임의코드 금지). context는 `rule_hits.eval_context`에 스냅샷 저장 → 재현·감사. 상세: `llm_wiki/_context/rule-engine.md`. (기술 §4.2(d) / 요구사항 FR-RA-08~10)
- **비용분류 어휘 = 서버가 내려준다**: 정본 `settlements.Category` 6종(회식·회의·식대·출장·접대·**기타**), 창구는 `GET /api/meta/categories/` 하나. 화면(`useCategories()`)·ai(`core_client.get_categories()`)가 런타임에 받아 쓰고 **저장 검증은 서버가 한다**(목록 밖 값은 400). **`기타` ≠ 미기재** — `기타`는 "어디에도 안 맞는다"는 확정, `""`는 "아직 못 정했다"(게이트가 `CATEGORY_MISSING`으로 잡는다). → `_context/category-vocabulary.md`
- **AI는 판정을 예측하지 않는다**: 「지금 제출하면 보완요청될까」는 결정론적 엔진이 이미 답을 갖고 있다(`orchestrator.judge(record=False)`). 룰 그래프를 프롬프트에 주고 순회를 흉내내게 하면 틀리고, 틀려도 티가 안 나며, 사용자에겐 "AI가 통과라 했는데 반려됨"이 된다. **엔진이 결정하고 모델은 사람 말로 옮긴다**(`narrate.py`·MCP `run_rule_engine`과 같은 분업). 모델이 낼 수 없어야 하는 값은 지시가 아니라 **출력 스키마에서 뺀다**. → `_context/draft-agent-v2.md`
- **인가 = 기능 단위(Capability) RBAC**: 역할이 아니라 6개 Capability(`team_aggregate`·`accounting_review`·`rule_view`·`rule_activate`·`governance_view`·`ai_lab`)로 판정. **유효능력 = 역할 기본값 ∪ 개인 추가부여(`users.extra_capabilities`)** — 예: `acc`=회계+룰열람+팀취합, `acclead`=회계+룰열람+룰활성. 룰콘솔은 열람(`rule_view`)/활성(`rule_activate`) 분리. DRF `HasCapability` 파생 권한으로 백엔드 강제, `/api/me`에 `capabilities` 노출, 프론트는 `useCan()`로 게이트. **Django admin에서 사용자별 `extra_capabilities` 체크박스 부여**. (기술 §3.1a)
- **EvalContext는 파생 불린을 두지 않고, 룰 조건에 상수를 허용한다**(v6) — 심야 22시 같은 기준을 조립기에 박으면 회사마다 다른 값을 바꾸려고 재배포해야 하고, 그 상수는 룰 콘솔에도 판정 스냅샷에도 안 보인다. 그래프가 `tx.payment_time >= "22:00"`으로 직접 비교한다(내규 개정은 잦지 않고 룰은 Rule Agent가 관리한다). **예외 셋만 조립기가 접는다** — ① null 여부(미해소 가드가 값 평가 전에 강등해 `x == null`을 룰로 못 쓴다) ② 별표 선해소(DSL에 룩업 연산자 없음 — 표로 개정되는 값은 그대로 별표다) ③ 산술·날짜(DSL에 연산자·요일 함수 없음). 남기는 불린은 **왜 예외인지를 필드 설명에 적는다**. → [[eval-context-sourcing]] §16
- **DSL에서 모름(null)은 어느 방향으로도 참을 만들지 않는다**(v6) — 비교·`in`·`not` 전부 거짓이고 `is_null`만이 예외다. 예전엔 연산자마다 달라(`!=`·`not(var)`가 모를 때 참) **틀리는 방향이 「조용한 위반 판정」**이었다(실측: T-21이 증빙 미확인 건에 「증빙 없음」 사유를 달았다). `is_null`이 감싼 경로는 **미해소 가드에서 면제**되지만(`dsl.guarded_vars`) 밖에도 나오면 유지하고, ACTIVE 전환 게이트는 그대로 전부 검사한다. **Rule Agent도 쓸 수 있다** — 처음엔 「가드 면제 + 미입력을 위반으로 단정」이 걱정돼 막으려 했으나, Agent가 만드는 노드는 `REJECT/RETURN/REVIEW`만 낼 수 있어(둘 다 사람에게 간다) 「모름을 근거로 통과」가 구조적으로 불가능하다. → [[eval-context-sourcing]] §17

---

## 3. 상태 보드 (Status Board) — _최종 갱신: 2026-08-24_

> **읽는 법**: 여기는 "지금 무엇이 되고 무엇이 안 되는가"만 적는다. **왜 그렇게 했는지·실측
> 수치·과거 결함의 서사는 `_context/` 캐논**에 있고 여기서는 가리키기만 한다(§4 규약).
> 의미 있는 진척마다 갱신하되 **행이 3줄을 넘으면 캐논으로 옮긴다.**

### 3.1 기반

| 영역 | 상태 | 비고 |
|---|---|---|
| 모노레포·부팅 | ✅ | `docker compose config` / `py_compile` 통과 |
| Django 도메인 모델 | ✅ | 8개 도메인·18개 테이블. 설계 `.personal/데이터베이스_저장소_설계문서.md` |
| Capability RBAC | ✅ | 6종 · `extra_capabilities` · `HasCapability` · `/api/me` · 프론트 `useCan()` |
| 프론트 6개 화면(S-01~06) | ✅ 빌드 통과 | 실 API 연동 상태는 §3.5 |
| 문서 3종 정합(Risk Review 2단계) | ✅ | 요구사항·기술·기획 + 화면설계서 일관 |

### 3.2 룰 도메인

| 영역 | 상태 | 비고 |
|---|---|---|
| 룰 그래프(트리) 도메인 | ✅ | scope별 버전·DRAFT 복제/원복·DSL 쉽게보기·검증 시뮬레이션·승인 흐름·롤백. 구조 시각화는 플로우차트(순환 감지) |
| 룰 엔진 판정 | ✅ | 게이트 우선(GLOBAL→scope) · 그래프당 `rule_hits` 1행 · **엔진은 최종반려를 만들지 않는다**(REJECT여도 상태는 RETURNED) · 제출이 판정을 이어 돌린다. → [[rule-engine]] |
| 네임드 플래그 | ✅ | 2계층(닫힌 `SystemFlag` / 열린 `RuleFlag`). **불변식: 플래그는 상태머신을 움직이지 않는다.** `code`는 데이터 계약. → [[rule-flags]] |
| EvalContext | ✅ v6 (56필드) | 원자 사실만, 판단은 그래프가 조합. 미해소 가드(`UNRESOLVED_*`) → REVIEW 강등. 파생 불린 4건 제거·상수는 룰에 허용(§2). **참석 인원은 신고(화면)와 확인(문서 추출)을 다른 필드로 가른다**. **값 어휘(enum) 8경로**는 서버 정본에서 나와 별표 축·증빙 추출을 같이 제약한다. `dining.gathering_unit`·`gathering_type`은 **증빙 서식에서만** 오고 저장 컬럼이 없다. → [[eval-context-sourcing]] §15~18 |
| 규정 임계값(policy) | ✅ 동적화 완료 | 저장층 `PolicyTable`(자유 JSON+`key_axes`) → 소비층 `ctx.policy.*`. **적재된 표에서 파생**(코드 상수 아님), `RESOLVERS`는 이름 override로만. 축 정합 검사(`check_table_axes`, DB 행 대조). → [[policy-domain]] §3 |
| 기본 게이트(DEFAULT GATE) | ✅ 정합 점검 완료 | 제품 기본 제공은 **이것 하나**. 기본 `REVIEW`+사유, `PASS`는 화이트리스트, `RETURN`/`REJECT` 안 냄. **자동 통과 요건은 가드에 맡기지 않고 화이트리스트에 적는다**(맡겼더니 실사용자 `False` 건이 통과했다). → [[default-gate]] §4.1 |
| 판정 입력(사실) 조립 | 🚧 대부분 해소 | 이력 집계·영업일·근무시간을 채워 「룰이 참조하는데 미조립」이 4→1로 줄었다(남은 1은 `trip.*`, 첨부 추출은 되나 **화면 입력칸이 없다**). `finance_dept_is_spender`는 `Team.is_finance` 필요. → [[eval-context-sourcing]] §15 |

### 3.3 AI Agent

| 영역 | 상태 | 비고 |
|---|---|---|
| Draft Agent | ✅ v2 | 사실 주입(기본 내역·첨부 추출·EvalContext) + **엔진 dry-run 판정 미리보기**. 판정을 LLM이 예측하지 않는다. 모델이 낼 수 없는 것은 스키마에서 뺀다. → [[draft-agent-v2]] |
| Rule Agent (생성·대화·검증셋·서술) | ✅ 전 구간 | 규정 문서 → RAG → LLM 노드 → 결정론적 조립 → DRAFT 저장 → 구조검증 → 재시도. 대화형 수정·검증셋 자동생성·시뮬 보고서 서술 포함. **호출은 기존 DRAFT에 이어 붙인다** — 편집 중인 초안을 프롬프트에 실어 중복 생성을 막고, 구조검증이 실패해도 초안은 지우지 않고 이번에 만든 노드만 걷어낸다(호출마다 새 계열이 생기던 것 해소). → [[rule-agent-v1-implementation]] |
| Risk Review Agent | ✅ v2 (등급 분기) | 1차 이상탐지 → **등급이 2차를 가른다**: `LOW`=LLM 0회 고정 안내(「검사 안 함」을 명시) / `MEDIUM`=fast / `HIGH`·미측정=heavy. 2차 산출물은 **구조화 보고서**(요약·특징·근거+판단·추가안내) — 근거 id를 서버가 대조해 지어낸 인용을 버리고, 근거 없는 판단은 참고사항으로 강등한다. → [[risk-review-agent-v2]] · **보고서 `highlights`는 화면에 없는 것만** — 이력·신고vs확인 인원·업종 신뢰도·미해소 사실을 **코드가 골라**(`review_notables`) 모델은 문장만 옮긴다 |
| 증빙자료 추출 Agent | ✅ | 업로드가 곧 판독 트리거. 신뢰도 게이트 0.6 미만은 EvalContext에 안 올린다. → [[evidence-extraction-agent]] |
| 결정 사유 초안 Agent | ✅ | 선택지는 서버 정본, LLM은 문장. ai 없어도 플래그 설명으로 폴백. → [[settlement-ui-rules]] §5 |
| 에이전트 컨텍스트 툴 | ✅ P0 | 프롬프트용 도메인 카탈로그(DSL·경로+타입+설명·별표축·판정선택지·플래그)를 live 모델에서 조립. TTL 180s, 실패는 `stale` 명시(조용한 폴백 금지). **불변식: 프롬프트 블록과 검증 기준이 같은 `Bundle`에서 나온다.** → [[agent-context-tool]] |
| 가맹점 업종 구분 | ✅ Draft 연동 / 🔲 Risk 미연동 | 캐시→카카오→LLM 재분류. 어휘 정본 `transactions/industry.py` 15종. **미확정을 `기타`로 밀지 않는다.** → [[merchant-industry-vocabulary]] |
| AI-LAB (관리자 실험) | ✅ 8탭 | 운영과 **같은 코드**를 부르고 결과 대신 근거를 편다. Rule 탭은 실제 DRAFT가 생긴다(dry-run 없음). → [[ai-lab]] |
| 이상탐지 서빙 | ✅ 연동 / 🚧 재학습 필요 | `get_tx_features`+`ml_infer` 실동작. 배포 pkl에 `feature_stats`가 없어 **`feature_contribs`는 빈 배열**, sklearn 버전 불일치(1.8.0 vs 1.5.2) — 재학습 시 버전 고정 |

### 3.4 RAG

| 영역 | 상태 | 비고 |
|---|---|---|
| PDF 파싱 | ✅ P0/P1 | docling+pypdfium2 2단 폴백 → 프로파일 → 교정 C1~C7. 회귀 66건. **남음**: GT 재채점·자간 잔존(법령 341)·furniture 육안검수. → [[pdf_parsing_strategy]] |
| 파싱 품질 평가 | ✅ | GT 8종 정량 채점, 법령 3종은 N/A+검수 시트. **실측 Overall 89.3**. 산출물 `docling_eval/output/evaluation/` |
| 청킹 | ✅ | **자르는 단위는 조(條)**, 분할 사다리 조→항→호→문장→문자. 표는 독립 청크. 888청크·종합 98.5/100. → [[chunking-strategy]] |
| 임베딩 | ✅ 평가 완료 | `text-embedding-3-large` @ `dimensions=1024` 확정(MRR .906). ⚠️ 기준선 `bge-m3`가 .933으로 더 높다 — **재검토 트리거로 기록**. → [[embedding-strategy]] |
| 검색 재선별(LLM rerank) | ✅ | `rerank(query, hits, top_n)` — **「관련 없음」과 「호출 실패」를 구분**(실패는 원본 top_n으로 fail-open, 안 그러면 하류가 "근거가 원래 없었다"로 오인). Risk Review 2차는 항상 켠다. 회귀 7건 |
| 문서 업로드 → 적재 | ✅ | 업로드 → `PolicyDoc(PENDING)` → 백그라운드 파싱·청킹·임베딩·Chroma upsert → 룰 트리거 → 콜백. **한계**: ai 재시작 시 진행 중 작업 유실 → 「재색인」으로 복구. → [[rag-ingestion]] |
| 적재 → 룰 자동 생성 | ✅ | 업로드 시 고른 scope 1개만. scope 미지정=`SKIPPED_NO_SCOPE`, 재색인=`SKIPPED_REINDEX`. 트리거 실패가 적재를 실패시키지 않는다 |
| 문서 분류(triage) + 별표 승인 | ✅ + 별표 고도화 | 분류는 **제안이지 차단이 아니다**(SKIP에서도 룰 생성 가능). 우선순위는 조항 단건이 아니라 **문서 단위 선별**로 정한다(단건만 보면 전 조항이 「확인 필요」로 나왔다) — AUTO 상한·최소 1건은 코드가 강제. 별표 후보는 **별도 모델**이고 개정은 INSERT. 별표 추출은 **부모 청크로 조각을 합쳐**(페이지 분할 표) 맥락과 함께 읽고, **자동검사→재시도**를 거쳐 AI 코멘트·활용안내와 올라온다. 승인이 강제하는 건 축 + **값 어휘**(경로만 맞고 표기가 다르면 룩업이 조용히 `*`로 떨어진다). → [[document-triage]] |
| docling 모킹 스위치 | ✅ | `DOCLING_MOCK=1`이면 파싱만 덤프로 대체. **진짜 위험은 켠 걸 잊는 것** → WARNING 로그·노란 배너·`dump:` doc_id·이름 불일치 시 폴백 없이 실패 |
| 결정 사례(case_history) | ✅ 기틀 | **「다르게 판단한 것」만** 적재(일치 건까지 넣으면 봐야 할 예외가 밀린다). 본문은 스냅샷. **남음**: 골든/실사례 메타 구분·마스킹 정책·사례 목록 화면. → [[decision-case-data]] |
| Chroma 운영 적재 | 🚧 | 화면 업로드 경로는 동작. CLI 재적재는 `app.rag.embedding.index`(§6) |

### 3.5 화면 · 흐름

| 영역 | 상태 | 비고 |
|---|---|---|
| 화면·흐름 불변식 | ✅ 정리 완료 | 이상 건 정의 · 결정 버튼 세트 · 일괄승인 금지 · 사유를 받는 기준 · 저장 vs 파생 · 데이터 스코프 · 상태 기록 · 빈 자리 처리. **새 화면·버튼 만들기 전에 읽는다** → [[settlement-ui-rules]] |
| S-01 내 지출 | ✅ 실 연동 | 내역 불러오기(ERP 수집, 멱등) · 신규 등록은 **저장 먼저 → 비전 → 초안**([[draft-agent-v2]]) · 상세 수정 PATCH · 전표 보기 · **참석 인원 입력칸**(빈칸=모름 / 0=해당없음 — 없던 탓에 1인당 한도 룰이 전건 미해소였다) |
| S-02 팀 취합·통계 | ✅ 실 연동 | 이상 건 = RETURN/REJECT 둘뿐. 예산은 한도만 DB·사용액은 집계 |
| S-03 검토 워크스페이스 | ✅ 실 연동 | 이상탐지·RAG 검증·EvalContext 스냅샷·룰 판정 패널·결정 모달. Risk Review 진행 상태 표시 · **룰 판정 패널**(S-01과 같은 컴포넌트 — 지출자와 검토자가 같은 사유를 본다) |
| S-04 룰 콘솔 | ✅ 실 연동 | 3개 탭 전 구간(초안 편집·시뮬레이션·Active 승인/롤백·작성 대화) |
| S-05 규정 문서 관리 | ✅ 실 연동 | 폴더 트리 + **조 단위 조항 아코디언**. 조항 상태는 저장하지 않고 파생(`SKIP`+사유만 저장) |
| S-08 예산 / S-09 카드 | ✅ 실 연동 / 🎭 조치 큐만 목업 | 저장하는 건 사람의 결정뿐 — 사용액·「회수 필요」는 파생. **다개월 추세·과부족 패턴도 실 데이터**(`/api/team-budget/trend/`, 목업 걷어냄) — 사용액 정의는 `settlements/budget.py` 한 곳, 집계 쿼리 2회, **정산 없는 달은 `0`이 아니라 `null`**. S-09 「회수/중지 필요」는 시연용 목업(`web/src/data/cardAttentionMock.ts`) — 분실신고·휴직·장기미사용을 담는 자리가 도메인에 없다. 화면에 그렇게 밝히고 회수는 서버로 안 나간다 |
| 알림 | ✅ 11종 | 상태 전이·비동기 완료·룰 콘솔 사건 → **메시지 + 이동할 페이지**. 생성 지점은 `transition()` 한 곳, 링크는 서버가 완성, 개수형은 묶는다. **지금은 페이지 이동까지만**(딥링크는 받는 쪽 인프라가 없어 다음 단계). → [[notifications]] |
| ERP 전표(안) | ✅ | `GET /api/erp/vouchers/by-settlement/{id}`. 없으면 404 그대로(빈 껍데기 금지) |

### 3.6 시드 · 운영

| 영역 | 상태 | 비고 |
|---|---|---|
| `seed_clean` (초기 적용) | ✅ | 막 설치한 회사 — 사용자·팀 + **사람·팀에 배정된 카드 10장** + `DEFAULT GATE` 1개. 팀 예산은 한도만. → [[default-gate]] §6 |
| `seed_adopted` (적용 완료) | ✅ | 3개월째 굴러가는 회사 — 직전 3개월 정산 ~185건이 **실제 전이를 타고** 흘러간 상태(전표 168·자동처리율 ~89%·평균 검토 ~27분). 시각은 결제일로 되돌리고, 종결 건 알림은 지운다 |
| `seed` (화면별 시연) | ✅ | 룰 4계열·정산 87건·검토 30건·RAG 하이라이트 3건. 거래일자는 이번 달 안에 배치. 회식 시연 3건은 **실제 `services.judge()`** 로 판정 |
| 로그 | ✅ | `logs/core.log`·`logs/ai.log` (5MB×3 로테이션, git 미추적). 디버깅은 여기부터 |

### 3.7 다음 후보

1. **별표 적재 경로 확장** — `PolicyTable`에 행을 넣는 실사용 경로가 문서 승인 흐름으로 열렸으나, 축 제안 정확도·개정 재현은 실데이터 검증 전. 축 매핑 **자동 확정은 금지**(스키마에 없는 축이 조용히 와일드카드로 떨어진다)
2. **RAG 운영 적재 마무리** — 청킹·임베딩 전략은 평가 완료, 실 코퍼스 전량 upsert만 남음
3. **출장 입력칸 3개** — `trip.*`는 첨부 추출(TRIP_PLAN)이 이미 뽑는데 화면 입력이 없어 0%다
4. **`merchant.forbidden` 정리** — 59% 채워지는데 참조 0. 게이트가 리터럴로 직접 비교해 선해소 목적이 사라졌다 — 게이트를 고치거나 선해소를 빼거나 정해야 한다
5. **`classify_merchant` Risk Review 연동** — Draft만 연결돼 있다
6. **`anomaly.pkl` 재학습** — `feature_contribs` 실값 확보 + sklearn 버전 고정
7. **Draft Agent 정리** — 폼 기반 옛 경로(`/agent/draft`) 제거, AI-LAB 정산 모드 탭
8. **알림 딥링크** — 지금은 페이지 이동까지다. `?open=/?graph=/?doc=` 소비 + 목록 하이라이트. `/rules?graph=`를 만드는 코드는 있는데 읽는 코드가 없어 **이미 죽어 있다**

---

## 4. 프로젝트 컨텍스트 구조 (llm_wiki) — 에이전트 자동 생성·활용

`llm_wiki/`는 이 프로젝트 컨텍스트의 **단일 진실 원천(SoT)**. 에이전트/Claude는 **`llm_wiki/_index.md`(색인)를 세션 시작 시 먼저 읽고**, 컨텍스트를 바꾸면 해당 문서와 색인 행을 함께 갱신한다.

```
llm_wiki/
├── _index.md            ← 컨텍스트 색인/매니페스트 (에이전트가 읽고 갱신하는 진입점)
├── docs/                ← 팀이 관리하는 기준 문서 — SoT (권위 범위·버전·상태는 _index.md 표)
│   ├── 요구사항_명세서.md
│   ├── 기술명세서.md      (2026-08-24: 기획_확장안.md 병합 — §12 서비스 기획 보충)
│   └── RULE_명세서.md    (참고 예시 — 제품 기본 제공은 DEFAULT GATE 1개뿐)
├── 화면설계서/           ← 압축해제 .docx (본문 word/document.xml, 추출 레시피는 CLAUDE.local.md)
├── figma_mockup/         ← 화면 목업 SVG (참고용, 픽셀 매칭 불필요)
└── _context/            ← AI가 관리하는 AI용 파생 컨텍스트 (구현 캐논·설계 원안·실측 기록)
```

**관리 주체가 다르다**: `docs/`·`화면설계서/`는 **팀**의 기준 문서, `_context/`는 **AI**가 생성·갱신하는 작업 컨텍스트. 상충하면 `docs/`가 이긴다.

**자동 생성·갱신 프로토콜(에이전트 규약):**
1. **세션 시작**: `_index.md`를 읽어 어떤 컨텍스트가 어디에 있는지·최신 상태를 파악한다.
2. **컨텍스트 변경**: 결정·스펙이 바뀌면 **① 권위 문서 본문 + ② `_index.md`의 해당 행(버전/상태/최종갱신)** 을 같은 커밋에서 함께 갱신한다. 세 스펙 문서 간 상충 금지.
3. **새 cross-cutting 컨텍스트**(결정 로그, 용어집, 상태머신 캐논 등): `_context/<slug>.md`로 생성하고 `_index.md`에 등록한다. (권위 스펙 문서와 중복 서술 금지 — 파생/요약만)
4. **파일명 규칙**: 권위 스펙은 한글 문서명 유지, 에이전트 생성물은 `_` 접두(예: `_index.md`, `_context/decisions.md`)로 구분.

- 외부 참조(레포에 없음): WBS.xlsx(2026-07-20~09-03), 프로젝트 기획서, 수집 데이터 보고서(AI Hub 합성데이터 벤치마크), 법인카드 사용 규정.

---

## 5. ⚠️ tiger_inc = RAG 소스 데이터 (열람 규칙)

`tiger_inc/`는 시스템이 **RAG로 검색·활용할 사내 규정/조직 데이터**다(코드/설계 산출물 아님).

- **해당 문서를 직접 편집·작성하는 작업이 아닌 한 열람하지 않는다.** (컨텍스트 오염 방지)
- 규정 값이 필요하면 실제 런타임에선 Chroma(`policy_docs`/`case_history`/`tax_refs`)를 거친다. 코딩 중 규정 내용을 추측해 하드코딩하지 말 것.
- 포함(`md/`·`pdf/` 동일 파일명): `법인카드_사용규정`, `업무추진비_사용규정`, `출장비_사용규정`, `회식_운영규정`, `부서소개`, `조직도`, `직급체계`, `조직설계_상세기획서`. `law/`에 `법인세법`·`부가가치세법`·`여신전문금융업법` PDF.

---

## 6. 자주 쓰는 명령

```bash
# 전체 스택 (repo 루트)
docker compose up --build            # 웹 :5173 / nginx :8080 / core :8000 / ai :9000 / chroma :8001
docker compose down [-v]             # 종료 (-v: 볼륨까지)
docker compose config                # compose 문법 검증

# 프론트 (apps/web) — 이 머신에선 --prefix 절대경로 권장(§CLAUDE.local.md)
npm install --prefix apps/web
npm run dev --prefix apps/web        # Vite dev (HMR)
npm run build --prefix apps/web      # tsc 타입체크 + vite build

# RAG 적재 — 두 경로가 있다.
#  ① 화면: 규정 문서 관리(/policy-docs)에서 PDF 업로드 → 백그라운드로 파싱·청킹·임베딩·적재
#     (Django가 파일을 갖고 ai가 같은 media 볼륨을 :ro로 읽는다. 상태는 목록 폴링으로 확인)
#  ② 아래 CLI: 이미 만들어 둔 파싱 덤프를 재적재할 때(평가·재현용)

# RAG 인덱싱 (관리자 온디맨드 배치) — 파싱덤프→교정→청킹→임베딩→Chroma upsert
#   덤프(docling_eval/)는 레포 루트라 컨테이너엔 /data/docling_eval:ro 로 마운트된다.
#   ⚠️ Git Bash는 `/data/...`를 윈도우 경로로 바꿔버린다 → PowerShell을 쓰거나 MSYS_NO_PATHCONV=1.
docker compose exec ai python -m app.rag.embedding.index --dump /data/docling_eval/output --dry-run  # 라우팅만(무과금)
docker compose exec ai python -m app.rag.embedding.index --dump /data/docling_eval/output            # 실적재(OpenAI 과금)
docker compose exec ai python -m app.rag.embedding.index --peek                                      # 적재 현황

# 벡터 DB 덤프·복원 — **재임베딩 없이** 옮긴다(OpenAI 호출 0회, 과금 0, 재현 100%).
#   시연 데이터를 확정하려면 벡터도 함께 고정돼야 한다 — 원문을 다시 파싱·임베딩하면
#   파서·청커·모델이 바뀔 때 어제 보던 검색 결과가 오늘 달라진다.
#   복원은 upsert다(기존을 지우지 않는다). 깨끗한 상태가 필요하면 `--reset`을 명시한다.
docker compose exec ai python -m app.rag.embedding.snapshot dump    --out /data/rag_snapshot
docker compose exec ai python -m app.rag.embedding.snapshot restore --in  /data/rag_snapshot

# Django (core)
docker compose exec core python manage.py migrate
docker compose exec core python manage.py createsuperuser

# 시드 — 무엇을 보여줄 것인가로 고른다. 셋 다 기존 데이터를 지운다(--dry-run 먼저).
#   seed_clean    **초기 적용**: 막 설치한 회사(사용자·카드 + DEFAULT GATE 1개, 정산 0건).
#                 규정 업로드 → 룰 생성 흐름을 처음부터 시연할 때.
#   seed_adopted  **적용 완료**: 3개월째 굴러가는 회사(직전 3개월 정산 ~185건이 실제 전이를
#                 타고 흘러간 상태). 통계·예산·전표·검토 이력이 차 있어야 하는 화면용.
#                 판정을 손으로 박지 않으므로, 룰이 바뀌면 끝에 기대 불일치를 경고로 낸다.
#   seed          화면별 상태를 골고루 흩어 놓은 옛 시연 데이터(이번 달 안에 전 상태 배치).
docker compose exec core python manage.py seed_clean --dry-run
docker compose exec core python manage.py seed_clean
docker compose exec core python manage.py seed_adopted
docker compose exec core python manage.py seed --fresh

# AI 서비스 계정 (ai → core 쓰기: 룰 DRAFT 저장·규정 적재 회신) — .env의 AI_SERVICE_PASSWORD 선행
#   **Agent별로 나누지 않은 계정 하나.** capability는 `rule_view` 뿐.
#   env를 바꿨으면 컨테이너 재생성이 먼저다 — 안 하면 core만 옛 env로 돌아 401이 난다.
docker compose up -d --force-recreate core ai
docker compose exec core python manage.py ensure_service_account
docker compose exec core python manage.py ensure_service_account --check   # 401 날 때 진단

# 로그 — 두 컨테이너가 호스트 ./logs/ 에 파일로도 남긴다(5MB×3 로테이션, git 미추적)
#   logs/core.log  Django(요청 실패·domain 로거 포함)
#   logs/ai.log    FastAPI + uvicorn(access/error)
#   LOG_LEVEL=DEBUG 로 올리려면 .env에서 바꾸고 컨테이너 재생성.
docker compose logs -f core ai       # 실시간(표준출력)
```

---

## 7. 규약

- 코드/주석은 주변 코드의 밀도·스타일에 맞춘다. 각 stub 파일 docstring에 대응 문서(§ 참조)를 남긴다.
- 요구사항/화면 변경은 §4 문서에 먼저 반영 후 코드에 반영(문서가 SoT).
- 개인 로컬 환경 노트·명령 tip은 `CLAUDE.local.md`(git 미추적) 참고.
