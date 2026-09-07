def test_package_imports():
    import uts_engine  # noqa: F401
    import uts_engine.cli  # noqa: F401
    import uts_engine.host  # noqa: F401
    import uts_engine.discovery.discovery  # noqa: F401
    import uts_engine.planning.ai_brain  # noqa: F401
    import uts_engine.automation.base  # noqa: F401
    import uts_engine.exporters.report_generator  # noqa: F401
    import uts_engine.exporters.alm.exporter  # noqa: F401
    import uts_engine.exporters.xpedite.exporter  # noqa: F401


def test_slugify_module():
    from uts_engine.discovery.module_filter import slugify_module

    assert slugify_module("My Module Name!!") == "my_module_name"
    assert slugify_module("") == "module"
