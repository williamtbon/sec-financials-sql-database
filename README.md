# SEC Financial Statement SQL Database Model

SEC Fair Access Note

The SEC asks automated tools to use a descriptive User-Agent. This project requires a contact email or custom User-Agent when running. Request rates should remain polite.

Example Use Cases
Compare revenue and margin trends across companies
Build credit-style leverage and liquidity screens
Analyze annual and quarterly financial statement trends
Practice SQL queries using real public-company data
Audit which XBRL tags feed each financial metric
Known Limitations
SEC XBRL tags vary by company, so mapping may not capture every financial concept perfectly.
Some companies report similar items under different tags.
The database is generated locally and should not be committed to GitHub.
The model is intended for research and SQL practice, not audited financial reporting.
Future Improvements
Add more canonical financial metrics.
Add export options for CSV or Excel.
Add a dashboard layer using Streamlit or Power BI.
Add more example SQL queries.
Add automated tests for concept mapping and database schema creation.
Disclaimer

This project is for educational and analytical purposes only. It uses public SEC data and should not be treated as audited financial advice or official financial statement reconstruction.

Python ETL project that builds a normalized SQLite database from SEC EDGAR/XBRL company facts for finance SQL analysis, financial statement review, ratio analysis, and cross-company comparison.

## Overview

This project retrieves SEC company facts and filing metadata, stores the data in a normalized SQLite database, maps raw XBRL tags into cleaner financial statement concepts, and creates SQL views for financial analysis.

## Key Features

- Pulls public SEC EDGAR/XBRL company facts
- Builds a normalized SQLite database
- Stores company, filing, fact, and concept-map tables
- Maps raw XBRL tags into financial statement metrics
- Creates SQL views for annual and quarterly analysis
- Supports margin, liquidity, debt, and free-cash-flow queries
- Includes example SQL queries for analysis

## Data Sources

The model uses public SEC data sources:

- SEC company ticker mapping
- SEC submissions data
- SEC XBRL company facts

## How to Run

Install dependencies:

```bash
pip install -r requirements.txt

Run for sample companies:
python sec_financials_sql_model.py --tickers AAPL MSFT NVDA --email your_email@example.com --db sec_financials.db --start-year 2019

Open the database:
sqlite3 sec_financials.db

