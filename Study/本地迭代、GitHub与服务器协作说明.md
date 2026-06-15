# 本地迭代、GitHub 与服务器协作说明

## 1. 目标

本文用于说明后续项目进入持续迭代后，`本地开发环境`、`GitHub 仓库`、`云服务器` 三者之间应该如何分工，避免代码冲突、环境混乱、日志丢失和 Docker 运行状态不可控。

当前默认前提：

- 服务器项目目录：`/data/apps/freight-agent`
- 外部访问入口：`Nginx -> Docker Compose -> freight-agent-app`
- 宿主机日志目录目标：`/data/logs/freight-agent`

---

## 2. 三者关系

可以把这套协作关系理解成下面这条链路：

```text
本地开发 -> 提交到 GitHub -> 服务器拉取代码 -> Docker 重建并启动 -> Nginx 对外提供访问
```

三者职责建议固定为：

### 2.1 本地

本地只负责：

- 写代码
- 调试功能
- 验证改动
- 提交 Git
- 推送 GitHub

本地不应该承担：

- 作为线上运行环境
- 保存生产密钥
- 直接成为服务器运行态的真实来源

### 2.2 GitHub

GitHub 是这套项目的`唯一代码真源`，用于保存：

- 业务代码
- Docker 部署文件
- Nginx 配置
- 文档
- 非敏感配置模板

GitHub 不应该保存：

- 生产密钥
- 服务器私有环境变量
- 运行日志
- Chroma 索引
- 缓存
- 临时导出文件

### 2.3 云服务器

服务器只负责：

- 拉取 GitHub 最新代码
- 保留生产环境专属配置
- 运行 Docker 容器
- 持久化运行数据和日志
- 对外提供访问

服务器上不建议长期做的事：

- 直接改业务代码
- 在服务器上手工维护一份“只在线上存在”的代码分叉
- 把线上调试改动长期留在未提交状态

---

## 3. 推荐协作原则

为了避免冲突，建议长期遵守下面几条规则。

### 3.1 代码只在本地改

推荐方式：

1. 本地开发和测试
2. 本地提交 Git
3. 推送到 GitHub
4. 服务器执行 `git pull`
5. 服务器执行 `docker compose up -d --build`

不推荐方式：

- 在服务器里直接改 Python 源码
- 改完服务器代码却不回写本地和 GitHub

原因很直接：一旦服务器代码被手改，下一次 `git pull` 时就很容易出现：

- 合并冲突
- 本地和线上代码不一致
- 排障时不知道当前线上到底跑的是哪一版

### 3.2 生产配置只在服务器放

像这些文件和数据，应该只在服务器放真实值：

- `deploy/.env.production`
- 证书文件
- 服务器专属路径配置
- 生产日志

这些内容不要进入 GitHub。

如果某个敏感文件已经被 Git 跟踪过，仅靠 `.gitignore` 不够，需要后续把它从 Git 索引中移除，再保留服务器本地版本。

### 3.3 运行数据和代码分离

代码应该跟着 GitHub 走，运行数据应该跟着宿主机挂载走。

典型运行数据包括：

- `/data/logs/freight-agent`
- `/data/apps/freight-agent/data/chroma`
- `/data/apps/freight-agent/data/cache`
- `/data/apps/freight-agent/data/exports`

这样即使容器重建，这些数据也不会因为容器销毁而丢失。

---

## 4. 后续标准更新流程

后续每次本地完成一个版本，推荐按下面顺序更新。

### 第 1 步：本地完成开发

本地完成：

- 功能开发
- 本地测试
- 文档更新
- Docker 文件变更检查

### 第 2 步：提交并推送 GitHub

示例流程：

```bash
git add .
git commit -m "feat: xxx"
git push origin main
```

如果后续你采用分支策略，也可以用：

- `main`：稳定版本
- `dev`：开发版本

但如果目前是你个人维护为主，先保持单主分支也可以。

### 第 3 步：服务器拉取最新代码

在服务器中：

```bash
cd /data/apps/freight-agent
git pull origin main
```

### 第 4 步：确认生产专属文件还在

重点确认这些内容没有被覆盖：

- `deploy/.env.production`
- `deploy/nginx/default.conf`
- `/data/logs/freight-agent`
- `data/chroma`
- `data/cache`
- `data/exports`

### 第 5 步：重建并启动容器

由于当前应用代码是打包进镜像的，不是通过源码目录挂载进容器，所以每次代码更新后都应该执行：

```bash
docker compose up -d --build
```

这一步的含义是：

- 重新构建应用镜像
- 用新镜像替换旧容器
- 保留挂载的数据目录

### 第 6 步：验证服务是否正常

建议至少执行：

```bash
docker compose ps
docker compose logs --tail=100 freight-agent-app
curl http://127.0.0.1/health
```

如果服务器已经通过 Nginx 对外提供访问，也可以再验证：

```bash
curl http://你的域名/health
```

---

## 5. 为什么一般不会起冲突

只要你遵守下面这条边界，三者之间通常不会乱：

`代码走 GitHub，配置留服务器，运行数据走挂载目录。`

这样三类东西是分开的：

### 5.1 Git 管理的是代码和部署模板

例如：

- `main.py`
- `graph/`
- `rag/`
- `Dockerfile`
- `docker-compose.yml`
- `deploy/nginx/default.conf`

### 5.2 服务器自己保留的是生产配置

例如：

- `deploy/.env.production`
- SSL 证书
- 服务器域名相关配置

### 5.3 Docker 宿主机挂载保留的是运行数据

例如：

- 日志
- Chroma
- 缓存
- 导出文件

只要服务器不要直接改 Git 跟踪的源码文件，后续 `git pull` 基本就不会出现代码冲突。

真正容易冲突的场景只有两个：

1. 你在服务器直接改了被 Git 跟踪的文件
2. 你把生产专属文件误提交进了 GitHub

---

## 6. Docker 在服务器上的角色

这套部署里，Docker 主要承担三件事：

### 6.1 固定运行环境

应用容器里始终使用一致的：

- Python 版本
- 依赖版本
- 启动命令

这样本地和服务器的差异会小很多。

### 6.2 固定服务编排

当前 Compose 架构里有两个主要服务：

- `freight-agent-app`
- `freight-agent-nginx`

职责分离后：

- 应用容器只负责运行 FastAPI + Agent
- Nginx 容器只负责反向代理和对外暴露 80 端口

### 6.3 固定启动方式

后续服务器上的标准动作会比较统一：

```bash
cd /data/apps/freight-agent
docker compose up -d --build
docker compose ps
docker compose logs -f --tail=100
```

也就是说，以后更新项目时，你不再需要手工再去执行：

- `pip install`
- 手工跑 `uvicorn`
- 手工维护后台进程

这些动作都交给 Docker 来接管。

---

## 7. Docker 对日志有没有影响

有影响，但影响是可控的。

需要区分两层：

### 7.1 容器日志

这是 `docker compose logs` 看到的内容。

它适合：

- 临时排查
- 看容器启动失败
- 看最近一段输出

但它不应该作为你后续日志平台的主数据源。

### 7.2 应用结构化日志

这是项目自己的日志系统输出的：

- `freight-agent-app.log`
- `freight-agent-app.jsonl`
- `freight-agent-error.log`

这三类日志才应该作为你后续：

- 前端日志平台
- 每日汇总
- AI 分析
- 异常聚类

的主数据来源。

---

## 8. 日志是否会每天存到 `/data/logs/freight-agent`

目标上应该是`会`，但基于当前文件，我要把一个重要事实说清楚：

### 8.1 你当前的目标是对的

你想要的最终状态应该是：

- 宿主机目录：`/data/logs/freight-agent`
- Docker 容器里应用把日志写到挂载目录
- 每天自动滚动归档
- 前端平台以后从宿主机日志目录读取或加工

这个方向完全正确。

### 8.2 但当前 Compose 和环境变量存在一个路径不一致风险

当前文件里有两处配置：

1. `docker-compose.yml` 里挂载的是：

```text
/data/logs/freight-agent:/app/runtime/logs
```

2. `deploy/.env.production` 里配置的是：

```text
APP_LOG_DIR=/data/logs/freight-agent
```

这意味着：

- 宿主机真正挂进容器的是 `/app/runtime/logs`
- 但应用当前被要求写到 `/data/logs/freight-agent`

如果不统一，日志有可能写进容器内部目录，而不是你期望的宿主机挂载目录。

### 8.3 推荐统一方式

推荐采用下面这组更一致的配置：

#### 方式 A，优先推荐

- `docker-compose.yml` 保持：

```text
/data/logs/freight-agent:/app/runtime/logs
```

- `deploy/.env.production` 改成：

```text
APP_LOG_DIR=/app/runtime/logs
```

这样最清晰：

- 容器内应用写 `/app/runtime/logs`
- 宿主机真实落盘到 `/data/logs/freight-agent`

#### 方式 B，也可以

把挂载改成：

```text
/data/logs/freight-agent:/data/logs/freight-agent
```

这样容器内外路径完全一致。

但从容器隔离视角看，我更推荐方式 A。

### 8.4 如何验证日志是否真的落到宿主机

服务器上可以执行：

```bash
ls -lah /data/logs/freight-agent
docker compose exec freight-agent-app sh -c "echo $APP_LOG_DIR"
```

然后确认：

1. 宿主机目录里有日志文件
2. 容器内 `APP_LOG_DIR` 指向的是挂载路径

---

## 9. 后续服务器常用命令

### 9.1 更新代码并重启

```bash
cd /data/apps/freight-agent
git pull origin main
docker compose up -d --build
```

### 9.2 查看容器状态

```bash
docker compose ps
```

### 9.3 查看应用日志

```bash
docker compose logs -f --tail=100 freight-agent-app
```

### 9.4 查看 Nginx 日志

```bash
docker compose logs -f --tail=100 freight-agent-nginx
```

### 9.5 查看宿主机落盘日志

```bash
ls -lah /data/logs/freight-agent
tail -n 100 /data/logs/freight-agent/freight-agent-app.log
```

---

## 10. 建议的长期工作方式

如果后续你长期维护这个项目，我建议固定成下面这套节奏：

### 日常开发

在本地开发、测试、提交、推送。

### 日常部署

在服务器上只做：

1. `git pull`
2. `docker compose up -d --build`
3. 健康检查
4. 日志检查

### 线上修复原则

如果线上必须热修：

1. 可以临时在服务器排查
2. 但不要让“只在服务器存在的改动”长期保留
3. 真正修复必须回到本地
4. 本地修好后重新提交 GitHub
5. 再由服务器重新拉取并部署

---

## 11. 结论

后续最稳的协作关系就是：

- 本地负责开发和验证
- GitHub 负责保存代码真源
- 服务器负责保存生产配置和运行数据
- Docker 负责固定运行环境和启动方式

只要你不在服务器上直接改 Git 跟踪源码，这套模式通常不会起冲突。

但有一个当前必须注意的点：

`日志目录的容器内路径和宿主机挂载路径需要统一。`

这个点如果不先校正，Docker 运行后日志未必会稳定落到你想要的 `/data/logs/freight-agent`。
