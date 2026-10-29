#!/bin/bash
set -euo pipefail
export LC_ALL=C

DEPLOY_FILES=(docker-compose.yaml .env.example release-provenance.json release-info
    docker-compose.https.yaml deploy/nginx/https.sh deploy/nginx/certificates.py
    docker-compose.model-gateway.yaml deploy/nginx/model-gateway.conf
    start.sh upgrade.sh deploy/offline.sh deploy/nginx/default.conf
    docs/offline-deployment.md docs/docker-deployment.md docs/license.md)
COMPOSE_COMMAND=(docker compose)
STAGING= BACKUP=

die() { echo "[ERROR] $*" >&2; exit 1; }
cleanup() {
    local status=$?
    if [[ $status != 0 && -n $BACKUP ]]; then
        echo "[ERROR] 升级未完成，部署文件备份保留在 $BACKUP；请检查服务状态及数据迁移情况" >&2
    fi
    [[ -z $STAGING ]] || rm -rf -- "$STAGING"
    return "$status"
}
trap cleanup EXIT

probe() { timeout 20 "$@"; }
check_runtime() {
    command -v docker >/dev/null || die 'Docker 未安装或未加入 PATH；请使用 installers/ 中的离线安装程序'
    local error help candidate found=false
    if ! ARCHITECTURE=$(probe docker info --format '{{.Architecture}}' 2>&1); then
        error=$ARCHITECTURE
        case "$error" in
            *'permission denied'*|*'access is denied'*|*'operation not permitted'*) die '当前用户无权访问 Docker 服务；请检查用户组和 socket/context' ;;
            *'Cannot connect'*|*'connection refused'*|*'no such file or directory'*) die 'Docker 服务可能未启动；请检查 context/DOCKER_HOST 和 systemctl status docker' ;;
            *) die 'Docker 服务检查失败或超时；请检查 docker info、TLS 或认证配置' ;;
        esac
    fi
    for candidate in plugin standalone; do
        if [[ $candidate == plugin ]]; then COMPOSE_COMMAND=(docker compose); else COMPOSE_COMMAND=(docker-compose); fi
        command -v "${COMPOSE_COMMAND[0]}" >/dev/null || continue
        probe "${COMPOSE_COMMAND[@]}" version >/dev/null 2>&1 || continue
        found=true
        help=$(probe "${COMPOSE_COMMAND[@]}" up --help) || continue
        [[ $help =~ (^|[[:space:],])--wait([[:space:],=]|$) && $help =~ (^|[[:space:],])--wait-timeout([[:space:],=]|$) ]] || continue
        help=$(probe "${COMPOSE_COMMAND[@]}" config --help) || continue
        [[ $help =~ (^|[[:space:],])--images([[:space:],=]|$) ]] || continue
        echo "[INFO] Docker 服务可用；使用 ${COMPOSE_COMMAND[*]}"
        return
    done
    $found && die 'Compose 版本不兼容；需支持 up --wait --wait-timeout、config --images 和当前编排格式'
    die 'docker compose 和 docker-compose 均不可用；请安装兼容的 Compose'
}

compose() (
    local source=$1
    shift
    local command=("${COMPOSE_COMMAND[@]}" --project-directory "$ROOT" -f "$source/docker-compose.yaml")
    if [[ $PROTOCOL == https ]]; then
        command+=(-f "$source/docker-compose.https.yaml" --profile https)
    fi
    if [[ -f $ROOT/.env ]] && awk '/^MODEL_GATEWAY_HTTP_ENABLED=true$/ {found=1} END {exit !found}' "$ROOT/.env"; then
        command+=(-f "$source/docker-compose.model-gateway.yaml")
    fi
    [[ ! -f $ROOT/.env ]] || command+=(--env-file "$ROOT/.env")
    unset HTTP_PORT TLS_HOSTS MODEL_GATEWAY_HTTP_PORT MODEL_GATEWAY_PUBLIC_URL
    cd "$ROOT"
    "${command[@]}" "$@"
)

read_release() {
    local source=$1 name extra
    for name in "${DEPLOY_FILES[@]}"; do
        [[ -f $source/$name ]] || die "安装包缺少部署文件：$name"
    done
    { IFS= read -r VERSION && IFS= read -r PLATFORM && extra=$(cat); } < "$source/release-info" || die '安装包版本信息必须为版本、平台两行文本'
    [[ -z $extra && $VERSION =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || die '安装包版本号无效'
    case "$PLATFORM" in
        linux/amd64) IMAGE="docker_images/x86/agent-manager-images-$VERSION.tar.xz" ;;
        linux/arm64) IMAGE="docker_images/arm/agent-manager-images-$VERSION.tar.xz" ;;
        *) die '安装包架构必须为 linux/amd64 或 linux/arm64' ;;
    esac
    [[ -s $source/$IMAGE ]] || die "安装包缺少离线镜像：$IMAGE"
}

prepare_environment() {
    if [[ ! -f $ROOT/.env ]]; then
        (umask 077; cp "$ROOT/.env.example" "$ROOT/.env"; chmod 600 "$ROOT/.env")
        echo '[INFO] 已从配置模板创建 .env；生产配置说明见 docs/offline-deployment.md'
    fi
    if [[ -n $PORT ]]; then
        local temp
        temp=$(mktemp "$ROOT/.env.XXXXXX")
        if ! awk -v port="$PORT" '
            /^[ \t]*(export[ \t]+)?HTTP_PORT[ \t]*=/ {print "HTTP_PORT=" port; found=1; next}
            {print} END {if (!found) print "HTTP_PORT=" port}
        ' "$ROOT/.env" > "$temp"; then rm -f "$temp"; die '端口配置写入失败'; fi
        chmod --reference="$ROOT/.env" "$temp"
        mv -f "$temp" "$ROOT/.env"
        echo "[INFO] 访问端口 $PORT 已保存到 .env（HTTP_PORT）"
    fi
}

save_protocol() {
    local temp
    if [[ $PROTOCOL == http ]] && ! awk '/^[ \t]*(export[ \t]+)?DEPLOY_PROTOCOL[ \t]*=/ {found=1} END {exit !found}' "$ROOT/.env"; then
        return
    fi
    temp=$(mktemp "$ROOT/.env.XXXXXX")
    awk -v protocol="$PROTOCOL" '
        /^[ \t]*(export[ \t]+)?DEPLOY_PROTOCOL[ \t]*=/ {next}
        {print} END {print "DEPLOY_PROTOCOL=" protocol}
    ' "$ROOT/.env" > "$temp"
    chmod --reference="$ROOT/.env" "$temp"
    mv -f "$temp" "$ROOT/.env"
}

preflight() {
    local source=$1 name
    read_release "$source"
    check_runtime
    case "$ARCHITECTURE" in x86_64) ARCHITECTURE=amd64 ;; aarch64) ARCHITECTURE=arm64 ;; esac
    [[ $PLATFORM == "linux/$ARCHITECTURE" ]] || die "安装包架构 $PLATFORM 与 Docker 架构 $ARCHITECTURE 不一致"
    # Compose diagnostics can contain credentials; only show a fixed error.
    IMAGES=$(compose "$source" config --images 2>/dev/null) || die 'Compose 无法解析部署配置；请检查 .env、docker-compose.yaml 和 env_file.required 支持'
    [[ -n $IMAGES ]] || die 'Compose 未返回镜像'
    while IFS= read -r name; do
        if [[ $name == agent-manager-* && ${name##*:} != "$VERSION" ]]; then
            die 'Compose 应用镜像版本与安装包版本不一致'
        fi
    done <<< "$IMAGES"
}

load_images() {
    local source=$1 name actual
    echo "[INFO] 加载离线镜像：$IMAGE"
    docker load --input "$source/$IMAGE"
    while IFS= read -r name; do
        actual=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$name")
        [[ $actual == "$PLATFORM" ]] || die "镜像 $name 架构为 $actual，期望 $PLATFORM"
    done <<< "$IMAGES"
}

start_services() {
    prepare_environment
    if [[ $PROTOCOL == http ]]; then
        compose "$ROOT" stop certificates
    fi
    compose "$ROOT" run --rm --no-deps --pull never backend agent-manager signing-key init
    local args=(up -d --pull never --no-build --wait --wait-timeout "$WAIT_TIMEOUT")
    [[ $ACTION != upgrade ]] || args+=(--force-recreate)
    local page_check=(wget -q -O /dev/null http://127.0.0.1/)
    if [[ $PROTOCOL == https ]]; then
        page_check=(wget --no-check-certificate -q -O /dev/null https://127.0.0.1/)
    fi
    if ! compose "$ROOT" "${args[@]}" ||
        ! compose "$ROOT" exec -T backend python -m backend.aidr_signing --check ||
        ! compose "$ROOT" exec -T nginx "${page_check[@]}"; then
        compose "$ROOT" ps --all || true
        die '服务健康检查失败'
    fi
    compose "$ROOT" ps
    echo '[INFO] 服务健康检查及 Nginx 页面检查通过'
}

extract_package() {
    local path entry
    # Inspect the same private copy we extract; reject links and special files before writing.
    cp -- "$ARCHIVE" "$STAGING/package.tar.gz"
    tar --quoting-style=escape -tzf "$STAGING/package.tar.gz" > "$STAGING/paths" || die '安装包无法读取或包含不安全路径'
    while IFS= read -r path; do
        case "$path" in
            agent-manager|agent-manager/*) ;;
            *) die "安装包包含不安全路径：$path" ;;
        esac
        case "/$path/" in */../*|*\\*) die "安装包包含不安全路径：$path" ;; esac
    done < "$STAGING/paths"
    tar --quoting-style=escape -tvzf "$STAGING/package.tar.gz" > "$STAGING/types" || die '安装包无法读取'
    while IFS= read -r entry; do
        case "$entry" in -*|d*) ;; *) die '安装包包含不安全路径或文件类型' ;; esac
    done < "$STAGING/types"
    mkdir "$STAGING/extracted"
    tar -xzf "$STAGING/package.tar.gz" -C "$STAGING/extracted" --no-same-owner --no-same-permissions
    find "$STAGING/extracted" -type f -perm /111 -exec chmod 755 {} +
    find "$STAGING/extracted" -type f ! -perm /111 -exec chmod 644 {} +
    find "$STAGING/extracted" -type d -exec chmod 755 {} +
    SOURCE="$STAGING/extracted/agent-manager"
}

backup_installation() {
    local name
    mkdir -p "$ROOT/backups"
    BACKUP=$(mktemp -d "$ROOT/backups/$(date +%Y%m%d-%H%M%S)-XXXXXX")
    for name in "${DEPLOY_FILES[@]}" .env scanner/releases; do
        [[ -e $ROOT/$name ]] || continue
        mkdir -p "$BACKUP/$(dirname "$name")"
        cp -a -- "$ROOT/$name" "$BACKUP/$name"
    done
    echo "[INFO] 部署文件备份完成：$BACKUP（不含数据库和数据卷）"
}

install_release() {
    local files=("${DEPLOY_FILES[@]}" "$IMAGE") path name
    if [[ -d $SOURCE/scanner/releases ]]; then
        while IFS= read -r -d '' path; do files+=("${path#"$SOURCE/"}"); done < <(find "$SOURCE/scanner/releases" -type f -print0)
    fi
    for name in "${files[@]}" scanner/releases; do
        path="$ROOT/$name"
        while [[ $path != "$ROOT" ]]; do
            [[ ! -L $path ]] || die "部署目标路径包含软链接：$name"
            path=$(dirname "$path")
        done
    done
    for name in "${files[@]}"; do
        [[ ! -e $ROOT/$name || -f $ROOT/$name ]] || die "部署目标不是普通文件：$name"
    done
    for name in "${files[@]}"; do
        mkdir -p "$ROOT/$(dirname "$name")"
        mv -f -- "$SOURCE/$name" "$ROOT/$name"
    done
    mkdir -p "$ROOT/scanner/releases"
}

main() {
    ACTION=$1; shift
    ROOT= ARCHIVE= PORT= WAIT_TIMEOUT=300 PROTOCOL=http
    while (( $# )); do
        case "$1" in
            --http|--https)
                [[ $ACTION == start ]] || die '协议选项仅用于 start'
                PROTOCOL=${1#--}; shift ;;
            --install-dir=*|--wait-timeout=*|--port=*) set -- "${1%%=*}" "${1#*=}" "${@:2}" ;;
            --install-dir|--wait-timeout|--port)
                [[ $# -ge 2 && -n $2 ]] || die "$1 缺少参数"
                case "$1" in --install-dir) ROOT=$2 ;; --wait-timeout) WAIT_TIMEOUT=$2 ;; --port) PORT=$2 ;; esac
                shift 2 ;;
            -h|--help) echo '用法：start.sh [--http|--https] [--port 1–65535] [--wait-timeout 秒] [--install-dir 目录]；默认 HTTP，HTTPS 固定 443，--port 控制 HTTP/跳转端口。upgrade.sh 安装包.tar.gz [--wait-timeout 秒] [--install-dir 目录] 保留已选协议。HTTPS 访问域名/IP 在 .env 的 TLS_HOSTS 中设置（逗号分隔）。'; return ;;
            --*) die "未知参数：$1" ;;
            *) [[ $ACTION == upgrade && -z $ARCHIVE ]] || die "无效参数：$1"; ARCHIVE=$1; shift ;;
        esac
    done
    [[ $WAIT_TIMEOUT =~ ^[0-9]{1,9}$ ]] && (( 10#$WAIT_TIMEOUT > 0 )) || die '--wait-timeout 必须大于 0'
    WAIT_TIMEOUT=$((10#$WAIT_TIMEOUT))
    if [[ -n $PORT ]]; then
        [[ $ACTION == start && $PORT =~ ^[0-9]{1,5}$ ]] && (( 10#$PORT >= 1 && 10#$PORT <= 65535 )) || die '--port 仅用于 start，取值必须为 1–65535'
        PORT=$((10#$PORT))
    fi
    [[ $PROTOCOL != https || $PORT != 443 ]] || die 'HTTPS 模式的 HTTP 跳转端口不能为 443'
    local tool
    for tool in flock timeout tar gzip awk mktemp cmp; do command -v "$tool" >/dev/null || die "缺少系统工具：$tool"; done
    ROOT=$(cd -- "$ROOT" && pwd -P)
    exec 9>>"$ROOT/.offline-deploy.lock"
    flock -n 9 || die '该安装目录正在执行启动或升级，请等待现有操作结束'
    if [[ $ACTION == start ]]; then
        if [[ ! -f $ROOT/release-info && -f $ROOT/pyproject.toml && -f $ROOT/backend/Dockerfile ]]; then
            check_runtime
            prepare_environment
            save_protocol
            compose "$ROOT" config --quiet 2>/dev/null || die 'Compose 配置无效'
            start_services
            echo '[INFO] 源码目录启动完成（使用已构建或已加载的镜像）'
            return
        fi
        read_release "$ROOT"
        prepare_environment
        # Bare start always selects HTTP; upgrade reuses the last saved choice.
        save_protocol
        preflight "$ROOT"
        load_images "$ROOT"
        start_services
        echo "[INFO] 版本 $VERSION 启动完成"
    else
        if [[ -f $ROOT/.env ]] && awk '/^DEPLOY_PROTOCOL=https$/ {found=1} END {exit !found}' "$ROOT/.env"; then
            PROTOCOL=https
        fi
        [[ -f $ARCHIVE ]] || die 'upgrade 需要指定存在的安装包'
        [[ -f $ROOT/docker-compose.yaml ]] || die '目标目录缺少现有 docker-compose.yaml，请指定已有安装目录'
        STAGING=$(mktemp -d "$ROOT/.upgrade-XXXXXX")
        extract_package
        local runner_root
        runner_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
        [[ -f $SOURCE/upgrade.sh && -f $SOURCE/deploy/offline.sh ]] || die '安装包缺少升级脚本'
        if ! cmp -s "$runner_root/upgrade.sh" "$SOURCE/upgrade.sh" ||
            ! cmp -s "$runner_root/deploy/offline.sh" "$SOURCE/deploy/offline.sh"; then
            bash -n "$SOURCE/upgrade.sh" && bash -n "$SOURCE/deploy/offline.sh" || die '安装包升级脚本语法错误'
            echo '[INFO] 安装包升级脚本有更新，使用包内脚本执行升级'
            # The new runner acquires its own installation lock before making changes.
            exec 9>&-
            bash "$SOURCE/upgrade.sh" "$STAGING/package.tar.gz" --install-dir "$ROOT" --wait-timeout "$WAIT_TIMEOUT"
            return
        fi
        preflight "$SOURCE"
        backup_installation
        load_images "$SOURCE"
        install_release
        start_services
        echo "[INFO] 已升级到 $VERSION；备份：$BACKUP"
    fi
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then main "$@"; fi
