from __future__ import annotations

from typing import Dict, List, Optional
import re

from .config import LEGAL_DISCLAIMER, GEMINI_MODEL, logger
from .repository import get_grant_by_id, get_grants_by_ids, prepare_item, get_grant_summary_cache, upsert_grant_summary_cache
from .utils import strip_html, unique
from .detail_fetch import fetch_detail_bundle, merged_source_text, extract_budget_text, extract_deadline_text, extract_field_text, extract_embedded_guideline_pdf
from .gemini_summary import summarize_grant_with_gemini
from .status_utils import effective_status
from hashlib import sha256

SUMMARY_CACHE_VERSION = "summary-v3-friendly"

FUNDING_ALLOW_TERMS = [
    "補助金", "助成金", "委託", "委託費", "研究費", "支援", "公募", "募集", "提案募集",
    "SBIR", "事業化", "実証", "PoC", "概念実証", "スタートアップ", "基金", "開発費",
    "アクセラ", "アクセラレーター", "活動資金", "実証支援", "協業費", "共創",
    "GAPファンド", "ギャップファンド", "STS", "DTSU", "自治体実証", "実証フィールド",
]

FUNDING_STRONG_ALLOW_TERMS = [
    "補助", "助成", "委託", "研究開発", "提案", "事業費", "実証", "PoC", "概念実証",
    "A-STEP", "SBIR", "D-Global", "START", "大学発新産業創出基金", "アクセラ", "活動資金", "支援金",
    "GAPファンド", "ギャップファンド", "NEDO", "STS", "DTSU",
]

FUNDING_DENY_TERMS = [
    "データベース", "センター", "利用申請", "利用募集", "施設利用", "共用施設", "設備利用",
    "研究員募集", "採用", "公募説明会", "説明会", "イベント", "シンポジウム", "セミナー",
    "ワークショップ", "コンテスト", "表彰", "お知らせ", "ニュース", "データ公開", "登録受付",
    "NBDC", "バイオサイエンスデータベースセンター",
]

FUNDING_DENY_URL_TERMS = [
    "/event/", "/sympo/", "/seminar/", "/news/", "/press/",
]


def is_funding_support_candidate(title: str, detail: str = "", href: Optional[str] = None) -> bool:
    hay = f"{title} {detail}".lower()
    if any(term.lower() in hay for term in FUNDING_DENY_TERMS):
        return False
    if href:
        low = href.lower()
        if any(term in low for term in FUNDING_DENY_URL_TERMS):
            return False
    strong = any(term.lower() in hay for term in FUNDING_STRONG_ALLOW_TERMS)
    allow = any(term.lower() in hay for term in FUNDING_ALLOW_TERMS)
    return strong or allow


def funding_type_label(title: str, detail: str = "") -> str:
    hay = f"{title} {detail}".lower()
    if any(term in hay for term in ["gapファンド", "ギャップファンド", "大学発新産業創出基金"]):
        return "GAPファンド"
    if any(term in hay for term in ["nedo", "sts", "dtsu", "sbir"]):
        return "研究開発型スタートアップ支援"
    if any(term in hay for term in ["アクセラ", "アクセラレーター", "活動資金", "実証支援", "協業費", "共創", "実証フィールド"]):
        return "アクセラ・活動資金"
    if "補助" in hay:
        return "補助金"
    if "助成" in hay:
        return "助成金"
    if "委託" in hay:
        return "委託"
    if "sbir" in hay:
        return "SBIR"
    if "基金" in hay:
        return "基金・支援"
    return "研究開発支援"


def _text_list(*values: str) -> List[str]:
    out: List[str] = []
    for v in values:
        text = strip_html(v or "")
        if text:
            out.append(text)
    return out


def _infer_documents(item: Dict) -> List[str]:
    docs: List[str] = []
    text = f"{item.get('title') or ''} {item.get('detail') or ''} {item.get('use_purpose') or ''}".lower()

    def add(label: str) -> None:
        if label not in docs:
            docs.append(label)

    add("申請書・応募フォーム")
    add("事業計画書")
    if any(k in text for k in ["研究", "実証", "poc", "試作", "開発", "技術"]):
        add("研究開発計画書（目的・体制・スケジュール）")
    add("経費明細・資金計画")
    if any(k in text for k in ["会社概要", "法人", "企業", "中小企業", "事業者"]):
        add("会社概要・事業概要資料")
    if any(k in text for k in ["決算", "財務", "貸借対照表", "損益計算書"]):
        add("直近の決算書・財務資料")
    if any(k in text for k in ["納税", "税"]):
        add("納税証明書")
    if any(k in text for k in ["見積", "設備", "装置", "機器", "導入", "外注", "委託"]):
        add("見積書・仕様書・カタログ")
    if any(k in text for k in ["共同", "連携", "コンソーシアム", "大学", "研究機関"]):
        add("共同実施者の役割分担・同意書")
    if any(k in text for k in ["gビズ", "gbiz", "jグランツ", "jgrants", "電子申請"]):
        add("GビズIDプライム")
    if any(k in text for k in ["特許", "知財", "商標"]):
        add("知財・特許の説明資料")
    return docs[:8]


def _infer_expenses(item: Dict) -> List[str]:
    text = f"{item.get('detail') or ''} {item.get('use_purpose') or ''} {item.get('title') or ''}".lower()
    mapping = [
        ("人件費", ["人件費", "研究員", "開発者"]),
        ("設備費", ["設備", "装置", "機器", "導入"]),
        ("委託費", ["委託", "外注"]),
        ("試作費", ["試作", "プロトタイプ", "poc"]),
        ("実証費", ["実証", "フィールド", "検証"]),
        ("知財費", ["特許", "知財", "商標"]),
    ]
    hits = [label for label, kws in mapping if any(k in text for k in kws)]
    return hits or ["要確認"]



def _summarize_text(text: str, limit: int = 110) -> str:
    plain = strip_html(text or '')
    plain = re.sub(r'\s+', ' ', plain).strip()
    if not plain:
        return '要確認'
    return plain[:limit] + ('…' if len(plain) > limit else '')


def _clean_public_text(text: str, limit: int = 140) -> str:
    plain = strip_html(text or "")
    plain = re.sub(r"\s+", " ", plain).strip()
    plain = re.sub(r"^[■●◆◇・\s]*(目的・概要|概要|趣旨|事業の目的|応募資格|対象者|補助内容|募集要項)[：:、\s]*", "", plain)
    plain = plain.strip(" 。:：・")
    if not plain:
        return ""
    if len(plain) > limit:
        plain = plain[:limit].rstrip() + "…"
    return plain


def _split_clean_sentences(text: str) -> List[str]:
    chunks = re.split(r"[。\n]", strip_html(text or ""))
    out: List[str] = []
    for chunk in chunks:
        cleaned = _clean_public_text(chunk, 220)
        if len(cleaned) < 8:
            continue
        if any(noise in cleaned for noise in ["目 次", "目次", "・・・・", "......", ".........."]):
            continue
        out.append(cleaned)
    return unique(out)


def _plain_hay(item: Dict, combined_text: str = "") -> str:
    return " ".join([
        str(item.get("title") or ""),
        str(item.get("system_name") or ""),
        str(item.get("institution_name") or ""),
        str(item.get("industry") or ""),
        str(item.get("use_purpose") or ""),
        str(item.get("detail_plain") or ""),
        str(combined_text or ""),
    ]).lower()


def _friendly_region(item: Dict, text: str) -> str:
    region = (item.get("target_area_search") or "").strip()
    if region and region not in {"全国", "日本全国", "国内全域"}:
        return region
    if "北海道" in text or "道内" in text:
        return "北海道"
    city_match = re.search(r"([一-龥ぁ-んァ-ヶ]+市)(?:内|に所在|に本社|の事業者)", text)
    if city_match:
        return city_match.group(1)
    pref_match = re.search(r"([一-龥ぁ-んァ-ヶ]+(?:都|道|府|県))(?:内|に所在|に本社|の事業者)", text)
    if pref_match:
        return pref_match.group(1)
    return region or ""


def _friendly_applicant_phrase(item: Dict, combined_text: str) -> str:
    text = _plain_hay(item, combined_text)
    region = _friendly_region(item, text)
    region_prefix = f"{region}の" if region and region not in {"全国", "日本全国", "国内全域"} else ""
    if "大学発" in text or "大学等発" in text or "大学等発スタートアップ" in text:
        return f"{region_prefix}大学発スタートアップや研究成果を事業化するチーム"
    if "研究開発型スタートアップ" in text or "スタートアップ" in text:
        return f"{region_prefix}研究開発型スタートアップ"
    if "中小企業" in text and "小規模事業者" in text:
        return f"{region_prefix}中小企業・小規模事業者など"
    if "中小企業者" in text:
        return f"{region_prefix}中小企業者など"
    if "大学" in text and ("研究機関" in text or "研究者" in text):
        return f"{region_prefix}大学・研究機関など"
    if "事業者" in text:
        return f"{region_prefix}事業者"
    return f"{region_prefix}応募条件に合う事業者"


def _friendly_use_phrase(item: Dict, combined_text: str) -> str:
    text = _plain_hay(item, combined_text)
    if any(k in text for k in ["海外出願", "外国出願"]):
        return "国内で出願済みの特許・商標などを海外にも出願する費用"
    if any(k in text for k in ["gapファンド", "ギャップファンド"]):
        return "研究成果を事業化へ進めるための検証・試作・市場確認"
    if any(k in text for k in ["アクセラ", "アクセラレーター", "共創", "協業", "活動資金"]):
        return "実証先探し、伴走支援、PoCや事業化準備"
    if any(k in text for k in ["実証", "poc", "概念実証", "フィールド"]):
        return "PoCや実証実験、社会実装前の検証"
    if any(k in text for k in ["試作", "プロトタイプ", "革新的サービス開発", "新商品", "新製品"]):
        return "新しいサービス・試作品の開発"
    if any(k in text for k in ["生産プロセス", "設備投資", "設備", "装置", "機器"]):
        return "生産性向上や開発に必要な設備投資"
    if any(k in text for k in ["販路", "展示会", "海外展開"]):
        return "販路開拓や海外展開の準備"
    if any(k in text for k in ["研究開発", "開発"]):
        return "研究開発や追加開発"
    return "事業化に向けた取り組み"


def _friendly_budget_tail(item: Dict, combined_text: str) -> str:
    max_limit = item.get("subsidy_max_limit")
    bits: List[str] = []
    if isinstance(max_limit, (int, float)) and max_limit > 0:
        if max_limit >= 100_000_000:
            bits.append(f"上限は約{max_limit / 100_000_000:g}億円")
        elif max_limit >= 10_000:
            bits.append(f"上限は約{int(max_limit / 10_000):,}万円")
        else:
            bits.append(f"上限は{int(max_limit):,}円")
    rate = item.get("subsidy_rate")
    if rate:
        bits.append(f"補助率は{rate}")
    if bits:
        return "（" + "、".join(bits[:2]) + "）"
    budget = extract_budget_text(combined_text, item.get("subsidy_rate"), item.get("subsidy_max_limit"))
    if budget and budget != "要確認":
        return f"（金額目安: {_clean_public_text(budget, 60)}）"
    return ""


def _friendly_overview(item: Dict, combined_text: str) -> str:
    applicant = _friendly_applicant_phrase(item, combined_text)
    use = _friendly_use_phrase(item, combined_text)
    kind = funding_type_label(item.get("title") or "", combined_text)
    tail = _friendly_budget_tail(item, combined_text)
    return f"{applicant}が、{use}に使える{kind}です{tail}。"


def _friendly_purpose(item: Dict, combined_text: str) -> str:
    text = _plain_hay(item, combined_text)
    if any(k in text for k in ["ものづくり", "革新的サービス開発", "生産プロセス"]):
        return "新しい製品・サービスづくりや生産性向上の投資を後押しする制度です。"
    if any(k in text for k in ["海外出願", "外国出願"]):
        return "国内で守っている知財を海外展開にも使えるよう、出願費用の負担を軽くする制度です。"
    if any(k in text for k in ["フードテック", "食品", "食料"]):
        return "食品・フードテックの技術を、実証や事業化に近づけるための制度です。"
    if any(k in text for k in ["gapファンド", "ギャップファンド", "大学発"]):
        return "研究成果を事業化に近づけるため、PoC・試作・顧客検証の最初の資金を支える制度です。"
    if any(k in text for k in ["アクセラ", "共創", "協業"]):
        return "資金だけでなく、実証先や伴走支援も含めて事業化の前進を助ける制度です。"
    if any(k in text for k in ["実証", "poc", "概念実証", "社会実装"]):
        return "机上の研究や試作を、実際の現場で確かめる段階へ進める制度です。"
    for key in ["目的", "趣旨", "概要", "事業概要", "狙い"]:
        hit = next((s for s in _split_clean_sentences(combined_text) if key in s), "")
        if hit and "参照" not in hit and not _looks_like_raw_excerpt(hit):
            return _clean_public_text(hit, 120)
    return _infer_purpose(item)


def _friendly_target_conditions(item: Dict, combined_text: str) -> List[str]:
    text = _plain_hay(item, combined_text)
    out: List[str] = []

    def add(label: str) -> None:
        cleaned = _clean_public_text(label, 90)
        if not cleaned:
            return
        vague = ["別添", "募集要項をご参照", "ご参照ください", "詳細は", "書類一式"]
        if any(v in cleaned for v in vague):
            return
        if cleaned not in out:
            out.append(cleaned)

    if "日本国内に本社及び補助事業の実施場所" in text:
        add("日本国内に本社と実施場所がある中小企業者・NPO・社会福祉法人")
    elif "道内の中小企業" in text or "北海道内の中小企業" in text:
        add("北海道内の中小企業者など")
    elif "道内に事業所を有する中小企業" in text:
        add("北海道内に事業所がある中小企業者または中小企業グループ")
    elif "中小企業" in text and "小規模事業者" in text:
        add("中小企業・小規模事業者など")
    elif "中小企業者" in text:
        add("中小企業者など")
    elif "大学発" in text or "大学等発" in text:
        add("大学・研究機関の研究成果をもとにしたスタートアップや事業化チーム")
    elif "スタートアップ" in text:
        add("スタートアップ、またはスタートアップと連携する事業者")

    if not out:
        for sentence in _split_clean_sentences(combined_text):
            if len(out) >= 2:
                break
            if any(k in sentence for k in ["応募資格", "補助対象者", "対象者", "応募対象", "対象となる事業者"]):
                if any(noise in sentence for noise in ["次の①", "第１号", "第1号", "規定する", "別紙", "様式"]):
                    continue
                add(sentence)

    employees = (item.get("target_number_of_employees") or "").strip()
    if employees and not any(k in employees for k in ("制限なし", "制約なし", "なし", "全規模", "問わない", "指定なし")):
        add(f"従業員数: {employees}")

    region = (item.get("target_area_search") or "").strip()
    if region:
        add(f"対象地域: {region}")

    industry = (item.get("industry") or "").strip()
    if industry:
        industries = [x.strip() for x in re.split(r"[/／,、]", industry) if x.strip()]
        if len(industries) >= 6:
            add("業種: 幅広い業種が対象。自社業種が含まれるかだけ確認")
        else:
            add(f"業種: {'、'.join(industries[:4])}")

    if not out:
        out.append("対象者の記載が読み取りづらいです。所在地・法人種別・企業単独応募の可否を先に確認してください")
    return out[:5]


def _friendly_suitable_for(item: Dict, combined_text: str) -> List[str]:
    applicant = _friendly_applicant_phrase(item, combined_text)
    use = _friendly_use_phrase(item, combined_text)
    first = f"{use}に使いたい{applicant}" if use.endswith("費用") else f"{use}を進めたい{applicant}"
    out = [first]
    text = _plain_hay(item, combined_text)
    region = _friendly_region(item, text)
    if region and region not in {"全国", "日本全国", "国内全域"}:
        out.append(f"{region}に拠点または実施場所がある会社")
    if any(k in text for k in ["見積", "設備", "装置", "外注"]):
        out.append("見積や仕様を具体化できている会社")
    if any(k in text for k in ["共同", "連携", "大学", "研究機関"]):
        out.append("共同研究先や連携先を説明できる会社")
    return unique(out)[:4]


def _friendly_not_suitable_for(item: Dict, combined_text: str) -> List[str]:
    out: List[str] = []
    if effective_status(item) == "closed":
        out.append("今回の締切に間に合わない会社")
    text = _plain_hay(item, combined_text)
    region = _friendly_region(item, text)
    if region and region not in {"全国", "日本全国", "国内全域"}:
        out.append(f"{region}に拠点・実施場所がない会社")
    if any(k in text for k in ["海外出願", "外国出願"]):
        out.append("まだ国内出願をしていない知財で使いたい会社")
    if any(k in text for k in ["設備投資", "設備", "装置"]) and not any(k in text for k in ["人件費", "研究員"]):
        out.append("人件費だけを主な用途にしたい会社")
    if any(k in text for k in ["大学発", "大学等発"]) and "企業単独" not in text:
        out.append("大学・研究機関との関係を説明できない会社")
    return out[:4] or ["対象条件が細かいため、所在地・法人種別・使いたい費用が合わない会社"]


def _looks_like_raw_excerpt(value: object) -> bool:
    text = " ".join(value) if isinstance(value, list) else str(value or "")
    if not text or text == "要確認":
        return False
    raw_markers = [
        "■", "目 次", "目次", "・・・・", "..........", "ご参照ください", "別添の募集要項",
        "font-size", "<p", "</", "第１章", "第1章",
    ]
    if any(marker in text for marker in raw_markers):
        return True
    return len(text) > 180 and any(k in text for k in ["目的", "概要", "応募資格", "補助率", "補助対象"])


def _infer_field(item: Dict) -> str:
    text = f"{item.get('title') or ''} {item.get('detail') or ''} {item.get('industry') or ''}".lower()
    mapping = [
        ('AI・ソフトウェア', ['ai', '人工知能', 'ソフトウェア', 'データ']),
        ('バイオ・医療', ['バイオ', '医療', '創薬', 'ヘルスケア', '医療機器']),
        ('アグリ・フードテック', ['農業', 'アグリ', 'food', '食品', 'フード']),
        ('エネルギー・GX', ['エネルギー', 'gx', '脱炭素', '水素', '再エネ']),
        ('宇宙', ['宇宙', '衛星', 'ロケット']),
        ('材料・化学', ['材料', '素材', '化学']),
        ('ロボティクス・製造', ['ロボ', '製造', 'ものづくり']),
        ('半導体・電子', ['半導体', '電子']),
    ]
    for label, kws in mapping:
        if any(k in text for k in kws):
            return label
    return '要確認'


def _infer_purpose(item: Dict) -> str:
    text = f"{item.get('title') or ''} {item.get('detail') or ''} {item.get('use_purpose') or ''}".lower()
    if any(k in text for k in ['実証', 'poc', '概念実証', '社会実装']):
        return 'PoCや実証、社会実装前の検証を進めたい事業向けです'
    if any(k in text for k in ['試作', 'プロトタイプ', '開発']):
        return '試作や研究開発を前に進めたい事業向けです'
    if any(k in text for k in ['設備', '装置', '機器']):
        return '研究開発に必要な設備や装置導入を含む事業向けです'
    return '研究開発や事業化に向けた取り組みを支える制度です'


def _budget_label(item: Dict) -> str:
    rate = item.get('subsidy_rate') or '要確認'
    max_limit = item.get('subsidy_max_limit')
    amount = f"上限{int(max_limit):,}円" if max_limit else '上限要確認'
    return f"{amount} / 補助率{rate}" if rate != '要確認' else amount

def _sanitize_summary_value(value, fallback='要確認'):
    if isinstance(value, list):
        cleaned = []
        for v in value:
            sv = _sanitize_summary_value(v, '')
            if sv and sv != '要確認' and sv not in cleaned:
                cleaned.append(sv)
        return cleaned
    text = strip_html(str(value or ''))
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return fallback
    if '目次' in text or '..........' in text or '……' in text:
        return fallback
    if len(text) > 180:
        text = text[:180].rstrip() + '…'
    return text


def _looks_meaningful(value):
    if isinstance(value, list):
        return any(_looks_meaningful(v) for v in value)
    text = str(value or '').strip()
    if not text or text == '要確認':
        return False
    bad = [
        '目次', '........', '……', '第1章', '第2章', '1.1.1',
        '公募要領に記載', '書類一式', '公式公募要領で確認', '公式要領で確認',
        '詳細は公式', '対象条件・締切・必要書類',
    ]
    return not any(b in text for b in bad)


def _meaningful_list(value, fallback: List[str]) -> List[str]:
    raw = value if isinstance(value, list) else ([value] if value else [])
    out = []
    for item in raw:
        text = _sanitize_summary_value(item, '')
        if _looks_meaningful(text) and text not in out:
            out.append(text)
    return out or fallback


def _find_context_sentences(text: str, keywords: List[str], limit: int = 3) -> List[str]:
    chunks = re.split(r'[。\n]', strip_html(text or ''))
    hits: List[str] = []
    for chunk in chunks:
        cleaned = re.sub(r'\s+', ' ', chunk).strip(' ・:：\t')
        if len(cleaned) < 6:
            continue
        if any(k.lower() in cleaned.lower() for k in keywords):
            hits.append(_sanitize_summary_value(cleaned[:120], ''))
        if len(hits) >= limit:
            break
    return unique([h for h in hits if h])


def _is_generic_legal_noise(text: str) -> bool:
    lowered = (text or "").lower()
    noise_terms = [
        "暴力団", "反社会的", "反社", "役員等", "資金等を供給", "便宜を供与",
        "公序良俗", "虚偽", "法令違反", "適正化法",
    ]
    return any(term.lower() in lowered for term in noise_terms)


def _infer_ineligible_or_unclear(combined_text: str) -> List[str]:
    hits = _find_context_sentences(combined_text, ["対象外", "補助対象外", "助成対象外", "対象とならない", "認められません", "交付決定前"], 4)
    hits = [h for h in hits if not _is_generic_legal_noise(h)]
    if hits:
        return hits[:4]
    return [
        "交付決定前に発注・契約した費用は対象外になりやすいです",
        "事業と直接関係しない汎用備品・通常経費は対象外になりやすいです",
    ]


def _gemini_extract_summary(item: Dict, bundle: Dict[str, object], combined_text: str) -> Optional[Dict[str, object]]:
    if not GEMINI_API_KEY:
        return None
    source_text = (combined_text or '')[:18000]
    if len(source_text) < 300:
        return None
    prompt = f"""あなたは日本の研究開発公募要領を読むアナリストです。以下の公募資料テキストを読み、一覧比較しやすい形で日本語JSONを返してください。
ルール:
- 目次、ページ番号、章見出しだけを返さない
- 分からない項目は "要確認" とする
- 原文にない断定をしない
- なるべく短く、実務で使える表現にする
- 予算は上限や補助率が分かれば含める
- 締切は日付が分かればそれを返す
返すキー:
purpose, target_conditions, field, budget, deadline, eligible_expenses, required_documents, cautions, application_steps, overview

制度名: {item.get('title') or ''}

資料テキスト:
{source_text}
"""
    schema = {
        "type": "object",
        "properties": {
            "purpose": {"type": "string"},
            "target_conditions": {"type": "array", "items": {"type": "string"}},
            "field": {"type": "string"},
            "budget": {"type": "string"},
            "deadline": {"type": "string"},
            "eligible_expenses": {"type": "array", "items": {"type": "string"}},
            "required_documents": {"type": "array", "items": {"type": "string"}},
            "cautions": {"type": "array", "items": {"type": "string"}},
            "application_steps": {"type": "array", "items": {"type": "string"}},
            "overview": {"type": "string"}
        },
        "required": ["purpose", "target_conditions", "field", "budget", "deadline", "eligible_expenses", "required_documents", "cautions", "application_steps", "overview"],
        "additionalProperties": False
    }
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
        },
    }
    url = f"{GEMINI_BASE_URL}/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    try:
        req = Request(url, data=json.dumps(body).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with urlopen(req, timeout=45) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        candidates = payload.get('candidates') or []
        parts = (((candidates[0] or {}).get('content') or {}).get('parts') or []) if candidates else []
        raw = '\n'.join(part.get('text', '') for part in parts if isinstance(part, dict)).strip()
        raw = re.sub(r'^```(?:json)?|```$', '', raw, flags=re.MULTILINE).strip()
        data = json.loads(raw)
    except Exception as exc:
        logger.info('gemini grant summary extraction failed: %s', exc)
        return None
    cleaned = {
        'purpose': _sanitize_summary_value(data.get('purpose')),
        'target_conditions': _sanitize_summary_value(data.get('target_conditions', [])),
        'field': _sanitize_summary_value(data.get('field')),
        'budget': _sanitize_summary_value(data.get('budget')),
        'deadline': _sanitize_summary_value(data.get('deadline')),
        'eligible_expenses': _sanitize_summary_value(data.get('eligible_expenses', [])),
        'required_documents': _sanitize_summary_value(data.get('required_documents', [])),
        'cautions': _sanitize_summary_value(data.get('cautions', [])),
        'application_steps': _sanitize_summary_value(data.get('application_steps', [])),
        'overview': _sanitize_summary_value(data.get('overview')),
    }
    meaningful_count = sum(1 for k,v in cleaned.items() if _looks_meaningful(v))
    return cleaned if meaningful_count >= 4 else None


def _build_exclusion_risks(item: Dict, combined_text: str, cautions_list: List[str]) -> List[Dict]:
    risks: List[Dict] = []
    text = (combined_text or "") + " " + " ".join(cautions_list or [])
    if effective_status(item) == "closed":
        risks.append({"label": "締切を過ぎているため、この回には応募できません", "level": "high"})
    region = (item.get("target_area_search") or "").strip()
    if region and "全国" not in region:
        risks.append({"label": f"対象地域が限られます（{region}）", "level": "high"})
    if effective_status(item) == "upcoming":
        risks.append({"label": "募集開始前のため、受付開始日まで申請できません", "level": "medium"})
    employees = (item.get("target_number_of_employees") or "").strip()
    if employees and not any(k in employees for k in ("制限なし", "制約なし", "なし", "全規模", "問わない", "指定なし")):
        risks.append({"label": f"従業員数の条件があります（{employees}）", "level": "medium"})
    for sentence in _find_context_sentences(text, ["対象外", "補助対象外", "対象とならない", "認められません"], 2):
        if _is_generic_legal_noise(sentence):
            continue
        risks.append({"label": sentence, "level": "medium"})
    if not risks:
        risks.append({"label": "本文上、大きな対象外リスクは目立ちません。地域・経費・事前着手だけ先に確認しましょう", "level": "low"})
    return risks[:6]


def _build_difficulty(item: Dict, combined_text: str, required_documents: List[str]) -> Dict:
    reasons: List[str] = []
    score = 2
    doc_count = len(required_documents or [])
    if doc_count >= 6:
        score += 1
        reasons.append(f"書類量: {doc_count}点前後。標準的な小型公募（3〜4点）より重めです")
        heavy_docs = []
        for doc in required_documents:
            if any(k in doc for k in ["事業計画", "研究開発計画", "取組内容", "経費", "決算", "定款", "見積"]):
                heavy_docs.append(doc)
        if heavy_docs:
            reasons.append(f"重い書類: {'、'.join(heavy_docs[:3])}")
    if not item.get("subsidy_rate"):
        score += 1
        reasons.append("補助率がすぐに読めないため、経費計画の確認に時間がかかりそうです")
    if not item.get("detail_plain") and not (combined_text or "").strip():
        score += 1
        reasons.append("公開情報が少なく、申請条件の読み取りに時間がかかりそうです")
    max_limit = item.get("subsidy_max_limit") or 0
    if isinstance(max_limit, (int, float)) and max_limit >= 100_000_000:
        score += 1
        reasons.append("大型案件のため事業計画の精度が求められる可能性があります")
    lower = (combined_text or "").lower()
    if any(k in lower for k in ["事前相談", "事前協議"]):
        score += 1
        reasons.append("申請前の事前相談が必要になりそうです")
    if any(k in lower for k in ["コンソーシアム", "共同", "連携機関"]):
        score += 1
        reasons.append("共同実施者や役割分担の整理が必要になりそうです")
    if any(k in lower for k in ["見積", "設備", "装置"]):
        reasons.append("設備・外注費: 見積や仕様の整理が必要です")
    if score < 1:
        score = 1
    if score > 5:
        score = 5
    label_map = {1: "低", 2: "やや低", 3: "中", 4: "やや高", 5: "高"}
    label = label_map.get(score, "中")
    if not reasons:
        reasons.append("申請書と事業計画を中心に準備する、一般的な研究開発公募の重さです")
    return {"score": score, "label": label, "reasons": reasons[:4]}


def _build_prep_load(difficulty: Dict) -> Dict:
    score = difficulty.get("score", 3)
    table = {1: (1, 2), 2: (2, 3), 3: (2, 4), 4: (4, 8), 5: (6, 10)}
    w_min, w_max = table.get(score, (2, 4))
    return {"weeks_min": w_min, "weeks_max": w_max, "label": f"{w_min}〜{w_max}週間（目安）"}


def _build_expert_needed(difficulty: Dict, item: Dict, combined_text: str) -> Dict:
    score = difficulty.get("score", 3)
    text = f"{item.get('title') or ''} {combined_text or ''}".lower()
    types = ["中小企業診断士"]
    if any(k in text for k in ["特許", "知財", "商標"]):
        types.append("弁理士")
    if any(k in text for k in ["許認可", "申請", "行政"]):
        types.append("行政書士")
    if any(k in text for k in ["決算", "会計", "経理"]):
        types.append("税理士・公認会計士")
    if score >= 4:
        return {"level": "high", "label": "専門家への相談を強く検討してください", "types": types[:3]}
    if score == 3:
        return {"level": "recommended", "label": "専門家への相談を検討してください", "types": types[:3]}
    return {"level": "optional", "label": "必要に応じて専門家への相談を検討してください", "types": types[:2]}


def build_grant_summary(grant_id: str) -> Dict:
    item = get_grant_by_id(grant_id)
    if not item:
        raise ValueError("指定した制度が見つかりません")
    item = prepare_item(item)
    item["status"] = effective_status(item)
    official_url = item.get("safe_public_url") or item.get("front_subsidy_detail_page_url")
    bundle = fetch_detail_bundle(official_url or "")
    embedded_pdf = extract_embedded_guideline_pdf(item)
    if embedded_pdf.get("pdf_text"):
        bundle = dict(bundle)
        bundle["pdf_text"] = embedded_pdf.get("pdf_text")
        if embedded_pdf.get("pdf_name"):
            bundle["pdf_url"] = embedded_pdf.get("pdf_name")
        notes = list(bundle.get("notes") or [])
        if embedded_pdf.get("note"):
            notes.insert(0, str(embedded_pdf.get("note")))
        notes = [n for n in notes if "公募要領PDFは見つかりません" not in n and "詳細ページ本文は取得できません" not in n]
        bundle["notes"] = unique(notes)
    combined_text = merged_source_text(item, bundle)
    source_text_hash = sha256((SUMMARY_CACHE_VERSION + "\n" + (combined_text or "")).encode("utf-8")).hexdigest()

    cached = get_grant_summary_cache(str(item.get("id") or ""), source_text_hash)
    fixed_ai_summary = cached.get("summary") if cached else None
    summary_source = "cache" if fixed_ai_summary else "rule_based"

    if not fixed_ai_summary:
        fixed_ai_summary = summarize_grant_with_gemini(combined_text, item.get("title") or "")
        if fixed_ai_summary:
            upsert_grant_summary_cache(str(item.get("id") or ""), fixed_ai_summary, source_text_hash, GEMINI_MODEL)
            summary_source = "gemini"

    overview = _friendly_overview(item, combined_text)
    purpose = _friendly_purpose(item, combined_text)
    target_conditions = _friendly_target_conditions(item, combined_text)

    expenses = _infer_expenses({**item, 'detail': combined_text, 'use_purpose': combined_text})
    document_candidates = _infer_documents({**item, 'detail': combined_text, 'use_purpose': combined_text})

    cautions = []
    if item.get("status") == "closed":
        cautions.append("締切済みです")
    if item.get("status") == "upcoming":
        cautions.append("募集開始日を確認してください")
    if not item.get("subsidy_rate"):
        cautions.append("補助率は公式要領で確認してください")
    if not bundle.get('pdf_text'):
        cautions.append("詳細は公式ページや公募要領で再確認してください")

    notes = list(bundle.get('notes') or [])
    if summary_source == "cache":
        notes.append("保存済みのGemini要約を表示しています")
    elif summary_source == "gemini":
        notes.append("Geminiで詳細ページ・PDF本文から応募判断用に整理しました")
    else:
        notes.append("Gemini要約は未使用です。ルールベースで整理しています")
    pdf_note = ' / '.join(unique(notes)) if notes else '掲載テキストをもとに整理しています。'

    def ai_value(key: str, fallback):
        if fixed_ai_summary and _looks_meaningful(fixed_ai_summary.get(key)):
            value = fixed_ai_summary.get(key)
            if not _looks_like_raw_excerpt(value):
                return value
        return fallback

    final_cautions = _meaningful_list(ai_value('cautions', unique(cautions)), unique(cautions) or ["締切、対象経費、事前着手の扱いを先に確認してください"])
    final_required_documents = _meaningful_list(ai_value('required_documents', document_candidates), document_candidates)
    exclusion_risks = _build_exclusion_risks(item, combined_text, final_cautions if isinstance(final_cautions, list) else [str(final_cautions)])
    difficulty_result = _build_difficulty(item, combined_text, final_required_documents if isinstance(final_required_documents, list) else [])
    prep_load_result = _build_prep_load(difficulty_result)
    expert_needed_result = _build_expert_needed(difficulty_result, item, combined_text)

    summary = {
        "overview": ai_value('overview', overview),
        "purpose": ai_value('purpose', purpose),
        "target_conditions": ai_value('target_companies', target_conditions),
        "field": ', '.join(fixed_ai_summary.get('fields') or []) if fixed_ai_summary and _looks_meaningful(fixed_ai_summary.get('fields')) else extract_field_text(combined_text, _infer_field(item)),
        "budget": ai_value('budget', extract_budget_text(combined_text, item.get('subsidy_rate'), item.get('subsidy_max_limit'))),
        "deadline": ai_value('deadline', extract_deadline_text(combined_text, item.get("acceptance_end_datetime") or item.get("project_end_deadline"))),
        "eligible_expenses": ai_value('eligible_expenses', expenses),
        "ineligible_or_unclear": _infer_ineligible_or_unclear(combined_text),
        "required_documents": final_required_documents,
        "application_steps": _meaningful_list(ai_value('preparation_tasks', []), ["対象地域・応募資格を確認する", "研究開発計画と経費明細を作る", "見積書・決算書など添付書類をそろえる", "締切の数日前までに電子申請を完了する"]),
        "cautions": final_cautions,
        "common_misses": ["地域要件の見落とし", "締切日の取り違え", "必要書類の不足", "研究フェーズと制度のずれ"],
        "suitable_for": ai_value('suitable_for', _friendly_suitable_for(item, combined_text)),
        "not_suitable_for": ai_value('not_suitable_for', _friendly_not_suitable_for(item, combined_text)),
        "rd_phase": ai_value('rd_phase', "unknown"),
        "expert_type_needed": ai_value('expert_type_needed', ["要確認"]),
        "first_questions_to_ask": _meaningful_list(ai_value('first_questions_to_ask', []), ["自社の所在地・業種・規模は対象に入るか", "人件費・外注費・設備費のうち使いたい費用は対象か", "交付決定前に発注・契約していないか", "締切までにGビズIDや添付書類がそろうか"]),
        "gemini_summary": fixed_ai_summary,
        "summary_source": summary_source,
        "exclusion_risks": exclusion_risks,
        "difficulty": difficulty_result,
        "prep_load": prep_load_result,
        "expert_needed": expert_needed_result,
    }
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "institution_name": item.get("institution_name"),
        "system_name": item.get("system_name"),
        "source": item.get("source"),
        "status": item.get("status"),
        "target_area_search": item.get("target_area_search"),
        "subsidy_rate": item.get("subsidy_rate"),
        "subsidy_max_limit": item.get("subsidy_max_limit"),
        "acceptance_end_datetime": item.get("acceptance_end_datetime"),
        "official_url": official_url,
        "front_subsidy_detail_page_url": item.get("front_subsidy_detail_page_url"),
        "safe_public_url": item.get("safe_public_url"),
        "pdf_url": bundle.get('pdf_url'),
        "pdf_note": pdf_note,
        "source_text_hash": source_text_hash,
        "legal_notice": LEGAL_DISCLAIMER.get("summary") or "最終確認は公式要領で行ってください。",
        "summary": summary,
    }

def build_compare(ids: List[str]) -> Dict:
    items = [prepare_item(x) for x in get_grants_by_ids(ids)]
    columns = []
    for item in items:
        columns.append({
            "id": item.get("id"),
            "title": item.get("title"),
            "subsidy_rate": item.get("subsidy_rate") or "要確認",
            "subsidy_max_limit": item.get("subsidy_max_limit") or 0,
            "target_conditions": " / ".join([x for x in [item.get("target_number_of_employees"), item.get("target_area_search"), item.get("industry")] if x]) or "要確認",
            "eligible_expenses": _infer_expenses(item),
            "difficulty": "中" if item.get("detail_plain") else "要確認",
            "deadline": item.get("acceptance_end_datetime") or item.get("project_end_deadline"),
            "best_for": item.get("use_purpose") or item.get("industry") or "要確認",
            "cautions": build_grant_summary(item.get("id"))["summary"]["cautions"],
        })
    return {
        "columns": columns,
        "legal_notice": LEGAL_DISCLAIMER.get("summary_note") or "比較は参考情報です。最終確認は公式要領で行ってください。",
    }


def build_readiness_check(ids: List[str]) -> Dict:
    items = [prepare_item(x) for x in get_grants_by_ids(ids)]
    if not items:
        return {"selected_titles": [], "checklist": [], "next_actions": [], "legal_notice": LEGAL_DISCLAIMER.get("summary_note")}
    selected_titles = [item.get("title") or "名称未設定" for item in items]
    needs_equipment = any("設備" in (item.get("detail_plain") or "") or "設備" in (item.get("title") or "") for item in items)
    checklist = [
        {"name": "GビズID", "status": "確認必要", "note": "申請方式によって必要です"},
        {"name": "決算書", "status": "確認必要", "note": "直近決算資料を準備してください"},
        {"name": "会社概要", "status": "確認必要", "note": "事業内容が分かる資料を準備してください"},
        {"name": "事業計画書", "status": "未準備", "note": "研究開発の目的・進め方・成果見込みを整理してください"},
        {"name": "社内承認", "status": "確認必要", "note": "申請前の意思決定フローを確認してください"},
    ]
    if needs_equipment:
        checklist.append({"name": "見積書", "status": "未準備", "note": "設備導入がある場合は見積書を用意してください"})
    next_actions = ["公募要領を確認", "必要書類を集める", "研究開発計画を1枚で整理する"]
    return {
        "selected_titles": selected_titles,
        "checklist": checklist,
        "next_actions": next_actions,
        "legal_notice": LEGAL_DISCLAIMER.get("summary_note") or "準備チェックは参考情報です。最終確認は公式要領で行ってください。",
    }
