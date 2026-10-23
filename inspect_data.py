"""Inventory real store inputs without imposing a source schema or editing files."""
import argparse
import csv
import io
import json
from pathlib import Path
import zipfile


TASK_DIR = Path(__file__).resolve().parent
SUPPORTED = {".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".xlsx", ".zip", ".yaml", ".yml", ".parquet"}
MAX_FILE_BYTES = 64 * 1024 * 1024


def json_structure(value, depth=0):
    """Describe actual keys and nested arrays; do not infer entity names."""
    if depth >= 4:
        return {"type": type(value).__name__}
    if isinstance(value, dict):
        return {"type": "object", "fields": {
            key: json_structure(item, depth + 1) for key, item in value.items()
        }}
    if isinstance(value, list):
        result = {"type": "array", "length": len(value)}
        if value:
            result["first_item"] = json_structure(value[0], depth + 1)
        if value and all(isinstance(item, dict) for item in value):
            result["record_keys"] = sorted({key for item in value for key in item})
        return result
    return {"type": type(value).__name__}


def inspect_csv(payload, suffix, encoding):
    text = payload.decode(encoding)
    try:
        dialect = csv.Sniffer().sniff(text[:65536], delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if suffix == ".tsv" else ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    header = next(reader, [])
    row_count, malformed, empty, samples = 0, 0, 0, []
    for row in reader:
        if not row or all(not cell.strip() for cell in row):
            empty += 1
            continue
        row_count += 1
        malformed += len(row) != len(header)
        if len(samples) < 3:
            samples.append(row)
    return {"format": "delimited", "encoding": encoding, "delimiter": delimiter,
            "columns": header, "duplicate_headers": len(header) != len(set(header)),
            "row_count": row_count, "empty_rows": empty,
            "rows_with_wrong_field_count": malformed, "sample_rows": samples}


def inspect_payload(path, payload, encoding):
    suffix = Path(path).suffix.lower()
    if suffix in {".yaml", ".yml"}:
        import yaml

        value = yaml.safe_load(payload.decode(encoding))
        return {"format": "yaml", "structure": json_structure(value),
                "sample": value[:3] if isinstance(value, list) else json_structure(value)}
    if suffix == ".parquet":
        import pandas as pd

        frame = pd.read_parquet(io.BytesIO(payload))
        return {"format": "parquet", "row_count": len(frame), "columns": list(frame.columns),
                "dtypes": frame.dtypes.astype(str).to_dict(), "missing": frame.isna().sum().to_dict(),
                "sample_rows": frame.head(3).fillna("").astype(str).values.tolist()}
    if suffix in {".csv", ".tsv"}:
        return inspect_csv(payload, suffix, encoding)
    if suffix == ".json":
        value = json.loads(payload.decode(encoding))
        return {"format": "json", "structure": json_structure(value),
                "sample": value[:3] if isinstance(value, list) else json_structure(value)}
    if suffix in {".jsonl", ".ndjson"}:
        records = [json.loads(line) for line in payload.decode(encoding).splitlines() if line.strip()]
        return {"format": "jsonl", "structure": json_structure(records), "sample": records[:3]}
    if suffix == ".xlsx":
        import pandas as pd

        sheets = pd.read_excel(io.BytesIO(payload), sheet_name=None, dtype=object)
        return {"format": "xlsx", "sheets": {
            name: {"row_count": len(frame), "columns": [str(col) for col in frame.columns],
                   "sample_rows": frame.head(3).fillna("").astype(str).values.tolist()}
            for name, frame in sheets.items()
        }}
    raise ValueError(f"Unsupported file format: {suffix}")


def inspect_archive(path, archive, encoding):
    results = []
    for member in archive.infolist():
        if member.is_dir() or "__MACOSX" in Path(member.filename).parts:
            continue
        if Path(member.filename).suffix.lower() not in SUPPORTED:
            continue
        virtual_path = f"{path}!/{member.filename}"
        if member.file_size > MAX_FILE_BYTES:
            results.append({"path": virtual_path, "error": "File exceeds the 64 MiB inspection limit"})
            continue
        results.extend(inspect_bytes(virtual_path, archive.read(member), encoding))
    return results


def inspect_bytes(path, payload, encoding):
    try:
        if Path(path).suffix.lower() == ".zip":
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                return inspect_archive(path, archive, encoding)
        return [{"path": str(path), "bytes": len(payload), **inspect_payload(path, payload, encoding)}]
    except (ValueError, UnicodeError, csv.Error, zipfile.BadZipFile, ImportError) as exc:
        return [{"path": str(path), "error": f"{type(exc).__name__}: {exc}"}]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, default=TASK_DIR / "data")
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.source.exists():
        parser.exit(2, f"Source path does not exist: {args.source}\n")
    candidates = [args.source] if args.source.is_file() else sorted(args.source.rglob("*"))
    paths = [path for path in candidates if path.is_file() and path.suffix.lower() in SUPPORTED
             and (args.output is None or path.resolve() != args.output.resolve())]
    if not paths:
        parser.exit(2, f"No store source files found in {args.source}. Add the original archive or STORE folders.\n")
    results = []
    for path in paths:
        if path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path) as archive:
                    results.extend(inspect_archive(str(path), archive, args.encoding))
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                results.append({"path": str(path), "error": str(exc)})
        elif path.stat().st_size > MAX_FILE_BYTES:
            results.append({"path": str(path), "error": "File exceeds the 64 MiB inspection limit"})
        else:
            results.extend(inspect_bytes(str(path), path.read_bytes(), args.encoding))
    report = {"source": str(args.source.resolve()), "files": results,
              "note": "Inspection only. No fields mapped or records cleaned. Samples may contain personal data."}
    encoded = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
        print(f"Inventory saved to {args.output}; inspected {len(results)} entries.")
    else:
        print(encoded)
    return int(any("error" in item for item in results))


if __name__ == "__main__":
    raise SystemExit(main())
