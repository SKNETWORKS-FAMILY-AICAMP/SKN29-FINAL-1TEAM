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
- **상태머신(FR-ST-01)** — 4단계: **① 개인 보유(`DRAFT`) → ② 팀 취합(`TEAM_COLLECTING`/`TEAM_RETURNED`/`TEAM_REJECTED`) → ③ 회계 제출·룰엔진(`SUBMITTED`/`RPA_JUDGED`) → ④ 회계 검토·확정(`PENDING_CONFIRM`/`RETURNED`/`IN_REVIEW`/`REJECT`/`CONFIRMED`/`ERP_VOUCHER_DRAFTED`)**. **팀 수준 보완/반려(`TEAM_*`, 팀장)** 와 **회계 수준(`RETURNED`/`REJECT`, 회계)** 은 별개 상태. `REJECT`=회계 최종반려(재제출 불가). 제출=2단계(개인 올림 `raise_to_team`: `DRAFT→TEAM_COLLECTING` / 팀 제출 `submit`: `TEAM_COLLECTING→SUBMITTED`), 1인 팀도 동일 경로. ✅ **구현 반영**: ① `DRAFT→SUBMITTED` 직행 제거·S-01 "팀에 올림" ② 계정과목=비용분류(`Category`) 매핑 `policies/scope.normalize_scope` ③ **엔진 scope 연결 완료** — `services.judge()`가 더 이상 "활성 그래프 없다고 보고 무조건 IN_REVIEW"가 아니라 `domain.policies.orchestrator.judge()`(GLOBAL 게이트→scope 그래프)를 실행해 실제 `RuleHit`을 남기고 PASS/REJECT/RETURN/REVIEW에 따라 분기한다(REVIEW·그래프 없음만 IN_REVIEW). 🚧 남음: `/submit` 팀 동일성 배치 강제(Open #8). (기술 §3.3 / 요구사항 FR-ST-05·Open #8~9)
- **예산·정책은 통제(차단)가 아니라 지표·추천으로만** 반영.
- **사람 확정 원칙**: 확신 통과 건도 회계 담당자 확정 없이는 CONFIRMED 불가.
- 영수증은 별도 OCR 없이 **OpenAI 비전**으로 직접 판독. Rule 적용은 결정론적 엔진, LLM은 Rule 생성 단계에서만.
- **가맹점 업종 구분 시스템**: 자체 DB 캐시 → 카카오 지도 API → 웹검색 캐스케이드로 업종 판별 → 비용분류 **보조 힌트**로만 사용(세무 판단 아님). 표준 업종코드(MCC)는 카드사 제휴 **post-MVP** 확장. (기술 §7-1 / 요구사항 §6.5 / FR-DA-03a~c)
- **룰은 사전 탑재하지 않는다 — 기본 게이트 1개 + 문서에서 생성**: 제품이 미리 준비해 제공하는 것은 **`DEFAULT GATE` 하나**뿐이며, 특정 회사 규정에 종속되지 않는 **범용 default 룰**로 고도화한다. **카테고리별 세부 룰은 고객이 자사 규정 문서를 업로드하면 Rule Agent가 생성**한다(RAG 조항 추출 → 초안 → 시뮬레이션 → ACTIVE 승인). `법인카드_사용규정_기반_RULE_명세서.md`의 58 RULE과 `seed_rules`의 4개 계열 그래프는 **참고용 예시·시연용**이지 기본 제공물이 아니다.
- **룰 도메인 = 그래프(트리)**: 단건 룰은 `condition+action+next_routings` 노드, 조립된 **룰 그래프(RuleGraph)** 가 최종 상태 도메인. **ACTIVE·버전관리·시뮬레이션·롤백은 그래프 단위**. (기술 §3.1·§4.2 / 요구사항 FR-RB·FR-RV·FR-RA)
- **룰엔진 = 3단 파이프라인**: ① `build_rule_context(tx_id)`로 **EvalContext(facts 스냅샷)** 조립(모든 I/O·데이터 접근은 여기서만) → ② 그래프 선택(**필수 게이트 GLOBAL → 계정과목별 scope**) → ③ **결정론적 순회**(엔진은 EvalContext만 참조, 외부 I/O 0). 조건은 **JSON-Logic류 DSL**(임의코드 금지). context는 `rule_hits.eval_context`에 스냅샷 저장 → 재현·감사. 상세: `llm_wiki/_context/rule-engine.md`. (기술 §4.2(d) / 요구사항 FR-RA-08~10)
- **인가 = 기능 단위(Capability) RBAC**: 역할이 아니라 6개 Capability(`team_aggregate`·`accounting_review`·`rule_view`·`rule_activate`·`governance_view`·`ai_lab`)로 판정. **유효능력 = 역할 기본값 ∪ 개인 추가부여(`users.extra_capabilities`)** — 예: `acc`=회계+룰열람+팀취합, `acclead`=회계+룰열람+룰활성. 룰콘솔은 열람(`rule_view`)/활성(`rule_activate`) 분리. DRF `HasCapability` 파생 권한으로 백엔드 강제, `/api/me`에 `capabilities` 노출, 프론트는 `useCan()`로 게이트. **Django admin에서 사용자별 `extra_capabilities` 체크박스 부여**. (기술 §3.1a)

---

## 3. 상태 보드 (Status Board) — _최종 갱신: 2026-08-14_

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
| RAG PDF 파싱 파이프라인 | ✅ P0/P1 구현 완료 | 전략 캐논 `llm_wiki/_context/pdf_parsing_strategy.md`(docling 기반으로 전면 재작성, 구 PyMuPDF+pdfplumber 수제안 폐기). `apps/ai/app/rag/parsing/` — engine(docling+pypdfium2 2단 폴백) → profile(REGULATION/LAW/DIAGRAM/GENERIC) → corrections C1~C7 → `ParsedDoc`. **실측 결과**: 고아 항/호 마커 95→0 · 법령 원문자 항 자동번호 882→0 · 장/조 순서 11종 전건 정합(장 미귀속 조 1건) · 자간 667→372(△44%) · 요소 소실 0. 회귀 테스트 66건 통과(`tests/test_parsing_corrections.py`) — **docling 재실행 없이** `docling_eval/output` 덤프 4,388요소에 교정만 걸어 고정. 구현 중 초안 3건을 실측으로 정정: ① 장 밀림의 원인은 **페이지 최상단 요소가 그 페이지 끝 순서로 배치**되는 것(위반 21/4,388) → 조 번호 역산이 아닌 기하 리딩오더 복구 ② 고아 마커는 **자기 자신의 번호**(다음 항 아님) ③ HTML escape 846건은 docling `export_to_markdown()` 산물이라 우리 경로엔 없음. **남음**: GT 8종 대비 재채점, 자간 잔존(법령 341건), furniture 147건 육안 검수 |
| RAG 청킹 전략 | ✅ 구현 + 평가 완료 | 전략 캐논 `llm_wiki/_context/chunking-strategy.md` · 평가 노트북 `docling_eval/chunking_evaluation.ipynb` → `output/chunking/`. **자르는 단위는 문자 수가 아니라 조(條)** — 실측이 근거다(문단 요소 중앙 **76자**·61%가 100자 미만 → 요소 단위 불가 / 조 블록 381개 중앙 **449자**, 1,200자 컷이면 **79%가 통째로** 남음 / 항 서브블록 p90 **420자** → 안전한 2차 분할선). 분할 사다리 `조→항→호→문장→문자`. 표는 **언제나 독립 청크**(한도표가 룰 임계값 원천), 별표는 조 밖 형제, 오버랩 대신 **계층 헤더+부모 확장+이웃 링크**. 📏 전략 비교: Fixed 800자는 조 경계 위반 **190건**·표 파손 29건, Recursive는 중앙 **114자**로 과분할, 우리 안은 각각 **1·0**. 📏 산출 **888청크**(부모 89), 중앙 290자·p90 956, 커버리지 **100%**·유실 0·중복 0·인용 100%·표 행보존 100% → **종합 98.5/100**(검색 성능은 N/A). `apps/ai/app/rag/chunking/` + 회귀 175건(전체 241건). **✅ 결정대기 ④ 해소**: 항/호 호칭을 프로파일이 아니라 **조 단위**로 판정(기본 `항`, 도입부에 `각 호`가 있는 조만 `호`, 법령은 예외 없이 `항`) — 규정이 자기 항목을 인용할 때의 표기를 역산한 실측이 근거이고, 이전 구현은 규정의 조 27개 중 **26개에서 틀린 호칭**을 회계 담당자 화면 인용에 쓰고 있었다. **`Budget` 정합 가드**(`0 < min_merge < target < max <= hard`) 추가 — `--max`만 주면 target이 기본값으로 남아 채우기 목표가 죽는 사고를 막고, 덤으로 §10.2 스윕의 "파편 91→103, 원인 미확인"이 **코퍼스가 아니라 `max > hard` 조합 탓**(hard가 도달 불가가 됨)이었음이 드러나 91로 정정됐다. **잡은 결함 4건**: ① 법인세법 표지가 통째로 `제55조의2`로 오인용 ② 항 범위 역순(`제3~2항`) ③ **덤프/운영 `grid` 계약 불일치**(C5가 무관한 표를 병합·텍스트 파손 → “최대 89행 표” 거짓 통계의 원인) ④ **법령의 조는 heading이 아니라 paragraph로 시작하는 경우가 많아** 앞 조에 흡수돼 남의 조문으로 인용되고 있었다(**64건 → 2건**) — 평가 노트북이 잡았다. **남음**: Chroma upsert, 검수 시트 40건 (임베딩 모델·정답셋 30건은 아래 행에서 해소) |
| RAG 임베딩 전략 | ✅ 평가 완료 / 🔲 upsert 미착수 | 전략 캐논 `llm_wiki/_context/embedding-strategy.md` · 평가 노트북 `docling_eval/docling_embedding_strategy.ipynb` → `output/embedding/`(결과 25종+벡터, 순위표 `ranking.csv` 포함). **청킹 §11 결정대기 ①② 해소**. **공급자는 OpenAI로 결정**된 상태에서, OpenAI 4변형(3-large 네이티브/1024/256 · 3-small) + 로컬 기준선 3종을 같은 코퍼스(799 잎청크)·같은 정답셋(30건)으로 실측 → **`text-embedding-3-large` @ `dimensions=1024`** 확정(문서입력=**헤더+본문**(현행 `embedding_text()` 유지), 질의=`사내 규정 조문 검색:` 접두, cosine, 배치 128). 📏 MRR .906 · R@1 .817 · R@5 .950 · nDCG@10 .916 · 표 R@5 1.00. **정답셋 30건 신설** — 6유형 5건씩, 정답은 **조문 ID**(`문서명\|조 라벨`)라 청킹 예산이 바뀌어도 무효가 안 된다. **차원 1024를 고른 근거**: 네이티브 3072 대비 ΔMRR **−0.006**(CI가 0 포함=잡음)인데 **R@1은 오히려 높고**(.817 vs .800) **저장 9.8→3.3MB(−67%)**. 256은 ΔMRR −0.091(CI 0 제외)로 **실제 손실** = 하한 확인, 3-small도 MRR .782로 명확히 낮다. **평가 방법에서 잡은 함정 4개**: ① `Recall@5`가 105조합 중 3개에서 1.000 → **천장에 붙어 변별력 상실**. 첫 실행이 실제로 이 지표로 정렬해 **엉뚱한 모델을 승자로 뽑았다** → 선정 기준을 `MRR→R@1→nDCG`로 고정 ② 상위 입력 전략들이 ΔMRR 0.0008~0.017 → 잡음으로 구현을 바꾸지 않도록 **동률 규칙**(Δ<0.01이면 기존 유지) 도입, **모델 선택에도 적용**(동률이면 차원 작은 쪽) ③ 질의 30건이라 부트스트랩 CI 필수 — 후보 1·2위도, 후보와 기준선도 **CI가 0을 포함**한다 ④ `| tail`이 nbconvert 실패를 exit 0으로 가려 **실패한 실행을 성공으로 착각**했다(이후 `set -o pipefail`). 실측 부수 소득: **본문만 임베딩(`A_content`)이 전 모델에서 꼴찌** — 계층 헤더 주입이 평균 MRR을 +0.050 움직인다(청킹 §5의 근거). 📏 한국어는 cl100k_base에서 토큰 1.6배(358 vs 223) — 전량 인덱싱 1회 306,566토큰, 단가 미확인이라 금액은 N/A. ⚠️ **기준선 `bge-m3`(자체 서빙)가 MRR .933으로 더 높다**(ΔMRR −0.028, CI [−0.100,+0.044]로 0 포함). 공급자 결정이 먼저였으므로 이 표가 그 결정을 정당화하진 않는다 — **격차는 재검토 트리거로 기록**. **남음**: 정답셋 사람 검수·난이도 보강(사용자 말투 질의·같은 조 항 구분 질의), 청킹 A~E 검색 비교(§10.4), Chroma upsert |
| 이상탐지 실학습/RAG upsert | 🚧 이상탐지 서빙 연동 완료 / RAG 미착수 | `apps/ai/app/ml/`에 확정 하이퍼파라미터·15개 피처 파이프라인(`features.py`)·decile 보정표·고정 임계값(`calibration.py`) 이식 + 오프라인 배치 학습 스크립트(`train.py`, 관리자 CLI 실행) 연결 완료. `registry.py`가 학습된 모델·threshold·calibration_table·`fill_values`를 pickle로 저장/로드. **`get_tx_features` 실연동 완료**: Django `transactions/features.py::build_tx_features`가 카드별 과거 거래 집계(최근7일사용횟수·확장 통계 등)를 조립해 `/api/internal/tx-features/<tx_id>/`로 노출 → FastMCP `get_tx_features`가 `app.ml.features.build_feature_matrix`(카테고리 고정 원-핫)로 변환 후 활성 모델의 `feature_columns`에 정렬. `ml_infer`에 형상 검증(빈 벡터·컬럼 수 불일치 시 명시적 에러) 추가. `일시불할부구분코드`(카드사 원천 필드, SoR에 없음)는 실거래는 `_`(결측 센티널) 기본값, 시드는 학습 데이터 관측 분포로 랜덤 배정. 실측: 학습 파이프라인 산출 24컬럼(원-핫 후, 기존 문서상 "23"은 오기)과 단건 서빙 벡터 컬럼 순서 일치 확인(`train.py`+`get_tx_features` 도커 컨테이너 실측 검증). RAG upsert는 그대로 미착수 |
| 가맹점 업종 구분 시스템 | 📄 문서화 완료 / 🔲 구현 미착수 | 3개 명세 반영. `classify_merchant` Tool·`merchant_categories` 캐시·카카오/웹 연동 필요 |
| 룰 그래프(트리) 도메인 | ✅ 1차 완료 | scope별 버전·DRAFT 복제/원복·노드 삭제·자동 저장·**DSL 쉽게보기(`RuleNode.condition_text`)** 에 더해 **검증 시뮬레이션 도메인**(`RuleTestCase`/`RuleSimulationRun`/`RuleSimulationResult` — 실행 스냅샷+해시 보존, 낡은 결과 표시)과 **승인 흐름**(Active 요청 시 검토자 코멘트·스코프당 승인대기 1건 제한, 활성자/검토자 추적, 버전 이력 롤백) 구현. 구조 시각화는 위→아래 스크롤 플로우차트(순환 감지 포함) |
| 화면 임시 비활성화 | ✅ 해소 | 규정 문서 관리(`/policy-docs`)는 실 API 연동 완료로 메뉴·라우트 복구(capability `rule_view`). mock `policyDocuments`는 제거 — 적재 상태는 백엔드가 실제로 진행시키는 값이라 흉내낸 데이터가 오해를 만든다 |
| 비전 판독 Tool 2종 | ✅ 구현 완료 | `app/vision/` — ① `read_receipt` 영수증(사진·캡처·PDF전표) → **사용내역 + 판정 사실**, ② `read_evidence_document` 증빙문서 → 판정 사실만. 둘 다 MCP tool로 노출(§5). **품목까지 읽는 이유**: 총액엔 없는 사실이 거기 있다(주류 유무→`dining.includes_alcohol`, 세부유형→`category.item_type`). **PDF도 이미지로 렌더**(`pypdfium2`) — 텍스트만 뽑으면 결재 도장·서명이 통째로 빠져 "승인받았는가"를 판별할 수 없다. **관측 계약이 핵심**: 스키마를 "선택적 키 객체"가 아니라 **관측 목록(array)** 으로 둬서 **넣지 않는 것이 기본값**이 되게 했다 — 「확인했는데 없음(false)」과 「안 봤음(경로 없음)」이 섞이면 미해소 가드가 잡아야 할 걸 놓친다. 종류별 허용 경로를 프롬프트·후처리 양쪽에서 제한(회의록에서 출장 지역등급을 찾게 두면 지어낸다), 근거 문구(`quote`) 없는 추출은 버린다. 출력이 `Attachment.extracted`/`field_confidence`/`evidence_spans`와 **같은 모양**이라 변환 계층 없이 저장된다. 파일 경로는 `app/media.py`가 단독 소유 — **절대경로·`..`를 잘라내지 않고 거부**(앞 슬래시만 떼면 요청과 다른 파일을 조용히 열어준다). 회귀 11건 |
| 시연용 초기 상태 시드 (`seed_clean`) | ✅ 구현 완료 | `seed`와 **정반대 목적** — "제품을 막 설치한 회사" 상태(사용자·팀·카드 + `DEFAULT GATE` 1개, 정산·규정문서·과목별 룰 0건). 규정 업로드 → Rule Agent 생성 흐름을 처음부터 시연할 때 쓴다. **기본 게이트 설계가 핵심**: 회사 규정이 없는 상태라 한도·기한 같은 **정책 판단을 넣을 수 없다**(`policy.*`는 회사 별표에서 오는데 신규 설치엔 없음 → 미해소 가드가 **전건 REVIEW 강등** → 게이트 무용지물). 그래서 정책이 아니라 **기록 완결성**만 본다: 증빙(RETURN)·목적(RETURN)·가맹점업종(REVIEW)·분류신뢰도(REVIEW)·PASS. **참조 필드는 조립기가 항상 채우는 것만** 골랐다 — `card.actual_user_recorded`는 공용카드에서 `None`(모름)이 대부분이라 참조하면 공용카드 건이 전부 REVIEW로 떨어져 제외. 심야·주말·고액 같은 이상 신호는 **일부러 뺐다**(Risk Review의 일이고 회사마다 정상 범위가 달라 범용 룰이 될 수 없다). 로그인 계정은 `seed`와 동일(kim/lead/acc/acclead/exec, pass1234) — 시드를 갈아끼울 때 헤매지 않게. 회귀 12건(정상 건 **강등 없이 PASS** 확인 포함) |
| 시연 시드 데이터 | ✅ 완료 | 룰 그래프 4계열(GLOBAL v1~v3·기업업무추진비 v1~v2·회식비 활성+초안·출장비 승인대기) + 작성 대화 로그, 정산 87건(회계팀 자체 지출 포함)·검토 대기 30건·검토 이전처리 10건, 하이라이트 3건은 RAG 검증 보고서(마크다운)+실제 EvalContext 스냅샷(`rule_hits`). **모든 거래일자는 이번 달 1~30일 안에 배치**(`seed.at()`) — 팀 통계·검토 이력의 "이번 달" 필터와 정합. **회식(GATHERING) 규정 검증 시연 3건 추가**(`_judge_dining_demo`) — 하드코딩 상태가 아니라 `services.judge()`(진짜 Rule Agent 오케스트레이션)로 실제 판정: 1인당 4만원·2차 아님(PASS→자동 `PENDING_CONFIRM`) / 1인당 15만원(한도 초과 M-001 REVIEW→`IN_REVIEW`) / 2차 결제(M-002 REVIEW→`IN_REVIEW`, 이어서 Risk Review Agent 2차 실호출까지 태워 `stage2_verdict` 실제 LLM 응답 확보). **실측 함정**: `upsert_policy_tables()`가 원래 시드 맨 끝에 있어서 이 판정 시점엔 `policy.dining_per_person_limit`이 미해소라 3건 전부 REVIEW로 강등됐다 — `PolicyTable` 적재를 `seed_rules` 직후·판정 직전으로 이동해 해결(기존 `_enrich_demo_cases`는 EvalContext를 수기로 채워써서 이 순서 의존성이 가려져 있었을 뿐, `build_rule_context`를 실제로 타는 경로는 원래도 이 순서가 필요했다) |
| 화면 데이터 스코프 규약 | ✅ 정리 완료 | "이번 달" 경계는 `web/src/lib/period.ts`에서만 정의(하드코딩 월 상수 제거). **S-01 내 지출**=오늘이 속한 달(단순 월 기준, 일자 무관). **S-02 팀 통계 대시보드**(KPI·예산)=팀·이번달·`REJECT` 제외 **전 상태** / **S-02 취합 목록**=팀·이번달·`TEAM_*`만. **S-03 이전 처리**=이번 달 회계 결정 완료 건(`api/settlements.ts:REVIEW_DECIDED_STATUSES`) |
| 팀 예산(TeamBudget) 정합 | ✅ 수정 완료 | 한도만 DB, 사용액은 팀·월·`REJECT` 제외 Settlement 집계(`TeamBudgetView`). **불변식 2개**: ① 팀 총한도(`category=''`) = 과목 한도 합 ② 과목 사용 합 = 총 사용액. 시드는 실제 집계에서 한도를 역산(`seed.py` BASE_USAGE_RATE)해 내역이 바뀌어도 어긋나지 않게 하고, **6개 과목 전부** 예산 행을 만든다(과거 `업무활성` 누락으로 항목 합 ≠ 총액이었음). 예산 행 없는 과목 지출은 API `unbudgetedUsed`로 노출 |
| 규정 임계값(policy) 도메인 | ✅ 전면 재구축 완료 | **원인 결함**: 초기 `Policy`(category·limit 스칼라 1개) 모델과 룰엔진 `ctx.policy.*` 카탈로그가 서로 모른 채 자라 필드가 하나도 안 겹쳤고, 조립기 부재로 `ctx.policy.*`가 전량 `null` → DSL이 null 비교를 `False`로 흡수해 **실 정산 경로에서 한도 룰이 조용히 미발동**했다(검증셋·시연 3건만 facts 수동 주입으로 동작). **조치**: ① 저장층 **`PolicyTable`**(별표 원본 자유 JSON `payload` + `key_axes` 축 선언, 개정은 `effective_date` INSERT) ② 소비층 **`ctx.policy.*` 고정 카탈로그 13종**(`gift_type`→`category.item_type` 이관, 누락 임계값 6종 승격, `biz_days_over_7`·`*_3m` 등 **필드명 상수 제거**, 스키마 v2) ③ 해소 규약 `policies/context_builder.py`(`RESOLVERS`·와일드카드 폴백·`ctx.tables` 원본 보존) ④ **미해소 가드** `UNRESOLVED_POLICY_VAR` → REVIEW 강등 ⑤ SoT 일원화(`draft_agent.THRESHOLDS`·시드 DSL 리터럴 제거 → 값은 `policies/tiger_tables.py` 한 곳). 내부 read API `/api/internal/rule-context/<id>/` + MCP `build_rule_context` 연결. 캐논 `llm_wiki/_context/policy-domain.md` / 결과 `policy-domain-plan.md` |
| EvalContext 스키마 v3 (다이어트) | ✅ 101 → 46 필드 | **원칙: EvalContext는 '단어'(원자 사실)만, '문장'(판단)은 룰 그래프가 조합한다.** 삭제 기준 4가지 — (a) **판정 필드**(`derived.personal_use_suspected` 등 — 결론을 입력받고 있었다 → 그래프에서 조합) (b) **조합 가능**(`*_missing` 7종 → `participant_count == 0`) (c) **원천 없고 부차적**(`tx.service_charge_ratio`·`is_holiday`·`merchant_grade`) (d) **과세분화**(출장 상세 9·참석자 상세 5·승인 상세 5·세부유형 3). `tables`는 고정 목록 폐지→동적, `policy` 13→8, 금지업종 별표(`forbidden_merchant_table`) 신설. 시드 그래프도 함께 정리(E-005 봉사료·M-004 분할결제·T-101/103/104 노드 삭제). **성과: 막는 필드의 등급이 A1·B7·C1·D1 → A2·B7·C0·D0** — 남은 건 전부 컬럼 추가로 해결 가능. 조립 커버리지 34/101→24/46. 기록·미결 8건 `llm_wiki/_context/eval-context-sourcing.md` §12·§13 |
| 판정 입력 실 연동 (Settlement 컬럼 + Attachment) | ✅ 1차 완료 | **Settlement 판정 컬럼 9종 신설**(`headcount`·`external_headcount`·`pre_approved`·`actual_user(_recorded)`·`item_type`(=청탁금지 룩업 키)·`kickback_target`·`is_secondary_venue`·`includes_alcohol`) — **전부 null 허용**(None=모름 계약). **`Attachment` 모델 신설**: 첨부 종류(영수증/사전승인/회의록/참석자명단/출장계획서/계약서) + **추출 결과 틀**(`extracted`=EvalContext dot-path→값, `field_confidence`, `evidence_spans`, `extraction_status`) — 채우는 주체는 **증빙자료 추출 Agent**(`llm_wiki/_context/evidence-extraction-agent.md`, 추출 로직 미착수). 조립기가 **첨부 추출 → 화면 입력 순으로 얹고**(빈 컬럼은 추출값을 덮지 않음), 시뮬레이션 실 내역 경로도 조립기 경유로 전환. **실측: 판정 강등 93% → 31%, GLOBAL 게이트 0건.** 남은 강등은 scope 무관 전수 실행 탓이 큼(운영은 scope별 그래프 선택) |
| EvalContext 사실(fact) 조립 | 🚧 policy 축만 완료 | 미해소 가드를 **전 구간 확장**(`UNRESOLVED_FACT:<path>` 신설, `None`=거짓 아닌 **모름** 계약)하자 실제 규모가 드러남 — **판정 120행 중 112건(93%) 강등**. `policy.*` 13종은 전부 해소되는데도 그렇다: 임계값과 비교할 **사실**(참석 인원·사전승인·카드 구분 등)이 SoR에 없다. 조립 커버리지 **34/101 필드**, ACTIVE 그래프 참조 19개 중 **10개 결측**. 필드별 출처 실현 가능성을 A(데이터 있음·코드만 15)/B(컬럼·입력칸만 12)/C(도메인 신설 13)/D(빼는 게 현실적 38)로 등급화 → `llm_wiki/_context/eval-context-sourcing.md`. **다음**: `Settlement`에 컬럼 6개(headcount·pre_approved·kickback_target·actual_user·item_type·is_secondary/alcohol) + S-01 입력칸 6개면 강등 93%→~8%(추정) |
| AI-LAB (관리자 실험 화면) | ✅ Draft·RAG 완료 | AI 기능을 **정산 흐름 없이 단독 실행**하는 관리자 화면(`/ai-lab`, Capability `ai_lab`=회계팀장 기본). 5탭: 상태 점검 / ① Draft Agent(생성·수정, 요청 JSON 직접 편집, 세션 이력) / RAG 검색(top-K·부모 확장·질의 접두 토글) / 임베딩 인스펙터(cosine 행렬) / 적재 현황(청크 원본 열람). **운영과 같은 코드를 부르고**(별도 구현 금지) 결과 대신 **근거**를 편다 — 프롬프트 전문·LLM 원본 출력·토큰·지연·정책 조회 출처(실조회/폴백)·검색 점수·메타데이터. 경로 `브라우저→Django /api/ai-lab/*(프록시·인가)→FastAPI /lab/*`. 추적은 `draft_agent.run(req, trace)`의 **선택적 dict 인자**로 모아 운영 응답 셰이프를 건드리지 않는다. 실패는 폴백 없이 사유 그대로(진단 목적). Rule/Risk/증빙추출은 stub이라 "예정"으로 표시. 캐논 `llm_wiki/_context/ai-lab.md` |
| 룰 엔진 판정 동작 | ✅ 구현 완료 | **승인된 그래프가 실 정산 판정에서 돈다.** `policies/orchestrator.py` 신설 — ① **게이트 우선**(FR-RA-10): GLOBAL이 PASS가 아니면 과목별 그래프는 아예 안 돌린다 ② **규칙이 없으면 통과가 아니다**: ACTIVE 그래프 부재 → `REVIEW`+`NO_ACTIVE_RULE_GRAPH`(사람에게). 게이트만 통과 시엔 PASS 유지 + `NO_SCOPE_RULE_GRAPH` ③ **`rule_hits` 그래프당 1행**(합치면 게이트·과목 경로를 되짚을 수 없다). 그래프가 없어도 `graph=None`으로 1행 — 그때의 EvalContext가 감사 대상 ④ 상태 전이는 `services.judge`로 분리 → `record=False`로 상태 안 건드리고 재판정 가능. **`엔진은 최종반려를 만들지 않는다`** — 노드 decision이 `REJECT`여도 상태는 `RETURNED`(재제출 불가 단말을 규칙이 내리면 되돌릴 수 없다. 최종반려는 회계 담당자 `review()`만) ⑤ **제출이 판정을 자동으로 이어 돌린다** — 따로 두면 아무도 안 불러 SUBMITTED에 고인다. 판정 실패는 제출을 되돌리지 않고 `judgeFailed`로 보고, `/judge/`로 재실행 ⑥ 프론트 `submitSettlements`가 건별 실제 도착 상태를 반환(예전엔 `'SUBMITTED'` 고정 반환이라 화면이 실제와 다른 상태를 그렸다) ⑦ 스냅샷 변환을 `policies/snapshot.py`로 일원화(시드·시뮬레이터가 각자 펴고 있었다) ⑧ 검토화면 EvalContext가 **최신** 판정 스냅샷을 본다(재제출 시 옛 스냅샷을 보여주던 결함) ⑨ FastAPI `/agent/rule/apply`·`mcp run_rule_engine`은 Django 판정으로 위임(LLM 미개입, FR-RA-06). 회귀 21건 |
| Rule Agent (생성) 통합 | ✅ 전 구간 연결 | 규정 문서 → 룰 그래프 DRAFT. `룰 콘솔 Tab1 → Django /api/rules/generate/(rule_view) → FastAPI /agent/rule-v0/generate → RAG → LLM → 결정론적 조립 → 룰 콘솔 API 3종으로 저장`. **v0의 "격리 우선"이 통합 시점에 그대로 결함이었다** — ① **RAG 사본 3개 제거**: 자체 `embedding.py`/`vector_store.py`가 정본과 달라 부모 청크를 안 걸렀고(조 전문이라 top-k 잠식) 부모 확장·컬렉션 라우팅·`embedder_version`·`embedding_function=None`이 전부 빠져 있었다. 결정적으로 `RULE_AGENT_V0_CHROMA_HOST` 기본값이 빈 문자열인데 compose가 안 주입해 **docker에선 빈 로컬 DB로 조용히 폴백 → 검색 0건**(성공 실측은 전부 호스트 export 상태였음). 이제 `app.rag.embedding.store` 정본만 쓴다 ② **403의 실제 원인**: `django_client`가 보내던 Bearer 토큰을 **검증할 인증 클래스가 없었다**(DRF는 세션+SimpleJWT뿐) → 전용 서비스 계정 `rule-agent`(capability `rule_view` **하나만**) + 런타임 JWT 발급·401 시 1회 재발급. `manage.py ensure_service_account` ③ **scope 400**: 문서·`Category`·프론트·Agent가 서로 달라 `scope:"회식"`이 무조건 400이었다 → 정본을 `Category`로 확정, `create_graph`가 `normalize_scope` 경유(회식→식대) ④ `RuleGraph.generation_meta` 신설(모델·질의·근거 인용) — 다음 버전으로 **복제하지 않는다** ⑤ 죽은 코드 제거: ai 패키지 안의 Django 앱 트리(`validate_expr` 반환값을 검사해 DSL 검증을 **항상 통과**시키던 코드)·커밋된 Chroma 바이너리 423KB·`apps/main.py` ⑥ `mcp/tools.py: search_policy` 실구현(Risk와 tool 경로 공유). 회귀 12건. 캐논 `llm_wiki/_context/rule-agent-v0.md` |
| 규정 문서 업로드 → 인덱싱 | ✅ 구현 완료 | **Rule Agent의 앞단이 열렸다.** `업로드 → PolicyDoc(PENDING) → FastAPI /embeddings/ingest(202 즉시) → 백그라운드 파싱·교정·청킹·임베딩·Chroma upsert → 룰 트리거 → core 콜백`. 파이프라인 본체는 `apps/ai/app/rag/ingest.py` 한 함수 — **각 단계 로직은 이미 있었는데 서로 디스크 파일로만 이어져 있었다**(파싱 CLI가 JSON을 떨구고 임베딩 CLI가 그걸 읽는 구조라 업로드된 파일 하나를 끝까지 밀 방법이 없었다). **비동기 방식 결정**: 브로커·워커를 새로 들이지 않고 `BackgroundTasks` + 상태 폴링 — docling 파싱이 문서당 수십 초~분이라 동기는 불가, 큐는 실제 부하(관리자가 가끔 규정 몇 종)에 비해 비용이 크고 기술명세서 §6.2 "별도 Job 큐 없음"과 어긋난다. **한계**: ai 재시작 시 진행 중 작업 유실 → `PARSING`/`INDEXING`에 멈추고 "재색인"으로 복구. 인가는 `rule_view`(규정은 룰의 원천 + 임베딩 비용 + 전 판정이 인용하는 코퍼스 변경). **콜백은 인증된 쓰기** — 다른 내부 read API와 달리 AllowAny를 쓰지 않고 서비스 계정 JWT(`clients/core_auth.py`로 공용화). `doc_id`=파일 해시라 재색인이 멱등 upsert. nginx `client_max_body_size 50m`(기본 1MB로는 규정 PDF가 곧바로 413). 화면 `PolicyDocuments` 실 API 연동 + 메뉴·라우트 복구. 회귀 11건 |
| 규정 문서 화면 (S-05 v4) | ✅ 목업대로 구현 | 좌 폴더 트리(`PolicyFolder` 자기참조) / 우 **조(條) 단위 조항 아코디언**. 목업이 요구한 건 문서 목록이 아니라 "조별로 무엇이 규칙과 연결됐고 무엇을 확인해야 하는가"라, 적재 후 청크를 조 단위로 다시 모아 `PolicyClause`로 저장한다(`ingest.build_clauses` — 부모 청크=조 전문 우선, 잎만 이으면 항 잘린 자리 문맥이 어긋남). **상태는 저장하지 않는다** — `LINKED`(=`RuleNode.action.source_clause`가 인용과 일치)·`NEEDS_REVIEW`는 파생이고 저장값은 사람의 `SKIP`+사유뿐. 룰은 나중에 생기고 지워지므로 컬럼에 굳히면 곧 어긋난다. **재색인이 사람 결정을 지우지 않게** 조 라벨 기준으로 이관(`_replace_clauses`). `SKIP`은 사유 필수("왜 규칙이 없지"를 묻는 사람이 반드시 나온다). **목업 하단 "확인 필요(3)" 노란 박스는 제외** — 같은 결정을 두 곳에서 내릴 수 있으면 어느 쪽이 최신인지 모르게 된다. 「규칙 생성하기」는 룰 콘솔로 넘긴다(생성 주인은 하나). 회귀 21건 |
| Agent ↔ 프론트 연동 | ✅ 연결 완료 | **① Risk Review 호출 지점 구멍 수정** — `_run_risk_review`가 `SettlementViewSet.judge` 액션 **안에만** 있어서, 제출(`/submit/`)이 판정을 자동으로 이어 돌리게 바뀐 뒤 **정상 흐름에서 Risk Review가 통째로 안 돌았다**(수동 `/judge/`를 눌러야만 돌았다). 호출 지점이 여러 곳이면 하나는 반드시 빠지므로 `domain/settlements/risk_review.py`로 빼서 **`services.judge` 한 곳**이 소유하게 함. `transaction.on_commit`으로 커밋 후 실행 — 60초짜리 AI 호출이 판정 트랜잭션을 붙들지 않는다. AI 실패는 판정을 되돌리지 않음 **② 대화형 룰 수정 연결** — `DraftTab` 채팅이 `"네, 반영했습니다"` **고정 문구를 만들어 로그에 저장**하고 있었다(아무것도 안 고쳤는데 고쳤다고 기록 → 로그가 실제 그래프와 어긋남). `POST /api/rules/{id}/converse/` → FastAPI `/agent/rule-v0/converse` 실호출로 교체. **로그는 Agent가 서버에서 남기므로** 화면은 저장하지 않고 다시 읽는다(양쪽 저장 시 이중 기록). 수정이 반영되면 그래프도 재조회 **③ ACTIVE 대화 수정 차단** — 노드 CRUD가 DRAFT만 허용하는데 여기서 안 막으면 Agent가 툴 호출 중 400을 받고 "왜 안 됐는지 모르는" 답을 낸다 **④ 위험 검토 큐(v0) Sidebar 연결**(`accounting_review`). 회귀 10건 |
| docling 모킹 스위치 | ✅ 구현 완료 | `DOCLING_MOCK=1`이면 **파싱만** 미리 떠둔 덤프(`docling_eval/output`, 11종 4,388요소)로 대체 — docling이 깨져도 그 뒤 체인(교정→청킹→임베딩→적재→조항→룰 트리거)을 끝까지 시험할 수 있다. **새 코드 경로가 아니다**: `dump.load_all()`이 이미 `ParsedDoc`(운영 `engine.convert()`와 같은 타입)을 돌려주고 관리자 CLI가 이미 그 경로를 쓴다 → 갈아끼우는 건 `ingest_pdf()`의 분기 한 곳, 로직은 전부 `rag/parsing/mock.py`에 격리. **진짜 위험은 "켜둔 걸 잊는 것"** 이라 거기에 방어: 매번 WARNING 로그 · 화면 노란 배너(경고 맨 앞) · `dump:` doc_id로 실물 벡터와 구분 · **이름 불일치 시 폴백 없이 실패**(접두사·부분 일치 금지 — 넘겨짚으면 A 문서가 B 레코드에 적재되는 조용한 오염). 정규화는 NFC/공백만(macOS 한글 NFD 함정). 📏 실측: 법인카드 25청크·20조항 / 회식 31청크·14조항 / 법인세법 425청크·207조항(LAW→`tax_refs`). 회귀 `apps/ai/tests/test_docling_mock.py` |
| 적재 → 룰 자동 생성 트리거 | ✅ 구현 완료 | `apps/ai/app/rag/rule_trigger.py` — 적재가 끝나면 `rule_agent.generate()`를 **실제로 호출**한다(v1, 2026-08-16). 결과는 `PolicyDoc.rule_trigger`에 저장돼 규정 문서 화면에 그대로 뜬다. 순서 의존이 핵심: 적재 완료 **후**에 불려야 하고(그 전이면 검색 0건→`NO_SOURCE`), 같은 백그라운드 태스크가 체인을 소유해 그 순서가 보장된다. **켜기 전 미결이던 2건 확정**: ① 범위 = **업로드 시 고른 scope 1개만**(전 scope는 LLM 호출 곱절 + 미요청 DRAFT 누적), scope 미지정이면 `SKIPPED_NO_SCOPE`로 건너뜀 ② **재색인은 자동 생성 안 함**(`SKIPPED_REINDEX`) — 매번 새 계열이 생기면 룰 콘솔이 초안으로 뒤덮인다(기존 계열에 버전 얹는 경로 미구현). Django `policy_doc_views._dispatch`가 `create`/`reembed` 경로를 보고 `isReindex`를 정확히 넘긴다. 트리거 실패는 **적재를 실패로 만들지 않는다**(문서는 이미 검색 가능, 룰은 수동 재시도 가능) |
| 기능 단위(Capability) RBAC | ✅ 백엔드+프론트 완료 | `Capability` 4종·`extra_capabilities`·`HasCapability` 권한·`/api/me` 노출·seed 반영. 프론트: `useCan()`로 Sidebar·팀취합·검토·룰활성 게이트 전환(role 문자열 제거). mock은 역할 기본값, 실 모드는 `/api/me` capabilities |
| Rule Agent → IN_REVIEW 자동이관 연결고리 | ✅ 구현 완료 | **원인 결함 해소**: `services.judge()`가 Rule Agent(`run_rule_engine`)를 한 번도 호출하지 않고 "활성 그래프가 없다고 보고" 무조건 IN_REVIEW로 보내는 하드코딩 placeholder였다(FR-RA-04 앞쪽 절반 부재 — settlement 113/114/115가 IN_REVIEW인 것도 seed.py가 상태머신을 안 거치고 직접 꽂아 넣은 시드였음, `SettlementEvent` 부재로 확인). `domain/policies/orchestrator.py::judge()`가 GLOBAL(ACTIVE) 게이트 먼저 실행 → PASS 아니면 그 결과가 최종 → PASS했거나 GLOBAL 자체가 없으면 scope(`normalize_scope(category)`) ACTIVE 그래프 실행 → 둘 다 없으면 IN_REVIEW. 실행마다 `RuleHit` 기록. `services.judge()`가 이걸 호출해 `RPA_JUDGED→{PENDING_CONFIRM,REJECT,RETURNED,IN_REVIEW}`로 실제 분기. 실측: settlement 51(식대, GLOBAL이 `PERSONAL_USE_SUSPECTED`로 REVIEW 판정 → scope 그래프 안 감·IN_REVIEW), settlement 58(업무활성, GLOBAL PASS이나 scope 그래프 없음 → IN_REVIEW), settlement 123/118/114/82/79(식대, GLOBAL+scope 둘 다 PASS → PENDING_CONFIRM) — 세 갈래(REVIEW 실판정·그래프부재·자동승인) 전부 실제 HTTP `/api/settlements/<id>/judge/` 경로로 확인, IN_REVIEW 귀결 시 Risk Review 자동호출(`stage2_verdict` 저장)까지 이어짐 |
| Category "업무활성"→"회식" 리네임 | ✅ 완료 | 팀 확정(2026-08-14, `Category.OPERATION("업무활성")`→`Category.GATHERING("회식")`, 같은 enum 슬롯 재사용). **단순 문자열 치환이 아니었다** — "업무활성"은 실제로 Draft Agent의 미분류 캐치올(가맹점 키워드 불일치 기본값 + 우체국·택배·인쇄 등, `draft_agent.py` 양쪽)이었고 "회식"(팀 회식·회식비 규정)과 무관한 다른 개념이라, 기존 데이터는 `비품`(SUPPLIES)으로 흡수했다(신규 마이그레이션 `settlements/0007` — Settlement.category/ai_category는 UPDATE, TeamBudget은 `(team,year_month,category)` 유니크 충돌이라 DELETE 후 재시드 의존). 회식 규정 그래프("회식비 검증 그래프")도 `scope="식대"`(회식이 MEAL 별칭이던 시절의 흔적)에서 `scope="회식"`으로 이전(`seed_rules.py`) — 순수 식대 정산이 더는 회식 전용 룰에 안 걸린다. TEST 픽스처(구조 검증용, 규정 근거 없음)는 이제 진짜 카테고리가 된 "업무활성" 자리를 못 빌려 써서 `scope="TEST_DEMO"`로 이동 — `RuleGraph.ck_rulegraph_scope` DB CHECK 제약이 `Category.values` 기반이라 임의 문자열은 원래 거부되므로, 제약에 `TEST_DEMO`를 명시적 sentinel로 추가(`policies/models.py`). **마이그레이션 시퀀싱 함정 2개 실측**: ① 제약을 최종 상태로 한 번에 바꾸면 아직 구값(`업무활성`)인 기존 행 때문에 `AddConstraint` 자체가 `IntegrityError`로 실패 → 넓히기(0009, 구값+신값 동시 허용)→데이터 이관(0010)→좁히기(0011) 3단계로 분리 ② TeamBudget 유니크 제약 충돌(위 참조). `rule_agent_v0/api.py` Scope Literal·`agent.py` DEFAULT_QUERIES도 동기화(회식 유효, 업무활성 제거) — 이 두 파일은 직전 세션에 반대 방향으로 "정정"했던 이력이 있다(`GAPS.md` D-7, 그때는 사실이 아니었고 지금은 맞다). 실측: Django 테스트 56건 통과, 프론트 `tsc -b && vite build` 통과, `seed --fresh` 재시드 확인(TEST 그래프명 자동 갱신) |
| Review List v0 → 검토 워크스페이스 흡수 | ✅ 제거·통합 완료 (2026-08-16) | v0는 `rule_agent_v0`의 격리 관례를 따라 **의도적으로 독립 구현**된 것이었다(옛 디자인 잔재 아님 — `594beb9 리스크 리뷰 에이전트 v0`에서 신규 생성). 하지만 **회계 검토 = Risk Review = 기존 검토 워크스페이스(S-03)** 라 같은 큐를 두 화면이 처리하게 됐고, 결정 경로도 둘로 갈렸다. 그래서 `apps/core/domain/risk_review_v0/`·`apps/web/src/risk_review_v0/`·`/api/risk-review-v0/*`·Sidebar 항목을 **전부 제거**하고 S-03로 흡수했다. **흡수하며 옮긴 것**: v0에만 있던 2차 판정 `violation_verdict`(VIOLATION/NO_VIOLATION/INSUFFICIENT_INFO)를 `SettlementSerializer.violationVerdict`로 승격 — 권고(`aiRecommendation`)와 **다른 축**이라 빠지면 `INSUFFICIENT_INFO`(판단 보류)가 "문제없음"으로 보인다. S-03 「② RAG 내규 검증」에 판정 배지 + 보류 시 경고 배너 추가. 나머지(anomaly_score 정렬·feature 기여도·RAG 근거·결정 API)는 S-03가 이미 갖고 있었다. 회귀 5건 |

다음 후보: **Risk Review 2단계 실동작**(판정이 `IN_REVIEW`로 넘긴 건을 이상탐지→RAG 내규검증으로 잇기 — 지금 판정이 실제로 돌기 시작해 이 큐가 채워진다) → **규정 문서 업로드→인덱싱 파이프라인**(Rule Agent 앞단) → Draft Agent(비전).

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

# Django (core)
docker compose exec core python manage.py migrate
docker compose exec core python manage.py createsuperuser

# 시드 — 목적이 정반대인 둘 중 하나를 고른다
#   seed        시연 데이터 한가득(정산 87건·룰 4계열·규정 하이라이트). 화면을 채워 보여줄 때
#   seed_clean  **막 설치한 회사** 상태(사용자 + DEFAULT GATE 1개만). 규정 업로드→룰 생성
#               흐름을 처음부터 시연할 때. 기존 데이터를 지우므로 --dry-run으로 먼저 확인.
docker compose exec core python manage.py seed --fresh
docker compose exec core python manage.py seed_clean --dry-run
docker compose exec core python manage.py seed_clean

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
