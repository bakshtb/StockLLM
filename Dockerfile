# StockLLM Home Assistant add-on image. Built locally by HA Supervisor on
# the host (no image registry / CI needed) -- see DOCS.md for install steps.
#
# Deliberately a plain Python base rather than one of HA's official
# s6-overlay base images: this add-on is a single Flask process with no
# need for HA's init/process-supervision system, so the extra layer of
# complexity isn't worth it for a personal single-service add-on.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

RUN chmod +x run.sh

EXPOSE 8099

CMD ["./run.sh"]
