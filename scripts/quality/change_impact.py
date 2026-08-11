"""Map changed paths to canonical boundaries and invariants."""
from __future__ import annotations

from pathlib import Path
from .config import load_registries

ROOT = Path(__file__).resolve().parents[2]


def impact_for_paths(paths: list[str], root: Path) -> dict:
    invariant_doc, boundary_doc = load_registries(root)
    boundaries = boundary_doc["boundaries"]
    touched = {item["id"] for item in boundaries for path in paths if any(path.replace("\\", "/").startswith(prefix) for prefix in item["paths"])}
    conservative = bool(paths) and not touched
    if conservative:
        touched = {item["id"] for item in boundaries}
    else:
        # Immediate consumers are affected contracts even when their own files
        # did not change (for example segmentation -> manifest).
        direct = set(touched)
        touched.update(consumer for item in boundaries if item["id"] in direct for consumer in item["consumers"])
    required = {inv for item in boundaries if item["id"] in touched for inv in item["invariants"]}
    required.update(item["id"] for item in invariant_doc["invariants"] if item["global"] and (touched or paths))
    tests = {test for item in boundaries if item["id"] in touched for test in item["tests"]}
    return {"boundaries": sorted(touched), "invariants": sorted(required), "tests": sorted(tests), "conservative": conservative}


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args(argv)
    impact = impact_for_paths(args.paths, root)
    print("BOUNDARIES_TOUCHED=" + ",".join(impact["boundaries"]))
    print("INVARIANTS_REQUIRED=" + ",".join(impact["invariants"]))
    print("TESTS_LOCAL=" + ",".join(impact["tests"]))
    print("CONSERVATIVE=" + ("SIM" if impact["conservative"] else "NAO"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
