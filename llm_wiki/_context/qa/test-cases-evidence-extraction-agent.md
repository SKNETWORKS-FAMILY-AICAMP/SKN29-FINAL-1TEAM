# 증빙자료 추출 Agent QA — 테스트 케이스 50건

모두 **synthetic**(이 QA 세션에서 PIL로 직접 생성한 이미지)이다. 실행 시점 DB에 실 `Attachment` 레코드가 0건이라(`Attachment.objects.count() == 0`), 재사용 가능한 실사용 이력 파일이 없었다. 대신 파일을 core↔ai 공유 media 볼륨(`attachments/qa/`)에 직접 배치하고 `/lab/extract/run`을 `fileRef`+`kind`로 직접 호출했다(이 엔드포인트는 `Attachment` DB 행을 요구하지 않는다 — `apps/ai/app/api/lab.py::extract_run` 참조). 정식 `POST /api/settlements/{id}/attachments/` multipart 업로드 왕복은 이번 라운드에서 생략했다(같은 파일을 두 번 비전 호출에 태우는 비용 중복을 피하기 위함) — 결과 해석에 영향 없음: 판독 로직 자체(`app.vision.read_receipt`/`read_evidence_document`)는 파일 출처와 무관하게 동일하게 동작한다.

생성 스크립트: `gen_cases.py`(세션 스크래치패드). 실제 이미지 파일: media 볼륨 `attachments/qa/*.png` (51개: 이미지 50 + manifest.json).

| ID | kind | 파일 | 품질등급 | golden 기대값 | 비고/의도 |
|---|---|---|---|---|---|
| R01 | RECEIPT | `attachments/qa/receipt_R01.png` | clean | `category.item_type`='식사'; `dining.includes_alcohol`=True; `tx.payment_time`='19:32' | clean, alcohol present (소주/맥주), time printed |
| R02 | RECEIPT | `attachments/qa/receipt_R02.png` | clean | `category.item_type`='식사'; `dining.includes_alcohol`=False; `tx.payment_time`='12:15' | clean, line items visible, explicitly no alcohol -> false (observed absence) |
| R03 | RECEIPT | `attachments/qa/receipt_R03.png` | field-absent | `category.item_type`=None; `dining.includes_alcohol`=None; `tx.payment_time`=None | no line items shown at all -> facts should be OMITTED not guessed |
| R04 | RECEIPT | `attachments/qa/receipt_R04.png` | clean | `category.item_type`='선물'; `dining.includes_alcohol`=None; `tx.payment_time`='15:00' | gift receipt, no dining items -> includes_alcohol should be absent |
| R05 | RECEIPT | `attachments/qa/receipt_R05.png` | clean | `category.item_type`='경조사'; `dining.includes_alcohol`=None; `tx.payment_time`=None | condolence flower receipt |
| R06 | RECEIPT | `attachments/qa/receipt_R06.png` | clean | `category.item_type`='식사'; `dining.includes_alcohol`=False; `tx.payment_time`='11:50'; `participants.participant_count`=4 | explicit participant count printed on receipt |
| R07 | RECEIPT | `attachments/qa/receipt_R07.png` | ambiguous | `category.item_type`='식사'; `dining.includes_alcohol`=True; `tx.payment_time`='23:10' | heavily blurred receipt, alcohol word barely legible -> expect lower confidence or omission |
| R08 | RECEIPT | `attachments/qa/receipt_R08.png` | clean | `category.item_type`='식사'; `dining.includes_alcohol`=True; `tx.payment_time`='20:45' | clean, multiple alcohol items |
| R09 | RECEIPT | `attachments/qa/receipt_R09.png` | clean | `category.item_type`=None; `dining.includes_alcohol`=False; `tx.payment_time`='09:05' | convenience store, clearly no alcohol, item_type ambiguous(기타/식사) -> allow model discretion, time should extract |
| R10 | RECEIPT | `attachments/qa/receipt_R10.png` | ambiguous | `category.item_type`='식사'; `dining.includes_alcohol`=True; `tx.payment_time`='18:20' | bottom half torn/cut off image but visible portion has alcohol -> should still extract from visible part |
| R11 | RECEIPT | `attachments/qa/receipt_R11.png` | clean | `category.item_type`='식사'; `dining.includes_alcohol`=False; `tx.payment_time`='19:00' | meat restaurant but only soft drinks listed, no alcohol -> false expected, tests against stereotype bias |
| R12 | RECEIPT | `attachments/qa/receipt_R12.png` | field-absent | `category.item_type`=None; `dining.includes_alcohol`=None; `tx.payment_time`=None | garbage/numeric only receipt, no interpretable korean text -> everything absent |
| R13 | RECEIPT | `attachments/qa/receipt_R13.png` | clean | `category.item_type`='식사'; `dining.includes_alcohol`=True; `tx.payment_time`='21:30' | mixed alcohol + soda, alcohol present |
| R14 | RECEIPT | `attachments/qa/receipt_R14.png` | clean | `category.item_type`='식사'; `dining.includes_alcohol`=None; `tx.payment_time`='18:00'; `participants.participant_count`=10 | large banquet, explicit headcount=10, no alcohol items shown |
| R15 | RECEIPT | `attachments/qa/receipt_R15.png` | clean | `category.item_type`='식사'; `dining.includes_alcohol`=False; `tx.payment_time`='14:00' | adversarial: memo text mentions '회의' but no meeting-minutes fields exist for RECEIPT kind (schema enforces) -> should not affect output shape |
| P01 | PRE_APPROVAL | `attachments/qa/approval_P01.png` | clean | `approval.pre_approval_obtained`=True | clean, both approval stamps present with dates -> true |
| P02 | PRE_APPROVAL | `attachments/qa/approval_P02.png` | clean | `approval.pre_approval_obtained`=False | explicit rejection stamp -> false |
| P03 | PRE_APPROVAL | `attachments/qa/approval_P03.png` | clean | `approval.pre_approval_obtained`=False | draft only, no approval stamp/signature -> false |
| P04 | PRE_APPROVAL | `attachments/qa/approval_P04.png` | clean | `approval.pre_approval_obtained`=False | pending status, no approvals yet -> false |
| P05 | PRE_APPROVAL | `attachments/qa/approval_P05.png` | clean | `approval.pre_approval_obtained`=True | single-level full delegation approval (전결) -> true |
| P06 | PRE_APPROVAL | `attachments/qa/approval_P06.png` | ambiguous | `approval.pre_approval_obtained`=True | stamp text present but heavily blurred -> should still lean true with LOWER confidence, or ambiguous |
| P07 | PRE_APPROVAL | `attachments/qa/approval_P07.png` | ambiguous | `approval.pre_approval_obtained`=None | approval seal/signature area cropped out of the image on the right edge -> should be low-confidence or omitted (not confidently true) |
| P08 | PRE_APPROVAL | `attachments/qa/approval_P08.png` | clean | `approval.pre_approval_obtained`=False | partial approval only (1st line approved, 2nd pending) -> overall not fully approved -> false |
| P09 | PRE_APPROVAL | `attachments/qa/approval_P09.png` | clean | `approval.pre_approval_obtained`=True | electronic approval system screenshot, status=완료 across full chain -> true |
| P10 | PRE_APPROVAL | `attachments/qa/approval_P10.png` | clean | `approval.pre_approval_obtained`=False | blank template, no approval marks anywhere -> false (observed absence) |
| P11 | PRE_APPROVAL | `attachments/qa/approval_P11.png` | clean | `approval.pre_approval_obtained`=True | adversarial: mentions lodging amount (a TRIP_PLAN-only field) inside a PRE_APPROVAL doc -> schema should prevent trip.lodging_amount_per_night from appearing; approval field should still extract true |
| P12 | PRE_APPROVAL | `attachments/qa/approval_P12.png` | clean | `approval.pre_approval_obtained`=True | signature only, no stamp -> true |
| M01 | MEETING_MINUTES | `attachments/qa/minutes_M01.png` | clean | `participants.participant_count`=5; `participants.external_participant_count`=0; `participants.has_kickback_law_target`=False | clean, 5 internal attendees explicitly listed |
| M02 | MEETING_MINUTES | `attachments/qa/minutes_M02.png` | clean | `participants.participant_count`=8; `participants.external_participant_count`=2; `participants.has_kickback_law_target`=False | 8 total, 2 external vendor reps |
| M03 | MEETING_MINUTES | `attachments/qa/minutes_M03.png` | clean | `participants.participant_count`=4; `participants.external_participant_count`=1; `participants.has_kickback_law_target`=True | includes a journalist -> kickback law target true |
| M04 | MEETING_MINUTES | `attachments/qa/minutes_M04.png` | clean | `participants.participant_count`=3; `participants.external_participant_count`=1; `participants.has_kickback_law_target`=True | includes a school teacher -> kickback law target true |
| M05 | MEETING_MINUTES | `attachments/qa/minutes_M05.png` | field-absent | `participants.participant_count`=None; `participants.external_participant_count`=None; `participants.has_kickback_law_target`=None | no attendee list at all, only agenda/discussion -> all participant fields should be OMITTED |
| M06 | MEETING_MINUTES | `attachments/qa/minutes_M06.png` | clean | `participants.participant_count`=6; `participants.external_participant_count`=0; `participants.has_kickback_law_target`=False | ADVERSARIAL: mentions trip destination/region grade/lodging cost inside meeting minutes -> must NOT produce trip.* fields (kind=MEETING_MINUTES schema doesn't allow them). Only participant fields expected. |
| M07 | MEETING_MINUTES | `attachments/qa/minutes_M07.png` | clean | `participants.participant_count`=4; `participants.external_participant_count`=0; `participants.has_kickback_law_target`=False | explicit 'no external attendees' statement -> external=0 confidently |
| M08 | MEETING_MINUTES | `attachments/qa/minutes_M08.png` | ambiguous | `participants.participant_count`=None; `participants.external_participant_count`=None; `participants.has_kickback_law_target`=None | handwritten-style vague notes, count not determinable -> omit rather than guess |
| M09 | MEETING_MINUTES | `attachments/qa/minutes_M09.png` | clean | `participants.participant_count`=5; `participants.external_participant_count`=1; `participants.has_kickback_law_target`=True | civil servant attendee -> kickback true |
| M10 | MEETING_MINUTES | `attachments/qa/minutes_M10.png` | clean | `participants.participant_count`=10; `participants.external_participant_count`=3; `participants.has_kickback_law_target`=False | table-like large group, 3 external contractors |
| PL01 | PARTICIPANT_LIST | `attachments/qa/plist_PL01.png` | clean | `participants.participant_count`=5; `participants.external_participant_count`=0; `participants.has_kickback_law_target`=False | 5 internal attendees, clean list |
| PL02 | PARTICIPANT_LIST | `attachments/qa/plist_PL02.png` | clean | `participants.participant_count`=7; `participants.external_participant_count`=3; `participants.has_kickback_law_target`=False | 7 total, 3 external clearly marked |
| PL03 | PARTICIPANT_LIST | `attachments/qa/plist_PL03.png` | clean | `participants.participant_count`=4; `participants.external_participant_count`=1; `participants.has_kickback_law_target`=True | press attendee present -> kickback true |
| PL04 | PARTICIPANT_LIST | `attachments/qa/plist_PL04.png` | ambiguous | `participants.participant_count`=None; `participants.external_participant_count`=None; `participants.has_kickback_law_target`=None | list partially torn off, total count not confidently readable -> omit rather than guess |
| PL05 | PARTICIPANT_LIST | `attachments/qa/plist_PL05.png` | clean | `participants.participant_count`=12; `participants.external_participant_count`=0; `participants.has_kickback_law_target`=False | large internal-only group, count stated directly |
| T01 | TRIP_PLAN | `attachments/qa/trip_T01.png` | clean | `trip.trip_type`='해외'; `trip.region_grade`='A'; `trip.lodging_amount_per_night`=200000 | clean overseas trip, all three fields explicit |
| T02 | TRIP_PLAN | `attachments/qa/trip_T02.png` | clean | `trip.trip_type`='국내'; `trip.region_grade`='나'; `trip.lodging_amount_per_night`=90000 | clean domestic trip |
| T03 | TRIP_PLAN | `attachments/qa/trip_T03.png` | clean | `trip.trip_type`='국내'; `trip.region_grade`=None; `trip.lodging_amount_per_night`=None | day trip, no lodging or region grade mentioned -> both should be omitted, trip_type still extractable |
| T04 | TRIP_PLAN | `attachments/qa/trip_T04.png` | ambiguous | `trip.trip_type`='해외'; `trip.region_grade`=None; `trip.lodging_amount_per_night`=None | region grade and lodging explicitly marked unknown/undetermined -> should be omitted, not guessed |
| T05 | TRIP_PLAN | `attachments/qa/trip_T05.png` | clean | `trip.trip_type`='국내'; `trip.region_grade`='다'; `trip.lodging_amount_per_night`=70000 | ADVERSARIAL: lists 5 meeting attendees inside a trip plan doc -> must NOT emit participants.* (kind=TRIP_PLAN schema doesn't allow those paths). Only trip.* fields expected. |
| CT01 | CONTRACT | `attachments/qa/contract_CT01.png` | n/a | `extraction_status`='SKIPPED' | kind=CONTRACT is not in TARGETS -> expect SKIPPED, no vision call, extracted={}  |
| CT02 | CONTRACT | `attachments/qa/contract_CT02.png` | n/a | `extraction_status`='SKIPPED' | kind=CONTRACT again, different doc content -> still SKIPPED |
| CT03 | OTHER | `attachments/qa/other_CT03.png` | n/a | `extraction_status`='SKIPPED' | kind=OTHER is not in TARGETS -> expect SKIPPED |

## 품질등급 정의

- `clean`: 명확·모호함 없음 — 높은 확신도의 정확한 추출 기대
- `field-absent`: 목표 필드에 대한 근거가 문서에 전혀 없음 — **추출하지 않는 것**(배열에서 생략)이 정답
- `ambiguous`: 필드는 존재하나 흐림/훼손/모호한 표기 — 정확히 추출하되 낮은 confidence, 또는 확신 없으면 생략이 정답
- `n/a`: CONTRACT/OTHER — `TARGETS`에 정의되지 않은 종류라 애초에 추출 대상이 아님(`SKIPPED` 기대)


## 적대적(closed-vocabulary) 케이스

문서 종류와 무관한 화제가 본문에 섞인 경우 해당 kind의 허용 경로 밖 필드를 만들어내는지 시험:

- `M06`(회의록에 출장 지역등급·숙박비 언급) — `trip.*` 유출 여부
- `T05`(출장계획서에 회의 참석자 5명 언급) — `participants.*` 유출 여부
- `P11`(사전승인 문서에 숙박비 언급) — `trip.lodging_amount_per_night` 유출 여부


## `TARGETS` 정본 (참조용, `apps/ai/app/vision/document.py` / `apps/ai/app/vision/receipt.py`)

```
RECEIPT: category.item_type, dining.includes_alcohol, tx.payment_time, participants.participant_count
PRE_APPROVAL: approval.pre_approval_obtained
MEETING_MINUTES: participants.participant_count, participants.external_participant_count, participants.has_kickback_law_target
PARTICIPANT_LIST: 위와 동일 3종
TRIP_PLAN: trip.trip_type, trip.region_grade, trip.lodging_amount_per_night
CONTRACT/OTHER: 정의 없음 → 항상 SKIPPED
```
