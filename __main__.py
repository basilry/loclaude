"""python -m local-claude 또는 python __main__.py 로 실행."""
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from core.cli import main

if __name__ == "__main__":
    main()
