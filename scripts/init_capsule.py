"""
memvid capsule initializer.
Creates .internal/wiki/memory.mv2 (or .internal/wiki/memory.json as fallback stub).
"""

from core.project_paths import get_project_paths

WIKI_DIR = get_project_paths().wiki_dir
CAPSULE_PATH = WIKI_DIR / "memory.mv2"
STUB_PATH = WIKI_DIR / "memory.json"


def init_with_memvid():
    from memvid import MemvidEncoder, MemvidRetriever

    encoder = MemvidEncoder()
    encoder.add_text("Local-Claude Wiki initialized.", metadata={"type": "system", "action": "init"})
    encoder.build_video(str(CAPSULE_PATH))
    print(f"memvid capsule created: {CAPSULE_PATH}")
    return True


def init_with_stub():
    import json

    data = {
        "version": "stub-1.0",
        "entries": [
            {
                "id": 0,
                "text": "Local-Claude Wiki initialized.",
                "metadata": {"type": "system", "action": "init"},
            }
        ],
    }
    STUB_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Stub capsule created: {STUB_PATH}")
    return True


def main():
    WIKI_DIR.mkdir(parents=True, exist_ok=True)

    try:
        init_with_memvid()
    except Exception as e:
        print(f"memvid unavailable ({e}), falling back to JSON stub.")
        init_with_stub()


if __name__ == "__main__":
    main()
