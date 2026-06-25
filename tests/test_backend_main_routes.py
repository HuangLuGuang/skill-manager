from pathlib import Path


def test_access_token_admin_routes_are_mounted_under_api_v1():
    main_py = Path("backend/main.py").read_text(encoding="utf-8")

    assert 'app.include_router(access_tokens.router, prefix=f"{settings.API_PREFIX}/v1")' in main_py
