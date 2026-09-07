from tbt_api.main import app


def _all_paths(routes) -> set[str]:
    """Route paths, recursing into included sub-routers.

    Newer Starlette wraps an include_router() call in an opaque
    _IncludedRouter rather than flattening its routes into app.routes, so a
    plain [r.path for r in app.routes] misses everything under /plan, /run
    and /uts — walk .original_router when present.
    """
    paths: set[str] = set()
    for r in routes:
        p = getattr(r, "path", None)
        if p:
            paths.add(p)
        sub = getattr(r, "original_router", None)
        if sub is not None:
            paths |= _all_paths(sub.routes)
    return paths


def test_app_registers_expected_routes():
    paths = _all_paths(app.routes)
    assert "/health" in paths
    assert "/plan" in paths
    assert "/run" in paths
    assert "/shots" in paths
    assert "/uts/scan" in paths
    assert "/uts/run" in paths
