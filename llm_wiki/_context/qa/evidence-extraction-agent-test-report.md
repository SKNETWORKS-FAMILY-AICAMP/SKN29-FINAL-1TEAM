# 증빙자료 추출 Agent QA — 실행 결과 보고서

실행일 2026-08-22. 대상: `POST /lab/extract/run`(`apps/ai/app/api/lab.py::extract_run`) → 운영과 동일한
`app.vision.read_receipt` / `app.vision.read_evidence_document`. 모델 `gpt-4o-mini`(env `VISION_MODEL` 기본값),
실 OpenAI 비전 호출 47건(RECEIPT 15 + PRE_APPROVAL 12 + MEETING_MINUTES 10 + PARTICIPANT_LIST 5 + TRIP_PLAN 5) +
`SKIPPED`(비전 호출 없음) 3건(CONTRACT×2, OTHER×1) = 총 50건. 케이스 정의는
`test-cases-evidence-extraction-agent.md` 참조.

## 실행 규모 — 실물 vs synthetic

- **50/50 synthetic** — DB에 실 `Attachment` 행이 0건(`Attachment.objects.count()==0`)이라 재사용 가능한 실사용 이력
  파일이 없었다(`docker compose exec core find /app/media -type f`로 loose 파일 50개는 발견했으나, 대응하는
  `Attachment`/`Receipt` DB 레코드가 없어 종류·정답을 알 수 없는 고아 파일이라 정답셋으로 못 쓴다).
- 목표(50건) **shortfall 없이 달성** — 전부 PIL로 직접 그린 한글 문서 이미지(AppleGothic 폰트), 정답을 내가 통제.
- 실행 방식: `docker cp`로 core↔ai 공유 media 볼륨(`attachments/qa/`)에 배치 후 `/lab/extract/run`을 `fileRef`+`kind`로
  직접 호출(`Attachment` DB 행 불필요 — 엔드포인트 자체가 요구하지 않음). Django API를 통한 정식 multipart 업로드는
  생략했다(같은 파일에 비전 호출이 중복 과금되는 것을 피함 — 판독 로직은 파일 출처와 무관하게 동일).
- **synthetic 데이터의 한계**: PIL로 그린 텍스트는 실제 스캔·사진보다 훨씬 깨끗하다(`ambiguous` 등급 케이스는
  Gaussian blur·노이즈·크롭·찢김으로 열화를 흉내냈지만, 실물 카메라 왜곡·저조도·손떨림과는 다르다). 아래 결과는
  "이상적 조건에서도 발생하는" 실패를 잡은 것이므로, 실물 사진에서는 같은 실패가 **더 심할 가능성**이 높다.

## 핵심 지표

### 1. Out-of-vocabulary 할루시네이션 — **0/50건, 구조적으로 차단됨**

`document.py`/`receipt.py` 둘 다 OpenAI structured output의 `json_schema(strict=True)` + `path` 필드
`enum=sorted(targets)`로 스키마 자체가 허용 경로만 값으로 받는다. 즉 이건 프롬프트 준수 여부가 아니라
**API 레벨에서 애초에 다른 문자열을 낼 수 없는 구조**다. 3개의 적대적 케이스(M06 회의록 속 출장 정보,
T05 출장계획서 속 참석자 명단, P11 사전승인 속 숙박비)로 직접 유인해봤지만 `trip.*`/`participants.*`가
`kind` 밖으로 유출된 사례는 0건. **"회의록에서 출장 지역등급을 찾게 두면 지어낸다"는 과거 버그가 방지하려던
바로 그 실패 모드는 이 아키텍처에서 재현 불가능함을 실측으로 확인**(CONTRACT/OTHER 3건도 전부 비전 호출 자체
없이 `SKIPPED`로 단락 — latency 0ms).

### 2. 필드별 정확도 (golden 있는 47건 기준, path별 TP/FP(허위 생성)/FN(누락)/정답생략/오답값)

| 필드 | TP | FP(없는데 생성) | FN(있는데 누락) | 정답생략 | 오답값 | n | recall(해당 시) |
|---|---|---|---|---|---|---|---|
| `category.item_type` (RECEIPT) | **0** | 0 | 12 | 3 | 0 | 15 | **0%** |
| `dining.includes_alcohol` (RECEIPT) | 8 | 1 | 2 | 4 | 0 | 15 | 80% |
| `tx.payment_time` (RECEIPT) | 6 | 0 | 6 | 3 | 0 | 12 | 50% |
| `approval.pre_approval_obtained` (PRE_APPROVAL) | 6 | 1 | 0 | 0 | **5** | 12 | 50%(오답률 42%) |
| `participants.participant_count` (MEETING/LIST) | 14 | **3** | 0 | 0 | 0 | 17 | — (아래 §3) |
| `participants.external_participant_count` | 6 | 2 | 4 | 1 | 2 | 15 | 46% |
| `participants.has_kickback_law_target` | 6 | 2 | 4 | 1 | 2 | 15 | 46% |
| `trip.trip_type` | 5 | 0 | 0 | 0 | 0 | 5 | 100% |
| `trip.region_grade` | 3 | 1 | 0 | 1 | 0 | 5 | 100%(해당 시) |
| `trip.lodging_amount_per_night` | 3 | 1 | 0 | 1 | 0 | 5 | 100%(해당 시) |

**가장 눈에 띄는 결함 — `category.item_type` recall 0%.** golden이 `식사`/`선물`/`경조사`로 명확한 12건 전부
필드 자체가 `extracted`에 나타나지 않았다(허용값 밖이라 버려진 흔적도 없음 — 모델이 애초에 그 경로를 시도조차
안 함). 삼겹살+소주 영수증(R01)처럼 아주 명백한 식사 영수증도 마찬가지다. `dining.includes_alcohol`은 같은
호출에서 정상적으로 나오는데 `category.item_type`만 비어 있어, 특정 경로에 대한 시스템적 무응답으로 보인다
(프롬프트 5개 규칙 중 `category.item_type`을 명시한 항목이 없는 것과 관련 가능성 — `_SYSTEM` 지시문이 주류·시각·
인원수는 규칙별로 짚어주는데 품목유형 판단 기준은 안 짚어준다).

### 3. 절대부재 상황에서의 값 날조(참부재 3건 전부 실패)

`participant_count`가 "정답=없음(모름)"이어야 하는 3건(M05: 안건만 있고 참석자 언급 자체 없음 / M08: "대략
여럿명, 이름 생략"이라고 명시적으로 불명확함을 서술 / PL04: "이하 명단 일부 훼손/누락") **모두 구체적인 숫자를
생성**했다(각각 0, 8, 3). 특히:

- **M05**: 모델이 반환한 `evidence_spans.quote` 자체가 `"참석자 총 인원수는 명시되어 있지 않음."`인데, 그
  옆에 `participant_count=0`(confidence 1.0)을 실었다. **근거 문구가 "정보 없음"이라고 말하는데 값은 확정값을
  낸 자기모순** — `_collect()`가 "quote가 비어있지 않은가"만 검사하고 "quote가 실제로 그 값을 뒷받침하는가"는
  검사하지 않기 때문에 이 계약 위반이 그대로 통과된다. 이건 `_context/evidence-extraction-agent.md`가 명시한
  「확인했는데 없음(0/false)」과 「안 봤음(경로 자체 생략)」의 구분이라는 핵심 계약을 **모델이 프롬프트 수준에서
  깨고 있고, 코드가 이를 잡아내지 못하는** 사례다.
- **M08**: quote가 `"참석: 대략 여럿명, 이름 생략"`인데 값은 `8`(confidence 1.0) — quote 어디에도 8이라는
  숫자적 근거가 없다. 완전한 값 날조.
- **PL04**: 문서가 명시적으로 "3번 이후 훼손/누락"이라 적었는데도 `count=3`(눈에 보이는 항목 수)을 확정값으로
  냈다 — 이 경우는 판단 여지가 있다(보이는 범위 내 사실이라는 해석도 가능해 M05/M08만큼 명백한 오류는 아님).

### 4. `approval.pre_approval_obtained` — 가장 안전critical한 필드에서 큰 오답률

golden=True 6건 중 정답 2건(P01·P09, 둘 다 **2단계 결재선이 모두 완료**로 명시된 문서), 오답 4건
(P05·P06·P11·P12, **1인 결재/전결/서명만 있는 문서**는 전부 `False`로 오판). "임원 결재란이 이미지로만
잘렸다"는 애매 케이스(P07)까지 포함하면 12건 중 정답은 절반뿐, **오답값만 5/12(42%)**. 재현되는 패턴:
승인 문구·서명·도장이 명확히 있어도 **결재선이 1단계뿐이면 "아직 승인 안 됨"으로 판단하는 경향**이 뚜렷하다
(2단계 완료 문서 2건은 전부 맞혔고, 1단계 문서 3건은 전부 틀렸다). CLAUDE.md 상태보드에 기록된 과거
"end-to-end 검증"은 2단계 결재 사례 기준이었을 가능성이 있고, 실제 회사에서 흔한 단일 결재자·전결 승인 문서에는
이 필드가 구조적으로 취약할 수 있다 — **재확인 필요 항목으로 특히 강조**.

### 5. `has_kickback_law_target` — 과탐/누락 양쪽

- **M04 누락(FN)**: "OO초등학교 이OO 교사" 참석 — 교직원은 청탁금지법(김영란법) 대상인데 `False`로 판정.
- **PL02 과탐(FP)**: 외부 거래처 임직원(대표·부장·이사) 참석을 `True`로 판정 — 이들은 일반 비즈니스 상대이지
  청탁금지법 대상(공무원/언론인/사립교원 등)이 아니다. "외부인 = 청탁금지 대상"으로 단순화하는 경향이 보인다.
- **PL03 누락(FN)**: "OO일보 박 기자" — 명백한 언론인 케이스인데 이 필드 자체가 `extracted`에서 통째로 빠짐
  (참석자수만 추출, kickback 판단 자체를 회피). 언론사 소속 판단만 회피하는 패턴인지는 표본 부족으로 단정 불가.

### 6. Confidence 보정(calibration) — 사실상 이진값, 모호도 미반영

수치 분포: **1.0이 절대다수**(대략 47건 중 40여 개 필드값), 예외는 P03/P04(0.9), P06(0.8), T04(0.0×2) 뿐.
의도적으로 흐리게(blur+noise) 만든 R07(주류 판독)·R10(찢긴 영수증)·M08(모호한 손글씨풍)·PL04(찢긴 명단) 케이스
전부 confidence 1.0을 냈다 — **화질 저하·모호성이 confidence 수치에 반영되지 않는다.** 유일하게 confidence가
낮게 나온 T04("?", "미정" 같은 명시적 미정 표기)조차, 0.0인데도 그 문자열 값 자체는 `extracted`에 그대로
담겼다(`_collect_facts`/`_collect`가 confidence 임계값으로 필터링하지 않기 때문 — 이 필터링은 Django
`context_builder.ATTACHMENT_CONFIDENCE_THRESHOLD=0.6`가 하류에서 담당하는 구조라, 이 자체는 설계대로다. 다만
**타입 계약 위반**은 지적할 만하다: `trip.lodging_amount_per_night`는 숫자여야 하는데 `"미정"`이라는 문자열이
그대로 값으로 실렸다 — `value_kind` 스키마가 `boolean`/`number`/`string`으로 분기 허용은 하지만, 필드별로
기대 타입을 강제하지 않아 하류 소비자가 `"미정"`을 숫자로 캐스팅하려 하면 에러가 날 수 있다).

## 근거 문구(quote) grounding 스팟체크 (15건 이상 확인)

`P01,P02,P03,P04,P05,P06,P07,P08,P09,P10,P11,P12,M01~M10,PL01~PL05,T01~T05` 전체(37건) 실제 quote를
원본 텍스트와 대조. 대부분 원문 그대로이거나 근접 발췌(정상). **문제 사례 2건**:

- **P06 — 근거 문구 자체가 원문에 없음(완전 날조 인용)**. 반환된 quote는 `"사전승인 없음"`인데, 실제 이미지에는
  이 문구가 전혀 없다(원문: "[승인] 팀장 (인) 2026-08-05", blur 처리됨). 모델이 흐림으로 읽지 못한 부분을
  "없다"는 취지의 문장으로 지어내 그걸 quote로 제출했다 — **인용 자체를 조작한 사례**로, "quote 없는 추출은
  버린다"는 방어선을 우회한다(quote는 있으나 허구).
- **P12 — 약한 grounding**: quote가 `"사전승인 신청서"`(문서 제목)로, 실제 판단 근거(서명 존재)와 무관한 텍스트를
  인용. 판단은 사람이 검증 가능해야 하는데 이 인용으로는 왜 `False`로 판정했는지 되짚을 수 없다.

## 지연시간(latency)

실 비전 호출 47건: 평균 **1.89초**, 최소 1.19초, 최대 2.99초(문서당 이미지 1장, `gpt-4o-mini`, `MAX_PAGES` 무관
— 전부 단일 페이지 PNG). `SKIPPED` 3건은 0ms(비전 호출 자체가 없어 정확히 무과금 확인). **토큰/비용은 응답에
노출되지 않는다** — `/lab/extract/run` 응답 셰이프에 usage 필드가 없어(다른 랩 엔드포인트처럼 `latencyMs`만
있음) 건별 비용을 직접 계산할 수 없었다(코드 확인: `app/vision/client.py::ask()`가 `resp.choices[0].message.content`만
읽고 `resp.usage`는 버림).

## 요약

| 항목 | 결과 |
|---|---|
| 케이스 수 | 50/50 (전부 synthetic, shortfall 없음) |
| Out-of-vocabulary 할루시네이션 | **0/50 — 구조적으로(json_schema enum) 차단 확인** |
| `category.item_type` recall | **0% — 유의미한 결함, 원인 미상(경로 자체를 시도 안 함)** |
| 절대부재 상황 값 날조 | 3/3 — participant_count가 "정보없음"에서도 항상 구체값 생성 |
| `pre_approval_obtained` 오답률 | 42%(5/12) — 1단계결재/전결 문서에서 체계적 오판(False 편향) |
| kickback 판정 | 과탐 1·누락 2 — "외부인=대상"으로 단순화하는 경향 |
| confidence 보정 | 사실상 상수 1.0 — 화질/모호성 미반영 |
| quote 조작 | 1건(P06) 완전 날조, 1건(P12) 약한 grounding |
| 지연시간 | 평균 1.89초/건(비전 호출) |
| 비용 노출 | 응답에 없음(토큰 usage 미노출) |

## 권고

1. `category.item_type` 회귀 재현 — 별도 최소 케이스로 재확인 후 프롬프트에 이 필드도 다른 필드처럼 판단 기준을
   명시적으로 추가.
2. `approval.pre_approval_obtained`는 정산 판정에 직결되는 필드다(룰 게이트 `approval.*` 참조). 1단계 결재만
   있는 실사 문서 샘플로 별도 회귀셋을 만들어 False-negative 편향을 정량화·수정 필요.
3. `_collect()`/`_collect_facts()`에 "quote가 실제로 값의 반대 근거(정보없음 서술)를 담고 있으면 드롭" 같은
   경량 휴리스틱(예: quote에 "명시되어 있지 않음"/"불명" 등 부정 표현이 있으면 값 폐기) 추가를 검토할 만하다 —
   현재는 quote 비어있음만 걸러낸다.
