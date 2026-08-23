// S-09 「회수/중지 필요 카드」 — **시연용 목업 데이터.**
//
//  ⚠️ 이 파일은 진짜 판정이 아니다. 실 API(`GET /api/cards/attention/`)가 내는 사유는 둘뿐이고
//  (퇴사 `RETIRED_OWNER` · 반복 이상사용 `REPEAT_ANOMALY`), 분실신고·휴직·장기미사용은 그 사실을
//  담는 자리가 도메인에 아직 없다(카드 분실 신고 접수·인사 휴직 연동 미구현). 서버가 만들어낼 수
//  없는 값이라 화면 구조와 조치 흐름을 먼저 보여주기 위한 대역이고, 해당 사실이 도메인에 들어오면
//  이 파일째 걷어내고 서버 응답을 그대로 그린다.
//
//  그래서 이 값은 **화면에 「시연용 예시 데이터」라고 밝히고** 쓴다 — 회수는 되돌릴 수 없는
//  결정이라, 근거가 가짜인 줄 모르고 누르는 상황을 만들면 안 된다. 같은 이유로 여기서 누르는
//  회수/정지는 서버로 나가지 않는다(화면 안에서만 「조치 완료」로 바뀐다).
//
//  기준일은 2026-08-23 고정이고 경과일도 함께 박아 둔다 — 런타임에 계산하면 시연할 때마다
//  숫자가 흔들려서 캡처와 화면이 어긋난다.

export type AttentionReason =
  | 'RETIRED_OWNER'      // 퇴사 처리
  | 'LOST_REPORTED'      // 분실·도난 신고
  | 'REPEAT_ANOMALY'     // 반복 이상사용
  | 'LEAVE_OF_ABSENCE'   // 휴직·장기 파견
  | 'DORMANT'            // 장기 미사용

/** 조치 시급도 — 색과 정렬 순서를 정한다. */
export type AttentionSeverity = 'URGENT' | 'WATCH' | 'HOLD'

export interface AttentionMockCard {
  id: number
  reason: AttentionReason
  severity: AttentionSeverity
  /** 마스킹 카드번호 */
  number: string
  name: string
  typeLabel: string
  assignee: string
  team: string
  /** 왜 조치 대상인지 — 한 문장 */
  note: string
  /** 근거 날짜. 라벨은 사유마다 다르다(퇴사일 / 신고일 / 감지일 …). */
  dateLabel: string
  date: string
  elapsedDays: number
  lastUsedAt: string
  lastUsedAmount: number
  monthUsage: number
  limit: number
  /** 권장 조치 — 결정은 사람이 한다. 화면은 추천만 한다. */
  recommend: string
}

export const SEVERITY_META: Record<AttentionSeverity, { label: string; tone: string; bg: string }> = {
  URGENT: { label: '즉시 조치', tone: 'var(--tone-red)', bg: 'var(--tone-red-bg)' },
  WATCH: { label: '확인 필요', tone: 'var(--tone-amber)', bg: 'var(--tone-amber-bg)' },
  HOLD: { label: '보류 검토', tone: 'var(--tone-gray)', bg: 'var(--tone-gray-bg)' },
}

export const REASON_META: Record<AttentionReason, { label: string; tone: string; bg: string; desc: string }> = {
  RETIRED_OWNER: {
    label: '퇴사 처리',
    tone: 'var(--tone-red)',
    bg: 'var(--tone-red-bg)',
    desc: '퇴사 처리된 임직원에게 배정된 개인카드',
  },
  LOST_REPORTED: {
    label: '분실·도난 신고',
    tone: 'var(--tone-orange)',
    bg: 'var(--tone-orange-bg)',
    desc: '분실 또는 도난이 신고 접수된 카드',
  },
  REPEAT_ANOMALY: {
    label: '반복 이상사용',
    tone: 'var(--tone-amber)',
    bg: 'var(--tone-amber-bg)',
    desc: '최근 30일 내 같은 패턴의 결제가 반복 감지된 카드',
  },
  LEAVE_OF_ABSENCE: {
    label: '휴직·장기 파견',
    tone: 'var(--tone-blue)',
    bg: 'var(--tone-blue-bg)',
    desc: '휴직·파견으로 당분간 사용 계획이 없는 카드',
  },
  DORMANT: {
    label: '장기 미사용',
    tone: 'var(--tone-gray)',
    bg: 'var(--tone-gray-bg)',
    desc: '4개월 이상 결제 이력이 없는 카드',
  },
}

/** 사유 표시 순서(= 시급한 것부터). */
export const REASON_ORDER: AttentionReason[] = [
  'RETIRED_OWNER', 'LOST_REPORTED', 'REPEAT_ANOMALY', 'LEAVE_OF_ABSENCE', 'DORMANT',
]

export const ATTENTION_MOCK: AttentionMockCard[] = [
  {
    id: -101,
    reason: 'RETIRED_OWNER',
    severity: 'URGENT',
    number: '**** 1042',
    name: '김성호 개인카드',
    typeLabel: '개인카드',
    assignee: '김성호',
    team: '영업팀',
    note: '퇴사 처리 완료 — 카드 회수 및 사용 정지가 필요합니다.',
    dateLabel: '퇴사일',
    date: '2026-07-31',
    elapsedDays: 23,
    lastUsedAt: '2026-07-29',
    lastUsedAmount: 84_000,
    monthUsage: 0,
    limit: 1_500_000,
    recommend: '즉시 회수 · 미정산 3건 확인',
  },
  {
    id: -102,
    reason: 'RETIRED_OWNER',
    severity: 'URGENT',
    number: '**** 1088',
    name: '한지우 개인카드',
    typeLabel: '개인카드',
    assignee: '한지우',
    team: 'AI·개발팀',
    note: '퇴사 처리 완료 — 퇴사일 이후 결제 1건이 확인됩니다.',
    dateLabel: '퇴사일',
    date: '2026-08-14',
    elapsedDays: 9,
    lastUsedAt: '2026-08-17',
    lastUsedAmount: 132_500,
    monthUsage: 246_800,
    limit: 1_500_000,
    recommend: '즉시 회수 · 퇴사 후 결제 건 소명 요청',
  },
  {
    id: -103,
    reason: 'LOST_REPORTED',
    severity: 'URGENT',
    number: '**** 7013',
    name: '영업팀 예비 팀카드',
    typeLabel: '팀카드',
    assignee: '영업팀 (이팀장 보관)',
    team: '영업팀',
    note: '분실 신고 접수 — 신고 이후 승인 시도 2건이 차단되었습니다.',
    dateLabel: '신고일',
    date: '2026-08-20',
    elapsedDays: 3,
    lastUsedAt: '2026-08-19',
    lastUsedAmount: 268_000,
    monthUsage: 1_142_000,
    limit: 5_000_000,
    recommend: '사용 정지 · 카드사 재발급 신청',
  },
  {
    id: -104,
    reason: 'LOST_REPORTED',
    severity: 'URGENT',
    number: '**** 2031',
    name: '윤도현 개인카드',
    typeLabel: '개인카드',
    assignee: '윤도현',
    team: '재무회계팀',
    note: '도난 의심 — 해외 가맹점 승인 시도가 연속 감지되어 본인이 신고했습니다.',
    dateLabel: '신고일',
    date: '2026-08-22',
    elapsedDays: 1,
    lastUsedAt: '2026-08-21',
    lastUsedAmount: 47_300,
    monthUsage: 512_400,
    limit: 1_500_000,
    recommend: '사용 정지 · 부정사용 이의제기 접수',
  },
  {
    id: -105,
    reason: 'REPEAT_ANOMALY',
    severity: 'WATCH',
    number: '**** 5104',
    name: '재무회계팀 팀카드',
    typeLabel: '팀카드',
    assignee: '재무회계팀',
    team: '재무회계팀',
    note: '최근 30일 내 동일 가맹점(스타벅스 역삼점) 14회 결제가 감지되었습니다.',
    dateLabel: '감지일',
    date: '2026-08-23',
    elapsedDays: 0,
    lastUsedAt: '2026-08-22',
    lastUsedAmount: 28_600,
    monthUsage: 2_884_000,
    limit: 5_000_000,
    recommend: '사용 목적 소명 요청 후 판단',
  },
  {
    id: -106,
    reason: 'REPEAT_ANOMALY',
    severity: 'WATCH',
    number: '**** 9107',
    name: 'AI·개발팀 팀카드',
    typeLabel: '팀카드',
    assignee: 'AI·개발팀',
    team: 'AI·개발팀',
    note: '심야(22시 이후) 결제 7회 · 주말 결제 5회가 한 달 안에 반복되었습니다.',
    dateLabel: '감지일',
    date: '2026-08-21',
    elapsedDays: 2,
    lastUsedAt: '2026-08-20',
    lastUsedAmount: 191_000,
    monthUsage: 3_310_500,
    limit: 5_000_000,
    recommend: '팀장 확인 요청 · 회수는 보류',
  },
  {
    id: -107,
    reason: 'LEAVE_OF_ABSENCE',
    severity: 'WATCH',
    number: '**** 1015',
    name: '최민서 개인카드',
    typeLabel: '개인카드',
    assignee: '최민서',
    team: '영업팀',
    note: '육아휴직(2026-08-01 ~ 2027-01-31) — 복직 전까지 사용 계획이 없습니다.',
    dateLabel: '휴직 시작일',
    date: '2026-08-01',
    elapsedDays: 22,
    lastUsedAt: '2026-07-28',
    lastUsedAmount: 62_400,
    monthUsage: 0,
    limit: 1_500_000,
    recommend: '일시 정지 · 복직 시 재활성',
  },
  {
    id: -108,
    reason: 'DORMANT',
    severity: 'HOLD',
    number: '**** 3312',
    name: '영업팀 선불카드',
    typeLabel: '선결제',
    assignee: '영업팀',
    team: '영업팀',
    note: '6개월 이상 결제 이력이 없습니다 — 잔액 ₩380,000이 묶여 있습니다.',
    dateLabel: '마지막 사용일',
    date: '2026-02-11',
    elapsedDays: 194,
    lastUsedAt: '2026-02-11',
    lastUsedAmount: 55_000,
    monthUsage: 0,
    limit: 1_000_000,
    recommend: '잔액 회수 후 카드 반납',
  },
  {
    id: -109,
    reason: 'DORMANT',
    severity: 'HOLD',
    number: '**** 5521',
    name: '경영지원본부 공용카드',
    typeLabel: '공용',
    assignee: '경영지원본부',
    team: '재무회계팀',
    note: '4개월 이상 결제 이력이 없고 보관자가 지정되어 있지 않습니다.',
    dateLabel: '마지막 사용일',
    date: '2026-04-03',
    elapsedDays: 142,
    lastUsedAt: '2026-04-03',
    lastUsedAmount: 118_000,
    monthUsage: 0,
    limit: 6_000_000,
    recommend: '보관자 지정 또는 반납',
  },
]

export const ATTENTION_MOCK_TOTAL = ATTENTION_MOCK.length
