"""`case_history` 최소 골든 데이터 — Risk Review 2차 검증(search_cases) 실측용.

RAG 인덱싱(policy_docs·tax_refs·org_docs)은 이미 실 문서 기반으로 적재돼 있지만
case_history는 아직 적재 파이프라인이 없다(과거 결정 이력을 임베딩하는 별도 배치가
필요 — Django `RiskReview`/`Settlement` 실데이터를 정기적으로 case_history에
반영하는 것은 post-MVP). 그 전까지 2차 검증이 "죽은 경로"가 되지 않도록, 시연 시드
(`seed.py` processed_reviews)의 대표 사례 성격을 반영한 최소 골든 셋을 수동으로 채운다.

⚠️ 이 데이터는 실제 회계 담당자 결정이 아니라 시연/개발용 예시다 — 실제 결정 이력
적재 파이프라인이 생기면 이 파일은 폐기한다.
"""
from __future__ import annotations

GOLDEN_CASES: list[dict] = [
    {
        "case_id": "case-golden-001",
        "category": "접대",
        "outcome": "REJECT",
        "citation": "과거 반려사례 #1123",
        "text": (
            "접대비 45만원, 심야(22시) 결제, 적격증빙(영수증) 미첨부. "
            "3만원 초과 접대비는 적격증빙 없이는 손금불산입 대상이라 반려 처리."
        ),
    },
    {
        "case_id": "case-golden-002",
        "category": "접대",
        "outcome": "REJECT",
        "citation": "과거 반려사례 #0842",
        "text": (
            "유흥주점(노래연습장) 결제 17만원, 심야 시간대. 유흥·사행성업종 결제는 "
            "사규상 금지업종이라 증빙 여부와 무관하게 반려."
        ),
    },
    {
        "case_id": "case-golden-003",
        "category": "회의",
        "outcome": "RETURN",
        "citation": "과거 보완요청사례 #0987",
        "text": (
            "동일 가맹점(카페) 12건 반복 결제, 합계 12.8만원, 매건 한도 임계값 바로 아래 금액. "
            "분할결제로 한도를 회피한 것으로 의심되어 원거래 통합·목적 소명을 보완요청."
        ),
    },
    {
        "case_id": "case-golden-004",
        "category": "출장",
        "outcome": "RETURN",
        "citation": "과거 보완요청사례 #0655",
        "text": (
            "출장 숙박비 38.6만원, 1박 숙박 한도 초과, 출장 신청 지역과 결제 가맹점 지역 불일치. "
            "출장 일정 변경 승인 첨부를 조건으로 보완요청."
        ),
    },
    {
        "case_id": "case-golden-005",
        "category": "식대",
        "outcome": "RETURN",
        "citation": "과거 보완요청사례 #0511",
        "text": (
            "회식 2차(주점) 19.8만원, 1인당 한도 초과, 주류 포함. "
            "회식 2차 비용은 원칙적으로 불인정되어 1차 회식비만 인정하고 나머지는 보완요청."
        ),
    },
    {
        "case_id": "case-golden-006",
        "category": "비품",
        "outcome": "RETURN",
        "citation": "과거 보완요청사례 #0399",
        "text": (
            "공용카드로 30만원 상당 상품권(유가증권) 구매, 사전승인 기록 없음. "
            "유가증권 구매는 사전 승인이 필수라 승인 근거 첨부를 조건으로 보완요청."
        ),
    },
    {
        "case_id": "case-golden-007",
        "category": "식대",
        "outcome": "APPROVE",
        "citation": "과거 승인사례 #0221",
        "text": (
            "주말 근무 식대 6만원, 적격증빙 첨부, 인원·목적 기재 명확. "
            "정상 패턴으로 판단해 승인."
        ),
    },
    {
        "case_id": "case-golden-008",
        "category": "출장",
        "outcome": "APPROVE",
        "citation": "과거 승인사례 #0198",
        "text": (
            "지방 출장 KTX 이동비 6만원, 출장 신청·정산 시점 일치, 증빙 첨부 완료. "
            "특이사항 없어 승인."
        ),
    },
    {
        "case_id": "case-golden-009",
        "category": "회의",
        "outcome": "APPROVE",
        "citation": "과거 승인사례 #0145",
        "text": (
            "주간 회의 다과 4.2만원, 참석 인원·목적 명시, 반복 가맹점이나 금액 경미. "
            "정상 범위로 판단해 승인."
        ),
    },
    {
        "case_id": "case-golden-010",
        "category": "접대",
        "outcome": "RETURN",
        "citation": "과거 보완요청사례 #0777",
        "text": (
            "골프장 접대비 42만원, 청탁금지법 대상자(공직자 등) 참석 여부 기재 누락. "
            "대상자 참석 시 1인당 법정 한도 적용 대상이라 참석자 확인을 조건으로 보완요청."
        ),
    },
    # ── 이하 확충분(2026-08-19, agent-v1-upgrade-plan.md §2.2) ──
    # "업무활성"→"회식"(GATHERING) 리네임 이후 이 파일이 갱신되지 않아 회식 사례가
    # 하나도 없었다(정산 카테고리 6종 중 1종 공백) — 우선 보강.
    {
        "case_id": "case-golden-011",
        "category": "회식",
        "outcome": "REJECT",
        "citation": "과거 반려사례 #1301",
        "text": (
            "팀 회식 2차(단란주점) 28만원, 1차와 별도 결제, 주류 포함. "
            "회식 2차 비용은 원칙적으로 불인정 대상이라 반려 처리."
        ),
    },
    {
        "case_id": "case-golden-012",
        "category": "회식",
        "outcome": "APPROVE",
        "citation": "과거 승인사례 #0433",
        "text": (
            "팀 회식 1차(식당) 1인당 3.8만원, 2차 없음, 참석 인원 8명 명시. "
            "1인당 한도 이내·2차 아님으로 정상 승인."
        ),
    },
    {
        "case_id": "case-golden-013",
        "category": "회식",
        "outcome": "RETURN",
        "citation": "과거 보완요청사례 #0912",
        "text": (
            "팀 회식 1인당 14.8만원, 사규상 1인당 한도(4만원) 대비 크게 초과. "
            "실제 참석 인원·특별 행사 여부 소명을 조건으로 보완요청."
        ),
    },
    {
        "case_id": "case-golden-014",
        "category": "비품",
        "outcome": "APPROVE",
        "citation": "과거 승인사례 #0266",
        "text": (
            "사무용품(문구·소모품) 구매 8.4만원, 법인카드 실사용자·목적 명확, 반복 가맹점 아님. "
            "특이사항 없어 승인."
        ),
    },
    {
        "case_id": "case-golden-015",
        "category": "회의",
        "outcome": "RETURN",
        "citation": "과거 보완요청사례 #0704",
        "text": (
            "외부 회의실 대관비 22만원, 참석자 목록·회의 목적 미기재. "
            "회의 성격 지출은 참석자·목적 기재가 필수라 보완요청."
        ),
    },
    {
        "case_id": "case-golden-016",
        "category": "출장",
        "outcome": "REJECT",
        "citation": "과거 반려사례 #0537",
        "text": (
            "출장 신청 없이 사후 결제한 항공권 62만원, 사전승인 기록 전무, 개인 일정과 날짜 중복. "
            "사전승인 없는 고액 출장비는 사후 소명으로도 인정하지 않아 반려."
        ),
    },
    {
        "case_id": "case-golden-017",
        "category": "접대",
        "outcome": "APPROVE",
        "citation": "과거 승인사례 #0289",
        "text": (
            "거래처 미팅 식사 접대비 18만원, 참석 인원 4명(내부 2·외부 2) 명시, 적격증빙 첨부. "
            "1인당 한도 이내·증빙 완비로 승인."
        ),
    },
    {
        "case_id": "case-golden-018",
        "category": "식대",
        "outcome": "RETURN",
        "citation": "과거 보완요청사례 #0623",
        "text": (
            "주말·심야(23시) 연속 식대 결제 5건, 매건 소액이나 짧은 시간 내 반복. "
            "업무 연관성(야근·당직 등) 소명을 조건으로 보완요청."
        ),
    },
]
