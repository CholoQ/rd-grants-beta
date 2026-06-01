from __future__ import annotations

import re
import time
import html
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import JGRANTS_REQUEST_TIMEOUT, logger
from .models import ParsedProfile
from .status_utils import JST, effective_status
from .utils import contains_any, normalize_region, unique


DEADLINE_FETCH_TIMEOUT = min(1.5, float(JGRANTS_REQUEST_TIMEOUT))
DEADLINE_CACHE_TTL_SECONDS = 6 * 60 * 60
DEADLINE_RESOLVE_LIMIT = 4
DEADLINE_PAGE_MAX_BYTES = 240_000
_DEADLINE_PAGE_CACHE: Dict[str, Dict[str, Any]] = {}

DEADLINE_MARKERS = [
    "応募締切", "申込締切", "申込み締切", "募集締切", "エントリー締切", "提案締切",
    "締切", "締め切り", "〆切", "応募期限", "申込期限", "募集期間", "応募期間",
    "受付期間", "公募期間", "エントリー期間", "応募受付",
]
DEADLINE_CLOSED_TERMS = [
    "募集終了", "受付終了", "応募受付を終了", "募集は終了", "募集を終了",
    "応募受付は終了", "受付を終了", "エントリー受付終了",
    "応募を締め切りました", "募集を締め切りました", "締め切りました", "締切済",
]


DOMAIN_TERMS = {
    "ai": ["AI", "人工知能", "ソフトウェア", "SaaS", "データ", "DX"],
    "medical": ["医療", "医療機器", "診断", "治療", "臨床"],
    "bio": ["バイオ", "微生物", "発酵", "細胞", "遺伝子", "ライフサイエンス"],
    "healthcare": ["ヘルスケア", "健康", "未病", "予防", "ウェルネス", "介護", "腸内環境"],
    "agri": ["アグリ", "農業", "農林水産", "植物", "土壌", "圃場", "作物", "栽培"],
    "foodtech": ["フードテック", "食", "食品", "食料", "発酵", "代替タンパク"],
    "energy": ["脱炭素", "GX", "エネルギー", "再エネ", "カーボン"],
    "space": ["宇宙", "衛星", "ロケット"],
    "materials": ["材料", "化学", "素材"],
    "robotics": ["ロボット", "製造", "ものづくり"],
    "semiconductor": ["半導体", "電子"],
}

SUPPORT_TERMS = {
    "accelerator": ["アクセラ", "アクセラレーター", "伴走支援", "メンタリング", "共創"],
    "activity_fund": ["活動資金", "支援金", "協業費", "実証費", "PoC費用", "開発・実証"],
    "gap_fund": ["GAPファンド", "ギャップファンド", "大学発", "研究シーズ", "仮説検証"],
    "deeptech_startup": ["NEDO", "STS", "SBIR", "ディープテック", "研究開発型スタートアップ"],
    "municipality_poc": ["自治体", "実証フィールド", "社会実験", "行政課題", "PoC"],
    "validation": ["PoC", "概念実証", "実証", "フィールド実証"],
    "startup": ["スタートアップ", "ベンチャー", "起業家", "大学発"],
}

ACCELERATOR_PROGRAMS: List[Dict[str, Any]] = [
    {
        "id": "accelerator::ja-accelerator",
        "title": "JAアクセラレーター by AgVenture Lab",
        "institution_name": "AgVenture Lab / JAグループ",
        "system_name": "JAアクセラレーター",
        "url": "https://ja-accelerator.agventurelab.or.jp/",
        "status": "unknown",
        "max_amount": 1_000_000,
        "subsidy_rate": "最大100万円のPoC費用助成（募集回により要確認）",
        "domains": ["agri", "foodtech", "bio"],
        "regions": ["全国"],
        "keywords": [
            "JA", "AgVenture Lab", "食", "農", "くらし", "アグリテック", "フードテック",
            "PoC費用", "実証", "共創", "スタートアップ", "微生物", "植物", "圃場",
        ],
        "summary": "アグリテック・フードテックを含む食・農・くらし領域のスタートアップ向けアクセラレーター。JAグループとの共創、メンタリング、PoC費用助成を確認したい候補です。",
        "target": "農業、食品、地域課題など食・農・くらしの課題解決に取り組む起業家・スタートアップ。募集年度ごとに応募条件を確認してください。",
        "expenses": "PoC費用、農業・食品領域の実証準備、JAグループとの協業検証、メンタリング・事業化支援。",
    },
    {
        "id": "accelerator::saf-contest",
        "title": "SA&Fクラスター アグリテック・フードテック ビジネスコンテスト",
        "institution_name": "AgVenture Lab",
        "system_name": "SA&Fクラスター",
        "url": "https://safcontest.agventurelab.or.jp/",
        "status": "unknown",
        "max_amount": 50_000_000,
        "subsidy_rate": "支援総額5,000万円規模（1社あたり上限は公式確認）",
        "domains": ["agri", "foodtech", "bio"],
        "regions": ["全国"],
        "keywords": [
            "AgVenture Lab", "SA&F", "アグリテック", "フードテック", "スタートアップ",
            "事業化", "協業", "実証", "PoC", "支援総額", "植物", "食品", "発酵",
        ],
        "summary": "アグリテック・フードテック分野で、大企業等との協業アイデアや実証・事業化を進めたい場合に見る候補です。",
        "target": "法人登記済みの国内スタートアップ等。協業先や募集回ごとの条件があるため公式確認が必要です。",
        "expenses": "協業プロジェクトの実行費、実証・開発・事業化に向けた活動費。精算資料が必要になる可能性があります。",
    },
    {
        "id": "accelerator::kanagawa-bak",
        "title": "ビジネスアクセラレーターかながわ（BAK）",
        "institution_name": "神奈川県",
        "system_name": "BAK / INCUBATION PROGRAM",
        "url": "https://www.pref.kanagawa.jp/docs/sr4/cnt/f537611/bak01.html",
        "status": "unknown",
        "max_amount": 7_500_000,
        "subsidy_rate": "最大750万円支援の募集回あり（年度により要確認）",
        "domains": ["startup", "deeptech", "healthcare", "agri", "energy", "ai", "robotics"],
        "regions": ["神奈川県", "全国"],
        "keywords": [
            "BAK", "ビジネスアクセラレーターかながわ", "神奈川県", "アクセラ", "共創",
            "大企業連携", "事業連携", "開発・実証", "支援金", "スタートアップ", "ベンチャー",
        ],
        "summary": "神奈川県内の大企業・中堅企業等とベンチャーの連携プロジェクト創出を支援するプログラム。実証・事業化支援として確認したい候補です。",
        "target": "国内法人のベンチャー企業等。BAK協議会加入や連携先との合意など、年度ごとの条件確認が必要です。",
        "expenses": "大企業等との連携プロジェクトの開発・実証費、活動資金、伴走支援。汎用補助金ではなく共創型です。",
    },
    {
        "id": "accelerator::kanagawa-yak",
        "title": "エール“ガバメント×ベンチャー”アライアンスかながわ（YAK）",
        "institution_name": "神奈川県",
        "system_name": "YAK / 自治体連携実証",
        "url": "https://www.pref.kanagawa.jp/docs/sr4/cnt/f537666/yak01.html",
        "status": "unknown",
        "max_amount": 7_500_000,
        "subsidy_rate": "最大750万円支援の募集回あり（年度により要確認）",
        "domains": ["startup", "deeptech", "healthcare", "agri", "energy", "ai", "robotics"],
        "regions": ["神奈川県", "全国"],
        "keywords": [
            "YAK", "ガバメント", "ベンチャー", "神奈川県", "県内市町村", "自治体",
            "行政課題", "実証事業", "開発・実証", "支援金", "スタートアップ",
        ],
        "summary": "神奈川県や県内市町村とベンチャー企業が連携し、行政・社会課題の解決に向けた実証や事業化を進めるプログラムです。",
        "target": "自治体課題に対して提案できるベンチャー企業等。自治体側テーマとの合意や年度条件の確認が必要です。",
        "expenses": "自治体連携プロジェクトの実証費、開発費、活動資金、伴走支援。行政課題との接点が重要です。",
    },
    {
        "id": "accelerator::kanagawa-ksap",
        "title": "かながわ・スタートアップ・アクセラレーション・プログラム（KSAP）",
        "institution_name": "神奈川県",
        "system_name": "KSAP",
        "url": "https://startups.pref.kanagawa.jp/program/ksap/",
        "status": "unknown",
        "max_amount": None,
        "subsidy_rate": "伴走支援中心。資金支援の有無は公式確認",
        "domains": ["startup", "deeptech", "healthcare", "agri", "energy", "ai", "robotics"],
        "regions": ["神奈川県"],
        "keywords": [
            "神奈川県", "アクセラレーション", "伴走支援", "スタートアップ",
            "社会課題", "事業開発", "実証", "自治体", "資金支援要確認",
        ],
        "summary": "社会課題に取り組むスタートアップ向けの伴走支援プログラム。資金そのものより事業開発支援として見る候補です。",
        "target": "神奈川県で事業活動を相談しながら成長を目指すスタートアップ。募集条件は公式確認が必要です。",
        "expenses": "直接費の支援は要確認。事業開発、メンタリング、県との接点づくりが主な価値です。",
    },
    {
        "id": "accelerator::nedo-deeptech-startup",
        "title": "NEDO ディープテック・スタートアップ支援（DTSU/STS/PCA/DMP）",
        "institution_name": "NEDO",
        "system_name": "研究開発型スタートアップ支援",
        "url": "https://www.nedo.go.jp/activities/introduction12_02.html",
        "status": "unknown",
        "max_amount": None,
        "subsidy_rate": "フェーズごとに助成率・上限が異なるため公募要領で確認",
        "domains": ["startup", "deeptech", "bio", "healthcare", "agri", "energy", "space", "materials", "robotics", "semiconductor", "ai"],
        "regions": ["全国"],
        "keywords": [
            "NEDO", "DTSU", "STS", "PCA", "DMP", "研究開発型スタートアップ", "ディープテック",
            "実用化研究開発", "量産化実証", "VC", "事業化", "助成", "スタートアップ",
        ],
        "summary": "研究開発型スタートアップの実用化研究開発や量産化実証を支援するNEDO系の大型候補です。STS/PCA/DMPなどフェーズ別に見ます。",
        "target": "研究開発型スタートアップ。フェーズ、VC等との関係、資金調達状況、事業化計画などの条件確認が必要です。",
        "expenses": "実用化研究開発、試作、量産化実証、事業化に向けた開発費。対象経費と助成率は公募回ごとに確認してください。",
        "route": "企業が直接応募可能な回があるが、フェーズ・VC要件を要確認",
        "granttype": "NEDO・研究開発型スタートアップ支援",
    },
    {
        "id": "accelerator::nedo-sbir",
        "title": "NEDO SBIR推進プログラム",
        "institution_name": "NEDO",
        "system_name": "SBIR",
        "url": "https://sbir.nedo.go.jp/",
        "status": "unknown",
        "max_amount": None,
        "subsidy_rate": "補助金・委託費など公募テーマごとに異なる",
        "domains": ["startup", "deeptech", "bio", "healthcare", "agri", "energy", "space", "materials", "robotics", "semiconductor", "ai"],
        "regions": ["全国"],
        "keywords": [
            "NEDO", "SBIR", "研究開発型スタートアップ", "中小企業", "政府調達",
            "社会実装", "技術実証", "フェーズ3", "補助金", "委託費",
        ],
        "summary": "研究開発型スタートアップ等に対する省庁横断の研究開発支援。テーマ公募型なので、技術テーマが合うと強い候補です。",
        "target": "研究開発成果の事業化を目指す中小企業・スタートアップ・研究者等。公募テーマとの一致が重要です。",
        "expenses": "研究開発、技術実証、社会実装に向けた費用。制度・テーマにより補助金または委託費として出ます。",
        "route": "企業・研究者が応募可能なテーマあり。テーマ一致が必須",
        "granttype": "SBIR・研究開発型スタートアップ支援",
    },
    {
        "id": "accelerator::jst-start-fund",
        "title": "JST 大学発新産業創出基金事業 / START",
        "institution_name": "JST",
        "system_name": "大学発新産業創出基金事業",
        "url": "https://www.jst.go.jp/program/startupkikin/index.html",
        "status": "unknown",
        "max_amount": None,
        "subsidy_rate": "GAPファンド・起業実証支援など枠により異なる",
        "domains": ["deeptech", "bio", "healthcare", "agri", "foodtech", "energy", "space", "materials", "robotics", "semiconductor", "ai"],
        "regions": ["全国"],
        "keywords": [
            "JST", "START", "大学発新産業創出基金", "GAPファンド", "大学発スタートアップ",
            "研究シーズ", "事業化", "仮説検証", "試作品", "起業実証",
        ],
        "summary": "大学等の研究シーズからスタートアップを生み出すための国の基盤的支援です。企業単独より、大学・研究者・大学発スタートアップ経由で確認します。",
        "target": "大学等の研究者、大学発スタートアップ、プラットフォーム参加機関など。企業単独応募ではなく大学経由になる場合が多いです。",
        "expenses": "研究シーズの事業化検証、試作品、仮説検証、起業実証、メンタリング。",
        "route": "大学・研究者経由が中心。企業単独応募は要確認",
        "granttype": "GAPファンド・大学発スタートアップ支援",
    },
    {
        "id": "accelerator::gtie-gap",
        "title": "GTIE GAPファンド",
        "institution_name": "GTIE",
        "system_name": "Greater Tokyo Innovation Ecosystem",
        "url": "https://gtie.jp/gap-fund/",
        "status": "unknown",
        "max_amount": None,
        "subsidy_rate": "コース・年度により異なる",
        "domains": ["deeptech", "bio", "healthcare", "agri", "foodtech", "energy", "space", "materials", "robotics", "semiconductor", "ai"],
        "regions": ["東京都", "神奈川県", "千葉県", "埼玉県"],
        "keywords": [
            "GTIE", "GAPファンド", "首都圏", "東京", "大学発", "研究シーズ",
            "メンタリング", "カスタマーデベロップメント", "大企業マッチング", "スタートアップ",
        ],
        "summary": "首都圏大学等の研究シーズを対象に、GAPファンドとメンタリング・マッチングで大学発スタートアップ創出を支援します。",
        "target": "GTIE参加大学等に所属する研究者・チームが中心。企業は大学側シーズ・研究者との関係がある場合に確認したい候補です。",
        "expenses": "研究成果の事業化検証、顧客開発、試作、メンタリング、大企業とのマッチング。",
        "route": "大学・研究者経由。企業単独応募は基本的に要確認",
        "granttype": "GAPファンド",
    },
    {
        "id": "accelerator::hsfc-gap",
        "title": "HSFC GAPファンド",
        "institution_name": "HSFC / 北海道大学等",
        "system_name": "北海道地域のGAPファンド",
        "url": "https://hsfc.jp/insights",
        "status": "unknown",
        "max_amount": None,
        "subsidy_rate": "枠・年度により異なる",
        "domains": ["deeptech", "agri", "foodtech", "bio", "healthcare", "energy", "materials", "ai"],
        "regions": ["北海道"],
        "keywords": [
            "HSFC", "GAPファンド", "北海道", "北海道大学", "アグリ", "フード",
            "水産", "林業", "研究成果", "事業化", "試作品", "仮説検証",
        ],
        "summary": "北海道の大学等研究シーズと事業化のギャップを埋めるGAPファンド。アグリ・フード領域も重点領域として見ます。",
        "target": "北海道大学等の参加機関に関係する研究者・チームが中心。大学発スタートアップや共同研究テーマは確認価値があります。",
        "expenses": "試作品製作、仮説検証データ取得、ビジネスモデル検証、研究成果の事業化準備。",
        "route": "大学・研究者経由。大学発テーマなら強い候補",
        "granttype": "GAPファンド",
    },
    {
        "id": "accelerator::ksac-gap",
        "title": "KSAC-GAPファンド",
        "institution_name": "KSAC",
        "system_name": "関西スタートアップアカデミア・コアリション",
        "url": "https://ksac.site/activity/corporate/",
        "status": "unknown",
        "max_amount": None,
        "subsidy_rate": "Step・枠により異なる",
        "domains": ["deeptech", "bio", "healthcare", "agri", "foodtech", "energy", "materials", "robotics", "ai"],
        "regions": ["大阪府", "京都府", "兵庫県", "奈良県", "滋賀県", "和歌山県"],
        "keywords": [
            "KSAC", "GAPファンド", "関西", "大学発", "研究シーズ", "事業化",
            "Demo Day", "VC", "大手企業", "仮説検証", "試作",
        ],
        "summary": "関西圏の大学等研究シーズを事業化へ近づけるGAPファンド。Demo DayやVC・大企業連携も視野に入ります。",
        "target": "KSAC参画大学等の研究者・チームが中心。企業は大学発シーズ・共同研究先がある場合に確認します。",
        "expenses": "研究シーズの事業化検証、試作、顧客仮説検証、Demo Day準備など。",
        "route": "大学・研究者経由。企業単独応募は要確認",
        "granttype": "GAPファンド",
    },
    {
        "id": "accelerator::tohoku-gap",
        "title": "東北大学 ギャップファンドプログラム",
        "institution_name": "東北大学スタートアップ事業化センター",
        "system_name": "GAP FUND PROGRAM",
        "url": "https://startup.tohoku.ac.jp/gap_fund_program",
        "status": "unknown",
        "max_amount": None,
        "subsidy_rate": "プログラム・年度により異なる",
        "domains": ["deeptech", "bio", "healthcare", "agri", "energy", "materials", "robotics", "semiconductor", "ai"],
        "regions": ["宮城県", "新潟県", "山形県", "福島県", "岩手県", "秋田県", "青森県"],
        "keywords": [
            "東北大学", "みちのくGAPファンド", "BIP", "東北", "新潟", "大学発",
            "研究成果", "事業アイデア", "検証", "スタートアップ",
        ],
        "summary": "東北大学の研究成果を活用した事業アイデア検証や、東北・新潟地域の大学等発スタートアップ創出に関わるGAP系支援です。",
        "target": "東北大学等の研究成果・研究者チームが中心。大学発・共同研究テーマなら確認したい候補です。",
        "expenses": "事業アイデアの検証、実用化に向けた研究開発、ビジネスモデル・事業計画の検討。",
        "route": "大学・研究者経由。起業済み企業は研究者・大学窓口との関係を確認",
        "granttype": "GAPファンド",
    },
    {
        "id": "accelerator::nexs-tokyo",
        "title": "NEXs Tokyo 連携事業創出プログラム",
        "institution_name": "東京都",
        "system_name": "NEXs Tokyo",
        "url": "https://www.nexstokyo.metro.tokyo.lg.jp/program",
        "status": "unknown",
        "max_amount": None,
        "subsidy_rate": "マッチング・伴走中心。直接資金は要確認",
        "domains": ["startup", "deeptech", "healthcare", "agri", "energy", "ai", "robotics", "materials", "space"],
        "regions": ["東京都", "全国"],
        "keywords": [
            "NEXs Tokyo", "東京都", "アクセラレーション", "連携事業創出",
            "自治体", "パートナー企業", "マッチング", "地域展開", "スタートアップ",
        ],
        "summary": "スタートアップとパートナー企業・自治体等のマッチングを通じて、地域を越えた連携事業創出を支援します。",
        "target": "東京発または全国各地域発のスタートアップ。連携先・展開地域との相性が重要です。",
        "expenses": "直接資金より、伴走、マッチング、連携事業創出、地域展開支援が中心です。",
        "route": "企業が応募可能。資金支援というより連携・事業開発支援",
        "granttype": "アクセラ・連携事業創出",
    },
    {
        "id": "accelerator::tokyo-cocial-impact",
        "title": "TOKYO Co-cial IMPACT アクセラレーションプログラム",
        "institution_name": "東京都",
        "system_name": "TOKYO Co-cial IMPACT",
        "url": "https://tokyo-co-cial-impact.metro.tokyo.lg.jp/acceleration-program/",
        "status": "unknown",
        "max_amount": None,
        "subsidy_rate": "伴走支援中心。資金支援は要確認",
        "domains": ["startup", "healthcare", "agri", "foodtech", "energy", "ai", "deeptech"],
        "regions": ["東京都"],
        "keywords": [
            "東京都", "社会課題", "インパクト", "アクセラレーション", "法人設立",
            "プロダクト", "サービス", "インパクト評価", "ファイナンス", "伴走",
        ],
        "summary": "社会的インパクトと経済的リターンの両立を目指す企業向けの伴走型成長支援です。",
        "target": "法人設立済みで、ユーザーへの提供を開始しているプロダクト・サービスを持つ企業が中心です。",
        "expenses": "直接費より、事業検証、インパクト評価、ファイナンス検討、専門家伴走が中心です。",
        "route": "企業が応募可能。成長支援中心で、直接資金は要確認",
        "granttype": "アクセラ・社会課題解決",
    },
    {
        "id": "accelerator::fukuoka-full-support",
        "title": "福岡市実証実験フルサポート事業",
        "institution_name": "福岡市 / FDC",
        "system_name": "実証実験フルサポート",
        "url": "https://www.fukuoka-dc.jpn.com/project_detail/experimental-test/",
        "status": "unknown",
        "max_amount": None,
        "subsidy_rate": "実証フィールド・調整・広報等の支援。費用支援は要確認",
        "domains": ["startup", "healthcare", "ai", "robotics", "energy", "agri", "foodtech", "deeptech"],
        "regions": ["福岡県", "全国"],
        "keywords": [
            "福岡市", "実証実験", "フルサポート", "AI", "IoT", "社会課題",
            "実証フィールド", "行政データ", "規制緩和", "スタートアップ",
        ],
        "summary": "福岡市を舞台に、先端技術を活用した実証実験プロジェクトを支援するプログラムです。",
        "target": "福岡市内で実証したいスタートアップ・企業等。社会課題や市民生活の質向上との接点が重要です。",
        "expenses": "実証フィールド提供、地元調整、行政データ、広報、規制緩和検討など。直接費は要確認です。",
        "route": "企業が応募可能。実証フィールド支援が中心",
        "granttype": "自治体PoC・実証支援",
    },
    {
        "id": "accelerator::osaka-osap",
        "title": "OIHスタートアップアクセラレーションプログラム（OSAP）",
        "institution_name": "大阪イノベーションハブ",
        "system_name": "OSAP",
        "url": "https://www.innovation-osaka.jp/acceleration/",
        "status": "unknown",
        "max_amount": None,
        "subsidy_rate": "伴走・連携支援中心。直接資金は要確認",
        "domains": ["startup", "deeptech", "healthcare", "bio", "ai", "robotics", "materials", "energy"],
        "regions": ["大阪府", "全国"],
        "keywords": [
            "大阪", "OIH", "OSAP", "アクセラレーション", "アーリー期",
            "大企業連携", "VC", "メンター", "グローバル", "スタートアップ",
        ],
        "summary": "アーリー期スタートアップの市場参入・成長を、大企業・VC・メンター連携で支援する大阪のアクセラレーションプログラムです。",
        "target": "関西発、または大阪に拠点設置を検討するスタートアップ等。募集期ごとの条件を確認してください。",
        "expenses": "直接費より、事業開発、メンタリング、大企業・VC連携、成長支援が中心です。",
        "route": "企業が応募可能。直接資金は要確認",
        "granttype": "アクセラ・事業開発支援",
    },
    {
        "id": "accelerator::aichi-manufacturing",
        "title": "Aichi Manufacturing Acceleration Program",
        "institution_name": "愛知県 / STATION Ai",
        "system_name": "A-MAP",
        "url": "https://a-map-stai.com/",
        "status": "unknown",
        "max_amount": None,
        "subsidy_rate": "伴走・事業開発支援中心。直接資金は要確認",
        "domains": ["startup", "robotics", "materials", "semiconductor", "ai", "energy", "deeptech"],
        "regions": ["愛知県", "全国"],
        "keywords": [
            "愛知県", "STATION Ai", "Manufacturing", "ものづくり", "製造",
            "シード", "アクセラレーション", "スタートアップ", "事業開発",
        ],
        "summary": "製造・ものづくり領域のシードスタートアップを支援する愛知県/STATION Ai系のアクセラレーションプログラムです。",
        "target": "Manufacturing領域のシードスタートアップ。愛知・製造業アセットとの相性が重要です。",
        "expenses": "事業開発、メンタリング、製造業連携、実証・市場検証支援。直接費は要確認です。",
        "route": "企業が応募可能。直接資金は要確認",
        "granttype": "アクセラ・製造スタートアップ支援",
    },
    {
        "id": "accelerator::hokkaido-hfx",
        "title": "HOKKAIDO F VILLAGE X（HFX）",
        "institution_name": "HOKKAIDO F VILLAGE X",
        "system_name": "HFX",
        "url": "https://hfx.jp/acceleration-program",
        "status": "unknown",
        "max_amount": None,
        "subsidy_rate": "実証・実装支援、出資検討あり。直接補助金は要確認",
        "domains": ["startup", "agri", "foodtech", "healthcare", "energy", "ai", "deeptech"],
        "regions": ["北海道", "全国"],
        "keywords": [
            "北海道", "F Village", "HFX", "アクセラレーション", "フード", "アグリ",
            "モビリティ", "サステナビリティ", "ウェルビーイング", "実証", "出資検討",
        ],
        "summary": "北海道ボールパークFビレッジや周辺自治体・企業と連携し、地域課題解決や実証・実装を進めるアクセラレーションプログラムです。",
        "target": "北海道で実証・実装したい国内外スタートアップ。フード＆アグリ、ウェルビーイング等のテーマと相性があります。",
        "expenses": "実証・実装サポート、自治体・企業連携、メンタリング、資金調達機会。直接補助金は要確認です。",
        "route": "企業が応募可能。実証支援・出資検討が中心",
        "granttype": "アクセラ・地域実証支援",
    },
    {
        "id": "accelerator::hiroshima-the-meet",
        "title": "The Meet 広島オープンアクセラレーター",
        "institution_name": "広島県",
        "system_name": "The Meet",
        "url": "https://www.pref.hiroshima.lg.jp/soshiki/259/themeet2025.html",
        "status": "closed",
        "max_amount": None,
        "subsidy_rate": "実証フィールド・マッチング支援中心。直接資金は要確認",
        "domains": ["startup", "ai", "healthcare", "agri", "energy", "robotics", "deeptech"],
        "regions": ["広島県", "全国"],
        "keywords": [
            "広島県", "The Meet", "オープンアクセラレーター", "市町", "公的機関",
            "デジタル", "実証フィールド", "行政課題", "スタートアップ",
        ],
        "summary": "スタートアップと県内市町・公的機関をマッチングし、行政・地域課題に対する実証フィールド提供を目指すプログラムです。",
        "target": "行政・地域課題にデジタル技術等で提案できるスタートアップ・企業等。",
        "expenses": "実証フィールド、自治体・公的機関連携、導入検証、広島進出支援。直接費は要確認です。",
        "route": "企業が応募可能。自治体連携・実証支援が中心",
        "granttype": "自治体PoC・実証支援",
    },
    {
        "id": "accelerator::oist-accelerator",
        "title": "OIST Innovation Accelerator",
        "institution_name": "OIST / 沖縄県",
        "system_name": "OIST Accelerator",
        "url": "https://www.oist.jp/ja/innovation/accelerator-startup-support-innovation",
        "status": "unknown",
        "max_amount": None,
        "subsidy_rate": "伴走・R&D/事業開発支援中心。資金条件は要確認",
        "domains": ["startup", "deeptech", "bio", "healthcare", "agri", "energy", "materials", "ai"],
        "regions": ["沖縄県", "全国"],
        "keywords": [
            "OIST", "沖縄", "アクセラレーター", "R&D", "顧客開拓", "事業トラクション",
            "ディープテック", "スタートアップ", "投資検討",
        ],
        "summary": "沖縄での顧客開拓、商業志向のR&D、事業トラクション構築を支援するOIST Innovationのアクセラレーターです。",
        "target": "沖縄・日本市場で検証したい革新的スタートアップ。技術の市場投入を目指すチームに向きます。",
        "expenses": "伴走、R&D、顧客開拓、事業開発、メンターネットワーク。直接費は要確認です。",
        "route": "企業・起業家が応募可能。直接資金は要確認",
        "granttype": "アクセラ・R&D事業化支援",
    },
]


def _payload_keywords(payload: Dict[str, Any], profile: Optional[ParsedProfile]) -> List[str]:
    tokens: List[str] = []
    free_text = (payload.get("free_text") or "").strip()
    if free_text:
        tokens.extend(re.findall(r"[一-龥ぁ-んァ-ヴA-Za-z0-9&・\-]{2,}", free_text))
    domain = (payload.get("tech_domain") or "").strip()
    if domain:
        tokens.extend(DOMAIN_TERMS.get(domain, []))
    support_type = (payload.get("support_type") or "").strip()
    tokens.extend(SUPPORT_TERMS.get(support_type, []))
    phase = (payload.get("rd_phase") or "").strip()
    if phase in {"poc", "demonstration"}:
        tokens.extend(["PoC", "実証", "概念実証"])
    if phase in {"prototype", "commercialization"}:
        tokens.extend(["試作", "事業化", "開発"])
    region = (payload.get("region_text") or "").strip()
    if region:
        tokens.append(region)
    if profile:
        tokens.extend(profile.keywords or [])
        for sector in profile.sectors or []:
            tokens.extend(DOMAIN_TERMS.get(sector, []))
        if profile.is_startup:
            tokens.extend(["スタートアップ", "ベンチャー"])
        if profile.university_origin:
            tokens.extend(["大学発", "研究シーズ"])
    return unique(tokens)[:16]


def _entry_text(entry: Dict[str, Any]) -> str:
    parts = [
        entry.get("title", ""),
        entry.get("institution_name", ""),
        entry.get("system_name", ""),
        entry.get("summary", ""),
        entry.get("target", ""),
        entry.get("expenses", ""),
        entry.get("route", ""),
        entry.get("granttype", ""),
        " ".join(entry.get("keywords") or []),
        " ".join(entry.get("domains") or []),
        " ".join(entry.get("regions") or []),
    ]
    return " ".join(str(p) for p in parts).lower()


def _domain_matches(entry: Dict[str, Any], payload: Dict[str, Any], profile: Optional[ParsedProfile]) -> bool:
    requested = []
    domain = (payload.get("tech_domain") or "").strip()
    if domain:
        requested.append(domain)
    if profile:
        requested.extend(profile.sectors or [])
    requested = unique(requested)
    if not requested:
        return True
    domains = set(entry.get("domains") or [])
    if "startup" in domains or "deeptech" in domains:
        return True
    return bool(domains & set(requested))


def _region_matches(entry: Dict[str, Any], payload: Dict[str, Any], profile: Optional[ParsedProfile]) -> bool:
    requested = normalize_region(payload.get("region_text") or "") or (profile.region if profile else None)
    if not requested:
        return True
    regions = entry.get("regions") or []
    return "全国" in regions or requested in regions


def _score_entry(entry: Dict[str, Any], payload: Dict[str, Any], profile: Optional[ParsedProfile], keywords: List[str]) -> int:
    text = _entry_text(entry)
    score = 0
    for keyword in keywords:
        if keyword and keyword.lower() in text:
            score += 10
    if _domain_matches(entry, payload, profile):
        score += 30
    if _region_matches(entry, payload, profile):
        score += 10
    support_type = (payload.get("support_type") or "").strip()
    if support_type in {"accelerator", "activity_fund", "gap_fund", "deeptech_startup", "municipality_poc", "startup", "validation"}:
        score += 25
    free_text = (payload.get("free_text") or "").lower()
    if contains_any(free_text, ["アクセラ", "活動資金", "支援金", "実証支援", "共創", "自治体", "gap", "ギャップファンド", "nedo", "sts", "sbir"]):
        score += 25
    if profile and profile.is_startup:
        score += 10
    return min(score, 100)


def _support_type_matches(entry: Dict[str, Any], support_type: str) -> bool:
    if support_type not in {"gap_fund", "deeptech_startup", "municipality_poc"}:
        return True
    text = _entry_text(entry)
    if support_type == "gap_fund":
        return contains_any(text, ["gapファンド", "ギャップファンド", "大学発新産業創出基金", "jst"])
    if support_type == "deeptech_startup":
        return contains_any(text, ["nedo", "sbir", "sts", "dtsu", "研究開発型スタートアップ", "ディープテック"])
    if support_type == "municipality_poc":
        return contains_any(text, ["自治体", "行政課題", "実証フィールド", "社会実験", "市町", "県内", "地域実証"])
    return True


def _strip_page_text(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", raw or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _fetch_deadline_page(url: str) -> Dict[str, Any]:
    if not url or not re.match(r"^https?://", url):
        return {"text": "", "error": "invalid_url"}
    cached = _DEADLINE_PAGE_CACHE.get(url)
    now = time.time()
    if cached and now - float(cached.get("fetched_at", 0)) < DEADLINE_CACHE_TTL_SECONDS:
        return dict(cached)
    payload: Dict[str, Any] = {"text": "", "error": None, "fetched_at": now}
    try:
        request = Request(
            url,
            headers={
                "User-Agent": "RikoNavi/0.1 (+deadline-check)",
                "Accept-Language": "ja,en;q=0.8",
            },
        )
        with urlopen(request, timeout=DEADLINE_FETCH_TIMEOUT) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read(DEADLINE_PAGE_MAX_BYTES).decode(charset, errors="ignore")
            payload["text"] = _strip_page_text(raw)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        payload["error"] = str(exc)[:160]
        logger.info("accelerator deadline fetch failed for %s: %s", url, exc)
    _DEADLINE_PAGE_CACHE[url] = dict(payload)
    return payload


def _deadline_contexts(text: str) -> List[str]:
    contexts: List[str] = []
    lower = (text or "").lower()
    for marker in DEADLINE_MARKERS:
        marker_lower = marker.lower()
        start = 0
        while True:
            index = lower.find(marker_lower, start)
            if index == -1:
                break
            contexts.append(text[max(0, index - 45): index + len(marker) + 135])
            start = index + len(marker_lower)
    return unique(contexts)[:12]


def _date_candidates(text: str) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    patterns = [
        (r"(20\d{2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{1,2})", 0),
        (r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?", 0),
        (r"令和\s*(\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?", 2018),
    ]
    for pattern, era_offset in patterns:
        for match in re.finditer(pattern, text or ""):
            year = int(match.group(1)) + era_offset
            month = int(match.group(2))
            day = int(match.group(3))
            try:
                dt = datetime(year, month, day, 23, 59, 59, tzinfo=JST)
            except ValueError:
                continue
            candidates.append({"dt": dt, "raw": match.group(0)})
    return candidates


def _has_closed_signal(text: str) -> bool:
    current_year = datetime.now().year
    for term in DEADLINE_CLOSED_TERMS:
        start = 0
        while True:
            index = (text or "").find(term, start)
            if index == -1:
                break
            window = (text or "")[max(0, index - 45): index + len(term) + 45]
            years = [int(year) for year in re.findall(r"20\d{2}", window)]
            if years and max(years) < current_year:
                start = index + len(term)
                continue
            return True
    return False


def _extract_deadline_info_from_text(text: str) -> Dict[str, Any]:
    clean = text or ""
    contexts = _deadline_contexts(clean)
    records: List[Dict[str, Any]] = []
    for context in contexts:
        dates = _date_candidates(context)
        if dates:
            picked = max(dates, key=lambda item: item["dt"])
            records.append({**picked, "context": context})

    now = datetime.now(JST)
    if records:
        future = [record for record in records if record["dt"] >= now]
        chosen = min(future, key=lambda item: item["dt"]) if future else max(records, key=lambda item: item["dt"])
        date_label = chosen["dt"].strftime("%Y-%m-%d")
        if chosen["dt"] >= now:
            return {
                "status": "open",
                "acceptance_end_datetime": chosen["dt"].isoformat(),
                "deadline_note": f"締切: {date_label}（公式ページから抽出）",
                "deadline_source": "official_page",
            }
        return {
            "status": "closed",
            "acceptance_end_datetime": chosen["dt"].isoformat(),
            "deadline_note": f"締切済みの可能性があります（抽出締切: {date_label}）",
            "deadline_source": "official_page",
        }
    if _has_closed_signal(clean):
        return {
            "status": "closed",
            "deadline_note": "公式ページに募集終了・受付終了の表記があります。",
            "deadline_source": "official_page",
        }
    return {}


def _known_stale_round(entry: Dict[str, Any]) -> bool:
    text = " ".join(str(entry.get(k) or "") for k in ["id", "title", "url", "system_name"])
    years = [int(y) for y in re.findall(r"20\d{2}", text)]
    if not years:
        return False
    current_year = datetime.now().year
    return max(years) < current_year


def _resolve_deadline_info(entry: Dict[str, Any], *, fetch_official: bool) -> Dict[str, Any]:
    status = "closed" if _known_stale_round(entry) else (entry.get("status") or "unknown")
    note = entry.get("deadline_note") or (
        "過年度の募集ページです。次回募集ページが出るまで候補から外します。"
        if status == "closed"
        else "締切・募集年度は公式ページで確認してください。"
    )
    info: Dict[str, Any] = {
        "status": status,
        "deadline_note": note,
        "acceptance_end_datetime": entry.get("acceptance_end_datetime"),
    }
    if status == "closed" or not fetch_official:
        return info

    fetched = _fetch_deadline_page(entry.get("url") or "")
    if fetched.get("text"):
        extracted = _extract_deadline_info_from_text(str(fetched.get("text") or ""))
        if extracted:
            return {**info, **extracted}
    if fetched.get("error"):
        info["deadline_note"] = "締切は自動取得できませんでした。公式ページで確認してください。"
    return info


def _to_item(entry: Dict[str, Any], deadline_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    info = deadline_info or _resolve_deadline_info(entry, fetch_official=False)
    status = str(info.get("status") or "unknown")
    deadline_note = str(info.get("deadline_note") or "締切・募集年度は公式ページで確認してください。")
    detail = (
        f"{entry['summary']}\n"
        f"■対象の目安: {entry['target']}\n"
        f"■応募経路の目安: {entry.get('route') or '募集回ごとに要確認'}\n"
        f"■使える可能性がある費用: {entry['expenses']}\n"
        f"■募集状況: {deadline_note}\n"
        "■注意: 補助金という名称ではなく、アクセラレーター、GAPファンド、実証支援、活動資金、協業費として募集されることがあります。"
        "募集年度、締切、支援金額は必ず公式ページで確認してください。"
    )
    return {
        "id": entry["id"],
        "title": entry["title"],
        "institution_name": entry["institution_name"],
        "system_name": entry["system_name"],
        "subsidy_catch_phrase": entry["summary"],
        "detail": detail,
        "use_purpose": entry.get("use_purpose") or "アクセラレーター、GAPファンド、実証支援、活動資金、PoC、共創",
        "industry": " ".join(entry.get("keywords") or []),
        "target_area_search": "、".join(entry.get("regions") or ["全国"]),
        "target_area_detail": "募集回ごとの対象地域・連携先条件を公式ページで確認してください。",
        "target_number_of_employees": "スタートアップ・ベンチャー向け。従業員数条件は募集回ごとに要確認",
        "subsidy_rate": entry.get("subsidy_rate"),
        "subsidy_max_limit": entry.get("max_amount"),
        "granttype": entry.get("granttype") or "アクセラ・活動資金",
        "acceptance_start_datetime": None,
        "acceptance_end_datetime": info.get("acceptance_end_datetime"),
        "project_end_deadline": None,
        "request_reception_presence": deadline_note,
        "is_enable_multiple_request": 0,
        "front_subsidy_detail_page_url": entry.get("url"),
        "applicant_route": entry.get("route"),
        "status": effective_status({**info, "status": status}),
        "raw_json": "",
        "content_hash": "",
        "source": "accelerator_catalog",
    }


def search_accelerators(payload: Dict[str, Any], profile: Optional[ParsedProfile] = None, max_items: int = 30) -> Dict[str, Any]:
    keywords = _payload_keywords(payload, profile)
    scored_entries: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []
    support_type = (payload.get("support_type") or "").strip()
    for entry in ACCELERATOR_PROGRAMS:
        if not _support_type_matches(entry, support_type):
            continue
        if not _region_matches(entry, payload, profile):
            continue
        score = _score_entry(entry, payload, profile, keywords)
        if score < 25:
            continue
        scored_entries.append({"entry": entry, "score": score})

    scored_entries.sort(
        key=lambda row: (row.get("score", 0), (row.get("entry") or {}).get("max_amount") or 0),
        reverse=True,
    )
    resolve_deadlines = payload.get("resolve_accelerator_deadlines") is not False
    for index, row in enumerate(scored_entries):
        entry = row["entry"]
        score = int(row.get("score") or 0)
        deadline_info = _resolve_deadline_info(entry, fetch_official=resolve_deadlines and index < DEADLINE_RESOLVE_LIMIT)
        item = _to_item(entry, deadline_info)
        if item.get("status") == "closed":
            continue
        item["_accelerator_score"] = score
        rows.append(item)
    rows.sort(key=lambda item: (item.get("_accelerator_score", 0), item.get("subsidy_max_limit") or 0), reverse=True)
    return {"items": rows[:max_items], "keywords": keywords, "fetched": len(rows)}
