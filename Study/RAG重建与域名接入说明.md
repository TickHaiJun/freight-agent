# RAG 重建与域名接入说明

## 1. 当前整体状态判断

基于你现在给出的服务器状态：

```text
freight-agent-app     Up ... (healthy)
freight-agent-nginx   Up ... (healthy)
0.0.0.0:80->80/tcp
```

说明当前项目已经基本进入最后收尾阶段了。

这意味着：

1. Docker Compose 编排已经正常
2. 应用容器已经健康
3. Nginx 容器已经健康
4. 公网 `80` 端口已经对外暴露
5. 你已经可以先通过公网 IP 访问服务

所以现在剩下的关键动作，主要就是：

1. 完成服务器端 RAG 知识库重建
2. 做一轮 RAG 问答验证
3. 后续如果有真实域名，再补域名解析和 HTTPS

---

## 2. 服务器端 RAG 最后一步应该怎么做

你刚才问的是：

```text
在服务器项目目录下执行 python scripts/rebuild_kb.py 就可以了吗？
```

我的建议是：

**不建议优先在宿主机直接裸跑这个命令。**

更稳妥的方式是：

```bash
cd /data/apps/freight-agent
docker compose exec freight-agent-app python -m scripts.rebuild_kb
```

---

## 3. 为什么更推荐在容器里执行

原因有三个。

### 3.1 当前项目真实运行环境在容器里

你线上真正跑起来的依赖、Python 版本、环境变量，都是在 `freight-agent-app` 容器里。

所以知识库重建最好也在同一个环境里做，这样最一致。

### 3.2 宿主机不一定有完整 Python 依赖

如果你在宿主机直接执行：

```bash
python scripts/rebuild_kb.py
```

可能遇到这些问题：

- 宿主机没装项目依赖
- 宿主机 Python 版本不同
- 宿主机环境变量不完整
- 宿主机模块导入路径不一致

也就是说，宿主机“能 SSH 登录”不等于“能裸跑项目 Python 脚本”。

### 3.3 容器里已经有正确的目录挂载

当前 Compose 已经把这些目录挂载进容器：

- `./data/docs:/app/data/docs`
- `./data/chroma:/app/data/chroma`
- `./data/cache:/app/data/cache`
- `./data/exports:/app/data/exports`

而你的生产环境变量里也已经对应配置了：

- `CHROMA_PERSIST_DIR=./data/chroma`
- `RAG_DOCS_DIR=./data/docs`

这意味着：

容器里执行重建，最终写入的索引和缓存，会真实落到宿主机项目目录下，不会丢。

---

## 4. 正确的 RAG 重建命令

建议按下面顺序做。

### 第一步：进入项目目录

```bash
cd /data/apps/freight-agent
```

### 第二步：先确认资料文件在不在

```bash
ls -lah data/docs
```

你要确认：

- 服务器上的 `data/docs` 里确实已经有你要入库的资料
- 文件名和你本地一致

### 第三步：执行重建

```bash
docker compose exec freight-agent-app python -m scripts.rebuild_kb
```

这一步会做的事情是：

1. 删除旧的 Chroma 持久化目录
2. 删除旧的 BM25 缓存
3. 重置 collection
4. 重新扫描 `data/docs`
5. 重新建索引
6. 重新导出 chunk 调试文件

也就是说：

**你不需要自己手动删 `data/chroma` 或 `data/cache`。**

脚本本身已经处理了。

---

## 5. RAG 重建完成后还要不要重启容器

从代码逻辑上说：

- BM25 每次查询都会重新加载缓存文件
- Chroma 使用的是持久化目录

理论上重建后就可以直接生效。

但从线上稳定性来说，我更建议你：

**重建完成后，重启一次应用容器。**

建议命令：

```bash
docker compose restart freight-agent-app
```

更稳的完整动作可以是：

```bash
cd /data/apps/freight-agent
docker compose exec freight-agent-app python -m scripts.rebuild_kb
docker compose restart freight-agent-app
docker compose ps
```

这样做的原因是：

- 避免应用进程里可能存在旧的向量库客户端状态
- 让应用进程用最新索引重新开始服务

Nginx 容器通常不需要跟着重启。

---

## 6. RAG 在服务器端需要注意什么

这部分是最容易被忽略的。

## 6.1 先确认资料文件是最新的

如果服务器上的 `data/docs` 不是你最新那批资料，那你重建出来的也是旧知识库。

所以重建前先确认：

```bash
ls -lah data/docs
```

必要时比对文件名、修改时间、文件大小。

---

## 6.2 当前线上并不是完整混合检索完全体

你现在 `deploy/.env.production` 里配置的是：

```text
RAG_ENABLE_VECTOR_SEARCH=false
```

这说明当前线上环境里，向量检索是关闭的。

这会带来一个现实影响：

- 你即使重建了知识库
- 当前线上 RAG 也不是完整“向量 + BM25”模式
- 更偏向 BM25 / 规则兜底这条链路

如果你后续想跑完整的混合检索，应该再确认是否要改成：

```text
RAG_ENABLE_VECTOR_SEARCH=true
```

然后再执行：

1. 重建知识库
2. 重启应用容器

---

## 6.3 重建会花时间，也会调用外部能力

RAG 重建不是瞬时动作，尤其会涉及：

- 文档读取
- 清洗
- 切分
- embedding
- Chroma 写入
- BM25 缓存生成

所以你要注意：

1. 容器里外网访问正常
2. `DASHSCOPE_API_KEY` 有效
3. 服务器不要在重建过程中强制中断

---

## 6.4 日志和导出文件要检查

重建后建议看一下：

```bash
ls -lah data/chroma
ls -lah data/cache
ls -lah data/exports
```

特别是：

- `data/cache/bm25.pkl`
- `data/exports/chunks.json`

这些文件如果生成了，说明重建主流程基本跑通了。

---

## 6.5 重建后一定要做问答验证

不要只看“命令没报错”，还要实际问一两个问题。

例如：

```text
锂电池货物需要什么声明文件？
```

或者：

```text
ACCOS 系统如何录入分单件数？
```

你要确认：

- 能召回资料
- 回答不是兜底
- 回答方向正确

---

## 7. 服务器端 RAG 最推荐的完整收尾流程

建议你按这套顺序走。

```bash
cd /data/apps/freight-agent
ls -lah data/docs
docker compose exec freight-agent-app python -m scripts.rebuild_kb
docker compose restart freight-agent-app
docker compose ps
docker compose logs --tail=100 freight-agent-app
```

然后再测试：

```bash
curl http://127.0.0.1/health
curl http://47.101.141.117/health
```

最后再实际测试 RAG 问答。

---

## 8. 如果以后有真实域名，服务器还要做什么

如果你后续有真实域名，服务器端还要再补几件事。

## 8.1 先做域名解析

在你的域名服务商或 DNS 控制台里，增加：

- `A` 记录
- 指向你的公网 IP：`47.101.141.117`

例如：

- `api.yourdomain.com -> 47.101.141.117`

或者：

- `www.yourdomain.com -> 47.101.141.117`

---

## 8.2 安全组要放通 443

你当前如果只是 HTTP，通常只开：

- `22`
- `80`

后续上 HTTPS 时，还要放通：

- `443`

---

## 8.3 修改 Nginx 的 `server_name`

你当前是：

```nginx
server_name 47.101.141.117;
```

以后有域名后，应该改成真实域名，例如：

```nginx
server_name api.yourdomain.com;
```

如果同时支持多个域名，也可以写多个。

---

## 8.4 增加 HTTPS 证书

你后续上真实域名后，建议补：

- 80 跳 443
- 443 SSL
- 证书文件挂载

典型思路是：

1. 申请证书
2. 把证书和私钥放到服务器
3. 挂载进 Nginx 容器
4. 修改 Nginx 配置支持 `listen 443 ssl`

---

## 8.5 证书怎么处理更合理

你当前是 Docker 化的 Nginx，所以更推荐：

- 证书保存在宿主机目录
- 通过 volume 挂载进 `freight-agent-nginx` 容器

例如后续可规划：

```text
/data/docker/freight-agent/nginx/certs
```

里面放：

- `fullchain.pem`
- `privkey.pem`

然后再挂载进 Nginx 容器。

---

## 8.6 域名上线后还要验证什么

你不仅要验证：

```text
https://你的域名/health
```

还要验证：

```text
https://你的域名/api/chat
```

因为你的核心接口是 SSE，HTTPS 之后也要确认：

- SSE 不被代理缓冲
- 长连接不被提前断开
- 前端能正常逐字显示

---

## 9. 有真实域名后的推荐动作顺序

后续如果你拿到真实域名，建议按这套顺序做：

1. DNS `A` 记录指向公网 IP
2. 安全组开放 `443`
3. 修改 Nginx `server_name`
4. 配置 SSL 证书
5. `docker compose up -d --build`
6. 测试：
   - `http://域名/health`
   - `https://域名/health`
   - `https://域名/api/chat`

---

## 10. 最终结论

你现在这个项目，确实已经接近最终环节了。

当前最推荐的下一步就是：

```bash
cd /data/apps/freight-agent
docker compose exec freight-agent-app python -m scripts.rebuild_kb
docker compose restart freight-agent-app
```

然后：

1. 测试健康检查
2. 测试 RAG 问答
3. 检查日志

如果这几步都正常，那你现在这个公网 IP 版本基本就算正式可用了。

后续真正再往前一步，就是：

- 上真实域名
- 上 HTTPS
- 把 Nginx 从 IP 入口切换为域名入口

这是下一阶段的事，不影响你现在先把公网 IP 版本跑通。
