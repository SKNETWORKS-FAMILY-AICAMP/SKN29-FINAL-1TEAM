# 부가가치세법 후처리 검수 요약

| 항목 | 값 |
|---|---|
| 문서 | 부가가치세법 |
| 페이지 | 35 |
| 요소 | 547 |
| steps | R2+R3+R4+R5+R6+R1 |
| R1_reordered | 298 |
| R2_markers_restored | 1 |
| R3_items_merged | 115 |
| R3_items_dropped | 115 |
| R4_texts_rejoined | 234 |
| R4_unmatched | 54 |
| R5_letter_spacing | 0 |
| R6_items_split | 0 |
| 줄바꿈_판정 | 696 |
| 근거없음(weak) | 188 |
| weak_비율 | 27% |
| vocab | 10825 |

## 줄바꿈 판정 규칙 분포

| 규칙 | 신뢰도 | 건수 |
|---|---|---|
| vocab-joined | strong | 217 |
| vocab-split | strong | 186 |
| length | weak | 175 |
| non-hangul | - | 52 |
| vocab-freq | strong | 32 |
| bound-prefix | strong | 14 |
| bound-exact | weak | 13 |
| bracket | strong | 7 |

## 검수 순서

1. `merges.csv` — R3가 별개 조문·목을 붙였는지. **법령은 여기서 오작동이 확인됨.**
2. `linebreaks_weak.csv` — 근거 없이 찍은 줄바꿈 판정. `decision`이 맞는지.
3. `unmatched.csv` — 원본 대조에 실패해 R4가 손대지 못한 요소.
4. `result.md` — 최종 텍스트를 원문 PDF와 나란히 놓고 확인.
