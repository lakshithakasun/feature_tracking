import sys
from pathlib import Path

from app.database import SessionLocal
from app.parsers import create_release_from_taxonomy, load_taxonomy_yaml


def main(file_path: str) -> None:
    source_path = Path(file_path)
    if not source_path.exists():
        raise SystemExit(f"File not found: {file_path}")

    raw_text = source_path.read_text(encoding="utf-8")
    taxonomy = load_taxonomy_yaml(raw_text)

    with SessionLocal() as session:
        release = create_release_from_taxonomy(session, taxonomy, source_file=str(source_path.name))
        print(f"Created release: {release.product_id} {release.version}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/load_taxonomy.py <path-to-taxonomy.yaml>")
    main(sys.argv[1])
