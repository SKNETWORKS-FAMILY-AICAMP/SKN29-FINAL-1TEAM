"""검토 에이전트(Risk Review Agent) 평가용 검증셋 100건 생성.

    python manage.py seed_risk_eval --dry-run   # 무엇을 만들지 미리 본다
    python manage.py seed_risk_eval             # 생성 + 실제 룰 판정까지

## 왜 별도 검증셋인가

`domain/policies/golden.py`의 300건은 **룰엔진 채점용**이라 이 에이전트엔 못 쓴다.
그 셋은 EvalContext 딕셔너리만 갖고 Settlement 행이 없는데, 검토 에이전트는
`run(settlement_id)`로 시작해 카드 이력 기반 이상탐지를 돌린다 — DB 행이 없으면
시작조차 못 한다. 게다가 이 에이전트의 핵심 입력인 `purpose`(자유서술)가 그 셋엔
아예 없고, 「애매한 건은 일부러 뺐다」는 golden의 설계 원칙은 검토 에이전트가 실제로
투입되는 자리(룰이 검토로 넘긴 건)를 정확히 비워둔다.

## 무엇을 재려는가 — 최종 추천처리의 합리성

문서 근거의 정확성·환각 여부는 하네스(서버측 인용 대조)가 이미 막는다. 여기서 재는
것은 **그래서 이 건을 어떻게 하라고 했는가**, 그리고 그 권고가 실제 정산 처리에
미치는 영향이다. 그래서 채점은 3값(APPROVE/SUPPLEMENT/REJECT)을 2값으로 접는다:

    APPROVE            → 승인
    SUPPLEMENT/REJECT  → 보완반려

「보완인가 반려인가」는 담당자가 조정할 수 있는 수위 문제지만, 「통과시킬 건인가
되돌릴 건인가」를 틀리면 정산 결과 자체가 달라진다.

## 구성 — 100건 (50 : 25 : 25)

    승인       50건   5개 분류 × 10건. 모든 요건이 갖춰진 정상 지출
    보완       25건   서류·기재 미비 — 사실관계는 정상이나 확인할 수 없다
    반려       25건   명백한 규정 위반 — 금지업종·현금성·한도 초과

보완 25 + 반려 25 = 보완반려 50건이고, 채점은 이 둘을 합쳐서 한다. 하위 구분을
남기는 이유는 **에이전트가 수위를 어떻게 고르는지**를 따로 보기 위해서다(채점엔 안 쓴다).

## 설계 원칙 — golden.py에서 그대로 가져온 것

  · **위반은 한 건에 하나만.** 두 개를 겹치면 어느 근거로 잡았는지 알 수 없다.
  · **정상 건이 우연히 위반이 되지 않게.** 인원을 금액에서 역산해 1인당 한도 안에 둔다.
  · **애매한 건은 넣지 않는다.** 「사람마다 다르게 볼 수 있는」 건을 섞으면 오답이
    에이전트 탓인지 설계 탓인지 갈리지 않는다.

여기에 이 에이전트에만 해당하는 원칙 하나를 더한다:

  · **판단 근거를 자유서술에도 싣는다.** 구조화 필드로만 신호를 주면 「문장을 읽는
    능력」이 평가에서 통째로 빠진다. 목적란은 실제 담당자가 쓸 법한 문장으로 적는다.

## 카드 이력을 새로 만들지 않는 이유

1차 이상탐지 점수는 **카드별 과거 거래 분포**에서 나온다. 이력이 없는 새 카드에
얹으면 점수가 상수에 수렴하고, 그 점수가 등급 분기(LOW=LLM 0회 / MEDIUM=fast /
HIGH=heavy)를 결정하므로 **평가 대상 경로 자체가 뒤틀린다.** 그래서 기존 시드가 만든
실제 카드(거래 21~26건 보유)에 얹는다.

## 재실행

`Transaction.raw_payload["riskEvalCase"]` 표식으로 이전 실행분만 찾아 지운다.
가맹점명이나 목적란에 표식을 넣지 않는 이유는 **그 두 값이 에이전트 프롬프트에 그대로
실리기** 때문이다 — 평가용 태그가 판단 근거에 섞이면 안 된다.

## AI 호출

이 명령은 **에이전트를 부르지 않는다.** 룰 판정만 실제 경로로 태우고
(`raise_to_team → submit → judge`), 검토 에이전트 실행은 평가 스크립트가 100건
전부에 대해 균일하게 돌린다. 판정 중 자동 예약(`risk_review.AUTO_SCHEDULE`)은
꺼두고 끝나면 되돌린다 — 안 그러면 검토로 떨어진 건만 먼저 AI를 부르게 되어
표본이 두 경로로 갈린다.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings as dj_settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from domain.cards.models import Card
from domain.settlements import risk_review, services
from domain.settlements.models import Settlement
from domain.settlements.models import SettlementStatus as S
from domain.transactions import industry as industry_vocab
from domain.transactions.models import Receipt, Transaction

User = get_user_model()

#: 라벨 파일 — 평가 스크립트가 이걸 읽어 채점한다.
GOLDEN_OUT = "var/risk_eval_golden.json"

APPROVE, BLOCK = "승인", "보완반려"

#: 하위 구분(채점엔 안 쓴다 — 수위 선택 경향만 따로 본다).
SUB_OK, SUB_SUPPLEMENT, SUB_REJECT = "정상", "서류미비", "규정위반"


def _n(amount: int, per_person_cap: int = 40_000) -> int:
    """정상 건의 참석 인원 — 금액에서 역산해 1인당 한도 안에 들게 한다.

    인원을 금액과 무관하게 뽑으면 평범한 회식의 절반이 1인당 한도 초과로 둔갑한다
    (golden.py가 같은 이유로 같은 방식을 쓴다).
    """
    return max(2, amount // per_person_cap + 1)


# ─────────────────────────────────────────────── 승인 50건 (5분류 × 10)
#
#  금액·가맹점·목적만 흔들고 **판정에 걸릴 사실은 전부 정상**이다.
#  증빙 있음 · 목적 기재 · 인원 기재 · 업종 정상 · 2차 아님 · 사전승인(고액 건).

_NORMAL_SPECS = [
    # (분류, 업종, 지출유형, [(가맹점, 금액, 목적), ...])
    ("식대", "일반음식점", "식사", [
        ("김밥천국 판교점", 28_000, "영업1팀 야근 저녁식사"),
        ("한솥도시락 정자점", 19_500, "마감 대응 야근 식대"),
        ("본죽 삼평점", 34_000, "출근 조 아침 식사"),
        ("compose커피 판교", 12_000, "오전 회의 전 간단 식사"),
        ("명동칼국수 분당", 46_000, "팀원 3인 점심 식대"),
        ("설렁탕집 서현", 52_000, "거래처 방문 전 점심"),
        ("돈까스클럽 야탑", 38_000, "신입 온보딩 점심"),
        ("우리집국밥 이매", 41_000, "월말 마감 근무 식대"),
        ("샐러디 판교테크노", 26_500, "재고 실사 대응 식사"),
        ("김치찌개연구소", 44_000, "협력사 실무 미팅 식사"),
    ]),
    ("회의", "카페", "식사", [
        ("스타벅스 판교점", 32_000, "주간 스프린트 회의 음료"),
        ("투썸플레이스 정자", 41_000, "제품 로드맵 검토 회의"),
        ("이디야 삼평점", 24_000, "채용 인터뷰 진행 다과"),
        ("커피빈 서현역", 38_500, "분기 실적 리뷰 회의"),
        ("폴바셋 판교", 56_000, "협력사 킥오프 회의 다과"),
        ("블루보틀 성수", 62_000, "외부 자문 미팅 음료"),
        ("할리스 야탑", 29_000, "팀 회고 회의 다과"),
        ("파스쿠찌 미금", 35_000, "월간 운영 점검 회의"),
        ("탐앤탐스 이매", 27_500, "신규 과제 착수 회의"),
        ("메가커피 판교역", 18_000, "데일리 스탠드업 음료"),
    ]),
    ("접대", "일반음식점", "식사", [
        ("한정식 다담 분당", 168_000, "협력사 계약 협의 오찬, 외부 2인 참석"),
        ("일식 미소야 정자", 142_000, "납품사 실무진 미팅 만찬"),
        ("중식당 만리향", 118_000, "거래처 담당자 상견례"),
        ("이탈리안 포지타노", 155_000, "신규 파트너 사업 논의"),
        ("한우다이닝 서현", 196_000, "연간 계약 갱신 협의 만찬"),
        ("바베큐하우스 판교", 124_000, "외주 개발사 중간 점검 오찬"),
        ("스시켄 분당", 178_000, "기술 제휴 논의 만찬"),
        ("가온한식 야탑", 132_000, "협력사 품질 개선 회의 오찬"),
        ("퓨전다이닝 미금", 149_000, "공급사 단가 협의 만찬"),
        ("정통중식 이매", 108_000, "물류사 실무 협의 오찬"),
    ]),
    ("회식", "일반음식점", "식사", [
        ("고기굽는집 판교", 186_000, "영업1팀 월례 회식, 참석 6명"),
        ("삼겹살명가 정자", 152_000, "분기 목표 달성 팀 회식"),
        ("곱창전골 서현", 168_000, "신규 입사자 환영 회식"),
        ("치킨앤비어 야탑", 124_000, "프로젝트 마무리 회식"),
        ("해물찜 미금", 198_000, "상반기 마감 팀 회식"),
        ("보쌈정식 이매", 142_000, "팀 워크숍 후 저녁 회식"),
        ("숯불갈비 분당", 214_000, "연간 우수팀 선정 축하 회식"),
        ("포차한잔 판교역", 118_000, "월간 회고 후 팀 저녁"),
        ("전집 성수", 136_000, "협업 종료 기념 팀 회식"),
        ("국수와만두 정자", 96_000, "소규모 팀 점심 회식"),
    ]),
    ("출장", "주유/교통", "교통", [
        ("코레일 KTX", 94_500, "부산 고객사 방문 왕복 교통비"),
        ("SR 수서고속철", 88_000, "대전 지사 업무 출장 교통비"),
        ("GS칼텍스 판교점", 72_000, "충청권 협력사 순회 주유비"),
        ("고속버스 동서울", 34_000, "강원 사업장 점검 출장"),
        ("SK에너지 분당", 65_000, "경기 남부 거래처 방문 주유"),
        ("카카오T 택시", 28_500, "공항 이동 교통비"),
        ("현대오일뱅크 야탑", 78_000, "영남권 출장 주유비"),
        ("공항철도", 19_000, "인천공항 이동 교통비"),
        ("에쓰오일 미금", 69_500, "호남권 협력사 방문 주유"),
        ("코레일 무궁화", 42_000, "청주 사업장 실사 교통비"),
    ]),
]


# ─────────────────────────────────────────────── 보완 25건 (서류·기재 미비)
#
#  **사실관계 자체는 정상**이다. 다만 확인할 근거가 없다 — 담당자가 보완을 요청해
#  받아내면 해소되는 종류. 각 건은 빠진 것이 **하나뿐**이다.

#  결함은 **요약 정보에 실제로 신호가 남는 것**만 쓴다. 예를 들어 「참석자 명단 없음」은
#  첨부 문서의 문제라 요약에 흔적이 없어, 명단을 안 낸 정상 건과 구분되지 않는다 —
#  그런 결함을 넣으면 에이전트가 못 맞히는 게 아니라 **맞힐 방법이 없는** 문제가 된다.
_SUPPLEMENT_SPECS = [
    # (분류, 업종, 지출유형, 가맹점, 금액, 목적, 결함키, 사유)
    # ── 사전승인 누락 7건 — 고액인데 승인 기록이 없다(preApproved=False로 보인다)
    ("접대", "일반음식점", "식사", "한정식 소반 분당", 620_000, "협력사 임원 만찬", "no_preapproval",
     "50만원 초과 집행인데 사전승인 기록이 없다"),
    ("접대", "일반음식점", "식사", "일식 오마카세 정자", 540_000, "신규 거래처 대표 만찬", "no_preapproval",
     "50만원 초과 집행인데 사전승인 기록이 없다"),
    ("접대", "일반음식점", "식사", "한우다이닝 서현", 580_000, "연간 계약 갱신 만찬", "no_preapproval",
     "50만원 초과 집행인데 사전승인 기록이 없다"),
    ("접대", "일반음식점", "식사", "정통일식 미금", 512_000, "공급사 임원 만찬", "no_preapproval",
     "50만원 초과 집행인데 사전승인 기록이 없다"),
    ("회식", "일반음식점", "식사", "대형연회장 판교", 720_000, "본부 전체 회식", "no_preapproval",
     "고액 회식인데 사전승인 기록이 없다"),
    ("회식", "일반음식점", "식사", "뷔페레스토랑 분당", 680_000, "부서 통합 회식", "no_preapproval",
     "고액 회식인데 사전승인 기록이 없다"),
    ("기타", "전자/가전", "기타", "하이마트 야탑", 560_000, "팀 공용 모니터 구매", "no_preapproval",
     "50만원 초과 집행인데 사전승인 기록이 없다"),
    # ── 참석 인원 미기재 6건 — 1인당 한도를 볼 수 없다(headcount=null)
    ("회식", "일반음식점", "식사", "화로구이 판교", 168_000, "팀 월례 회식", "no_headcount",
     "참석 인원이 없어 1인당 한도를 확인할 수 없다"),
    ("회식", "일반음식점", "식사", "양대창 정자", 192_000, "분기 마감 회식", "no_headcount",
     "참석 인원이 없어 1인당 한도를 확인할 수 없다"),
    ("회식", "일반음식점", "식사", "조개구이 야탑", 154_000, "프로젝트 종료 회식", "no_headcount",
     "참석 인원이 없어 1인당 한도를 확인할 수 없다"),
    ("회식", "일반음식점", "식사", "해산물포차 판교", 182_000, "팀 저녁 회식", "no_headcount",
     "참석 인원이 없어 1인당 한도를 확인할 수 없다"),
    ("접대", "일반음식점", "식사", "중식당 백리향", 228_000, "거래처 실무 협의 만찬", "no_headcount",
     "참석 인원이 없어 1인당 한도를 확인할 수 없다"),
    ("접대", "일반음식점", "식사", "이탈리안 트라토리아", 246_000, "공급사 미팅 만찬", "no_headcount",
     "참석 인원이 없어 1인당 한도를 확인할 수 없다"),
    # ── 지출 목적 미기재 6건 — 업무 관련성을 판단할 근거가 없다(purpose 공란)
    ("회식", "일반음식점", "식사", "닭갈비촌 미금", 176_000, "", "no_purpose",
     "지출 목적이 기재되지 않았다"),
    ("회식", "일반음식점", "식사", "막창골목 서현", 148_000, "", "no_purpose",
     "지출 목적이 기재되지 않았다"),
    ("식대", "일반음식점", "식사", "고기국수 판교", 58_000, "", "no_purpose",
     "지출 목적이 기재되지 않았다"),
    ("회의", "카페", "식사", "베이커리카페 이매", 68_000, "", "no_purpose",
     "지출 목적이 기재되지 않았다"),
    ("출장", "주유/교통", "교통", "렌터카 제주", 186_000, "", "no_purpose",
     "지출 목적이 기재되지 않았다"),
    ("접대", "일반음식점", "식사", "가온한정식 서현", 194_000, "", "no_purpose",
     "지출 목적이 기재되지 않았다"),
    # ── 적격증빙 누락 6건 — 영수증이 없다(판정 스냅샷·사유 플래그에 남는다)
    ("식대", "일반음식점", "식사", "제육본가 정자", 47_000, "팀 점심 식대", "no_receipt",
     "적격증빙(영수증)이 첨부되지 않았다"),
    ("식대", "일반음식점", "식사", "냉면집 서현", 52_000, "야근 대응 식대", "no_receipt",
     "적격증빙(영수증)이 첨부되지 않았다"),
    ("식대", "일반음식점", "식사", "순대국밥 야탑", 39_000, "주말 당직 식대", "no_receipt",
     "적격증빙(영수증)이 첨부되지 않았다"),
    ("회의", "카페", "식사", "카페드파리 분당", 88_000, "외부 자문단 회의 다과", "no_receipt",
     "적격증빙(영수증)이 첨부되지 않았다"),
    ("출장", "숙박", "숙박", "비즈니스호텔 대전", 138_000, "대전 지사 출장 1박 숙박비", "no_receipt",
     "적격증빙(영수증)이 첨부되지 않았다"),
    ("출장", "숙박", "숙박", "시티호텔 부산", 142_000, "부산 고객사 출장 숙박비", "no_receipt",
     "적격증빙(영수증)이 첨부되지 않았다"),
]


# ─────────────────────────────────────────────── 반려 25건 (명백한 규정 위반)
#
#  **보완으로 해소되지 않는다.** 서류를 더 받아도 지출 자체가 규정 위반이다.

_REJECT_SPECS = [
    # (분류, 업종, 지출유형, 가맹점, 금액, 목적, 인원, 결함키, 사유)
    ("회식", "주점/유흥", "식사", "유흥주점 블루문", 480_000, "팀 회식 2차", 6, "forbidden_industry",
     "금지업종(유흥주점) 결제"),
    ("회식", "주점/유흥", "식사", "룸살롱 로얄", 620_000, "거래처 접대 후 이동", 5, "forbidden_industry",
     "금지업종(유흥주점) 결제"),
    ("회식", "노래연습장", "식사", "코인노래방 판교", 96_000, "회식 후 2차 노래방", 8, "forbidden_industry",
     "금지업종(노래연습장) 결제"),
    ("회식", "노래연습장", "식사", "노래연습장 하모니", 128_000, "팀 회식 2차", 7, "forbidden_industry",
     "금지업종(노래연습장) 결제"),
    ("접대", "사행성업종", "식사", "강원랜드 카지노", 850_000, "거래처 임원 동행", 3, "forbidden_industry",
     "금지업종(사행성) 결제"),
    ("접대", "주점/유흥", "식사", "바 프리미엄 청담", 540_000, "협력사 임원 접대 2차", 4, "forbidden_industry",
     "금지업종(주점) 결제"),
    ("회식", "노래연습장", "식사", "가라오케 스타", 210_000, "부서 회식 2차", 9, "forbidden_industry",
     "금지업종(노래연습장) 결제"),
    ("기타", "마트/편의점", "상품권", "이마트 판교점", 500_000, "명절 협력사 선물 구매", None, "cash_equivalent",
     "현금성 자산(상품권) 구매"),
    ("기타", "마트/편의점", "상품권", "롯데백화점 분당", 600_000, "거래처 감사 선물", None, "cash_equivalent",
     "현금성 자산(상품권) 구매"),
    ("접대", "마트/편의점", "상품권", "신세계상품권 센터", 400_000, "협력사 명절 인사", None, "cash_equivalent",
     "현금성 자산(상품권) 구매"),
    ("기타", "면세점", "상품권", "신라면세점", 380_000, "해외 거래처 선물 구매", None, "cash_equivalent",
     "현금성 자산(상품권) 구매"),
    ("접대", "마트/편의점", "상품권", "GS리테일 기프트", 320_000, "거래처 담당자 선물", None, "cash_equivalent",
     "현금성 자산(상품권) 구매"),
    ("회식", "일반음식점", "식사", "한우오마카세 청담", 640_000, "팀 회식, 참석 4명", 4, "per_person_over",
     "1인당 160,000원 — 회식 1인당 한도(50,000원) 3배 초과"),
    ("회식", "일반음식점", "식사", "프리미엄스시 판교", 520_000, "팀 회식, 참석 4명", 4, "per_person_over",
     "1인당 130,000원 — 회식 1인당 한도 초과"),
    ("회식", "일반음식점", "식사", "와규전문점 정자", 450_000, "소규모 팀 회식, 참석 3명", 3, "per_person_over",
     "1인당 150,000원 — 회식 1인당 한도 초과"),
    ("회식", "일반음식점", "식사", "게살요리 전문점", 380_000, "팀 회식, 참석 3명", 3, "per_person_over",
     "1인당 126,667원 — 회식 1인당 한도 초과"),
    ("회식", "일반음식점", "식사", "송이버섯한정식", 340_000, "팀 저녁 회식, 참석 2명", 2, "per_person_over",
     "1인당 170,000원 — 회식 1인당 한도 초과"),
    ("출장", "숙박", "숙박", "그랜드호텔 서울", 420_000, "서울 본사 출장 1박 숙박비", None, "lodging_over",
     "국내 1박 숙박비 상한(150,000원) 초과"),
    ("출장", "숙박", "숙박", "리조트 스위트 제주", 380_000, "제주 워크숍 1박 숙박비", None, "lodging_over",
     "국내 1박 숙박비 상한 초과"),
    ("출장", "숙박", "숙박", "특급호텔 부산", 350_000, "부산 출장 1박 숙박비", None, "lodging_over",
     "국내 1박 숙박비 상한 초과"),
    ("출장", "숙박", "숙박", "호텔스위트 대구", 290_000, "대구 지사 출장 1박", None, "lodging_over",
     "국내 1박 숙박비 상한 초과"),
    ("기타", "골프장", "행사성", "레이크사이드CC", 720_000, "거래처 임원 라운딩", 4, "forbidden_industry",
     "금지업종(골프장) 결제"),
    ("기타", "이·미용", "기타", "프리미엄 스파 청담", 280_000, "임원 개인 이용", None, "personal_use",
     "업무 관련성이 없는 개인 목적 지출"),
    ("기타", "레저", "행사성", "요트클럽 한강", 560_000, "거래처 초청 행사", 6, "forbidden_industry",
     "업무 무관 레저 시설 결제"),
    ("회식", "주점/유흥", "식사", "이자카야 프리미엄", 340_000, "회식 3차 이동", 5, "forbidden_industry",
     "금지업종(주점) 결제 · 3차 이동"),
]


class Command(BaseCommand):
    help = "검토 에이전트 평가용 검증셋 100건 생성 (승인 50 · 보완 25 · 반려 25)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="생성 없이 구성만 출력")

    # ── 실행 ────────────────────────────────────────────────────────
    def handle(self, *args, **options):
        cases = self._compose()
        self._print_composition(cases)
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("\n(dry-run — 아무것도 만들지 않았다)"))
            return

        actors = self._actors()
        self._cleanup()

        # 판정이 검토로 떨어진 건만 먼저 AI를 부르면 표본이 두 경로로 갈린다.
        # 평가는 100건 전부를 같은 방식으로 돌려야 한다.
        saved = risk_review.AUTO_SCHEDULE
        risk_review.AUTO_SCHEDULE = False
        try:
            rows = [self._materialize(c, actors, i) for i, c in enumerate(cases)]
        finally:
            risk_review.AUTO_SCHEDULE = saved

        out = Path(dj_settings.BASE_DIR) / GOLDEN_OUT
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

        self._report(rows, out)

    # ── 구성 ────────────────────────────────────────────────────────
    def _compose(self) -> list[dict]:
        cases: list[dict] = []
        for category, industry, item_type, items in _NORMAL_SPECS:
            for merchant, amount, purpose in items:
                cases.append(dict(
                    label=APPROVE, sub=SUB_OK, category=category, industry=industry,
                    item_type=item_type, merchant=merchant, amount=amount, purpose=purpose,
                    headcount=_n(amount), defect="", note="모든 요건 충족",
                ))
        for category, industry, item_type, merchant, amount, purpose, defect, note in _SUPPLEMENT_SPECS:
            cases.append(dict(
                label=BLOCK, sub=SUB_SUPPLEMENT, category=category, industry=industry,
                item_type=item_type, merchant=merchant, amount=amount, purpose=purpose,
                headcount=None if defect == "no_headcount" else _n(amount),
                defect=defect, note=note,
            ))
        for category, industry, item_type, merchant, amount, purpose, headcount, defect, note in _REJECT_SPECS:
            cases.append(dict(
                label=BLOCK, sub=SUB_REJECT, category=category, industry=industry,
                item_type=item_type, merchant=merchant, amount=amount, purpose=purpose,
                headcount=headcount, defect=defect, note=note,
            ))
        return cases

    def _print_composition(self, cases: list[dict]) -> None:
        from collections import Counter
        self.stdout.write(f"검증셋 {len(cases)}건")
        for k, v in Counter((c["label"], c["sub"]) for c in cases).items():
            self.stdout.write(f"  {k[0]:5s} / {k[1]:6s}  {v:3d}건")
        self.stdout.write("  분류별: " + ", ".join(
            f"{k} {v}" for k, v in Counter(c["category"] for c in cases).most_common()))

    # ── 생성 ────────────────────────────────────────────────────────
    def _actors(self) -> list[tuple]:
        """실제 카드 이력이 있는 (카드, 소유자, 팀) 조합. 없으면 멈춘다."""
        from django.db.models import Count

        cards = (Card.objects.annotate(n=Count("transactions"))
                 .filter(n__gte=5, owner__isnull=False, team__isnull=False)
                 .select_related("owner", "team").order_by("-n")[:6])
        if not cards:
            raise SystemExit(
                "거래 이력이 있는 카드가 없다 — `seed_adopted`(또는 `seed`)를 먼저 실행할 것.\n"
                "이력 없는 카드에 얹으면 1차 이상탐지 점수가 무의미해진다."
            )
        return [(c, c.owner, c.team) for c in cards]

    def _cleanup(self) -> None:
        """이전 실행분만 지운다 — 표식은 raw_payload에만 둔다(프롬프트에 안 실린다)."""
        old = Transaction.objects.filter(raw_payload__has_key="riskEvalCase")
        n = Settlement.objects.filter(transaction__in=old).delete()[0]
        m = old.delete()[0]
        if n or m:
            self.stdout.write(f"이전 실행분 정리: 정산·거래 {n + m}행")

    def _materialize(self, case: dict, actors: list[tuple], idx: int) -> dict:
        card, owner, team = actors[idx % len(actors)]
        now = timezone.localtime(timezone.now())
        ts = (now - timezone.timedelta(days=1 + idx % 21)).replace(
            hour=12 if case["category"] != "회식" else 19, minute=30, second=0, microsecond=0)

        tx = Transaction.objects.create(
            card=card, merchant=case["merchant"], amount=case["amount"], ts=ts,
            raw_payload={"일시불할부구분코드": "A", "riskEvalCase": f"RE-{idx + 1:03d}"},
        )
        if case["defect"] != "no_receipt":
            Receipt.objects.create(matched_tx=tx, status=Receipt.Status.MATCHED,
                                   file_ref=f"receipts/{tx.id}.jpg")

        code, label = industry_vocab.resolve(case["industry"])
        #  결함이 아닌 사실은 **전부 채운다.** `None`은 「모름」이라 미해소 가드가 판정을
        #  검토로 낮춘다 — 결함 하나만 뒤집는다는 설계가 무너진다.
        settlement = Settlement.objects.create(
            transaction=tx, category=case["category"], ai_category=case["category"],
            ai_suggested=True, merchant_industry=label, merchant_industry_code=code,
            purpose=case["purpose"], status=S.DRAFT, submitted_by=owner, team=team,
            item_type=case["item_type"],
            headcount=case["headcount"],
            external_headcount=(
                None if case["headcount"] is None
                else (2 if case["category"] == "접대" else 0)
            ),
            kickback_target=False,
            pre_approved=case["defect"] != "no_preapproval",
            is_secondary_venue="2차" in case["purpose"] or "3차" in case["purpose"],
            includes_alcohol=case["category"] == "회식",
            actual_user_recorded=True, actual_user=owner,
        )

        # 실제 상태머신을 태운다 — 판정 스냅샷(EvalContext)이 있어야 에이전트가
        # 화면에 없는 사실(이력·신고vs확인 인원·미해소)을 볼 수 있다.
        services.raise_to_team(settlement, owner)
        services.submit(settlement, owner)
        result = services.judge(settlement, owner, reuse_recorded=True)
        settlement.refresh_from_db()

        return {
            "case_id": f"RE-{idx + 1:03d}",
            "settlementId": settlement.pk,
            "label": case["label"],
            "sub": case["sub"],
            "category": case["category"],
            "merchant": case["merchant"],
            "amount": case["amount"],
            "defect": case["defect"],
            "note": case["note"],
            "ruleDecision": getattr(result, "decision", "") or "",
            "status": settlement.status,
        }

    # ── 결과 ────────────────────────────────────────────────────────
    def _report(self, rows: list[dict], out: Path) -> None:
        from collections import Counter

        self.stdout.write(self.style.SUCCESS(f"\n생성 완료 — {len(rows)}건"))
        self.stdout.write(f"라벨 파일: {out}")
        self.stdout.write("\n[참고] 룰엔진이 같은 건을 어떻게 판정했나 — 라벨별 분포")
        for label in (APPROVE, BLOCK):
            dist = Counter(r["ruleDecision"] for r in rows if r["label"] == label)
            self.stdout.write(f"  {label:5s}  " + ", ".join(f"{k or '(없음)'} {v}" for k, v in dist.most_common()))
        self.stdout.write(
            "\n룰 판정은 참고값이다 — 이 검증셋이 채점하는 것은 검토 에이전트의 최종 추천처리다."
        )
