# Task #4 DATA — accepted requirements

Deadline: **23.10.2026**. Recipient: **p.lebedev@itransition.com**.

The general three-part announcement and the later DATA announcement describe the same assignment. The DATA announcement supplies the dataset, calculations, dashboard contents, deadline, and submission method. Task #3.5 books are not the source data for this task.

## Part 1: store analytics

Process STORE1 and every other supplied store separately using pandas. The announcement mentions three views; the supplied input actually has **five stores (STORE1–STORE5)**. The dashboard provides five independent store views; do not combine their results.

- Inspect actual files, source fields, relationships, encodings, currencies, and timestamp formats before writing source mappings.
- Clean types, duplicate records, missing values, and malformed values. Record each decision and rejected record; preserve the original files.
- Parse timestamps and extract calendar dates: year, month, day. Resolve timezone/date-format ambiguities from the input rather than guessing.
- Add `paid_price = quantity * unit_price` to orders, converting EUR to USD at 1.2. Use decimal arithmetic/integer cents so monetary calculations are reproducible. Document the rounding convention after inspecting price precision.
- Compute daily revenue as the sum of paid prices and rank the top five dates. Render dates as `YYYY-MM-dd`. Document deterministic handling of ties.
- Reconcile customer records, assuming one identity field can change. Report real unique customer count, retain all source user IDs, and save an audit of merges. Missing values alone must not establish that two people are the same person. Determine identity fields and rules from the supplied schema.
- Count unique author sets. A+B, A, and B are three sets. Canonicalize author order; do not split a real person's name using an unverified separator.
- Find the most popular author or author set by **sold quantity**, not order-row count. Preserve coauthored sets; document ties and interpretation against actual data.
- Find the best buyer by total spending after reconciliation and list all associated `user_id` values as an array. Document ties.
- Plot daily revenue as a line chart. Show all required metrics neatly in a BI-style dashboard for each store.

## Parts 2 and 3: chat

- Add a visible chat area to the application.
- Answer natural-language questions using API/tool results; do not send the complete dataset to the model or ask the model to calculate totals itself.
- Support general analysis via a query tool rather than a separate function for each question. Candidate implementation: restricted, read-only SQL against cleaned store data, with table/operation restrictions and time/result-size limits. Final schema depends on the supplied files.
- Allow the model to change the dashboard through validated state/filter updates. A tool must actually apply the command; a text acknowledgement is insufficient.
- Use the existing local OpenAI key configuration. Do not make paid API requests during preparation.
- Distinguish mathematical calculations from semantic predicates such as detecting person names. Such predicates need their own documented implementation; SQL alone does not recognize human names.

## Deliverables

- Reproducible ingestion/cleaning pipeline and dependencies.
- Source-schema mapping based on actual input.
- Cleaning/reconciliation audit and computed results for each store.
- Online browser-accessible dashboard with three store views and a chat area.
- Code repository URL and dashboard URL sent by email to the recipient above.

No video is required in the supplied Task #4 announcement. Repository publication, deployment, and sending email require Vlad's explicit authorization. No submission has been confirmed.

## Implementation state

All five actual stores are ingested. Cleaned tables, identity-merge audits, aggregate results and matplotlib charts are saved under `results/`. The new Streamlit dashboard has independent store views and SQL-backed OpenAI chat/control; `public/index.html` is a standalone static Part 1 dashboard. The old book prototype is archived under `prototype-books/`.

Vlad manually confirmed that the live chat works. The engineering agent did not make paid OpenAI requests or finish browser-rendered inspection. A local Git repository has been initialized; GitHub ownership/visibility is awaiting Vlad's choice. Public deployment and email submission remain pending. See README.md for source mappings, calculation rules and actual execution details.
