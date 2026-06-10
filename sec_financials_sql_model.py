#!/usr/bin/env python3
"""
SEC Financial Statement SQL Database Model

Purpose
-------
Builds a normalized SQLite database from SEC EDGAR/XBRL company facts.
It is designed for finance SQL projects: cross-company financial statements,
margin analysis, credit ratios, cash-flow analysis, and trend queries.

Data source
-----------
- Ticker map:      https://www.sec.gov/files/company_tickers.json
- Submissions:    https://data.sec.gov/submissions/CIK##########.json
- Company facts:  https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json

SEC fair-access note
--------------------
Use a descriptive User-Agent with your name/project/email and keep request
rates polite. This script sleeps between requests by default.

Example
-------
python sec_financials_sql_model.py \
    --tickers AAPL MSFT NVDA \
    --email your_email@example.com \
    --db sec_financials.db \
    --start-year 2019

Then open the SQLite DB with:
sqlite3 sec_financials.db

Example SQL:
SELECT * FROM v_period_metrics WHERE ticker='AAPL' ORDER BY filed_date DESC LIMIT 10;
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import requests
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: requests\n"
        "Install it with: pip install requests"
    ) from exc


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

DEFAULT_FORMS = ("10-K", "10-Q", "10-K/A", "10-Q/A")
DEFAULT_UNITS = {"USD", "shares", "USD/shares", "pure"}


# ---------------------------------------------------------------------------
# Canonical financial metric map
# ---------------------------------------------------------------------------
# SEC XBRL is tag-based, and companies may use different standard tags for
# economically similar lines. This map lets the SQL model create clean views
# while preserving every raw fact in the facts table.
#
# Columns:
# canonical_metric, statement, taxonomy, tag, preferred_unit,
# expected_period_type, priority
#
# expected_period_type:
# - "instant" for balance-sheet snapshots
# - "duration" for income/cash-flow periods
# - None for concepts where either can appear
# ---------------------------------------------------------------------------

CONCEPT_MAP_ROWS: List[Tuple[str, str, str, str, Optional[str], Optional[str], int]] = [
    # Income statement
    ("Revenue", "IncomeStatement", "us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", "USD", "duration", 1),
    ("Revenue", "IncomeStatement", "us-gaap", "Revenues", "USD", "duration", 2),
    ("Revenue", "IncomeStatement", "us-gaap", "SalesRevenueNet", "USD", "duration", 3),
    ("Revenue", "IncomeStatement", "us-gaap", "SalesRevenueGoodsNet", "USD", "duration", 4),
    ("Revenue", "IncomeStatement", "us-gaap", "SalesRevenueServicesNet", "USD", "duration", 5),

    ("CostOfRevenue", "IncomeStatement", "us-gaap", "CostOfRevenue", "USD", "duration", 1),
    ("CostOfRevenue", "IncomeStatement", "us-gaap", "CostOfGoodsAndServicesSold", "USD", "duration", 2),
    ("CostOfRevenue", "IncomeStatement", "us-gaap", "CostOfGoodsSold", "USD", "duration", 3),
    ("CostOfRevenue", "IncomeStatement", "us-gaap", "CostOfRevenueGoods", "USD", "duration", 4),
    ("CostOfRevenue", "IncomeStatement", "us-gaap", "CostOfRevenueServices", "USD", "duration", 5),

    ("GrossProfit", "IncomeStatement", "us-gaap", "GrossProfit", "USD", "duration", 1),
    ("ResearchDevelopment", "IncomeStatement", "us-gaap", "ResearchAndDevelopmentExpense", "USD", "duration", 1),
    ("SellingGeneralAdministrative", "IncomeStatement", "us-gaap", "SellingGeneralAndAdministrativeExpense", "USD", "duration", 1),
    ("OperatingIncome", "IncomeStatement", "us-gaap", "OperatingIncomeLoss", "USD", "duration", 1),
    ("InterestExpense", "IncomeStatement", "us-gaap", "InterestExpenseNonOperating", "USD", "duration", 1),
    ("InterestExpense", "IncomeStatement", "us-gaap", "InterestExpense", "USD", "duration", 2),
    ("IncomeTax", "IncomeStatement", "us-gaap", "IncomeTaxExpenseBenefit", "USD", "duration", 1),
    ("NetIncome", "IncomeStatement", "us-gaap", "NetIncomeLoss", "USD", "duration", 1),
    ("NetIncome", "IncomeStatement", "us-gaap", "ProfitLoss", "USD", "duration", 2),
    ("EPSDiluted", "IncomeStatement", "us-gaap", "EarningsPerShareDiluted", "USD/shares", "duration", 1),
    ("EPSBasic", "IncomeStatement", "us-gaap", "EarningsPerShareBasic", "USD/shares", "duration", 1),
    ("SharesDiluted", "IncomeStatement", "us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding", "shares", "duration", 1),
    ("SharesBasic", "IncomeStatement", "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", "shares", "duration", 1),

    # Balance sheet
    ("Cash", "BalanceSheet", "us-gaap", "CashAndCashEquivalentsAtCarryingValue", "USD", "instant", 1),
    ("Cash", "BalanceSheet", "us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "USD", "instant", 2),
    ("ShortTermInvestments", "BalanceSheet", "us-gaap", "ShortTermInvestments", "USD", "instant", 1),
    ("ShortTermInvestments", "BalanceSheet", "us-gaap", "MarketableSecuritiesCurrent", "USD", "instant", 2),
    ("CurrentAssets", "BalanceSheet", "us-gaap", "AssetsCurrent", "USD", "instant", 1),
    ("Assets", "BalanceSheet", "us-gaap", "Assets", "USD", "instant", 1),
    ("CurrentLiabilities", "BalanceSheet", "us-gaap", "LiabilitiesCurrent", "USD", "instant", 1),
    ("Liabilities", "BalanceSheet", "us-gaap", "Liabilities", "USD", "instant", 1),
    ("Equity", "BalanceSheet", "us-gaap", "StockholdersEquity", "USD", "instant", 1),
    ("Equity", "BalanceSheet", "us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "USD", "instant", 2),
    ("DebtCurrent", "BalanceSheet", "us-gaap", "ShortTermBorrowings", "USD", "instant", 1),
    ("DebtCurrent", "BalanceSheet", "us-gaap", "ShortTermBorrowingsCurrent", "USD", "instant", 2),
    ("DebtCurrent", "BalanceSheet", "us-gaap", "CurrentPortionOfLongTermDebt", "USD", "instant", 3),
    ("DebtLongTerm", "BalanceSheet", "us-gaap", "LongTermDebtNoncurrent", "USD", "instant", 1),
    ("DebtLongTerm", "BalanceSheet", "us-gaap", "LongTermDebt", "USD", "instant", 2),
    ("Inventory", "BalanceSheet", "us-gaap", "InventoryNet", "USD", "instant", 1),
    ("AccountsReceivable", "BalanceSheet", "us-gaap", "AccountsReceivableNetCurrent", "USD", "instant", 1),
    ("Goodwill", "BalanceSheet", "us-gaap", "Goodwill", "USD", "instant", 1),

    # Cash flow statement
    ("OperatingCashFlow", "CashFlow", "us-gaap", "NetCashProvidedByUsedInOperatingActivities", "USD", "duration", 1),
    ("InvestingCashFlow", "CashFlow", "us-gaap", "NetCashProvidedByUsedInInvestingActivities", "USD", "duration", 1),
    ("FinancingCashFlow", "CashFlow", "us-gaap", "NetCashProvidedByUsedInFinancingActivities", "USD", "duration", 1),
    ("CapEx", "CashFlow", "us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment", "USD", "duration", 1),
    ("DepreciationAmortization", "CashFlow", "us-gaap", "DepreciationDepletionAndAmortization", "USD", "duration", 1),
    ("DepreciationAmortization", "CashFlow", "us-gaap", "DepreciationAmortizationAndAccretionNet", "USD", "duration", 2),
    ("DividendsPaid", "CashFlow", "us-gaap", "PaymentsOfDividends", "USD", "duration", 1),
    ("RepurchaseOfStock", "CashFlow", "us-gaap", "PaymentsForRepurchaseOfCommonStock", "USD", "duration", 1),
]


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def pad_cik(cik: str | int) -> str:
    """Return SEC 10-digit CIK string with leading zeros."""
    digits = "".join(ch for ch in str(cik) if ch.isdigit())
    if not digits:
        raise ValueError(f"Invalid CIK: {cik!r}")
    return digits.zfill(10)


def safe_year(date_str: Optional[str]) -> Optional[int]:
    if not date_str:
        return None
    try:
        return int(str(date_str)[:4])
    except (ValueError, TypeError):
        return None


def as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def infer_period_type(start_date: Optional[str], end_date: Optional[str]) -> str:
    if not start_date or start_date == end_date:
        return "instant"
    return "duration"


def compact_accession(accn: str) -> str:
    return accn.replace("-", "")


# ---------------------------------------------------------------------------
# SEC HTTP client
# ---------------------------------------------------------------------------

class SecClient:
    def __init__(
        self,
        user_agent: str,
        sleep_seconds: float = 0.20,
        timeout: int = 30,
        max_retries: int = 4,
    ) -> None:
        self.sleep_seconds = sleep_seconds
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": "data.sec.gov",
        })

    def get_json(self, url: str, host_override: Optional[str] = None) -> Dict[str, Any]:
        headers = {}
        if host_override:
            headers["Host"] = host_override

        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                time.sleep(self.sleep_seconds)
                response = self.session.get(url, headers=headers, timeout=self.timeout)

                # Be polite if rate-limited or temporarily blocked.
                if response.status_code in (429, 503):
                    retry_after = response.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 30)
                    print(f"[SEC] {response.status_code}; sleeping {wait:.1f}s before retrying {url}", file=sys.stderr)
                    time.sleep(wait)
                    continue

                response.raise_for_status()
                return response.json()

            except Exception as exc:  # requests can raise several exception classes
                last_error = exc
                wait = min(2 ** attempt, 30)
                print(f"[SEC] request failed on attempt {attempt}/{self.max_retries}: {exc}", file=sys.stderr)
                if attempt < self.max_retries:
                    time.sleep(wait)

        raise RuntimeError(f"Failed to fetch JSON from {url}") from last_error

    def get_ticker_map(self) -> Dict[str, Dict[str, Any]]:
        # sec.gov file uses a different host than data.sec.gov.
        old_host = self.session.headers.get("Host")
        self.session.headers["Host"] = "www.sec.gov"
        try:
            raw = self.get_json(SEC_TICKERS_URL, host_override="www.sec.gov")
        finally:
            if old_host:
                self.session.headers["Host"] = old_host

        ticker_map: Dict[str, Dict[str, Any]] = {}
        for _, row in raw.items():
            ticker = str(row.get("ticker", "")).upper()
            if ticker:
                ticker_map[ticker] = {
                    "ticker": ticker,
                    "cik": pad_cik(row.get("cik_str")),
                    "title": row.get("title"),
                }
        return ticker_map

    def get_submissions(self, cik: str) -> Dict[str, Any]:
        return self.get_json(SEC_SUBMISSIONS_URL.format(cik=pad_cik(cik)))

    def get_companyfacts(self, cik: str) -> Dict[str, Any]:
        return self.get_json(SEC_COMPANYFACTS_URL.format(cik=pad_cik(cik)))


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

def connect_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS companies (
        cik TEXT PRIMARY KEY,
        ticker TEXT,
        name TEXT,
        entity_name TEXT,
        sic TEXT,
        sic_description TEXT,
        fiscal_year_end TEXT,
        exchanges TEXT,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS filings (
        cik TEXT NOT NULL,
        accession_number TEXT NOT NULL,
        filing_date TEXT,
        report_date TEXT,
        acceptance_datetime TEXT,
        form TEXT,
        file_number TEXT,
        film_number TEXT,
        items TEXT,
        size INTEGER,
        is_xbrl INTEGER,
        is_inline_xbrl INTEGER,
        primary_document TEXT,
        primary_doc_description TEXT,
        document_url TEXT,
        imported_at TEXT NOT NULL,
        PRIMARY KEY (cik, accession_number),
        FOREIGN KEY (cik) REFERENCES companies(cik)
    );

    CREATE TABLE IF NOT EXISTS facts (
        fact_id INTEGER PRIMARY KEY AUTOINCREMENT,
        cik TEXT NOT NULL,
        taxonomy TEXT NOT NULL,
        tag TEXT NOT NULL,
        label TEXT,
        description TEXT,
        unit TEXT NOT NULL,
        value REAL,
        start_date TEXT,
        end_date TEXT,
        fiscal_year INTEGER,
        fiscal_period TEXT,
        form TEXT,
        filed_date TEXT,
        accession_number TEXT,
        frame TEXT,
        period_type TEXT,
        imported_at TEXT NOT NULL,
        FOREIGN KEY (cik) REFERENCES companies(cik),
        UNIQUE (
            cik, taxonomy, tag, unit, accession_number,
            start_date, end_date, fiscal_year, fiscal_period, form, filed_date, value
        )
    );

    CREATE TABLE IF NOT EXISTS concept_map (
        canonical_metric TEXT NOT NULL,
        statement TEXT NOT NULL,
        taxonomy TEXT NOT NULL,
        tag TEXT NOT NULL,
        preferred_unit TEXT NOT NULL DEFAULT '',
        expected_period_type TEXT NOT NULL DEFAULT '',
        priority INTEGER NOT NULL,
        PRIMARY KEY (canonical_metric, taxonomy, tag, preferred_unit, expected_period_type)
    );

    CREATE INDEX IF NOT EXISTS idx_companies_ticker ON companies(ticker);
    CREATE INDEX IF NOT EXISTS idx_filings_cik_form_filing ON filings(cik, form, filing_date);
    CREATE INDEX IF NOT EXISTS idx_facts_cik_tag ON facts(cik, taxonomy, tag);
    CREATE INDEX IF NOT EXISTS idx_facts_period ON facts(cik, form, fiscal_year, fiscal_period, end_date);
    CREATE INDEX IF NOT EXISTS idx_facts_accn ON facts(cik, accession_number);
    CREATE INDEX IF NOT EXISTS idx_map_tag ON concept_map(taxonomy, tag);

    DROP VIEW IF EXISTS v_mapped_facts;
    CREATE VIEW v_mapped_facts AS
    SELECT
        c.ticker,
        c.name AS company_name,
        f.fact_id,
        f.cik,
        f.taxonomy,
        f.tag,
        f.label,
        f.unit,
        f.value,
        f.start_date,
        f.end_date,
        f.period_type,
        f.fiscal_year,
        f.fiscal_period,
        f.form,
        f.filed_date,
        f.accession_number,
        f.frame,
        cm.canonical_metric,
        cm.statement,
        cm.priority
    FROM facts f
    JOIN concept_map cm
      ON cm.taxonomy = f.taxonomy
     AND cm.tag = f.tag
     AND (cm.preferred_unit = '' OR cm.preferred_unit = f.unit)
     AND (cm.expected_period_type = '' OR cm.expected_period_type = f.period_type)
    JOIN companies c
      ON c.cik = f.cik;

    DROP VIEW IF EXISTS v_best_mapped_facts;
    CREATE VIEW v_best_mapped_facts AS
    SELECT *
    FROM (
        SELECT
            mf.*,
            ROW_NUMBER() OVER (
                PARTITION BY mf.cik, mf.accession_number, mf.canonical_metric
                ORDER BY mf.priority ASC, mf.filed_date DESC, mf.fact_id DESC
            ) AS rn
        FROM v_mapped_facts mf
        WHERE mf.form IN ('10-K', '10-Q', '10-K/A', '10-Q/A')
    )
    WHERE rn = 1;

    DROP VIEW IF EXISTS v_period_metrics;
    CREATE VIEW v_period_metrics AS
    SELECT
        ticker,
        company_name,
        cik,
        accession_number,
        form,
        filed_date,
        fiscal_year,
        fiscal_period,
        end_date,

        MAX(CASE WHEN canonical_metric = 'Revenue' THEN value END) AS revenue,
        MAX(CASE WHEN canonical_metric = 'CostOfRevenue' THEN value END) AS cost_of_revenue,
        MAX(CASE WHEN canonical_metric = 'GrossProfit' THEN value END) AS gross_profit,
        MAX(CASE WHEN canonical_metric = 'ResearchDevelopment' THEN value END) AS research_development,
        MAX(CASE WHEN canonical_metric = 'SellingGeneralAdministrative' THEN value END) AS selling_general_admin,
        MAX(CASE WHEN canonical_metric = 'OperatingIncome' THEN value END) AS operating_income,
        MAX(CASE WHEN canonical_metric = 'InterestExpense' THEN value END) AS interest_expense,
        MAX(CASE WHEN canonical_metric = 'IncomeTax' THEN value END) AS income_tax,
        MAX(CASE WHEN canonical_metric = 'NetIncome' THEN value END) AS net_income,
        MAX(CASE WHEN canonical_metric = 'EPSDiluted' THEN value END) AS eps_diluted,
        MAX(CASE WHEN canonical_metric = 'EPSBasic' THEN value END) AS eps_basic,
        MAX(CASE WHEN canonical_metric = 'SharesDiluted' THEN value END) AS shares_diluted,
        MAX(CASE WHEN canonical_metric = 'SharesBasic' THEN value END) AS shares_basic,

        MAX(CASE WHEN canonical_metric = 'Cash' THEN value END) AS cash,
        MAX(CASE WHEN canonical_metric = 'ShortTermInvestments' THEN value END) AS short_term_investments,
        MAX(CASE WHEN canonical_metric = 'CurrentAssets' THEN value END) AS current_assets,
        MAX(CASE WHEN canonical_metric = 'Assets' THEN value END) AS assets,
        MAX(CASE WHEN canonical_metric = 'CurrentLiabilities' THEN value END) AS current_liabilities,
        MAX(CASE WHEN canonical_metric = 'Liabilities' THEN value END) AS liabilities,
        MAX(CASE WHEN canonical_metric = 'Equity' THEN value END) AS equity,
        MAX(CASE WHEN canonical_metric = 'DebtCurrent' THEN value END) AS debt_current,
        MAX(CASE WHEN canonical_metric = 'DebtLongTerm' THEN value END) AS debt_long_term,
        MAX(CASE WHEN canonical_metric = 'Inventory' THEN value END) AS inventory,
        MAX(CASE WHEN canonical_metric = 'AccountsReceivable' THEN value END) AS accounts_receivable,
        MAX(CASE WHEN canonical_metric = 'Goodwill' THEN value END) AS goodwill,

        MAX(CASE WHEN canonical_metric = 'OperatingCashFlow' THEN value END) AS operating_cash_flow,
        MAX(CASE WHEN canonical_metric = 'InvestingCashFlow' THEN value END) AS investing_cash_flow,
        MAX(CASE WHEN canonical_metric = 'FinancingCashFlow' THEN value END) AS financing_cash_flow,
        MAX(CASE WHEN canonical_metric = 'CapEx' THEN value END) AS capex,
        MAX(CASE WHEN canonical_metric = 'DepreciationAmortization' THEN value END) AS depreciation_amortization,
        MAX(CASE WHEN canonical_metric = 'DividendsPaid' THEN value END) AS dividends_paid,
        MAX(CASE WHEN canonical_metric = 'RepurchaseOfStock' THEN value END) AS repurchase_of_stock,

        CASE
            WHEN MAX(CASE WHEN canonical_metric = 'Revenue' THEN value END) != 0
            THEN MAX(CASE WHEN canonical_metric = 'GrossProfit' THEN value END)
                 / MAX(CASE WHEN canonical_metric = 'Revenue' THEN value END)
        END AS gross_margin,

        CASE
            WHEN MAX(CASE WHEN canonical_metric = 'Revenue' THEN value END) != 0
            THEN MAX(CASE WHEN canonical_metric = 'OperatingIncome' THEN value END)
                 / MAX(CASE WHEN canonical_metric = 'Revenue' THEN value END)
        END AS operating_margin,

        CASE
            WHEN MAX(CASE WHEN canonical_metric = 'Revenue' THEN value END) != 0
            THEN MAX(CASE WHEN canonical_metric = 'NetIncome' THEN value END)
                 / MAX(CASE WHEN canonical_metric = 'Revenue' THEN value END)
        END AS net_margin,

        CASE
            WHEN MAX(CASE WHEN canonical_metric = 'CurrentLiabilities' THEN value END) != 0
            THEN MAX(CASE WHEN canonical_metric = 'CurrentAssets' THEN value END)
                 / MAX(CASE WHEN canonical_metric = 'CurrentLiabilities' THEN value END)
        END AS current_ratio,

        CASE
            WHEN MAX(CASE WHEN canonical_metric = 'Equity' THEN value END) != 0
            THEN (
                COALESCE(MAX(CASE WHEN canonical_metric = 'DebtCurrent' THEN value END), 0)
                + COALESCE(MAX(CASE WHEN canonical_metric = 'DebtLongTerm' THEN value END), 0)
            ) / MAX(CASE WHEN canonical_metric = 'Equity' THEN value END)
        END AS debt_to_equity,

        CASE
            WHEN MAX(CASE WHEN canonical_metric = 'OperatingCashFlow' THEN value END) IS NOT NULL
            THEN MAX(CASE WHEN canonical_metric = 'OperatingCashFlow' THEN value END)
                 - ABS(COALESCE(MAX(CASE WHEN canonical_metric = 'CapEx' THEN value END), 0))
        END AS free_cash_flow

    FROM v_best_mapped_facts
    GROUP BY
        ticker, company_name, cik, accession_number, form,
        filed_date, fiscal_year, fiscal_period, end_date;

    DROP VIEW IF EXISTS v_annual_metrics;
    CREATE VIEW v_annual_metrics AS
    SELECT *
    FROM v_period_metrics
    WHERE form IN ('10-K', '10-K/A')
      AND fiscal_period = 'FY';

    DROP VIEW IF EXISTS v_quarterly_metrics;
    CREATE VIEW v_quarterly_metrics AS
    SELECT *
    FROM v_period_metrics
    WHERE form IN ('10-Q', '10-Q/A')
      AND fiscal_period IN ('Q1', 'Q2', 'Q3');
    """)

    refresh_concept_map(conn)
    conn.commit()


def refresh_concept_map(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM concept_map;")
    conn.executemany(
        """
        INSERT INTO concept_map (
            canonical_metric,
            statement,
            taxonomy,
            tag,
            preferred_unit,
            expected_period_type,
            priority
        )
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        [
            (metric, statement, taxonomy, tag, unit or '', period_type or '', priority)
            for metric, statement, taxonomy, tag, unit, period_type, priority in CONCEPT_MAP_ROWS
        ],
    )


# ---------------------------------------------------------------------------
# Database loaders
# ---------------------------------------------------------------------------

def upsert_company(
    conn: sqlite3.Connection,
    cik: str,
    ticker: Optional[str],
    ticker_title: Optional[str],
    submissions: Dict[str, Any],
    facts_json: Dict[str, Any],
) -> None:
    name = submissions.get("name") or ticker_title
    entity_name = facts_json.get("entityName")
    exchanges = submissions.get("exchanges")
    tickers = submissions.get("tickers")

    # Prefer ticker passed by user; fall back to first ticker in submissions.
    if not ticker and isinstance(tickers, list) and tickers:
        ticker = str(tickers[0]).upper()

    conn.execute(
        """
        INSERT INTO companies (
            cik, ticker, name, entity_name, sic, sic_description,
            fiscal_year_end, exchanges, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cik) DO UPDATE SET
            ticker = excluded.ticker,
            name = excluded.name,
            entity_name = excluded.entity_name,
            sic = excluded.sic,
            sic_description = excluded.sic_description,
            fiscal_year_end = excluded.fiscal_year_end,
            exchanges = excluded.exchanges,
            updated_at = excluded.updated_at;
        """,
        (
            cik,
            ticker.upper() if ticker else None,
            name,
            entity_name,
            submissions.get("sic"),
            submissions.get("sicDescription"),
            submissions.get("fiscalYearEnd"),
            json.dumps(exchanges) if exchanges is not None else None,
            utc_now(),
        ),
    )


def build_document_url(cik: str, accn: Optional[str], primary_document: Optional[str]) -> Optional[str]:
    if not accn or not primary_document:
        return None
    cik_int = str(int(cik))
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{compact_accession(accn)}/{primary_document}"


def rows_from_columnar_recent(recent: Dict[str, List[Any]]) -> Iterable[Dict[str, Any]]:
    if not recent:
        return []

    keys = list(recent.keys())
    n = max((len(recent.get(k, [])) for k in keys), default=0)

    for i in range(n):
        row: Dict[str, Any] = {}
        for k in keys:
            values = recent.get(k, [])
            row[k] = values[i] if i < len(values) else None
        yield row


def upsert_filings(
    conn: sqlite3.Connection,
    cik: str,
    submissions: Dict[str, Any],
    forms: Sequence[str],
    start_year: Optional[int],
) -> int:
    recent = submissions.get("filings", {}).get("recent", {})
    form_set = set(forms)
    rows = []

    for filing in rows_from_columnar_recent(recent):
        form = filing.get("form")
        filing_date = filing.get("filingDate")
        if form_set and form not in form_set:
            continue
        if start_year and safe_year(filing_date) and safe_year(filing_date) < start_year:
            continue

        accn = filing.get("accessionNumber")
        primary_doc = filing.get("primaryDocument")
        rows.append((
            cik,
            accn,
            filing_date,
            filing.get("reportDate"),
            filing.get("acceptanceDateTime"),
            form,
            filing.get("fileNumber"),
            filing.get("filmNumber"),
            filing.get("items"),
            filing.get("size"),
            int(bool(filing.get("isXBRL"))) if filing.get("isXBRL") is not None else None,
            int(bool(filing.get("isInlineXBRL"))) if filing.get("isInlineXBRL") is not None else None,
            primary_doc,
            filing.get("primaryDocDescription"),
            build_document_url(cik, accn, primary_doc),
            utc_now(),
        ))

    conn.executemany(
        """
        INSERT INTO filings (
            cik, accession_number, filing_date, report_date, acceptance_datetime,
            form, file_number, film_number, items, size, is_xbrl,
            is_inline_xbrl, primary_document, primary_doc_description,
            document_url, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cik, accession_number) DO UPDATE SET
            filing_date = excluded.filing_date,
            report_date = excluded.report_date,
            acceptance_datetime = excluded.acceptance_datetime,
            form = excluded.form,
            file_number = excluded.file_number,
            film_number = excluded.film_number,
            items = excluded.items,
            size = excluded.size,
            is_xbrl = excluded.is_xbrl,
            is_inline_xbrl = excluded.is_inline_xbrl,
            primary_document = excluded.primary_document,
            primary_doc_description = excluded.primary_doc_description,
            document_url = excluded.document_url,
            imported_at = excluded.imported_at;
        """,
        rows,
    )
    return len(rows)


def iter_company_facts(
    cik: str,
    companyfacts: Dict[str, Any],
    forms: Sequence[str],
    start_year: Optional[int],
    allowed_units: Optional[set[str]],
) -> Iterable[Tuple[Any, ...]]:
    form_set = set(forms)

    facts_root = companyfacts.get("facts", {})
    for taxonomy, taxonomy_obj in facts_root.items():
        if not isinstance(taxonomy_obj, dict):
            continue

        for tag, concept_obj in taxonomy_obj.items():
            if not isinstance(concept_obj, dict):
                continue

            label = concept_obj.get("label")
            description = concept_obj.get("description")
            units_obj = concept_obj.get("units", {})

            for unit, unit_facts in units_obj.items():
                if allowed_units is not None and unit not in allowed_units:
                    continue
                if not isinstance(unit_facts, list):
                    continue

                for fact in unit_facts:
                    form = fact.get("form")
                    if form_set and form not in form_set:
                        continue

                    filed_date = fact.get("filed")
                    end_date = fact.get("end")

                    # Prefer filed year for recency filter; fall back to period end.
                    candidate_year = safe_year(filed_date) or safe_year(end_date)
                    if start_year and candidate_year and candidate_year < start_year:
                        continue

                    val = as_float(fact.get("val"))
                    if val is None:
                        continue

                    yield (
                        cik,
                        taxonomy,
                        tag,
                        label,
                        description,
                        unit,
                        val,
                        fact.get("start"),
                        end_date,
                        fact.get("fy"),
                        fact.get("fp"),
                        form,
                        filed_date,
                        fact.get("accn"),
                        fact.get("frame"),
                        infer_period_type(fact.get("start"), end_date),
                        utc_now(),
                    )


def insert_facts(
    conn: sqlite3.Connection,
    cik: str,
    companyfacts: Dict[str, Any],
    forms: Sequence[str],
    start_year: Optional[int],
    allowed_units: Optional[set[str]],
) -> int:
    rows = list(iter_company_facts(cik, companyfacts, forms, start_year, allowed_units))

    conn.executemany(
        """
        INSERT OR IGNORE INTO facts (
            cik, taxonomy, tag, label, description, unit, value,
            start_date, end_date, fiscal_year, fiscal_period, form,
            filed_date, accession_number, frame, period_type, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        rows,
    )
    return len(rows)


# ---------------------------------------------------------------------------
# Model diagnostics and examples
# ---------------------------------------------------------------------------

def print_summary(conn: sqlite3.Connection) -> None:
    counts = {
        "companies": conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
        "filings": conn.execute("SELECT COUNT(*) FROM filings").fetchone()[0],
        "facts": conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0],
        "mapped_facts": conn.execute("SELECT COUNT(*) FROM v_mapped_facts").fetchone()[0],
        "period_rows": conn.execute("SELECT COUNT(*) FROM v_period_metrics").fetchone()[0],
    }

    print("\nDatabase summary")
    print("----------------")
    for k, v in counts.items():
        print(f"{k:>14}: {v:,}")

    print("\nLoaded companies")
    print("----------------")
    for row in conn.execute("""
        SELECT ticker, name, cik, sic, sic_description
        FROM companies
        ORDER BY ticker;
    """):
        print(f"{row[0] or 'N/A':>8} | {row[1]} | CIK {row[2]} | SIC {row[3]} {row[4] or ''}")

    print("\nRecent period metrics sample")
    print("----------------------------")
    sample_sql = """
        SELECT
            ticker, form, fiscal_year, fiscal_period, filed_date,
            ROUND(revenue / 1000000000.0, 2) AS revenue_bn,
            ROUND(net_income / 1000000000.0, 2) AS net_income_bn,
            ROUND(operating_margin, 4) AS operating_margin,
            ROUND(free_cash_flow / 1000000000.0, 2) AS fcf_bn
        FROM v_period_metrics
        ORDER BY ticker, filed_date DESC
        LIMIT 12;
    """
    rows = conn.execute(sample_sql).fetchall()
    if not rows:
        print("No mapped period rows yet. Try a different ticker or widen --start-year.")
        return

    print("ticker | form | fy | fp | filed | revenue_bn | net_income_bn | op_margin | fcf_bn")
    for row in rows:
        print(" | ".join("" if x is None else str(x) for x in row))


def print_example_sql() -> None:
    print("""
Useful SQL queries
------------------

-- 1) Annual margin trend
SELECT
    ticker,
    fiscal_year,
    revenue,
    gross_margin,
    operating_margin,
    net_margin,
    free_cash_flow
FROM v_annual_metrics
WHERE ticker IN ('AAPL', 'MSFT', 'NVDA')
ORDER BY ticker, fiscal_year;

-- 2) Credit-style balance sheet risk
SELECT
    ticker,
    fiscal_year,
    cash,
    current_assets,
    current_liabilities,
    current_ratio,
    debt_current,
    debt_long_term,
    equity,
    debt_to_equity
FROM v_annual_metrics
ORDER BY ticker, fiscal_year DESC;

-- 3) Raw tag audit: see exactly which XBRL concepts fed the clean model
SELECT
    ticker,
    canonical_metric,
    taxonomy,
    tag,
    unit,
    value,
    form,
    fiscal_year,
    fiscal_period,
    filed_date
FROM v_best_mapped_facts
WHERE ticker = 'AAPL'
ORDER BY filed_date DESC, canonical_metric;

-- 4) Find companies with improving operating margin
WITH annual AS (
    SELECT
        ticker,
        fiscal_year,
        operating_margin,
        LAG(operating_margin) OVER (
            PARTITION BY ticker ORDER BY fiscal_year
        ) AS prior_operating_margin
    FROM v_annual_metrics
)
SELECT
    ticker,
    fiscal_year,
    operating_margin,
    prior_operating_margin,
    operating_margin - prior_operating_margin AS margin_change
FROM annual
WHERE prior_operating_margin IS NOT NULL
ORDER BY margin_change DESC;
""")


# ---------------------------------------------------------------------------
# Main ETL
# ---------------------------------------------------------------------------

def load_company(
    conn: sqlite3.Connection,
    client: SecClient,
    cik: str,
    ticker: Optional[str],
    ticker_title: Optional[str],
    forms: Sequence[str],
    start_year: Optional[int],
    allowed_units: Optional[set[str]],
) -> None:
    cik = pad_cik(cik)
    label = ticker or cik

    print(f"\nLoading {label} / CIK {cik}")

    submissions = client.get_submissions(cik)
    companyfacts = client.get_companyfacts(cik)

    upsert_company(conn, cik, ticker, ticker_title, submissions, companyfacts)
    filings_count = upsert_filings(conn, cik, submissions, forms, start_year)
    facts_count = insert_facts(conn, cik, companyfacts, forms, start_year, allowed_units)

    conn.commit()
    print(f"  filings upserted: {filings_count:,}")
    print(f"  facts inserted/ignored: {facts_count:,}")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a SQLite SEC financial statement database from EDGAR/XBRL company facts."
    )
    parser.add_argument(
        "--tickers",
        nargs="*",
        default=[],
        help="Ticker symbols to load, e.g. AAPL MSFT NVDA.",
    )
    parser.add_argument(
        "--ciks",
        nargs="*",
        default=[],
        help="CIKs to load directly. Can be padded or unpadded.",
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Email/contact for SEC User-Agent. Example: william@example.com",
    )
    parser.add_argument(
        "--user-agent",
        default=None,
        help="Optional full User-Agent. If omitted, one is built from --email.",
    )
    parser.add_argument(
        "--db",
        default="sec_financials.db",
        help="SQLite database path.",
    )
    parser.add_argument(
        "--forms",
        nargs="*",
        default=list(DEFAULT_FORMS),
        help="SEC forms to include. Default: 10-K 10-Q 10-K/A 10-Q/A.",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=2018,
        help="Only load filings/facts filed on or after this year. Use 0 to disable.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.20,
        help="Seconds to sleep between SEC requests. Default 0.20.",
    )
    parser.add_argument(
        "--keep-all-units",
        action="store_true",
        help="Keep every XBRL unit instead of filtering to USD, shares, USD/shares, and pure.",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Delete existing DB before loading.",
    )
    parser.add_argument(
        "--examples",
        action="store_true",
        help="Print useful SQL example queries after loading.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    if not args.tickers and not args.ciks:
        print("Error: provide at least one --tickers value or one --ciks value.", file=sys.stderr)
        print("Example: python sec_financials_sql_model.py --tickers AAPL MSFT --email you@example.com", file=sys.stderr)
        return 2

    start_year = args.start_year if args.start_year and args.start_year > 0 else None
    allowed_units = None if args.keep_all_units else set(DEFAULT_UNITS)

    user_agent = args.user_agent or f"sec-financials-sql-model/1.0 contact:{args.email}"

    if args.rebuild and os.path.exists(args.db):
        os.remove(args.db)

    conn = connect_db(args.db)
    create_schema(conn)

    client = SecClient(user_agent=user_agent, sleep_seconds=args.sleep)

    ticker_map: Dict[str, Dict[str, Any]] = {}
    targets: List[Tuple[str, Optional[str], Optional[str]]] = []

    if args.tickers:
        print("Fetching SEC ticker map...")
        ticker_map = client.get_ticker_map()

        for raw_ticker in args.tickers:
            ticker = raw_ticker.upper().strip()
            if ticker not in ticker_map:
                print(f"Warning: ticker not found in SEC ticker map: {ticker}", file=sys.stderr)
                continue
            row = ticker_map[ticker]
            targets.append((row["cik"], ticker, row.get("title")))

    for raw_cik in args.ciks:
        targets.append((pad_cik(raw_cik), None, None))

    # Remove duplicates while preserving order.
    seen = set()
    unique_targets = []
    for cik, ticker, title in targets:
        if cik in seen:
            continue
        seen.add(cik)
        unique_targets.append((cik, ticker, title))

    try:
        for cik, ticker, title in unique_targets:
            load_company(
                conn=conn,
                client=client,
                cik=cik,
                ticker=ticker,
                ticker_title=title,
                forms=args.forms,
                start_year=start_year,
                allowed_units=allowed_units,
            )

        print_summary(conn)
        if args.examples:
            print_example_sql()

        print(f"\nDone. SQLite database saved to: {args.db}")
        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
