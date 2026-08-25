"""추가 증빙 첨부와 추출 결과 — `_context/evidence-extraction-agent.md`.

정산 판정에 필요한 사실의 상당수는 사람이 타이핑할 값이 아니라 **증빙 문서 안에 있다**
(사전승인 결재, 회의록의 참석자, 출장계획서의 지역·숙박). `Receipt`는 거래-영수증 매칭 전용이라
종류 구분이 없어 "어느 문서에서 무엇을 뽑을지"를 표현할 수 없었다. 그래서 정산에 붙는
**다종 첨부**를 별도 모델로 둔다.

**이 모듈은 저장 구조(틀)만 정의한다.** 실제 추출은 증빙자료 추출 Agent(FastAPI)가 수행하고
결과를 ``Attachment.extracted``에 써 넣는다. Django는 그 값을 EvalContext로 옮길 뿐,
문서를 직접 읽지 않는다(관계형=Django / 판독=AI 분리 원칙).

핵심 계약 — **관측 여부와 값을 구분한다**:
  · ``extracted``에 경로가 **있으면** 그 사실을 관측한 것이다. 부재를 확인했으면 명시값(0/False)을 쓴다.
  · 경로가 **없으면** 관측하지 않은 것이다 → EvalContext에서 ``None``으로 남고 미해소 가드가 잡는다.
  「관측했는데 없음」과 「안 봤음」을 섞으면 조용한 오판이 다시 생긴다.
"""
from django.conf import settings
from django.db import models


class AttachmentKind(models.TextChoices):
    """첨부의 종류 — 추출 Agent가 "무엇을 뽑을지" 고르는 기준."""
    RECEIPT = "RECEIPT", "영수증·카드전표"
    PRE_APPROVAL = "PRE_APPROVAL", "사전승인 문서(결재)"
    MEETING_MINUTES = "MEETING_MINUTES", "회의록"
    PARTICIPANT_LIST = "PARTICIPANT_LIST", "참석자 명단"
    TRIP_PLAN = "TRIP_PLAN", "출장계획서"
    #  **서식이 있는 증빙 2종.** 자유 서술 문서에서 「회식 단위」를 찾는 것보다 체크박스가
    #  훨씬 안정적이고, 서식의 선택지가 곧 `vocab.*`라 표기 불일치가 애초에 안 생긴다
    #  (실측 2026-08-25: 별표 축의 「음식물 vs 식사」 불일치 — `.personal/EVIDENCE_FORMS_PLAN.md`).
    DINING_REPORT = "DINING_REPORT", "회식 실시 확인서"
    HOSPITALITY_REPORT = "HOSPITALITY_REPORT", "접대 확인서"
    CONTRACT = "CONTRACT", "계약서·견적서"
    OTHER = "OTHER", "기타"


class ExtractionStatus(models.TextChoices):
    PENDING = "PENDING", "추출 대기"
    RUNNING = "RUNNING", "추출 중"
    DONE = "DONE", "추출 완료"
    FAILED = "FAILED", "추출 실패"
    SKIPPED = "SKIPPED", "추출 대상 아님"


class Attachment(models.Model):
    """정산에 붙는 추가 증빙 1건 + 그 문서에서 뽑아낸 사실.

    ``Receipt``(거래-영수증 매칭)와 역할이 다르다. Receipt는 "이 거래의 영수증이 있나"를,
    Attachment는 "이 정산을 뒷받침하는 문서들과 거기서 읽어낸 사실"을 다룬다.
    """
    settlement = models.ForeignKey(
        "settlements.Settlement", on_delete=models.CASCADE, related_name="attachments",
    )
    kind = models.CharField(max_length=20, choices=AttachmentKind.choices, default=AttachmentKind.OTHER)
    #  실물 파일. `PolicyDoc.file`과 같은 방식으로 media 볼륨에 저장하고, ai는 그 볼륨을
    #  읽기 전용으로 마운트해 판독한다(파일의 SoR은 Django, 판독은 AI).
    file = models.FileField("원본 파일", upload_to="attachments/%Y%m/", blank=True)
    #  ai에 넘기는 **볼륨 기준 상대경로**. `file.name`과 같은 값이지만 별도 컬럼으로 둔다 —
    #  외부 스토리지 키(업로드 없이 참조만 하는 경우)도 같은 자리에 담기 위해서다.
    file_ref = models.CharField("파일 경로/키", max_length=300, blank=True)
    original_name = models.CharField(max_length=200, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    # ── 추출 결과 (증빙자료 추출 Agent가 채운다) ────────────────────
    extraction_status = models.CharField(
        max_length=10, choices=ExtractionStatus.choices, default=ExtractionStatus.PENDING,
    )
    #  EvalContext dot-path → 값. `RuleTestCase.facts`와 같은 형태라 조립기가 그대로 얹는다.
    #  예: {"participants.participant_count": 4, "approval.pre_approval_obtained": true}
    #  **스키마에 없는 경로는 조립기가 조용히 버린다** — 추출기가 앞서 나가도 판정이 깨지지 않는다.
    extracted = models.JSONField("추출 사실(dot-path→값)", default=dict, blank=True)
    #  경로별 신뢰도. 저신뢰 값은 사람 확인 대상으로 표시하기 위해 함께 남긴다.
    field_confidence = models.JSONField("경로별 신뢰도", default=dict, blank=True)
    #  추출 근거(문서 내 위치·인용문). 감사 시 "왜 그렇게 읽었나"를 되짚는다.
    evidence_spans = models.JSONField("추출 근거 위치", default=list, blank=True)
    extractor_version = models.CharField(max_length=32, blank=True)   # 재추출 판별
    extracted_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["settlement_id", "kind", "id"]
        indexes = [models.Index(fields=["settlement", "kind"], name="ix_attachment_settle_kind")]

    def __str__(self):
        return f"{self.get_kind_display()} #{self.pk} (settlement {self.settlement_id})"

    @property
    def is_extracted(self) -> bool:
        return self.extraction_status == ExtractionStatus.DONE
