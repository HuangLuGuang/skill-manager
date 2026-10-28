from pathlib import Path

import yaml


def test_nginx_configs_hide_version_tokens():
    for config_path in (Path("deploy/nginx/default.conf"), Path("web/nginx.conf")):
        nginx_config = config_path.read_text(encoding="utf-8")

        assert "server_tokens off;" in nginx_config


def test_compose_proxy_preserves_client_ip_without_trusting_inbound_header():
    nginx_config = Path("deploy/nginx/default.conf").read_text(encoding="utf-8")
    compose_config = yaml.safe_load(Path("docker-compose.yaml").read_text(encoding="utf-8"))

    assert nginx_config.count("proxy_set_header X-Forwarded-For $remote_addr;") == nginx_config.count("proxy_pass ")
    assert "$proxy_add_x_forwarded_for" not in nginx_config
    assert compose_config["services"]["backend"]["environment"]["FORWARDED_ALLOW_IPS"] == (
        "${FORWARDED_ALLOW_IPS:-127.0.0.1,172.16.0.0/12}"
    )


def test_docs_spa_entry_does_not_collide_with_screenshot_directory():
    nginx_config = Path("web/nginx.conf").read_text(encoding="utf-8")

    assert "location = /docs {" in nginx_config
    assert "location = /docs/ {" in nginx_config
    assert nginx_config.count("try_files /index.html =404;") == 2
    assert "location / {\n        try_files $uri $uri/ /index.html;" in nginx_config


def test_deploy_smoke_checks_docs_entry_before_replacing_production():
    gitlab_ci = Path(".gitlab-ci.yml").read_text(encoding="utf-8")

    build_position = gitlab_ci.index('./build.sh -t "$IMAGE_TAG" -p linux/amd64 --all')
    smoke_position = gitlab_ci.index('docker run --rm --entrypoint sh "agent-manager-frontend:${IMAGE_TAG}"')
    deploy_position = gitlab_ci.index('install -m 0644 docker-compose.yaml "$DEPLOY_DIR/docker-compose.yaml"')

    assert build_position < smoke_position < deploy_position
    assert "wget -qO- http://127.0.0.1/docs >/dev/null" in gitlab_ci
    assert "wget -qO- http://127.0.0.1/docs/ >/dev/null" in gitlab_ci
