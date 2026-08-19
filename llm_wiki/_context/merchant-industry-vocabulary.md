# 가맹점 업종 어휘 정본 (merchant industry vocabulary)

> 파생 컨텍스트. 권위 스펙은 `docs/기술명세서.md §7-1`. 여기엔 **왜 통일했는지·무엇을 옮겼는지**만 남긴다.
> 최종 갱신: 2026-08-19

## 1. 문제 — 한 저장소 안에 어휘가 네 갈래였다

`Settlement.merchant_industry`는 조립기(`policies/context_builder`)가 `merchant.merchant_type`
판정 사실로 그대로 올리는 값이다. 그런데 그 값을 만드는 쪽과 쓰는 쪽의 표기가 서로 달랐다.

| 출처 | 표기 |
|---|---|
| `classify_merchant`(ai, 10종) | `주점/유흥` · `레저/골프` · `마트/편의점` … |
| 룰 DSL (`seed_rules` GLOBAL R-002 / TEST T-50) | `유흥업소` · `주점` · `노래연습장` · `골프장` · `면세점` |
| 금지업종 별표 (`tiger_tables.forbidden_merchant_table`) | `유흥주점` · `단란주점` · `이용업` · `미용업` · `카지노` |
| 시드·ERP 수집 실데이터 | `한식` · `분식` · `일식` · `서점` · `종합소매` · `여객운송` |

**증상이 조용하다는 게 핵심이다.** 어휘가 갈리면
- 룰의 `{"in": [{"var": "merchant.merchant_type"}, [...]]}`가 **그냥 안 걸린다**(에러 아님, False),
- 금지업종 별표는 `strict_keys=True`라 키를 못 찾으면 `null` → 미해소 가드가 **REVIEW로 강등**한다.

둘 다 화면에 "업종 어휘가 안 맞습니다"라고 뜨지 않는다. 판정이 약해진 걸 알아챌 방법이 없었다.

## 2. 결정

1. **정본은 core 한 곳** — `apps/core/domain/transactions/industry.py` (`IndustryCode` + `ALIASES` + `resolve()`).
2. **ai는 미러** — `apps/ai/app/schemas.py`(`IndustryLabel`/`INDUSTRY_CODES`). 별도 컨테이너라
   import이 불가능해 `Category`와 같은 관례를 따른다. **어긋나면 캐시 적재 API가 400으로 거부**한다
   (조용히 저장되면 그 값이 그대로 판정 사실이 되므로 경계에서 막는다).
3. **어휘를 10 → 15종으로 확장** — 규정이 가르는 구분을 담아야 한다. 추가: `노래연습장`,
   `사행성업종`, `이·미용`, `골프장`/`레저` 분리, `면세점`. (`레저/골프` 한 덩어리로는
   주의업종 룰의 "골프장"을 판정할 수 없었다.)
4. **코드/라벨 분리** — 라벨(`주점/유흥`)은 표기라 개정될 수 있고, 코드(`BAR_ENTERTAINMENT`)는
   데이터 계약이라 고정이다(네임드 플래그의 `code`/`label`과 같은 규약). `Settlement`에
   `merchant_industry_code` 컬럼 신설, 조립기는 **코드를 먼저** 본다.
5. **모르면 `기타`로 밀지 않는다** — 접히지 않는 값은 `("", "")`(미확정). `기타`로 밀면 금지업종
   별표가 `"*" → False`로 폴백해 **확인하지 않은 것을 안전하다고 단정**한다.
   미확정은 `merchant_info_resolved=False`로 남아 사람이 본다.
6. **별칭 흡수** — 규정 원문 표기(`유흥주점`·`이용업`), 옛 시드/ERP 표기(`한식`·`서점`),
   폐기된 ai 표기(`레저/골프`)를 전부 `ALIASES`로 정본에 접는다. 부분일치는 **긴 별칭 우선**
   (`유흥주점`이 `주점`보다 먼저 걸려야 한다).

## 3. 이관 범위 (2026-08-19)

| 대상 | 변경 |
|---|---|
| 룰 DSL | GLOBAL `R-002` → `["주점/유흥","사행성업종","노래연습장","이·미용"]`, TEST `T-50` → `["주점/유흥","노래연습장","골프장","면세점"]` |
| 금지업종 별표 | payload 키를 정본 라벨로(`주점/유흥`·`노래연습장`·`사행성업종`·`이·미용`) |
| 조립기 | `merchant_industry_code or merchant_industry` → `resolve()` → `merchant_type` |
| 캐시 쓰기 | `MerchantCategoryUpsertView`가 정본 외 어휘를 **400**으로 거부 |
| 시드 / ERP 수집 | 표기는 그대로 두고 저장 직전 `resolve()` 경유 |
| 시뮬레이션 | 검증셋 `merchantType`도 접어서 실 판정과 같은 어휘로 돈다 |
| 데이터 이관 | `transactions/0004` (캐시: 카카오 group code → 정본), `settlements/0010` (정산: 라벨 접기 + 코드 채움) |

**되돌리기(backwards)는 두지 않았다** — 옛 카카오 group code·자유 표기는 정본에서 역산되지
않는다(원본은 `merchant_categories.raw`에 남아 있다).

## 4. Draft Agent 연동 (같은 작업에서 함께)

업종을 **서버가 조회해 넣는다**(`agents/draft_agent._resolve_industry`). 예전엔 LLM 출력
스키마(`LLMDraftOutput.merchantIndustry`)에 있어서 모델이 가맹점명만 보고 지어냈고, 그
자유 문자열이 그대로 저장·판정에 들어갔다.

- **조회는 LLM 호출보다 먼저** — 업종은 분류 판단의 입력이다(뒤에 붙이면 표시용).
- **수정 모드는 재조회하지 않는다** — 화면 값을 물려받고, 비어 있을 때만 조회한다.
- **실패해도 초안은 나온다** — 업종은 보조 힌트다. 미확정이면 프롬프트에 `미확인`이라 적어
  모델이 추측으로 채우지 않게 한다.
- 화면(S-01 `SettlementDetailModal`)이 저장 시 `merchantIndustry(_code)`를 함께 올린다.
  **이게 빠지면 연동해도 판정에 아무것도 안 남는다** — 실제로 빠져 있던 자리다.

## 5. 남은 것

- Risk Review Agent 연동(업종-분류 불일치·유흥업종 접대 등). 지금은 Draft만 부른다.
- `place_hint`를 채우는 경로 — 거래에 주소가 없어 화면은 아직 보내지 않는다(영수증 판독이
  주소를 뽑으면 그때 연결).
- 캐시 TTL(30일) 만료 후 재조회 비용 — 실사용 데이터가 쌓이면 히트율을 보고 조정.

## 관련
- `docs/기술명세서.md §7-1` (권위)
- `_context/rule-engine.md` (EvalContext·미해소 가드)
- `_context/rule-flags.md` (code/label 분리 규약의 선례)
