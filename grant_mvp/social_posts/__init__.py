"""SNS投稿候補生成モジュール (grant_mvp.social_posts).

S1: ディレクトリ・CSVスキーマ・CLIスケルトンのみ。
投稿生成本体（filters / templates / safety / generator）は S2 以降で追加する。
"""
import os
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _PACKAGE_DIR.parent.parent  # grant_mvp_next_gemini_connected/

SITE_URL = os.getenv("GRANT_MVP_SITE_URL", "https://example.com/")
POSTS_CSV_PATH = Path(
    os.getenv("GRANT_MVP_POSTS_CSV", str(PROJECT_ROOT / "posts.csv"))
)
DEADLINE_NEAR_DAYS = int(os.getenv("GRANT_MVP_DEADLINE_NEAR_DAYS", "14"))
COOLDOWN_DAYS = int(os.getenv("GRANT_MVP_COOLDOWN_DAYS", "30"))
MAX_PER_THEME = int(os.getenv("GRANT_MVP_MAX_PER_THEME", "2"))

CSV_FIELDS = [
    "id",
    "created_at",
    "sns",
    "theme",
    "grant_id",
    "title",
    "body",
    "char_count",
    "site_url",
    "source_url",
    "body_hash",
    "generation_method",
    "status",
]

CSV_ENCODING = "utf-8-sig"

SUPPORTED_SNS = ("x", "linkedin")
SUPPORTED_THEMES = (
    "today",
    "deadline_near",
    "poc",
    "ip",
    "startup",
    "sme",
    "howto",
)
