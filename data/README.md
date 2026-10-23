# Source data

Place the original Task #4 archive or STORE folders here, for example directly as supplied by the organizer. Preserve original filenames and folder structure.

The supplied inputs are STORE1 through STORE5. Each store contains `users.csv`, `orders.parquet`, and `books.yaml`. Do not substitute the Task #3.5 JSON or fabricated data.

From the project root, inventory the supplied source files with:

```sh
python3 task-04/inspect_data.py --output task-04/results/source_inventory.json
```

The inventory contains paths, headers/JSON structure, and up to three example records. It may include customer data; it is for local schema analysis and must not be publicly committed without review. Source files are read only. ZIP archives are inspected in place, without extracting their contents.
