"""비용분류 `비품` 폐기 — 기존 데이터를 `기타`로 옮긴다.

정산 과목을 **회식·회의·식대·출장·접대** 다섯으로 단순화하면서 `비품`을 뺐다(2026-08-24).
비품 구매는 「나열된 어디에도 안 맞는」 지출이라 `기타`가 정확히 그 자리다.

## 왜 데이터를 먼저 옮겨야 하나

`Category`에서 값을 빼면 `RuleGraph.scope`의 CHECK 제약이 **좁아진다**. 그 제약을 다시
걸기 전에 옛 값을 쓰는 행이 남아 있으면 `AddConstraint`가 IntegrityError로 죽는다 —
`policies/0009~0011`에서 "업무활성"→"회식" 리네임 때 실제로 겪은 일이라 그때 넓히기→이관→
좁히기 3단계로 쪼갰다. 이번에도 **이관이 먼저**다(`policies/0021`이 이 마이그레이션에 의존).

## 되돌리지 않는다

reverse는 no-op다. 어느 행이 원래 `기타`였고 어느 행이 이 마이그레이션 때문에 `기타`가
됐는지 구분할 수 없어서, 되돌리면 멀쩡한 기록까지 `비품`으로 만든다.
"""
from django.db import migrations

RETIRED = "비품"
REPLACEMENT = "기타"


def move_supplies(apps, schema_editor):
    Settlement = apps.get_model("settlements", "Settlement")
    #  확정 분류와 AI 제안을 **둘 다** 옮긴다. `ai_category`만 남으면 목록 배지가
    #  목록에 없는 값을 그리고, 사람이 그 값을 다시 고를 수도 없다.
    Settlement.objects.filter(category=RETIRED).update(category=REPLACEMENT)
    Settlement.objects.filter(ai_category=RETIRED).update(ai_category=REPLACEMENT)

    #  팀 예산도 옮긴다. **합치지 않고 옮기기만 한다** — 같은 (팀, 월)에 `기타` 행이
    #  이미 있으면 한도가 둘이 되므로, 그때는 비품 행을 지우고 한도를 기타에 더한다
    #  (불변식: 팀 총한도 = 과목 한도의 합).
    TeamBudget = apps.get_model("settlements", "TeamBudget")
    for row in TeamBudget.objects.filter(category=RETIRED):
        existing = TeamBudget.objects.filter(
            team_id=row.team_id, year_month=row.year_month, category=REPLACEMENT,
        ).first()
        if existing is None:
            row.category = REPLACEMENT
            row.save(update_fields=["category"])
        else:
            existing.limit_amount += row.limit_amount
            existing.save(update_fields=["limit_amount"])
            row.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("settlements", "0014_backfill_actual_user_for_self_registered"),
    ]

    operations = [
        migrations.RunPython(move_supplies, migrations.RunPython.noop),
    ]
