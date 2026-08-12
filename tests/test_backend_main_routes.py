from pathlib import Path


def test_access_token_admin_routes_are_mounted_under_api_v1():
    main_py = Path("backend/main.py").read_text(encoding="utf-8")

    assert 'app.include_router(access_tokens.router, prefix=f"{settings.API_PREFIX}/v1")' in main_py
    assert 'app.include_router(mcp_gateway.admin_router, prefix=f"{settings.API_PREFIX}/v1"' in main_py
    assert "app.include_router(mcp_gateway.runtime_router)" in main_py
    assert "app.include_router(security_audit.router, prefix=settings.API_PREFIX)" in main_py


def test_api_entrypoints_use_supported_lifespan_startup():
    backend_main = Path("backend/main.py").read_text(encoding="utf-8")
    api_cli = Path("agent_manager/api/api_cli.py").read_text(encoding="utf-8")

    assert "lifespan=lifespan_with_startup(warmup_skill_scanner)" in backend_main
    assert "lifespan=lifespan_with_startup(warmup_skill_scanner)" in api_cli
    assert 'add_event_handler("startup"' not in backend_main
    assert 'add_event_handler("startup"' not in api_cli


def test_deploy_smoke_checks_backend_image_before_replacing_production():
    gitlab_ci = Path(".gitlab-ci.yml").read_text(encoding="utf-8")

    build_position = gitlab_ci.index('./build.sh -t "$IMAGE_TAG" -p linux/amd64 --all')
    smoke_position = gitlab_ci.index('from backend.main import app')
    deploy_position = gitlab_ci.index('install -m 0644 docker-compose.yaml "$DEPLOY_DIR/docker-compose.yaml"')

    assert build_position < smoke_position < deploy_position
    assert 'with TestClient(app) as client:' in gitlab_ci
    assert 'response = client.get("/health")' in gitlab_ci
    assert "response.raise_for_status()" in gitlab_ci


def test_mcp_runtime_is_proxied_in_dev_and_deployment():
    vite_config = Path("web/vite.config.js").read_text(encoding="utf-8")
    nginx_config = Path("deploy/nginx/default.conf").read_text(encoding="utf-8")

    assert "'/mcp/':" in vite_config
    assert "location /mcp/" in nginx_config
    assert "proxy_pass http://skill_manager_backend;" in nginx_config
