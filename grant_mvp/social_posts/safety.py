"""SNS投稿の安全チェック.

- 誇大表現・採択保証を示唆する語の検出
- 公式確認文言の存在確認
- LinkedIn 用免責文の付与・確認
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple


BANNED_WORDS: Tuple[str, ...] = (
    "絶対採択",
    "必ず採択",
    "採択保証",
    "採択確実",
    "確実に採択",
    "確実に受かる",
    "確実に取れる",
    "最短で採択",
    "100%採択",
    "100%通る",
    "100％採択",
    "100％通る",
    "誰でも採択",
    "簡単に採択",
    "裏ワザ",
    "特別ルート",
)

OFFICIAL_CHECK_TOKENS: Tuple[str, ...] = (
    "公式ページでご確認",
    "公式の公募要領",
    "公式要領",
    "公募要領をご確認",
    "公募要領で",
)

REQUIRED_DISCLAIMER = (
    "※本投稿は情報整理を目的とし、申請可否・採択可能性を保証するものではありません。"
    "最終確認は必ず公式の公募要領または専門家にてお願いします。"
)


@dataclass
class SafetyResult:
    ok: bool
    reasons: List[str] = field(default_factory=list)
    banned_hits: List[str] = field(default_factory=list)


def find_banned(body: str) -> List[str]:
    return [w for w in BANNED_WORDS if w in body]


def has_official_check(body: str) -> bool:
    return any(t in body for t in OFFICIAL_CHECK_TOKENS)


def has_disclaimer(body: str) -> bool:
    if REQUIRED_DISCLAIMER in body:
        return True
    return ("採択可能性を保証" in body) and (
        "公式の公募要領" in body or "公式要領" in body
    )


def ensure_disclaimer(body: str) -> str:
    if has_disclaimer(body):
        return body
    sep = "" if body.endswith("\n") else "\n\n"
    return f"{body}{sep}{REQUIRED_DISCLAIMER}"


def validate(body: str, sns: str) -> SafetyResult:
    reasons: List[str] = []
    banned = find_banned(body)
    if banned:
        reasons.append(f"禁止語句を含む: {banned}")
    if not has_official_check(body):
        reasons.append("公式確認文言が含まれていない")
    if sns == "linkedin" and not has_disclaimer(body):
        reasons.append("LinkedIn免責文が含まれていない")
    return SafetyResult(ok=not reasons, reasons=reasons, banned_hits=banned)
