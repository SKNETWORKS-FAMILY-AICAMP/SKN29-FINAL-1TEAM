"""정산 건의 업종 표기를 정본 어휘로 이관 + 코드 채움 (§7-1).

`merchant_industry`는 조립기가 `merchant.merchant_type` 사실로 그대로 올리는 값이다.
시드·ERP 수집이 `한식`·`서점`·`여객운송` 같은 표기로 채워 왔는데 룰은 `주점`·`골프장`
표기로 비교하고 있었다. 표기를 정본으로 접고, 새 `merchant_industry_code`를 함께 채운다.

접히지 않는 값은 **원문을 남긴다** — 정산 건은 감사 대상이라 사람이 입력했을 수 있는
원문을 지우지 않는다. 대신 코드가 비어 있어 조립기가 미확정으로 올린다.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    from domain.transactions.industry import resolve

    Settlement = apps.get_model("settlements", "Settlement")
    for row in Settlement.objects.exclude(merchant_industry="").iterator():
        code, label = resolve(row.merchant_industry)
        if not code:
            continue
        if (row.merchant_industry, row.merchant_industry_code) != (label, code):
            row.merchant_industry, row.merchant_industry_code = label, code
            row.save(update_fields=["merchant_industry", "merchant_industry_code"])


def backwards(apps, schema_editor):
    """되돌리지 않는다 — 옛 자유 표기는 정본에서 역산되지 않는다."""


class Migration(migrations.Migration):
    dependencies = [
        ("settlements", "0009_settlement_merchant_industry_code"),
        ("transactions", "0004_canonicalize_merchant_industry"),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
