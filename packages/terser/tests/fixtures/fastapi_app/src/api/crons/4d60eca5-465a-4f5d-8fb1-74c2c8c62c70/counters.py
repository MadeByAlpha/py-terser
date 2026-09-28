from collections import Counter

COUNTERS: dict[str, list[int]] = {
    "GET /numeric/stats": [3, 5, 8],
    "POST /documents/manifest": [1, 1, 2],
    "GET /relay/echo": [13, 21],
}


def rollup(counters: dict[str, list[int]]) -> dict[str, int]:
    methods = Counter()
    for route, hits in counters.items():
        methods[route.split(" ", 1)[0]] += sum(hits)
    return dict(sorted(methods.items()))
