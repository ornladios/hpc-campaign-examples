#!/usr/bin/env python3
"""Validate the completed example campaign's layout and stored provenance."""

from __future__ import annotations

import argparse
from pathlib import Path

from hpc_campaign import Manager


def verify_campaign(archive: Path) -> None:
    """Check the final layout, including datasets added for Plans and views."""
    manager = Manager(archive=str(archive))
    manager.open(create=False)
    try:
        layout = manager.validate_schema()
        if "instances" in layout:
            print(f"[ok] schema validated for {len(layout['instances'])} run(s)")
        else:
            print("[ok] schema validated at campaign root")

        documents = manager.prov_documents(active=True)
        if len(documents) != 1:
            raise ValueError(f"Expected one active provenance document, found {len(documents)}")
        document = manager.prov_document(documents[0].document_id)
        print(f"[ok] active provenance loaded and hash verified: {len(document.get_records())} records")
    finally:
        manager.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path, help="Completed campaign archive to validate")
    args = parser.parse_args()
    verify_campaign(args.archive)


if __name__ == "__main__":
    main()
