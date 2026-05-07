"""投稿候補生成のオーケストレーション.

filters → templates → safety → store の流れで posts.csv に追記する。
S3 では deadline_near テーマのみ対応。
generation_method は "template" 固定（将来 Gemini を差し込む口は残す）。

【S3の重複回避ポリシー（案A）】
- 重複判定は **body_hash の完全一致のみ**（既存 posts.csv 全行と突合）。
- body_hash がヒットした場合は `skipped_duplicate += 1` とし、その投稿のみ破棄。
  per_sns_count は増やさないので、同じ run 内で次の未投稿候補（別の公募）が
  優先して埋められる ＝ 毎回 fresh な候補を追加生成する挙動。
- そのため「同じテーマ・同じSNSで同じ公募が、日をまたいで再登場する」ケースは
  S3 では**抑制しない**。これは S6 で `(grant_id, sns)` の cooldown_days を
  実装して対応する（既存 CSV の created_at を見て N 日以内なら除外）。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import (
    COOLDOWN_DAYS,
    DEADLINE_NEAR_DAYS,
    MAX_PER_THEME,
    POSTS_CSV_PATH,
    SITE_URL,
)
from .filters import (
    find_deadline_near, find_poc, find_ip, find_startup, find_sme,
)
from .safety import validate
from .store import (
    append_posts,
    body_hash,
    existing_body_hashes,
    latest_created_at_by_grant_sns,
    recent_theme_grant_ids,
)
from .templates import (
    render_deadline_near_linkedin, render_deadline_near_x,
    render_poc_x, render_poc_linkedin,
    render_ip_x, render_ip_linkedin,
    render_startup_x, render_startup_linkedin,
    render_sme_x, render_sme_linkedin,
    HOWTO_POSTS, render_howto_x, render_howto_linkedin,
)


logger = logging.getLogger("grant_mvp.social_posts.generator")


def _make_post(
    grant: Dict[str, Any],
    sns: str,
    theme: str,
    body: str,
    site_url: str,
) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sns": sns,
        "theme": theme,
        "grant_id": grant.get("id", ""),
        "title": grant.get("title", ""),
        "body": body,
        "char_count": len(body),
        "site_url": site_url,
        "source_url": grant.get("front_subsidy_detail_page_url", "") or "",
        "body_hash": body_hash(body),
        "generation_method": "template",
        "status": "draft",
    }


def generate_deadline_near(
    out_path: Path = POSTS_CSV_PATH,
    *,
    sns_filter: Optional[str] = None,
    max_per_theme: int = MAX_PER_THEME,
    days: int = DEADLINE_NEAR_DAYS,
    cooldown_days: int = COOLDOWN_DAYS,
    recent_window: int = 5,
    site_url: str = SITE_URL,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """deadline_near の投稿候補を生成する。"""
    summary: Dict[str, Any] = {
        "candidates_in_window": 0,
        "generated": 0,
        "skipped_cooldown": 0,
        "skipped_recent_theme_duplicate": 0,
        "skipped_duplicate": 0,
        "skipped_safety": 0,
        "skipped_error": 0,
        "details": [],
        "posts": [],
    }

    try:
        grants = find_deadline_near(days=days, limit=200)
    except Exception as exc:
        logger.warning("DB抽出失敗: %s", exc)
        summary["details"].append(f"[error] DB抽出失敗: {exc}")
        return summary

    summary["candidates_in_window"] = len(grants)
    if not grants:
        summary["details"].append("[info] 締切間近の公募なし")
        return summary

    seen_hashes = existing_body_hashes(out_path)
    cooldown_map = latest_created_at_by_grant_sns(out_path)
    recent_set = recent_theme_grant_ids(out_path, n=recent_window)
    now = datetime.now(timezone.utc)
    cooldown_delta = timedelta(days=cooldown_days)
    theme_key = "deadline_near"

    if sns_filter == "x":
        sns_targets: Tuple[str, ...] = ("x",)
    elif sns_filter == "linkedin":
        sns_targets = ("linkedin",)
    else:
        sns_targets = ("x", "linkedin")

    per_sns_count: Dict[str, int] = {s: 0 for s in sns_targets}
    posts_to_append: List[Dict[str, Any]] = []

    for grant in grants:
        if all(per_sns_count[s] >= max_per_theme for s in sns_targets):
            break
        for sns in sns_targets:
            if per_sns_count[sns] >= max_per_theme:
                continue

            grant_id = grant.get("id", "")

            # 直近 recent_window 件で同一 (theme, grant_id) があれば抑制
            if (theme_key, grant_id) in recent_set:
                summary["skipped_recent_theme_duplicate"] += 1
                summary["details"].append(
                    f"[skip:recent_theme] grant={grant_id or '?'} sns={sns}"
                )
                continue

            # (grant_id, sns) が cooldown_days 以内に投稿済みなら抑制
            latest = cooldown_map.get((grant_id, sns))
            if latest is not None and (now - latest) < cooldown_delta:
                elapsed = (now - latest).days
                summary["skipped_cooldown"] += 1
                summary["details"].append(
                    f"[skip:cooldown] grant={grant_id or '?'} sns={sns} "
                    f"({elapsed}日経過 < {cooldown_days}日)"
                )
                continue

            try:
                days_left = grant.get("_days_until_deadline", 0)
                if sns == "x":
                    body = render_deadline_near_x(grant, days_left, site_url)
                else:
                    body = render_deadline_near_linkedin(grant, days_left, site_url)
            except Exception as exc:
                summary["skipped_error"] += 1
                summary["details"].append(
                    f"[skip:error] grant={grant.get('id','?')} sns={sns} {exc}"
                )
                continue

            result = validate(body, sns)
            if not result.ok:
                summary["skipped_safety"] += 1
                summary["details"].append(
                    f"[skip:safety] grant={grant.get('id','?')} sns={sns} reasons={result.reasons}"
                )
                continue

            h = body_hash(body)
            if h in seen_hashes:
                summary["skipped_duplicate"] += 1
                summary["details"].append(
                    f"[skip:dup] grant={grant.get('id','?')} sns={sns}"
                )
                continue
            seen_hashes.add(h)

            post = _make_post(grant, sns, "deadline_near", body, site_url)
            posts_to_append.append(post)
            per_sns_count[sns] += 1
            summary["generated"] += 1

    summary["posts"] = posts_to_append

    if dry_run:
        summary["details"].append("[dry-run] CSV書き込みは行いません")
    elif posts_to_append:
        try:
            written = append_posts(out_path, posts_to_append)
            summary["details"].append(f"[csv] {written} 件を {out_path} に追記")
        except Exception as exc:
            logger.warning("CSV書き込み失敗: %s", exc)
            summary["details"].append(f"[error] CSV書き込み失敗: {exc}")

    return summary


# ===== S4: 共通テーマ生成（poc / ip / startup / sme） =====

SIMPLE_THEMES = {
    "poc":     (find_poc,     render_poc_x,     render_poc_linkedin),
    "ip":      (find_ip,      render_ip_x,      render_ip_linkedin),
    "startup": (find_startup, render_startup_x, render_startup_linkedin),
    "sme":     (find_sme,     render_sme_x,     render_sme_linkedin),
}


def generate_simple_theme(
    theme_key: str,
    out_path: Path = POSTS_CSV_PATH,
    *,
    sns_filter: Optional[str] = None,
    max_per_theme: int = MAX_PER_THEME,
    cooldown_days: int = COOLDOWN_DAYS,
    recent_window: int = 5,
    site_url: str = SITE_URL,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """deadline_near 以外のシンプルテーマ（poc/ip/startup/sme）の投稿候補生成。"""
    if theme_key not in SIMPLE_THEMES:
        raise ValueError(f"unsupported simple theme: {theme_key}")
    finder, render_x, render_li = SIMPLE_THEMES[theme_key]

    summary: Dict[str, Any] = {
        "candidates_in_window": 0,
        "generated": 0,
        "skipped_cooldown": 0,
        "skipped_recent_theme_duplicate": 0,
        "skipped_duplicate": 0,
        "skipped_safety": 0,
        "skipped_error": 0,
        "details": [],
        "posts": [],
    }

    try:
        grants = finder(limit=200)
    except Exception as exc:
        logger.warning("DB抽出失敗: %s", exc)
        summary["details"].append(f"[error] DB抽出失敗: {exc}")
        return summary

    summary["candidates_in_window"] = len(grants)
    if not grants:
        summary["details"].append(f"[info] {theme_key} 候補なし")
        return summary

    seen_hashes = existing_body_hashes(out_path)
    cooldown_map = latest_created_at_by_grant_sns(out_path)
    recent_set = recent_theme_grant_ids(out_path, n=recent_window)
    now = datetime.now(timezone.utc)
    cooldown_delta = timedelta(days=cooldown_days)

    if sns_filter == "x":
        sns_targets: Tuple[str, ...] = ("x",)
    elif sns_filter == "linkedin":
        sns_targets = ("linkedin",)
    else:
        sns_targets = ("x", "linkedin")

    per_sns_count: Dict[str, int] = {s: 0 for s in sns_targets}
    posts_to_append: List[Dict[str, Any]] = []

    for grant in grants:
        if all(per_sns_count[s] >= max_per_theme for s in sns_targets):
            break
        for sns in sns_targets:
            if per_sns_count[sns] >= max_per_theme:
                continue

            grant_id = grant.get("id", "")

            if (theme_key, grant_id) in recent_set:
                summary["skipped_recent_theme_duplicate"] += 1
                summary["details"].append(
                    f"[skip:recent_theme] grant={grant_id or '?'} sns={sns}"
                )
                continue

            latest = cooldown_map.get((grant_id, sns))
            if latest is not None and (now - latest) < cooldown_delta:
                elapsed = (now - latest).days
                summary["skipped_cooldown"] += 1
                summary["details"].append(
                    f"[skip:cooldown] grant={grant_id or '?'} sns={sns} "
                    f"({elapsed}日経過 < {cooldown_days}日)"
                )
                continue

            try:
                body = render_x(grant, site_url) if sns == "x" else render_li(grant, site_url)
            except Exception as exc:
                summary["skipped_error"] += 1
                summary["details"].append(
                    f"[skip:error] grant={grant.get('id','?')} sns={sns} {exc}"
                )
                continue

            result = validate(body, sns)
            if not result.ok:
                summary["skipped_safety"] += 1
                summary["details"].append(
                    f"[skip:safety] grant={grant.get('id','?')} sns={sns} reasons={result.reasons}"
                )
                continue

            h = body_hash(body)
            if h in seen_hashes:
                summary["skipped_duplicate"] += 1
                summary["details"].append(
                    f"[skip:dup] grant={grant.get('id','?')} sns={sns}"
                )
                continue
            seen_hashes.add(h)

            post = _make_post(grant, sns, theme_key, body, site_url)
            posts_to_append.append(post)
            per_sns_count[sns] += 1
            summary["generated"] += 1

    summary["posts"] = posts_to_append

    if dry_run:
        summary["details"].append("[dry-run] CSV書き込みは行いません")
    elif posts_to_append:
        try:
            written = append_posts(out_path, posts_to_append)
            summary["details"].append(f"[csv] {written} 件を {out_path} に追記")
        except Exception as exc:
            logger.warning("CSV書き込み失敗: %s", exc)
            summary["details"].append(f"[error] CSV書き込み失敗: {exc}")

    return summary


# ===== S5: howto 固定ノウハウ投稿 =====

def generate_howto(
    out_path: Path = POSTS_CSV_PATH,
    *,
    sns_filter: Optional[str] = None,
    max_per_theme: int = MAX_PER_THEME,
    site_url: str = SITE_URL,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """固定ノウハウ投稿（DB不使用）。重複は body_hash のみで制御し、
    cooldown / recent_theme は適用しない（grant_id="" 共有のため誤抑制を避ける）。
    """
    summary: Dict[str, Any] = {
        "candidates_in_window": len(HOWTO_POSTS),
        "generated": 0,
        "skipped_cooldown": 0,
        "skipped_recent_theme_duplicate": 0,
        "skipped_duplicate": 0,
        "skipped_safety": 0,
        "skipped_error": 0,
        "details": [],
        "posts": [],
    }
    seen_hashes = existing_body_hashes(out_path)

    if sns_filter == "x":
        sns_targets: Tuple[str, ...] = ("x",)
    elif sns_filter == "linkedin":
        sns_targets = ("linkedin",)
    else:
        sns_targets = ("x", "linkedin")

    per_sns_count: Dict[str, int] = {s: 0 for s in sns_targets}
    posts_to_append: List[Dict[str, Any]] = []

    for entry in HOWTO_POSTS:
        if all(per_sns_count[s] >= max_per_theme for s in sns_targets):
            break
        for sns in sns_targets:
            if per_sns_count[sns] >= max_per_theme:
                continue
            try:
                body = (
                    render_howto_x(entry, site_url)
                    if sns == "x"
                    else render_howto_linkedin(entry, site_url)
                )
            except Exception as exc:
                summary["skipped_error"] += 1
                summary["details"].append(
                    f"[skip:error] howto={entry['key']} sns={sns} {exc}"
                )
                continue

            result = validate(body, sns)
            if not result.ok:
                summary["skipped_safety"] += 1
                summary["details"].append(
                    f"[skip:safety] howto={entry['key']} sns={sns} reasons={result.reasons}"
                )
                continue

            h = body_hash(body)
            if h in seen_hashes:
                summary["skipped_duplicate"] += 1
                summary["details"].append(
                    f"[skip:dup] howto={entry['key']} sns={sns}"
                )
                continue
            seen_hashes.add(h)

            pseudo_grant = {
                "id": "",
                "title": entry["lead"],
                "front_subsidy_detail_page_url": "",
            }
            post = _make_post(pseudo_grant, sns, "howto", body, site_url)
            posts_to_append.append(post)
            per_sns_count[sns] += 1
            summary["generated"] += 1

    summary["posts"] = posts_to_append

    if dry_run:
        summary["details"].append("[dry-run] CSV書き込みは行いません")
    elif posts_to_append:
        try:
            written = append_posts(out_path, posts_to_append)
            summary["details"].append(f"[csv] {written} 件を {out_path} に追記")
        except Exception as exc:
            logger.warning("CSV書き込み失敗: %s", exc)
            summary["details"].append(f"[error] CSV書き込み失敗: {exc}")

    return summary
