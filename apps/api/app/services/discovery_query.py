from app.models.crm import ICP
from app.providers.lead_discovery import DiscoveryQuery

SENIORITY_IDS = {
    "training": "100",
    "in training": "100",
    "entry": "110",
    "entry level": "110",
    "junior": "110",
    "senior": "120",
    "strategic": "130",
    "manager": "200",
    "entry level manager": "200",
    "experienced manager": "210",
    "director": "220",
    "vp": "300",
    "vice president": "300",
    "cxo": "310",
    "c-level": "310",
    "cio": "310",
    "cto": "310",
    "ceo": "310",
    "owner": "320",
    "partner": "320",
}

INDUSTRY_IDS = {
    "technology": "4",
    "software": "4",
    "it": "6",
    "enterprise": "6",
    "bfsi": "43",
    "finance": "43",
    "financial services": "43",
    "healthcare": "14",
    "manufacturing": "25",
    "retail": "27",
    "government": "75",
}

HEADCOUNT = (
    ("B", 1, 10),
    ("C", 11, 50),
    ("D", 51, 200),
    ("E", 201, 500),
    ("F", 501, 1000),
    ("G", 1001, 5000),
    ("H", 5001, 10000),
    ("I", 10001, 10_000_000),
)


def _csv(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _headcount(min_employees: int | None, max_employees: int | None) -> tuple[str, ...]:
    if min_employees is None and max_employees is None:
        return ()
    low = min_employees or 1
    high = max_employees or 10_000_000
    return tuple(code for code, start, end in HEADCOUNT if end >= low and start <= high)


def _seniority_ids(labels: list[str]) -> tuple[str, ...]:
    ids: list[str] = []
    for label in labels:
        mapped = SENIORITY_IDS.get(label.lower())
        if mapped and mapped not in ids:
            ids.append(mapped)
    return tuple(ids)


def _industry_ids(labels: list[str]) -> tuple[tuple[str, ...], list[str]]:
    ids: list[str] = []
    unknown: list[str] = []
    for label in labels:
        mapped = INDUSTRY_IDS.get(label.lower())
        if mapped:
            if mapped not in ids:
                ids.append(mapped)
        else:
            unknown.append(label)
    return tuple(ids), unknown


def optional_search_language(*, keywords: str, description: str, leftover_industries: list[str]) -> str:
    parts = [keywords.strip()]
    parts.extend(leftover_industries)
    if description.strip() and not keywords.strip():
        parts.append(description.strip()[:120])
    return ", ".join(part for part in parts if part)


def build_discovery_query(
    icp: ICP | None,
    *,
    search_query: str = "",
    profile_urls: list[str] | None = None,
    max_items: int = 10,
    process_token: str = "",
) -> DiscoveryQuery:
    industries = _csv(icp.industries if icp else "")
    industry_ids, leftover = _industry_ids(industries)
    titles = _csv((icp.job_functions if icp else "") + "," + (icp.personas if icp else ""))
    geos = _csv(icp.geographies if icp else "")
    keywords = (icp.keywords if icp else "") or ""
    language = search_query.strip() or optional_search_language(
        keywords=keywords,
        description=icp.description if icp else "",
        leftover_industries=leftover,
    )
    return DiscoveryQuery(
        industries=", ".join(industries),
        geographies=", ".join(geos),
        search_query=language,
        profile_urls=tuple(url.strip() for url in (profile_urls or []) if url.strip()),
        max_items=max(1, max_items),
        process_token=process_token,
        job_titles=tuple(titles),
        seniorities=tuple(_csv(icp.seniorities if icp else "")),
        target_companies=tuple(_csv(icp.target_companies if icp else "")),
        keywords=keywords,
        min_employees=icp.min_employees if icp else None,
        max_employees=icp.max_employees if icp else None,
        industry_ids=industry_ids,
        seniority_ids=_seniority_ids(_csv(icp.seniorities if icp else "")),
        company_headcount=_headcount(icp.min_employees if icp else None, icp.max_employees if icp else None),
    )
