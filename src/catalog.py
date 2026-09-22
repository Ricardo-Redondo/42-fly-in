from pathlib import Path

MAPS_ROOT = Path(__file__).resolve().parent.parent / "maps"


def discover_maps(root: Path = MAPS_ROOT) -> list[Path]:
    """All *.txt map files under root, sorted by category then name."""
    return sorted(root.rglob("*.txt"))
