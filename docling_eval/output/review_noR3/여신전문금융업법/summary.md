# 여신전문금융업법 후처리 검수 요약

| 항목 | 값 |
|---|---|
| 문서 | 여신전문금융업법 |
| 페이지 | 34 |
| 요소 | 806 |
| steps | R4+R5+R1 |
| R1_reordered | 12 |
| R2_markers_restored | 0 |
| R3_items_merged | 0 |
| R3_items_dropped | 0 |
| R4_texts_rejoined | 170 |
| R4_unmatched | 60 |
| R5_letter_spacing | 0 |
| R6_items_split | 0 |
| 줄바꿈_판정 | 474 |
| 근거없음(weak) | 210 |
| weak_비율 | 44% |
| vocab | 10825 |

## 줄바꿈 판정 규칙 분포

| 규칙 | 신뢰도 | 건수 |
|---|---|---|
| length | weak | 208 |
| vocab-joined | strong | 129 |
| vocab-split | strong | 80 |
| vocab-freq | strong | 20 |
| non-hangul | - | 19 |
| bound-prefix | strong | 7 |
| bracket | strong | 6 |
| closer | strong | 3 |
| bound-exact | weak | 1 |
| standalone | weak | 1 |

## 검수 순서

1. `merges.csv` — R3가 별개 조문·목을 붙였는지. **법령은 여기서 오작동이 확인됨.**
2. `linebreaks_weak.csv` — 근거 없이 찍은 줄바꿈 판정. `decision`이 맞는지.
3. `unmatched.csv` — 원본 대조에 실패해 R4가 손대지 못한 요소.
4. `result.md` — 최종 텍스트를 원문 PDF와 나란히 놓고 확인.
