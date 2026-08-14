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
docker-compose.yml  로컬 개발 오케스트레이션 (db·chroma·core·ai·web·nginx)
llm_wiki/     설계·기획 산출물(아래 §4)
tiger_inc/    RAG 소스 데이터 — §5 열람 규칙 주의
daily_scrum/  주차별 진행 보고
```

아키텍처 원칙(기술명세서 기준): **SoR은 Postgres 하나**(AI는 "제안"만, 확정은 Django 서비스 레이어) · **관계형=Django 경유 / 벡터=Chroma 직접**(LLM/Tool의 Postgres 직접 SQL 금지) · **FastAPI는 내부 전용**(사용자 트래픽은 Django만) · **동기 REST(MVP)**, 무거운 작업은 관리자 온디맨드 배치.

---

## 2. 핵심 설계 결정 (변경 시 세 문서 + 화면 모두 동기화)

- **Risk Review = MVP 2단계**: ① 단순 이상거래 탐지(비지도, anomaly_score) → ② RAG 내규 검증(이상 후보 한정). 지도학습(`review_probability`)·자동 재학습 피드백 루프는 **post-MVP 확장**. (콜드스타트/라벨부족 대응)
- **상태머신(FR-ST-01)** — 4단계: **① 개인 보유(`DRAFT`) → ② 팀 취합(`TEAM_COLLECTING`/`TEAM_RETURNED`/`TEAM_REJECTED`) → ③ 회계 제출·룰엔진(`SUBMITTED`/`RPA_JUDGED`) → ④ 회계 검토·확정(`PENDING_CONFIRM`/`RETURNED`/`IN_REVIEW`/`REJECT`/`CONFIRMED`/`ERP_VOUCHER_DRAFTED`)**. **팀 수준 보완/반려(`TEAM_*`, 팀장)** 와 **회계 수준(`RETURNED`/`REJECT`, 회계)** 은 별개 상태. `REJECT`=회계 최종반려(재제출 불가). 제출=2단계(개인 올림 `raise_to_team`: `DRAFT→TEAM_COLLECTING` / 팀 제출 `submit`: `TEAM_COLLECTING→SUBMITTED`), 1인 팀도 동일 경로. ✅ **구현 반영**: ① `DRAFT→SUBMITTED` 직행 제거·S-01 "팀에 올림" ② 계정과목=비용분류(`Category`) 매핑 `policies/scope.normalize_scope` ③ **엔진 scope 연결 완료** — `services.judge()`가 더 이상 "활성 그래프 없다고 보고 무조건 IN_REVIEW"가 아니라 `domain.policies.orchestrator.judge_settlement()`(GLOBAL 게이트→scope 그래프, 신규)를 실행해 실제 `RuleHit`을 남기고 PASS/REJECT/RETURN/REVIEW에 따라 분기한다(REVIEW·그래프 없음만 IN_REVIEW). 🚧 남음: `/submit` 팀 동일성 배치 강제(Open #8). (기술 §3.3 / 요구사항 FR-ST-05·Open #8~9)
- **예산·정책은 통제(차단)가 아니라 지표·추천으로만** 반영.
- **사람 확정 원칙**: 확신 통과 건도 회계 담당자 확정 없이는 CONFIRMED 불가.
- 영수증은 별도 OCR 없이 **OpenAI 비전**으로 직접 판독. Rule 적용은 결정론적 엔진, LLM은 Rule 생성 단계에서만.
- **가맹점 업종 구분 시스템**: 자체 DB 캐시 → 카카오 지도 API → 웹검색 캐스케이드로 업종 판별 → 비용분류 **보조 힌트**로만 사용(세무 판단 아님). 표준 업종코드(MCC)는 카드사 제휴 **post-MVP** 확장. (기술 §7-1 / 요구사항 §6.5 / FR-DA-03a~c)
- **룰은 사전 탑재하지 않는다 — 기본 게이트 1개 + 문서에서 생성**: 제품이 미리 준비해 제공하는 것은 **`DEFAULT GATE` 하나**뿐이며, 특정 회사 규정에 종속되지 않는 **범용 default 룰**로 고도화한다. **카테고리별 세부 룰은 고객이 자사 규정 문서를 업로드하면 Rule Agent가 생성**한다(RAG 조항 추출 → 초안 → 시뮬레이션 → ACTIVE 승인). `법인카드_사용규정_기반_RULE_명세서.md`의 58 RULE과 `seed_rules`의 4개 계열 그래프는 **참고용 예시·시연용**이지 기본 제공물이 아니다.
- **룰 도메인 = 그래프(트리)**: 단건 룰은 `condition+action+next_routings` 노드, 조립된 **룰 그래프(RuleGraph)** 가 최종 상태 도메인. **ACTIVE·버전관리·시뮬레이션·롤백은 그래프 단위**. (기술 §3.1·§4.2 / 요구사항 FR-RB·FR-RV·FR-RA)
- **룰엔진 = 3단 파이프라인**: ① `build_rule_context(tx_id)`로 **EvalContext(facts 스냅샷)** 조립(모든 I/O·데이터 접근은 여기서만) → ② 그래프 선택(**필수 게이트 GLOBAL → 계정과목별 scope**) → ③ **결정론적 순회**(엔진은 EvalContext만 참조, 외부 I/O 0). 조건은 **JSON-Logic류 DSL**(임의코드 금지). context는 `rule_hits.eval_context`에 스냅샷 저장 → 재현·감사. 상세: `llm_wiki/_context/rule-engine.md`. (기술 §4.2(d) / 요구사항 FR-RA-08~10)
- **인가 = 기능 단위(Capability) RBAC**: 역할이 아니라 6개 Capability(`team_aggregate`·`accounting_review`·`rule_view`·`rule_activate`·`governance_view`·`ai_lab`)로 판정. **유효능력 = 역할 기본값 ∪ 개인 추가부여(`users.extra_capabilities`)** — 예: `acc`=회계+룰열람+팀취합, `acclead`=회계+룰열람+룰활성. 룰콘솔은 열람(`rule_view`)/활성(`rule_activate`) 분리. DRF `HasCapability` 파생 권한으로 백엔드 강제, `/api/me`에 `capabilities` 노출, 프론트는 `useCan()`로 게이트. **Django admin에서 사용자별 `extra_capabilities` 체크박스 부여**. (기술 §3.1a)

---

## 3. 상태 보드 (Status Board) — _최종 갱신: 2026-08-12_

작업 진행/추적용. **의미 있는 진척마다 이 섹션을 갱신**한다.

| 영역 | 상태 | 비고 |
|---|---|---|
| 문서: Risk Review 2단계 반영 | ✅ 완료 | 요구사항·기술·기획 3문서 + 화면설계서 일관 |
| 모노레포 스캐폴드 | ✅ 부팅 가능 | `docker compose config`·`py_compile` 통과 |
| 프론트 6개 화면(S-01~06) | ✅ 빌드 통과 | mock 데이터 렌더. `npm run build` OK |
| Django 도메인 모델 | ✅ 구현 완료 | 8개 도메인 18개 테이블(실 필드·FK·제약·마이그레이션). `RuleHit.eval_context/flags/schema_version/builder_version` + `0002` 마이그레이션 반영. 설계 문서 `.personal/데이터베이스_저장소_설계문서.md` |
| FastAPI Agent 로직 | 🚧 Draft·Risk 실동작 / Rule 미착수 | Draft Agent(비전 제외) 기존 구현. **Risk Review Agent(2단계) 실동작 추가**: 1차 이상탐지(`get_tx_features`+`ml_infer`, 위 행 참조) → 2차 RAG 내규 검증(`search_policy`/`search_cases` 실구현 + LLM structured output `RiskVerdict`)까지 end-to-end 연결. `search_policy`는 운영 인덱스(`app/rag/embedding/store.py`, `policy_docs` 실측 103청크)를 사용 — `agents/rule_agent_v0/vector_store.py`는 격리된 로컬 실험 스토어(RULE_AGENT_V0_CHROMA_HOST 미설정 시 `./chroma_data_v0`, 실측 1건)라 승격하지 않았다(승격했으면 2차 검증이 빈 결과만 도는 죽은 경로가 될 뻔). `case_history`는 실 결정이력 적재 파이프라인이 없어 `app/rag/golden_cases.py`(10건, 시연용 명시)로 최소 골든 시드, `python -m app.rag.case_store --upsert`로 적재. LLM 출력 스키마(`violation_verdict`/`review_reasons`/`recommendation`/`citations`/`similar_cases`)는 기존 `RiskReview.reasons`(1차 feature contribs, 프론트 기존 계약)와 분리해 신규 `RiskReview.stage2_verdict`(JSONField)에 저장 — `rag_refs`/`ai_recommendation`은 기존 포맷으로 매핑해 채움(SUPPLEMENT→RETURN). Django `SettlementViewSet.judge` 액션이 IN_REVIEW 전이 직후 FastAPI `/agent/risk-review` 호출·저장(AI 미기동 시 조용히 스킵, 상태 전이 자체는 유지). 실측 검증: 실제 IN_REVIEW/SUBMITTED 정산 건으로 NO_VIOLATION(실 인용 포함)·INSUFFICIENT_INFO(정보없음/판단보류 구분) 양쪽 분기 확인. **`anomaly.pkl` 실물 로드 확인**(`/app/var/models/`에 배치): 레지스트리가 정상 인식, `get_tx_features`+`ml_infer`가 실제 정산 건에 대해 anomaly_score·percentile_band·calibrated_rate를 실값으로 반환(예: settlement 114 → anomaly_score −0.0127, 80~90% 밴드). 다만 이 pkl은 `fill_values`·`feature_stats`(둘 다 이 세션에서 신규 추가된 필드) **이전 시점에 학습**된 것이라 `feature_columns`가 23개(현재 코드 기준 24개 — `일시불할부구분코드` 카테고리 A·B만 학습, `_` 없음)이고 `feature_stats`가 없어 **feature_contribs는 여전히 빈 배열**이다(모델이 없어서가 아니라 이 모델에 그 통계가 없어서 — `AnomalyModel.__setstate__`로 신규 필드 누락 시 `None` 기본값을 채워 로드 자체는 깨지지 않게 방어). `align_to_model`이 컬럼명 기준 reindex라 23→24 스키마 차이는 흡수됨(누락 카테고리는 0으로). contribs를 실값으로 보려면 현재 `train.py`(feature_stats 포함 버전)로 재학습 필요. sklearn 버전 경고(pkl=1.8.0, 컨테이너 설치=1.5.2, `InconsistentVersionWarning`)도 함께 확인됨 — 재현성 문제로 이어질 수 있어 재학습 시 버전 고정 권장. 참석인원·사전승인 등 세부 판정 사실을 2차 프롬프트에 아직 안 넘겨 애매한 근거는 INSUFFICIENT_INFO로 보수적으로 수렴하는 경향(그 자체가 가드 오작동은 아님). Rule Agent 3단 파이프라인은 여전히 stub |
| 프론트 ↔ 백엔드 연동 | 🚧 진행 중 | **S-04 Rule 콘솔 3개 탭 전 구간 실 API 연동 완료**(초안 편집·저장, 검증셋·시뮬레이션 실행/보고서, Active 승인·버전이력·롤백, 작성 대화 로그). S-03 검토 화면은 RAG 보고서·EvalContext 스냅샷 연동. 나머지 화면 순차 진행 |
| RAG 문서 파싱(docling) | 🚧 PoC 완료 | `docling_eval/` — 파싱 검증 노트북 + `postprocess.py`(결함 6종 교정: 리딩오더·목록 마커·문단 분할/병합·CJK 줄바꿈 재결합·자간). tiger_inc 규정 4종 실측 **요소 완전일치 29~54% → 77~96%**. CJK 줄바꿈만 원리상 완전 복원 불가(양끝맞춤이라 어절 내/간 간격이 동일)라 어휘 사전 기반 추정 + md 원본 대조 채점. **문서 유형별 가드**: 페이지 끝 고아 목록 마커 유무로 규정형/법령형을 갈라, 법령(`law/` 3종)은 `steps={"R1","R4","R5"}`로 R2·R3·R6를 끈다(그 결함이 없어 R3가 별개 조문·목을 오병합 — 법인세법 412건·여신법 126건). 정답지(md) 없는 문서는 `review.py`가 판정 전수를 `output/review/<문서>/`에 시트로 떨궈 사람이 검수(weak 비율: 법인세 28%·부가세 27%·여신 44%). 도해 위주 문서(조직도·조직설계)는 후처리 적용 시 회귀(80%→53%)라 제외. Chroma upsert는 미착수 |
| docling 파싱 품질 평가 | ✅ 노트북 완료 | `docling_eval/docling_parsing_evaluation.ipynb` — **파싱이 아니라 채점** 전용(`output/` 산출물 ↔ GT 대조). **GT = `tiger_inc/md/*.md`**(PDF와 동일 파일명 원고) 8종만 정량 채점, 법령 3종은 GT 없어 **N/A + 사람 검수 시트**. 3영역 가중합(Layout .30 / Hierarchy .30 / Table .40). **실측 Overall 89.3** — Layout 92.6(탐지 F1 .93·타입 .92) / Hierarchy 85.6(헤딩 F1 .84·레벨 .93·부모자식 .74·순서 .92) / Table 89.6(탐지 F1 .93·행 .59·열 1.00·헤더 .94·셀 .96). **정답 없는 항목은 점수화 금지**: bbox IoU·병합셀은 `N/A`로 두고 가중치를 같은 영역에 재분배(기하 이상치는 0건). 채점 함정 3개를 명시 처리 — ① 표 요소는 `<table 3x2>` 자리표시자라 셀 격자를 펼쳐 매칭(안 하면 표가 전부 Missing+Extra 이중 계상) ② 문서 제목 개념 부재로 생기는 레벨 오프셋 δ는 레벨 지표에서만 세고 부모-자식에선 제목≡ROOT로 접어 이중 감점 방지(strict .15 vs offset .93) ③ `개정 v1.1` 배지가 헤딩에 섞인 건 미탐지가 아니라 `Text Mismatch`. 공백·자간 결함은 `norm_loose`=`norm_strict`≠ 로 분리 집계(셀 161건, Cell Acc loose .96 vs strict .76). 산출물 `output/evaluation/` 5종(summary·details·error_cases·qualitative·report.md) |
| RAG PDF 파싱 파이프라인 | ✅ P0/P1 구현 완료 | 전략 캐논 `llm_wiki/_context/pdf_parsing_strategy.md`(docling 기반으로 전면 재작성, 구 PyMuPDF+pdfplumber 수제안 폐기). `apps/ai/app/rag/parsing/` — engine(docling+pypdfium2 2단 폴백) → profile(REGULATION/LAW/DIAGRAM/GENERIC) → corrections C1~C7 → `ParsedDoc`. **실측 결과**: 고아 항/호 마커 95→0 · 법령 원문자 항 자동번호 882→0 · 장/조 순서 11종 전건 정합(장 미귀속 조 1건) · 자간 667→372(△44%) · 요소 소실 0. 회귀 테스트 61건 통과(`tests/test_parsing_corrections.py`) — **docling 재실행 없이** `docling_eval/output` 덤프 4,388요소에 교정만 걸어 고정. 구현 중 초안 3건을 실측으로 정정: ① 장 밀림의 원인은 **페이지 최상단 요소가 그 페이지 끝 순서로 배치**되는 것(위반 21/4,388) → 조 번호 역산이 아닌 기하 리딩오더 복구 ② 고아 마커는 **자기 자신의 번호**(다음 항 아님) ③ HTML escape 846건은 docling `export_to_markdown()` 산물이라 우리 경로엔 없음. **남음**: GT 8종 대비 재채점, 자간 잔존(법령 341건), furniture 147건 육안 검수 |
| RAG 청킹 전략 | ✅ 구현 + 평가 완료 | 전략 캐논 `llm_wiki/_context/chunking-strategy.md` · 평가 노트북 `docling_eval/chunking_evaluation.ipynb` → `output/chunking/`. **자르는 단위는 문자 수가 아니라 조(條)** — 실측이 근거다(문단 요소 중앙 **76자**·61%가 100자 미만 → 요소 단위 불가 / 조 블록 381개 중앙 **449자**, 1,200자 컷이면 **79%가 통째로** 남음 / 항 서브블록 p90 **420자** → 안전한 2차 분할선). 분할 사다리 `조→항→호→문장→문자`. 표는 **언제나 독립 청크**(한도표가 룰 임계값 원천), 별표는 조 밖 형제, 오버랩 대신 **계층 헤더+부모 확장+이웃 링크**. 📏 전략 비교: Fixed 800자는 조 경계 위반 **190건**·표 파손 29건, Recursive는 중앙 **114자**로 과분할, 우리 안은 각각 **1·0**. 📏 산출 **888청크**(부모 89), 중앙 290자·p90 956, 커버리지 **100%**·유실 0·중복 0·인용 100%·표 행보존 100% → **종합 98.5/100**(검색 성능은 N/A). `apps/ai/app/rag/chunking/` + 회귀 164건(전체 225건). **✅ 결정대기 ④ 해소**: 항/호 호칭을 프로파일이 아니라 **조 단위**로 판정(기본 `항`, 도입부에 `각 호`가 있는 조만 `호`, 법령은 예외 없이 `항`) — 규정이 자기 항목을 인용할 때의 표기를 역산한 실측이 근거이고, 이전 구현은 규정의 조 27개 중 **26개에서 틀린 호칭**을 회계 담당자 화면 인용에 쓰고 있었다. **`Budget` 정합 가드**(`0 < min_merge < target < max <= hard`) 추가 — `--max`만 주면 target이 기본값으로 남아 채우기 목표가 죽는 사고를 막고, 덤으로 §10.2 스윕의 "파편 91→103, 원인 미확인"이 **코퍼스가 아니라 `max > hard` 조합 탓**(hard가 도달 불가가 됨)이었음이 드러나 91로 정정됐다. **잡은 결함 4건**: ① 법인세법 표지가 통째로 `제55조의2`로 오인용 ② 항 범위 역순(`제3~2항`) ③ **덤프/운영 `grid` 계약 불일치**(C5가 무관한 표를 병합·텍스트 파손 → “최대 89행 표” 거짓 통계의 원인) ④ **법령의 조는 heading이 아니라 paragraph로 시작하는 경우가 많아** 앞 조에 흡수돼 남의 조문으로 인용되고 있었다(**64건 → 2건**) — 평가 노트북이 잡았다. **남음**: Chroma upsert, 검수 시트 40건 (임베딩 모델·정답셋 30건은 아래 행에서 해소) |
| RAG 임베딩 전략 | ✅ 평가 완료 / 🔲 upsert 미착수 | 전략 캐논 `llm_wiki/_context/embedding-strategy.md` · 평가 노트북 `docling_eval/docling_embedding_strategy.ipynb` → `output/embedding/`(결과 25종+벡터, 순위표 `ranking.csv` 포함). **청킹 §11 결정대기 ①② 해소**. **공급자는 OpenAI로 결정**된 상태에서, OpenAI 4변형(3-large 네이티브/1024/256 · 3-small) + 로컬 기준선 3종을 같은 코퍼스(799 잎청크)·같은 정답셋(30건)으로 실측 → **`text-embedding-3-large` @ `dimensions=1024`** 확정(문서입력=**헤더+본문**(현행 `embedding_text()` 유지), 질의=`사내 규정 조문 검색:` 접두, cosine, 배치 128). 📏 MRR .906 · R@1 .817 · R@5 .950 · nDCG@10 .916 · 표 R@5 1.00. **정답셋 30건 신설** — 6유형 5건씩, 정답은 **조문 ID**(`문서명\|조 라벨`)라 청킹 예산이 바뀌어도 무효가 안 된다. **차원 1024를 고른 근거**: 네이티브 3072 대비 ΔMRR **−0.006**(CI가 0 포함=잡음)인데 **R@1은 오히려 높고**(.817 vs .800) **저장 9.8→3.3MB(−67%)**. 256은 ΔMRR −0.091(CI 0 제외)로 **실제 손실** = 하한 확인, 3-small도 MRR .782로 명확히 낮다. **평가 방법에서 잡은 함정 4개**: ① `Recall@5`가 105조합 중 3개에서 1.000 → **천장에 붙어 변별력 상실**. 첫 실행이 실제로 이 지표로 정렬해 **엉뚱한 모델을 승자로 뽑았다** → 선정 기준을 `MRR→R@1→nDCG`로 고정 ② 상위 입력 전략들이 ΔMRR 0.0008~0.017 → 잡음으로 구현을 바꾸지 않도록 **동률 규칙**(Δ<0.01이면 기존 유지) 도입, **모델 선택에도 적용**(동률이면 차원 작은 쪽) ③ 질의 30건이라 부트스트랩 CI 필수 — 후보 1·2위도, 후보와 기준선도 **CI가 0을 포함**한다 ④ `| tail`이 nbconvert 실패를 exit 0으로 가려 **실패한 실행을 성공으로 착각**했다(이후 `set -o pipefail`). 실측 부수 소득: **본문만 임베딩(`A_content`)이 전 모델에서 꼴찌** — 계층 헤더 주입이 평균 MRR을 +0.050 움직인다(청킹 §5의 근거). 📏 한국어는 cl100k_base에서 토큰 1.6배(358 vs 223) — 전량 인덱싱 1회 306,566토큰, 단가 미확인이라 금액은 N/A. ⚠️ **기준선 `bge-m3`(자체 서빙)가 MRR .933으로 더 높다**(ΔMRR −0.028, CI [−0.100,+0.044]로 0 포함). 공급자 결정이 먼저였으므로 이 표가 그 결정을 정당화하진 않는다 — **격차는 재검토 트리거로 기록**. **남음**: 정답셋 사람 검수·난이도 보강(사용자 말투 질의·같은 조 항 구분 질의), 청킹 A~E 검색 비교(§10.4), Chroma upsert |
| 이상탐지 실학습/RAG upsert | 🚧 이상탐지 서빙 연동 완료 / RAG 미착수 | `apps/ai/app/ml/`에 확정 하이퍼파라미터·15개 피처 파이프라인(`features.py`)·decile 보정표·고정 임계값(`calibration.py`) 이식 + 오프라인 배치 학습 스크립트(`train.py`, 관리자 CLI 실행) 연결 완료. `registry.py`가 학습된 모델·threshold·calibration_table·`fill_values`를 pickle로 저장/로드. **`get_tx_features` 실연동 완료**: Django `transactions/features.py::build_tx_features`가 카드별 과거 거래 집계(최근7일사용횟수·확장 통계 등)를 조립해 `/api/internal/tx-features/<tx_id>/`로 노출 → FastMCP `get_tx_features`가 `app.ml.features.build_feature_matrix`(카테고리 고정 원-핫)로 변환 후 활성 모델의 `feature_columns`에 정렬. `ml_infer`에 형상 검증(빈 벡터·컬럼 수 불일치 시 명시적 에러) 추가. `일시불할부구분코드`(카드사 원천 필드, SoR에 없음)는 실거래는 `_`(결측 센티널) 기본값, 시드는 학습 데이터 관측 분포로 랜덤 배정. 실측: 학습 파이프라인 산출 24컬럼(원-핫 후, 기존 문서상 "23"은 오기)과 단건 서빙 벡터 컬럼 순서 일치 확인(`train.py`+`get_tx_features` 도커 컨테이너 실측 검증). RAG upsert는 그대로 미착수 |
| 가맹점 업종 구분 시스템 | 📄 문서화 완료 / 🔲 구현 미착수 | 3개 명세 반영. `classify_merchant` Tool·`merchant_categories` 캐시·카카오/웹 연동 필요 |
| 룰 그래프(트리) 도메인 | ✅ 1차 완료 | scope별 버전·DRAFT 복제/원복·노드 삭제·자동 저장·**DSL 쉽게보기(`RuleNode.condition_text`)** 에 더해 **검증 시뮬레이션 도메인**(`RuleTestCase`/`RuleSimulationRun`/`RuleSimulationResult` — 실행 스냅샷+해시 보존, 낡은 결과 표시)과 **승인 흐름**(Active 요청 시 검토자 코멘트·스코프당 승인대기 1건 제한, 활성자/검토자 추적, 버전 이력 롤백) 구현. 구조 시각화는 위→아래 스크롤 플로우차트(순환 감지 포함) |
| 화면 임시 비활성화 | ⏸ 규정 문서 관리(S-?/`/policy-docs`) | 실 API 미연동(mock 전용)이라 사이드바 메뉴·라우트를 주석 처리. 화면 파일(`PolicyDocuments.tsx`)은 그대로 두었고, `App.tsx` import·라우트와 `Sidebar.tsx` MENU 한 줄만 되살리면 복구 |
| 시연 시드 데이터 | ✅ 완료 | 룰 그래프 4계열(GLOBAL v1~v3·기업업무추진비 v1~v2·회식비 활성+초안·출장비 승인대기) + 작성 대화 로그, 정산 87건(회계팀 자체 지출 포함)·검토 대기 30건·검토 이전처리 10건, 하이라이트 3건은 RAG 검증 보고서(마크다운)+실제 EvalContext 스냅샷(`rule_hits`). **모든 거래일자는 이번 달 1~30일 안에 배치**(`seed.at()`) — 팀 통계·검토 이력의 "이번 달" 필터와 정합. **회식(GATHERING) 규정 검증 시연 3건 추가**(`_judge_dining_demo`) — 하드코딩 상태가 아니라 `services.judge()`(진짜 Rule Agent 오케스트레이션)로 실제 판정: 1인당 4만원·2차 아님(PASS→자동 `PENDING_CONFIRM`) / 1인당 15만원(한도 초과 M-001 REVIEW→`IN_REVIEW`) / 2차 결제(M-002 REVIEW→`IN_REVIEW`, 이어서 Risk Review Agent 2차 실호출까지 태워 `stage2_verdict` 실제 LLM 응답 확보). **실측 함정**: `upsert_policy_tables()`가 원래 시드 맨 끝에 있어서 이 판정 시점엔 `policy.dining_per_person_limit`이 미해소라 3건 전부 REVIEW로 강등됐다 — `PolicyTable` 적재를 `seed_rules` 직후·판정 직전으로 이동해 해결(기존 `_enrich_demo_cases`는 EvalContext를 수기로 채워써서 이 순서 의존성이 가려져 있었을 뿐, `build_rule_context`를 실제로 타는 경로는 원래도 이 순서가 필요했다) |
| 화면 데이터 스코프 규약 | ✅ 정리 완료 | "이번 달" 경계는 `web/src/lib/period.ts`에서만 정의(하드코딩 월 상수 제거). **S-01 내 지출**=오늘이 속한 달(단순 월 기준, 일자 무관). **S-02 팀 통계 대시보드**(KPI·예산)=팀·이번달·`REJECT` 제외 **전 상태** / **S-02 취합 목록**=팀·이번달·`TEAM_*`만. **S-03 이전 처리**=이번 달 회계 결정 완료 건(`api/settlements.ts:REVIEW_DECIDED_STATUSES`) |
| 팀 예산(TeamBudget) 정합 | ✅ 수정 완료 | 한도만 DB, 사용액은 팀·월·`REJECT` 제외 Settlement 집계(`TeamBudgetView`). **불변식 2개**: ① 팀 총한도(`category=''`) = 과목 한도 합 ② 과목 사용 합 = 총 사용액. 시드는 실제 집계에서 한도를 역산(`seed.py` BASE_USAGE_RATE)해 내역이 바뀌어도 어긋나지 않게 하고, **6개 과목 전부** 예산 행을 만든다(과거 `업무활성` 누락으로 항목 합 ≠ 총액이었음). 예산 행 없는 과목 지출은 API `unbudgetedUsed`로 노출 |
| 규정 임계값(policy) 도메인 | ✅ 전면 재구축 완료 | **원인 결함**: 초기 `Policy`(category·limit 스칼라 1개) 모델과 룰엔진 `ctx.policy.*` 카탈로그가 서로 모른 채 자라 필드가 하나도 안 겹쳤고, 조립기 부재로 `ctx.policy.*`가 전량 `null` → DSL이 null 비교를 `False`로 흡수해 **실 정산 경로에서 한도 룰이 조용히 미발동**했다(검증셋·시연 3건만 facts 수동 주입으로 동작). **조치**: ① 저장층 **`PolicyTable`**(별표 원본 자유 JSON `payload` + `key_axes` 축 선언, 개정은 `effective_date` INSERT) ② 소비층 **`ctx.policy.*` 고정 카탈로그 13종**(`gift_type`→`category.item_type` 이관, 누락 임계값 6종 승격, `biz_days_over_7`·`*_3m` 등 **필드명 상수 제거**, 스키마 v2) ③ 해소 규약 `policies/context_builder.py`(`RESOLVERS`·와일드카드 폴백·`ctx.tables` 원본 보존) ④ **미해소 가드** `UNRESOLVED_POLICY_VAR` → REVIEW 강등 ⑤ SoT 일원화(`draft_agent.THRESHOLDS`·시드 DSL 리터럴 제거 → 값은 `policies/tiger_tables.py` 한 곳). 내부 read API `/api/internal/rule-context/<id>/` + MCP `build_rule_context` 연결. 캐논 `llm_wiki/_context/policy-domain.md` / 결과 `policy-domain-plan.md` |
| EvalContext 스키마 v3 (다이어트) | ✅ 101 → 46 필드 | **원칙: EvalContext는 '단어'(원자 사실)만, '문장'(판단)은 룰 그래프가 조합한다.** 삭제 기준 4가지 — (a) **판정 필드**(`derived.personal_use_suspected` 등 — 결론을 입력받고 있었다 → 그래프에서 조합) (b) **조합 가능**(`*_missing` 7종 → `participant_count == 0`) (c) **원천 없고 부차적**(`tx.service_charge_ratio`·`is_holiday`·`merchant_grade`) (d) **과세분화**(출장 상세 9·참석자 상세 5·승인 상세 5·세부유형 3). `tables`는 고정 목록 폐지→동적, `policy` 13→8, 금지업종 별표(`forbidden_merchant_table`) 신설. 시드 그래프도 함께 정리(E-005 봉사료·M-004 분할결제·T-101/103/104 노드 삭제). **성과: 막는 필드의 등급이 A1·B7·C1·D1 → A2·B7·C0·D0** — 남은 건 전부 컬럼 추가로 해결 가능. 조립 커버리지 34/101→24/46. 기록·미결 8건 `llm_wiki/_context/eval-context-sourcing.md` §12·§13 |
| 판정 입력 실 연동 (Settlement 컬럼 + Attachment) | ✅ 1차 완료 | **Settlement 판정 컬럼 9종 신설**(`headcount`·`external_headcount`·`pre_approved`·`actual_user(_recorded)`·`item_type`(=청탁금지 룩업 키)·`kickback_target`·`is_secondary_venue`·`includes_alcohol`) — **전부 null 허용**(None=모름 계약). **`Attachment` 모델 신설**: 첨부 종류(영수증/사전승인/회의록/참석자명단/출장계획서/계약서) + **추출 결과 틀**(`extracted`=EvalContext dot-path→값, `field_confidence`, `evidence_spans`, `extraction_status`) — 채우는 주체는 **증빙자료 추출 Agent**(`llm_wiki/_context/evidence-extraction-agent.md`, 추출 로직 미착수). 조립기가 **첨부 추출 → 화면 입력 순으로 얹고**(빈 컬럼은 추출값을 덮지 않음), 시뮬레이션 실 내역 경로도 조립기 경유로 전환. **실측: 판정 강등 93% → 31%, GLOBAL 게이트 0건.** 남은 강등은 scope 무관 전수 실행 탓이 큼(운영은 scope별 그래프 선택) |
| EvalContext 사실(fact) 조립 | 🚧 policy 축만 완료 | 미해소 가드를 **전 구간 확장**(`UNRESOLVED_FACT:<path>` 신설, `None`=거짓 아닌 **모름** 계약)하자 실제 규모가 드러남 — **판정 120행 중 112건(93%) 강등**. `policy.*` 13종은 전부 해소되는데도 그렇다: 임계값과 비교할 **사실**(참석 인원·사전승인·카드 구분 등)이 SoR에 없다. 조립 커버리지 **34/101 필드**, ACTIVE 그래프 참조 19개 중 **10개 결측**. 필드별 출처 실현 가능성을 A(데이터 있음·코드만 15)/B(컬럼·입력칸만 12)/C(도메인 신설 13)/D(빼는 게 현실적 38)로 등급화 → `llm_wiki/_context/eval-context-sourcing.md`. **다음**: `Settlement`에 컬럼 6개(headcount·pre_approved·kickback_target·actual_user·item_type·is_secondary/alcohol) + S-01 입력칸 6개면 강등 93%→~8%(추정) |
| AI-LAB (관리자 실험 화면) | ✅ Draft·RAG 완료 | AI 기능을 **정산 흐름 없이 단독 실행**하는 관리자 화면(`/ai-lab`, Capability `ai_lab`=회계팀장 기본). 5탭: 상태 점검 / ① Draft Agent(생성·수정, 요청 JSON 직접 편집, 세션 이력) / RAG 검색(top-K·부모 확장·질의 접두 토글) / 임베딩 인스펙터(cosine 행렬) / 적재 현황(청크 원본 열람). **운영과 같은 코드를 부르고**(별도 구현 금지) 결과 대신 **근거**를 편다 — 프롬프트 전문·LLM 원본 출력·토큰·지연·정책 조회 출처(실조회/폴백)·검색 점수·메타데이터. 경로 `브라우저→Django /api/ai-lab/*(프록시·인가)→FastAPI /lab/*`. 추적은 `draft_agent.run(req, trace)`의 **선택적 dict 인자**로 모아 운영 응답 셰이프를 건드리지 않는다. 실패는 폴백 없이 사유 그대로(진단 목적). Rule/Risk/증빙추출은 stub이라 "예정"으로 표시. 캐논 `llm_wiki/_context/ai-lab.md` |
| 기능 단위(Capability) RBAC | ✅ 백엔드+프론트 완료 | `Capability` 4종·`extra_capabilities`·`HasCapability` 권한·`/api/me` 노출·seed 반영. 프론트: `useCan()`로 Sidebar·팀취합·검토·룰활성 게이트 전환(role 문자열 제거). mock은 역할 기본값, 실 모드는 `/api/me` capabilities |
| Rule Agent → IN_REVIEW 자동이관 연결고리 | ✅ 구현 완료 | **원인 결함 해소**: `services.judge()`가 Rule Agent(`run_rule_engine`)를 한 번도 호출하지 않고 "활성 그래프가 없다고 보고" 무조건 IN_REVIEW로 보내는 하드코딩 placeholder였다(FR-RA-04 앞쪽 절반 부재 — settlement 113/114/115가 IN_REVIEW인 것도 seed.py가 상태머신을 안 거치고 직접 꽂아 넣은 시드였음, `SettlementEvent` 부재로 확인). 신규 `domain/policies/orchestrator.py::judge_settlement()`가 GLOBAL(ACTIVE) 게이트 먼저 실행 → PASS 아니면 그 결과가 최종 → PASS했거나 GLOBAL 자체가 없으면 scope(`normalize_scope(category)`) ACTIVE 그래프 실행 → 둘 다 없으면 IN_REVIEW. 실행마다 `RuleHit` 기록. `services.judge()`가 이걸 호출해 `RPA_JUDGED→{PENDING_CONFIRM,REJECT,RETURNED,IN_REVIEW}`로 실제 분기. 실측: settlement 51(식대, GLOBAL이 `PERSONAL_USE_SUSPECTED`로 REVIEW 판정 → scope 그래프 안 감·IN_REVIEW), settlement 58(업무활성, GLOBAL PASS이나 scope 그래프 없음 → IN_REVIEW), settlement 123/118/114/82/79(식대, GLOBAL+scope 둘 다 PASS → PENDING_CONFIRM) — 세 갈래(REVIEW 실판정·그래프부재·자동승인) 전부 실제 HTTP `/api/settlements/<id>/judge/` 경로로 확인, IN_REVIEW 귀결 시 Risk Review 자동호출(`stage2_verdict` 저장)까지 이어짐 |
| Category "업무활성"→"회식" 리네임 | ✅ 완료 | 팀 확정(2026-08-14, `Category.OPERATION("업무활성")`→`Category.GATHERING("회식")`, 같은 enum 슬롯 재사용). **단순 문자열 치환이 아니었다** — "업무활성"은 실제로 Draft Agent의 미분류 캐치올(가맹점 키워드 불일치 기본값 + 우체국·택배·인쇄 등, `draft_agent.py` 양쪽)이었고 "회식"(팀 회식·회식비 규정)과 무관한 다른 개념이라, 기존 데이터는 `비품`(SUPPLIES)으로 흡수했다(신규 마이그레이션 `settlements/0007` — Settlement.category/ai_category는 UPDATE, TeamBudget은 `(team,year_month,category)` 유니크 충돌이라 DELETE 후 재시드 의존). 회식 규정 그래프("회식비 검증 그래프")도 `scope="식대"`(회식이 MEAL 별칭이던 시절의 흔적)에서 `scope="회식"`으로 이전(`seed_rules.py`) — 순수 식대 정산이 더는 회식 전용 룰에 안 걸린다. TEST 픽스처(구조 검증용, 규정 근거 없음)는 이제 진짜 카테고리가 된 "업무활성" 자리를 못 빌려 써서 `scope="TEST_DEMO"`로 이동 — `RuleGraph.ck_rulegraph_scope` DB CHECK 제약이 `Category.values` 기반이라 임의 문자열은 원래 거부되므로, 제약에 `TEST_DEMO`를 명시적 sentinel로 추가(`policies/models.py`). **마이그레이션 시퀀싱 함정 2개 실측**: ① 제약을 최종 상태로 한 번에 바꾸면 아직 구값(`업무활성`)인 기존 행 때문에 `AddConstraint` 자체가 `IntegrityError`로 실패 → 넓히기(0009, 구값+신값 동시 허용)→데이터 이관(0010)→좁히기(0011) 3단계로 분리 ② TeamBudget 유니크 제약 충돌(위 참조). `rule_agent_v0/api.py` Scope Literal·`agent.py` DEFAULT_QUERIES도 동기화(회식 유효, 업무활성 제거) — 이 두 파일은 직전 세션에 반대 방향으로 "정정"했던 이력이 있다(`GAPS.md` D-7, 그때는 사실이 아니었고 지금은 맞다). 실측: Django 테스트 56건 통과, 프론트 `tsc -b && vite build` 통과, `seed --fresh` 재시드 확인(TEST 그래프명 자동 갱신) |
| Review List v0 | ✅ 백엔드·프론트 독립 구현 완료 | `rule_agent_v0`와 동일 명명 규칙의 격리 서브패키지 `apps/core/domain/risk_review_v0/`(신규 모델 없음 — `Settlement`/`RiskReview` 운영 모델 그대로 import) + `apps/web/src/risk_review_v0/`(별도 라우트 `/risk-review-v0`, Sidebar 미연결). `GET reviews/`(IN_REVIEW, anomaly_score 내림차순) · `POST reviews/<id>/decision/`(기존 `services.review` 재사용 → decision_labels 적재는 그 서비스가 이미 함, 신규 로직 없음). 권한은 `CanAccountingReview` 그대로 적용(스킵 안 함). 실측: `Client().force_login()`으로 회계(acc, 200)·일반사원(kim, 403×2) 확인, APPROVE→PENDING_CONFIRM·RETURN(사유 없으면 400→사유 있으면 RETURNED) 실제 `decision_labels` 행 생성 확인, 목록 정렬(0.94→0.0) 확인. 프론트 `tsc -b && vite build` 통과. **v0→v1 전환 시 남은 일**: θ_anomaly 컷오프 적용 여부 결정, feature_contribs 실값(재학습 시), 메인 URL/네비게이션 정식 편입, 기술명세서에 엔드포인트·스키마(신규 `RiskReview.stage2_verdict` 필드 포함) 정식 반영 |

다음 후보: 도메인 모델·마이그레이션 → 정산 상태전이 서비스 → Draft Agent(비전) → Risk Review 2단계 실동작.

---

## 4. 프로젝트 컨텍스트 구조 (llm_wiki) — 에이전트 자동 생성·활용

`llm_wiki/`는 이 프로젝트 컨텍스트의 **단일 진실 원천(SoT)**. 에이전트/Claude는 **`llm_wiki/_index.md`(색인)를 세션 시작 시 먼저 읽고**, 컨텍스트를 바꾸면 해당 문서와 색인 행을 함께 갱신한다.

```
llm_wiki/
├── _index.md            ← 컨텍스트 색인/매니페스트 (에이전트가 읽고 갱신하는 진입점)
├── docs/                ← 팀이 관리하는 기준 문서 — SoT (권위 범위·버전·상태는 _index.md 표)
│   ├── 요구사항_명세서.md
│   ├── 기술명세서.md
│   ├── 기획_확장안.md
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

- 외부 참조(레포에 없음): WBS.xlsx(2026-07-20~09-03), 프로젝트 기획서, 수집 데이터 보고서(AI Hub 합성데이터 벤치마크), 법인카드 사용 규정 `TIGER-REG-2026-003`.

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

# RAG 인덱싱 (관리자 온디맨드 배치) — 파싱덤프→교정→청킹→임베딩→Chroma upsert
#   덤프(docling_eval/)는 레포 루트라 컨테이너엔 /data/docling_eval:ro 로 마운트된다.
#   ⚠️ Git Bash는 `/data/...`를 윈도우 경로로 바꿔버린다 → PowerShell을 쓰거나 MSYS_NO_PATHCONV=1.
docker compose exec ai python -m app.rag.embedding.index --dump /data/docling_eval/output --dry-run  # 라우팅만(무과금)
docker compose exec ai python -m app.rag.embedding.index --dump /data/docling_eval/output            # 실적재(OpenAI 과금)
docker compose exec ai python -m app.rag.embedding.index --peek                                      # 적재 현황

# Django (core)
docker compose exec core python manage.py migrate
docker compose exec core python manage.py createsuperuser
```

---

## 7. 규약

- 코드/주석은 주변 코드의 밀도·스타일에 맞춘다. 각 stub 파일 docstring에 대응 문서(§ 참조)를 남긴다.
- 요구사항/화면 변경은 §4 문서에 먼저 반영 후 코드에 반영(문서가 SoT).
- 개인 로컬 환경 노트·명령 tip은 `CLAUDE.local.md`(git 미추적) 참고.
