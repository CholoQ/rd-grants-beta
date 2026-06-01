#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grant_mvp.company_profile import _normalize_company_url, _pick_budget_range, _pick_domain, _pick_phase
from grant_mvp.accelerators import _extract_deadline_info_from_text, search_accelerators
from grant_mvp.profile_parser import parse_profile_heuristic, postprocess_profile_from_text
from grant_mvp.rd_scheme import build_rd_search
from grant_mvp.utils import parse_budget_min


ENDOPHYTE_TEXT = (
    "内生菌は植物の根の中に入り、菌と植物が互いに支え合いながら共生します。"
    "食・農・環境の各分野を横断するグリーン課題に対し、土壌の生物多様性を起点に解決します。"
)

AGRI_FREE_TEXT = (
    "うちは大学発のアグリテック系スタートアップです。人員はCEOの私とCTOの先生と2人です。"
    "コア技術は植物の生育を良くする微生物です。これはいまラボで実証できているのですが、"
    "今後圃場でのPoCを実施したいです。そのための予算を探してください。予算感は1000万円以上です。"
)

METAGEN_TEXT = (
    "https://metagen.co.jp 腸内環境をやっている大学発ヘルスケアスタートアップで今年で11年目です。"
    "研究開発型で研究開発のシーズはあるのですが、そのPoCや事業化、追加開発に向けた予算が欲しいです。"
    "予算感は1000〜1億円ほど。医療は除いてください。ヘルスケア、バイオから探してください。"
)

AGRI_ACCELERATOR_TEXT = (
    "アグリテックの大学発スタートアップです。植物微生物の圃場PoCを進めたいので、"
    "補助金だけでなくアクセラや活動資金、実証支援も見たいです。"
)

KANAGAWA_ACCELERATOR_TEXT = (
    "神奈川県で自治体や大企業と組むアクセラ、活動資金、実証支援を探したいです。"
)

DEEPTECH_FUND_TEXT = (
    "研究開発型スタートアップです。NEDO STSやSBIR、ディープテック系の資金を探したいです。"
)

GAP_FUND_TEXT = (
    "大学発の研究シーズがあります。GAPファンドで試作と仮説検証の資金を探したいです。"
)

MUNICIPALITY_POC_TEXT = (
    "自治体PoCや実証フィールドを探したいです。福岡や広島などの自治体実証も見たいです。"
)


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{name} failed: {detail}")
    print(f"ok - {name}")


def main() -> None:
    check("normalize bare company URL", _normalize_company_url("endo-phyte.com") == "https://endo-phyte.com")
    check("Endophyte is agri", _pick_domain(ENDOPHYTE_TEXT) == "agri")
    check("foodtech stays foodtech", _pick_domain("代替肉や培養肉、機能性食品を開発する企業です。") == "foodtech")
    check("medical stays medical", _pick_domain("医療機器を使った診断支援サービスを開発しています。") == "medical")
    check("bio stays bio", _pick_domain("創薬や細胞解析に関わるバイオ研究開発です。") == "bio")
    check("healthcare stays healthcare", _pick_domain("ヘルスケアと予防、睡眠改善のサービスです。") == "healthcare")
    check("microbiome healthcare", _pick_domain("腸内環境とマイクロバイオームのヘルスケアです。", "医療は除いてヘルスケアから探してください。") == "healthcare")
    check("field PoC stays poc", _pick_phase("ラボで実証できており、次に圃場PoCを実施したいです。") == "poc")
    check("company URL budget yen text", _pick_budget_range("1000万円以上") == "5m_30m")
    check("company URL budget numeric text", _pick_budget_range("10000000 yen") == "5m_30m")
    check("company URL budget range text", _pick_budget_range("1000〜1億円ほど") == "30m_100m")
    check("budget min range text", parse_budget_min("1000〜1億円ほど") == 10_000_000)
    deadline_info = _extract_deadline_info_from_text("募集期間：2099年6月1日から2099年7月31日まで。応募締切は2099年7月31日です。")
    check("accelerator future deadline extraction", deadline_info.get("status") == "open" and "2099-07-31" in str(deadline_info.get("acceptance_end_datetime")), str(deadline_info))
    closed_info = _extract_deadline_info_from_text("本プログラムの募集は終了しました。")
    check("accelerator closed phrase extraction", closed_info.get("status") == "closed", str(closed_info))

    metagen_profile = postprocess_profile_from_text(parse_profile_heuristic(METAGEN_TEXT), METAGEN_TEXT)
    check("metagen healthcare sector", "healthcare" in metagen_profile.sectors, str(metagen_profile.sectors))
    check("metagen medical excluded", "medical" not in metagen_profile.sectors and "medical" in metagen_profile.negative_sectors, f"{metagen_profile.sectors} / {metagen_profile.negative_sectors}")
    check("metagen drug discovery discouraged", "drug_discovery" in metagen_profile.negative_sectors, str(metagen_profile.negative_sectors))

    profile = postprocess_profile_from_text(parse_profile_heuristic(AGRI_FREE_TEXT), AGRI_FREE_TEXT)
    check("agri free text sector", "agri" in profile.sectors, str(profile.sectors))
    check("agri free text budget", profile.budget_min == 10_000_000, str(profile.budget_min))
    check("agri free text employee count", profile.employee_count == 2, str(profile.employee_count))

    result = build_rd_search({
        "free_text": AGRI_FREE_TEXT,
        "sources": ["jgrants"],
        "support_type": "any",
        "fast_mode": True,
    })
    items = result.get("items") or []
    check("agri search returns broad candidates", len(items) >= 10, f"{len(items)} candidates")
    check("agri search excludes closed top candidates", all(item.get("status") != "closed" for item in items), "closed item present")

    agri_accel_profile = postprocess_profile_from_text(parse_profile_heuristic(AGRI_ACCELERATOR_TEXT), AGRI_ACCELERATOR_TEXT)
    agri_accel = search_accelerators({
        "free_text": AGRI_ACCELERATOR_TEXT,
        "tech_domain": "agri",
        "support_type": "accelerator",
        "rd_phase": "poc",
        "resolve_accelerator_deadlines": False,
    }, agri_accel_profile)
    agri_titles = [item["title"] for item in agri_accel.get("items", [])]
    check("agri accelerator catalog includes AgVenture", any("AgVenture" in t or "JAアクセラレーター" in t for t in agri_titles), str(agri_titles))

    accel_result = build_rd_search({
        "free_text": AGRI_ACCELERATOR_TEXT,
        "tech_domain": "agri",
        "support_type": "accelerator",
        "rd_phase": "poc",
        "sources": ["accelerators"],
        "fast_mode": True,
        "resolve_accelerator_deadlines": False,
    })
    accel_items = accel_result.get("items") or []
    check("accelerator source returns candidates", len(accel_items) >= 1, f"{len(accel_items)} candidates")
    check("accelerator source counted", accel_result.get("source_mix", {}).get("accelerator_items", 0) >= 1, str(accel_result.get("source_mix")))

    kanagawa_profile = postprocess_profile_from_text(parse_profile_heuristic(KANAGAWA_ACCELERATOR_TEXT), KANAGAWA_ACCELERATOR_TEXT)
    kanagawa_accel = search_accelerators({
        "free_text": KANAGAWA_ACCELERATOR_TEXT,
        "region_text": "神奈川県",
        "support_type": "activity_fund",
        "resolve_accelerator_deadlines": False,
    }, kanagawa_profile)
    kanagawa_titles = [item["title"] for item in kanagawa_accel.get("items", [])]
    check("kanagawa accelerator catalog includes BAK or YAK", any("BAK" in t or "YAK" in t for t in kanagawa_titles), str(kanagawa_titles))

    deeptech_result = build_rd_search({
        "free_text": DEEPTECH_FUND_TEXT,
        "support_type": "deeptech_startup",
        "rd_phase": "prototype",
        "sources": ["accelerators"],
        "fast_mode": True,
        "resolve_accelerator_deadlines": False,
    })
    deeptech_titles = [item["title"] for item in deeptech_result.get("items", [])]
    check("deeptech catalog includes NEDO STS or SBIR", any("NEDO" in t or "SBIR" in t for t in deeptech_titles), str(deeptech_titles))

    gap_result = build_rd_search({
        "free_text": GAP_FUND_TEXT,
        "support_type": "gap_fund",
        "rd_phase": "poc",
        "sources": ["accelerators"],
        "fast_mode": True,
        "resolve_accelerator_deadlines": False,
    })
    gap_titles = [item["title"] for item in gap_result.get("items", [])]
    check("gap catalog includes JST or GTIE", any("JST" in t or "GTIE" in t or "GAP" in t for t in gap_titles), str(gap_titles))
    check("gap catalog flags university route", any("大学・研究者経由" in " ".join(item.get("match_cautions") or []) for item in gap_result.get("items", [])), str([item.get("match_cautions") for item in gap_result.get("items", [])]))

    municipality_result = build_rd_search({
        "free_text": MUNICIPALITY_POC_TEXT,
        "support_type": "municipality_poc",
        "rd_phase": "demonstration",
        "sources": ["accelerators"],
        "fast_mode": True,
        "resolve_accelerator_deadlines": False,
    })
    municipality_titles = [item["title"] for item in municipality_result.get("items", [])]
    check("municipality catalog includes local PoC programs", any("福岡市" in t or "広島" in t or "BAK" in t or "YAK" in t for t in municipality_titles), str(municipality_titles))
    check("stale annual accelerator pages are hidden", not any("The Meet" in t for t in municipality_titles), str(municipality_titles))
    check("accelerator unknown deadlines are explicit", any(item.get("status") == "unknown" for item in municipality_result.get("items", [])), str([(item["title"], item.get("status")) for item in municipality_result.get("items", [])]))


if __name__ == "__main__":
    main()
