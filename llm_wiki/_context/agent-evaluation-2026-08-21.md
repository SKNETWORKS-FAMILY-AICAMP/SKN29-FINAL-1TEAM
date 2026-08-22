# Agent 정량 평가 (2026-08-21)

> **파생 컨텍스트.** 4개 Agent(Draft·Rule·Risk Review·증빙자료 추출)를 **실제 운영 코드로 라이브
> 실행**해 얻은 정량 평가 기록이다. mock·가정이 아니라 이 문서 작성 시점에 실제 docker
> 컨테이너(core·ai·db)를 대상으로 실행한 결과이며, 재현 스크립트도 함께 남긴다.
>
> **개정 이력**: 1차 작성 후 "이 테스트 방식이 답을 미리 정해놓은 순환논리 아니냐"는 지적을
> 받아 방법론을 재검토했고, 그 과정에서 Risk Review Agent의 원인 분석이 **실제로 틀렸다는 것**을
> 확인해 정정했다(§3). Evidence Extraction Agent도 더 어려운 문서로 2차 평가를 추가해 진짜 결함
> 1건을 새로 찾았다(§4). 이 버전이 최종본이다.
>
> 작성: 2026-08-21 · 평가 대상: `feature/rule-agent-v1` 브랜치 현재 상태

---

## 0. 방법론

### 0.1 무엇으로 했나 — 실행 환경과 도구

**별도 평가 프레임워크·라이브러리는 쓰지 않았다.** `httpx`(Python HTTP 클라이언트)로 **실제 돌고
있는 docker 컨테이너(core·ai·db)에 직접 요청을 쏘고**, 응답을 정답과 비교하는 파이썬 스크립트
로 전부 실행했다.

- **실행 위치**: Draft·Rule·Risk Review는 `docker compose cp`로 스크립트를 `ai` 컨테이너 안에
  복사한 뒤 `docker compose exec`로 컨테이너 내부에서 실행(→ `http://localhost:9000`,
  FastAPI에 직접 접근). 증빙자료 추출은 파일 업로드가 필요해 호스트에서 직접
  nginx(`http://localhost:8080`)로 Django에 붙였다.
- **호출 경로**: 운영 엔드포인트(`/agent/draft`) 또는 AI-LAB 엔드포인트(`/lab/rule/generate`,
  `/lab/risk/run`, 지난 세션에 만든 "운영과 같은 코드를 부르되 부작용을 감수하거나 없앤" 경로)를
  그대로 썼다. **평가 전용 구현은 두지 않았다** — 별도 구현은 평가 결과가 운영과 갈리는 순간
  의미를 잃는다.
- **이미지 생성**: 증빙자료 추출 평가용 합성 문서는 `PIL`(Pillow)로 흰 배경에 검은 텍스트를 직접
  그려서 만들었다 — 실제 스캔 문서가 아니라 손으로 만든 이미지다(§4 한계 참조).

### 0.2 어떻게 정답을 정했나 — Agent마다 신뢰도가 다르다

정답(ground truth)을 어디서 가져왔는지가 평가 신뢰도의 핵심이라, Agent마다 방식이 다르고
**신뢰도 순위도 다르다**:

| Agent | 정답 출처 | 신뢰도 |
|---|---|---|
| **Risk Review Agent** | **시스템 자체의 배포된 코드**(ACTIVE 룰 그래프 M-001/M-002 조건문 + Agent에 실제로 전달된 facts 원문을 직접 조회) | 가장 높음 — 추측이 아니라 코드·데이터가 정답 |
| Draft Agent | 내가 직접 설계한 시나리오 + "AI로 수정" 모드로 사실만 전달하는 재검증 | 중간 — 시나리오 자체가 주관적 설계 |
| 증빙자료 추출 Agent | 내가 합성 문서에 직접 기입한 값(1차: 쉬운 문서 / 2차: 세계지식·모호성·관측계약을 요구하는 어려운 문서) | 중간 — 문서가 실측이 아니라 합성 |
| Rule Agent | "정답"이 없는 생성형 과제라 정답 비교 대신 구조적 정합성(노드 커버리지·자체검증·시뮬레이션 통과율)으로 대체 | 별도 지표(정답 비교 아님) |

### 0.3 방법론에 대한 자체 비판 — 이 평가가 순환논리(데이터 누수)가 아닌지

평가 도중 "정답을 이미 알고 있는 값을 입력에 넣고 그 값이 나오는지 확인하는 것 아니냐"는
지적이 있었고, **일부는 맞는 지적이었다.**

- 처음 Draft Agent 개선안으로 "외부 참석자 수 필드를 스키마에 추가"를 제안했는데, 이 도메인에서
  "거래처 사람이 있었다"는 사실상 "접대"라는 라벨을 다른 말로 바꿔 쓴 것에 가깝다. 그 값을 넣고
  정답이 나오는지 보는 건 **데이터 누수(leakage)** 와 같은 패턴이라 재검증 방식을 바꿨다(§1).
- 증빙자료 추출 Agent의 1차 평가(9/9=100%)도 문제를 너무 쉽게(명시적 키워드·고대비 텍스트) 냈다는
  자체 비판을 반영해, 세계지식이 필요한 표현·명시적 키워드 없는 판정·관측 계약 위반 여부를 보는
  2차(강화판) 평가를 추가했다(§4) — 그 결과 100%가 아니라 75%가 나왔고, 진짜 결함도 하나 찾았다.
- Risk Review Agent는 처음부터 "시스템 코드가 정답"이라 상대적으로 누수 위험이 적었지만, **원인
  분석 자체가 틀렸다는 걸 재검토 중에 발견**했다(§3) — 겉보기 정확도 숫자보다 원인 분석의
  정확성이 더 중요하다는 걸 보여주는 사례다.

**교훈**: 정확도 숫자 자체보다 "그 숫자가 무엇을 실제로 증명하는가"를 매번 되물어야 하고,
쉬운 통과보다 **정직하게 찾은 결함이 평가의 진짜 성과**다.

### 0.4 부작용 처리

Rule Agent가 생성한 DRAFT 그래프, 증빙 추출 테스트로 업로드한 첨부파일은 평가 종료 직후
삭제해 실 데이터에 흔적을 남기지 않았다. 재현 스크립트 전문은 §6에 보존한다(레포에 커밋된
파일이 아니라 이 문서가 유일한 사본이다).

---

## 1. Draft Agent — 분류 정확도

**대상**: `POST /agent/draft`(생성 모드) 직접 호출, 12개 시나리오(6개 비용분류 × 2건).

| 지표 | 값 |
|---|---|
| 분류 정확도 | **10/12 = 83.3%** |
| 평균 확신도(confidence) | 0.78 |
| 평균 지연 | 1,482ms (p90 1,613ms) |

### 상세 결과

| 시나리오 | 정답 | 예측 | 확신도 | 지연 |
|---|---|---|---|---|
| 동네 커피전문점 소액 | 식대 | 식대 ✅ | 0.7 | 1,613ms |
| 편의점 간식 | 식대 | 식대 ✅ | 0.8 | 2,843ms |
| 팀 회식 삼겹살 | 회식 | 회식 ✅ | 0.9 | 1,528ms |
| 팀 회식 노래방 2차 | 회식 | 회식 ✅ | 0.9 | 1,569ms |
| 호텔 회의실 대관 | 회의 | 회의 ✅ | 0.8 | 1,267ms |
| 스터디카페 회의룸 | 회의 | 회의 ✅ | 0.7 | 1,468ms |
| KTX 출장 승차권 | 출장 | 출장 ✅ | 0.8 | 1,205ms |
| 공항 리무진버스 | 출장 | 출장 ✅ | 0.9 | 1,261ms |
| 생활용품점 사무비품 | 비품 | 비품 ✅ | 0.7 | 1,007ms |
| 문구점 사무용품 | 비품 | 비품 ✅ | 0.5 | 1,548ms |
| **고급 오마카세 거래처 접대** | **접대** | **회식 ❌** | 0.9 | 1,316ms |
| **골프 라운딩 접대** | **접대** | **회식 ❌** | 0.8 | 1,157ms |

### 발견한 것

오답 2건 전부 "접대"를 "회식"으로 잘못 예측했다. 프롬프트에 넘어가는 정보(가맹점명·업종·금액·
카드구분·인원)만으로는 "거래처를 접대하는 자리"와 "우리 팀 회식"을 구분할 신호가 **원천적으로
없다** — 둘 다 관측 가능한 특징(고액·소수인원·저녁시간대·유흥 인접 업종)이 겹친다.

### 재검증 — "AI로 수정" 모드에 거래처 동석 사실을 전달해도 분류가 안 바뀐다

**가설**(입력에 거래처 참석 여부가 없어서 구분이 안 된다)을 검증하려고, 운영에 이미 있는
"AI로 수정" 모드(`instruction` 자연어 지시)로 위 두 오답 건에 "B사 구매팀 최상무님도 함께
식사하셨어요" / "C사 최이사님도 동행하셨습니다" 같은 **거래처 동석 사실만**(정답 단어 "접대"는
쓰지 않음) 전달해봤다.

| 케이스 | 1차(정보 없음) | 지시(거래처 사실만) | 2차(전달 후) |
|---|---|---|---|
| 오마카세 + "B사 구매팀 최상무님도 함께 식사" | 회식 | 사실만 전달 | **회식 (그대로)** — headcount만 갱신 |
| 골프 + "C사 최이사님도 동행" | 회식 | 사실만 전달 | **회식 (그대로)** — headcount만 갱신 |
| 대조군: 삼겹살 + "전 팀원이 인사차 들름"(비거래처) | 회식 | 사실만 전달 | 회식 그대로(정상 — 외부인=무조건 접대가 아님을 확인) |

**결과: 안 바뀌었다.** 명시적 거래처 정보를 줬는데도 분류가 그대로였던 이유는 애초 가설(입력
신호 부족)이 아니라 더 앞단의 원인이었다 — Draft Agent의 수정 모드 시스템 프롬프트가
"지시에 해당하는 항목만 수정하고, 언급되지 않은 항목은 현재 값을 그대로 유지하라"고 못박고
있어서, "분류를 접대로 바꿔줘"라고 직접 요청하지 않는 한 **분류 자체를 재판단하지 않는다**
(headcount만 지시문에서 "5명"을 읽어 갱신한 게 그 증거 — 다른 필드는 실제로 반영함). 즉 신호가
없어서가 아니라, 수정 모드가 설계상 "명시적으로 요청받은 필드만" 고치도록 보수적으로 짜여 있다.

### 방법론 주의사항 — 이 재검증도 완전히 깨끗하진 않다

애초에 "외부 참석자 수" 같은 필드를 스키마에 추가해 그 값으로만 테스트하는 방식은 **데이터
누수(leakage)** 에 가깝다 — 이 도메인에서 "거래처 사람이 있었다"는 사실상 "접대"라는 라벨을
다른 말로 바꿔 쓴 것과 같아서, 그 값을 넣고 정답이 나오는지 보는 건 답을 몰래 입력에 심어놓고
모델이 그걸 읽었는지 확인하는 것과 다르지 않다. 위 대조군(비거래처 방문 시 안 뒤집힘)을 넣은
것은 이 문제를 완화하려는 장치이지만, 근본적으로 "AI가 똑똑해서 구분했다"를 증명하는 테스트는
아니고 "기능이 프롬프트까지 올바르게 배선됐는가"를 보는 테스트에 가깝다는 한계는 남는다.

---

## 2. Rule Agent — 생성 품질

**대상**: scope=`비품`으로 실제 그래프 생성 1회(`POST /lab/rule/generate`) → 자동 검증셋 생성
(`POST /rules/{id}/test-cases/generate/`) → 시뮬레이션(`GET /rules/{id}/simulation/`). 종료 후
생성된 DRAFT 그래프(id 85)는 삭제.

| 지표 | 값 |
|---|---|
| 생성 성공 여부 | 1회 시도로 성공(재시도 0회) |
| 근거 문서 수 | 6개 청크 |
| 거부된 노드(LLM이 냈지만 조립기가 반려) | 0개 |
| 노드 커버리지 | **5/5 = 100%**(도달 불가 노드 없음) |
| 자동 검증셋 생성 시도 대비 채택 | **12/16 = 75%**(4건은 조건 역산 → 재시뮬레이션 시 다른 노드로 라우팅돼 자체검증 실패) |
| 시뮬레이션 통과율(채택된 12건 기준) | **12/12 = 100%** |
| 생성 지연 | 약 67초 |

### 발견한 것 ①

자체검증 실패 4건은 전부 **금액 구간 경계 노드**(`30000_100000` ↔ `100000_300000` 등)에서
발생했다 — LLM이 초안 조건의 경계값을 살짝 겹치게 잡는 경향이 있다. 다만 이건 **자동 검증셋
생성 단계가 스스로 걸러내는 안전장치**로 정상 작동한 것이다 — 사람에게 최종 넘어가는 12건은
전부 시뮬레이션 100% 통과, 노드 커버리지 100%로 실제 시뮬레이션 보고서도 "활성화 권장(우수)"
등급을 매겼다.

### 발견한 것 ② — 시드로 배포된 실제 그래프가 원본 규정보다 좁다(§3 조사 중 발견)

Risk Review Agent 원인 분석(§3)을 위해 실제 `회식_운영규정` 원문을 RAG로 직접 검색하던 중,
**시연용으로 이미 배포된(`seed_rules`) "회식비 검증 그래프"(M-001~M-003)가 원본 규정의 일부만
구현하고 있다**는 걸 발견했다. 원본 제8조(사전승인이 필요한 경우)는 8개 트리거를 정의한다:

```
1. 건당 총액 30만원 초과            ← 그래프에 없음
2. 22시 이후(야간) 사용             ← 그래프에 없음
3. 토·일·공휴일 사용                ← 그래프에 없음
4. 거래처 등 외부인 참석            ← 그래프에 없음
5. 호텔·특급 레스토랑 등 고급 업종   ← 그래프에 없음
6. 주류 포함 + 1인당 8만원 초과     ← 그래프에 없음(M-001은 주류 무관 1인당 5만원만 봄)
7. 출장 중 회식                    ← 그래프에 없음
8. 전사 회식(금액 무관)             ← 그래프에 없음
```

그래프가 실제로 구현한 건 M-001(1인당 5만원 초과, 제14조①)·M-002(2차, 제14조③)·M-003(참석자
명단 누락, 제14조②) 세 가지뿐이다. **이건 이번에 평가한 "비품" 생성과는 무관한, 이전 세션에서
시연용으로 만들어진 그래프의 커버리지 문제**다 — Rule Agent 자체의 결함이라기보다, 시연 그래프가
규정 전체가 아니라 일부 조항(제14조)만 반영해 만들어졌다는 사실이 이번에 우연히 드러난 것이다.
실사용 전환 시 제7·8조(사전승인 트리거)를 다루는 노드를 추가해야 한다.

---

## 3. Risk Review Agent — 위반 판정 정확도 (⚠️ 원인 분석 정정됨)

**대상**: 회식(GATHERING) 카테고리 6건, `POST /lab/risk/run`으로 라이브 재실행. 정답은 **실제
배포된 ACTIVE 룰 그래프의 결정론적 조건**(M-001: 1인당 5만원 초과, M-002: 2차 결제)으로 독립
산정.

| settlement | 가맹점 | 1인당 금액 | 실제 규정상 정답 | Agent 예측 | 결과 |
|---|---|---|---|---|---|
| 381 | 포차 정든 | 40,000원 | NO_VIOLATION | VIOLATION | ❌ 오탐 |
| 382 | 호프 갈매기 | 150,000원 | VIOLATION (M-001) | VIOLATION | ✅ |
| 383 | 이자카야 다시(2차) | 50,000원 | VIOLATION (M-002) | VIOLATION | ✅ |
| 466 | 포차 참 | 35,000원 | NO_VIOLATION | NO_VIOLATION | ✅ |
| 467 | 호프 만선 | 80,000원 | VIOLATION (M-001) | NO_VIOLATION | ❌ 미탐 |
| 468 | 이자카야 노을 | 104,000원 | VIOLATION (M-001) | VIOLATION | ✅ |

| 지표 | 값 |
|---|---|
| 정확도 | **4/6 = 66.7%** |
| 평균 지연(1차+2차 합산) | 약 13.1초 |

### ⚠️ 정정 — 381 오탐의 원인은 "RAG 검색 오류"가 아니었다

**1차 작성 당시 결론(틀림)**: "회식 규정에 없는 '30만원 초과 시 사전승인' 조항을 인용한 걸 보니
RAG가 다른 문서(업무추진비 규정)를 잘못 끌어온 것 같다."

**재조사 결과**: 실제 `회식_운영규정 제8조`를 RAG로 직접 검색해보니, "건당 총액 30만원 초과"뿐
아니라 **"주류 포함 + 1인당 8만원 초과"도 제8조 6호에 실재하는 진짜 조항**이었다. 즉 Agent가
인용한 규정은 **가짜도, 다른 문서 것도 아니라 진짜 회식 규정 원문**이다 — 다만 그 조항이
1차 판정(결정론적 룰 그래프)에는 아직 구현이 안 되어 있었을 뿐이다(§2 발견 ②). RAG는 **오히려
1차 룰 그래프보다 더 정확하게 원본 규정을 찾아낸 것**이다.

그렇다면 381이 왜 틀렸는가? Django 내부 API(`/api/internal/rule-context/381/`)로 이 정산에
**실제로 어떤 사실이 잡혀 있는지, 그리고 Agent에게 어떤 문장으로 전달됐는지**를 직접 확인했다.

```
EvalContext: dining.includes_alcohol=True, approval.pre_approval_obtained=True
Agent에게 전달된 facts_nl() 문장: "참석 인원 7명, 사전승인 받음, 2차 성격 아님, 주류 포함"
```

**Agent는 "사전승인 받음"이라는 문장을 프롬프트에서 그대로 전달받고도**, "주류가 포함되어
있어 사전승인이 필요합니다"라며 위반 처리했다. 즉 **이미 사전승인을 받았다는, 프롬프트에 명시된
사실을 무시하고 "사전승인이 필요하다"는 결론을 낸 것**이다 — 검색 정확도 문제가 아니라 **이미
주어진 입력을 반영하지 못한 추론 오류**다.

### 467 미탐 — 이건 원래 분석대로 산술 판단 누락이 맞다

같은 방식으로 467도 재확인했다: `EvalContext`는 `includes_alcohol=False`(모델의 "주류
미포함" 답과 일치, 정확), `pre_approval_obtained=True`. 문제는 1인당 80,000원(240,000÷3)으로
M-001(1인당 5만원)을 명백히 초과하는데, Agent는 "참석 인원 3명으로 회식이 가능하며"라고만
언급하고 **금액÷인원 계산 자체를 판단에 반영하지 않았다**. 인원(3명)과 금액(240,000원)이 둘 다
프롬프트에 있었는데도 나눗셈을 실제로 수행하지 않은 것으로 보인다 — 여기는 원래 분석(산술 판단
누락)이 맞았다.

### 종합 — 두 결함의 성격이 다르다

| 오류 | 성격 | 개선 방향 |
|---|---|---|
| 381 오탐 | **주어진 사실(사전승인 완료)을 무시**하고 다른 조항 근거로 위반 결론 | 판단 결과가 EvalContext의 명시적 사실과 모순되면 재검토하도록 프롬프트에 자기검증 단계 추가 |
| 467 미탐 | **1인당 금액 계산(나눗셈)을 아예 수행하지 않음** | 서버가 `amount/headcount`를 미리 계산해 "1인당 40,000원"처럼 프롬프트에 명시적으로 박아 넣기(모델이 산수를 하게 두지 않음) |
| (부수 발견) | 배포된 룰 그래프가 원본 규정의 8개 트리거 중 3개만 구현 | Rule Agent로 제7·8조 커버 노드 추가 생성 필요(§2) |

4개 Agent 중 Risk Review Agent가 가장 취약하지만, 그 이유는 "RAG가 엉뚱한 문서를 찾는다"가
아니라 **"올바른 근거를 찾고도 이미 주어진 사실을 놓치거나 계산을 안 한다"**는, 더 좁고 고치기
쉬운 문제였다.

---

## 4. 증빙자료 추출 Agent — 필드 추출 정확도 (1차 + 2차 강화판)

> ⚠️ **아키텍처 갱신 안내**: 이 평가는 이 세션에서 임시로 짠 **동기** 실행 구현을 대상으로
> 돌렸다. 평가 직후 팀원이 `main`에 독립적으로 구현한 **비동기**(`on_commit`) 버전이 발견돼
> 그쪽을 채택했다(`_context/evidence-extraction-agent.md` 상단 참조) — 업로드 응답은 이제
> 즉시 `PENDING`이고, 판독은 커밋 후 별도로 돈다. **판독 로직 자체(비전 모델 호출)는 두
> 구현이 동일**(`app/vision/`을 그대로 공유)하므로 아래 정확도 수치 자체는 유효하지만, §6.5
> 재현 스크립트를 그대로 돌리면 `extracted`가 아직 비어 있는 `PENDING` 상태를 볼 수 있다 —
> 재현하려면 업로드 후 완료될 때까지 잠깐 폴링(`GET .../attachments/`)해야 한다.

### 4.1 1차 평가 — 쉬운 합성 문서

**대상**: 명시적 키워드(`[STATUS: APPROVED]`, `Attendees (5 total)` 등)를 쓴 합성 문서 6종.

| 지표 | 값 |
|---|---|
| 필드 단위 정확도 | **9/9 = 100%** |
| 평균 확신도 | 1.00(전 필드 최고) |
| 평균 지연 | 약 2.3초/문서 |

100%가 나왔지만, 스스로 "이건 너무 쉬운 문서 아니냐"는 의문이 들어 2차 평가를 추가했다.

### 4.2 2차 평가(강화판) — 세계지식·모호성·관측 계약 위반 여부

| 케이스 | 요구하는 능력 | 정답 | 실제 | 결과 |
|---|---|---|---|---|
| 술 종류를 "하이볼"로만 표기 | 세계지식(하이볼=술이라는 상식) | `includes_alcohol=True` | True | ✅ |
| 승인 여부를 체크박스로만 표기("[X] Reviewed and cleared") | 명시적 "APPROVED" 없이 승인 여부 추론 | `pre_approval_obtained=True` | True | ✅ |
| **승인 여부 언급 자체가 없는 문서**(회식 예정 메모) | **관측 계약 준수**(모르면 값을 내지 말아야 함) | 경로 자체가 없어야 함(모름) | **`False`를 지어냄** | ❌ |
| 참석자 수를 직접 안 세고 서명 명단만 나열 | 명단을 세어서 인원수 도출 | `participant_count=5` | 5 | ✅ |

| 지표 | 값 |
|---|---|
| 정확도 | **3/4 = 75%** |

### 발견한 것 — 관측 계약 위반(진짜 결함)

세계지식이 필요한 추론(하이볼→주류)이나 암묵적 표현(체크박스→승인)은 잘 처리했다. 그런데
**승인 여부가 아예 언급되지 않은 문서**에서, 이 프로젝트가 가장 중요하게 여기는 원칙 —
"관측하지 않았으면 경로 자체를 내지 말라"(`_context/evidence-extraction-agent.md` §3.2,
「확인했는데 없음」과 「안 봤음」을 구분) — 를 **위반하고 `approval.pre_approval_obtained=False`를
지어냈다.** 이건 단순 정확도 문제가 아니라 **이 프로젝트가 겪었던 "조용한 False" 문제가 증빙자료
추출 Agent에서도 재발할 수 있다는 실측 증거**다 — 판정 파이프라인에서는 미해소 가드가 이런
값을 걸러줄 수 없다(경로가 아예 없는 것과 `False`인 것은 EvalContext에서 다르게 취급되기
때문에, 지어낸 `False`가 그대로 "확인된 사실"로 판정에 들어갈 위험이 있다). 프롬프트의
관측 계약 지시를 더 강하게 하거나(예: few-shot으로 "언급 없음" 사례를 명시), 후처리에서
문서 내 해당 키워드 언급 여부를 별도로 검증하는 게 필요해 보인다.

### 종합

1차(쉬운 문서) 100% → 2차(어려운 문서) 75%로, 처음 평가가 문제를 너무 쉽게 냈다는 자체 비판이
맞았다는 게 확인됐다. 그리고 어려운 조건에서만 드러나는 **실제 결함**(관측 계약 위반)을 찾아냈다
— 이게 "9/9 100%"라는 숫자보다 훨씬 값진 결과다.

---

## 5. 종합 요약

| Agent | 핵심 지표 | 결과 | 비고 |
|---|---|---|---|
| Draft Agent | 분류 정확도 | 83.3% (10/12) | 접대/회식 오분류 — 거래처 동석 사실을 수정 모드로 전달해도 안 바뀜(수정 모드가 명시적 요청 없인 분류를 재판단하지 않는 설계, §1 재검증) |
| Rule Agent | 노드 커버리지 / 시뮬레이션 통과율 | 100% / 100% | 생성 자체검증 단계가 75%에서 스스로 걸러냄(정상 동작). 부수 발견: 이미 배포된 시연용 회식 그래프가 원본 규정 8개 트리거 중 3개만 구현(§2) |
| Risk Review Agent | 위반 판정 정확도 | **66.7% (4/6)** | 4개 중 가장 취약. 원인은 검색 오류가 아니라 **주어진 사실을 무시**(오탐 1)·**나눗셈 미수행**(미탐 1) — 1차 분석(RAG 오검색)은 재조사로 정정됨(§3) |
| 증빙자료 추출 Agent | 필드 추출 정확도 | 100%→75% | 쉬운 문서 100%, 어려운 문서 75% — **관측 계약 위반**(모르면서 `False` 지어냄) 실측 발견(§4) |

**우선순위**: Risk Review Agent의 2차 검증 개선이 가장 시급하다. ① 오탐은 판단 결과와
EvalContext 명시 사실이 모순되면 자기검증하는 단계 추가, ② 미탐은 1인당 금액을 서버가 미리
계산해 프롬프트에 박아 넣기. 증빙자료 추출 Agent의 관측 계약 위반도 이 프로젝트의 핵심 원칙과
직결되는 문제라 우선순위가 높다.

---

## 6. 재현 스크립트 (원문 보존)

이 문서 작성 시점에 `docker compose up` 상태의 로컬 스택에 대해 실행한 스크립트 전문이다.
레포에 별도로 커밋하지 않았으므로 재현하려면 아래를 파일로 복원해 실행한다.

### 6.1 Draft Agent — 1차 평가 (`ai` 컨테이너 내부에서 실행)

```python
"""Draft Agent 정량 평가 — 분류 정확도·확신도·지연.
운영과 같은 엔드포인트(POST /agent/draft, 생성 모드)를 그대로 호출한다. 부작용 없음.
"""
import statistics, time
import httpx

BASE = "http://localhost:9000"

CASES = [
    ("동네 커피전문점 소액", {"merchant": "이디야커피 강남역점", "amount": 8500, "cardType": "PERSONAL", "evidence": "OK", "headcount": 0}, "식대"),
    ("편의점 간식", {"merchant": "CU 역삼점", "amount": 12000, "cardType": "PERSONAL", "evidence": "OK", "headcount": 0}, "식대"),
    ("팀 회식 삼겹살", {"merchant": "대치동 화로삼겹살", "amount": 320000, "cardType": "TEAM", "evidence": "OK", "headcount": 6}, "회식"),
    ("팀 회식 노래방 2차", {"merchant": "코인노래연습장", "amount": 180000, "cardType": "TEAM", "evidence": "OK", "headcount": 8}, "회식"),
    ("호텔 회의실 대관", {"merchant": "롯데호텔 비즈니스센터", "amount": 150000, "cardType": "TEAM", "evidence": "OK", "headcount": 0}, "회의"),
    ("스터디카페 회의룸", {"merchant": "그린램프 스터디카페", "amount": 45000, "cardType": "TEAM", "evidence": "OK", "headcount": 0}, "회의"),
    ("KTX 출장 승차권", {"merchant": "KTX 서울-부산", "amount": 59800, "cardType": "PERSONAL", "evidence": "OK", "headcount": 0}, "출장"),
    ("공항 리무진버스", {"merchant": "인천공항 리무진버스", "amount": 18000, "cardType": "PERSONAL", "evidence": "OK", "headcount": 0}, "출장"),
    ("생활용품점 사무비품", {"merchant": "다이소 역삼점", "amount": 45000, "cardType": "PERSONAL", "evidence": "OK", "headcount": 0}, "비품"),
    ("문구점 사무용품", {"merchant": "알파문구 강남점", "amount": 32000, "cardType": "PERSONAL", "evidence": "MISSING", "headcount": 0}, "비품"),
    ("고급 오마카세 거래처 접대", {"merchant": "긴자스시 오마카세", "amount": 850000, "cardType": "TEAM", "evidence": "OK", "headcount": 4}, "접대"),
    ("골프 라운딩 접대", {"merchant": "레이크사이드CC", "amount": 1200000, "cardType": "TEAM", "evidence": "OK", "headcount": 4}, "접대"),
]

def main():
    results = []
    for label, payload, expected in CASES:
        started = time.perf_counter()
        try:
            resp = httpx.post(f"{BASE}/agent/draft", json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            results.append({"label": label, "expected": expected, "predicted": None, "ok": False,
                             "confidence": None, "latencyMs": None, "error": str(exc)})
            continue
        latency = round((time.perf_counter() - started) * 1000, 1)
        predicted = data.get("draft", {}).get("category")
        confidence = data.get("confidence")
        results.append({
            "label": label, "expected": expected, "predicted": predicted,
            "ok": predicted == expected, "confidence": confidence, "latencyMs": latency,
        })

    correct = sum(1 for r in results if r["ok"])
    total = len(results)
    for r in results:
        mark = "O" if r["ok"] else "X"
        print(f"[{mark}] {r['label']:30s} 예상={r['expected']:4s} 예측={str(r['predicted']):6s} "
              f"conf={r['confidence']} lat={r['latencyMs']}ms")
    print(f"분류 정확도: {correct}/{total} = {correct/total:.1%}")

if __name__ == "__main__":
    main()
```

### 6.2 Draft Agent — 재검증 (수정 모드로 거래처 사실 전달)

```python
import httpx

BASE = "http://localhost:9000"

def gen(merchant, amount, headcount=0):
    r = httpx.post(f"{BASE}/agent/draft", json={
        "merchant": merchant, "amount": amount, "cardType": "TEAM", "evidence": "OK", "headcount": headcount
    }, timeout=60).json()
    return r["draft"]

def revise(current, instruction):
    r = httpx.post(f"{BASE}/agent/draft", json={
        "instruction": instruction,
        "current": {
            "merchant": current["merchant"], "amount": current["amount"], "category": current["category"],
            "aiCategory": current.get("aiCategory", current["category"]), "purpose": current.get("purpose", ""),
            "evidence": current.get("evidence", "OK"), "headcount": current.get("headcount", 0),
        },
    }, timeout=60).json()
    return r["draft"], r.get("changes", [])

CASES = [
    ("긴자스시 오마카세", 850000, 4, "이 자리에 B사 구매팀 최상무님도 함께 식사하셨어요."),
    ("레이크사이드CC", 1200000, 4, "라운딩에 C사 최이사님도 동행하셨습니다."),
    ("대치동 화로삼겹살", 320000, 6, "예전에 같이 일했던 전 팀원이 인사하러 잠깐 들렀어요."),  # 대조군
]

for merchant, amount, headcount, instruction in CASES:
    base = gen(merchant, amount, headcount)
    revised, changes = revise(base, instruction)
    print(f"{merchant}: {base['category']} → {revised['category']} (changes={changes})")
```

### 6.3 Rule Agent (Django `core` + FastAPI `ai` 오가며 실행)

```python
# ai 컨테이너: 생성 + 부작용 있음(DRAFT 그래프 실제 생성) → 끝나면 core에서 삭제
import httpx, time
started = time.perf_counter()
r = httpx.post("http://localhost:9000/lab/rule/generate", json={"scope": "비품", "topK": 6}, timeout=200).json()
res = r["result"]
print("status", res.get("status"), "graph", res.get("graph"))

# core 컨테이너: 자동 검증셋 생성 + 시뮬레이션 (세션 로그인 필요, acclead/pass1234)
s = httpx.Client(base_url="http://localhost:8000")
s.post("/api/auth/login/", json={"username": "acclead", "password": "pass1234"})
r2 = s.post("/api/rules/85/test-cases/generate/", json={}, timeout=200)  # 85 = 위에서 받은 graph_id
print(r2.json())
r3 = s.get("/api/rules/85/simulation/", timeout=60)
print(r3.json())

# 정리
s.delete("/api/rules/85/delete/")
```

### 6.4 Risk Review Agent (`ai` 컨테이너 + Django 내부 API로 원인 조사)

```python
"""Risk Review Agent 정량 평가 + 원인 조사.
정답은 실제 ACTIVE 룰 그래프(회식비 검증 그래프)의 M-001/M-002 조건으로 독립 산정.
원인 조사는 Django 내부 API로 각 정산의 실제 EvalContext를 직접 확인한다.
"""
import httpx

BASE = "http://localhost:9000"
DJANGO = "http://localhost:8080"
LIMIT = 50000

CASES = [
    (381, 280000, 7, "포차 정든"),
    (382, 900000, 6, "호프 갈매기"),
    (383, 350000, 7, "이자카야 다시"),   # 2차 결제 데모 케이스 — M-002로 VIOLATION이 정답
    (466, 210000, 6, "포차 참"),
    (467, 240000, 3, "호프 만선"),
    (468, 520000, 5, "이자카야 노을"),
]

for sid, amount, headcount, merchant in CASES:
    per_person = amount / headcount
    expected = "VIOLATION" if per_person > LIMIT else "NO_VIOLATION"
    data = httpx.post(f"{BASE}/lab/risk/run", json={"settlementId": sid}, timeout=90).json()["result"]
    predicted = data["stage2_rag_review"].get("violation_verdict")
    ok = predicted == expected
    print(f"[{'O' if ok else 'X'}] {sid} {merchant} 1인당={round(per_person)} 예상={expected} 예측={predicted}")
    if not ok:
        ctx = httpx.get(f"{DJANGO}/api/internal/rule-context/{sid}/", timeout=10).json()["eval_context"]
        print("   실제 EvalContext:", ctx.get("dining"), ctx.get("approval"), ctx.get("participants"))
        print("   Agent 근거:", data["stage2_rag_review"].get("review_reasons"))
```

### 6.5 증빙자료 추출 Agent — 1차 + 2차(강화판) (호스트에서 `nginx:8080` 직접 호출)

```python
"""증빙자료 추출 Agent 정량 평가 — 필드 단위 정확도(합성 문서).
1차: 명시적 키워드 위주 쉬운 문서. 2차: 세계지식·모호성·관측계약을 요구하는 어려운 문서.
운영 경로(Django 업로드 → FastAPI /agent/extract → app/vision) 그대로 태운다.
"""
import io, time
import httpx
from PIL import Image, ImageDraw

DJANGO = "http://localhost:8080"
SETTLEMENT_ID = "475"  # 검증용 정산 — 판정에 영향 없음

CASES_EASY = [
    {"label": "사전승인-승인완료", "kind": "PRE_APPROVAL",
     "lines": ["PRE-APPROVAL REQUEST", "Approver: Park (Finance Lead)", "Approval date: 2026-08-10", "[STATUS: APPROVED - SIGNED]"],
     "expected": {"approval.pre_approval_obtained": True}},
    {"label": "사전승인-미승인", "kind": "PRE_APPROVAL",
     "lines": ["PRE-APPROVAL REQUEST", "Approver: (pending)", "Status: DRAFT - SUBMITTED, NOT YET APPROVED", "No signature or stamp present"],
     "expected": {"approval.pre_approval_obtained": False}},
    {"label": "회의록-5명(외부2)", "kind": "MEETING_MINUTES",
     "lines": ["MEETING MINUTES", "Date: 2026-08-10", "Attendees (5 total):", "- Internal: Kim, Lee, Park (3)", "- External: Choi(ClientCo), Jung(ClientCo) (2)"],
     "expected": {"participants.participant_count": 5, "participants.external_participant_count": 2}},
    {"label": "회의록-2명(전원내부)", "kind": "MEETING_MINUTES",
     "lines": ["MEETING MINUTES", "Date: 2026-08-11", "Attendees (2 total), all internal staff:", "- Kim, Lee", "No external guests."],
     "expected": {"participants.participant_count": 2, "participants.external_participant_count": 0}},
    {"label": "참석자명단-4명", "kind": "PARTICIPANT_LIST",
     "lines": ["PARTICIPANT LIST", "1. Kim (Sales team)", "2. Lee (Sales team)", "3. Park (Sales team)", "4. Choi (Sales team)", "Total: 4 employees, no outside guests"],
     "expected": {"participants.participant_count": 4, "participants.external_participant_count": 0}},
    {"label": "출장계획서-숙박비12만원", "kind": "TRIP_PLAN",
     "lines": ["BUSINESS TRIP PLAN", "Trip type: DOMESTIC", "Region grade: A", "Lodging: 120,000 KRW per night", "Duration: 2 nights"],
     "expected": {"trip.lodging_amount_per_night": 120000}},
]

CASES_HARD = [
    {"label": "하드-하이볼(세계지식 필요)", "kind": "RECEIPT",
     "lines": ["RECEIPT - IZAKAYA DASHI", "1. Grilled salmon set  18,000", "2. Highball x2       12,000", "3. Edamame             4,000", "Total: 34,000 KRW"],
     "expected": {"dining.includes_alcohol": True}},
    {"label": "하드-체크박스 승인(명시적 단어 없음)", "kind": "PRE_APPROVAL",
     "lines": ["EXPENSE PRE-CLEARANCE FORM", "Requested by: Kim", "Reviewed by: Park (Team Lead)", "[X] Reviewed and cleared to proceed", "Date: 2026-08-10"],
     "expected": {"approval.pre_approval_obtained": True}},
    {"label": "관측계약-승인여부 언급 없음(모름이 정답)", "kind": "PRE_APPROVAL",
     "lines": ["MEMO", "Team dinner scheduled for next Friday.", "Venue: TBD", "Budget estimate: 300,000 KRW"],
     "expected_absent": ["approval.pre_approval_obtained"]},
    {"label": "하드-서명 명단만(총원 문구 없음, 세어야 함)", "kind": "PARTICIPANT_LIST",
     "lines": ["SIGN-IN SHEET", "1) Kim Minsu", "2) Lee Jiwon", "3) Park Sena", "4) Choi Yuna", "5) Jung Hosik", "(signatures collected above, no headcount stated)"],
     "expected": {"participants.participant_count": 5}},
]

def make_image(lines):
    img = Image.new("RGB", (700, 360), "white")
    d = ImageDraw.Draw(img)
    y = 30
    for line in lines:
        d.text((30, y), line, fill="black")
        y += 40
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def run(cases):
    total = correct = 0
    for case in cases:
        png = make_image(case["lines"])
        files = {"file": (f"{case['kind']}.png", png, "image/png")}
        data = {"kind": case["kind"]}
        resp = httpx.post(f"{DJANGO}/api/settlements/{SETTLEMENT_ID}/attachments/", data=data, files=files, timeout=100)
        resp.raise_for_status()
        body = resp.json()
        extracted = body.get("extracted", {})

        if "expected_absent" in case:
            for path in case["expected_absent"]:
                total += 1
                ok = path not in extracted
                correct += int(ok)
                print(f"[{'O' if ok else 'X'}] {case['label']} | {path}: 기대=없음 실제={extracted.get(path, '(없음)')}")
        else:
            for path, expected_value in case["expected"].items():
                total += 1
                actual = extracted.get(path)
                ok = actual == expected_value
                correct += int(ok)
                print(f"[{'O' if ok else 'X'}] {case['label']} | {path}: 기대={expected_value} 실제={actual}")

        httpx.delete(f"{DJANGO}/api/settlements/{SETTLEMENT_ID}/attachments/{body['id']}/", timeout=10)
    print(f"정확도: {correct}/{total} = {correct/total:.1%}")

print("=== 1차(쉬운 문서) ===")
run(CASES_EASY)
print("\n=== 2차(강화판) ===")
run(CASES_HARD)
```
