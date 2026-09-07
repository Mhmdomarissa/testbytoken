from tbt_api.config import is_allowed_target, normalize_target


def test_normalize_bare_domain_gets_https():
    assert normalize_target("example.com") == "https://example.com"


def test_normalize_keeps_explicit_scheme():
    assert normalize_target("http://example.com") == "http://example.com"


def test_normalize_windows_path_is_detected():
    # pathlib.Path.as_uri() only resolves this on an actual Windows host
    # (WindowsPath vs PosixPath), so just confirm the pattern is recognized
    # rather than exercising the platform-specific URI conversion here.
    from tbt_api.config import _WINDOWS_PATH

    assert _WINDOWS_PATH.match(r"C:\pages\report.html")


def test_local_demo_allows_everything(monkeypatch):
    monkeypatch.setattr("tbt_api.config.LOCAL_DEMO", True)
    assert is_allowed_target("http://localhost:9999") is True


def test_blocks_localhost_when_not_local_demo(monkeypatch):
    monkeypatch.setattr("tbt_api.config.LOCAL_DEMO", False)
    assert is_allowed_target("http://localhost:9999") is False


def test_blocks_private_ip_when_not_local_demo(monkeypatch):
    monkeypatch.setattr("tbt_api.config.LOCAL_DEMO", False)
    assert is_allowed_target("http://10.0.0.5") is False


def test_allows_public_host_when_not_local_demo(monkeypatch):
    monkeypatch.setattr("tbt_api.config.LOCAL_DEMO", False)
    assert is_allowed_target("https://example.com") is True
