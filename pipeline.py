"""Reproducible pandas ETL for the supplied STORE CSV, Parquet and Ruby-keyed YAML."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unicodedata

import pandas as pd
import yaml

from config import DATA_DIR, DB_PATH, RESULTS_DIR

MISSING = {"", "null", "none", "nan", "n/a", "-", "\\t", "\\n"}
IDENTITY_FIELDS = ("name", "address", "phone", "email")
DATE_PATTERNS = (
    (r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"),
    (r"\d{1,2}/\d{1,2}/\d{2}(?!\d)", "%m/%d/%y"),
    (r"\d{1,2}\.\d{1,2}\.\d{4}", "%d.%m.%Y"),
    (r"\d{1,2}-[A-Za-z]+-\d{4}", None),
)


def clean_text(value):
    if value is None or pd.isna(value):
        return None
    text = " ".join(unicodedata.normalize("NFKC", str(value)).split())
    return None if text.casefold() in MISSING else text


def identity_value(value, field):
    text = clean_text(value)
    if text is None:
        return None
    if field == "phone":
        return re.sub(r"\D", "", text) or None
    return text.casefold()


def parse_price(value):
    """Parse actual source notation, retaining currency and exact source amount."""
    text = str(value).strip()
    currencies = re.findall(r"USD|EUR|\$|€", text)
    if len(currencies) != 1:
        raise ValueError(f"Missing/ambiguous currency: {text!r}")
    currency = "EUR" if currencies[0] in {"EUR", "€"} else "USD"
    match = re.fullmatch(r"[$€](\d+)¢(\d{1,2})", text)
    alternate = re.fullmatch(r"(\d+)[$€](\d{1,2})¢", text)
    if match or alternate:
        dollars, cents = (match or alternate).groups()
        amount = Decimal(dollars) + Decimal(cents) / 100
    else:
        number = re.sub(r"USD|EUR|\$|€", "", text).strip()
        if not re.fullmatch(r"\d+(?:\.\d{0,2})?", number):
            raise ValueError(f"Malformed unit price: {text!r}")
        amount = Decimal(number)
    return amount, currency


def parse_timestamp(value):
    """Use format-specific date rules; slash dates in this source are MM/DD/YY."""
    text = " ".join(str(value).strip().split())
    text = re.sub(r"([AP])\.M\.", r"\1M", text, flags=re.I)
    if re.match(r"^[A-Za-z]{3} [A-Za-z]{3} ", text):
        return datetime.strptime(text, "%a %b %d %H:%M:%S %Y")
    for pattern, date_format in DATE_PATTERNS:
        match = re.search(pattern, text)
        if match is None:
            continue
        date_text = match.group()
        if date_format is None:
            month = date_text.split("-")[1]
            date_format = "%d-%b-%Y" if len(month) == 3 else "%d-%B-%Y"
        day = datetime.strptime(date_text, date_format)
        time_text = (text[:match.start()] + " " + text[match.end():]).strip(" ,;T")
        time_text = time_text.upper()
        for time_format in ("%H:%M:%S.%f", "%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p"):
            try:
                clock = datetime.strptime(time_text, time_format).time()
                return datetime.combine(day.date(), clock)
            except ValueError:
                continue
        raise ValueError(f"Malformed time: {value!r}")
    raise ValueError(f"Unrecognized timestamp: {value!r}")


def require_columns(frame, columns, label):
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{label}: missing source columns {sorted(missing)}")


def clean_ids(frame, columns):
    for column in columns:
        values = pd.to_numeric(frame[column], errors="raise")
        if values.isna().any() or (values % 1 != 0).any() or (values < 0).any():
            raise ValueError(f"Invalid identifier in {column}")
        frame[column] = values.astype("int64")


def reconcile_users(users):
    """Union records differing in at most one normalized identity field.

    Require at least two nonmissing matching fields; two missing values alone
    are never evidence. Transitive components retain all original user IDs.
    """
    parent = list(range(len(users)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    lookup, edges = {}, []
    rows = users.reset_index(drop=True).to_dict("records")
    for index, row in enumerate(rows):
        values = tuple(identity_value(row[field], field) for field in IDENTITY_FIELDS)
        for omitted in range(len(IDENTITY_FIELDS)):
            signature = values[:omitted] + values[omitted + 1:]
            if sum(value is not None for value in signature) < 2:
                continue
            key = (omitted, signature)
            if key in lookup:
                previous = lookup[key]
                left, right = root(index), root(previous)
                if left != right:
                    parent[left] = right
                    edges.append({"left_user_id": row["user_id"],
                                  "right_user_id": rows[previous]["user_id"],
                                  "allowed_changed_field": IDENTITY_FIELDS[omitted]})
            else:
                lookup[key] = index
    components = defaultdict(list)
    for index, row in enumerate(rows):
        components[root(index)].append(row["user_id"])
    mapping = {user_id: min(ids) for ids in components.values() for user_id in ids}
    result = users.copy()
    result["customer_id"] = result.user_id.map(mapping).astype("int64")
    return result, pd.DataFrame(edges, columns=["left_user_id", "right_user_id", "allowed_changed_field"])


def process_store(folder, output):
    store = folder.name
    output.mkdir(parents=True, exist_ok=True)
    users = pd.read_csv(folder / "users.csv", dtype=str, keep_default_na=False)
    raw_books = yaml.safe_load((folder / "books.yaml").read_text(encoding="utf-8"))
    books = pd.DataFrame(raw_books).rename(columns=lambda column: column.lstrip(":"))
    orders = pd.read_parquet(folder / "orders.parquet")
    require_columns(users, ["id", *IDENTITY_FIELDS], "users.csv")
    require_columns(books, ["id", "title", "author", "genre", "publisher", "year"], "books.yaml")
    require_columns(orders, ["id", "user_id", "book_id", "quantity", "unit_price", "timestamp", "shipping"], "orders.parquet")
    audit = {"raw_rows": {"users": len(users), "books": len(books), "orders": len(orders)},
             "duplicates_removed": {}, "source_sha256": {}}
    for filename in ("users.csv", "books.yaml", "orders.parquet"):
        audit["source_sha256"][filename] = hashlib.sha256((folder / filename).read_bytes()).hexdigest()
    frames = {"users": users, "books": books, "orders": orders}
    for name, frame in frames.items():
        audit["duplicates_removed"][name] = int(frame.duplicated().sum())
        frames[name] = frame.drop_duplicates().copy()
        if frames[name].id.duplicated().any():
            raise ValueError(f"{store}/{name}: conflicting duplicate IDs; manual review required")
    users, books, orders = (frames[name] for name in ("users", "books", "orders"))
    users = users.rename(columns={"id": "user_id"})
    books = books.rename(columns={"id": "book_id", "year": "publication_year"})
    orders = orders.rename(columns={"id": "order_id"})
    clean_ids(users, ["user_id"])
    clean_ids(books, ["book_id"])
    clean_ids(orders, ["order_id", "user_id", "book_id"])
    for column in IDENTITY_FIELDS:
        users[column] = users[column].map(clean_text)
    audit["missing_user_fields"] = {column: int(users[column].isna().sum()) for column in IDENTITY_FIELDS}
    users, edges = reconcile_users(users)
    audit["identity_merges"] = len(edges)
    for column in ("title", "author", "genre", "publisher"):
        books[column] = books[column].map(clean_text)
    if books[["title", "author"]].isna().any().any():
        raise ValueError(f"{store}: missing title/author requires review")
    years = pd.to_numeric(books.publication_year, errors="coerce")
    years = years.where(years.between(1, 9999) & years.mod(1).eq(0))
    books["publication_year"] = years.astype("Int64")
    audit["invalid_or_missing_publication_years"] = int(years.isna().sum())
    audit["missing_publishers"] = int(books.publisher.isna().sum())
    # Source author strings use commas between people. Canonical sets ignore order/case.
    display_names = {}
    for text in books.author:
        for name in text.split(","):
            name = clean_text(name)
            if name:
                key = name.casefold()
                display_names[key] = min(display_names.get(key, name), name)
    author_keys = books.author.map(lambda text: tuple(sorted({clean_text(name).casefold() for name in text.split(",") if clean_text(name)})))
    books["author_set_key"] = author_keys.map(lambda names: json.dumps(names, ensure_ascii=False))
    books["author_set"] = author_keys.map(lambda names: ", ".join(display_names[name] for name in names))
    # Transparent person-name heuristic used only for optional chat commands.
    ignored = {"the", "and", "for", "from", "with", "will", "may", "king", "queen", "lord", "lady",
               "miss", "mrs", "mr", "dr", "prof", "sir", "rev", "hon", "pres", "gov", "rep", "sen",
               "phd", "dds", "dvm", "esq", "iii", "amb", "fr", "ms", "msgr"}
    name_tokens = {token for name in display_names for token in re.findall(r"[^\W\d_]+", name)
                   if len(token) >= 3 and token not in ignored}
    books["has_person_name"] = books.title.map(lambda title: bool(set(re.findall(r"[^\W\d_]+", title.casefold())) & name_tokens))
    parsed, rejected, currencies = [], [], Counter()
    quantity_values = pd.to_numeric(orders.quantity, errors="coerce")
    orders["quantity"] = quantity_values
    user_ids, book_ids = set(users.user_id), set(books.book_id)
    for row in orders.to_dict("records"):
        try:
            if pd.isna(row["quantity"]) or row["quantity"] <= 0 or row["quantity"] % 1:
                raise ValueError("Quantity must be a positive integer")
            if row["user_id"] not in user_ids or row["book_id"] not in book_ids:
                raise ValueError("Unknown user_id or book_id")
            quantity = int(row["quantity"])
            amount, currency = parse_price(row["unit_price"])
            unit_usd = amount * (Decimal("1.2") if currency == "EUR" else Decimal(1))
            paid_cents = int((unit_usd * quantity * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            timestamp = parse_timestamp(row["timestamp"])
            parsed.append({**row, "quantity": quantity, "original_unit_price": row["unit_price"],
                           "original_timestamp": row["timestamp"], "currency": currency,
                           "unit_price_original": str(amount), "unit_price_usd": float(unit_usd),
                           "paid_price_cents": paid_cents, "paid_price": paid_cents / 100,
                           "timestamp": timestamp, "date": timestamp.date().isoformat(),
                           "year": timestamp.year, "month": timestamp.month, "day": timestamp.day,
                           "shipping": clean_text(row["shipping"])})
            currencies[currency] += 1
        except (ValueError, ArithmeticError) as exc:
            rejected.append({**row, "rejection_reason": str(exc)})
    pd.DataFrame(rejected).to_csv(output / "rejected_orders.csv", index=False)
    if rejected:
        raise ValueError(f"{store}: {len(rejected)} invalid orders; see {output / 'rejected_orders.csv'}. No partial totals published.")
    orders = pd.DataFrame(parsed).drop(columns=["unit_price"])
    orders["timestamp"] = pd.to_datetime(orders.timestamp)
    orders = orders.merge(users[["user_id", "customer_id"]], on="user_id", how="left", validate="many_to_one")
    daily = orders.groupby("date", as_index=False).agg(revenue_cents=("paid_price_cents", "sum"),
                                                       order_count=("order_id", "size"), books_sold=("quantity", "sum"))
    daily["revenue_usd"] = daily.revenue_cents / 100
    sold = orders.merge(books[["book_id", "author_set_key", "author_set"]], on="book_id", validate="many_to_one")
    authors = sold.groupby(["author_set_key", "author_set"], as_index=False).agg(
        books_sold=("quantity", "sum"), revenue_cents=("paid_price_cents", "sum"))
    authors = authors.sort_values(["books_sold", "author_set_key"], ascending=[False, True])
    spending = orders.groupby("customer_id", as_index=False).agg(
        total_cents=("paid_price_cents", "sum"), order_count=("order_id", "size"), books_bought=("quantity", "sum"))
    aliases = users.groupby("customer_id", as_index=False).agg(
        user_ids=("user_id", lambda ids: json.dumps(sorted(map(int, ids)))),
        aliases=("name", lambda names: json.dumps(sorted({name for name in names if name}), ensure_ascii=False)))
    spending = aliases.merge(spending, on="customer_id", how="left", validate="one_to_one")
    for column in ("total_cents", "order_count", "books_bought"):
        spending[column] = spending[column].fillna(0).astype("int64")
    spending["total_usd"] = spending.total_cents / 100
    spending = spending.sort_values(["total_cents", "customer_id"], ascending=[False, True])
    audit.update({"clean_rows": {"users": len(users), "books": len(books), "orders": len(orders)},
                  "currency_order_counts": dict(currencies), "rejected_orders": 0,
                  "invariants": {"revenue_cents": int(orders.paid_price_cents.sum()),
                                 "daily_revenue_cents": int(daily.revenue_cents.sum()),
                                 "customer_spending_cents": int(spending.total_cents.sum()),
                                 "sold_quantity": int(orders.quantity.sum()),
                                 "author_set_sold_quantity": int(authors.books_sold.sum())}})
    invariant = audit["invariants"]
    if not (invariant["revenue_cents"] == invariant["daily_revenue_cents"] == invariant["customer_spending_cents"]
            and invariant["sold_quantity"] == invariant["author_set_sold_quantity"]):
        raise ValueError(f"{store}: aggregation invariant failed")
    top_days = daily.sort_values(["revenue_cents", "date"], ascending=[False, True]).head(5)
    winners = authors.loc[authors.books_sold.eq(authors.books_sold.max())]
    buyers = spending.loc[spending.total_cents.eq(spending.total_cents.max())]
    report = {"store": store, "unique_users": int(users.customer_id.nunique()),
              "unique_author_sets": int(books.author_set_key.nunique()), "book_count": len(books),
              "order_count": len(orders), "books_sold": invariant["sold_quantity"],
              "revenue_usd": f"{Decimal(invariant['revenue_cents']) / 100:.2f}",
              "top_5_days": [{"date": row.date, "revenue_usd": f"{Decimal(int(row.revenue_cents)) / 100:.2f}"} for row in top_days.itertuples()],
              "most_popular_author_sets": [{"authors": json.loads(row.author_set_key), "name": row.author_set,
                                             "books_sold": int(row.books_sold)} for row in winners.itertuples()],
              "best_buyers": [{"customer_id": int(row.customer_id), "user_ids": json.loads(row.user_ids),
                               "aliases": json.loads(row.aliases), "total_usd": f"{Decimal(int(row.total_cents)) / 100:.2f}"}
                              for row in buyers.itertuples()]}
    for name, frame in {"users": users, "books": books, "orders": orders, "daily_revenue": daily,
                        "author_sales": authors, "customer_spending": spending, "identity_merges": edges}.items():
        frame.insert(0, "store", store)
        frame.to_csv(output / f"{name}.csv", index=False)
        frame.to_parquet(output / f"{name}.parquet", index=False)
    (output / "audit.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"users": users, "books": books, "orders": orders, "daily_revenue": daily,
            "author_sales": authors, "customer_spending": spending, "identity_merges": edges}, report


def plot_revenue(frame, destination, store):
    os.environ.setdefault("MPLCONFIGDIR", str(RESULTS_DIR / ".matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker

    series = frame.set_index(pd.to_datetime(frame.date)).revenue_usd.sort_index()
    series = series.reindex(pd.date_range(series.index.min(), series.index.max()), fill_value=0)
    fig, axis = plt.subplots(figsize=(12, 4), layout="constrained")
    axis.plot(series.index, series, color="#17817c", linewidth=1.3)
    axis.fill_between(series.index, series, color="#17817c", alpha=.09)
    axis.set(title=f"{store} · Daily revenue", xlabel="Date", ylabel="Revenue (USD)")
    axis.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    axis.grid(axis="y", alpha=.2)
    axis.spines[["top", "right"]].set_visible(False)
    fig.savefig(destination, dpi=160)
    plt.close(fig)


def build(data_dir=DATA_DIR, results_dir=RESULTS_DIR, db_path=DB_PATH):
    stores = sorted(path for path in data_dir.glob("STORE*") if path.is_dir())
    if not stores:
        raise ValueError(f"No STORE folders found in {data_dir}")
    results_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    reports = []
    # Publish the SQLite snapshot only after every store succeeds.
    with tempfile.NamedTemporaryFile(dir=db_path.parent, suffix=".sqlite", delete=False) as handle:
        pending_db = Path(handle.name)
    try:
        with sqlite3.connect(pending_db) as connection:
            for index, folder in enumerate(stores):
                frames, report = process_store(folder, results_dir / folder.name)
                for name, frame in frames.items():
                    frame.to_sql(name, connection, if_exists="replace" if index == 0 else "append", index=False)
                plot_revenue(frames["daily_revenue"], results_dir / folder.name / "daily_revenue.png", folder.name)
                reports.append(report)
                print(f"{folder.name}: {report['order_count']:,} orders; {report['unique_users']:,} real users; ${report['revenue_usd']} revenue")
            connection.executescript("""
                CREATE UNIQUE INDEX orders_key ON orders(store, order_id);
                CREATE UNIQUE INDEX users_key ON users(store, user_id);
                CREATE UNIQUE INDEX books_key ON books(store, book_id);
                CREATE INDEX orders_customer ON orders(store, customer_id);
                CREATE INDEX orders_day ON orders(store, date);
                CREATE INDEX users_customer ON users(store, customer_id);
                CREATE INDEX customer_spend ON customer_spending(store, total_cents);
                CREATE INDEX author_popularity ON author_sales(store, books_sold);
                CREATE VIEW sales AS
                SELECT o.*, b.title, b.author_set, b.author_set_key, b.genre,
                       b.publication_year, b.has_person_name, u.name AS user_name
                FROM orders o JOIN books b ON o.store=b.store AND o.book_id=b.book_id
                JOIN users u ON o.store=u.store AND o.user_id=u.user_id;
            """)
        pending_db.replace(db_path)
    finally:
        pending_db.unlink(missing_ok=True)
    report_path = results_dir / "summary.json"
    report_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["Store analytics — calculated values", ""]
    for report in reports:
        lines.extend([report["store"], f"Unique users: {report['unique_users']}",
                      f"Unique author sets: {report['unique_author_sets']}",
                      "Top 5 revenue days: " + "; ".join(f"{row['date']}: ${row['revenue_usd']}" for row in report["top_5_days"]),
                      "Most popular author sets: " + "; ".join(f"{row['name']} ({row['books_sold']} sold)" for row in report["most_popular_author_sets"]),
                      "Best buyers: " + "; ".join(f"{row['user_ids']} — ${row['total_usd']}" for row in report["best_buyers"]), ""])
    (results_dir / "results.txt").write_text("\n".join(lines), encoding="utf-8")
    from export_static import export
    export(results_dir)
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--database", type=Path, default=DB_PATH)
    options = parser.parse_args()
    build(options.data_dir, options.results_dir, options.database)
