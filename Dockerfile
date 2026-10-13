ARG CATALOG_BUILD_MANIFEST=catalog-build-manifest-source-binding-v1.json
FROM python:3.12-slim AS catalog-build
ARG CATALOG_BUILD_MANIFEST

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
COPY pokemon_index /app/pokemon_index
COPY scripts/__init__.py scripts/build_catalog_snapshot.py /app/scripts/
COPY catalog-build-manifest*.json /app/
COPY catalog /app/catalog
RUN case "$CATALOG_BUILD_MANIFEST" in \
      catalog-build-manifest-source-binding-v1.json|catalog-build-manifest-international-pokemon-scale-v1.json) ;; \
      *) echo 'Unsupported catalog manifest' >&2; exit 1 ;; esac \
    && python -m scripts.build_catalog_snapshot \
    --manifest "/app/$CATALOG_BUILD_MANIFEST" --db /app/catalog.sqlite3 \
    && chmod 0444 /app/catalog.sqlite3

FROM python:3.12-slim
ARG CATALOG_BUILD_MANIFEST
ARG SOURCE_COMMIT=unknown
LABEL org.opencontainers.image.source="https://github.com/pengxu9-rgb/pokemon-commerce-index" \
      org.opencontainers.image.revision="$SOURCE_COMMIT" \
      pokemon.catalog.manifest="$CATALOG_BUILD_MANIFEST"
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pokemon_index /app/pokemon_index
COPY --from=catalog-build /app/catalog.sqlite3 /app/catalog.sqlite3
USER 65532:65532
EXPOSE 8080
CMD ["python", "-m", "pokemon_index", "--db", "/app/catalog.sqlite3", "serve", "--host", "0.0.0.0", "--internal-catalog-api"]
