-- Whole-store metrics. All identifiers are scoped to a store.
SELECT store, COUNT(DISTINCT customer_id) AS unique_users
FROM users GROUP BY store ORDER BY store;

SELECT store, COUNT(DISTINCT author_set_key) AS unique_author_sets
FROM books GROUP BY store ORDER BY store;

-- Top five dates per store, with earlier date breaking an equal-revenue tie.
WITH ranked AS (
    SELECT store, date, revenue_cents,
           ROW_NUMBER() OVER (PARTITION BY store ORDER BY revenue_cents DESC, date) AS position
    FROM daily_revenue
)
SELECT store, date, revenue_cents / 100.0 AS revenue_usd
FROM ranked WHERE position <= 5 ORDER BY store, position;

-- Keep every author-set winner in case of a tie.
SELECT a.store, a.author_set, a.books_sold
FROM author_sales AS a
JOIN (SELECT store, MAX(books_sold) AS top_count FROM author_sales GROUP BY store) AS best
ON a.store = best.store AND a.books_sold = best.top_count
ORDER BY a.store, a.author_set;

-- All IDs and aliases are retained, including aliases with no orders of their own.
SELECT a.store, a.customer_id, a.user_ids, a.aliases, a.total_cents / 100.0 AS total_usd
FROM customer_spending AS a
JOIN (SELECT store, MAX(total_cents) AS top_total FROM customer_spending GROUP BY store) AS best
ON a.store = best.store AND a.total_cents = best.top_total
ORDER BY a.store, a.customer_id;

-- Example open-ended chat question: top five expensive books, not order totals.
SELECT book_id, title, MAX(unit_price_usd) AS highest_observed_unit_price_usd
FROM sales WHERE store = 'STORE1'
GROUP BY book_id, title
ORDER BY highest_observed_unit_price_usd DESC, book_id LIMIT 5;
