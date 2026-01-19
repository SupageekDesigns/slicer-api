FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y \
    wget \
    bzip2 \
    libgl1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libdbus-1-3 \
    libx11-6 \
    libxext6 \
    libxrender1 \
    libsm6 \
    libxcb1 \
    libxkbcommon0 \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q https://github.com/prusa3d/PrusaSlicer/releases/download/version_2.7.1/PrusaSlicer-2.7.1+linux-x64-GTK3-202312140926.tar.bz2 \
    && tar -xjf PrusaSlicer-2.7.1+linux-x64-GTK3-202312140926.tar.bz2 \
    && mv PrusaSlicer-2.7.1+linux-x64-GTK3-202312140926 /opt/prusaslicer \
    && rm PrusaSlicer-2.7.1+linux-x64-GTK3-202312140926.tar.bz2 \
    && ln -s /opt/prusaslicer/prusa-slicer /usr/local/bin/prusa-slicer

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--timeout", "120", "server:app"]
