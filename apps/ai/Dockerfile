FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# docling(표 구조 인식)이 opencv-python(cv2)을 끌어오는데, GUI 빌드라 slim 이미지엔
# 없는 X11/OpenGL 공유 라이브러리를 필요로 한다. 없으면 "libxcb.so.1: cannot open
# shared object file" 로 PDF 파싱 자체가 실패한다.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libxcb1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 9000

# 개발 시 compose가 --reload로 override.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
