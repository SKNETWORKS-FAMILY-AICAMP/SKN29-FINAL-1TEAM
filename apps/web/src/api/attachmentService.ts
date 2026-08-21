// 증빙 첨부 서비스 — **업로드가 곧 판독 트리거**다.
//
// 서버가 파일을 받으면 커밋 직후 비전 판독(`/agent/extract-evidence`)을 돌린다. 판독은
// 수십 초 걸리므로 업로드 응답의 `extractionStatus`는 대개 `PENDING`/`RUNNING`이다 →
// 화면이 목록을 폴링해 `DONE`/`FAILED`/`SKIPPED`가 되는 걸 지켜본다(규정 문서 적재와 같은 방식).
//
// 추출 결과(`extracted`)는 **EvalContext dot-path → 값**이다. 요약해서 보여주지 않는다 —
// 그 경로가 곧 판정이 읽는 자리라, 사람이 대조할 수 있어야 한다.
import { endpoints } from './client'

export type AttachmentKind =
  | 'RECEIPT' | 'PRE_APPROVAL' | 'MEETING_MINUTES'
  | 'PARTICIPANT_LIST' | 'TRIP_PLAN' | 'CONTRACT' | 'OTHER'

export type ExtractionStatus = 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED' | 'SKIPPED'

export interface Attachment {
  id: number
  kind: AttachmentKind
  kindLabel: string
  originalName: string
  mimeType: string
  uploadedAt: string
  extractionStatus: ExtractionStatus
  extractionStatusLabel: string
  /** EvalContext dot-path → 값. 경로가 **있으면** 관측한 것, 없으면 안 본 것이다. */
  extracted: Record<string, unknown>
  fieldConfidence: Record<string, number>
  evidenceSpans: unknown[]
  extractorVersion: string
  extractedAt: string | null
  error: string
}

/** 첨부 종류 선택지 — 종류가 "무엇을 뽑을지"를 정한다(서버 `TARGETS`). */
export const ATTACHMENT_KINDS: { value: AttachmentKind; label: string; extracts: string }[] = [
  { value: 'RECEIPT', label: '영수증·카드전표', extracts: '금액·가맹점·품목 → 주류 포함 여부, 지출 세부유형' },
  { value: 'PRE_APPROVAL', label: '사전승인 문서(결재)', extracts: '사전승인 여부' },
  { value: 'MEETING_MINUTES', label: '회의록', extracts: '참석 인원·외부 인원·청탁금지 대상' },
  { value: 'PARTICIPANT_LIST', label: '참석자 명단', extracts: '참석 인원·외부 인원·청탁금지 대상' },
  { value: 'TRIP_PLAN', label: '출장계획서', extracts: '출장 구분·지역등급·1박 숙박비' },
  { value: 'CONTRACT', label: '계약서·견적서', extracts: '추출 대상 아님(보관만)' },
  { value: 'OTHER', label: '기타', extracts: '추출 대상 아님(보관만)' },
]

/** 판독이 아직 끝나지 않은 상태 — 폴링을 계속할지 판단하는 기준. */
export const IN_PROGRESS: ExtractionStatus[] = ['PENDING', 'RUNNING']

export async function fetchAttachments(settlementId: string): Promise<Attachment[]> {
  const { data } = await endpoints.settlementAttachments(settlementId)
  return data ?? []
}

export async function uploadAttachment(
  settlementId: string, file: File, kind: AttachmentKind,
): Promise<Attachment> {
  const form = new FormData()
  form.append('file', file)
  form.append('kind', kind)
  const { data } = await endpoints.uploadAttachment(settlementId, form)
  return data
}

export async function deleteAttachment(settlementId: string, attachmentId: number): Promise<void> {
  await endpoints.deleteAttachment(settlementId, attachmentId)
}

/** 판독 재시도 — ai가 안 떠 있었거나 타임아웃으로 FAILED가 된 건. */
export async function reextractAttachment(settlementId: string, attachmentId: number): Promise<Attachment> {
  const { data } = await endpoints.reextractAttachment(settlementId, attachmentId)
  return data
}

/** dot-path를 사람이 읽는 라벨로. 모르는 경로는 **경로 그대로** 보여준다(감추면 대조가 안 된다). */
export const FACT_LABEL: Record<string, string> = {
  'approval.pre_approval_obtained': '사전승인 여부',
  'participants.participant_count': '참석 인원',
  'participants.external_participant_count': '외부 참석 인원',
  'participants.has_kickback_law_target': '청탁금지 대상자 참석',
  'trip.trip_type': '출장 구분',
  'trip.region_grade': '지역 등급',
  'trip.lodging_amount_per_night': '1박 숙박비',
  'category.item_type': '지출 세부유형',
  'dining.includes_alcohol': '주류 포함',
  'dining.is_secondary_venue': '2차 결제',
  'evidence.has_valid_receipt': '적격증빙',
}

export function formatFactValue(value: unknown): string {
  if (value === true) return '예'
  if (value === false) return '아니오'
  if (value === null || value === undefined) return '-'
  if (typeof value === 'number') return value.toLocaleString('ko-KR')
  return String(value)
}
