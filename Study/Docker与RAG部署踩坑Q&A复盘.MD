# Docker 与 RAG 部署踩坑 Q&A 复盘

## 1. 文档目的

这份文档不是重新讲一遍部署流程，而是把最近在 **Docker 部署** 和 **RAG 重建** 过程中真实遇到的问题，提炼成一组可反复查看的 Q&A。

目标有两个：

1. 帮你快速复盘这次上线到底踩了哪些坑
2. 以后再部署、再扩知识库、再换服务器时，能直接拿来排查

本文主要基于这些材料归纳：

- [docker-compose构建成功之后要做的事情.md](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\Study\docker-compose构建成功之后要做的事情.md)
- [RAG重建与域名接入说明.md](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\Study\RAG重建与域名接入说明.md)
- [RAG本地与服务器执行差异说明.MD](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\Study\RAG本地与服务器执行差异说明.MD)
- [本地迭代、GitHub与服务器协作说明.md](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\Study\本地迭代、GitHub与服务器协作说明.md)
- [服务器更新与手动同步清单.MD](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\Study\服务器更新与手动同步清单.MD)

---

## 2. 总结先说

这次 Docker 和 RAG 部署里，真正暴露出来的问题，不是“命令不会敲”，而是这 5 类工程认知没有一开始彻底想清楚：

1. 宿主机代码和容器代码不是一回事
2. 本地 Python 环境和 Docker 容器环境不是一回事
3. Docker 挂载目录不是普通目录
4. RAG 重建不只是“跑脚本”，还依赖底层 SQLite、向量库、Embedding 接法
5. “能启动容器”不等于“RAG 能构建”、也不等于“线上链路全通”

所以后面你只要记住一句话：

> 这类问题优先按“运行环境、挂载方式、镜像版本、依赖版本、模型接法”五层去排，而不是先猜代码逻辑。

---

## 3. Q&A 复盘

## Q1：为什么 `git pull origin main` 之后，服务器代码明明是新的，但容器里还是旧代码？

### 现象

服务器宿主机里：

```bash
grep -n "rmtree(chroma_dir)" rag/indexer.py
```

没有输出，说明宿主机代码已经更新。

但容器里：

```bash
docker compose exec freight-agent-app grep -n "rmtree(chroma_dir)" /app/rag/indexer.py
```

还能看到旧代码。

### 根因

因为当前应用容器的代码不是“运行时挂载进去”的，而是构建镜像时通过：

```dockerfile
COPY . /app
```

打进镜像里的。

这意味着：

- `git pull` 更新的是宿主机项目目录
- **不会自动更新已经在跑的容器内部代码**
- 只有重新构建镜像并重建容器，容器内代码才会更新

### 正确解决

```bash
cd /data/apps/freight-agent
git pull origin main
docker compose build --no-cache freight-agent-app
docker compose up -d --force-recreate
```

### 后续建议

以后凡是你改了：

- Python 源码
- `requirements.txt`
- `Dockerfile`

都不要只做 `git pull`，而要默认接着做：

```bash
docker compose build --no-cache freight-agent-app
docker compose up -d --force-recreate
```

---

## Q2：为什么 `docker compose exec freight-agent-app python -m scripts.rebuild_kb` 最早会报 `Device or resource busy: data/chroma`？

### 现象

你在容器内执行：

```bash
docker compose exec freight-agent-app python -m scripts.rebuild_kb
```

报错：

```text
OSError: [Errno 16] Device or resource busy: 'data/chroma'
```

### 根因

不是权限问题，也不是命令写错，而是当前实现和 Docker 挂载方式冲突。

当时 `rebuild_knowledge_base()` 里是：

```python
shutil.rmtree(chroma_dir)
```

而当前 Compose 里挂载的是：

```text
./data/chroma:/app/data/chroma
```

所以容器里的 `/app/data/chroma` 是一个 **bind mount 挂载点**。

在 Linux 里：

- 普通目录可以 `rmtree`
- 挂载点目录本身不能直接删

所以会报：

```text
Device or resource busy
```

### 正确解决

长期方案就是现在已经改过的 Docker 友好版本：

- 保留 `data/chroma` 根目录
- 只清空它内部内容
- 再重建索引

### 后续建议

以后只要看到：

- `Device or resource busy`
- 某个路径又正好是 Compose 挂载目录

优先怀疑：

> 代码在删除挂载点本身，而不是删除挂载点内容

---

## Q3：为什么最早 `init_kb` 又会报 `sqlite3` 版本不支持？

### 现象

你在容器里执行：

```bash
docker compose exec freight-agent-app python -m scripts.init_kb
```

报错：

```text
RuntimeError: Your system has an unsupported version of sqlite3.
Chroma requires sqlite3 >= 3.35.0.
```

当时容器里实际版本是：

```bash
docker compose exec freight-agent-app python -c "import sqlite3; print(sqlite3.sqlite_version)"
```

结果：

```text
3.34.1
```

### 根因

根因不是 Chroma 配置错，而是 **Docker 基础镜像太旧**，导致容器里的 Python 绑定了低版本 sqlite。

也就是说：

- 代码没问题
- RAG 逻辑没问题
- 但运行时底层依赖不满足 Chroma 最低要求

### 正确解决

升级 Docker 基础镜像，随后无缓存重建镜像。

实际修复后，容器里 sqlite 版本变成了：

```text
3.40.1
```

### 后续建议

以后凡是这类错误：

```text
unsupported version of sqlite3
```

优先排查的是：

1. Docker 基础镜像
2. 容器内 Python 版本
3. 容器内 sqlite 版本

而不是先怀疑 RAG 代码本身。

---

## Q4：为什么修完 SQLite、修完挂载目录问题之后，`rebuild_kb` 还是报模型不支持？

### 现象

执行：

```bash
docker compose exec freight-agent-app python -m scripts.rebuild_kb
```

报错：

```text
Unsupported model `qwen3-vl-embedding` for OpenAI compatibility mode.
```

### 根因

这说明当时问题已经不在：

- Docker
- SQLite
- Chroma
- 挂载目录

而是在 **Embedding 模型调用方式不匹配**。

当时代码是：

- 用 `openai.OpenAI(...)`
- `base_url=https://dashscope.aliyuncs.com/compatible-mode/v1`
- 调 `client.embeddings.create(...)`

这条链路的含义是：

> 走的是 DashScope 的 OpenAI compatible mode

但你要用的模型是：

```text
qwen3-vl-embedding
```

线上真实结果已经证明：

> 它不支持当前这条 compatible mode 调法

### 正确解决

最终采用的长期方案是：

- 不再走 OpenAI compatible mode
- 改成 DashScope 原生 SDK 调用方式
- 多模态 embedding 走 `dashscope.MultiModalEmbedding.call(...)`

### 后续建议

以后遇到“模型存在，但接口说不支持”的问题，先问自己这三个问题：

1. 我现在用的是原生 SDK 还是兼容模式？
2. 这个模型是文本模型还是多模态模型？
3. 当前接口到底支不支持这个模型，而不是这个模型支不支持平台？

很多时候问题不是模型不能用，而是：

> 模型和当前接入方式不匹配

---

## Q5：既然本地之前 `qwen3-vl-embedding` 能用，为什么服务器上不行？

### 现象

你之前的认知是：

- 本地 `qwen3-vl-embedding` 能用
- 服务器上不行

### 根因

差异不在“本地”和“服务器”这四个字本身，而在 **接入实现变了**。

真正变化的是：

- 之前某个版本本地可能走的是 DashScope 原生调用
- 后来代码切成了 OpenAI compatible mode
- 于是 `qwen3-vl-embedding` 在线上就不再兼容

### 正确理解

不是：

> 本地能用，服务器不能用

而是：

> 原生调用能用，compatible mode 不能用

### 后续建议

以后排查“本地可用、线上不可用”时，先不要只看平台差异，要先查：

1. 本地和线上代码是不是同一版
2. 本地和线上依赖是不是同一版
3. 本地和线上 `.env` 是否一致
4. 本地和线上走的 API 接法是否一致

---

## Q6：为什么 `docker compose up -d --build` 成功，不代表 RAG 也一定已经能用了？

### 现象

你已经看到：

- `freight-agent-app` healthy
- `freight-agent-nginx` started / healthy
- 公网 IP 可访问

这说明服务层已经起来了。

### 根因

但这只代表：

1. Docker Compose 编排没问题
2. Nginx 转发没问题
3. 应用健康检查没问题

不代表：

1. 知识库已经构建
2. 向量库已经就绪
3. embedding 接入没问题
4. RAG 检索链路已经可用

也就是说：

> “服务可访问”和“RAG 可用”是两层不同状态

### 正确做法

Docker 启动成功后，还要继续做：

1. 容器状态检查
2. `/health` 检查
3. RAG 重建
4. RAG 问答联调
5. 日志检查

### 后续建议

以后把上线验证分成三层，不要混着看：

1. **容器层**：容器能不能起来
2. **服务层**：HTTP 接口能不能访问
3. **业务层**：RAG / 询价链路能不能真正工作

---

## Q7：为什么我不应该默认每次部署都重建 RAG？

### 现象

一开始很容易形成一个直觉：

> 每次 `docker compose up -d --build` 之后，都顺手重建一次知识库

### 根因

这样做并不总是必要，因为：

- 代码更新 != 知识库资料变化
- Prompt 调整 != 索引必须重建
- 前端更新 != 索引必须重建

如果每次部署都重建：

- 浪费时间
- 增加出错面
- 增加外部 embedding 调用成本

### 正确做法

只有下面几类变化，才建议重建 RAG：

1. `data/docs` 资料变了
2. `rag/metadata.py` 变了
3. `splitter` 规则变了
4. embedding 模型变了
5. 向量库结构变了

### 后续建议

以后把“部署”和“RAG 重建”看成两个动作：

- 普通代码部署：`git pull` + `docker compose up -d --build`
- 知识库变更部署：上面步骤 + `python -m scripts.rebuild_kb`

---

## Q8：为什么不推荐在宿主机直接裸跑 `python scripts/rebuild_kb.py`？

### 现象

直觉上会觉得：

```bash
python scripts/rebuild_kb.py
```

是不是更简单。

### 根因

但当前线上真实运行环境已经是 Docker 容器：

- Python 版本在容器里
- 项目依赖在容器里
- `.env.production` 在容器里生效
- Chroma/BM25 挂载路径也是围绕容器构建的

宿主机未必具备：

- 同版本 Python
- 同版本依赖
- 同样的环境变量

### 正确做法

优先使用：

```bash
docker compose exec freight-agent-app python -m scripts.rebuild_kb
```

这样更接近线上真实运行环境。

### 后续建议

以后凡是这种“属于应用内部逻辑，但要在线上手工执行一次”的命令，优先放在容器里执行，而不是宿主机裸跑。

---

## Q9：为什么 Docker 和日志没有冲突，日志还能稳定落宿主机？

### 现象

上线后很容易担心：

> 容器重建了，日志会不会丢？

### 根因

当前不是把日志写在容器内部孤立文件系统里，而是做了宿主机挂载。

也就是：

- 容器内写日志
- 实际落在宿主机日志目录

所以：

- 容器删了，日志还在
- 容器重建了，日志仍然写到原目录

### 正确理解

Docker 本身不会天然丢日志，真正关键是：

> 日志有没有做宿主机持久化挂载

### 后续建议

以后排查“日志为什么没看到”时，优先看：

1. `APP_LOG_DIR` 容器内路径
2. Compose 挂载路径
3. 宿主机目标目录是否存在

---

## Q10：为什么我后来越来越需要把部署问题和代码问题拆开看？

### 现象

这次问题链条里，你先后遇到了：

1. 容器代码没更新
2. SQLite 版本低
3. 删除挂载目录报错
4. embedding 模型 compatible mode 不支持

如果把这些都统称成“RAG 出问题”，会很乱。

### 根因

因为它们实际上分属四层：

1. **镜像层**：Docker 基础镜像版本
2. **挂载层**：目录是不是 bind mount
3. **依赖层**：sqlite / chromadb / dashscope
4. **业务接入层**：embedding 模型调用方式

### 正确做法

以后排这类问题，建议按下面顺序查：

1. 宿主机代码是否更新
2. 容器代码是否更新
3. 容器内 Python/依赖版本是否满足
4. 挂载目录是否参与清理逻辑
5. 模型和 SDK 接法是否匹配

### 后续建议

这会比“先去改 Python 代码”更省时间，也更不容易误判。

---

## 4. 最终沉淀下来的几条长期规则

## 规则 1：服务器代码更新不等于容器代码更新

以后凡是改了后端代码，都默认做：

```bash
git pull origin main
docker compose build --no-cache freight-agent-app
docker compose up -d --force-recreate
```

---

## 规则 2：挂载目录不能按普通目录对待

凡是 Compose 挂载目录：

- 不要默认 `rmtree` 根目录
- 优先清空目录内容

---

## 规则 3：RAG 问题先拆环境，再拆代码

RAG 一旦出问题，优先排查顺序：

1. Python 版本
2. sqlite 版本
3. 依赖包版本
4. 容器内代码版本
5. Embedding 模型接法

---

## 规则 4：本地能用，不代表 compatible mode 也能用

尤其是：

- 多模态模型
- 视觉 embedding
- 平台专属模型

不要默认它们能走 OpenAI compatible mode。

---

## 规则 5：Docker 成功启动只是中间里程碑，不是最终成功

真正的最终成功至少要满足：

1. Compose 正常
2. Nginx 正常
3. `/health` 正常
4. `/api/chat` 正常
5. RAG 能重建
6. RAG 实际问答能命中
7. 日志能落盘

---

## 5. 一句话复盘

这次 Docker 和 RAG 部署中最大的收获，不是“又解决了几个 bug”，而是你已经把这套系统的运行边界摸清楚了：

- **代码在哪一层生效**
- **依赖在哪一层生效**
- **挂载目录能不能删**
- **RAG 问题是环境问题还是接入问题**
- **Docker 成功和业务成功不是同一件事**

这套认知比单独记住某个命令更重要。  
因为以后你换域名、换服务器、扩文档、再做 CI/CD，这些判断还会继续用上。
