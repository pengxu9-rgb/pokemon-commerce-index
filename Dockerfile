FROM python:3.12-slim AS catalog-build

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
COPY pokemon_index /app/pokemon_index
COPY catalog/ja-all-sets.jsonl catalog/ja-all-available.jsonl \
     catalog/en-physical-sets.jsonl catalog/en-physical-cards.jsonl \
     catalog/en-physical-ambiguous.jsonl \
     catalog/ptcg-jp-candidates.jsonl catalog/ptcg-jp-multi-record-candidates.jsonl \
     catalog/ptcg-jp-reference.jsonl \
     catalog/tcgdex-ambiguous-candidates.jsonl /app/catalog/
RUN python -m pokemon_index --db /app/catalog.sqlite3 init \
 && python -m pokemon_index --db /app/catalog.sqlite3 import-sets /app/catalog/ja-all-sets.jsonl \
 && python -m pokemon_index --db /app/catalog.sqlite3 import-sets /app/catalog/en-physical-sets.jsonl \
 && python -m pokemon_index --db /app/catalog.sqlite3 import-cards /app/catalog/ja-all-available.jsonl \
 && python -m pokemon_index --db /app/catalog.sqlite3 import-cards /app/catalog/en-physical-cards.jsonl \
 && python -m pokemon_index --db /app/catalog.sqlite3 import-cards /app/catalog/en-physical-ambiguous.jsonl \
 && python -m pokemon_index --db /app/catalog.sqlite3 import-cards /app/catalog/ptcg-jp-candidates.jsonl \
 && python -m pokemon_index --db /app/catalog.sqlite3 import-cards /app/catalog/ptcg-jp-multi-record-candidates.jsonl \
 && python -m pokemon_index --db /app/catalog.sqlite3 import-cards /app/catalog/tcgdex-ambiguous-candidates.jsonl \
 && python -m pokemon_index --db /app/catalog.sqlite3 import-card-references /app/catalog/ptcg-jp-reference.jsonl

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pokemon_index /app/pokemon_index
COPY --from=catalog-build /app/catalog.sqlite3 /app/catalog.sqlite3
USER 65532:65532
EXPOSE 8080
CMD ["python", "-m", "pokemon_index", "--db", "/app/catalog.sqlite3", "serve", "--host", "0.0.0.0", "--internal-catalog-api"]
