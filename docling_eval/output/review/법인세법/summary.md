# 법인세법 후처리 검수 요약

| 항목 | 값 |
|---|---|
| 문서 | 법인세법 |
| 페이지 | 97 |
| 요소 | 1398 |
| steps | R2+R3+R4+R5+R6+R1 |
| R1_reordered | 746 |
| R2_markers_restored | 9 |
| R3_items_merged | 412 |
| R3_items_dropped | 412 |
| R4_texts_rejoined | 646 |
| R4_unmatched | 171 |
| R5_letter_spacing | 0 |
| R6_items_split | 2 |
| 줄바꿈_판정 | 2071 |
| 근거없음(weak) | 574 |
| weak_비율 | 28% |
| vocab | 10825 |

## 줄바꿈 판정 규칙 분포

| 규칙 | 신뢰도 | 건수 |
|---|---|---|
| vocab-joined | strong | 616 |
| length | weak | 533 |
| vocab-split | strong | 481 |
| non-hangul | - | 243 |
| vocab-freq | strong | 90 |
| bound-exact | weak | 36 |
| bound-prefix | strong | 29 |
| bracket | strong | 24 |
| closer | strong | 14 |
| standalone | weak | 5 |

## 검수 순서

1. `merges.csv` — R3가 별개 조문·목을 붙였는지. **법령은 여기서 오작동이 확인됨.**
2. `linebreaks_weak.csv` — 근거 없이 찍은 줄바꿈 판정. `decision`이 맞는지.
3. `unmatched.csv` — 원본 대조에 실패해 R4가 손대지 못한 요소.
4. `result.md` — 최종 텍스트를 원문 PDF와 나란히 놓고 확인.
