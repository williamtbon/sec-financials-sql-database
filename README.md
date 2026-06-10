# SEC Financials SQL Database

## Purpose

I built this project to practice working with real SEC financial-statement data in a database format. The goal was to take public SEC EDGAR/XBRL company facts and organize them into a local SQLite database that can be queried for financial analysis.

This project was useful because it helped me understand the data side of finance. Before ratios or valuation models can be built, the underlying financial data has to be collected, cleaned, structured, and stored in a way that can actually be used.

## What This Project Does

This project creates a local SQL database using public SEC financial-statement data.

Main features include:

* Pulling public company financial facts from SEC data sources
* Processing XBRL-style financial data
* Storing financial information in SQLite
* Creating tables for easier company-level analysis
* Allowing financial-statement data to be queried with SQL
* Supporting future analysis such as ratios, screening, or valuation work

## Why I Used SQL

Raw financial data can be difficult to analyze directly because it is often nested, inconsistent, or spread across different reporting periods. SQL makes the data easier to organize and query.

A database structure makes it easier to:

* Filter by company
* Review financial concepts
* Compare reporting periods
* Store repeatable outputs
* Build future analysis tools on top of the same dataset

## Project Structure

```text
sec-financials-sql-database/
│
├── sec_financials_sql_model.py
├── requirements.txt
├── .gitignore
├── LICENSE
└── README.md
```

## How to Run

Clone the repository:

```bash
git clone https://github.com/williamtbon/sec-financials-sql-database.git
cd sec-financials-sql-database
```

Install the required packages:

```bash
pip install -r requirements.txt
```

Run the script:

```bash
python sec_financials_sql_model.py
```

## Example SQL Queries

Once the database is created, it can be used to practice queries like:

```sql
SELECT *
FROM financial_facts
WHERE ticker = 'AAPL';
```

```sql
SELECT ticker, fiscal_year, concept, value
FROM financial_facts
WHERE concept LIKE '%Revenue%';
```

```sql
SELECT ticker, fiscal_year, value
FROM financial_facts
WHERE concept LIKE '%NetIncome%';
```

The exact table and column names may depend on the database schema used in the script.

## Notes From Building This

This project helped me understand that financial data is not always clean or standardized. SEC data is very useful, but companies may use different tags or reporting structures for similar financial concepts.

One important takeaway was that data engineering is part of financial analysis. A model is only as useful as the data structure behind it. Building the SQL database helped me practice organizing raw financial data before using it for deeper analysis.

## SEC Data Access Note

When working with SEC data, requests should follow SEC fair-access expectations. That means using reasonable request frequency and, when required, including a clear User-Agent that identifies the application or user.

This project is intended to use public data responsibly and should not be used to aggressively scrape SEC systems.

## Example Use Cases

This project can be used to practice:

* Querying company financial statement data
* Comparing company data across reporting periods
* Building financial ratio models
* Creating screening tools
* Connecting Python analysis with SQL storage
* Preparing data for valuation or credit-analysis projects

## Limitations

This project has several limitations:

* SEC data may need additional cleaning before advanced analysis.
* Financial concepts may not map perfectly across all companies.
* Some company-specific filings may require manual review.
* The database should not be treated as audited financial reporting.
* The model may need adjustments for companies with unusual reporting structures.

## Future Improvements

Future improvements could include:

* Improving ticker and company mapping
* Standardizing XBRL concepts more carefully
* Adding financial ratio calculations
* Creating a dashboard or reporting layer
* Adding better error handling and logging
* Supporting larger batches of companies
* Expanding the database schema for broader analysis

## Disclaimer

This project is for educational and research purposes only. It uses public financial data and should not be treated as financial advice, investment advice, or audited reporting.
