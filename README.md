# Task #4 DATA — Store Intelligence

Store analytics for the actual **STORE1–STORE5** inputs. Python/pandas cleans the source files, reconciles customers and computes the metrics. SQLite stores the reproducible result. Streamlit displays separate store views and a single chat for data questions and dashboard commands. OpenAI uses bounded SQL tools; it never receives the complete dataset.

Deadline: **23 October 2026**. Submit a repository URL and a publicly accessible dashboard URL by email to **p.lebedev@itransition.com**. Code repository: https://github.com/VlodekH/itransition-store-analytics. Public dashboard deployment and email submission are still pending. The supplied instructions do not require a video for Task #4.

## Run

From the repository root (the directory containing `pipeline.py`; in the internship workspace, run `cd task-04` first):

```sh
python3 -m pip install -r requirements.txt
python3 pipeline.py
python3 -m streamlit run dashboard.py
```

The original STORE1–STORE5 files are not committed. After cloning, place each store's `users.csv`, `orders.parquet`, and `books.yaml` under `data/STORE1/` through `data/STORE5/`, then run the commands above. The pipeline builds the database and all results. In the existing internship workspace the database is already built, so the last command is sufficient. Streamlit prints its local URL.

To enable chat, copy `.env.example` to `.env` if it does not exist, set your key, and restart Streamlit:

```dotenv
OPENAI_API_KEY=your-key-here
OPENAI_MODEL=gpt-5.4-mini
TASK4_STORE_DB_PATH=
```

Leave the database setting empty to use `task-04/results/stores.sqlite`. `.env` is ignored by git and excluded from Docker builds. The old prototype setting `TASK4_DB_PATH` is not used by the new store application. OpenAI API usage is billed to the configured account. No paid API requests were made while implementing this version.

An optional HTTP API exposes the same tools:

```sh
python3 -m uvicorn api:app --port 8000
```

API documentation: http://localhost:8000/docs. The Streamlit app works without starting this separate API process; it invokes the same Python tools directly.

## Input and schema

The real input for each store is:

| File | Observed source columns |
|---|---|
| `users.csv` | `id`, `name`, `address`, `phone`, `email` |
| `orders.parquet` | `id`, `user_id`, `book_id`, `quantity`, `unit_price`, `timestamp`, `shipping` |
| `books.yaml` | Ruby-style keys `:id`, `:title`, `:author`, `:genre`, `:publisher`, `:year` |

The pipeline reads all formats into pandas and explicitly maps these observed fields. Source archives/files are preserved. SHA-256 fingerprints and row counts are recorded per store. Every join uses both `store` and the entity ID, since IDs can overlap between stores.

There are **five** supplied stores, although the announcement mentions three views. The application therefore shows all five independently rather than dropping STORE4 and STORE5. `ASSIGNMENT.md` records the full requirements.

## Cleaning and calculation decisions

- IDs and quantities are integer types; phone numbers remain strings. Full duplicate rows are removed and counted. Conflicting duplicate primary IDs stop ingestion.
- Whitespace is normalized, including Unicode forms. Empty values, `NULL`, `None`, `-`, and literal escaped whitespace markers are treated as missing. Original files and original order price/timestamp values are retained.
- Invalid/missing publication years become nullable integers. Missing publishers/addresses are kept as missing; they do not cause otherwise valid orders to be deleted.
- Timestamp parsing uses explicit format families: ISO, English month names, ctime-style, `DD.MM.YYYY`, and **`MM/DD/YY`**. The slash interpretation is supported by the supplied data: thousands of slash dates have the second component greater than 12 and none have the first greater than 12. AM/PM and `A.M.`/`P.M.` are normalized. No timezone is invented; local source calendar dates determine daily revenue. Parsed timestamps and year/month/day are saved.
- Prices support the observed USD/EUR prefix/suffix notation, trailing decimal dots, `$70¢50` and `39€25¢`. `Decimal` preserves the exact source amount. EUR is multiplied by exactly 1.2; the whole line amount (`quantity × unit price × rate`) is rounded to cents with `ROUND_HALF_UP`. Unit USD prices before line rounding can have three decimal places. Revenue uses integer cents, never accumulated floating-point amounts.
- Missing/malformed required order values or unknown foreign keys are written to `rejected_orders.csv` and stop the build. The current supplied files produce no rejected orders. Optional metadata missingness is recorded in `audit.json`.
- Customers are reconciled within each store using normalized name/address/phone/email. Records matching in at least three of four fields are connected, with at least two nonmissing matches required. Matching missing values alone cannot link people. A union-find collects transitive changes, such as address changing in one record and phone changing in the next. The smallest original user ID labels the component; all IDs and name aliases are retained. Matching is deterministic under the assignment's one-changed-field assumption; it is not universal real-world identity resolution. `identity_merges.csv` explains each merge.
- Author sets ignore order, repeated names and case; the observed source separates coauthors with commas. A+B, A and B remain three distinct sets. Unique sets are counted across the complete store catalog. Popularity means sold **quantity** grouped by the entire set, not order count and not independently crediting each coauthor.
- Unique users count all reconciled users, including those with no purchases. Best-buyer aliases also include IDs with no individual purchases. Best buyer and author-set ties are all retained. Revenue-day ties are ordered by earlier date, with exactly five days shown.
- The default dashboard shows whole-store results. Applying filters recalculates order-based metrics; filtered user/author counts refer to those present in the filtered orders. Charts include zero-revenue gaps. Source dates are displayed as `YYYY-MM-DD`.

## Results

Full values: `results/results.txt` and `results/summary.json`.

| Store | Valid orders | Real unique users | Unique author sets | Total revenue USD |
|---|---:|---:|---:|---:|
| STORE1 | 10,493 | 3,221 | 324 | 739,353.52 |
| STORE2 | 9,181 | 3,166 | 281 | 668,103.35 |
| STORE3 | 9,280 | 2,955 | 307 | 681,625.41 |
| STORE4 | 10,877 | 2,850 | 299 | 778,289.22 |
| STORE5 | 9,714 | 2,987 | 311 | 704,421.69 |

Each `results/STORE*/` contains cleaned CSV and Parquet tables, reconciliation edges, the audit, metrics JSON and a matplotlib revenue chart. `results/stores.sqlite` contains all stores in `orders`, `books`, `users`, `daily_revenue`, `author_sales`, `customer_spending`, `identity_merges`, and the joined `sales` view. `sql/analytics.sql` provides SQL equivalents of the core metrics and a top-five-books example.

`public/index.html` is a self-contained static Part 1 dashboard with five tabs and embedded charts. It opens locally in a browser and can be hosted without the raw customer contact files. The full Streamlit app is needed for interactive chat and commands. Regenerate the static artifact using:

```sh
python3 export_static.py
```

## Chat and SQL tools

The chat accepts questions and commands in English or Russian. Examples:

- `Топ-5 самых дорогих книг в STORE1` — runs a SQL query and returns the highest observed sales price per book. These data do not include a separate catalog list price.
- `Сколько реальных покупателей в STORE3?`
- `Какие пять дней принесли больше всего выручки в STORE2?`
- `У какого автора или набора авторов больше всего проданных книг?`
- `Кто лучший покупатель и какие у него user_id?`
- `Покажи STORE4, заказы за ноябрь 2025, сортируй по сумме убыванию`.
- `Покажи 5 самых дорогих книг` — switches the Books view and its sorting/limit.
- `Сбрось фильтры`.

The model can call `get_database_schema`, `query_database(sql)` and `set_dashboard_state(...)`. SQL is checked and executed by our application in a read-only SQLite connection, with an authorizer restricting tables/operations/functions, a three-second execution budget, one statement per call, and maximum 100 returned rows. Writes, schema changes, attachment of other databases and extension loading are denied by SQLite permissions rather than a prompt. The UI displays executed queries and returned results in a chat expander. Tool errors are returned to the model for correction, within a bounded loop. State changes are validated and applied before Streamlit renders its widgets.

Function calling and strict argument schemas follow the [official OpenAI documentation](https://developers.openai.com/api/docs/guides/function-calling). Correct SQL execution does not guarantee correct interpretation of every question. The optional people-name filter uses a documented author-token heuristic and may have false positives/negatives; this is stated in the UI and assistant instructions.

No paid OpenAI request or new automated test suite was run by the engineering agent. Actual pipeline execution checked row/accounting invariants and produced the results above. Vlad manually confirmed that the live chat works. The public code repository is available; public dashboard deployment and email submission are still required.

## Deployment preparation

The Dockerfile packages the sources and builds the data snapshot:

```sh
docker build -t itransition-store-intelligence .
docker run --env-file .env -p 8501:8501 itransition-store-intelligence
```

These commands are preparation instructions; the Docker build has not been run. For public hosting, configure port 8501 and `OPENAI_API_KEY` as a hosting secret. The build needs the supplied `data/STORE*` files; they are currently excluded from git by the workspace's `.gitignore`. Before publishing a repository, decide explicitly which source/derived data may be included, so the deploy has its inputs and secrets remain excluded. `public/index.html` alone is sufficient only for Part 1.

`submission_email.txt` contains a draft with URL placeholders. Publishing the repository/dashboard and sending the email require Vlad's authorization.

## Previous prototype

`prototype-books/` preserves the older Task #3.5-based application and its historical checks. It is not the submitted Task #4 implementation and is not imported by the new application.
