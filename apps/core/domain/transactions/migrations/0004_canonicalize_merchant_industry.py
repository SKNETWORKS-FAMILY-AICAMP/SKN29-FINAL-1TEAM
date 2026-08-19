"""가맹점 업종 캐시를 정본 어휘로 이관 (§7-1).

기존 행은 카카오 group code(`CE7`·`FD6`·`AD5`·`AT4`)와 자유 라벨(`한식`·`주점`)로 채워져
있었다. 그 값이 그대로 판정 사실(`merchant.merchant_type`)이 되는데 룰·금지업종 별표는
다른 표기로 비교하고 있었다 — 조용히 안 걸리던 자리다.

접히지 않는 값은 **지운다**(빈 문자열). 남겨두면 옛 어휘가 계속 판정에 올라간다.
빈 값은 조립기에서 `merchant_info_resolved=False`가 되어 사람이 보게 되고, 다음 조회 때
카카오+LLM이 정본 어휘로 다시 채운다.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    from domain.transactions.industry import resolve

    MerchantCategory = apps.get_model("transactions", "MerchantCategory")
    for row in MerchantCategory.objects.all().iterator():
        # 옛 industry_code는 카카오 group code라 정본이 아니다 → 라벨을 먼저 본다.
        code, label = resolve(row.industry_label)
        if not code:
            code, label = resolve(row.industry_code)
        if (code, label) != (row.industry_code, row.industry_label):
            row.industry_code, row.industry_label = code, label
            row.save(update_fields=["industry_code", "industry_label"])


def backwards(apps, schema_editor):
    """되돌릴 수 없다 — 옛 카카오 group code는 정본에 대응물이 없다(원본은 `raw`에 있다)."""


class Migration(migrations.Migration):
    dependencies = [("transactions", "0003_alter_merchantcategory_industry_code_and_more")]
    operations = [migrations.RunPython(forwards, backwards)]
