# 벡터 DB 덤프 위치
#  `docker compose exec ai python -m app.rag.embedding.snapshot dump --out /data/rag_snapshot`
#  덤프는 임베딩 벡터를 그대로 담아 복원 시 OpenAI를 부르지 않는다(과금 0, 재현 100%).
