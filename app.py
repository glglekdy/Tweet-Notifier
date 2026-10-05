"""Dishost 호환용 진입점.

Dishost(Pterodactyl) 의 기본 시작 파일 이름이 `app.py` 라서, 패널의 시작 설정을
건드리지 않아도 그대로 돌아가도록 얇은 껍데기를 둔다. 실제 구동 코드는 `main.py` 에 있다.
"""

from __future__ import annotations

import sys

from main import main

if __name__ == "__main__":
    sys.exit(main())
