# 부가가치세법 후처리 검수 요약

| 항목 | 값 |
|---|---|
| 문서 | 부가가치세법 |
| 페이지 | 35 |
| 요소 | 662 |
| steps | R4+R5+R1 |
| R1_reordered | 16 |
| R2_markers_restored | 0 |
| R3_items_merged | 0 |
| R3_items_dropped | 0 |
| R4_texts_rejoined | 228 |
| R4_unmatched | 54 |
| R5_letter_spacing | 0 |
| R6_items_split | 0 |
| 줄바꿈_판정 | 581 |
| 근거없음(weak) | 162 |
| weak_비율 | 28% |
| vocab | 10825 |

## 줄바꿈 판정 규칙 분포

| 규칙 | 신뢰도 | 건수 |
|---|---|---|
| vocab-joined | strong | 208 |
| length | weak | 153 |
| vocab-split | strong | 142 |
| vocab-freq | strong | 31 |
| non-hangul | - | 17 |
| bound-prefix | strong | 14 |
| bound-exact | weak | 9 |
| bracket | strong | 7 |

## 검수 순서

1. `merges.csv` — R3가 별개 조문·목을 붙였는지. **법령은 여기서 오작동이 확인됨.**
2. `linebreaks_weak.csv` — 근거 없이 찍은 줄바꿈 판정. `decision`이 맞는지.
3. `unmatched.csv` — 원본 대조에 실패해 R4가 손대지 못한 요소.
4. `result.md` — 최종 텍스트를 원문 PDF와 나란히 놓고 확인.
