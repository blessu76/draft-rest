"""ipe_web_kit — ipe 웹 공통 킷(Python 표준 라이브러리만 · 3.9+).

로직은 함수로, UI 는 assets/ipe-kit.css + 테마 토큰(--ipe-*)으로 준다. 웹은 git 태그에서
vendor/ipe_web_kit/ 로 복사해 쓴다(ipe_web_kit.vendor).
"""
from pathlib import Path

__version__ = "0.6.0"
# 킷 자산(ipe-kit.css)의 개정 — ?v= 캐시버스팅 글자. 자산이 바뀔 때만 올린다(PATCH 태그가 사이트 출력을 바꾸지 않게).
ASSET_REV = "0.1.0"

ASSETS = Path(__file__).resolve().parent / "assets"
