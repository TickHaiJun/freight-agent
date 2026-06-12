# AI Freight Agent 阿里云 Ubuntu 22.04 部署教程

## 1. 文档目标

这份文档基于你当前的部署决策整理：

- 云服务器：`47.101.141.117`
- 系统：`Ubuntu 22.04`
- 架构：`Docker Compose + Nginx`
- 客户端工具：`MobaXterm`
- 当前阶段：`手动部署`

目标是从 0 到 1，把当前项目部署到阿里云服务器，并形成一套后续可复用的标准部署路径。

这份方案明确采用以下边界：

1. `FREIGHT_API_BASE` 云服务器可达
2. 外网不开放应用端口 `8012`
3. 对外统一通过 `Nginx` 转发
4. 先 SSH 登录，再执行初始化脚本
5. 当前先做手动部署，不做 GitHub CI/CD

---

## 2. 这次部署的目标架构

部署完成后的结构如下：

```text
浏览器 / 前端
    ->
公网 IP 47.101.141.117:80/443
    ->
Nginx 容器
    ->
freight-agent 应用容器
    ->
DeepSeek / DashScope / 运价接口
```

也就是说：

- 外部只访问 `80/443`
- 应用容器不直接暴露到公网
- Nginx 负责反向代理
- Docker Compose 负责管理容器

---

## 3. 为什么采用 Docker Compose + Nginx

这套方案适合你当前阶段，原因很明确：

### 3.1 比纯手动 `uvicorn + systemd` 更稳定

优点：

- 环境更一致
- 迁移更容易
- 更新更清晰
- 后续接 CI/CD 更顺

### 3.2 比现在就上 K8s 更简单

你当前只是单机单项目，不需要把复杂度拉到集群层。

### 3.3 比直接开放应用端口更合理

既然你已经明确不想开放 `8012`，那就应该：

- 让应用只在容器内监听
- 由 Nginx 做统一外部入口

这是更合理的生产入口设计。

---

## 4. 服务器目录规划

仍然建议把数据盘挂载到：

```text
/data
```

然后采用这套规划：

```text
/data
├── apps
│   └── freight-agent
├── logs
│   └── freight-agent
├── backups
│   └── freight-agent
├── docker
│   └── freight-agent
└── tmp
```

目录职责如下。

### 4.1 `/data/apps/freight-agent`

放项目代码仓库。

### 4.2 `/data/logs/freight-agent`

放应用日志，容器通过挂载卷写入这里。

### 4.3 `/data/backups/freight-agent`

放备份包、回滚包、配置备份。

### 4.4 `/data/docker/freight-agent`

放部署层文件，例如：

- `docker-compose.yml`
- `nginx.conf`
- `.env.production`

如果你想把“源码”和“部署配置”分开，这个目录很有用。

---

## 5. 安全组怎么放

当前方案下，安全组建议开放：

1. `22/TCP`
2. `80/TCP`
3. `443/TCP`

不建议开放：

1. `8012/TCP`

原因：

- `8012` 应该只给容器内部或宿主机内部使用
- 外部访问统一走 `Nginx`

---

## 6. 你会用到哪些工具

### 6.1 必备

1. `MobaXterm`
2. `Git`
3. `VS Code`

### 6.2 MobaXterm 的使用方式

你这次最适合的流程是：

1. 用 MobaXterm 新建 SSH Session
2. 连接到 `47.101.141.117`
3. 输入用户名
4. 输入密码
5. 登录后把 `.sh` 上传到服务器
6. 在终端里执行脚本

注意：

- SSH 密码不建议写进脚本
- 脚本应在登录成功后运行

---

## 7. 部署前你需要知道的项目改动范围

如果要正式采用 `Docker Compose + Nginx` 架构，这个项目后续需要新增或调整这些文件。

### 7.1 预计新增的文件

1. `Dockerfile`
2. `.dockerignore`
3. `docker-compose.yml`
4. `deploy/nginx/default.conf`
5. `deploy/.env.production.example`

### 7.2 可能调整的文件

1. `README.md`
2. `docs/deploy/...`
3. `config.py`
4. 日志目录相关说明

### 7.3 为什么这些文件需要加

因为你现在项目本身还不是容器化项目，当前仓库核心运行方式还是：

```bash
uvicorn main:app ...
```

而采用 Docker Compose 部署，至少需要补这几个层次：

1. 应用镜像怎么构建
2. 容器怎么启动
3. Nginx 怎么代理
4. 日志和文档目录怎么挂载
5. 生产环境变量怎么管理

---

## 8. 整体部署步骤

部署会分成 3 段。

### 第一段：服务器初始化

包括：

1. SSH 登录
2. 更新系统
3. 安装 Docker
4. 安装 Docker Compose 插件
5. 创建目录

### 第二段：项目和部署文件准备

包括：

1. 拉取项目代码
2. 上传或创建部署文件
3. 配 `.env.production`
4. 准备 Nginx 配置

### 第三段：启动和验证

包括：

1. `docker compose up -d`
2. 看容器状态
3. 验证 `/health`
4. 验证 `/api/chat`
5. 检查日志目录

---

## 9. 第一步：用 MobaXterm 登录服务器

### 9.1 新建会话

在 MobaXterm：

1. 点击 `Session`
2. 选择 `SSH`
3. Remote host 填：

```text
47.101.141.117
```

4. 勾选 `Specify username`
5. 用户名填：

```text
root
```

或者如果不是 root，就填你的实际用户。

密码这里你后续自己输入，不写进文档。

### 9.2 首次登录后先执行

```bash
whoami
uname -a
lsblk
df -h
```

确认：

1. 当前用户
2. Ubuntu 版本
3. 数据盘是否识别
4. 当前文件系统情况

---

## 10. 第二步：数据盘挂载

如果数据盘还没挂载，仍然建议挂到：

```text
/data
```

### 10.1 查看磁盘

```bash
lsblk
sudo fdisk -l
```

通常会看到类似：

```text
/dev/vda   系统盘
/dev/vdb   数据盘
```

### 10.2 如果数据盘是空盘

注意：这一步会清空该盘数据。

```bash
sudo mkfs.ext4 /dev/vdb
```

### 10.3 挂载

```bash
sudo mkdir -p /data
sudo mount /dev/vdb /data
df -h
```

### 10.4 开机自动挂载

```bash
sudo blkid /dev/vdb
```

拿到 UUID 后编辑：

```bash
sudo vim /etc/fstab
```

追加：

```text
UUID=你的UUID /data ext4 defaults,nofail 0 2
```

验证：

```bash
sudo mount -a
df -h
```

---

## 11. 第三步：安装 Docker 与 Compose

在 Ubuntu 上执行：

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y ca-certificates curl gnupg lsb-release git unzip vim
```

添加 Docker 官方源：

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
```

```bash
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

安装 Docker：

```bash
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

验证：

```bash
docker --version
docker compose version
```

如果你不是 root 用户，追加到 docker 组：

```bash
sudo usermod -aG docker $USER
```

然后重新登录。

---

## 12. 第四步：创建目录结构

```bash
sudo mkdir -p /data/apps/freight-agent
sudo mkdir -p /data/logs/freight-agent
sudo mkdir -p /data/backups/freight-agent
sudo mkdir -p /data/docker/freight-agent
sudo mkdir -p /data/tmp
```

如果用普通用户部署，调整权限，例如当前用户是 `ubuntu`：

```bash
sudo chown -R ubuntu:ubuntu /data/apps
sudo chown -R ubuntu:ubuntu /data/logs
sudo chown -R ubuntu:ubuntu /data/backups
sudo chown -R ubuntu:ubuntu /data/docker
sudo chown -R ubuntu:ubuntu /data/tmp
```

---

## 13. 第五步：获取项目代码

推荐两种方式。

### 13.1 方式 A：GitHub 拉取

如果仓库已经在 GitHub：

```bash
cd /data/apps
git clone 你的仓库地址 freight-agent
```

### 13.2 方式 B：MobaXterm 上传

通过 MobaXterm 左侧 SFTP 面板把项目上传到：

```text
/data/apps/freight-agent
```

建议上传：

- 源码
- `graph/`
- `rag/`
- `tools/`
- `scripts/`
- `data/docs/`
- `requirements.txt`

不建议上传：

- `AiEnv/`
- `__pycache__/`
- `docs/history/`
- `data/chroma/`
- `data/cache/`

---

## 14. 第六步：部署层文件怎么放

当前建议把部署文件放在：

```text
/data/docker/freight-agent
```

例如：

```text
/data/docker/freight-agent
├── docker-compose.yml
├── .env.production
└── nginx
    └── default.conf
```

这样源码和部署层分离，后续维护更清晰。

---

## 15. 第七步：生产环境变量建议

建议新建：

```text
/data/docker/freight-agent/.env.production
```

示例内容：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

FREIGHT_API_BASE=你的正式报价接口地址

DASHSCOPE_API_KEY=your_dashscope_api_key
EMBEDDING_MODEL=qwen3-vl-embedding

CHROMA_PERSIST_DIR=/app/data/chroma
CHROMA_COLLECTION_NAME=freight_knowledge

RAG_ENABLE_VECTOR_SEARCH=false
RAG_TOP_K_VECTOR=8
RAG_TOP_K_BM25=8
RAG_TOP_K_FINAL=4
RAG_CHUNK_SIZE=500
RAG_CHUNK_OVERLAP=100
RAG_ENABLE_RERANK=false
RAG_VECTOR_SEARCH_TIMEOUT_SECONDS=8
RAG_DOCS_DIR=/app/data/docs

APP_LOG_DIR=/app/runtime/logs
APP_LOG_LEVEL=INFO
APP_LOG_FILE_PREFIX=freight-agent
APP_LOG_BACKUP_DAYS=30
APP_LOG_JSON_ENABLED=true
APP_LOG_DEBUG_STATE=false
APP_LOG_SERVICE_NAME=freight-agent
```

注意：

- 容器内路径和宿主机路径不一样
- 宿主机的 `/data/logs/freight-agent` 会通过 volume 映射到容器内 `/app/runtime/logs`

---

## 16. 第八步：Nginx 容器配置建议

建议未来新增：

```text
deploy/nginx/default.conf
```

基本结构应类似：

```nginx
server {
    listen 80;
    server_name 47.101.141.117;

    client_max_body_size 20m;

    location / {
        proxy_pass http://freight-agent-app:8012;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding off;
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }
}
```

这里的关键点是：

- `proxy_pass` 指向 Compose 内部服务名
- 不再写 `127.0.0.1:8012`
- SSE 场景要关闭缓冲

---

## 17. 第九步：Docker Compose 层怎么设计

建议未来新增：

```text
docker-compose.yml
```

推荐结构：

1. `freight-agent-app`
2. `freight-agent-nginx`

应用容器：

- 从 `Dockerfile` 构建
- 读取 `.env.production`
- 挂载知识库目录
- 挂载日志目录

Nginx 容器：

- 挂载 `default.conf`
- 对外暴露 `80:80`
- 依赖应用容器

---

## 18. 第十步：部署成功后应该是什么样

最终你会在服务器上形成两类东西。

### 18.1 代码与部署目录

```text
/data/apps/freight-agent
/data/docker/freight-agent
```

### 18.2 日志与运行数据

```text
/data/logs/freight-agent
/data/apps/freight-agent/data/docs
/data/apps/freight-agent/data/chroma
/data/apps/freight-agent/data/cache
```

---

## 19. 第十一步：实际启动顺序

未来真正部署时，顺序应该是：

1. 准备 Dockerfile
2. 准备 docker-compose.yml
3. 准备 nginx 配置
4. 准备 `.env.production`
5. 在服务器执行：

```bash
cd /data/docker/freight-agent
docker compose up -d --build
```

6. 查看状态：

```bash
docker compose ps
docker compose logs -f
```

7. 验证：

```bash
curl http://127.0.0.1/health
curl http://47.101.141.117/health
```

---

## 20. 第十二步：日志怎么接

由于当前项目已经支持：

- `freight-agent-app.log`
- `freight-agent-app.jsonl`
- `freight-agent-error.log`

所以容器部署时，核心目标是把容器内日志目录挂载到宿主机：

```text
/data/logs/freight-agent
```

这样你后续的前端日志平台仍然可以直接消费宿主机文件。

---

## 21. 第十三步：当前阶段需要你理解的一点

这次文档写的是“部署架构教程”和“初始化脚本”，不是说项目现在已经可以直接 `docker compose up`。

因为当前仓库还没有这些关键文件：

1. `Dockerfile`
2. `.dockerignore`
3. `docker-compose.yml`
4. `Nginx` 配置文件

所以这次输出的价值是：

1. 先把服务器和目录规划好
2. 先把 Docker 环境准备好
3. 先把整体部署形态定下来
4. 后面再正式补容器化文件

---

## 22. 最短执行清单

如果你只想先把服务器准备好，最短路径是：

1. 用 MobaXterm SSH 登录 `47.101.141.117`
2. 更新系统
3. 挂载数据盘到 `/data`
4. 安装 Docker 和 Compose
5. 创建 `/data/apps/freight-agent`
6. 创建 `/data/logs/freight-agent`
7. 上传项目代码
8. 上传部署层配置
9. 等项目补齐容器化文件后再执行 `docker compose up -d --build`

---

## 23. 这次部署文档对应的项目改动清单

后续我真正开始实现 Docker Compose 架构时，预计会新增或修改这些文件：

### 新增

1. `Dockerfile`
2. `.dockerignore`
3. `docker-compose.yml`
4. `deploy/nginx/default.conf`
5. `deploy/.env.production.example`

### 可能修改

1. `README.md`
2. `docs/deploy/...`
3. 日志目录说明
4. 启动说明

如果后面你让我继续实现，我会严格控制改动面，不会去顺手重构主业务链路。  
