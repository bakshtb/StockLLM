# StockLLM Home Assistant add-on image. Built locally by HA Supervisor on
# the host (no image registry / CI needed) -- see DOCS.md for install steps.
# That host is frequently a Raspberry Pi (this add-on's own dev/runtime
# environment is HAOS on ARM) -- the Node stage below exists ONLY to run
# `npm run build` and is discarded after; the final image is Python-only,
# so the add-on's actual runtime footprint doesn't grow just because its
# front-end now has a build step.

FROM node:22-slim AS webui-builder
WORKDIR /webui
COPY webui/package.json webui/package-lock.json ./
RUN npm ci
COPY webui/ .
RUN npm run build

# Deliberately a plain Python base rather than one of HA's official
# s6-overlay base images: this add-on is a single Flask process with no
# need for HA's init/process-supervision system, so the extra layer of
# complexity isn't worth it for a personal single-service add-on.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app
# webui-builder's outDir (webui/vite.config.js) already points at
# dashboard/assets/dist/ relative to the webui/ project -- this just
# overlays that build output onto the plain source copy above, since dist/
# itself is gitignored (build output, not source).
COPY --from=webui-builder /dashboard/assets/dist /app/dashboard/assets/dist

RUN chmod +x run.sh

EXPOSE 8099

CMD ["./run.sh"]
