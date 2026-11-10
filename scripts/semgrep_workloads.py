"""Reference fixture generator for the S7 protocol v3; not a gate."""

import hashlib
import json
import sys


def fragment(size: int, seed: int = 0) -> str:
    tail = "\neval(payload)\n"
    lines = ["import json\n"]
    used = len(lines[0])
    index = seed
    while True:
        line = f"value_{index:04d} = json.loads(payload).get('value', 0)\n"
        if used + len(line) + len(tail) + 2 > size:
            break
        lines.append(line)
        used += len(line)
        index += 1
    result = "".join(lines) + "#" + "p" * (size - used - len(tail) - 1) + tail
    assert len(result.encode("utf-8")) == size
    return result


def workload(parts: list[str]) -> dict[str, object]:
    text = "\n".join(parts)
    segments = []
    expected = []
    offset = 0
    for part in parts:
        segments.append([offset, offset + len(part)])
        start = offset + part.rindex("\neval(payload)\n") + 1
        expected.append(["petasos.semgrep.python.dynamic_code", start, start + 13])
        offset += len(part) + 1
    return {
        "payload_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "payload_bytes": len(text.encode("utf-8")),
        "selected_bytes": sum(len(part.encode("utf-8")) for part in parts),
        "distinct_fragments": len(set(parts)),
        "segments": segments,
        "expected_findings": expected,
    }


if __name__ == "__main__":
    manifest = {
        "workload_id": "eight_outstanding_three_profiles_16k_64k_v3",
        "generator_version": 3,
        "fixtures": {
            "single_16k": workload([fragment(16384)]),
            "sixteen_64k_repeated": workload([fragment(4096)] * 16),
            "sixteen_64k_distinct": workload([fragment(4096, i * 1000) for i in range(16)]),
        },
    }
    sys.stdout.buffer.write((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
