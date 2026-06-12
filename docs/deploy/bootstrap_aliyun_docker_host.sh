#!/usr/bin/env bash
set -euo pipefail

# 用途：
# 1. 初始化 Ubuntu 22.04 的 Docker / Compose 环境
# 2. 创建 freight-agent 的标准目录
# 3. 校验容器化部署所需文件是否齐全
# 4. 在环境变量已正确填写的前提下，直接执行 docker compose up -d --build
#
# 使用方式：
# 1. 先通过 MobaXterm SSH 登录服务器
# 2. 确保项目代码已经上传到 /data/apps/freight-agent
# 3. 确保 deploy/.env.production 中的 fill_me 已替换为真实值
# 4. 执行：
#    bash /path/to/bootstrap_aliyun_docker_host.sh
#
# 说明：
# - 本脚本不会自动输入 SSH 密码
# - 本脚本不会自动格式化数据盘，避免误删数据
# - 如果 /data 还没挂载，请先手动完成挂载
# - 如果生产环境变量仍是占位值，脚本会主动退出，不会继续启动容器

SERVER_PUBLIC_IP="47.101.141.117"
DEPLOY_USER="${DEPLOY_USER:-root}"
APP_NAME="${APP_NAME:-freight-agent}"
APP_ROOT="${APP_ROOT:-/data/apps/${APP_NAME}}"
LOG_ROOT="${LOG_ROOT:-/data/logs/${APP_NAME}}"
BACKUP_ROOT="${BACKUP_ROOT:-/data/backups/${APP_NAME}}"
DOCKER_ROOT="${DOCKER_ROOT:-/data/docker/${APP_NAME}}"
TMP_ROOT="${TMP_ROOT:-/data/tmp}"

PROJECT_ROOT="${PROJECT_ROOT:-${APP_ROOT}}"
COMPOSE_FILE="${COMPOSE_FILE:-${PROJECT_ROOT}/docker-compose.yml}"
ENV_FILE="${ENV_FILE:-${PROJECT_ROOT}/deploy/.env.production}"
NGINX_CONF="${NGINX_CONF:-${PROJECT_ROOT}/deploy/nginx/default.conf}"

log() {
  echo "==> $*"
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

assert_file() {
  local file="$1"
  [[ -f "$file" ]] || fail "Required file not found: $file"
}

assert_dir() {
  local dir="$1"
  [[ -d "$dir" ]] || fail "Required directory not found: $dir"
}

check_placeholder_env() {
  local file="$1"
  if grep -q 'fill_me' "$file"; then
    fail "Production env file still contains fill_me placeholders: $file"
  fi
}

log "Server IP: ${SERVER_PUBLIC_IP}"
log "Deploy user: ${DEPLOY_USER}"
log "Project root: ${PROJECT_ROOT}"
log "Docker root: ${DOCKER_ROOT}"

assert_dir "/data"

log "Updating system packages..."
apt update
apt upgrade -y

log "Installing base packages..."
apt install -y ca-certificates curl gnupg lsb-release git unzip vim htop tree

log "Configuring Docker repository..."
install -m 0755 -d /etc/apt/keyrings
if [[ ! -f /etc/apt/keyrings/docker.gpg ]]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
fi

if [[ ! -f /etc/apt/sources.list.d/docker.list ]]; then
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
    tee /etc/apt/sources.list.d/docker.list > /dev/null
fi

log "Installing Docker Engine and Compose plugin..."
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

log "Enabling Docker service..."
systemctl enable docker
systemctl start docker

log "Creating standard directories..."
mkdir -p "${APP_ROOT}"
mkdir -p "${LOG_ROOT}"
mkdir -p "${BACKUP_ROOT}"
mkdir -p "${DOCKER_ROOT}/nginx"
mkdir -p "${TMP_ROOT}"

log "Creating runtime data directories under project..."
mkdir -p "${PROJECT_ROOT}/data/docs"
mkdir -p "${PROJECT_ROOT}/data/chroma"
mkdir -p "${PROJECT_ROOT}/data/cache"
mkdir -p "${PROJECT_ROOT}/data/exports"
mkdir -p "${PROJECT_ROOT}/deploy/nginx"

log "Checking required deployment files..."
assert_dir "${PROJECT_ROOT}"
assert_file "${PROJECT_ROOT}/Dockerfile"
assert_file "${PROJECT_ROOT}/.dockerignore"
assert_file "${COMPOSE_FILE}"
assert_file "${ENV_FILE}"
assert_file "${NGINX_CONF}"
assert_file "${PROJECT_ROOT}/requirements.txt"
assert_file "${PROJECT_ROOT}/main.py"

log "Checking production env placeholders..."
check_placeholder_env "${ENV_FILE}"

log "Checking Docker and Compose availability..."
docker --version
docker compose version

log "Validating docker compose configuration..."
cd "${PROJECT_ROOT}"
docker compose config >/dev/null

log "Building and starting containers..."
docker compose up -d --build

log "Waiting briefly for containers to initialize..."
sleep 5

log "Container status:"
docker compose ps

log "Recent container logs:"
docker compose logs --tail=80

log "Verifying local health endpoint through Nginx..."
curl --fail --silent http://127.0.0.1/health || fail "Local health check failed via Nginx"
echo

log "Checking log directory contents..."
ls -lah "${LOG_ROOT}" || true

cat <<EOF

Deployment finished.

What was done:
- Docker and Compose installed or refreshed
- Standard directories ensured
- Project deployment files validated
- docker compose up -d --build executed
- Local /health checked through Nginx

Next checks:
1. Open in browser: http://${SERVER_PUBLIC_IP}/health
2. Test chat API: http://${SERVER_PUBLIC_IP}/api/chat
3. Check logs: ${LOG_ROOT}
4. Check containers: cd ${PROJECT_ROOT} && docker compose ps

EOF
