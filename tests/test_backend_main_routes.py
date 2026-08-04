from pathlib import Path


def test_access_token_admin_routes_are_mounted_under_api_v1():
    main_py = Path("backend/main.py").read_text(encoding="utf-8")

    assert 'app.include_router(access_tokens.router, prefix=f"{settings.API_PREFIX}/v1")' in main_py
    assert 'app.include_router(mcp_gateway.admin_router, prefix=f"{settings.API_PREFIX}/v1"' in main_py
    assert "app.include_router(mcp_gateway.runtime_router)" in main_py
    assert "app.include_router(security_audit.router, prefix=settings.API_PREFIX)" in main_py


def test_mcp_runtime_is_proxied_in_dev_and_deployment():
    vite_config = Path("web/vite.config.js").read_text(encoding="utf-8")
    nginx_config = Path("deploy/nginx/default.conf").read_text(encoding="utf-8")

    assert "'/mcp/':" in vite_config
    assert "location /mcp/" in nginx_config
    assert "proxy_pass http://skill_manager_backend;" in nginx_config
