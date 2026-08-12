# Docling PDF 파싱 품질 평가 리포트

> 생성: `docling_eval/docling_parsing_evaluation.ipynb`

## 1. 평가 대상

- 자동 정량 평가: **8종** — 법인카드_사용규정, 부서소개, 업무추진비_사용규정, 조직도, 조직설계_상세기획서, 직급체계, 출장비_사용규정, 회식_운영규정
- N/A (Ground Truth 없음): **3종** — 법인세법, 부가가치세법, 여신전문금융업법
- Ground Truth: `tiger_inc/md/*.md` (PDF와 동일 파일명의 원고)
- 평가 입력: `docling_eval/output/` (layout CSV · 표 JSON · 마크다운)

| Document | PDF Pages | Docling Max Page | Page Match | Size (pt) | PDF Chars | Docling Chars | Text Layer | Char Ratio |
|---|---|---|---|---|---|---|---|---|
| 법인세법 | 97 | 97 | OK | 595x842 | 188243 | 180260 | 있음 | 0.958 |
| 법인카드_사용규정 | 7 | 7 | OK | 595x842 | 6148 | 5748 | 있음 | 0.935 |
| 부가가치세법 | 35 | 35 | OK | 595x842 | 65134 | 62009 | 있음 | 0.952 |
| 부서소개 | 5 | 5 | OK | 595x842 | 2633 | 2357 | 있음 | 0.895 |
| 업무추진비_사용규정 | 6 | 6 | OK | 595x842 | 6566 | 6227 | 있음 | 0.948 |
| 여신전문금융업법 | 34 | 34 | OK | 595x842 | 57222 | 53887 | 있음 | 0.942 |
| 조직도 | 6 | 6 | OK | 595x842 | 2663 | 1871 | 있음 | 0.703 |
| 조직설계_상세기획서 | 12 | 12 | OK | 595x842 | 8087 | 6867 | 있음 | 0.849 |
| 직급체계 | 4 | 4 | OK | 595x842 | 1648 | 1546 | 있음 | 0.938 |
| 출장비_사용규정 | 6 | 6 | OK | 595x842 | 4843 | 4555 | 있음 | 0.941 |
| 회식_운영규정 | 10 | 10 | OK | 595x842 | 8433 | 7878 | 있음 | 0.934 |

## 2. 평가 방법

| 영역 | 방법 | 가중치 |
|---|---|---|
| Layout Analysis | GT 요소 시퀀스와 docling 요소 시퀀스를 텍스트로 정렬 → 탐지 P/R/F1 + 타입 혼동행렬 | 0.30 |
| Text Hierarchy | 헤딩 정렬 → 탐지 F1 · 레벨 정확도(오프셋 보정) · 부모-자식 · 문서 순서(LIS) | 0.30 |
| Table Structure | 셀 격자 JSON을 GT 파이프 표와 자카드 매칭 → 탐지/행/열/헤더/셀 값 | 0.40 |

정규화는 2단계(`norm_strict` = 공백 접기, `norm_loose` = 공백·구두점 제거)를 쓰며,
`loose`는 같은데 `strict`가 다른 경우를 **공백·자간 결함**으로 따로 집계한다.

**N/A로 제외한 지표**: Bounding Box IoU, Merged Cell Accuracy
(정답 bbox·병합 정보가 GT에 없어 점수화하지 않았고, 가중치는 같은 영역 내에서 재분배했다.)

## 3. Layout Analysis 결과

| Document | GT | Docling | Detected(TP) | Text Mismatch | Missing(FN) | Extra(FP) | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|---|---|
| 법인카드_사용규정 | 98 | 102 | 97 | 1 | 1 | 5 | 0.951 | 0.99 | 0.97 |
| 부서소개 | 16 | 19 | 15 | 0 | 1 | 4 | 0.789 | 0.938 | 0.857 |
| 업무추진비_사용규정 | 80 | 86 | 78 | 1 | 2 | 8 | 0.907 | 0.975 | 0.94 |
| 조직도 | 22 | 26 | 22 | 0 | 0 | 4 | 0.846 | 1.0 | 0.917 |
| 조직설계_상세기획서 | 59 | 67 | 59 | 0 | 0 | 8 | 0.881 | 1.0 | 0.937 |
| 직급체계 | 19 | 21 | 18 | 0 | 1 | 3 | 0.857 | 0.947 | 0.9 |
| 출장비_사용규정 | 66 | 68 | 63 | 2 | 3 | 5 | 0.926 | 0.955 | 0.94 |
| 회식_운영규정 | 67 | 77 | 63 | 2 | 4 | 14 | 0.818 | 0.94 | 0.875 |

- 전체 Element Detection: P=0.891 / R=0.972 / F1=0.929
- 요소 타입 분류 정확도: 0.923
- Bounding Box IoU: **N/A** (GT에 좌표 없음) — 기하 이상치 0건은 별도 검수

## 4. Text Hierarchy 결과

| Document | GT H | DT H | TP | Text Mismatch | Missing | Extra | Detect F1 | Level δ | Level Acc(strict) | Level Acc(offset) | Parent Acc | Order Acc | GT Levels | DT Levels |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 법인카드_사용규정 | 28 | 28 | 27 | 1 | 1 | 1 | 0.964 | -1 | 0.037 | 0.963 | 0.667 | 0.926 | 1/2/3 | 1/2 |
| 부서소개 | 8 | 9 | 8 | 0 | 0 | 1 | 0.941 | -1 | 0.125 | 0.875 | 1.0 | 1.0 | 1/2 | 1 |
| 업무추진비_사용규정 | 24 | 25 | 22 | 1 | 2 | 3 | 0.898 | -1 | 0.045 | 0.955 | 0.818 | 0.955 | 1/2/3 | 1/2 |
| 조직도 | 5 | 9 | 4 | 0 | 1 | 5 | 0.571 | -1 | 0.25 | 0.75 | 1.0 | 0.75 | 1/2 | 1 |
| 조직설계_상세기획서 | 12 | 23 | 10 | 0 | 2 | 13 | 0.571 | 0 | 1.0 | 1.0 | 0.8 | 1.0 | 1/2 | 1/2 |
| 직급체계 | 5 | 6 | 5 | 0 | 0 | 1 | 0.909 | -1 | 0.2 | 0.8 | 1.0 | 1.0 | 1/2 | 1 |
| 출장비_사용규정 | 23 | 24 | 20 | 2 | 3 | 4 | 0.851 | -1 | 0.05 | 0.95 | 0.5 | 0.85 | 1/2/3 | 1/2 |
| 회식_운영규정 | 20 | 21 | 18 | 2 | 2 | 3 | 0.878 | -1 | 0.056 | 0.889 | 0.722 | 0.889 | 1/2/3 | 1/2 |

- Heading Detection F1=0.844 / Level(offset 보정)=0.930
  (strict=0.149) / Parent-Child=0.737 /
  Document Order=0.921

## 5. Table Structure 결과

| Document | GT Tables | Detected Tables | Matched | Missing | False Positive | Split | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|---|---|
| 법인카드_사용규정 | 2 | 2 | 2 | 0 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| 부서소개 | 7 | 9 | 7 | 0 | 0 | 2 | 1.0 | 1.0 | 1.0 |
| 업무추진비_사용규정 | 3 | 2 | 2 | 1 | 0 | 0 | 1.0 | 0.667 | 0.8 |
| 조직도 | 2 | 4 | 2 | 0 | 1 | 1 | 0.667 | 1.0 | 0.8 |
| 조직설계_상세기획서 | 6 | 12 | 6 | 0 | 1 | 4 | 0.857 | 1.0 | 0.923 |
| 직급체계 | 2 | 3 | 2 | 0 | 0 | 1 | 1.0 | 1.0 | 1.0 |
| 출장비_사용규정 | 3 | 4 | 3 | 0 | 0 | 1 | 1.0 | 1.0 | 1.0 |
| 회식_운영규정 | 9 | 11 | 8 | 1 | 1 | 2 | 0.889 | 0.889 | 0.889 |

| Document | GT Table | DT Table | GT RxC | DT RxC | Row OK | Col OK | Header Detected | Header OK |
|---|---|---|---|---|---|---|---|---|
| 법인카드_사용규정 | 1 | 1 | 6x2 | 3x2 | False | True | False | False |
| 법인카드_사용규정 | 2 | 2 | 6x4 | 6x4 | True | True | True | True |
| 부서소개 | 1 | 1 | 6x5 | 6x5 | True | True | True | True |
| 부서소개 | 2 | 2 | 3x5 | 3x5 | True | True | True | True |
| 부서소개 | 3 | 3 | 3x5 | 3x5 | True | True | True | True |
| 부서소개 | 4 | 4 | 4x5 | 4x5 | True | True | True | True |
| 부서소개 | 5 | 5,6 | 4x5 | 5x5 | False | True | True | True |
| 부서소개 | 6 | 7 | 2x5 | 2x5 | True | True | True | True |
| 부서소개 | 7 | 8,9 | 12x3 | 13x3 | False | True | True | True |
| 업무추진비_사용규정 | 2 | 1 | 4x3 | 4x3 | True | True | True | True |
| 업무추진비_사용규정 | 3 | 2 | 5x2 | 5x2 | True | True | True | True |
| 조직도 | 1 | 1 | 8x2 | 8x2 | True | True | True | True |
| 조직도 | 2 | 3,4 | 8x2 | 8x2 | True | True | True | True |
| 조직설계_상세기획서 | 1 | 1 | 9x2 | 9x2 | True | True | True | True |
| 조직설계_상세기획서 | 2 | 2,3 | 17x5 | 18x5 | False | True | True | True |
| 조직설계_상세기획서 | 3 | 4,5,6 | 11x4 | 13x4 | False | True | True | True |
| 조직설계_상세기획서 | 4 | 7 | 5x3 | 5x3 | True | True | True | True |
| 조직설계_상세기획서 | 5 | 9,10 | 12x3 | 11x3 | False | True | True | True |
| 조직설계_상세기획서 | 6 | 11,12 | 8x2 | 9x2 | False | True | True | True |
| 직급체계 | 1 | 1,2 | 11x4 | 12x4 | False | True | True | True |
| 직급체계 | 2 | 3 | 5x3 | 5x3 | True | True | True | True |
| 출장비_사용규정 | 1 | 1 | 7x2 | 3x2 | False | True | False | False |
| 출장비_사용규정 | 2 | 2 | 3x4 | 3x4 | True | True | True | True |
| 출장비_사용규정 | 3 | 3,4 | 4x5 | 5x5 | False | True | True | True |
| 회식_운영규정 | 2 | 1 | 9x3 | 9x3 | True | True | True | True |
| 회식_운영규정 | 3 | 2 | 5x5 | 5x5 | True | True | True | True |
| 회식_운영규정 | 4 | 3 | 3x2 | 3x2 | True | True | True | True |
| 회식_운영규정 | 5 | 4 | 5x4 | 5x4 | True | True | True | True |
| 회식_운영규정 | 6 | 5,6 | 8x3 | 9x3 | False | True | True | True |
| 회식_운영규정 | 7 | 7 | 6x2 | 6x2 | True | True | True | True |
| 회식_운영규정 | 8 | 8,9 | 10x5 | 11x5 | False | True | True | True |
| 회식_운영규정 | 9 | 11 | 7x7 | 6x7 | False | True | True | True |

- Cell Accuracy(loose)=0.965 / (strict)=0.755
- Merged Cell Accuracy: **N/A** (마크다운 GT는 rowspan/colspan을 표현할 수 없음)

## 6. 정량 평가 점수

| Category | Metric | Score | Weight | Status | Note | Eff.Weight |
|---|---|---|---|---|---|---|
| Layout | Element Detection F1 | 0.929 | 0.4 | OK |  | 0.533 |
| Layout | Element Type Accuracy | 0.923 | 0.35 | OK | 정렬된 쌍 기준 | 0.467 |
| Layout | Bounding Box IoU |  | 0.25 | N/A | GT 좌표 없음 | 0.0 |
| Hierarchy | Heading Detection F1 | 0.844 | 0.4 | OK |  | 0.4 |
| Hierarchy | Heading Level Accuracy | 0.93 | 0.25 | OK | 문서별 오프셋 보정 | 0.25 |
| Hierarchy | Parent-Child Accuracy | 0.737 | 0.2 | OK |  | 0.2 |
| Hierarchy | Document Order Accuracy | 0.921 | 0.15 | OK |  | 0.15 |
| Table | Table Detection F1 | 0.928 | 0.2 | OK |  | 0.222 |
| Table | Row Accuracy | 0.594 | 0.15 | OK | 행 수 완전일치 비율 | 0.167 |
| Table | Column Accuracy | 1.0 | 0.15 | OK | 열 수 완전일치 비율 | 0.167 |
| Table | Header Accuracy | 0.938 | 0.15 | OK |  | 0.167 |
| Table | Cell Accuracy | 0.965 | 0.25 | OK | 정규화 후 값 일치 | 0.278 |
| Table | Merged Cell Accuracy |  | 0.1 | N/A | 마크다운 GT 표현 불가 | 0.0 |
| Layout | ── Layout Score (100점) | 92.6 | 0.3 | OK | 영역 합산 | 0.3 |
| Hierarchy | ── Hierarchy Score (100점) | 85.6 | 0.3 | OK | 영역 합산 | 0.3 |
| Table | ── Table Score (100점) | 89.6 | 0.4 | OK | 영역 합산 | 0.4 |

```text
+--------------------------------------+
|       DOCLING PARSING QUALITY        |
+--------------------------------------+
| Layout Analysis       :   92.6 / 100 |
| Text Hierarchy        :   85.6 / 100 |
| Table Structure       :   89.6 / 100 |
|                                      |
| Overall Score         :   89.3 / 100 |
+--------------------------------------+
```

## 7. 오류 사례

| Error Type | Count |
|---|---|
| OCR/Text Error | 161 |
| Layout Extra | 51 |
| Layout Error | 32 |
| Heading Extra | 31 |
| Parent-Child Error | 30 |
| Cell Content Error | 27 |
| Table Detection Error | 16 |
| Row/Column Error | 13 |
| Layout Missing | 12 |
| Heading Missing | 11 |
| Document Order Error | 9 |
| Heading Level Error | 8 |
| Text Mismatch | 6 |
| Heading Text Mismatch | 6 |
| Header Error | 2 |

| Area | Error Type | Document | Page | Expected | Detected |
|---|---|---|---|---|---|
| Layout | Text Mismatch | 법인카드_사용규정 | 2 | 제2조 (정의) | 제2조 (정의) 개정 v1.1 |
| Layout | Layout Missing | 법인카드_사용규정 |  | [List] 항목 구분이 모호한 건은 리스크 리뷰어가 1차 분류하되, 최종 항목 확정은 재무회계팀 및 관리자가 수행하며 시스템은 참고 정보만 제공한다. | (없음) |
| Layout | Layout Extra | 법인카드_사용규정 | 1 | (없음) | [Text] 개정이력 v1.0 제정 (조문 정합성 검토 반영) / v1.1 개정: 제2조 관리자 정의 정비, 제10조 사전승인 예외절차 신 설, 별표1 이사 겸직·대행 시 한도 적용기준 명확화 |
| Layout | Layout Extra | 법인카드_사용규정 | 3 | (없음) | [List] 인을 받아 개인 카드를 발급받을 수 있다. |
| Layout | Layout Extra | 법인카드_사용규정 | 3 | (없음) | [Text] 원본부에 서면(이메일 포함)으로 보고하여야 한다. |
| Layout | Layout Extra | 법인카드_사용규정 | 5 | (없음) | [List] 지원본부에 경보를 발생시킨다. |
| Layout | Layout Extra | 법인카드_사용규정 | 6 | (없음) | [List] 하며 시스템은 참고 정보만 제공한다. |
| Layout | Layout Missing | 부서소개 |  | [Text] 총 16개 부서(15개 부/실 + 감사실), 27개 팀으로 구성된다. | (없음) |
| Layout | Layout Extra | 부서소개 | 1 | (없음) | [Heading] 부서 소개 |
| Layout | Layout Extra | 부서소개 | 1 | (없음) | [Text] 내 부 참 고 문 서 |
| Layout | Layout Extra | 부서소개 | 4 | (없음) | [Table] <table 2x5> |
| Layout | Layout Extra | 부서소개 | 5 | (없음) | [Table] <table 6x3> |
| Layout | Text Mismatch | 업무추진비_사용규정 | 2 | 제2조 (정의) | 제2조 (정의) 개정 v1.2 |
| Layout | Layout Missing | 업무추진비_사용규정 |  | [Heading] 제6조 (사용 승인) | (없음) |
| Layout | Layout Missing | 업무추진비_사용규정 |  | [Heading] 제7조 (기록 사항) | (없음) |
| Layout | Layout Extra | 업무추진비_사용규정 | 1 | (없음) | [Text] 제정일 |
| Layout | Layout Extra | 업무추진비_사용규정 | 1 | (없음) | [Text] 2026. 7. 20. |
| Layout | Layout Extra | 업무추진비_사용규정 | 1 | (없음) | [Text] 시행일 |
| Layout | Layout Extra | 업무추진비_사용규정 | 1 | (없음) | [Text] 2026. 8. 1. |
| Layout | Layout Extra | 업무추진비_사용규정 | 1 | (없음) | [Text] 소관부서 |
| Layout | Layout Extra | 업무추진비_사용규정 | 1 | (없음) | [Text] 경영지원본부 (재무회계부) |
| Layout | Layout Extra | 업무추진비_사용규정 | 3 | (없음) | [Heading] 제6조 (사용 승인) 개정 v1.3(2026.7.28) |
| Layout | Layout Extra | 업무추진비_사용규정 | 4 | (없음) | [Heading] 제7조 (기록 사항) 개정 v1.3(2026.7.28) |
| Layout | Layout Extra | 조직도 | 1 | (없음) | [Heading] 조직도 |
| Layout | Layout Extra | 조직도 | 1 | (없음) | [Text] 내 부 참 고 문 서 |
| Layout | Layout Extra | 조직도 | 4 | (없음) | [Table] <table 2x2> |
| Layout | Layout Extra | 조직도 | 5 | (없음) | [Table] <table 4x2> |
| Layout | Layout Extra | 조직설계_상세기획서 | 1 | (없음) | [Heading] 조직설계 상세 기획서 |
| Layout | Layout Extra | 조직설계_상세기획서 | 1 | (없음) | [Text] 내 부 참 고 문 서 |
| Layout | Layout Extra | 조직설계_상세기획서 | 6 | (없음) | [Table] <table 7x5> |
| Layout | Layout Extra | 조직설계_상세기획서 | 7 | (없음) | [Table] <table 4x4> |
| Layout | Layout Extra | 조직설계_상세기획서 | 8 | (없음) | [Table] <table 4x4> |
| Layout | Layout Extra | 조직설계_상세기획서 | 9 | (없음) | [Table] <table 3x3> |
| Layout | Layout Extra | 조직설계_상세기획서 | 10 | (없음) | [Table] <table 5x3> |
| Layout | Layout Extra | 조직설계_상세기획서 | 12 | (없음) | [Table] <table 4x2> |
| Layout | Layout Missing | 직급체계 |  | [Text] 국내 IT기업의 일반적 관행에 따라 **직급(연차/근속 기반 호칭)**과 **직책(팀장/부서장/본부장 등 보직)**을 분리 운영한다. | (없음) |
| Layout | Layout Extra | 직급체계 | 1 | (없음) | [Heading] 직급 체계 |
| Layout | Layout Extra | 직급체계 | 1 | (없음) | [Text] 내 부 참 고 문 서 |
| Layout | Layout Extra | 직급체계 | 3 | (없음) | [Table] <table 5x4> |
| Layout | Text Mismatch | 출장비_사용규정 | 5 | 별표 1. 국내출장 여비 정액 기준 | 별표 1. 국내출장 여비 정액 기준 개정 v1.1(2026.7.28) |
| … 외 375행 | | | | | |

## 8. 정성 평가

| Category | Evaluation Item | Auto Metric | Result | Comment |
|---|---|---|---|---|
| Layout | 영역 탐지(요소 누락/오탐) | 0.929 | PASS | F1=0.929 / 누락 12건 |
| Layout | 요소 타입 분류 | 0.923 | PASS | 정확도=0.923 |
| Layout | Bounding Box 정확도 |  | REVIEW | GT 좌표 없음 — 육안 검수 필요 |
| Layout | 머리말/꼬리말 분리 |  | REVIEW | docling이 furniture로 분리한 요소 147건 — 육안 확인 |
| Hierarchy | 헤딩 탐지 | 0.844 | WARN | F1=0.844 |
| Hierarchy | 헤딩 레벨(H1/H2/H3) 구분 | 0.93 | PASS | offset 보정=0.930, strict=0.149 |
| Hierarchy | 부모-자식 관계 | 0.737 | FAIL | 정확도=0.737 |
| Hierarchy | 문서 순서(리딩오더) | 0.921 | PASS | 정확도=0.921 |
| Table | 표 탐지 | 0.928 | PASS | F1=0.928 / 분할 11건 |
| Table | 행/열 복원 | 0.797 | WARN | row=0.594, col=1.000 |
| Table | 헤더 인식 | 0.938 | PASS | 정확도=0.938 |
| Table | 셀 값 정확도 | 0.965 | PASS | loose=0.965, strict=0.755 |
| Table | 병합 셀 |  | REVIEW | 마크다운 GT로 판정 불가 — 원본 PDF와 육안 대조 필요 |
| Text | 공백·자간 결함 |  | REVIEW | 공백만 다른 셀 161건 — CJK 양끝맞춤 조판 유래 |

> `Result`는 자동 지표 기반 **제안값**이다. 최종 판정은 `qualitative_review.csv`에서 평가자가 수정한다.

## 9. 종합 결과

```text
==================================================
        DOCLING PARSING EVALUATION
==================================================
Documents scored : 8  (GT: tiger_inc/md)
Documents N/A    : 3  (no ground truth)

[1] Layout Analysis
--------------------------------------------------
Element Detection F1  : 0.93
Element Type Accuracy : 0.92
Bounding Box IoU      : N/A  (no GT coordinates)
Layout Score          : 92.6 / 100

[2] Text Hierarchy
--------------------------------------------------
Heading Detection F1  : 0.84
Heading Level (offset): 0.93   (strict: 0.15)
Parent-Child Relation : 0.74
Document Order        : 0.92
Hierarchy Score       : 85.6 / 100

[3] Table Structure
--------------------------------------------------
Table Detection F1    : 0.93
Row Accuracy          : 0.59
Column Accuracy       : 1.00
Header Accuracy       : 0.94
Cell Accuracy         : 0.96   (strict: 0.76)
Merged Cell Accuracy  : N/A  (not expressible in MD GT)
Table Score           : 89.6 / 100

==================================================
OVERALL SCORE : 89.3 / 100
==================================================
```

## 10. 개선이 필요한 부분

- **Hierarchy / Heading Detection F1** = 0.844 — 개선 필요
- **Hierarchy / Parent-Child Accuracy** = 0.737 — 개선 필요
- **Table / Row Accuracy** = 0.594 — 개선 필요
- **공백·자간 결함** 161건 — CJK 양끝맞춤 조판 유래. 청크 임베딩 전 공백 재결합 후처리 필요
- **표 분할** 11건 — 페이지 경계에서 표가 쪼개짐. 인접 페이지 동일 열 구조 표 병합 후처리 필요
