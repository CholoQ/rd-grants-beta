"""SNS投稿テンプレート.

S2 では deadline_near テーマのみ実装する。
将来 Gemini を差し込む場合は generator.py 側で generation_method を
切り替える前提（ここではテンプレート文字列のみ返す）。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from . import SITE_URL
from .safety import REQUIRED_DISCLAIMER


X_LIMIT = 280


def _trim(text: Optional[str], limit: int) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 1)] + "…"


def _short_title(title: Optional[str], limit: int = 36) -> str:
    return _trim(title, limit)


def _short_catch(grant: Dict[str, Any], limit: int = 40) -> str:
    catch = grant.get("subsidy_catch_phrase") or grant.get("detail") or ""
    return _trim(catch, limit)


def _detail_excerpt(grant: Dict[str, Any], limit: int = 300) -> str:
    return _trim(grant.get("detail"), limit)


def _format_yen(amount: Any) -> str:
    if amount in (None, "", 0):
        return ""
    try:
        return f"{int(amount):,}円"
    except (TypeError, ValueError):
        return ""


def _format_period(start: Optional[str], end: Optional[str]) -> str:
    s = (start or "").split("T")[0]
    e = (end or "").split("T")[0]
    if s and e:
        return f"{s} 〜 {e}"
    return e or s or ""


def _source_label(source: Optional[str]) -> str:
    if not source:
        return ""
    s = source.lower()
    if "jgrants" in s:
        return "Jグランツ"
    if "nedo" in s:
        return "NEDO"
    if "jst" in s:
        return "JST"
    if "amed" in s:
        return "AMED"
    return source


def _public_url(grant: Dict[str, Any], fallback: str) -> str:
    return grant.get("front_subsidy_detail_page_url") or fallback


# ---- deadline_near : X ----

def render_deadline_near_x(
    grant: Dict[str, Any],
    days_until_deadline: int,
    site_url: str = SITE_URL,
) -> str:
    title = _short_title(grant.get("title"), limit=36)
    catch = _short_catch(grant, limit=40)

    def _build(t: str, c: str) -> str:
        return (
            f"【締切まで{days_until_deadline}日】{t}\n"
            f"{c}\n\n"
            f"▶ 詳細・条件は公式ページでご確認ください\n"
            f"{site_url}\n\n"
            f"#助成金 #研究開発 #締切間近"
        )

    body = _build(title, catch)
    if len(body) > X_LIMIT:
        over = len(body) - X_LIMIT
        new_len = max(len(catch) - over - 1, 12)
        catch = _trim(catch, new_len)
        body = _build(title, catch)
    return body


# ---- deadline_near : LinkedIn ----

def render_deadline_near_linkedin(
    grant: Dict[str, Any],
    days_until_deadline: int,
    site_url: str = SITE_URL,
) -> str:
    title = (grant.get("title") or "").strip()
    inst = (grant.get("institution_name") or "").strip()
    period = _format_period(
        grant.get("acceptance_start_datetime"),
        grant.get("acceptance_end_datetime"),
    )
    yen = _format_yen(grant.get("subsidy_max_limit"))
    rate = (grant.get("subsidy_rate") or "").strip()
    src_label = _source_label(grant.get("source"))
    detail = _detail_excerpt(grant, limit=300)
    detail_url = _public_url(grant, site_url)

    lines = [
        f"【締切まで{days_until_deadline}日｜注目の公募】",
        "",
        title,
        "",
    ]
    if inst:
        lines.append(f"◇ 実施機関：{inst}")
    if period:
        lines.append(f"◇ 募集期間:{period}")
    if yen:
        lines.append(f"◇ 助成上限:{yen}")
    if rate:
        lines.append(f"◇ 補助率:{rate}")
    if src_label:
        lines.append(f"◇ 出典:{src_label}")
    lines.append("")
    if detail:
        lines.append(detail)
        lines.append("")
    lines.append("▼ 公募の詳細・条件は公式ページでご確認ください")
    lines.append(detail_url)
    lines.append("")
    lines.append("—")
    lines.append("複数の公募を横断検索したい方はこちら：")
    lines.append(site_url)
    lines.append("")
    lines.append(
        "※本投稿は情報整理を目的とし、申請可否・採択可能性を保証するものではありません。"
        "最終確認は必ず公式の公募要領または専門家にてお願いします。"
    )
    lines.append("")
    lines.append("#助成金 #研究開発 #補助金 #締切間近")
    return "\n".join(lines)


# ===== S4: 共通レンダラ（新規テーマ用） =====

_THEME_META = {
    "poc": ("PoC・実証向け", "#助成金 #研究開発 #PoC #実証"),
    "ip": ("知財支援", "#助成金 #知財 #特許"),
    "startup": ("スタートアップ向け", "#助成金 #スタートアップ #創業"),
    "sme": ("中小企業向け", "#助成金 #中小企業 #補助金"),
}


def _build_x_simple(
    grant: Dict[str, Any],
    lead_text: str,
    hashtags: str,
    site_url: str,
) -> str:
    title = _short_title(grant.get("title"), limit=36)
    catch = _short_catch(grant, limit=40)

    def _build(t: str, c: str) -> str:
        return (
            f"【{lead_text}】{t}\n"
            f"{c}\n\n"
            f"▶ 詳細・条件は公式ページでご確認ください\n"
            f"{site_url}\n\n"
            f"{hashtags}"
        )

    body = _build(title, catch)
    if len(body) > X_LIMIT:
        over = len(body) - X_LIMIT
        new_len = max(len(catch) - over - 1, 12)
        catch = _trim(catch, new_len)
        body = _build(title, catch)
    return body


def _build_linkedin_simple(
    grant: Dict[str, Any],
    lead_text: str,
    hashtags: str,
    site_url: str,
) -> str:
    title = (grant.get("title") or "").strip()
    inst = (grant.get("institution_name") or "").strip()
    period = _format_period(
        grant.get("acceptance_start_datetime"),
        grant.get("acceptance_end_datetime"),
    )
    yen = _format_yen(grant.get("subsidy_max_limit"))
    rate = (grant.get("subsidy_rate") or "").strip()
    src_label = _source_label(grant.get("source"))
    detail = _detail_excerpt(grant, limit=300)
    detail_url = _public_url(grant, site_url)

    lines = [f"【{lead_text}｜注目の公募】", "", title, ""]
    if inst:
        lines.append(f"◇ 実施機関:{inst}")
    if period:
        lines.append(f"◇ 募集期間:{period}")
    if yen:
        lines.append(f"◇ 助成上限:{yen}")
    if rate:
        lines.append(f"◇ 補助率:{rate}")
    if src_label:
        lines.append(f"◇ 出典:{src_label}")
    lines.append("")
    if detail:
        lines.append(detail)
        lines.append("")
    lines.append("▼ 公募の詳細・条件は公式ページでご確認ください")
    lines.append(detail_url)
    lines.append("")
    lines.append("—")
    lines.append("複数の公募を横断検索したい方はこちら:")
    lines.append(site_url)
    lines.append("")
    lines.append(
        "※本投稿は情報整理を目的とし、申請可否・採択可能性を保証するものではありません。"
        "最終確認は必ず公式の公募要領または専門家にてお願いします。"
    )
    lines.append("")
    lines.append(hashtags)
    return "\n".join(lines)


# ---- poc ----
def render_poc_x(grant: Dict[str, Any], site_url: str = SITE_URL) -> str:
    lead, tags = _THEME_META["poc"]
    return _build_x_simple(grant, lead, tags, site_url)

def render_poc_linkedin(grant: Dict[str, Any], site_url: str = SITE_URL) -> str:
    lead, tags = _THEME_META["poc"]
    return _build_linkedin_simple(grant, lead, tags, site_url)


# ---- ip ----
def render_ip_x(grant: Dict[str, Any], site_url: str = SITE_URL) -> str:
    lead, tags = _THEME_META["ip"]
    return _build_x_simple(grant, lead, tags, site_url)

def render_ip_linkedin(grant: Dict[str, Any], site_url: str = SITE_URL) -> str:
    lead, tags = _THEME_META["ip"]
    return _build_linkedin_simple(grant, lead, tags, site_url)


# ---- startup ----
def render_startup_x(grant: Dict[str, Any], site_url: str = SITE_URL) -> str:
    lead, tags = _THEME_META["startup"]
    return _build_x_simple(grant, lead, tags, site_url)

def render_startup_linkedin(grant: Dict[str, Any], site_url: str = SITE_URL) -> str:
    lead, tags = _THEME_META["startup"]
    return _build_linkedin_simple(grant, lead, tags, site_url)


# ---- sme ----
def render_sme_x(grant: Dict[str, Any], site_url: str = SITE_URL) -> str:
    lead, tags = _THEME_META["sme"]
    return _build_x_simple(grant, lead, tags, site_url)

def render_sme_linkedin(grant: Dict[str, Any], site_url: str = SITE_URL) -> str:
    lead, tags = _THEME_META["sme"]
    return _build_linkedin_simple(grant, lead, tags, site_url)


# ===== S5: howto 固定ノウハウ投稿 =====

HOWTO_POSTS = [
    {
        "key": "phase",
        "lead": "研究フェーズ別の助成金の選び方",
        "x_body": (
            "🔎 研究フェーズ別の助成金の選び方\n"
            "・基礎/シーズ → 学術系の研究助成\n"
            "・PoC/試作 → 実証・スタートアップ系\n"
            "・量産/事業化 → 中小企業庁・自治体系\n\n"
            "▶ 公募要領は公式ページでご確認ください\n"
            "{site_url}\n\n#助成金 #研究開発"
        ),
        "linkedin_body": (
            "【研究フェーズ別の助成金の選び方】\n\n"
            "助成金は研究のフェーズで選び方が変わります。\n"
            "・基礎/シーズ：学術系の研究助成（科研費・JST戦略創造 等）\n"
            "・PoC/試作：実証・スタートアップ向け補助金\n"
            "・量産/事業化:中小企業庁・自治体の事業化支援\n\n"
            "▼ 各制度の詳細・条件は必ず公式ページでご確認ください\n"
            "{site_url}\n\n"
            "{disclaimer}\n\n"
            "#助成金 #研究開発 #補助金"
        ),
    },
    {
        "key": "poc_vs_jissho",
        "lead": "PoC向けと実証向け公募の違い",
        "x_body": (
            "💡 PoCと実証、公募はどう違う？\n"
            "・PoC：技術的な可行性を確かめる初期段階\n"
            "・実証：社会実装を見据えた中規模実験\n"
            "予算・採択件数・期間が変わります。\n\n"
            "▶ 公募要領は公式ページでご確認ください\n"
            "{site_url}\n\n#助成金 #PoC"
        ),
        "linkedin_body": (
            "【PoC向けと実証向け公募の違い】\n\n"
            "「PoC」と「実証」は似ているようで、対象とする段階が違います。\n"
            "・PoC：技術的な可行性検証。小規模・短期間が中心\n"
            "・実証：社会実装を見据えた中〜大規模実験\n"
            "・予算上限・採択件数・期間が大きく異なる\n\n"
            "応募前に、自社の段階がどちらに該当するか必ず確認しましょう。\n\n"
            "▼ 各制度の詳細・条件は必ず公式ページでご確認ください\n"
            "{site_url}\n\n"
            "{disclaimer}\n\n"
            "#助成金 #PoC #実証"
        ),
    },
    {
        "key": "ip_overlooked",
        "lead": "知財・商標関連費用の見落とし",
        "x_body": (
            "📑 知財費用が対象になる助成金もあります\n"
            "・特許出願料・PCT出願費用\n"
            "・商標登録費用\n"
            "・弁理士費用（一部）\n"
            "事業化フェーズで見落としがち。\n\n"
            "▶ 公募要領は公式ページでご確認ください\n"
            "{site_url}\n\n#助成金 #知財"
        ),
        "linkedin_body": (
            "【知財・商標関連費用の見落とし】\n\n"
            "事業化フェーズの公募では、知財関連費用が対象経費に含まれていることがあります。\n"
            "・特許出願料・PCT出願費用\n"
            "・商標登録費用\n"
            "・弁理士費用（一部対象）\n"
            "・先行調査費\n\n"
            "「ハードしか申請できない」と思い込む前に、対象経費の項目を確認しましょう。\n\n"
            "▼ 各制度の詳細・条件は必ず公式ページでご確認ください\n"
            "{site_url}\n\n"
            "{disclaimer}\n\n"
            "#助成金 #知財 #特許"
        ),
    },
    {
        "key": "target_costs",
        "lead": "対象経費の見方｜最初の3項目",
        "x_body": (
            "💰 公募の「対象経費」、最初に見るべき3つ\n"
            "・人件費の扱い（社内/外部）\n"
            "・設備費の上限\n"
            "・委託費・外注費の比率\n"
            "ここが合わないと採択後に困ります。\n\n"
            "▶ 公募要領は公式ページでご確認ください\n"
            "{site_url}\n\n#助成金 #補助金"
        ),
        "linkedin_body": (
            "【対象経費の見方｜最初に見る3項目】\n\n"
            "採択後に困らないために、応募前に対象経費を確認しましょう。\n"
            "・人件費の扱い（社内人件費が認められるか）\n"
            "・設備費の上限額・按分ルール\n"
            "・委託費・外注費の比率上限\n\n"
            "「自社の支出構造に合わない」公募は、採択されても執行に苦労します。\n\n"
            "▼ 各制度の詳細・条件は必ず公式ページでご確認ください\n"
            "{site_url}\n\n"
            "{disclaimer}\n\n"
            "#助成金 #補助金 #研究開発"
        ),
    },
    {
        "key": "koubo_yoryo",
        "lead": "公募要領で最初に見るべき4箇所",
        "x_body": (
            "📌 公募要領、最初に見るべき4箇所\n"
            "1. 対象者の要件\n"
            "2. 対象経費の範囲\n"
            "3. 補助率・上限額\n"
            "4. スケジュール（締切・事業期間）\n\n"
            "▶ 公募要領は公式ページでご確認ください\n"
            "{site_url}\n\n#助成金 #補助金"
        ),
        "linkedin_body": (
            "【公募要領で最初に見るべき4箇所】\n\n"
            "公募要領は分量が多いですが、最初に見るべき箇所は4つだけです。\n"
            "1. 対象者の要件（業種・規模・地域）\n"
            "2. 対象経費の範囲\n"
            "3. 補助率・上限額\n"
            "4. スケジュール（締切・交付決定・事業期間）\n\n"
            "ここで「合わない」と分かれば、それ以降を読まずに次の公募に進めます。\n\n"
            "▼ 各制度の詳細・条件は必ず公式ページでご確認ください\n"
            "{site_url}\n\n"
            "{disclaimer}\n\n"
            "#助成金 #補助金 #公募要領"
        ),
    },
]


def render_howto_x(post: Dict[str, Any], site_url: str = SITE_URL) -> str:
    return post["x_body"].format(site_url=site_url)


def render_howto_linkedin(post: Dict[str, Any], site_url: str = SITE_URL) -> str:
    return post["linkedin_body"].format(
        site_url=site_url,
        disclaimer=REQUIRED_DISCLAIMER,
    )
