"""Store analytics dashboard with a unified SQL-backed assistant chat."""
from datetime import date
import json

import pandas as pd
import streamlit as st

from ai_agent import VIEWS, ask_openai, is_configured
from config import DB_PATH
from db import filter_facets, load_store, store_names

st.set_page_config(page_title="Store Intelligence", page_icon="📊", layout="wide")
st.markdown("""
<style>
.block-container {max-width:1480px;padding-top:2rem;padding-bottom:5rem;}
[data-testid="stAppViewContainer"] {background:#f7f9fb;}
[data-testid="stMetric"] {background:white;border:1px solid #e1e7ed;border-radius:10px;padding:18px 20px;}
[data-testid="stMetricLabel"] {color:#536579;}
h1,h2,h3 {letter-spacing:-.025em;}
[data-testid="stSidebar"] {background:#edf2f5;}
</style>
""", unsafe_allow_html=True)

if not DB_PATH.is_file():
    st.title("Store Intelligence")
    st.info("Prepare the store data first: python3 pipeline.py")
    st.stop()

stores = store_names()


def reset_filters(store):
    facets = filter_facets(store)
    return {"date_from": date.fromisoformat(facets["date_from"]), "date_to": date.fromisoformat(facets["date_to"]),
            "genre": "All genres", "title": "", "min_unit_price": None, "max_unit_price": None,
            "person_filter": "Any title", "customer_id": None, "sort_by": "date", "sort_desc": True, "limit": 100}


if "active_store" not in st.session_state or st.session_state.active_store not in stores:
    st.session_state.active_store = stores[0]
    st.session_state.update(reset_filters(stores[0]))
if "view" not in st.session_state:
    st.session_state.view = "overview"
if "messages" not in st.session_state:
    st.session_state.messages = []


def store_changed():
    st.session_state.update(reset_filters(st.session_state.active_store))


def clear_filters():
    st.session_state.update(reset_filters(st.session_state.active_store))


def chat_context():
    context = {key: st.session_state.get(key) for key in
               ("active_store", "view", "date_from", "date_to", "genre", "title", "min_unit_price",
                "max_unit_price", "customer_id", "sort_by", "sort_desc", "limit")}
    context["has_person_name"] = {"Any title": None, "With person names": True,
                                  "Without person names": False}[st.session_state.person_filter]
    return context


def handle_chat():
    prompt = st.session_state.chat_prompt
    if not prompt or not prompt.strip():
        return
    history = st.session_state.messages.copy()
    st.session_state.messages.append({"role": "user", "content": prompt})
    try:
        result = ask_openai(prompt, context=chat_context(), history=history)
        for key, value in result["state"].items():
            if key in {"date_from", "date_to"}:
                st.session_state[key] = date.fromisoformat(value)
            elif key == "has_person_name":
                st.session_state.person_filter = {None: "Any title", True: "With person names", False: "Without person names"}[value]
            else:
                st.session_state[key] = value
        st.session_state.messages.append({"role": "assistant", "content": result["answer"], "trace": result["trace"]})
    except (RuntimeError, ValueError, OSError) as exc:
        st.session_state.messages.append({"role": "assistant", "content": f"Request failed: {exc}"})


@st.cache_data(show_spinner=False)
def cached_store(store, modified):
    return load_store(store)


st.caption("RETAIL ANALYTICS")
st.title("Store Intelligence")
st.write("Revenue, authors and customers — one store at a time.")
st.radio("Store", stores, key="active_store", horizontal=True, on_change=store_changed, label_visibility="collapsed")
store = st.session_state.active_store
facets = filter_facets(store)
frames = cached_store(store, DB_PATH.stat().st_mtime_ns)

with st.sidebar:
    st.subheader("Refine the view")
    st.caption(store + " · All prices in USD")
    st.date_input("From", key="date_from")
    st.date_input("Through", key="date_to")
    st.selectbox("Genre", ["All genres", *facets["genres"]], key="genre")
    st.text_input("Title contains", key="title")
    low, high = st.columns(2)
    with low:
        st.number_input("Min unit price", min_value=0.0, max_value=1_000_000.0, value=None, step=1.0, key="min_unit_price")
    with high:
        st.number_input("Max unit price", min_value=0.0, max_value=1_000_000.0, value=None, step=1.0, key="max_unit_price")
    st.selectbox("Person names in title", ["Any title", "With person names", "Without person names"], key="person_filter")
    st.number_input("Customer ID", min_value=0, step=1, value=None, key="customer_id")
    st.divider()
    st.selectbox("Sort records by", ["date", "unit_price_usd", "paid_price", "quantity", "title"], key="sort_by")
    st.checkbox("Descending", key="sort_desc")
    st.number_input("Rows to display", min_value=1, max_value=1000, step=1, key="limit")
    st.button("Reset filters", on_click=clear_filters, use_container_width=True)
    st.caption("Person names use an author-token heuristic and may be missed or misidentified.")

context = chat_context()
if context["date_from"] > context["date_to"]:
    st.error("The start date must not be later than the end date.")
    st.stop()
if context["min_unit_price"] is not None and context["max_unit_price"] is not None and context["min_unit_price"] > context["max_unit_price"]:
    st.error("The minimum price must not exceed the maximum price.")
    st.stop()

sales = frames["sales"].copy()
mask = sales.date.ge(str(context["date_from"])) & sales.date.le(str(context["date_to"]))
if context["genre"] != "All genres":
    mask &= sales.genre.eq(context["genre"])
if context["title"]:
    mask &= sales.title.str.contains(context["title"], case=False, regex=False, na=False)
if context["has_person_name"] is not None:
    mask &= sales.has_person_name.eq(int(context["has_person_name"]))
if context["min_unit_price"] is not None:
    mask &= sales.unit_price_usd.ge(context["min_unit_price"])
if context["max_unit_price"] is not None:
    mask &= sales.unit_price_usd.le(context["max_unit_price"])
if context["customer_id"] is not None:
    mask &= sales.customer_id.eq(context["customer_id"])
sales = sales.loc[mask].copy()
filtered = (str(context["date_from"]) != facets["date_from"] or str(context["date_to"]) != facets["date_to"]
            or context["genre"] != "All genres" or bool(context["title"]) or context["has_person_name"] is not None
            or any(context[key] is not None for key in ("min_unit_price", "max_unit_price", "customer_id")))

unique_users = sales.customer_id.nunique() if filtered else frames["users"].customer_id.nunique()
unique_sets = sales.author_set_key.nunique() if filtered else frames["books"].author_set_key.nunique()
metrics = st.columns(4)
metrics[0].metric("Revenue", f"${int(sales.paid_price_cents.sum()) / 100:,.2f}")
metrics[1].metric("Real unique customers", f"{unique_users:,}")
metrics[2].metric("Unique author sets", f"{unique_sets:,}")
metrics[3].metric("Books sold", f"{int(sales.quantity.sum()):,}")
st.caption("Filtered order metrics" if filtered else "Full-store metrics · customer count includes users with no purchases · author sets include the whole catalog")
st.radio("Explore", VIEWS, format_func=str.title, horizontal=True, key="view", label_visibility="collapsed")

limit = int(context["limit"])
view = st.session_state.view
if sales.empty:
    st.info("No orders match these filters. Reset the filters or change the date range.")
else:
    daily = sales.groupby("date", as_index=False).agg(revenue_cents=("paid_price_cents", "sum"))
    daily["revenue_usd"] = daily.revenue_cents / 100
    top_days = daily.sort_values(["revenue_cents", "date"], ascending=[False, True]).head(5)
    authors = sales.groupby(["author_set_key", "author_set"], as_index=False).agg(
        books_sold=("quantity", "sum"), revenue_cents=("paid_price_cents", "sum"))
    authors = authors.sort_values(["books_sold", "author_set_key"], ascending=[False, True])
    customers = sales.groupby("customer_id", as_index=False).agg(total_cents=("paid_price_cents", "sum"),
                                                                 books_bought=("quantity", "sum"), orders=("order_id", "size"))
    customers = customers.merge(frames["customer_spending"][["customer_id", "user_ids", "aliases"]], on="customer_id", validate="one_to_one")
    customers["total_usd"] = customers.total_cents / 100
    customers = customers.sort_values(["total_cents", "customer_id"], ascending=[False, True])
    if view == "overview":
        chart, ranking = st.columns([2.3, 1])
        with chart:
            st.subheader("Daily revenue")
            chart_data = daily.set_index(pd.to_datetime(daily.date)).revenue_usd.sort_index()
            chart_data = chart_data.reindex(pd.date_range(context["date_from"], context["date_to"]), fill_value=0)
            st.line_chart(chart_data.rename("Revenue (USD)"), color="#17817c", height=320)
        with ranking:
            st.subheader("Top 5 revenue days")
            display = top_days[["date", "revenue_usd"]].rename(columns={"date": "Date", "revenue_usd": "Revenue (USD)"})
            st.dataframe(display, hide_index=True, column_config={"Revenue (USD)": st.column_config.NumberColumn(format="$%.2f")}, width="stretch")
        popular, buyer = st.columns(2)
        with popular, st.container(border=True):
            st.subheader("Most popular author set")
            for row in authors.loc[authors.books_sold.eq(authors.books_sold.max())].itertuples():
                st.write(row.author_set)
                st.caption(f"{int(row.books_sold):,} books sold · coauthors counted as one set")
        with buyer, st.container(border=True):
            st.subheader("Best buyer · reconciled identities")
            for row in customers.loc[customers.total_cents.eq(customers.total_cents.max())].itertuples():
                st.write(" · ".join(json.loads(row.aliases)))
                st.code(row.user_ids, language="json")
                st.caption(f"${row.total_usd:,.2f} spent · all associated user IDs shown")
    elif view == "orders":
        st.subheader("Orders")
        data = sales.sort_values([context["sort_by"], "order_id"], ascending=[not context["sort_desc"], True]).head(limit)
        st.dataframe(data[["order_id", "date", "user_id", "customer_id", "title", "author_set", "quantity", "unit_price_usd", "paid_price"]],
                     hide_index=True, width="stretch", column_config={"paid_price": st.column_config.NumberColumn(format="$%.2f")})
    elif view == "books":
        st.subheader("Books · observed sales prices")
        data = sales.groupby(["book_id", "title", "author_set", "genre"], as_index=False, dropna=False).agg(
            unit_price_usd=("unit_price_usd", "max"), min_unit_price_usd=("unit_price_usd", "min"),
            quantity=("quantity", "sum"), paid_price_cents=("paid_price_cents", "sum"), date=("date", "max"))
        data["paid_price"] = data.paid_price_cents / 100
        data = data.sort_values([context["sort_by"], "book_id"], ascending=[not context["sort_desc"], True]).head(limit)
        st.caption("Unit price shows the highest observed converted sales price per book in the selected orders.")
        st.dataframe(data.drop(columns=["paid_price_cents"]), hide_index=True, width="stretch")
    elif view == "customers":
        st.subheader("Customers · aliases combined")
        st.dataframe(customers[["customer_id", "user_ids", "aliases", "total_usd", "orders", "books_bought"]].head(limit),
                     hide_index=True, width="stretch", column_config={"total_usd": st.column_config.NumberColumn(format="$%.2f")})
    elif view == "authors":
        st.subheader("Author sets · ranked by books sold")
        authors["revenue_usd"] = authors.revenue_cents / 100
        st.dataframe(authors[["author_set", "books_sold", "revenue_usd"]].head(limit), hide_index=True, width="stretch")

st.divider()
st.subheader("Data assistant")
st.caption("Ask a question or change this view. For example: ‘Топ-5 самых дорогих книг’ or ‘Покажи заказы STORE2 за июнь 2025’.")
if not is_configured():
    st.info("To enable chat, add OPENAI_API_KEY to .env and restart Streamlit.")
for message in st.session_state.messages[-12:]:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("trace"):
            with st.expander("Query and action details"):
                for item in message["trace"]:
                    st.caption(item["tool"])
                    st.code(item["arguments"], language="json")
                    st.json(item["result"], expanded=False)
st.chat_input("Ask about a store or tell the dashboard what to show…", key="chat_prompt",
              on_submit=handle_chat, disabled=not is_configured(), max_chars=1500)
