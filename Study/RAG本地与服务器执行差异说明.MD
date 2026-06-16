# RAG 本地与服务器执行差异说明

## 1. 先说结论

你刚才问的核心其实有三个：

1. 我更推荐哪个方案，长远怎么做
2. 把 `rag/indexer.py` 改成 Docker 友好版本后，本地和服务器会不会有区别
3. 本地和服务器的 RAG 构建命令、项目启动方式，到底是不是同一套

先给结论：

### 1.1 长远推荐方案

**长远我更推荐：改代码，让 `rebuild_kb` 变成 Docker 友好版本。**

也就是：

- 不再删除挂载目录本身
- 只清空挂载目录里的内容
- 然后重建索引

这是工程上最正确、最可持续的做法。

### 1.2 眼下最稳妥的落地方式

在代码还没改之前，服务器端最稳的是：

- 先手动清空旧索引内容
- 再执行 `init_kb`

这是临时运维绕过方案，不是长期标准方案。

### 1.3 本地和服务器最大的区别

**区别不在“有没有 `scripts/rebuild_kb.py`”，而在运行环境不同。**

- 本地：大概率是裸 Python 环境，或者本地手工运行
- 服务器：现在是 Docker 容器 + 挂载目录 + Nginx 架构

所以：

- 同样一段 Python 代码
- 在本地可能能删目录
- 在服务器 Docker 挂载场景下就可能删不了

这就是这次报错的本质。

---

## 2. 为什么我长远更推荐改 `rag/indexer.py`

原因很直接：你现在这个项目已经不是“本地实验项目”了，而是已经进入正式部署态。

当前 `rebuild_knowledge_base()` 的实现是：

```python
if chroma_dir.exists():
    shutil.rmtree(chroma_dir)
```

这在“普通本地目录”场景里通常没问题，但在 Docker 场景里有明显问题：

### 2.1 Docker 挂载目录不是普通目录

你当前 Compose 有这个挂载：

```text
./data/chroma:/app/data/chroma
```

这意味着：

- 容器里的 `/app/data/chroma`
- 实际是宿主机 bind mount 进来的挂载点

Linux 对挂载点目录本身不允许像普通目录那样直接删掉，所以 `rmtree` 会报：

```text
Device or resource busy
```

### 2.2 这是结构性问题，不是偶发问题

它不是：

- 网络抖动
- 权限偶发
- 命令写错

而是当前实现策略和 Docker 挂载模型天然冲突。

所以这个问题如果不从代码层修掉，以后你每次线上重建知识库都得绕一次。

### 2.3 改代码后能统一本地和服务器心智模型

如果把 `rebuild_kb` 改成：

- 保留目录
- 删除目录内容
- 再重建

那么以后你就可以统一理解成：

`rebuild_kb` = 正常的全量重建命令

而不是：

- 本地能用
- 服务器不能直接用

这对长期运维是非常重要的。

---

## 3. 眼下为什么还推荐临时运维方案

虽然长期应该改代码，但你现在项目已经在服务器上跑起来了，当前最实际的目标是：

`先把线上 RAG 跑通。`

所以在代码还没改之前，最快恢复方案是：

1. 停应用容器
2. 手动清空旧索引内容
3. 用 `init_kb` 重新构建
4. 再启动应用

这种方式的优点是：

- 不用马上改代码
- 风险最小
- 能快速验证线上知识库是否可用

缺点是：

- 以后每次重建都得记住这套特殊动作
- 不是优雅的最终方案

所以它适合作为当前阶段的“临时实用方案”，不适合作为长期规范。

---

## 4. 本地和服务器的本质区别是什么

这部分你一定要想清楚。

## 4.1 本地环境

本地通常是：

- 你自己的 Python 环境
- 你的本地目录结构
- 你的本地依赖
- 你的本地 `.env`

在这种情况下：

- `python scripts/rebuild_kb.py`
- `python -m scripts.rebuild_kb`

常常就是直接对你本地磁盘目录操作。

如果 `data/chroma` 只是普通目录，`shutil.rmtree()` 大概率能正常删。

## 4.2 服务器环境

你现在服务器不是裸跑 Python，而是：

- Docker 容器运行应用
- 宿主机目录挂载进容器
- Nginx 作为统一入口

所以服务器现在真正的 RAG 运行环境是：

- 容器内 Python
- 容器内依赖
- 容器内环境变量
- 容器内挂载目录视图

这和本地“裸目录直删”的语义不完全一样。

## 4.3 问题不是“脚本不同”，而是“目录语义不同”

同样是：

```python
shutil.rmtree("./data/chroma")
```

在不同环境里含义不一样：

- 本地普通目录：删除一个普通目录
- Docker 挂载目录：试图删除一个挂载点

这就是为什么本地可能没问题，服务器会报错。

---

## 5. 本地和服务器的 RAG 构建指令是不是不同

结论是：

**从“意图层面”看，它们应该尽量一样。**

也就是：

- 初始化：`init_kb`
- 全量重建：`rebuild_kb`

这个语义不应该变。

但从“执行方式”看，当前它们暂时不完全一样。

---

## 6. 当前阶段推荐的命令区别

### 6.1 本地推荐

如果你本地是裸 Python 跑项目，当前可以用：

```bash
python -m scripts.init_kb
python -m scripts.rebuild_kb
```

或者：

```bash
python scripts/init_kb.py
python scripts/rebuild_kb.py
```

但更推荐 `-m` 方式，因为导入路径更稳。

### 6.2 服务器推荐

当前服务器推荐的是容器内执行：

初始化：

```bash
docker compose exec freight-agent-app python -m scripts.init_kb
```

重建：

```bash
docker compose exec freight-agent-app python -m scripts.rebuild_kb
```

但由于当前 `rebuild_kb` 还不是 Docker 友好版本，所以眼下真正可执行的是：

```bash
docker compose stop freight-agent-app
rm -rf data/chroma/*
rm -f data/cache/bm25.pkl
rm -f data/exports/chunks.json
docker compose run --rm freight-agent-app python -m scripts.init_kb
docker compose up -d freight-agent-app
```

也就是说：

- **长期目标**：本地和服务器都能直接用 `rebuild_kb`
- **当前现实**：服务器先用临时绕过方案

---

## 7. 改成 Docker 友好版本后，本地和服务器会有什么区别

如果后续我把 `rag/indexer.py` 改成 Docker 友好版本，差异会明显缩小。

### 7.1 不会改变“功能语义”

改完之后：

- `build_knowledge_base()` 仍然是初始化
- `rebuild_knowledge_base()` 仍然是全量重建

也就是说，命令的业务含义不会变。

### 7.2 会改变“底层清理方式”

当前是：

- 删除整个目录

改完后会变成：

- 保留目录本身
- 只删目录内容

这个变化对本地和服务器的影响是：

- 本地仍然能正常用
- 服务器 Docker 挂载场景也能正常用

### 7.3 会统一你的操作心智

改完后你可以长期统一理解：

- 本地重建：`python -m scripts.rebuild_kb`
- 服务器重建：`docker compose exec freight-agent-app python -m scripts.rebuild_kb`

区别只在：

- 本地是本地 Python
- 服务器是容器 Python

而不是：

- 本地能 rebuild
- 服务器要停容器、删目录、再 init

这就是为什么我说长远更推荐改代码。

---

## 8. 本地和服务器项目启动有没有区别

有，而且这个区别是正常的。

## 8.1 本地启动

本地你通常是：

```bash
uvicorn main:app --host 0.0.0.0 --port 8012 --reload
```

特点是：

- 调试方便
- 热更新方便
- 适合开发

## 8.2 服务器启动

服务器现在是：

```bash
docker compose up -d --build
```

特点是：

- 统一依赖环境
- 统一端口和 Nginx 代理
- 统一日志挂载
- 适合正式运行

## 8.3 启动方式不同，但应用语义应该尽量一样

你要追求的是：

- 本地是开发形态
- 服务器是部署形态

但：

- 接口行为要一样
- RAG 构建语义要一样
- 日志行为尽量一致

这才是成熟工程的做法。

---

## 9. 我对这件事的最终推荐

我给你一个明确排序。

### 第一推荐：长期方案

**修改 `rag/indexer.py`，把 `rebuild_kb` 改成 Docker 友好版本。**

这样收益最大：

- 本地和服务器语义统一
- 后续运维最省心
- 不需要每次都手动绕

### 第二推荐：当前临时方案

在代码还没改前，服务器端先这样做：

```bash
docker compose stop freight-agent-app
rm -rf data/chroma/*
rm -f data/cache/bm25.pkl
rm -f data/exports/chunks.json
docker compose run --rm freight-agent-app python -m scripts.init_kb
docker compose up -d freight-agent-app
```

### 第三推荐：不建议继续的方案

不建议继续反复直接跑：

```bash
docker compose exec freight-agent-app python -m scripts.rebuild_kb
```

因为当前实现下，它在 Docker 挂载场景里就是不稳定的。

---

## 10. 最终结论

一句话总结：

**长远我更推荐改代码；当前我更推荐先用临时运维方案把线上 RAG 跑通。**

本地和服务器真正的区别不是“脚本名字不同”，而是：

- 本地更像裸 Python 目录环境
- 服务器是 Docker 挂载运行环境

改成 Docker 友好版本之后：

- 本地依然可以继续用 `rebuild_kb`
- 服务器也可以正常用 `rebuild_kb`
- 只是执行入口不同：
  - 本地：`python -m scripts.rebuild_kb`
  - 服务器：`docker compose exec freight-agent-app python -m scripts.rebuild_kb`

这才是长期最干净的状态。
