# 비용분류(Category) 어휘 정본 캐논

_최종 갱신: 2026-08-22 · 상태: 구현 완료_

> **한 줄**: 비용분류 목록의 정본은 `apps/core/domain/settlements/models.py::Category` 하나이고,
> 화면·ai는 `GET /api/meta/categories/`로 **런타임에 받아 쓴다**. 상수 복사본을 두지 않는다.

관련: [[merchant-industry-vocabulary]](같은 규율의 선례) · [[rule-flags]](사전 복사로 어긋났던 이력) ·
[[policy-domain]](분류 축 별표) · [[rule-engine]](scope 선택)

---

## 1. 왜 이 문서가 생겼나

같은 6개 목록이 저장소 안 **9곳에 상수로 복사**돼 있었다.

| 계층 | 위치 | 형태 |
|---|---|---|
| core(정본) | `settlements/models.py::Category` | TextChoices |
| core(파생) | `policies/models.py` `RULE_SCOPE_CHOICES`·CHECK 제약 | `Category.values` 참조 — OK |
| core(복사) | `settlements/draft_agent.py` `KEYWORD_CATEGORY`·`PURPOSE_TEMPLATE`·`_CATEGORIES` | 문자열 |
| ai(복사) | `schemas.py::Category` Literal | 구조화 출력 enum |
| ai(복사) | `agents/draft_agent.py` `VALID_CATEGORIES` + **프롬프트 문장 2개** | "다음 6개 중 하나만" |
| ai(복사) | `agents/rule_agent_v0/api.py::Scope` Literal | 요청 검증 |
| web(복사) | `types/domain.ts` `Category`·`CATEGORIES`·`CATEGORY_TONE` | 유니언 + 배열 |
| web(복사) | `ai-lab/DraftLab.tsx`·`ai-lab/RuleLab.tsx` | 배열 ×2 |
| web(복사) | `policy-docs/UploadModal.tsx`·`rule-console/NewRuleGraphModal.tsx` | 배열 ×2 |

그리고 **서버는 저장되는 값을 검증하지 않았다** — Django의 `choices=`는 DB 제약이 아니고,
`SettlementViewSet`의 커스텀 `create`/`update`는 `full_clean()`을 부르지 않는다. 즉 화면
드롭다운이 유일한 방어였고, 요청을 손대면 임의 문자열이 그대로 `category.value` 판정 사실이
됐다(그리고 룰 그래프 scope 선택 키라, 오타 하나가 "적용할 룰이 없다"로 조용히 흘러간다).

이 구조가 실제로 사고를 낸 이력이 두 번 있다:
- **룰 플래그 라벨**: 프론트가 사전을 복사해 갖고 있다가 백엔드 27개 vs 프론트 9개로 갈렸다
  (→ 서버가 `ruleFlagInfo`로 라벨을 실어 보내는 것으로 해결. `_context/rule-flags.md`).
- **"업무활성"→"회식" 리네임**(2026-08-14): 9곳을 손으로 따라가야 했고, `rule_agent_v0`의
  두 파일은 **직전 세션에 반대 방향으로 "정정"했던** 이력까지 있다.

---

## 2. 결정

### D-1. 정본은 `settlements.Category` 하나, 노출 창구는 `/api/meta/categories/` 하나

```
settlements.Category  ──►  GET /api/meta/categories/  ──┬──►  web: useCategories()
   (TextChoices)              { categories, ruleScopes } └──►  ai : core_client.get_categories()
```

- `ruleScopes`(= `GLOBAL ∪ Category.values`)도 **함께 싣는다**. "GLOBAL을 앞에 붙인다"는
  조합 규칙도 서버 도메인(`policies.models.RULE_SCOPE_CHOICES`)이지 클라이언트 지식이 아니다.
- 인가는 `AllowAny` — 사용자 데이터가 아니라 **어휘**이고, 로그인 화면 이전에도 필요하다.

### D-2. 서버가 저장 시점에 검증한다 (`_invalid_category`)

`create`·`PATCH` 양쪽에서 목록 밖 값이면 400. 한쪽만 막으면 다른 쪽으로 들어온다.
이게 정합의 실질적 자물쇠다 — 미러가 낡아도 **틀린 값이 저장되지는 않는다**.

### D-3. ai는 **구조화 출력 enum을 런타임에 다시 찍는다**

`agents/draft_agent._with_categories()`가 `pydantic.create_model`로 `LLMDraftOutput`/
`LLMReviseOutput`을 core 어휘 + 빈 문자열로 재생성해 `response_format`에 넘긴다.

- 정적 Literal로 두면 core가 분류를 늘려도 **모델이 그 값을 낼 방법 자체가 없다**
  (API가 enum을 강제하므로 조용히 옛 목록으로 수렴한다 — 에러가 안 나는 자리).
- **프롬프트 지시문도 같은 목록**을 본다(`_system_prompt()`). 스키마만 바꾸고 문장에 옛
  목록이 남으면 모델은 "고를 수 있지만 고르면 안 되는 값"으로 취급한다.
- 응답 모델(`api/draft.py::Draft`)의 타입은 `str`로 풀었다. 여기서 정적 미러로 한 번 더
  조이면 core가 분류를 늘렸을 때 **응답 검증에서 422**가 나서, 모델은 제대로 골랐는데
  화면에는 서버 오류로 보인다.

### D-4. 프론트는 유니언 타입을 버리고 서버 목록을 쓴다

`type Category = string` + `lib/categories.ts::useCategories()`(모듈 캐시 1개, 요청 공유).
mock 모드와 조회 실패에는 `CATEGORIES_FALLBACK`으로 떨어지되 **실패는 캐시하지 않는다**
(배포 직후 잠깐의 장애가 세션 내내 남지 않게). 색상 팔레트(`CATEGORY_TONE`)는 프론트가
계속 소유하고, 모르는 분류는 `categoryTone()`이 기본값으로 떨어뜨린다 — 어휘는 서버,
표현은 화면.

### D-5. `기타`를 추가한다 — 단, **`기타` ≠ 미기재**

| 값 | 뜻 | 판정 |
|---|---|---|
| `기타`(`Category.OTHER`) | 사람이 "나열된 어디에도 안 맞는다"고 **확정** | 통과(과목 그래프 없으면 `NO_SCOPE_RULE_GRAPH`) |
| `""` | 아직 못 정했다 | 기본 게이트 `CATEGORY_MISSING` → 검토 |

이 구분은 [[merchant-industry-vocabulary]]에서 이미 채택한 규율이다 — 거기서도 미확정을
`기타`로 밀면 금지업종 별표가 `"*"→False`로 폴백해 **확인 안 한 걸 안전하다고 단정**한다.
비용분류도 같다: 미확정을 `기타`로 접으면 `CATEGORY_MISSING`이 안 걸려 아무도 확인하지
않은 건이 확인된 것으로 취급된다.

### D-6. AI가 못 정하면 **비워 둔다** (실재 과목으로 밀지 않는다)

`core/draft_agent._guess_category()`의 폴백이 `비품`이었다("업무활성" 캐치올 폐지 때 흡수한
잔재). 비품은 자기 예산 행과 scope 그래프를 가진 실제 과목이라, 성격이 다른 지출을
흘려보내면 그 과목의 집계·판정이 함께 흐려진다. 지금은 `("", 0.0, "특정하지 못했습니다")`.

같은 이유로 **`기타`로도 밀지 않는다** — `기타`는 확정이지 "모른다"가 아니다(D-5).
캐치올이던 우체국·택배·인쇄 키워드만 `기타`로 이관했다(그건 실제로 "어디에도 안 맞는"
일반 업무비다).

ai 쪽 LLM 실패 폴백도 `"비품"` → `UNSET_CATEGORY("")`로 바꿨고, LLM에게도 enum에 `""`를
열어 줬다: **판단할 수 없으면 비워 두라**(추측해서 아무 분류나 고르지 말라)는 지시와 함께.

---

## 3. 「기타」 추가가 복잡해지지 않은 이유 (실측)

| 축 | 결과 |
|---|---|
| 별표(PolicyTable) | 분류 축 표 4종이 전부 `"*"` 와일드카드 폴백 → 기타도 기본 임계값으로 해소, 미해소 가드에 안 걸림 |
| 기본 게이트 | `CATEGORY_MISSING`은 `category.value == null` 검사라 기타는 안 걸림(원하는 동작) |
| ERP 전표 | `_build_voucher`가 category 문자열 pass-through, 계정과목 매핑 테이블이 없음 → 영향 0 |
| scope | `normalize_scope`가 매핑 없는 값을 원문 통과 → `기타`→`기타`. 그래프가 없어도 GLOBAL만 통과하면 PASS 유지(회의·비품이 이미 그 상태) |
| 마이그레이션 | `RuleGraph.ck_rulegraph_scope` **넓히기 1건**(`policies/0019`) — 집합이 커지기만 하므로 0009~0011의 3단계 분리 불필요 |
| 예산 | `seed`는 `C.values` 순회라 자동, `seed_clean`은 명시 dict + `missing` assert 가드가 누락을 잡아 줌 |

**남은 주의 하나**: LLM이 애매하면 `기타`로 도피할 수 있다. 프롬프트에서 `기타`를
**배제 조건**("나열된 어디에도 맞지 않으면")으로 서술하고, 정말 판단이 안 되는 경우는
`""`로 가도록 두 갈래를 명시했다.

---

## 4. 함께 고친 화면 결함 3건

이 정합 작업 중 드러난, 어휘와 같은 뿌리를 가진 결함들.

1. **상세 모달이 미분류를 '접대'로 만들었다** — 기본값이 `item?.category ?? item?.aiCategory ?? '접대'`
   였고 드롭다운에 빈 옵션이 없었다. 화면에서 표현조차 못 하는 상태(`""`)를 판정은
   `CATEGORY_MISSING`으로 걸고 있었으니, **화면과 판정이 서로 다른 사실을 말하고** 있었다.
   → 기본값 `""`, 「선택 필요 — 분류를 골라주세요」 옵션 + 경고 칩 + 결과 안내 문구.
   막지는 않는다(백엔드가 허용하는 상태를 화면만 금지하면 반대 방향으로 어긋난다).
2. **검토 화면의 비용분류 `<select>`가 죽어 있었다** — `onChange`도 저장 경로도 없고,
   확정 분류가 아니라 AI 제안을 보여줬다. 그 카드는 "기본 내역(조회 전용)"이다
   → readOnly 표시로 교체(확정/AI 제안/미기재 배지 구분).
3. **표시와 필터가 서로 다른 값을 봤다** — 목록 배지·필터·fact.json이 `aiCategory`를 봐서,
   사람이 고쳐 확정한 건이 화면에 보이는 분류로 안 걸렸다 → 전부 `category || aiCategory`
   (fact.json만은 `category`만 — 판정이 보는 값을 그대로 보여야 한다).

---

## 5. 코드·테스트 위치

| 무엇 | 어디 |
|---|---|
| 정본 | `apps/core/domain/settlements/models.py::Category` |
| 노출 API | `apps/core/domain/common/views.py::CategoryMetaView` → `/api/meta/categories/` |
| 저장 검증 | `apps/core/domain/settlements/views.py::_invalid_category` |
| scope 정규화 | `apps/core/domain/policies/scope.py::normalize_scope` |
| ai 조회·캐시 | `apps/ai/app/clients/core_client.py::get_categories` |
| ai enum 재생성 | `apps/ai/app/agents/draft_agent.py::_with_categories` |
| ai scope 검증 | `apps/ai/app/agents/rule_agent_v0/api.py::_validate_scope` |
| web 훅 | `apps/web/src/lib/categories.ts::useCategories` |
| 회귀(core) | `domain/settlements/tests/test_category_vocabulary.py` (15건) |
| 회귀(ai) | `apps/ai/tests/test_category_vocabulary.py` (8건) |

---

## 6. 분류를 늘리려면 (체크리스트)

1. `Category`에 값 추가
2. `makemigrations` — `RuleGraph.ck_rulegraph_scope` 넓히기가 생긴다(값을 **빼거나 이름을
   바꾸는** 변경이면 넓히기→이관→좁히기 3단계로. `policies/0009~0011` 참조)
3. `seed_clean`의 `default_limits`에 기본 한도 추가(빠뜨리면 `missing` assert가 잡는다)
4. `apps/web/src/types/domain.ts` — `CATEGORY_TONE`에 색, `CATEGORIES_FALLBACK`에 값
   (둘 다 폴백/표현용. **목록 자체는 서버에서 온다**)
5. `apps/ai/app/schemas.py::Category` 미러 — core 미기동 시 폴백용
6. (선택) `rule_agent_v0/agent.py::DEFAULT_QUERIES`에 질의 힌트 — 없으면
   `f"{scope} 관련 규정"`으로 떨어지므로 막히지는 않는다

4·5는 **없어도 동작한다**(폴백 목록이 한 세대 낡을 뿐). 1~3만 필수다.
