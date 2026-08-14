"""1/3 — RuleGraph.scope CHECK 제약을 임시로 넓힌다(구값+신값 동시 허용).

'업무활성' Category 폐지(settlements 0007)에 맞춰 `ck_rulegraph_scope`를 최종 상태로 한 번에
바꾸면, 아직 데이터가 '업무활성'인 행이 남아있는 시점에 새 제약(신값만 허용)이 즉시 위반된다
(실측: `IntegrityError: check constraint "ck_rulegraph_scope" ... is violated by some row`).
그래서 3단계로 나눈다 — ① 넓히기(이 마이그레이션, 구값·신값 동시 허용) → ② 데이터 이관(0010)
→ ③ 좁히기(0011, 최종 상태 — 구값 제거). 이 파일은 `models.py`의 최종 CheckConstraint 정의와
다르다 — 중간 단계 전용이라 의도적으로 어긋난다.
"""
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ('policies', '0010_alter_policydoc_options_remove_policydoc_file_ref_and_more'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='rulegraph',
            name='ck_rulegraph_scope',
        ),
        migrations.AddConstraint(
            model_name='rulegraph',
            constraint=models.CheckConstraint(
                condition=Q(scope__in=[
                    'GLOBAL', 'TEST_DEMO',
                    # 신값(최종 Category.values)
                    '회식', '회의', '식대', '출장', '접대', '비품',
                    # 구값(0010 데이터 이관 전까지만 허용, 0011에서 제거)
                    '업무활성',
                ]),
                name='ck_rulegraph_scope',
            ),
        ),
    ]
