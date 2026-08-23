"""화면에서 **본인이 직접 등록한** 건의 실사용자를 채운다.

`SettlementViewSet.create`가 `actual_user`를 안 넣고 있었다(2026-08-24 발견). 그 결과
본인이 팀·공용카드로 올린 건이 전부 `actual_user_recorded=None`(모름)으로 남아
기본 게이트의 `ACTUAL_USER_REQUIRED`에 걸리고 자동 통과에서 빠졌다.

## 무엇을 채우고 무엇을 안 채우나

채우는 것: **`submitted_by`가 있는데 `actual_user`가 빈 건.**
등록자가 있다는 건 그 사람이 로그인해서 자기 지출로 올렸다는 뜻이고, **등록 행위 자체가
「내가 썼다」는 기록**이다. 지어내는 게 아니라 이미 일어난 사실을 뒤늦게 적는 것이다.

안 채우는 것: **`submitted_by`가 비어 있는 건.** 「내역 불러오기」가 팀·공용카드를 수집할
때 만드는 모양이다 — 카드사 원장에서 긁어와 **주인을 모르는** 상태라 `claim()`(「내가
사용했어요」)으로 사람이 해소해야 한다. 여기서 임의로 채우면 판정이 쓰는 사실을 지어내는 것이
되고, 그건 이 저장소가 계속 피해 온 실수다(`erp_import` 모듈 docstring).

되돌릴 때(reverse)는 **아무것도 하지 않는다.** 어느 행이 이 마이그레이션 때문에 채워졌고
어느 행이 원래 채워져 있었는지 구분할 수 없어서, 되돌리면 멀쩡한 기록까지 지운다.
"""
from django.db import migrations
from django.db.models import F


def backfill(apps, schema_editor):
    Settlement = apps.get_model("settlements", "Settlement")
    Settlement.objects.filter(
        submitted_by__isnull=False, actual_user__isnull=True,
    ).update(actual_user=F("submitted_by"), actual_user_recorded=True)


class Migration(migrations.Migration):

    dependencies = [
        ("settlements", "0013_alter_settlement_ai_category_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
