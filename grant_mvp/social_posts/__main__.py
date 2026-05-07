"""CLIエントリ: python -m grant_mvp.social_posts

S1 はスケルトンのみ。--init / --dry-run で土台の動作確認ができる。
投稿生成本体は S2 以降。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import (
    MAX_PER_THEME,
    POSTS_CSV_PATH,
    SITE_URL,
    SUPPORTED_SNS,
    SUPPORTED_THEMES,
)
from .store import init_csv, load_existing


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m grant_mvp.social_posts",
        description="SNS投稿候補生成（S1スケルトン）",
    )
    parser.add_argument("--theme", choices=SUPPORTED_THEMES,
                        help="テーマ指定（未指定なら全テーマ）")
    parser.add_argument("--sns", choices=SUPPORTED_SNS,
                        help="SNS指定（未指定なら両方）")
    parser.add_argument("--max-per-theme", type=int,
                        help="1回あたり/テーマあたりの上限")
    parser.add_argument("--dry-run", action="store_true",
                        help="CSVに書き込まず標準出力のみ")
    parser.add_argument("--out", type=Path, default=POSTS_CSV_PATH,
                        help=f"出力先CSVパス（既定: {POSTS_CSV_PATH}）")
    parser.add_argument("--init", action="store_true",
                        help="posts.csv をヘッダ付きで初期化して終了")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.init:
        created = init_csv(args.out)
        msg = "を作成しました" if created else "は既に存在します"
        print(f"[init] {args.out} {msg}")
        return 0

    print(
        f"[social_posts] SITE_URL={SITE_URL}  out={args.out}  "
        f"sns={args.sns or 'both'}  theme={args.theme or 'all'}  dry_run={args.dry_run}"
    )

    target_themes = [args.theme] if args.theme else list(SUPPORTED_THEMES)
    max_per_theme = args.max_per_theme or MAX_PER_THEME

    summaries = {}
    for theme in target_themes:
        if theme == "deadline_near":
            from .generator import generate_deadline_near
            summaries[theme] = generate_deadline_near(
                out_path=args.out,
                sns_filter=args.sns,
                max_per_theme=max_per_theme,
                dry_run=args.dry_run,
            )
        elif theme in ("poc", "ip", "startup", "sme"):
            from .generator import generate_simple_theme
            summaries[theme] = generate_simple_theme(
                theme,
                out_path=args.out,
                sns_filter=args.sns,
                max_per_theme=max_per_theme,
                dry_run=args.dry_run,
            )
        elif theme == "howto":
            from .generator import generate_howto
            summaries[theme] = generate_howto(
                out_path=args.out,
                sns_filter=args.sns,
                max_per_theme=max_per_theme,
                dry_run=args.dry_run,
            )
        else:
            print(f"[skip] theme={theme} は未実装")

    for theme, s in summaries.items():
        print(f"\n=== theme={theme} ===")
        print(f"  candidates_in_window : {s['candidates_in_window']}")
        print(f"  generated            : {s['generated']}")
        print(f"  skipped_cooldown     : {s['skipped_cooldown']}")
        print(f"  skipped_recent_theme : {s['skipped_recent_theme_duplicate']}")
        print(f"  skipped_duplicate    : {s['skipped_duplicate']}")
        print(f"  skipped_safety       : {s['skipped_safety']}")
        print(f"  skipped_error        : {s['skipped_error']}")
        for line in s["details"]:
            print(f"    {line}")
        if args.dry_run:
            for p in s.get("posts", []):
                print(f"\n  --- [{p['sns']}] {p['title']} (chars={p['char_count']}) ---")
                print(p["body"])

    existing = load_existing(args.out)
    print(f"\n[total] posts.csv 件数: {len(existing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
