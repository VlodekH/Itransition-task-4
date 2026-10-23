"""Read-only analytics access and bounded SQL execution for the store assistant."""
import json
import sqlite3
import time

import pandas as pd

from config import DB_PATH

TABLES = ("orders", "books", "users", "daily_revenue", "author_sales", "customer_spending", "identity_merges", "sales")
FUNCTIONS = {"count", "sum", "total", "avg", "min", "max", "round", "abs", "coalesce", "ifnull", "nullif",
             "lower", "upper", "length", "trim", "ltrim", "rtrim", "substr", "substring", "replace", "instr",
             "like", "glob", "date", "strftime", "julianday", "json_extract", "json_array_length",
             "row_number", "rank", "dense_rank", "lag", "lead", "first_value", "last_value", "ntile"}


def connect():
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"Store database not found: {DB_PATH}. Run: python3 pipeline.py")
    connection = sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def store_names():
    with connect() as connection:
        return [row[0] for row in connection.execute("SELECT DISTINCT store FROM books ORDER BY store")]


def database_schema():
    with connect() as connection:
        schema = {table: [{"name": row[1], "type": row[2]} for row in connection.execute(f'PRAGMA table_info("{table}")')]
                  for table in TABLES}
    return {"stores": store_names(), "tables": schema,
            "rules": ["All joins must include store as well as the entity ID: IDs can overlap between stores.",
                      "sales is orders joined with book metadata and user_name; it is convenient for analytics.",
                      "paid_price_cents/revenue_cents/total_cents are exact USD integer cents. Sum them before dividing by 100.0.",
                      "unit_price_usd is converted unit price before line rounding; paid_price is the rounded USD order-line total.",
                      "users.customer_id reconciles aliases; COUNT(DISTINCT customer_id) gives real unique users.",
                      "customer_spending has reconciled totals, all user_ids and all name aliases, including zero-spend users.",
                      "author_set_key is a canonical, order-independent set; author_set is its display name.",
                      "Count unique author sets from books. Popularity is SUM(quantity), grouped by the full author set.",
                      "daily_revenue and author_sales are unfiltered store totals. Recompute from sales when filters apply.",
                      "date is YYYY-MM-DD. timestamp is parsed ISO local wall time; source has no timezone.",
                      "has_person_name is only an author-token heuristic, not reliable general named entity recognition."]}


def _authorize(action, arg1, arg2, database, source):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and arg1 in TABLES:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in FUNCTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def query_database(sql):
    """Execute one SELECT/WITH query with SQLite-level permissions and a time budget."""
    if not isinstance(sql, str) or not sql.strip() or len(sql) > 20000:
        raise ValueError("Supply a nonempty SQL query up to 20,000 characters")
    if not sql.lstrip().lower().startswith(("select", "with")):
        raise ValueError("Only read-only SELECT/WITH queries are allowed")
    with connect() as connection:
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_000_000)
        connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 20000)
        connection.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 10)
        deadline = time.monotonic() + 3
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        connection.set_authorizer(_authorize)
        cursor = connection.execute(sql)
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchmany(101)
        values = [list(row) for row in rows[:100]]
        if len(json.dumps(values, default=str).encode()) > 128000:
            raise ValueError("Result is too large; select fewer columns or rows")
    return {"columns": columns, "rows": values, "returned_rows": len(values),
            "truncated": len(rows) > 100, "row_limit": 100}


def load_store(store):
    """The dashboard loads one store at a time; data never goes to the model implicitly."""
    with connect() as connection:
        return {name: pd.read_sql_query(f'SELECT * FROM "{name}" WHERE store=?', connection, params=(store,))
                for name in ("sales", "books", "users", "customer_spending", "daily_revenue", "author_sales")}


def filter_facets(store):
    with connect() as connection:
        row = connection.execute("SELECT MIN(date), MAX(date) FROM orders WHERE store=?", (store,)).fetchone()
        genres = [value[0] for value in connection.execute("SELECT DISTINCT genre FROM books WHERE store=? AND genre IS NOT NULL ORDER BY genre", (store,))]
    return {"stores": store_names(), "date_from": row[0], "date_to": row[1], "genres": genres}
