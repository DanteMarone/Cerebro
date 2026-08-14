"""Static assets must be served with types a browser will execute.

This exists because the entire UI once rendered blank against a fully green test suite: Python
resolves MIME types from the Windows registry, where `.mjs` is `text/plain`, and browsers refuse
to execute an ES module served as text. Nothing in a unit test notices a blank page.
"""

from fastapi.testclient import TestClient

from cerebro.api.app import app


def client():
    """No context manager: these assertions need routing only, not the app lifespan."""
    return TestClient(app)


def test_index_is_served():
    resp = client().get("/")
    assert resp.status_code == 200
    assert "<script" in resp.text


def test_app_imports_hooks_from_hooks_module():
    """Preact core does not export hooks; importing them there leaves the entire UI blank."""
    app_source = client().get("/static/app.js").text
    assert 'from "./vendor/hooks.module.js"' in app_source
    core_import = app_source.split('from "./vendor/preact.module.js"')[0].split("import")[-1]
    assert "useState" not in core_import


def test_vendored_modules_are_served_as_javascript():
    """A module served as text/plain is rejected by strict MIME checking and the app is blank."""
    c = client()
    modules = (
        "/static/vendor/preact.module.js",
        "/static/vendor/hooks.module.js",
        "/static/vendor/htm.module.js",
        "/static/app.js",
    )
    for path in modules:
        resp = c.get(path)
        assert resp.status_code == 200, path
        content_type = resp.headers["content-type"].split(";")[0]
        assert content_type in ("text/javascript", "application/javascript"), (
            f"{path} served as {content_type!r}, which a browser will not execute as a module"
        )


def test_stylesheet_is_served_as_css():
    c = client()
    resp = c.get("/static/style.css")
    assert resp.status_code == 200
    assert resp.headers["content-type"].split(";")[0] == "text/css"
