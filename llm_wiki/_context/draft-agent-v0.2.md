# Draft Agent v0 구현 설계서 — Input 구조화 & 프롬프팅

> 파생 컨텍스트. 권위 규범 = `_context/draft-agent-plan.md`(§4-1 착수 조건, §4-2 A-1~A-4)를 코드 작성 직전 수준으로 구체화한 것.
> **이 문서는 설계서다.** 아래 코드 블록은 전부 "이렇게 짜면 된다"는 사전 스펙이며, 아직 코드에 반영되지 않았다.

---

## 0. 코드베이스 현황 (as-is)

| 파일 | 현재 상태 | v0에서 필요한 조치 |
|---|---|---|
| `apps/ai/app/api/draft.py` | `DraftRequest`가 `settlement_id: int` 하나만 받는 stub. 계약(merchant/amount/…)과 무관 | 전면 재작성 |
| `apps/ai/app/agents/draft_agent.py` | `run(settlement_id)` → 고정 dict 반환 | 전면 재작성 |
| `apps/ai/app/mcp/tools.py`의 `get_policy(category)` | `{"limit": None, "required_evidence": [], "refs": []}`만 반환하는 stub(Django 미연동) | v0에서는 쓰지 않는다. `draft_agent.py` 안에 더미 dict를 직접 하드코딩. 실연동은 v1(B-3) |
| `apps/ai/requirements.txt` | `openai>=1.40,<2.0` 이미 포함 | 조치 불필요 |
| `apps/ai/app/config.py` | `settings.openai_api_key`가 `.env`에서 로드됨 | `OpenAI(api_key=settings.openai_api_key)`로 바로 사용 |
| `apps/core/domain/settlements/draft_agent.py` (Django 플레이스홀더) | 6개 분류 키워드맵·정책 임계값·목적 템플릿이 규칙 코드로 존재 | "뭘 반영해야 하는지" 아이디어만 참고. 그대로 옮기면 LLM을 쓰는 의미가 없음 |
| `apps/core/domain/policies/models.py`의 `Policy` | `category`, `limit_amount`, `required_evidence`, `tax_note`, `refs` 필드를 가진 실제 테이블 | v0와 무관. §2 더미 dict를 이 필드명에 맞춰두면 v1 전환이 수월(`limit` → `limit_amount`) |
| Django `draft_suggest` 액션 (`views.py`) | FastAPI를 호출하지 않고 Django 플레이스홀더를 직접 호출 중 | v0 범위 아님(v1, B-5) |

---

## 1. Input/Output 스키마

생성 모드만 지원한다. `instruction`/`receipt_image` 필드는 계약을 지키기 위해 스키마엔 남기되 로직에서는 무시한다(v1에서 분기 추가할 자리 확보). 값이 정해진 필드(`cardType`/`evidence`/`category`)는 `Literal`로 제한해, 잘못된 값이 조용히 통과해 화면까지 흘러가는 걸 막는다.

### 1-1 요청 스키마

```python
# apps/ai/app/api/draft.py
from typing import Literal, Optional
from pydantic import BaseModel

CardType = Literal["PERSONAL", "TEAM", "SHARED", "POST_PAID", "PREPAID"]
Evidence = Literal["OK", "MISSING"]
Category = Literal["회식", "회의", "식대", "출장", "접대", "비품"]  # 2026-08-14: 업무활성 폐지 → 회식

class DraftRequest(BaseModel):
    merchant: str
    amount: int
    date: Optional[str] = None
    ts: Optional[str] = None            # date/ts 중 하나만 와도 되게 둘 다 optional
    cardType: CardType
    evidence: Optional[Evidence] = "OK"
    headcount: Optional[int] = 0        # 실제 프론트는 생성 모드에서 이 필드를 보내지 않음 → 기본값 필수
    instruction: Optional[str] = None   # v0는 무시(항상 생성 모드). v1 분기용 자리만 확보
    receipt_image: Optional[str] = None # v0 범위 밖. 받아도 무시

    def resolved_ts(self) -> str:
        return self.date or self.ts or ""
```

`instruction`이 채워져서 와도 v0는 에러 없이 항상 생성 모드로 응답한다. 수정 모드의 실제 요청은 이 flat 구조가 아니라 `{ instruction, current: {...} }` 중첩 구조로 오므로(`draft-agent-plan.md` §3-2), v1에서는 이 `DraftRequest`를 재사용하지 않고 별도의 `ReviseRequest`를 신설한다.

### 1-2 응답 스키마

```python
class DraftComment(BaseModel):
    icon: Literal["ocr", "ai", "doc"]
    text: str

class PolicyHint(BaseModel):
    level: Literal["warn", "info"]
    clause: str
    text: str
    status: str

class Draft(BaseModel):
    merchant: str
    amount: int
    category: Category
    aiCategory: Category
    aiSuggested: bool
    merchantIndustry: str = ""
    purpose: str
    evidence: Evidence
    headcount: int = 0

class DraftResponse(BaseModel):
    mode: Literal["create", "revise"] = "create"
    draft: Draft
    confidence: float
    comments: list[DraftComment]
    policyHints: list[PolicyHint]
```

v0는 `mode`가 항상 `"create"`다.

### 1-3 라우터

```python
router = APIRouter()

@router.post("/draft", response_model=DraftResponse)
def run_draft(req: DraftRequest):
    return draft_agent.run(req)
```

엔드포인트 경로(`POST /agent/draft`)는 기술명세서 §4.1과 동일하게 유지한다.

### 1-4 1차 방어

- 필수 필드 누락(merchant/amount/cardType) → pydantic이 자동으로 422 반환.
- LLM이 6개 분류 밖의 값을 내놓는 경우는 §4-2에서 후처리로 방어한다(입력 검증 아님).

---

## 2. 더미 정책 설계 (`get_policy` 대체)

`policyHints`는 LLM이 지어내지 않고, 아래 숫자를 근거로 파이썬 코드가 결정론적으로 생성한다(감사 가능성 원칙).

```python
# apps/ai/app/agents/draft_agent.py
DUMMY_POLICY = {
    "limit": 30000,                 # 이 금액을 넘으면 증빙 필요(v0 더미 기준). 실제 Policy 모델은 limit_amount 필드(v1 참고)
    "required_evidence": ["영수증"],
}

def _build_policy_hints(amount: int, evidence: str) -> list[dict]:
    hints = []
    if amount > DUMMY_POLICY["limit"]:
        hints.append({
            "level": "warn" if evidence != "OK" else "info",
            "clause": "DUMMY-POLICY-01",
            "text": f"{DUMMY_POLICY['limit']:,}원을 초과하면 증빙이 필요합니다 (v0 더미 기준값).",
            "status": "증빙 첨부됨" if evidence == "OK" else "증빙 미첨부 → 첨부를 권장합니다.",
        })
    return hints
```

DoD 조건(정책 힌트 최소 1건 동작)은 검증 샘플 2·3건(320,000원/59,800원, 둘 다 30,000원 초과)에서 충족된다. 1인당 한도 같은 로직은 v0에 추가하지 않는다(v1에서 실연동 시 확장).

---

## 3. 프롬프트 설계

### 3-1 시스템 프롬프트

```
당신은 법인카드 정산 초안 작성 보조입니다.

반드시 지켜야 할 규칙:
1. 비용 분류(category)는 다음 6개 중 하나만 선택하세요: 회식, 회의, 식대, 출장, 접대, 비품.
2. 가맹점 업종(merchantIndustry)은 참고용 힌트일 뿐이며, 세무·회계 판단의 근거로 사용하지 마세요.
3. 판단 확신이 낮으면 aiSuggested를 true로 하고 confidence를 낮게(0.5 이하) 주세요.
   확신이 높으면 aiSuggested는 true로 유지하되(v0는 전부 사람 확인 대상) confidence만 높게 주세요.
4. purpose(지출 목적)는 가맹점·금액·참석 인원 정보를 근거로 1~2문장으로 자연스럽게 작성하세요.
   참석 인원 정보가 없으면(0명) 인원수를 언급하지 말고 목적만 작성하세요.
5. 정책 한도·규정 문구는 절대 스스로 계산하거나 만들어내지 마세요. policyHints는 서버가 별도로 채웁니다.
6. 반드시 아래 JSON 형식으로만 답하세요. 다른 설명 문장을 붙이지 마세요.

{
  "category": "식대",
  "merchantIndustry": "업종 추정 또는 빈 문자열",
  "purpose": "지출 목적 문장",
  "confidence": 0.0에서 1.0 사이 숫자,
  "aiSuggested": true 또는 false,
  "comments": [
    {"icon": "ai", "text": "이 분류를 선택한 이유"},
    {"icon": "doc", "text": "지출 목적을 이렇게 작성한 이유 또는 사용자에게 확인 요청하는 문장"}
  ]
}
```

### 3-2 유저 프롬프트 템플릿

```
가맹점: {merchant}
금액: {amount}원
일시: {ts}
카드구분: {card_type}
증빙 여부: {evidence}
참석 인원: {headcount}명 (0이면 정보 없음)
```

`instruction`은 v0에서 프롬프트에 넣지 않는다(생성 모드만 지원).

### 3-3 JSON mode (strict Structured Output은 v1)

v0는 OpenAI `response_format={"type": "json_object"}`(느슨한 JSON 모드, enum 강제 없음)만 건다 — 코드 한 줄로 "```json` 코드펜스가 섞여 파싱 실패" 같은 흔한 문제를 막을 수 있다. `enum` 강제(json_schema strict)는 v1(B-2)에서 진행한다.

---

## 4. 조립 로직

### 4-1 OpenAI 호출 함수

```python
# apps/ai/app/agents/draft_agent.py
import json
from openai import OpenAI
from app.config import settings

_client = OpenAI(api_key=settings.openai_api_key)
_MODEL = "gpt-4o-mini"  # 키 권한에 따라 조정. model_not_found면 사용 가능 모델로 교체

def _call_llm(req: "DraftRequest") -> dict:
    user_prompt = USER_PROMPT_TEMPLATE.format(
        merchant=req.merchant,
        amount=req.amount,
        ts=req.resolved_ts(),
        card_type=req.cardType,
        evidence=req.evidence or "OK",
        headcount=req.headcount or 0,
    )
    resp = _client.chat.completions.create(
        model=_MODEL,
        response_format={"type": "json_object"},
        temperature=0.3,
        timeout=15,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    return json.loads(resp.choices[0].message.content)
```

### 4-2 조립 함수 (`run`)

전체 후처리(분류 clamp, 타입 변환 포함)를 `try` 안에 두어, LLM이 예상 밖 타입(예: `confidence`를 문자열로 반환)을 내놓아도 500 없이 항상 200으로 방어한다.

```python
VALID_CATEGORIES = {"회식", "회의", "식대", "출장", "접대", "비품"}

def run(req: "DraftRequest") -> dict:
    try:
        llm_out = _call_llm(req)

        category = llm_out.get("category")
        comments = list(llm_out.get("comments", []))
        if category not in VALID_CATEGORIES:
            # 2026-08-14: 미분류 캐치올 기본값은 "회식"이 아니라 "비품"이다 — "회식"은 팀 회식이라는
            # 구체적 의미를 가진 독립 카테고리로, "판단 불가"의 기본값으로 쓰면 안 된다.
            category = "비품"
            comments.append({"icon": "ai", "text": "분류 추정이 불분명해 기본값(비품)으로 조정했습니다."})

        draft = {
            "merchant": req.merchant,
            "amount": req.amount,
            "category": category,
            "aiCategory": category,
            "aiSuggested": bool(llm_out.get("aiSuggested", True)),
            "merchantIndustry": llm_out.get("merchantIndustry", ""),
            "purpose": llm_out.get("purpose", ""),
            "evidence": req.evidence or "OK",
            "headcount": req.headcount or 0,
        }
        confidence = float(llm_out.get("confidence", 0.5))

    except Exception as exc:  # OpenAI 호출 실패·JSON 파싱 실패·타입 이상 등 전부 여기서 흡수
        comments = [{"icon": "ai", "text": f"LLM 호출/응답 처리에 실패해 기본값으로 채웠습니다: {exc}"}]
        draft = {
            "merchant": req.merchant,
            "amount": req.amount,
            "category": "비품",
            "aiCategory": "비품",
            "aiSuggested": True,
            "merchantIndustry": "",
            "purpose": f"{req.merchant} 관련 지출 (초안 자동 생성 실패)",
            "evidence": req.evidence or "OK",
            "headcount": req.headcount or 0,
        }
        confidence = 0.3

    return {
        "mode": "create",
        "draft": draft,
        "confidence": confidence,
        "comments": comments,
        "policyHints": _build_policy_hints(req.amount, req.evidence or "OK"),
    }
```

### 4-3 에러/폴백 정책

| 상황 | 처리 |
|---|---|
| `OPENAI_API_KEY` 비어있음 | 클라이언트 생성은 실패하지 않음(지연 평가) → 실제 호출 시 예외 → `except`가 흡수 → 200 유지 |
| JSON 파싱 실패 | `response_format=json_object`로 대부분 방지, 실패해도 동일하게 폴백 |
| 6개 분류 밖 값 / 필드 타입 이상 | `try` 블록 안에서 함께 방어(clamp 또는 예외 → 폴백) |
| 타임아웃 | `timeout=15` 고정, 초과 시 예외 → 폴백 |

---

## 5. 검증 계획

```bash
cd apps/ai
uvicorn app.main:app --reload --port 9000
```

```bash
curl -s -X POST http://localhost:9000/agent/draft -H "Content-Type: application/json" -d '{
  "merchant": "스타벅스 강남점", "amount": 8400, "ts": "2026-08-10T09:12:00",
  "cardType": "PERSONAL", "evidence": "OK", "headcount": 0
}' | jq

curl -s -X POST http://localhost:9000/agent/draft -H "Content-Type: application/json" -d '{
  "merchant": "한우마을", "amount": 320000, "ts": "2026-08-10T19:00:00",
  "cardType": "TEAM", "evidence": "OK", "headcount": 4
}' | jq

curl -s -X POST http://localhost:9000/agent/draft -H "Content-Type: application/json" -d '{
  "merchant": "KTX 서울-부산", "amount": 59800, "ts": "2026-08-10T07:30:00",
  "cardType": "POST_PAID", "evidence": "MISSING", "headcount": 0
}' | jq
```

확인 포인트:

1. 200 응답
2. `mode`, `draft.category`, `draft.purpose`, `confidence`, `comments`가 채워짐
3. `draft.category`가 6개 중 하나(샘플 1은 회의/식대, 2는 접대/식대, 3은 출장 근처 — 정확도 개선은 v1)
4. `policyHints`가 최소 1건(샘플 2·3은 30,000원 초과이므로 반드시 뜸, 샘플 1은 안 떠도 정상)

---

## 6. 파일별 변경 사항

| 파일 | 조치 |
|---|---|
| `apps/ai/app/api/draft.py` | 전면 재작성 (§1) |
| `apps/ai/app/agents/draft_agent.py` | 전면 재작성 (§2, §3, §4) |
| `apps/ai/app/mcp/tools.py` | 손대지 않음 — `get_policy` 실연동은 v1(B-3) |
| `apps/ai/app/config.py`, `requirements.txt`, `.env` | 변경 불필요 |

---

## 7. v0가 하지 않는 것

- Structured Output strict schema / enum 강제 (v1, B-2)
- 수정 모드 처리 — 페이로드가 `{instruction, current:{...}}` 중첩 구조 (v1, B-4)
- `get_policy` 실제 Django 연동 (v1, B-3)
- 영수증 이미지 처리
- Django `draft_suggest` → FastAPI 호출 배선 (v1, B-5)
- `evidence`/`headcount`를 Settlement DB에 영구 저장 (현재 Django 모델에 해당 컬럼 자체가 없음 — 스키마 결정 선행 필요, `draft-agent-plan.md` §7 참고)

---

## 8. 인계 메모 (템플릿)

- 사용한 모델명 / temperature
- 검증 샘플 3건 응답 로그 원문
- 프롬프트에서 애매했던 부분 (예: `merchantIndustry`를 LLM이 근거 없이 지어내는 것에 대한 우려, `confidence`가 실제 신뢰도를 반영하는지)
