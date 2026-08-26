"""시연용 **적용 완료** 시드 — 3개월째 굴러가고 있는 회사.

    docker compose exec core python manage.py seed_adopted
    docker compose exec core python manage.py seed_adopted --dry-run   # 지울 것만 보고 멈춤

`seed_clean`(막 설치한 회사)의 **반대편 끝**이다. 규정 문서를 올려 과목별 룰까지 만들었고,
직전 3개월(이번 달 포함)의 정산이 실제로 흘러간 상태를 만든다 — 통계·예산·전표·검토 이력이
전부 차 있어야 하는 화면을 이 시드 하나로 채운다.

`seed`(기존 시연 시드)와도 목적이 다르다. `seed`는 **한 화면씩 골고루** 보여주려고 이번 달
안에 온갖 상태를 흩어 놓은 데이터고, 여기는 **시간이 흐른 회사**다: 6·7월은 끝나 있고
이번 달만 살아 있다.

## 무엇이 진짜인가 (이 시드의 규율)

**판정을 손으로 박지 않는다.** 상태·`rule_hits`·`SettlementEvent`·ERP 전표는 전부
`settlements.services`의 실제 전이를 태워서 나온 결과다(`raise_to_team → submit → judge →
review/confirm`). 시드가 상태 문자열을 직접 쓰기 시작하면 화면에 보이는 이력이 서비스가
만드는 이력과 조용히 달라진다.

그래서 시드는 **사실만 정하고 판정은 기대만 적는다**(`expect`). 엔진이 다른 답을 내면
조용히 받아들이지 않고 **끝에 불일치 목록을 출력한다** — 룰이 바뀌었는데 시드가 안 따라온
상황을 그 자리에서 알아채기 위해서다.

## 손으로 만드는 것 둘 — 그리고 그 이유

  · **시각** — `SettlementEvent.created_at`·`Settlement.created_at`은 `auto_now_add`라
    무엇을 해도 "지금"이 박힌다. 지난달 건의 이력이 전부 오늘로 찍히면 월별 통계가
    무너지므로, 전이 직후 그 건의 행들을 결제일 기준으로 되돌려 놓는다.
  · **이상탐지 결과** — 검토로 넘어간 건의 `RiskReview`는 여기서 직접 쓴다. Risk Review
    Agent를 백 번 부르면 시연 준비에 수십 분과 토큰이 든다(`risk_review.AUTO_SCHEDULE`을
    꺼서 예약 자체를 막는다). **이 값들은 시연용 대역이다.**

## 룰 그래프 — DEFAULT GATE는 여기 없다

`seed_rules`가 심는 4계열(공통 게이트 v3 · 기업업무추진비 v2 · 회식비 v1 · 출장비 승인대기)이
ACTIVE다. 제품 기본 게이트(`seed_clean`의 DEFAULT GATE)는 같은 GLOBAL scope라 `_upsert`가
**ARCHIVED로 물러나게** 한다 — 그게 이 시나리오의 서사 그대로다(제품 기본값으로 시작해
회사 규정 반영본으로 개정됨). 초기 상태는 `seed_clean`에서 본다.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import random
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from django.core.management import call_command
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from domain.accounts.models import Capability, JobTitle, Position, Role, Team, User
from domain.cards.models import Card, CardType
from domain.erp.models import ErpVoucher
from domain.notifications.models import Notification
from domain.policies.models import PolicyTable, RuleGraph, RuleHit
from domain.policies.tiger_tables import upsert_all as upsert_policy_tables
from domain.risk.models import DecisionCase, RiskReview
from domain.settlements.attachments import Attachment, AttachmentKind, ExtractionStatus
from domain.settlements import risk_review as risk_review_module
from domain.settlements import services as settlement_services
from domain.settlements.models import Category as C, Settlement, SettlementEvent
from domain.settlements.models import SettlementStatus as S
from domain.transactions import industry as industry_vocab
from domain.transactions.models import MerchantCategory, MerchantSource, Receipt, Transaction

#: 시연 재현성 — 같은 커맨드를 두 번 돌리면 같은 데이터가 나와야 캡처와 화면이 안 어긋난다.
SEED = 20260823

#: 만들 개월 수(이번 달 포함). 3이면 이번 달·지난달·지지난달.
MONTHS_BACK = 3


# ════════════════════════════════════════════════════════════════════════════
#  지출 사실 한 건
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class Spend:
    """정산 한 건이 되는 **사실**. 판정 결과는 여기 없다 — 엔진이 정한다.

    `expect`는 "이 사실이면 룰이 이렇게 볼 것"이라는 시드의 **주장**이고,
    `outcome`은 그 뒤에 사람이 무엇을 했는가다. 둘을 나눠 둬야 "룰이 통과시켰는데
    사람이 되돌린 건"을 만들 수 있다(실제로 자주 일어나는 일이다).
    """
    owner: User
    merchant: str
    industry: str
    category: str
    item_type: str
    amount: int
    card: Card
    year: int
    month: int
    day: int
    hour: int
    purpose: str
    #: 엔진이 낼 것으로 기대하는 판정 — PASS / REVIEW / RETURN
    expect: str = "PASS"
    #: 사람까지 포함한 결말 — confirm / approve(검토 후 승인) / fix(보완 후 재제출) /
    #:  reject(최종반려) / inflight_team / inflight_pending / inflight_review / inflight_draft
    outcome: str = "confirm"
    receipt: bool = True
    headcount: int | None = None
    external_headcount: int | None = None
    #: **문서로 확인된** 인원(참석자 명단 첨부에서 읽어낸 값). 신고값(`headcount`)과 다른 축이다 —
    #  법정 한도 판정은 본인이 적은 인원으로 나누면 인원을 부풀려 한도를 피할 수 있어서
    #  확인값만 쓴다(`seed_rules` E-003). `None`이면 명단 첨부를 만들지 않는다.
    verified_headcount: int | None = None
    pre_approved: bool | None = None
    kickback_target: bool | None = None
    is_secondary_venue: bool | None = None
    includes_alcohol: bool | None = None
    minute: int = 0
    #: 공용·팀 카드에서만 의미가 있다. `None`(모름)으로 두면 공통 게이트 R-004가
    #  참조하는 경로가 미해소라 판정 전체가 REVIEW로 강등된다.
    actual_user_recorded: bool | None = None
    #: 검토로 간 건에 붙일 이상탐지 대역값(0~1). 없으면 등급만 낮게 잡는다.
    anomaly: float = 0.0
    anomaly_reasons: list[str] = field(default_factory=list)
    #: **AI가 권고한 처리**(`RiskReview.ai_recommendation`). 비면 결말에 맞춘다 — 그러면
    #  사람과 기계가 같은 결론이라 사례가 남지 않는다(`decision_cases.record`는 다를 때만
    #  기록한다). 사례를 만들려면 여기에 **사람과 다른 값**을 적는다.
    ai_recommends: str = ""
    #: 회계 담당자가 쓴 결정 사유. **이 문장이 사례의 본체다** — 임베딩되는 `text`의 끝에
    #  그대로 실리고, 다음 건의 2차 검증이 이걸 근거로 끌어온다. 비면 기본 문장을 쓴다.
    reason: str = ""
    #: 사례 패턴 라벨(보고용). 사례로 의도한 건인지 끝에서 대조한다.
    case_pattern: str = ""
    #: 보완 후 재제출 때 **실제로 채워지는 값**. 상태만 되돌리고 사실을 그대로 두면
    #  재판정이 같은 사유로 또 걸려 「보완했는데 여전히 검토 중」으로 남는다.
    fix_purpose: str = ""
    fix_industry: str = ""


# ── 가맹점 사전 ────────────────────────────────────────────────────────────
#  (표시명, 정본 업종 어휘, 세부유형). 업종은 `transactions.industry` 표기를 그대로 쓴다 —
#  자유 표기를 넣으면 조립기가 접지 못해 `merchant.merchant_info_resolved=False`가 되고,
#  공통 게이트의 심야·업종미확인 분기가 엉뚱하게 걸린다.
MERCHANTS: dict[str, list[tuple[str, str, str]]] = {
    C.MEAL: [
        ("김밥천국 여의도", "일반음식점", "식사"), ("본죽 역삼점", "일반음식점", "식사"),
        ("설렁탕집 여의도", "일반음식점", "식사"), ("김가네 강남", "일반음식점", "식사"),
        ("백반집 삼성", "일반음식점", "식사"), ("배달의민족", "일반음식점", "식사"),
    ],
    C.MEETING: [
        ("스타벅스 강남점", "카페", "식사"), ("투썸플레이스 을지로", "카페", "식사"),
        ("메가커피 역삼", "카페", "식사"), ("성수동 커피랩", "카페", "식사"),
        ("위워크 회의실", "기타", "행사성"),
    ],
    C.GATHERING: [
        ("포차 정든", "일반음식점", "행사성"), ("고기집 한마당", "일반음식점", "행사성"),
        ("호프 갈매기", "일반음식점", "행사성"), ("이자카야 다시", "일반음식점", "행사성"),
    ],
    C.ENTERTAIN: [
        ("한우명가 여의도", "일반음식점", "식사"), ("그랜드호텔 레스토랑", "일반음식점", "식사"),
        ("일식당 소라", "일반음식점", "식사"), ("비즈니스 다이닝", "일반음식점", "식사"),
    ],
    C.TRIP: [
        ("코레일 KTX", "주유/교통", "교통"), ("SRT 수서-동대구", "주유/교통", "교통"),
        ("대한항공", "주유/교통", "교통"), ("신라스테이 대전", "숙박", "숙박"),
        ("카카오T", "주유/교통", "교통"), ("GS칼텍스 주유", "주유/교통", "교통"),
    ],
    #  「비품」 과목이 폐기되면서(2026-08-24) 소모품·사무용품 구매가 여기로 왔다 —
    #  나열된 다섯 과목 어디에도 안 맞는 지출이 모이는 자리다.
    C.OTHER: [
        ("오피스디포", "문구/사무용품", "소모품"), ("알파문구", "문구/사무용품", "소모품"),
        ("다이소 역삼", "문구/사무용품", "소모품"), ("쿠팡", "기타", "소모품"),
        ("교보문고", "문구/사무용품", "소모품"), ("테크노마트", "전자/가전", "소모품"),
        ("우체국 등기", "기타", "기타"), ("공영주차장", "주유/교통", "기타"),
    ],
}

#: 과목별 금액대(원). 회식·접대는 1인당 한도가 걸리는 축이라 인원과 함께 잡는다.
AMOUNTS: dict[str, tuple[int, int]] = {
    C.MEAL: (8_000, 95_000),
    C.MEETING: (12_000, 68_000),
    C.GATHERING: (180_000, 520_000),
    C.ENTERTAIN: (120_000, 280_000),
    C.TRIP: (14_000, 240_000),
    C.OTHER: (4_000, 180_000),      # 소모품(~18만) ∪ 기타 잡비(4천~) — 폐기된 비품 대역 흡수
}

PURPOSES: dict[str, list[str]] = {
    C.MEAL: ["야근 식대", "주말 근무 식대", "현장 근무 식대", "월말 마감 식대"],
    C.MEETING: ["주간 회의 다과", "거래처 미팅 음료", "스프린트 회고 다과", "킥오프 미팅"],
    C.GATHERING: ["분기 마감 팀 회식", "신규 입사자 환영 회식", "프로젝트 완료 회식"],
    C.ENTERTAIN: ["거래처 계약 협의", "신규 거래처 상담", "재계약 협의 식사"],
    C.TRIP: ["지방사업장 출장", "고객사 방문 이동", "출장 숙박", "본사 회의 참석"],
    C.OTHER: ["사무 비품 구매", "제안서 인쇄 용지", "개발 장비 소모품", "기술 서적 구입",
              "증빙 원본 발송", "출장 중 주차"],
}


# ════════════════════════════════════════════════════════════════════════════
#  결정 사례 — 회계 담당자가 기계와 **다르게** 판단한 건
# ════════════════════════════════════════════════════════════════════════════
#  `decision_cases.record()`는 사람의 결정이 AI 권고(또는 룰 판정)와 **다를 때만** 사례를
#  남긴다. 그래서 시드가 사례를 만들려면 `ai_recommends`에 사람과 다른 값을 적어야 한다 —
#  예전엔 AI 권고를 결말에서 뽑아 써서 둘이 항상 같았고, 185건을 돌려도 사례가 **0건**이었다.
#
#  ## 왜 세 패턴인가 — 서로 다른 것을 가르친다
#
#    A **소명 확인** (AI 반려 → 사람 승인)  … 형식 신호는 위반인데 맥락이 정당했다.
#      가르치는 것: **오탐 교정.** 같은 신호가 또 와도 그것만으로 반려하지 않는다.
#    B **놓친 실질** (AI 승인 → 사람 보완·반려) … 형식은 다 맞는데 실질이 어긋났다.
#      가르치는 것: **미탐 교정.** 통과 신호가 곧 정상이 아니다.
#    C **수위 조정** (AI 반려 → 사람 보완요청) … 위반은 맞지만 고칠 수 있는 것이었다.
#      가르치는 것: **처리 등급.** `REJECT`는 최종반려라 재제출이 막힌다 — 고칠 수 있으면
#      보완이다. 이건 규정이 아니라 **이 회사가 일하는 방식**이라 문서에서 못 뽑는다.
#
#  A는 판정을 낮추고, B는 올리고, C는 **같은 위반을 다른 등급으로** 처리한다. 하나만
#  쌓으면 검색이 한쪽으로 쏠린다.
#
#  ## 사실은 「엔진이 실제로 REVIEW를 내는 것」에서만 고른다
#
#  사례는 검토를 거쳐야 생긴다(`services.review()`가 남긴다). 그래서 조리법은 **ACTIVE
#  그래프를 실측해서** 골랐다 — 그럴듯한 위반이 아니라 실제로 `REVIEW`가 나오는 사실이다.
#  실측(2026-08-26)에서 **회식 1인당 한도 초과는 `RETURN`이고**(M-01) **심야·주말 룰은
#  게이트에 없다**(v7). 그럴듯해 보여서 썼다가 사례가 21건 증발했다.
#
#  ## 사유 문장이 사례의 본체다
#
#  임베딩되는 `text`는 `상황 + "AI 권고는 X였으나 담당자는 Y로 판단" + 사유`다. 앞의 둘은
#  코드가 조립하므로 **값어치는 전부 `reason`에 있다.** 무엇을 확인했는지·어느 조항인지를
#  문장 안에 담는다 — "확인했으므로 승인함"은 검색돼도 쓸모없다.

#: 조리법 — 엔진이 `REVIEW`를 내는 사실 묶음. 값은 `_plan_month.spend()`에 넘길 인자다.
#  세 경로 모두 ACTIVE 그래프에서 확인했다.
CASE_RECIPES = {
    #  E-03 청탁금지법 대상자 참석 + 1인당 법정 한도 초과 → REVIEW.
    #  **법률 리스크라 룰이 자동 처리하지 않는다** — 이 제품에서 REVIEW의 정석이다.
    "entertain_kickback": dict(
        team="영업팀", category=C.ENTERTAIN, amount=(185_000, 275_000), headcount=4,
        external_headcount=2, kickback_target=True, pre_approved=True,
        anomaly=(0.62, 0.82), anomaly_reasons=["청탁금지법 대상자 참석", "1인당 법정 한도 초과"],
    ),
    #  업종을 정본 어휘로 접지 못한 가맹점 → `merchant.merchant_info_resolved=False` →
    #  공통 게이트의 화이트리스트(G-PASS)를 못 넘어 G-REVIEW.
    #  **`기타`로 밀지 않는 설계가 그대로 드러나는 자리다**(CLAUDE.md §2) — 모르면 모른다고
    #  하고 사람에게 넘긴다. 신규 개업·해외 결제·상호 변경에서 실제로 자주 난다.
    "merchant_unknown": dict(
        team="영업팀", category=C.MEAL, amount=(45_000, 180_000), industry="",
        anomaly=(0.35, 0.6), anomaly_reasons=["가맹점 업종 미확인"],
    ),
    #  목적란이 비어 `evidence.expense_purpose_missing=True` → 같은 화이트리스트에서 탈락.
    "purpose_missing": dict(
        team="AI·개발팀", category=C.MEETING, amount=(30_000, 140_000), purpose="",
        anomaly=(0.3, 0.52), anomaly_reasons=["지출 목적 미기재"],
    ),
}

#: 사례 30건. `month`는 몇 번째 달인가(0=가장 오래된 달).
#  **달을 앞쪽에 몰았다** — 도입 1개월차엔 사람이 많이 뒤집고, 룰이 쌓일수록 준다. 그게
#  이 제품의 진척도 서사 그대로이고(CLAUDE.md §2 「회계가 규칙을 쌓을수록 확정이 늘고
#  검토가 준다」), 세 달에 고르게 펴면 그 곡선이 안 보인다.
#  `fix_*`는 보완 후 재제출 때 **실제로 고쳐지는 값**이다(`_remediate`) — 상태만 되돌리고
#  사실을 그대로 두면 재판정이 같은 사유로 또 걸린다.
CASES: list[dict] = [
    # ══ A · 소명 확인 (AI 반려 권고 → 담당자 승인) ═══════════════════════════
    dict(pattern="A", recipe="entertain_kickback", month=0, ai="REJECT", outcome="approve",
         purpose="공개 기술세미나 다과",
         reason="공공기관 담당자가 참석자 명단에 있으나 불특정 다수를 대상으로 한 공개 "
                "세미나의 다과이고 참석자 전원에게 동일하게 제공됐습니다. 청탁금지법 "
                "제8조③1호의 예외에 해당해 1인당 한도 계산 대상이 아닙니다. 세미나 공지와 "
                "참석자 명단으로 확인했습니다."),
    dict(pattern="A", recipe="entertain_kickback", month=0, ai="REJECT", outcome="approve",
         purpose="계약 체결 후 사업 협의",
         reason="외부 참석자를 다시 세어(2명→3명) 1인당 금액을 재계산한 결과 법정 한도 "
                "이하입니다. 계약서와 참석자 명단으로 인원을 확인했고, 상대방은 청탁금지법 "
                "적용 대상이 아닌 민간 기업 담당자였습니다. AI 권고는 신고 인원 기준 "
                "계산에 따른 것입니다."),
    dict(pattern="A", recipe="merchant_unknown", month=0, ai="REJECT", outcome="approve",
         merchant="성수 브런치랩", category=C.MEAL, purpose="현장 근무 식대",
         reason="업종이 확인되지 않아 판정이 보류됐으나, 사업자등록증으로 일반음식점임을 "
                "확인했습니다. 신규 개업 가맹점이라 업종 데이터가 아직 없는 것이지 "
                "금지업종이 아닙니다. 가맹점 정보를 등록했으니 다음 건부터는 자동 "
                "판정됩니다."),
    dict(pattern="A", recipe="merchant_unknown", month=0, ai="REJECT", outcome="approve",
         merchant="TOKYO STATION HOTEL", category=C.TRIP, amount=(150_000, 240_000),
         purpose="해외 출장 숙박",
         reason="해외 가맹점이라 국내 업종 분류에 걸리지 않은 건입니다. 출장 품의서의 "
                "일정·지역과 결제일이 일치하고 숙박비는 별표3의 해당 지역등급 상한 "
                "이내입니다. 업종 미확인은 해외 결제에서 정상적으로 발생합니다."),
    dict(pattern="A", recipe="purpose_missing", month=0, ai="REJECT", outcome="approve",
         reason="목적란이 비어 있으나 첨부된 회의록에 안건·참석자·일시가 모두 있습니다. "
                "ERP에서 자동 수집된 건이라 목적란이 비어 들어온 것이고, 지출 자체의 "
                "문제가 아닙니다. 회의록으로 업무 관련성이 확인되므로 승인합니다."),
    dict(pattern="A", recipe="entertain_kickback", month=1, ai="REJECT", outcome="approve",
         purpose="해외 파트너사 임원 접견",
         reason="상대방이 외국 민간 기업 임원으로 청탁금지법 적용 대상이 아닙니다. 명함과 "
                "사업자등록 정보로 소속을 확인했습니다. 「공공기관 담당자」로 분류된 것은 "
                "가맹점 인근 기관명이 목적란에 적혀 생긴 오인입니다."),
    dict(pattern="A", recipe="merchant_unknown", month=1, ai="REJECT", outcome="approve",
         merchant="(주)오피스온라인", category=C.OTHER, purpose="제안서 인쇄 용지",
         reason="온라인 결제대행 상호로 잡혀 업종이 확인되지 않았습니다. 주문 내역상 실제 "
                "구매 품목은 사무용 인쇄 용지이고 세금계산서도 문구·사무용품으로 "
                "발행됐습니다. 결제대행 상호는 업종 판정의 한계이지 지출의 문제가 "
                "아닙니다."),
    dict(pattern="A", recipe="entertain_kickback", month=1, ai="REJECT", outcome="approve",
         purpose="공공 발주 사업 착수 협의",
         reason="발주기관 담당자가 참석했으나 계약 이행을 위한 공식 착수회의이고 식사는 "
                "회의 시간대에 제공된 것입니다. 청탁금지법 제8조③2호의 공식적 행사 "
                "범위로 판단합니다. 회의록과 착수계로 확인했습니다."),
    dict(pattern="A", recipe="merchant_unknown", month=2, ai="REJECT", outcome="approve",
         merchant="더블유커피 역삼", category=C.MEETING, purpose="스프린트 회고 다과",
         reason="가맹점이 상호를 변경해 업종 캐시가 비었습니다. 사업자등록번호가 기존 "
                "거래처(카페)와 동일한 법인이며 위치도 같습니다. 상호 변경은 업종 미확인의 "
                "흔한 원인이므로 이것만으로 반려할 사유가 되지 않습니다."),
    dict(pattern="A", recipe="purpose_missing", month=2, ai="REJECT", outcome="approve",
         reason="목적이 비어 있으나 같은 날 같은 팀의 회의 일정이 캘린더에 등록돼 있고 "
                "참석자와 결제 시각이 일치합니다. 목적 미기재는 기재 누락이지 업무 관련성 "
                "부재가 아닙니다. 지출자에게 다음부터 목적을 적도록 안내하고 승인합니다."),

    # ══ B · 놓친 실질 (AI 승인 권고 → 담당자 보완요청·반려) ══════════════════
    dict(pattern="B", recipe="entertain_kickback", month=0, ai="APPROVE", outcome="review_return",
         purpose="거래처 상담",
         reason="신고 인원은 4명인데 첨부된 참석자 명단에는 2명만 적혀 있습니다. 1인당 "
                "법정 한도는 확인 인원으로 계산하므로 이 차이가 판정을 뒤집습니다. 실제 "
                "참석자로 명단을 다시 작성해 재제출해 주십시오. AI 권고는 신고값만 보고 "
                "판단한 것입니다."),
    dict(pattern="B", recipe="entertain_kickback", month=0, ai="APPROVE", outcome="review_reject",
         purpose="신규 거래처 상담",
         reason="업무 관련성을 확인할 수 없습니다. 목적란의 거래처와 계약·견적 이력이 없고 "
                "결제 시각(20:50)과 장소가 담당 업무 구역과 무관합니다. 소명 요청에 추가 "
                "자료가 제출되지 않아 최종 반려하며, 해당 금액은 회수 대상입니다."),
    dict(pattern="B", recipe="merchant_unknown", month=0, ai="APPROVE", outcome="review_return",
         merchant="라운지 클럽하우스", category=C.ENTERTAIN, amount=(210_000, 320_000),
         purpose="거래처 접대",
         reason="업종이 확인되지 않은 상태에서 상호와 결제 시각(22시 이후), 금액대가 "
                "유흥업종 가능성을 시사합니다. 법인카드 사용규정 제5조는 유흥업종 사용을 "
                "금지합니다. 업종 확인이 가능한 영수증 원본과 참석자 명단을 제출해 "
                "주십시오."),
    dict(pattern="B", recipe="purpose_missing", month=0, ai="APPROVE", outcome="review_return",
         reason="목적이 비어 있고 회의록·참석자 명단 등 업무 관련성을 확인할 첨부도 "
                "없습니다. 금액이 작아 형식 요건은 통과하지만 지출 근거가 전혀 없는 "
                "상태입니다. 목적을 기재하거나 관련 자료를 첨부해 재제출해 주십시오."),
    dict(pattern="B", recipe="entertain_kickback", month=1, ai="APPROVE", outcome="review_return",
         purpose="재계약 협의 식사",
         reason="같은 금액·같은 가맹점의 정산이 지난달에도 청구돼 있습니다. 중복 청구인지 "
                "별개 회차인지 확인이 필요합니다. 두 건의 면담 기록을 각각 제출해 "
                "주십시오. 단건만 보면 정상이라 이력을 보지 않으면 걸러지지 않습니다."),
    dict(pattern="B", recipe="merchant_unknown", month=1, ai="APPROVE", outcome="review_return",
         merchant="편의점 GS25 도곡", category=C.MEAL, amount=(48_000, 92_000),
         purpose="야근 식대",
         reason="같은 가맹점에서 최근 3주간 평일 저녁마다 유사 금액대 결제가 반복됩니다. "
                "단건으로는 정상이지만 이력을 보면 야근 기록이 없는 회차가 섞여 있습니다. "
                "해당 일자의 근무 기록을 첨부해 주십시오."),
    dict(pattern="B", recipe="entertain_kickback", month=1, ai="APPROVE", outcome="review_return",
         purpose="공공기관 담당자 사업 협의",
         reason="상대방 소속과 직위가 기재되지 않아 청탁금지법 적용 대상 여부를 판단할 수 "
                "없습니다. 업무추진비 규정 제12조③은 접대 상대방의 소속·직위 기재를 "
                "요구합니다. 명함 또는 면담 기록을 첨부해 재제출해 주십시오."),
    dict(pattern="B", recipe="merchant_unknown", month=2, ai="APPROVE", outcome="review_return",
         merchant="한빛상사", category=C.OTHER, amount=(120_000, 180_000),
         purpose="개발 장비 소모품",
         reason="결제 금액이 첨부된 견적서 금액과 다릅니다(견적 98,000원). 차액의 구성이 "
                "확인되지 않으니 최종 세금계산서와 품목 내역을 제출해 주십시오. 업종 "
                "미확인이라 품목으로 검증할 다른 경로도 없습니다."),
    dict(pattern="B", recipe="purpose_missing", month=2, ai="APPROVE", outcome="review_return",
         reason="팀 공용카드로 결제됐는데 실사용자와 정산 제출자가 다르고 그 사유가 "
                "기재되지 않았습니다. 목적란까지 비어 있어 누가 무엇을 위해 썼는지 확인할 "
                "수 없습니다. 법인카드 사용규정 제6조②에 따라 실사용자를 지정하고 목적을 "
                "적어 재제출해 주십시오."),
    dict(pattern="B", recipe="entertain_kickback", month=2, ai="APPROVE", outcome="review_return",
         purpose="협력사 담당자 상담",
         reason="참석자 명단의 외부 인원 2명이 모두 같은 공공기관 소속이고, 같은 분기에 "
                "같은 상대방과의 접대가 3회째입니다. 회차별로는 한도 이내지만 청탁금지법은 "
                "동일인 기준 누적으로도 봅니다. 분기 누적 내역을 정리해 제출해 주십시오."),

    # ══ C · 수위 조정 (AI 반려 권고 → 담당자 보완요청) ═══════════════════════
    dict(pattern="C", recipe="entertain_kickback", month=0, ai="REJECT", outcome="review_fix",
         purpose="공공기관 담당자 포함 사업 협의",
         reason="상대방 소속·직위가 없어 법 위반 소지가 있다는 AI 권고는 타당하나, 이는 "
                "기재 누락이라 보완이 가능합니다. 최종 반려는 재제출을 막으므로 위반이 "
                "확정된 건에만 씁니다. 상대방 정보를 채워 다시 올려 주십시오."),
    dict(pattern="C", recipe="merchant_unknown", month=0, ai="REJECT", outcome="review_fix",
         merchant="대성상회", category=C.OTHER, purpose="사무 비품 구매",
         fix_industry="문구/사무용품",
         reason="업종을 확인할 수 없다는 것과 금지업종이라는 것은 다릅니다. 확인이 안 되는 "
                "단계에서 최종 반려하면 지출자가 소명할 기회가 사라집니다. 사업자등록증 "
                "또는 품목이 보이는 영수증을 첨부하면 판정이 다시 돌아가므로 보완요청으로 "
                "처리합니다."),
    dict(pattern="C", recipe="purpose_missing", month=0, ai="REJECT", outcome="review_fix",
         fix_purpose="주간 스프린트 회고 다과",
         reason="목적 미기재만으로 반려하지 않습니다. 목적란은 화면에서 바로 채울 수 있고 "
                "채우면 자동 재판정되는 항목이라, 반려로 닫으면 그 경로가 막힙니다. 어떤 "
                "업무의 회의였는지 적어 재제출해 주십시오."),
    dict(pattern="C", recipe="entertain_kickback", month=0, ai="REJECT", outcome="review_fix",
         purpose="거래처 계약 협의",
         reason="사전승인 없이 집행된 건입니다. 업무추진비 규정 제8조는 사전승인을 원칙으로 "
                "하되 긴급한 경우 사후 품의를 허용합니다. 사후 품의를 올려 승인받은 뒤 "
                "재제출해 주십시오 — 절차 위반이지 지출 자체의 위반이 아닙니다."),
    dict(pattern="C", recipe="merchant_unknown", month=1, ai="REJECT", outcome="review_fix",
         merchant="바른한우 논현", category=C.MEAL, amount=(90_000, 170_000),
         purpose="현장 근무 식대", fix_industry="일반음식점",
         reason="간이영수증만 첨부돼 업종도 품목도 확인되지 않습니다. 적격증빙이 아니어서 "
                "그대로는 손금 처리가 어렵지만 가맹점에 신용카드 매출전표 재발급을 요청할 "
                "수 있습니다. 재발급분을 첨부해 재제출해 주십시오."),
    dict(pattern="C", recipe="purpose_missing", month=1, ai="REJECT", outcome="review_fix",
         fix_purpose="분기 로드맵 검토 회의 다과",
         reason="목적란이 비어 있어 업무 관련성을 판단할 근거가 없다는 지적은 맞습니다. "
                "다만 회의 참석자가 사내 인원뿐이고 금액도 소액이라 위반이 확정된 건이 "
                "아닙니다. 회의명과 참석 범위를 적어 재제출해 주십시오."),
    dict(pattern="C", recipe="entertain_kickback", month=1, ai="REJECT", outcome="review_fix",
         purpose="신규 거래처 상담",
         reason="참석자 명단에 외부 인원 수만 있고 이름이 없습니다. 청탁금지법 적용 대상 "
                "여부를 가리려면 개인 식별이 필요하지만, 이는 제출로 해소되는 항목이라 "
                "보완요청합니다."),
    dict(pattern="C", recipe="merchant_unknown", month=2, ai="REJECT", outcome="review_fix",
         merchant="아이티몰", category=C.OTHER, amount=(100_000, 180_000),
         purpose="개발 장비 소모품", fix_industry="전자/가전",
         reason="비용분류가 「기타」로 올라왔으나 품목상 소모품 구매가 맞습니다. 분류 "
                "오기재는 지출 자체의 문제가 아니므로 보완으로 처리합니다. 업종 확인 자료와 "
                "함께 분류를 바로잡아 재제출해 주십시오."),
    dict(pattern="C", recipe="entertain_kickback", month=2, ai="REJECT", outcome="review_fix",
         purpose="협력사 임원 면담",
         reason="1인당 법정 한도를 넘었지만 참석자 명단이 신고 인원보다 적어 계산 자체가 "
                "확정되지 않았습니다. 명단을 정확히 채우면 한도 이내일 수 있으므로 "
                "보완요청으로 처리합니다 — 확정되지 않은 위반으로 최종 반려할 수 없습니다."),
    dict(pattern="C", recipe="purpose_missing", month=2, ai="REJECT", outcome="review_fix",
         fix_purpose="고객사 방문 전 사전 미팅",
         reason="목적이 비어 있고 금액도 평소보다 큽니다. 다만 결제 시각·장소가 같은 날 "
                "고객사 방문 일정과 이어지므로 사적 사용으로 단정할 수 없습니다. 방문 "
                "일정과 목적을 적어 재제출해 주십시오."),
]


#: **일부러 비워 둔** 미해소 사실. 업종을 못 접은 가맹점(`merchant_unknown` 조리법)은
#  금지업종 여부도 알 수 없다 — 그게 설계다(모르면 `기타`로 밀지 않고 사람에게 넘긴다,
#  CLAUDE.md §2). 경고 목록에 남기되 「시드가 못 채운 것」과 갈라 표시한다.
INTENTIONAL_UNRESOLVED = {
    "UNRESOLVED_FACT:merchant.forbidden": "업종 미확인 사례가 의도적으로 만든 것",
}

#: `outcome` → 회계 담당자의 검토 결정. `fix`는 **룰이** 보완요청한 건이라 여기 없다
#  (사람이 결정한 게 아니다). `review_*`는 사람이 검토에서 내린 결정이다.
REVIEW_DECISION = {
    "approve": "APPROVE", "reject": "REJECT",
    "review_return": "RETURN", "review_reject": "REJECT", "review_fix": "RETURN",
}

#: 사례가 아닌 건의 기본 사유. 사례 건은 `Spend.reason`이 이걸 덮는다.
DEFAULT_REVIEW_REASON = {
    "APPROVE": "소명 확인 완료 — 승인합니다.",
    "RETURN": "판단에 필요한 자료가 부족합니다 — 보완 후 재제출해 주십시오.",
    "REJECT": "업무 관련성을 소명하지 못해 최종 반려합니다.",
}


class Command(BaseCommand):
    help = "시연용 적용 완료 상태: 직전 3개월 정산이 실제로 흘러간 회사"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="지울 건수만 출력하고 멈춘다")
        parser.add_argument(
            "--live-risk-review", action="store_true",
            help="검토로 간 건에 Risk Review Agent를 실제로 호출한다(느리고 토큰을 쓴다)",
        )

    # ════════════════════════════════════════════════════════════════════
    def handle(self, *args, **options):
        if options["dry_run"]:
            call_command("seed_clean", "--dry-run")
            self.stdout.write(self.style.WARNING(
                "\n(seed_adopted는 위 목록을 지운 뒤 직전 "
                f"{MONTHS_BACK}개월치 정산을 새로 만든다)"
            ))
            return

        self.verbosity = int(options.get("verbosity", 1))
        self.rng = random.Random(SEED)
        self.today = timezone.localdate()
        self.months = self._months()

        #  ① 조직·카드·기준코드는 초기 시드가 만든다 — 두 시드가 사람·카드를 각자 만들면
        #     로그인 계정이 갈라진다. 여기서는 **그 위에 3개월을 얹기만** 한다.
        call_command("seed_clean", verbosity=0)
        teams = {t.name: t for t in Team.objects.all()}
        self._extra_members(teams)
        self._merchant_cache()

        #  ② 규정 별표를 **판정보다 먼저** 적재한다. 늦게 부르면 `policy.*`가 미해소라
        #     전건이 REVIEW로 강등된다(seed.py에서 실측된 순서 의존성).
        upsert_policy_tables()
        #  ③ 과목별 룰. GLOBAL scope가 겹쳐 DEFAULT GATE는 ARCHIVED로 물러난다(모듈 docstring).
        call_command("seed_rules", verbosity=self.verbosity)

        spends = self._plan(teams)

        #  ④ 판정을 실제로 태운다. Risk Review Agent 호출만 끈다 — 수백 건을 한 번에
        #     돌리는 경로라 켜 두면 시연 준비가 수십 분이 되고 토큰도 그만큼 든다.
        previous = risk_review_module.AUTO_SCHEDULE
        risk_review_module.AUTO_SCHEDULE = bool(options["live_risk_review"])
        try:
            mismatched = self._run_pipeline(spends)
        finally:
            risk_review_module.AUTO_SCHEDULE = previous

        self._budgets(teams)
        #  ⑤ 규정 문서 — **시드가 만들 수 없는 것**이라 얼려 둔 실제 적재 결과를 얹는다.
        #     파싱·청킹·임베딩·조항 분류·별표 추출이 다 돌아야 생기고 그중 둘은 LLM 호출이다.
        #     손으로 적으면 `chunk_ids`가 실제 청크를 안 가리켜 근거 링크가 끊긴다.
        #     덤프가 없으면 조용히 넘어간다(문서 없이도 나머지 화면은 다 산다).
        call_command("load_policy_docs", quiet_missing=True, verbosity=self.verbosity)
        self._prune_notifications()
        self._report(mismatched)

    # ── 기간 ─────────────────────────────────────────────────────────────
    def _months(self) -> list[tuple[int, int]]:
        """이번 달부터 거꾸로 `MONTHS_BACK`개월. 실행 시점을 따라가므로 시드가 늙지 않는다."""
        out = []
        year, month = self.today.year, self.today.month
        for _ in range(MONTHS_BACK):
            out.append((year, month))
            year, month = (year - 1, 12) if month == 1 else (year, month - 1)
        return list(reversed(out))

    def _last_day(self, year: int, month: int) -> int:
        """그 달에 지출이 있을 수 있는 마지막 날 — **이번 달은 오늘까지**(미래 결제 금지)."""
        if (year, month) == (self.today.year, self.today.month):
            return max(1, self.today.day - 1)
        return calendar.monthrange(year, month)[1]

    # ── 사람·카드 ────────────────────────────────────────────────────────
    def _extra_members(self, teams: dict[str, Team]) -> None:
        """팀당 4~5명이 되도록 팀원을 붙인다.

        `seed_clean`의 5명만으로는 팀 통계가 사람 한둘로 채워져 "누가 얼마나 썼나" 화면이
        의미를 잃는다. **직책을 흩어 놓는 게 중요하다** — 전원 비직책자면 별표1(직책별
        사전승인 기준)이 한 행으로만 해소돼 직책별로 판정이 갈리는지 확인할 수 없다.

        **팀당 팀장은 한 명이다.** 예전엔 영업팀에 `lead`(역할 팀장)와 박민수(직책 팀장)가
        같이 있어서, `_team_lead()`가 둘 중 하나를 집을 때마다 처리자가 달라졌다.

        **직책이 팀장이면 팀 취합 권한을 개별 부여한다**(`extra_capabilities`). 역할은
        `EMPLOYEE`인데 직책만 팀장인 사람이 실재하고(이영희), 그 사람이 팀 제출을 하는 것이
        조직 현실이다. 이걸 안 주면 화면 이력엔 "이영희가 제출했다"고 남는데 정작 이영희로
        로그인하면 그 화면에 못 들어간다 — **이력과 인가가 서로 다른 말을 한다.**
        역할 기본값을 넓히지 않는 이유: 그러면 전 직원이 팀 취합 권한을 갖는다.
        """
        pos = {p.name: p for p in Position.objects.all()}
        title = {j.name: j for j in JobTitle.objects.all()}
        NONE = title["비직책자(공용카드)"]
        roster = [
            #  영업팀 팀장은 `lead`(seed_clean이 만든다) — 여기서 또 만들지 않는다.
            ("박민수", "영업팀", "차장", None), ("정하늘", "영업팀", "주임", None),
            ("이도윤", "영업팀", "대리", None), ("서지훈", "영업팀", "사원", None),
            ("이영희", "AI·개발팀", "과장", "팀장"), ("최지우", "AI·개발팀", "대리", None),
            ("김철수", "AI·개발팀", "사원", None), ("한도현", "AI·개발팀", "부장", "부서장"),
            ("오세진", "재무회계팀", "대리", None), ("한지민", "재무회계팀", "사원", None),
        ]
        for index, (name, team_name, grade, job) in enumerate(roster):
            user = User.objects.create_user(
                f"emp{index + 1}", password="pass1234", role=Role.EMPLOYEE,
                team=teams[team_name], first_name=name,
                position=pos[grade], job_title=title[job] if job else NONE,
                #  직책 팀장은 팀 취합을 한다 — 역할이 아니라 **개인 부여**로 준다(위 docstring).
                extra_capabilities=[Capability.TEAM_AGGREGATE.value] if job == "팀장" else [],
            )
            Card.objects.create(
                card_type=CardType.PERSONAL, name=f"{name} 개인카드",
                number_masked=f"**** {2101 + index}", owner=user, team=user.team,
                limit_amount=3_000_000 if job else 1_500_000,
            )

    def _merchant_cache(self) -> None:
        """가맹점 업종 캐시 — `merchant.industry_confidence`가 `None`으로 남지 않게.

        지금 ACTIVE 그래프 중 이 값을 보는 건 없지만, 캐시가 비어 있으면 화면의 업종
        표시가 「미확인」으로 뜬다(적용 완료 회사가 3개월째 그러면 이상하다).
        `resolve()`를 거치므로 저장값은 정본 어휘로 접힌다.
        """
        for rows in MERCHANTS.values():
            for merchant, industry, _ in rows:
                code, label = industry_vocab.resolve(industry)
                MerchantCategory.objects.get_or_create(
                    normalized_name=merchant,
                    defaults=dict(industry_code=code, industry_label=label,
                                  source=MerchantSource.KAKAO, confidence=0.95),
                )

    # ════════════════════════════════════════════════════════════════════
    #  지출 계획 — 사실만 정한다
    # ════════════════════════════════════════════════════════════════════
    def _plan(self, teams: dict[str, Team]) -> list[Spend]:
        """월별 지출 목록. **끝난 달과 이번 달의 모양이 다르다.**

        6·7월은 전부 종결돼 있어야 한다(그게 "지난달"의 뜻이다). 이번 달만 진행 중인 건이
        섞인다 — 팀 취합 대기·승인 대기·검토 중. 지난달에 미결이 남아 있으면 화면이
        "3개월째 밀린 회사"가 되는데, 이 시드가 보여주려는 건 그 반대다.
        """
        from .ensure_service_account import SERVICE_USERNAME

        members = defaultdict(list)
        spenders = (User.objects
                    .filter(is_superuser=False, role=Role.EMPLOYEE)
                    .exclude(username=SERVICE_USERNAME)   # ai 서비스 계정은 사람이 아니다
                    .select_related("team"))
        for user in spenders:
            if user.team_id:
                members[user.team.name].append(user)
        # 팀장·회계도 지출한다(회계팀도 지출 주체라는 걸 화면에서 보여야 한다).
        for user in User.objects.filter(username__in=["lead", "acc", "acclead"]).select_related("team"):
            members[user.team.name].append(user)

        cards = self._cards_by_team()
        spends: list[Spend] = []
        for index, (year, month) in enumerate(self.months):
            current = (year, month) == (self.today.year, self.today.month)
            spends.extend(self._plan_month(year, month, members, cards, current, index))
        self.expected_cases = Counter(row.case_pattern for row in spends if row.case_pattern)
        return spends

    def _cards_by_team(self) -> dict[str, dict[str, Card]]:
        out: dict[str, dict[str, Card]] = defaultdict(dict)
        for card in Card.objects.select_related("team", "owner"):
            if card.card_type == CardType.PERSONAL and card.owner_id:
                out[card.owner.username]["personal"] = card
            elif card.team_id:
                out[card.team.name][card.card_type.lower()] = card
            elif card.card_type == CardType.POST_PAID:
                out["*"]["post_paid"] = card
        return out

    def _plan_month(self, year, month, members, cards, current: bool, index: int = 0) -> list[Spend]:
        last_day = self._last_day(year, month)
        rows: list[Spend] = []

        def day() -> int:
            return self.rng.randint(1, last_day)

        def pick(team_name: str) -> User:
            return self.rng.choice(members[team_name])

        def card_for(user: User, category: str) -> Card:
            """카드 귀속은 판정 사실이 된다 — 성격에 맞는 카드를 고른다.

            팀 성격 지출(회식·팀 다과·팀 비품)은 팀카드, 출장은 후정산, 나머지는 개인카드.
            """
            team_cards = cards.get(user.team.name, {})
            if category == C.GATHERING and "team" in team_cards:
                return team_cards["team"]
            if category == C.TRIP and self.rng.random() < 0.45:
                return cards["*"]["post_paid"]
            return cards.get(user.username, {}).get("personal") or team_cards.get("team")

        def spend(team_name: str, category: str, **over) -> Spend:
            user = over.pop("owner", None) or pick(team_name)
            merchant, industry, item_type = self.rng.choice(MERCHANTS[category])
            #  사례는 가맹점·업종을 지정한다 — 업종을 못 접는 상황(`industry=""`)이
            #  게이트 화이트리스트를 못 넘는 REVIEW 경로라, 사전에 있는 가맹점으로는
            #  만들 수 없다. `""`도 유효한 값이라 `or`가 아니라 기본값으로 받는다.
            merchant = over.pop("merchant", None) or merchant
            industry = over.pop("industry", industry)
            item_type = over.pop("item_type", None) or item_type
            low, high = AMOUNTS[category]
            amount = over.pop("amount", None) or self.rng.randrange(low, high, 500)
            card = over.pop("card", None) or card_for(user, category)
            #  목적도 마찬가지 — **빈 목적이 곧 판정 사실**이다(`expense_purpose_missing`).
            purpose = over.pop("purpose", None)
            if purpose is None:
                purpose = self.rng.choice(PURPOSES[category])
            row = Spend(
                owner=user, merchant=merchant, industry=industry, category=category,
                item_type=item_type, amount=amount, card=card,
                year=year, month=month,
                day=over.pop("day", None) or day(), hour=over.pop("hour", None) or self.rng.randint(9, 19),
                purpose=purpose,
                **over,
            )
            self._fill_category_facts(row)
            return row

        # ── ① 평범한 지출 — 이게 대부분이다 ──────────────────────────
        #  적용이 끝난 회사의 정상 분포는 "거의 다 자동 통과"다. 검토 큐가 매달 절반씩
        #  쌓이면 그건 적용 완료가 아니라 도입 실패다.
        #  **자동 통과 건은 사례를 늘린 만큼 같이 늘어나야 한다.** 사례 30건은 전부
        #  검토를 거치므로, 분모를 그대로 두면 자동처리율이 89%에서 82%로 내려앉는다 —
        #  화면은 그대로인데 지표만 나빠져 "도입이 후퇴한 회사"로 읽힌다.
        plan = [
            ("영업팀", C.MEAL, 9), ("영업팀", C.MEETING, 6), ("영업팀", C.TRIP, 7),
            ("영업팀", C.OTHER, 5), ("영업팀", C.ENTERTAIN, 3), ("영업팀", C.GATHERING, 2),
            ("AI·개발팀", C.MEAL, 8), ("AI·개발팀", C.MEETING, 6), ("AI·개발팀", C.OTHER, 6),
            ("AI·개발팀", C.TRIP, 3), ("AI·개발팀", C.GATHERING, 2),
            ("재무회계팀", C.MEAL, 6), ("재무회계팀", C.MEETING, 5), ("재무회계팀", C.OTHER, 5),
            ("재무회계팀", C.TRIP, 3), ("재무회계팀", C.OTHER, 3),
        ]
        for team_name, category, count in plan:
            for _ in range(count):
                rows.append(spend(team_name, category))

        # ── ② 검토를 거쳐 승인된 건 ────────────────────────────────
        #  금액은 달마다 흔든다 — 세 달이 같은 숫자면 "복사한 데이터"로 읽힌다.
        #
        #  **여기 있던 두 건은 기대값이 낡아 있었다**(2026-08-26 실측). 회식 1인당 한도
        #  초과는 M-01이 `RETURN`을 내고(검토가 아니라 보완요청이다), 심야·주말은 게이트
        #  v7에 그런 룰이 아예 없어 `PASS`로 빠졌다. 「검토를 거쳐 승인」이라는 서사가
        #  실제로는 두 달 내내 성립하지 않았고, 시드는 매번 경고를 냈지만 그 경고가
        #  **12줄에서 잘려** 보이지 않았다. 사실을 실제 REVIEW 경로로 바꿔 붙인다.
        #
        #  1인당 한도 초과(M-01) — 룰이 보완요청을 내는 건이라 「고쳐서 다시 올린」 결말이다.
        rows.append(spend("영업팀", C.GATHERING,
                          amount=self.rng.randrange(560_000, 760_000, 5_000), headcount=8,
                          expect="RETURN", outcome="fix",
                          purpose="분기 마감 팀 회식"))
        #  청탁금지법 대상자 참석(E-003) — 법률 리스크라 룰이 자동 처리하지 않는다.
        rows.append(spend("영업팀", C.ENTERTAIN,
                          amount=self.rng.randrange(190_000, 265_000, 1_000),
                          headcount=4, external_headcount=2, kickback_target=True, pre_approved=True,
                          expect="REVIEW", outcome="approve",
                          purpose="공공기관 담당자 포함 사업 협의",
                          anomaly=round(self.rng.uniform(0.66, 0.78), 2),
                          anomaly_reasons=["청탁금지법 대상자 참석", "1인당 법정 한도 초과"]))
        #  주말 심야 근무 식대 — 게이트에 시각 룰이 없어 자동 통과한다. **그게 정상이다**
        #  (심야라는 사실만으로 사람을 부르지 않는다). 서사만 남기고 판정은 엔진에 맡긴다.
        weekend = self._weekend_day(year, month, last_day)
        if weekend:
            rows.append(spend("AI·개발팀", C.MEAL,
                              amount=self.rng.randrange(62_000, 96_000, 1_000),
                              day=weekend, hour=23,
                              purpose="장애 대응 주말 야간 근무 식대"))

        # ── ③ 보완요청 후 고쳐서 다시 올라온 건 ─────────────────────
        #  적격증빙 누락(E-001). 지출자가 영수증을 첨부해 재제출하면 통과한다.
        rows.append(spend("영업팀", C.ENTERTAIN,
                          amount=self.rng.randrange(140_000, 230_000, 1_000),
                          headcount=3, external_headcount=1, receipt=False, pre_approved=True,
                          expect="RETURN", outcome="fix",
                          purpose="거래처 담당자 상담"))
        #  공용·팀 카드 실사용자 미기재(R-004). 실사용자를 채워 넣으면 자동 재판정된다.
        rows.append(spend("AI·개발팀", C.GATHERING,
                          amount=self.rng.randrange(240_000, 380_000, 5_000),
                          card=cards["AI·개발팀"].get("team"), actual_user_recorded=False,
                          expect="RETURN", outcome="fix",
                          purpose="스프린트 마감 팀 회식"))

        # ── ④ 이번 달에만 있는 것들 ────────────────────────────────
        if current:
            #  최종반려 — 드물지만 있어야 한다. 없으면 "반려가 가능한 시스템"인지 안 보인다.
            rows.append(spend("영업팀", C.ENTERTAIN, amount=265_000, headcount=2,
                              external_headcount=1, kickback_target=True, pre_approved=True,
                              expect="REVIEW", outcome="reject",
                              purpose="업무 관련성 확인 필요", anomaly=0.89,
                              anomaly_reasons=["청탁금지법 대상자 참석", "업무 관련성 불명확"]))
            #  진행 중 — 화면이 살아 있으려면 "지금 처리할 것"이 있어야 한다.
            for _ in range(4):
                rows.append(spend("영업팀", self.rng.choice([C.MEAL, C.MEETING, C.OTHER]),
                                  outcome="inflight_team", day=self.rng.randint(max(1, last_day - 6), last_day)))
            for _ in range(2):
                rows.append(spend("AI·개발팀", self.rng.choice([C.MEAL, C.OTHER]),
                                  outcome="inflight_team", day=self.rng.randint(max(1, last_day - 6), last_day)))
            for _ in range(3):
                rows.append(spend("재무회계팀", self.rng.choice([C.MEAL, C.MEETING, C.TRIP]),
                                  outcome="inflight_pending", day=self.rng.randint(max(1, last_day - 8), last_day)))
            #  검토 대기 — 회계 담당자의 오늘 할 일. 검토 워크스페이스가 한두 건이면
            #  정렬·필터·일괄 흐름을 시연할 수 없어 성격이 다른 4건을 남긴다.
            def recent() -> int:
                return self.rng.randint(max(1, last_day - 5), last_day)

            #  **검토 큐에 남길 건은 실제로 REVIEW가 나오는 사실이어야 한다.** 회식 1인당
            #  초과·심야는 각각 RETURN·PASS라 여기 두면 큐가 빈다(실측 2026-08-26).
            rows.append(spend("AI·개발팀", C.MEAL, amount=138_000, industry="",
                              merchant="위드플레이트 판교",
                              expect="REVIEW", outcome="inflight_review", day=recent(),
                              purpose="런칭 대응 야간 근무 식대", anomaly=0.52,
                              anomaly_reasons=["가맹점 업종 미확인"]))
            rows.append(spend("영업팀", C.ENTERTAIN, amount=272_000, headcount=4,
                              external_headcount=2, kickback_target=True, pre_approved=True,
                              expect="REVIEW", outcome="inflight_review", day=recent(),
                              purpose="신규 거래처 임원 상담", anomaly=0.74,
                              anomaly_reasons=["청탁금지법 대상자 참석", "고액 접대"]))
            rows.append(spend("재무회계팀", C.MEETING, amount=86_000,
                              expect="REVIEW", outcome="inflight_review", day=recent(),
                              purpose="", anomaly=0.44,
                              anomaly_reasons=["지출 목적 미기재"]))
            night = self._weekend_day(year, month, last_day)
            if night:
                rows.append(spend("영업팀", C.OTHER, amount=164_000, day=night,
                                  merchant="글로벌테크몰", industry="",
                                  expect="REVIEW", outcome="inflight_review",
                                  purpose="주말 마감 대응 장비 구매", anomaly=0.58,
                                  anomaly_reasons=["가맹점 업종 미확인"]))
            #  아직 개인이 들고 있는 건.
            for _ in range(3):
                rows.append(spend("영업팀", self.rng.choice([C.MEAL, C.TRIP]),
                                  outcome="inflight_draft", day=self.rng.randint(max(1, last_day - 3), last_day)))

        # ── ⑤ 결정 사례 — 사람이 기계와 다르게 판단한 건 ────────────
        rows.extend(self._plan_cases(index, spend, year, month, last_day))
        return rows

    def _plan_cases(self, index: int, spend, year: int, month: int, last_day: int) -> list[Spend]:
        """이 달에 해당하는 `CASES`를 사실로 펼친다.

        조리법이 정하는 건 **엔진이 REVIEW를 내게 하는 사실**뿐이고, 사례를 가르는 건
        `ai_recommends`(기계의 결론)와 `outcome`(사람의 결론)의 차이다. 둘이 같으면
        `decision_cases.record()`가 사례를 만들지 않는다 — 그래서 여기서 어긋나게 둔다.
        """
        rows: list[Spend] = []
        for case in CASES:
            if case["month"] != index:
                continue
            recipe = dict(CASE_RECIPES[case["recipe"]])
            #  사례가 조리법을 덮어쓸 수 있다(가맹점·과목·금액대). 사실의 종류가 아니라
            #  **판단의 종류**로 패턴을 가르므로, 같은 조리법이 여러 과목으로 나온다.
            recipe.update({k: v for k, v in case.items()
                           if k not in ("pattern", "recipe", "month", "ai", "outcome",
                                        "reason", "fix_purpose", "fix_industry")})
            team = recipe.pop("team")
            low, high = recipe.pop("amount")
            anomaly_low, anomaly_high = recipe.pop("anomaly")
            rows.append(spend(
                team, recipe.pop("category"),
                amount=self.rng.randrange(low, high, 1_000),
                expect="REVIEW", outcome=case["outcome"],
                anomaly=round(self.rng.uniform(anomaly_low, anomaly_high), 2),
                ai_recommends=case["ai"], reason=case["reason"], case_pattern=case["pattern"],
                fix_purpose=case.get("fix_purpose", ""),
                fix_industry=case.get("fix_industry", ""),
                **recipe,
            ))
        return rows

    def _weekend_day(self, year: int, month: int, last_day: int) -> int | None:
        days = [d for d in range(1, last_day + 1)
                if calendar.weekday(year, month, d) >= 5]
        return self.rng.choice(days) if days else None

    def _fill_category_facts(self, row: Spend) -> None:
        """룰이 참조하는 사실을 과목에 맞게 채운다 — **비우면 「모름」이 된다.**

        미해소 가드가 `None`을 보면 판정을 REVIEW로 강등하므로, 적용이 끝난 회사라면
        당연히 채워져 있을 값들을 채운다. 반대로 **그 과목에서 묻지 않는 항목은 그대로
        `None`으로 둔다** — 0으로 채우면 "0명이 참석했다"는 다른 사실이 된다.
        """
        shared = row.card is not None and row.card.card_type in (CardType.SHARED, CardType.TEAM)
        if shared and row.actual_user_recorded is None:
            #  적용이 끝난 회사는 공용·팀 카드에 실사용자를 적는다(그러지 않으면 R-004에 걸린다).
            #  아직 개인이 들고 있는 건(DRAFT)만 안 적힌 채로 둔다 — 실제로 그 시점엔 없다.
            row.actual_user_recorded = row.outcome != "inflight_draft"

        if row.category in (C.GATHERING, C.ENTERTAIN):
            if row.headcount is None:
                #  **1인당 금액이 곧 판정 축이다**(회식 M-001 한도 5만원 · 접대 청탁금지 3만원).
                #  인원을 금액과 무관하게 뽑으면 평범한 회식이 무작위로 한도 초과가 된다 —
                #  1인당 3~4만원대가 되도록 금액에서 역산한다.
                per_person = self.rng.randrange(28_000, 42_000, 1_000)
                row.headcount = max(3, min(14, round(row.amount / per_person)))
            if row.category == C.ENTERTAIN and row.external_headcount is None:
                row.external_headcount = self.rng.randint(1, 2)
            if row.category == C.ENTERTAIN and row.verified_headcount is None:
                #  **접대비는 참석자 명단이 있는 게 정상이다.** 규정이 그걸 요구하고
                #  (제12조③·청탁금지법 제8조) 룰이 확인값만 보기 때문에, 명단이 없으면
                #  전건이 「판정 정보 부족」으로 강등된다. 신고값과 같은 수로 둔다 —
                #  둘이 어긋나는 시나리오는 아래 ④에서 따로 만든다.
                row.verified_headcount = row.headcount
            if row.category == C.GATHERING:
                row.external_headcount = 0
                if row.verified_headcount is None:
                    #  **회식도 참석자 명단이 있는 게 정상이다.** 1인당 한도 룰(M-01)이
                    #  신고값이 아니라 **확인값**을 본다 — 본인이 적은 인원으로 나누면
                    #  인원을 부풀리는 것만으로 한도를 피할 수 있어서다(접대 E-03과 같은 이유).
                    #  명단이 없으면 전건이 「판정 정보 부족」으로 강등된다.
                    row.verified_headcount = row.headcount
                if row.is_secondary_venue is None:
                    row.is_secondary_venue = False
                if row.includes_alcohol is None:
                    row.includes_alcohol = True
            if row.kickback_target is None:
                row.kickback_target = False
        if row.pre_approved is None:
            #  별표1의 **가장 좁은** 기준(비직책자 30만원)을 넘으면 사전승인을 받아 둔다.
            #  `None`으로 두면 안 된다 — 접대 그래프 E-002가 이 경로를 참조하므로 모름이면
            #  미해소 가드가 접대 건 전체를 REVIEW로 강등한다(모름 ≠ 아니오).
            row.pre_approved = row.amount > 300_000

    # ════════════════════════════════════════════════════════════════════
    #  실행 — 실제 상태 전이를 태운다
    # ════════════════════════════════════════════════════════════════════
    def _run_pipeline(self, spends: list[Spend]) -> list[tuple[Spend, str]]:
        actors = {u.username: u for u in User.objects.filter(username__in=["lead", "acc", "acclead"])}
        accountant = actors.get("acc")
        mismatched: list[tuple[Spend, str]] = []

        golden: list[dict] = []
        for row in spends:
            settlement = self._create(row)
            #  **골든 라벨을 남긴다.** `outcome`은 시드가 정한 「사람이 무엇을 했는가」이고
            #  룰과 독립이다 — 룰 버전을 바꿔 가며 채점하려면 이 라벨이 필요하다.
            #  최종 상태로는 대신할 수 없다: `fix`(보완 후 재제출) 건도 결국 CONFIRMED로
            #  끝나므로, 상태만 보면 「룰이 잡았어야 할 건」이 승인 건으로 둔갑한다.
            golden.append({
                "settlementId": settlement.id, "category": row.category,
                "outcome": row.outcome, "expect": row.expect,
                "label": ("보완반려" if row.outcome in ("fix", "reject") else
                          "미결" if row.outcome.startswith("inflight") else "승인"),
            })
            #  **판정 전에 붙여야 한다.** 첨부에서 나온 사실이 EvalContext에 실리려면
            #  `judge()`보다 먼저 존재해야 한다 — 뒤에 붙이면 이미 끝난 판정에 안 들어간다.
            self._attach_participant_list(settlement, row, settlement.transaction.ts)
            base = timezone.localtime(settlement.transaction.ts)
            marker = self._latest_event_id(settlement)

            if row.outcome == "inflight_draft":
                self._stamp(settlement, base + timedelta(minutes=10))
                continue

            lead = self._team_lead(row.owner) or actors.get("lead")
            settlement_services.raise_to_team(settlement, row.owner)
            marker = self._stamp_events(settlement, marker, base + timedelta(days=1, hours=9))
            if row.outcome == "inflight_team":
                self._stamp(settlement, base + timedelta(minutes=10))
                continue

            submitted_at = base + timedelta(days=2, hours=10)
            settlement_services.submit(settlement, lead)
            result = settlement_services.judge(settlement, accountant, reuse_recorded=True)
            marker = self._stamp_events(settlement, marker, submitted_at)
            if result.decision != row.expect:
                mismatched.append((row, result.decision))

            if settlement.status == S.RETURNED:
                #  보완 — 사실을 고쳐서 다시 올린다. 재제출은 **판정을 다시 돌린다**
                #  (사실이 바뀌었으므로 옛 판정을 재사용하면 안 된다).
                self._remediate(settlement, row)
                fixed_at = submitted_at + timedelta(days=1, hours=1)
                settlement_services.submit(settlement, row.owner)
                settlement_services.judge(settlement, accountant)
                marker = self._stamp_events(settlement, marker, fixed_at)
                submitted_at = fixed_at

            if settlement.status == S.IN_REVIEW:
                self._write_risk_review(settlement, row)
                if row.outcome == "inflight_review":
                    self._stamp(settlement, base + timedelta(minutes=10), judged_at=submitted_at)
                    continue
                minutes = self.rng.randint(4, 46)   # 평균 검토시간 지표의 근거가 된다
                decision = REVIEW_DECISION.get(row.outcome, "APPROVE")
                reason = row.reason or DEFAULT_REVIEW_REASON[decision]
                settlement_services.review(settlement, decision, accountant, reason)
                reviewed_at = submitted_at + timedelta(minutes=minutes)
                marker = self._stamp_events(settlement, marker, reviewed_at)

                #  검토에서 보완요청이 나온 건은 **끝난 달이면 닫는다.** 지난달에 보완요청이
                #  났으면 지금쯤 처리됐을 것이고, 안 닫으면 "3개월째 밀린 회사"가 된다
                #  (이 시드가 보여주려는 것의 정반대다). 이번 달 것만 열어 둬 회계 화면에
                #  「지금 기다리는 일」로 남긴다.
                past_month = (row.year, row.month) != (self.today.year, self.today.month)
                if settlement.status == S.RETURNED and (row.outcome == "review_fix" or past_month):
                    self._remediate(settlement, row)
                    refixed_at = reviewed_at + timedelta(days=1, hours=2)
                    settlement_services.submit(settlement, row.owner)
                    settlement_services.judge(settlement, accountant)
                    marker = self._stamp_events(settlement, marker, refixed_at)
                    submitted_at = refixed_at
                    if settlement.status == S.IN_REVIEW:
                        #  보완이 됐어도 사실이 그대로면(예: 청탁금지법 대상자 참석) 다시
                        #  검토로 온다. 이번엔 **AI도 승인 권고**라 사례가 남지 않는다 —
                        #  같은 건으로 사례가 두 번 쌓이면 코퍼스가 한 사건에 쏠린다.
                        self._write_risk_review(settlement, row, recommends="APPROVE")
                        settlement_services.review(
                            settlement, "APPROVE", accountant,
                            "보완 자료를 확인했습니다 — 승인합니다.")
                        marker = self._stamp_events(
                            settlement, marker, refixed_at + timedelta(minutes=self.rng.randint(4, 30)))

            if settlement.status == S.PENDING_CONFIRM:
                if row.outcome == "inflight_pending":
                    self._stamp(settlement, base + timedelta(minutes=10), judged_at=submitted_at)
                    continue
                settlement_services.confirm(settlement, accountant)
                marker = self._stamp_events(settlement, marker, submitted_at + timedelta(days=1, hours=5))

            self._stamp(settlement, base + timedelta(minutes=10), judged_at=submitted_at)

        self._write_golden(golden)
        return mismatched

    def _write_golden(self, rows: list[dict]) -> None:
        """골든 라벨을 파일로 남긴다 — `rule_eval`이 이걸로 룰 버전을 채점한다.

        DB 컬럼을 만들지 않는 이유: 이건 **시연 데이터의 정답지**이지 도메인 사실이 아니다.
        운영 스키마에 넣으면 판정이 정답지를 참조할 수 있게 되고, 그 순간 채점이 의미를 잃는다.
        """
        path = Path(settings.BASE_DIR) / "var" / "adopted_golden.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        counts = Counter(r["label"] for r in rows)
        self.stdout.write(
            f"  골든 라벨 {len(rows)}건 → {path.name} "
            f"(승인 {counts['승인']} · 보완반려 {counts['보완반려']} · 미결 {counts['미결']})"
        )

    def _team_lead(self, user: User) -> User | None:
        """같은 팀의 팀 취합 담당자.

        **직책만 보지 않고 권한도 확인한다.** 직책이 팀장이어도 `team_aggregate`가 없으면
        화면에서 그 일을 할 수 없는 사람이라, 이력에 처리자로 남기면 인가와 어긋난다.
        지금은 직책 팀장에게 권한을 부여하므로 대개 같은 사람이지만, 둘이 갈릴 때는
        **권한 쪽을 따른다** — 이력은 "실제로 할 수 있는 사람"이 한 것으로 남아야 한다.
        """
        candidates = (User.objects.filter(team_id=user.team_id, job_title__name="팀장")
                      .exclude(pk=user.pk))
        for candidate in candidates:
            if candidate.has_capability(Capability.TEAM_AGGREGATE):
                return candidate
        return None

    def _create(self, row: Spend) -> Settlement:
        year, month = row.year, row.month
        ts = timezone.make_aware(
            dt.datetime(year, month, row.day, row.hour,
                        row.minute or self.rng.choice([0, 15, 30, 45]))
        )
        tx = Transaction.objects.create(card=row.card, merchant=row.merchant, amount=row.amount, ts=ts)
        if row.receipt:
            Receipt.objects.create(matched_tx=tx, status=Receipt.Status.MATCHED,
                                   file_ref=f"receipts/{tx.id}.jpg")
        code, label = industry_vocab.resolve(row.industry)
        recorded = row.actual_user_recorded
        return Settlement.objects.create(
            transaction=tx, category=row.category, ai_category=row.category, ai_suggested=False,
            merchant_industry=label, merchant_industry_code=code,
            purpose=row.purpose, status=S.DRAFT,
            submitted_by=row.owner, team=row.owner.team, item_type=row.item_type,
            headcount=row.headcount, external_headcount=row.external_headcount,
            pre_approved=row.pre_approved, kickback_target=row.kickback_target,
            is_secondary_venue=row.is_secondary_venue, includes_alcohol=row.includes_alcohol,
            actual_user_recorded=recorded,
            actual_user=row.owner if recorded else None,
        )

    # ── 참석자 명단 첨부 ─────────────────────────────────────────────────
    #
    #  **접대비 판정은 「문서로 확인된 인원」을 요구한다**(`seed_rules` E-003). 명단이 없으면
    #  `tx.verified_per_person_amount`가 null이라 미해소 가드가 판정을 REVIEW로 강등한다 —
    #  룰이 의도한 동작이다. 그런데 시드가 그 문서를 안 만들어서 **접대 건이 전건 강등**되고
    #  있었다(2026-08-24, `test_seed_adopted`가 실패로 잡았다).
    #
    #  판독 결과를 손으로 쓰는 건 `RiskReview`와 같은 이유다 — 비전 판독을 시연 준비마다
    #  수십 번 부를 수 없다. **모양은 실제 판독기와 같게** 맞춘다(`vision/document.py`가
    #  내는 dot-path·신뢰도 형식 그대로) — 다르면 조립기가 못 읽는다.
    PARTICIPANT_CONFIDENCE = 0.92

    def _attach_participant_list(self, settlement: Settlement, row: Spend, when,
                                 verified: int | None = None) -> None:
        """확인 인원이 정해진 건에 참석자 명단 첨부를 만든다.

        `verified`를 넘기면 그 값으로 다시 만든다 — 보완(`_remediate`)에서 명단을
        고쳐 올리는 경우다.
        """
        verified = verified if verified is not None else row.verified_headcount
        if not verified:
            return
        settlement.attachments.filter(kind=AttachmentKind.PARTICIPANT_LIST).delete()
        extracted = {"participants.verified_participant_count": verified}
        if row.external_headcount is not None:
            extracted["participants.verified_external_count"] = row.external_headcount
        if row.kickback_target is not None:
            extracted["participants.has_kickback_law_target"] = row.kickback_target

        attachment = Attachment.objects.create(
            settlement=settlement,
            kind=AttachmentKind.PARTICIPANT_LIST,
            original_name=f"참석자명단_{settlement.pk}.pdf",
            file_ref=f"attachments/seed/{settlement.pk}.pdf",
            extraction_status=ExtractionStatus.DONE,
            extracted=extracted,
            field_confidence={path: self.PARTICIPANT_CONFIDENCE for path in extracted},
            extractor_version="seed",
            uploaded_by=row.owner,
        )
        #  `extracted_at`은 조립기가 문서끼리 충돌할 때 순서를 보는 값이고, `uploaded_at`은
        #  `auto_now_add`라 무엇을 해도 "지금"이 박힌다 — 둘 다 결제일로 되돌린다
        #  (`_stamp_events`가 이력 시각에 대해 하는 것과 같은 이유).
        Attachment.objects.filter(pk=attachment.pk).update(extracted_at=when, uploaded_at=when)

    def _remediate(self, settlement: Settlement, row: Spend) -> None:
        """보완요청을 받은 건을 지출자가 고친다 — **사실을 실제로 바꾼다.**

        상태만 되돌리고 사실을 그대로 두면 재판정이 같은 사유로 또 걸린다(그게 정상이다).
        여기서 고치는 건 증빙 첨부·사전승인 기록처럼 화면에서 실제로 할 수 있는 보완이다.
        """
        tx = settlement.transaction
        if not tx.receipts.exclude(status=Receipt.Status.MISSING).exists():
            Receipt.objects.create(matched_tx=tx, status=Receipt.Status.MATCHED,
                                   file_ref=f"receipts/{tx.id}-fixed.jpg")
        if settlement.pre_approved is not True:
            settlement.pre_approved = True
        if settlement.actual_user_recorded is False:
            settlement.actual_user_recorded = True
            settlement.actual_user = settlement.submitted_by
        fields = ["pre_approved", "actual_user_recorded", "actual_user", "updated_at"]

        #  검토에서 보완요청이 나온 건은 **그 사유를 실제로 해소한다**. 목적을 안 채우면
        #  `expense_purpose_missing`이 그대로라 재판정이 또 게이트 화이트리스트에서 떨어지고,
        #  업종도 마찬가지다 — 화면에서 사람이 하는 보완을 그대로 흉내낸다.
        if row.fix_purpose and not settlement.purpose:
            settlement.purpose = row.fix_purpose
            fields.append("purpose")
        if row.fix_industry and not settlement.merchant_industry:
            code, label = industry_vocab.resolve(row.fix_industry)
            settlement.merchant_industry_code, settlement.merchant_industry = code, label
            fields += ["merchant_industry_code", "merchant_industry"]

        #  **1인당 한도 초과는 인원을 다시 세어 고친다.** 회식 M-01은 참석 인원으로 나눈
        #  값을 보므로, 명단을 빠뜨린 사람을 채워 넣으면 한도 아래로 내려간다 — 화면에서
        #  실제로 할 수 있는 보완이다. 이 보정이 없으면 재판정이 같은 사유로 또 걸려
        #  **지난달에 보완요청이 미결로 남는다**(실측 2026-08-25).
        flags = (settlement.rule_judgement or {}).get("flags") or []
        if "PER_PERSON_LIMIT_OVER" in flags:
            limit = 50_000
            amount = int(settlement.transaction.amount)
            needed = amount // limit + 1
            if (settlement.headcount or 0) < needed:
                settlement.headcount = needed
                fields.append("headcount")
            self._attach_participant_list(
                settlement, row, settlement.transaction.ts, verified=needed)

        settlement.save(update_fields=fields)

    def _write_risk_review(self, settlement: Settlement, row: Spend,
                           recommends: str = "") -> None:
        """검토로 넘어간 건의 이상탐지 결과 — **시연용 대역값이다.**

        진짜는 Risk Review Agent가 만든다(`risk_review.run`). 수백 건을 한 번에 돌리는
        시드에서 그걸 부르면 준비에 수십 분과 토큰이 든다. 대신 값이 비어 있으면 검토
        화면이 "왜 검토로 왔는지"를 못 보여주므로, 룰이 실제로 붙인 사유와 어긋나지 않는
        범위에서 채운다.
        """
        if row.anomaly <= 0:
            return
        #  **AI 권고와 사람의 결정은 별개 축이다.** 예전엔 권고를 결말에서 뽑아 써서
        #  둘이 항상 같았고, 그래서 185건을 돌려도 `DecisionCase`가 **0건**이었다
        #  (`decision_cases.record`는 다를 때만 남긴다). 사례 건은 `ai_recommends`가 채운다.
        recommendation = (recommends or row.ai_recommends
                          or ("REJECT" if row.outcome == "reject" else "APPROVE"))
        tier = self._risk_tier(row.anomaly)
        #  근거는 **판정이 실제로 붙인 사유**에서 만든다 — 시드가 조문을 지어내면 화면의
        #  인용문과 룰이 건 사유가 서로 다른 말을 한다.
        refs = [{"title": reason, "source": f"{settlement.category} 검증 그래프", "kind": "policy"}
                for reason in row.anomaly_reasons]
        RiskReview.objects.create(
            settlement=settlement,
            anomaly_score=row.anomaly,
            #  1차 등급·상태를 비워 두면 화면이 「측정 안 됨」/등급 없음으로 그린다
            #  (`stage1_status`가 빈 값이면 시리얼라이저가 `ok`로 폴백하지만 등급은 안 나온다).
            risk_tier=tier,
            stage1_status="ok",
            anomaly_reasons=row.anomaly_reasons,
            reasons=[{"feature": reason, "weight": round(row.anomaly / max(1, len(row.anomaly_reasons)), 2)}
                     for reason in row.anomaly_reasons],
            rag_refs=refs,
            ai_recommendation=recommendation,
            ai_confidence=round(min(0.95, 0.55 + row.anomaly / 3), 2),
            #  ②RAG 카드가 읽는 **구조화 보고서**. 없으면 「보고서가 없습니다」로 뜬다 —
            #  검토 화면이 시연의 핵심이라 빈 채로 둘 수 없다. Agent 산출물의 대역이다.
            report=self._demo_report(row, recommendation, settlement),
            tier_path="heavy" if tier == "HIGH" else "fast",
            model_name="seed",
            stage2_verdict={
                "violation_verdict": "VIOLATION" if recommendation != "APPROVE" else "NO_VIOLATION",
                "review_reasons": row.anomaly_reasons,
                "recommendation": recommendation,
                "citations": [], "similar_cases": [],
            },
        )

    @staticmethod
    def _risk_tier(score: float) -> str:
        """`risk_review_agent.RISK_TIER_*`와 **같은 경계**를 쓴다.

        시드 점수는 0~1 대역이고 실제 모델 점수는 0.05~0.07 근방이라 스케일이 다르다 —
        여기서는 시연용 대역값의 상대 크기로만 등급을 매긴다. 컷오프 실험이 끝나 상수가
        바뀌면 이 함수도 같이 본다(`.personal/FINDINGS.md`에 예정으로 등록돼 있다).
        """
        if score >= 0.7:
            return "HIGH"
        return "MEDIUM" if score >= 0.4 else "LOW"

    def _demo_report(self, row: Spend, recommendation: str, settlement) -> dict:
        """검토 화면이 그대로 그리는 보고서 — **시연용 대역이다.**

        Agent를 185번 부를 수 없어 손으로 쓰지만, **모양은 실제 산출물과 같게** 맞춘다
        (`risk_review_agent.RiskReport`). 화면은 모양이 어긋나도 죽지 않게 방어하지만
        (`RiskReportView.normalize`), 어긋난 채 두면 시연에서 절반만 보인다.
        """
        amount = int(settlement.transaction.amount)
        per_person = f" · 1인당 {amount // row.headcount:,}원" if row.headcount else ""
        head = row.anomaly_reasons[0] if row.anomaly_reasons else "이상 신호"
        return {
            "summary": (
                f"{head} 사유로 검토가 필요한 건입니다. "
                + {"REJECT": "규정 위반 소지가 있어 반려를 권장합니다.",
                   "RETURN": "판단에 필요한 자료가 없어 보완을 권장합니다."}.get(
                       recommendation, "소명이 확인되면 승인 가능합니다.")
            ),
            "recommendation": recommendation,
            "highlights": [
                f"{row.merchant} · {amount:,}원{per_person}",
                f"결제 {row.hour:02d}시 · {row.category}",
            ],
            "findings": [
                {"claim": reason,
                 "reasoning": f"{settlement.category} 검증 그래프가 이 사유로 검토를 요청했습니다.",
                 "evidence": []}
                for reason in (row.anomaly_reasons or ["이상 신호가 감지됐습니다."])
            ],
            "advisories": ["시연용 대역 보고서입니다 — 실제 검토는 Agent 산출물로 대체됩니다."],
        }

    # ── 시각 되돌리기 ────────────────────────────────────────────────────
    def _latest_event_id(self, settlement: Settlement) -> int:
        return settlement.events.order_by("-id").values_list("id", flat=True).first() or 0

    def _stamp_events(self, settlement: Settlement, since: int, when) -> int:
        """방금 만들어진 이력에 **결제일 기준 시각**을 박는다.

        `SettlementEvent.created_at`은 `auto_now_add`라 무엇을 해도 "지금"이 들어간다.
        지난달 건의 이력이 오늘로 찍히면 월별 통계와 검토 소요시간이 통째로 무너진다.
        `QuerySet.update()`는 `auto_now_add`를 우회하는 유일한 통로다.
        """
        ids = list(settlement.events.filter(id__gt=since).values_list("id", flat=True))
        if ids:
            SettlementEvent.objects.filter(id__in=ids).update(created_at=when)
        return max(ids) if ids else since

    def _stamp(self, settlement: Settlement, created_at, *, judged_at=None) -> None:
        """정산·판정로그·전표의 생성 시각도 같은 이유로 되돌린다."""
        Settlement.objects.filter(pk=settlement.pk).update(created_at=created_at, updated_at=created_at)
        if judged_at is not None:
            Settlement.objects.filter(pk=settlement.pk).update(rule_judged_at=judged_at)
            RuleHit.objects.filter(settlement=settlement).update(created_at=judged_at)
            ErpVoucher.objects.filter(settlement=settlement).update(created_at=judged_at + timedelta(days=1))
        RiskReview.objects.filter(settlement=settlement).update(created_at=judged_at or created_at)

    # ── 예산 ─────────────────────────────────────────────────────────────
    def _budgets(self, teams: dict[str, Team]) -> None:
        """월별 팀 예산 — **한도만** 넣고, 실제 사용액에서 역산한다.

        한도를 손으로 박으면 내역이 바뀔 때마다 대시보드가 어긋난다. 이번 달에 시드된
        사용액에서 목표 소진율로 역산하면 내역이 바뀌어도 비율이 유지된다(`seed`와 같은 방법).

        불변식 둘을 지킨다: ① 팀 총한도(`category=""`) = 과목 한도의 합
        ② **모든 과목** 행을 만든다 — 빠진 과목의 지출은 총액엔 잡히는데 항목 카드엔 안 보인다.
        """
        from domain.settlements.models import TeamBudget

        TeamBudget.objects.all().delete()
        BASE_RATE = 0.68            # 일반 과목 목표 소진율
        OVER_RATE = 1.12            # 초과 시연 과목: 한도 < 사용액
        MIN_LIMIT = 300_000
        over_demo = {"영업팀": C.ENTERTAIN, "AI·개발팀": C.MEETING, "재무회계팀": C.TRIP}

        used: dict[tuple[int, str, str], int] = defaultdict(int)
        for s in Settlement.objects.exclude(status=S.REJECT).select_related("transaction"):
            if s.team_id:
                key = timezone.localtime(s.transaction.ts).strftime("%Y-%m")
                used[(s.team_id, key, s.category)] += int(s.transaction.amount)

        def round_up(value, unit=10_000):
            return int(-(-int(value) // unit) * unit)

        for year, month in self.months:
            key = f"{year:04d}-{month:02d}"
            for team in teams.values():
                limits = {}
                for category in C.values:
                    spent = used.get((team.id, key, category), 0)
                    rate = OVER_RATE if over_demo.get(team.name) == category else BASE_RATE
                    limits[category] = max(MIN_LIMIT, round_up(spent / rate)) if spent else MIN_LIMIT
                for category, limit in limits.items():
                    TeamBudget.objects.create(team=team, year_month=key,
                                              category=category, limit_amount=limit)
                TeamBudget.objects.create(team=team, year_month=key, category="",
                                          limit_amount=sum(limits.values()))

    # ── 알림 정리 ────────────────────────────────────────────────────────
    def _prune_notifications(self) -> None:
        """**끝난 건의 알림은 지운다.**

        알림은 "지금 당신이 할 일"이지 과거 원장이 아니다(원장은 `SettlementEvent`가 갖고
        있다). 3개월치 전이를 전부 태우면 종결된 건의 알림 수백 개가 종이 되어 시연 첫
        화면이 읽을 수 없게 된다 — 진행 중인 건의 알림만 남긴다.
        """
        alive = set(
            Settlement.objects
            .exclude(status__in=[S.CONFIRMED, S.ERP_VOUCHER_DRAFTED, S.REJECT, S.TEAM_REJECTED])
            .values_list("pk", flat=True)
        )
        keep = {f"settlement:{pk}" for pk in alive}
        Notification.objects.exclude(target__in=keep).delete()

    # ── 결과 보고 ────────────────────────────────────────────────────────
    def _report(self, mismatched: list[tuple[Spend, str]]) -> None:
        #  기대 불일치는 **조용히 넘기지 않는다** — verbosity=0으로 불려도 경고는 낸다.
        if mismatched:
            self.stdout.write(self.style.WARNING(
                f"\n[경고] 시드가 기대한 판정과 엔진 결과가 다른 건 {len(mismatched)}개:"
            ))
            for row, actual in mismatched[:20]:
                #  사례 건은 표시해 둔다 — 이게 어긋나면 사례가 통째로 안 생긴다.
                tag = f" [사례 {row.case_pattern}]" if row.case_pattern else ""
                self.stdout.write(
                    f"  - {row.category} {row.merchant} {row.amount:,}원 "
                    f"기대={row.expect} 실제={actual}{tag} · {row.purpose}"
                )
            self.stdout.write("  사실(Spend)을 고치거나 기대값을 갱신할 것.")

        self._report_cases()
        self._warn_unresolved_facts()
        if not self.verbosity:
            return

        by_status = {row["status"]: row["n"]
                     for row in Settlement.objects.values("status").annotate(n=Count("id"))}

        judged = Settlement.objects.exclude(rule_judged_at=None).count()
        reviewed = Settlement.objects.filter(events__to_state=S.IN_REVIEW).distinct().count()
        auto_rate = f"{(1 - reviewed / judged) * 100:.1f}%" if judged else "-"

        self.stdout.write(self.style.SUCCESS(
            f"적용 완료 시드 - 기간 {self.months[0][0]}-{self.months[0][1]:02d} ~ "
            f"{self.months[-1][0]}-{self.months[-1][1]:02d}\n"
            f"  사용자 {User.objects.filter(is_superuser=False).count()}명 / "
            f"카드 {Card.objects.count()}장 / 정산 {Settlement.objects.count()}건 / "
            f"판정로그 {RuleHit.objects.count()}행 / 전표 {ErpVoucher.objects.count()}건 / "
            f"별표 {PolicyTable.objects.count()}행\n"
            f"  ACTIVE 룰 그래프 {RuleGraph.objects.filter(status='ACTIVE').count()}개 "
            f"(DEFAULT GATE는 회사 규정 반영본에 자리를 내주고 ARCHIVED)\n"
            f"  자동처리율 {auto_rate} (판정 {judged}건 중 사람 검토 {reviewed}건)"
        ))
        for status, count in sorted(by_status.items(), key=lambda kv: -kv[1]):
            self.stdout.write(f"    {status:<24}{count:>5}")

    def _report_cases(self) -> None:
        """사례가 **의도한 수만큼 실제로 남았는지** 대조한다.

        사례는 시드가 직접 쓰는 게 아니라 `services.review()`가 「사람의 결정이 기계와
        다르다」고 판단해서 남기는 것이다. 그래서 사이에 있는 어느 고리가 끊겨도
        (엔진이 REVIEW를 안 내거나 · 검토를 안 거치거나 · 사유가 비거나) 사례는 **조용히
        0건이 된다** — 실제로 그랬다(이 시드는 오랫동안 사례를 한 건도 안 만들었다).
        그래서 판정 불일치와 같은 급으로 경고한다.
        """
        expected = getattr(self, "expected_cases", Counter())
        if not expected:
            return
        actual = DecisionCase.objects.count()
        want = sum(expected.values())
        if actual != want:
            self.stdout.write(self.style.WARNING(
                f"\n[경고] 결정 사례 기대 {want}건 / 실제 {actual}건. "
                "엔진이 REVIEW를 안 냈거나(위 판정 불일치 참조) 사람의 결정이 "
                "AI 권고와 같아진 것이다."
            ))
        if not self.verbosity:
            return
        by_pattern = " · ".join(f"{k} {v}건" for k, v in sorted(expected.items()))
        indexed = DecisionCase.objects.exclude(indexed_at=None).count()
        self.stdout.write(
            f"  결정 사례 {actual}건 ({by_pattern}) / Chroma 적재 {indexed}건"
            + ("" if indexed == actual else
               "\n    ※ 미적재분은 ai 기동 후 `manage.py reindex_cases`로 올린다")
        )

    def _warn_unresolved_facts(self) -> None:
        """**룰이 참조하는데 시드가 못 채운 사실**을 끝에 나열한다.

        기대 판정 불일치(`expect`)는 "결과가 다르다"만 말해서, 원인이 사실 누락인지 룰 변경인지
        구분되지 않는다. 실제로 그 구분이 필요했다 — 접대 그래프가 「문서로 확인된 인원」을
        요구하도록 바뀌었을 때, 시드는 "기대=PASS 실제=REVIEW"라고만 알려줬고 **왜인지는
        `rule_hits`를 직접 열어야** 알 수 있었다(2026-08-24).

        미해소는 판정 플래그에 이미 경로까지 적혀 있다(`UNRESOLVED_FACT:<경로>`) — 그걸 모아
        보여주기만 하면 된다. 새 룰이 새 사실을 요구할 때 **그 자리에서** 드러난다.
        """
        counts: dict[str, int] = {}
        for flags in RuleHit.objects.values_list("flags", flat=True):
            for flag in flags or []:
                if str(flag).startswith("UNRESOLVED_"):
                    counts[str(flag)] = counts.get(str(flag), 0) + 1
        if not counts:
            return
        self.stdout.write(self.style.WARNING(
            f"\n[경고] 룰이 참조하는데 시드가 못 채운 사실 {len(counts)}종:"
        ))
        for flag, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            #  em dash를 쓰지 않는다 — 윈도우 콘솔(cp949)에서 UnicodeEncodeError로 죽는다.
            #  이 경고는 룰이 못 채운 사실이 있을 때만 뜨므로, 평소엔 안 보이다가
            #  그래프를 고친 순간 시드 전체를 죽인다(실측 2026-08-25).
            note = f"  ({INTENTIONAL_UNRESOLVED[flag]})" if flag in INTENTIONAL_UNRESOLVED else ""
            self.stdout.write(f"  - {flag} : {n}건 강등{note}")
        self.stdout.write(
            "  판정이 「정보 부족」으로 떨어진다. 그 사실을 만드는 첨부·컬럼을 시드에 추가할 것"
            "(괄호가 붙은 줄은 시드가 일부러 비워 둔 것이다)."
        )
