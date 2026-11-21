"""Parser for extracting structured mutual fund data from raw Groww HTML/JSON."""

from datetime import datetime
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from src.config import DATA_RAW_DIR

logger = logging.getLogger(__name__)

SEBI_RISKOMETER_LEVELS = [
    "Very High Risk",
    "High Risk",
    "Moderately High Risk",
    "Moderate Risk",
    "Low to Moderate Risk",
    "Low Risk",
]


class FundManager(BaseModel):
    """Detailed profile of a fund manager."""
    person_name: str
    managing_since: Optional[str] = None
    managing_since_date: Optional[str] = None
    education: Optional[str] = None
    experience: Optional[str] = None
    other_funds_managed: List[str] = Field(default_factory=list)


class ParsedSchemeData(BaseModel):
    """Structured and verified mutual fund scheme data model."""
    scheme_id: str
    scheme_name: str
    amc_name: str
    category: str
    sub_category: Optional[str] = None
    riskometer: str
    benchmark_name: str
    expense_ratio: str
    exit_load: str
    min_sip_investment: int
    min_lumpsum_investment: int
    lock_in_period: str
    aum: Optional[str] = None
    fund_managers: List[FundManager] = Field(default_factory=list)
    source_url: str
    last_scraped_date: str
    section_facts: Dict[str, str] = Field(default_factory=dict)
    structured_summary: str = ""


class GrowwParser:
    """Parser to extract structured financial parameters and fund manager profiles."""

    def __init__(self, raw_dir: Path = DATA_RAW_DIR):
        self.raw_dir = Path(raw_dir)

    def _extract_riskometer(self, soup: Optional[BeautifulSoup], mf_data: Dict[str, Any]) -> str:
        """Extract SEBI Riskometer level from HTML DOM or fallback fields."""
        if soup:
            for level in SEBI_RISKOMETER_LEVELS:
                # Look for exact text node match in DOM
                for tag in soup.find_all(string=re.compile(rf"\b{re.escape(level)}\b", re.IGNORECASE)):
                    cleaned = tag.strip()
                    if cleaned and len(cleaned) <= 30 and "credit risk" not in cleaned.lower():
                        return level

        # Fallback to nfo_risk or category defaults
        nfo_risk = mf_data.get("nfo_risk")
        if nfo_risk:
            for level in SEBI_RISKOMETER_LEVELS:
                if level.lower().startswith(nfo_risk.lower()):
                    return level
            return f"{nfo_risk} Risk"

        return "Very High Risk"

    def _clean_exit_load(self, raw_exit_load: Optional[str]) -> str:
        """Normalize exit load text, trimming whitespace and escaping special chars."""
        if not raw_exit_load or not raw_exit_load.strip():
            return "Nil (No exit load applicable)."

        cleaned = re.sub(r"[\r\n]+", " ", raw_exit_load)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned.endswith("."):
            cleaned += "."
        return cleaned

    def _format_expense_ratio(self, raw_ter: Any) -> str:
        """Format expense ratio into standardized percentage string."""
        if raw_ter is None or str(raw_ter).strip() == "":
            return "N/A"
        try:
            val = float(raw_ter)
            return f"{val:.2f}%"
        except (ValueError, TypeError):
            val_str = str(raw_ter).strip()
            if not val_str.endswith("%"):
                val_str += "%"
            return val_str

    def _parse_fund_managers(
        self,
        managers_data: Optional[List[Dict[str, Any]]],
        fallback_manager_name: Optional[str] = None,
    ) -> List[FundManager]:
        """Parse structured fund manager cards into FundManager instances."""
        managers: List[FundManager] = []
        if managers_data:
            for item in managers_data:
                name = item.get("person_name") or item.get("name")
                if not name:
                    continue

                date_from_str = item.get("date_from")
                managing_since = None
                managing_since_date = None
                if date_from_str:
                    try:
                        # ISO 8601 parsing e.g. 2023-06-21T18:30:00.000Z
                        dt = datetime.fromisoformat(date_from_str.replace("Z", "+00:00"))
                        managing_since = dt.strftime("%B %Y")
                        managing_since_date = dt.strftime("%Y-%m-%d")
                    except Exception:
                        managing_since = date_from_str[:10]
                        managing_since_date = date_from_str[:10]

                # Extract other schemes managed
                other_funds: List[str] = []
                for fund in item.get("funds_managed") or []:
                    fname = fund.get("scheme_name")
                    if fname and fname not in other_funds:
                        other_funds.append(fname)

                edu = item.get("education")
                if edu:
                    edu = re.sub(r"\s+", " ", edu).strip()

                exp = item.get("experience")
                if exp:
                    exp = re.sub(r"\s+", " ", exp).strip()

                managers.append(
                    FundManager(
                        person_name=name.strip(),
                        managing_since=managing_since,
                        managing_since_date=managing_since_date,
                        education=edu,
                        experience=exp,
                        other_funds_managed=other_funds,
                    )
                )

        if not managers and fallback_manager_name:
            managers.append(FundManager(person_name=fallback_manager_name.strip()))

        return managers

    def _format_lock_in(self, lock_in: Any) -> str:
        """Determine lock-in period string from parsed lock_in dictionary or string."""
        if isinstance(lock_in, dict):
            years = lock_in.get("years")
            months = lock_in.get("months")
            days = lock_in.get("days")
            parts = []
            if years:
                parts.append(f"{years} year{'s' if years > 1 else ''}")
            if months:
                parts.append(f"{months} month{'s' if months > 1 else ''}")
            if days:
                parts.append(f"{days} day{'s' if days > 1 else ''}")
            if parts:
                return ", ".join(parts)
            return "Nil (No lock-in period)."

        if isinstance(lock_in, str) and lock_in.strip():
            return lock_in.strip()

        return "Nil (No lock-in period)."

    def parse_raw_payload(self, raw_payload: Dict[str, Any]) -> ParsedSchemeData:
        """Parse raw crawled JSON/HTML payload into validated ParsedSchemeData model.
        
        Args:
            raw_payload: Dictionary containing 'scheme_id', 'source_url', 'raw_html',
                         'mf_server_side_data', and 'last_scraped_date'.
                         
        Returns:
            ParsedSchemeData instance.
        """
        scheme_id = raw_payload["scheme_id"]
        source_url = raw_payload["source_url"]
        last_scraped_date = raw_payload.get("last_scraped_date") or datetime.now().strftime("%Y-%m-%d")
        mf_data = raw_payload.get("mf_server_side_data") or {}

        # Parse HTML DOM if present
        raw_html = raw_payload.get("raw_html")
        soup = BeautifulSoup(raw_html, "html.parser") if raw_html else None

        scheme_name = mf_data.get("scheme_name") or raw_payload.get("scheme_name") or scheme_id
        amc_name = mf_data.get("fund_house") or mf_data.get("amc") or "HDFC Mutual Fund"
        category = mf_data.get("category") or "Mutual Fund"
        sub_category = mf_data.get("sub_category")

        benchmark_name = mf_data.get("benchmark_name") or mf_data.get("benchmark") or "Not Specified"
        riskometer = self._extract_riskometer(soup, mf_data)
        expense_ratio = self._format_expense_ratio(mf_data.get("expense_ratio"))
        exit_load = self._clean_exit_load(mf_data.get("exit_load"))

        raw_aum = mf_data.get("aum")
        if raw_aum:
            try:
                aum_formatted = f"₹{float(raw_aum):,.2f} Cr"
            except (ValueError, TypeError):
                aum_formatted = str(raw_aum)
        else:
            aum_formatted = "Not Disclosed"

        min_sip = int(mf_data.get("min_sip_investment") or 100)
        min_lump = int(mf_data.get("min_investment_amount") or 100)
        lock_in = self._format_lock_in(mf_data.get("lock_in"))

        fund_managers = self._parse_fund_managers(
            mf_data.get("fund_manager_details"),
            fallback_manager_name=mf_data.get("fund_manager"),
        )

        # Build Section Facts
        mgr_names = ", ".join(m.person_name for m in fund_managers) if fund_managers else "Not specified"
        mgr_summaries = []
        for m in fund_managers:
            since_info = f" (managing since {m.managing_since})" if m.managing_since else ""
            edu_info = f". Education: {m.education}" if m.education else ""
            mgr_summaries.append(f"{m.person_name}{since_info}{edu_info}")
        mgr_text = "; ".join(mgr_summaries)

        section_facts = {
            "expense_ratio": (
                f"The Total Expense Ratio (TER) of {scheme_name} (Direct Plan) is {expense_ratio}."
            ),
            "fund_size": (
                f"The total Fund Size (AUM / Assets Under Management) of {scheme_name} is {aum_formatted}."
            ),
            "exit_load": (
                f"The exit load for {scheme_name} is: {exit_load}"
            ),
            "investment_limits": (
                f"The minimum SIP investment amount for {scheme_name} is ₹{min_sip}. "
                f"The minimum lumpsum investment amount is ₹{min_lump}."
            ),
            "lock_in": (
                f"The lock-in period for {scheme_name} is {lock_in}"
            ),
            "riskometer_and_benchmark": (
                f"{scheme_name} is categorized as {riskometer}. "
                f"Its designated benchmark index is {benchmark_name}."
            ),
            "fund_management": (
                f"{scheme_name} is managed by: {mgr_text}."
            ),
        }

        # Unified structured summary text
        structured_summary = (
            f"Scheme: {scheme_name}\n"
            f"AMC: {amc_name}\n"
            f"Category: {category} ({sub_category or 'General'})\n"
            f"Expense Ratio (Direct Plan): {expense_ratio}\n"
            f"Fund Size (AUM): {aum_formatted}\n"
            f"Exit Load: {exit_load}\n"
            f"Minimum Investment: Minimum SIP is ₹{min_sip}; Minimum Lumpsum is ₹{min_lump}.\n"
            f"Lock-in Period: {lock_in}\n"
            f"Riskometer: {riskometer}\n"
            f"Benchmark Index: {benchmark_name}\n"
            f"Fund Managers: {mgr_text}\n"
            f"Source URL: {source_url}\n"
            f"Last updated from sources: {last_scraped_date}"
        )

        return ParsedSchemeData(
            scheme_id=scheme_id,
            scheme_name=scheme_name,
            amc_name=amc_name,
            category=category,
            sub_category=sub_category,
            riskometer=riskometer,
            benchmark_name=benchmark_name,
            expense_ratio=expense_ratio,
            exit_load=exit_load,
            min_sip_investment=min_sip,
            min_lumpsum_investment=min_lump,
            lock_in_period=lock_in,
            aum=aum_formatted,
            fund_managers=fund_managers,
            source_url=source_url,
            last_scraped_date=last_scraped_date,
            section_facts=section_facts,
            structured_summary=structured_summary,
        )

    def parse_all_cached(self) -> Dict[str, ParsedSchemeData]:
        """Parse all cached scheme JSON files in data/raw/."""
        parsed_schemes: Dict[str, ParsedSchemeData] = {}
        for json_file in sorted(self.raw_dir.glob("*.json")):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    raw_payload = json.load(f)
                parsed = self.parse_raw_payload(raw_payload)
                parsed_schemes[parsed.scheme_id] = parsed
                logger.info(f"Successfully parsed scheme: '{parsed.scheme_name}' ({parsed.scheme_id})")
            except Exception as e:
                logger.error(f"Failed to parse cached file '{json_file}': {e}")

        return parsed_schemes


if __name__ == "__main__":
    parser = GrowwParser()
    schemes = parser.parse_all_cached()
    print(f"\nSuccessfully parsed {len(schemes)} schemes from local cache.")
    for sid, s in schemes.items():
        print(f"\n--- {s.scheme_name} ({sid}) ---")
        print(f"TER: {s.expense_ratio}")
        print(f"Exit Load: {s.exit_load}")
        print(f"Benchmark: {s.benchmark_name}")
        print(f"Riskometer: {s.riskometer}")
        print(f"Min SIP: ₹{s.min_sip_investment}")
        print(f"Managers ({len(s.fund_managers)}): {', '.join(m.person_name for m in s.fund_managers)}")
