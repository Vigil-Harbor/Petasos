#!/usr/bin/env python
"""PET-184 record validator.

Validates a JSON document against a JSON Schema and exits 0 (valid) or 1
(invalid), printing each violation to stdout. Used by dispatch.ps1 for:

  - every marker and .meta.json write            (so the two canonical
    contracts are actually enforced, not merely documented)
  - the Decision 4 classifier's "schema-valid" predicate, against schema.json
    (PowerShell 5.1 has no Test-Json -Schema; that is 6.1+)

Usage:
  validate.py <schema.json> <document.json>
  validate.py <schema.json> --stdin        # document on stdin, UTF-8
"""
import json
import sys


def _load(path):
    # utf-8-sig tolerates a BOM if some other writer ever introduces one.
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def main(argv):
    if len(argv) != 3:
        print("usage: validate.py <schema.json> <document.json|--stdin>")
        return 2

    schema_path, doc_arg = argv[1], argv[2]

    try:
        schema = _load(schema_path)
    except Exception as exc:                      # noqa: BLE001
        print("SCHEMA-UNREADABLE %s: %s" % (schema_path, exc))
        return 2

    try:
        if doc_arg == "--stdin":
            raw = sys.stdin.buffer.read().decode("utf-8-sig")
            doc = json.loads(raw) if raw.strip() else None
            if doc is None:
                print("DOC-EMPTY")
                return 1
        else:
            doc = _load(doc_arg)
    except Exception as exc:                      # noqa: BLE001
        print("DOC-UNPARSEABLE: %s" % exc)
        return 1

    try:
        import jsonschema
    except ImportError:
        print("JSONSCHEMA-MISSING")
        return 2

    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
    if not errors:
        print("VALID")
        return 0

    for err in errors:
        loc = "/".join(str(p) for p in err.path) or "(root)"
        print("VIOL %s :: %s" % (loc, err.message))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
