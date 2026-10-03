FROM python:3.12-slim AS catalog-build

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
COPY pokemon_index /app/pokemon_index
COPY scripts/__init__.py scripts/build_catalog_snapshot.py /app/scripts/
COPY catalog-build-manifest-source-facts-escalation-v1.json /app/catalog-build-manifest-source-facts-escalation-v1.json
COPY catalog /app/catalog
RUN python -m scripts.build_catalog_snapshot \
    --manifest /app/catalog-build-manifest-source-facts-escalation-v1.json --db /app/catalog.sqlite3 \
    && chmod 0444 /app/catalog.sqlite3

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pokemon_index /app/pokemon_index
COPY --from=catalog-build /app/catalog.sqlite3 /app/catalog.sqlite3
USER 65532:65532
EXPOSE 8080
CMD ["python", "-m", "pokemon_index", "--db", "/app/catalog.sqlite3", "serve", "--host", "0.0.0.0", "--internal-catalog-api"]
