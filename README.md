# SEC Financials SQL Database

## Purpose

I built this project to practice working with real SEC financial-statement data in a database format. The goal was to take public SEC EDGAR/XBRL company facts and organize them into a cleaner SQLite structure that can be queried for financial analysis.

This project helped me understand how raw financial data can be collected, normalized, stored, and analyzed using Python and SQL.

## What It Does

This project creates a local SQL database using public SEC financial-statement data.

Core features include:

- Pulling public company financial facts from SEC data sources
- Processing XBRL-style financial data
- Storing financial information in SQLite
- Creating database tables for easier analysis
- Allowing financial-statement data to be queried with SQL
- Supporting repeatable company-level financial analysis

## Why SQL?

Raw financial data can be difficult to analyze directly because it is often stored in nested or semi-structured formats. A SQL database makes it easier to:

- Filter by company
- Compare reporting periods
- Query specific financial concepts
- Organize data across multiple firms
- Build future analysis tools on top of the database

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

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the script:

```bash
python sec_financials_sql_model.py
```

## Example Use Cases

This database can be used to practice:

- Querying company financial statement data
- Comparing financial metrics across periods
- Building financial ratio models
- Creating screening tools
- Connecting Python analysis with SQL storage
- Preparing data for future valuation or credit models

## Example SQL Questions

Once the data is stored, the database could be used to answer questions such as:

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

## SEC Data Access Note

When working with SEC data, requests should follow SEC fair-access expectations. This means using reasonable request frequency and, when required, a clear User-Agent identifying the application or user.

Do not aggressively scrape SEC systems or send unnecessary high-frequency requests.

## What I Learned

While building this project, I learned that:

- SEC financial data is powerful but not always simple to work with.
- Companies may report similar financial concepts using different tags.
- XBRL data requires careful handling before it can be used for analysis.
- A normalized SQL database makes financial data easier to query and reuse.
- Data engineering is an important part of financial analysis, not just a technical side task.

## Limitations

This project has several limitations:

- SEC data may require additional cleaning before advanced analysis.
- Financial concepts may not map perfectly across all companies.
- The database should not be treated as audited financial reporting.
- Some company-specific filings may require manual review.
- The model may need adjustments for firms with unusual reporting structures.

## Future Improvements

Possible future improvements include:

- Adding more robust company/ticker mapping
- Improving XBRL concept standardization
- Adding financial ratio calculations
- Creating a dashboard or reporting layer
- Supporting multiple database backends
- Adding error handling and logging
- Expanding the database schema for broader analysis

## Disclaimer

This project is for educational and research purposes only. It uses public financial data and should not be treated as financial advice, investment advice, or audited reporting.
