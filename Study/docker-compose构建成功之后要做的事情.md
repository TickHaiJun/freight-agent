# docker compose 构建成功之后要做的事情

## 1. 先回答你的问题

如果你现在已经看到：

- `freight-agent-app` 是 `Healthy`
- `freight-agent-nginx` 是 `Started`
- `docker compose up -d --build` 没有报错退出

那么从项目本身来看，已经具备“可以访问”的前提了。

但要真正通过公网 IP 访问，还要再满足下面几个条件：

1. 阿里云安全组已经放通 `80`
2. 服务器本机防火墙没有拦截 `80`
3. Nginx 容器已经正常监听 `80`
4. 应用容器健康检查通过
5. 你访问的是：

```text
http://47.101.141.117
```

所以准确说法不是“构建成功就一定能访问”，而是：

`构建成功 + 容器正常 + 80 端口可达 = 基本就可以通过公网 IP 访问`

---

## 2. 你当前的 Nginx 配置对不对

基于当前项目文件，Nginx 配置整体是对的，适合你现在“没有域名、先用公网 IP 访问”的场景。

当前关键配置是：

```nginx
server {
    listen 80;
    server_name 47.101.141.117;

    location / {
        proxy_pass http://freight-agent-app:8012;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_cache off;
        chunked_transfer_encoding off;
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }
}
```

### 2.1 为什么说它是对的

因为它已经满足这几个关键点：

1. `listen 80`
   说明外部可以通过 HTTP 访问。

2. `server_name 47.101.141.117`
   说明你当前用公网 IP 访问是合理的。

3. `proxy_pass http://freight-agent-app:8012`
   说明 Nginx 会把请求转给 Compose 网络里的应用容器。

4. `proxy_buffering off`
   这个非常重要，SSE 流式输出必须关代理缓冲，否则前端会出现“卡住不出字”。

5. `proxy_read_timeout 3600`
   适合聊天接口这种长连接响应。

### 2.2 当前不需要改的地方

在你还没有域名之前，当前不需要为了“更正式”去改成域名配置。

以后你有域名了，再把：

```text
server_name 47.101.141.117;
```

改成：

```text
server_name your-domain.com;
```

并加上 HTTPS 即可。

---

## 3. `docker compose up -d --build` 之后立刻要做的事情

这一步非常重要。不要看到容器起来了就停住，后面还要做完整验证。

## 3.1 先检查容器状态

```bash
cd /data/apps/freight-agent
docker compose ps
```

你需要重点看：

- `freight-agent-app` 是否是 `healthy`
- `freight-agent-nginx` 是否是 `up`

如果应用是 `healthy`，说明 `/health` 在容器内已经通了。

---

## 3.2 查看最近日志

先看应用日志：

```bash
docker compose logs --tail=100 freight-agent-app
```

再看 Nginx 日志：

```bash
docker compose logs --tail=100 freight-agent-nginx
```

这一步主要看有没有：

- Python 启动异常
- 环境变量缺失
- 依赖加载失败
- Nginx 配置错误

---

## 3.3 先测服务器本机健康检查

```bash
curl http://127.0.0.1/health
```

如果这里能通，说明：

- Nginx 本机监听没问题
- Nginx 到应用容器的反代没问题
- 应用本身 `/health` 路由存在且可达

你当前项目里 `/health` 路由是存在的，所以这一步应该是必须成功的。

---

## 3.4 再测公网 IP 健康检查

```bash
curl http://47.101.141.117/health
```

如果这里也能通，说明公网访问已经打通。

这时浏览器就可以直接访问：

```text
http://47.101.141.117/health
```

正常应该返回类似健康状态 JSON。

---

## 3.5 检查宿主机日志是否开始落盘

```bash
ls -lah /data/logs/freight-agent
```

你应该重点确认这几个文件是否开始出现：

- `freight-agent-app.log`
- `freight-agent-app.jsonl`
- `freight-agent-error.log`

如果这些文件已经生成，说明容器内应用日志已经正确写到宿主机目录，而不是写在容器临时层里。

---

## 4. 对你这个项目来说，还需要做哪些验证

你这个项目不是静态网站，也不是普通 REST 服务，它是：

- FastAPI
- SSE 流式聊天
- 运价查询工具调用
- RAG 检索问答
- 结构化日志落盘

所以你构建成功之后，至少要补这几类验证。

## 4.1 验证健康接口

目标：

- 服务已经真正启动
- Nginx 已经能转发

命令：

```bash
curl http://127.0.0.1/health
curl http://47.101.141.117/health
```

---

## 4.2 验证聊天主接口是否能通

建议你至少用一条最简单的消息做测试，例如：

```bash
curl -N -X POST "http://47.101.141.117/api/chat" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"test001\",\"message\":\"你好\",\"context\":{}}"
```

这一步验证的是：

- Nginx 到 SSE 是否正常
- 前端未来走 `/api/chat` 是否能收到流式返回
- Agent 主链路是否能正常响应

---

## 4.3 验证运价链路

建议再测一条简单运价问题，例如：

```text
我有一票货，发往洛杉矶，散货，600公斤，4个立方，今天发，多少钱
```

这里你主要观察：

- 是否会正常追问
- 是否错误进入兜底
- 是否能调用运价接口

因为你当前项目的核心能力之一就是询价链路，这一块不能只看 `/health`。

---

## 4.4 验证 RAG 链路

如果你已经在服务器准备好了知识库和索引，还应该测一条知识问答，例如：

```text
锂电池货物需要什么声明文件？
```

如果你当前服务器还没重建知识库，那这一步可以暂时不测，但要记住：

`容器起来了 != RAG 就一定可用`

---

## 4.5 验证日志是否真正可用

不仅要看文件在不在，还要看有没有内容：

```bash
tail -n 50 /data/logs/freight-agent/freight-agent-app.log
tail -n 20 /data/logs/freight-agent/freight-agent-app.jsonl
```

因为你后面还要做日志平台，这一步不是可有可无。

---

## 5. 如果现在访问不了，优先查什么

如果你执行完 `docker compose up -d --build` 后仍然访问不了，不要盲猜，按这个顺序排查。

## 5.1 先查容器状态

```bash
docker compose ps
```

看应用容器有没有退出，Nginx 有没有退出。

## 5.2 再查应用日志

```bash
docker compose logs --tail=100 freight-agent-app
```

看有没有：

- Python 报错
- 环境变量缺失
- 启动异常

## 5.3 再查 Nginx 日志

```bash
docker compose logs --tail=100 freight-agent-nginx
```

看有没有：

- 配置错误
- upstream 不通

## 5.4 再查服务器本机访问

```bash
curl http://127.0.0.1/health
```

如果本机能通，但公网 IP 不通，那问题一般在：

- 安全组
- 云服务器防火墙
- 公网入口

## 5.5 再查公网访问

```bash
curl http://47.101.141.117/health
```

---

## 6. 你现在没有域名，怎么访问最合理

目前没有域名是完全没问题的。

你当前阶段最合理的做法就是：

- 先用公网 IP 跑通
- 先完成功能联调
- 先确认 Nginx 和 Docker 稳定
- 后面再上域名和 HTTPS

所以现在推荐的访问地址就是：

```text
http://47.101.141.117
```

以及：

```text
http://47.101.141.117/health
http://47.101.141.117/api/chat
```

---

## 7. 这一步之后，对你项目还要补哪些事

从“容器已经起来”到“项目真正进入可用状态”，建议你继续做下面这些事。

## 7.1 确认生产环境变量最终正确

重点看：

- `DEEPSEEK_API_KEY`
- `FREIGHT_API_BASE`
- `DASHSCOPE_API_KEY`
- `APP_LOG_DIR`

这一步是因为：

- 容器能起来，不代表业务接口一定能通
- 容器能起来，不代表日志一定写对地方

---

## 7.2 确认知识库是否已就绪

如果你要用 RAG，就继续检查：

- `data/docs` 是否已同步
- Chroma 是否存在
- 索引是否已经构建

如果服务器还没完成知识库初始化，这一步后面一定要补。

---

## 7.3 确认日志滚动是否正常

你后面要做日志平台，所以建议后续观察：

- 日志是否每天滚动
- `.jsonl` 是否持续写入
- `/data/logs/freight-agent` 是否权限正常

---

## 7.4 确认后续更新流程可复用

你应该尽快把服务器更新流程固定成：

```bash
cd /data/apps/freight-agent
git pull origin main
docker compose up -d --build
docker compose ps
curl http://127.0.0.1/health
```

这样后面每次迭代就不会乱。

---

## 8. 最终结论

你当前这次 `docker compose up -d --build` 的结果整体是好的：

- 应用容器已经 `Healthy`
- Nginx 容器已经启动
- Nginx 配置对当前“公网 IP 访问 + SSE”场景是正确的

所以现在下一步不应该再去改部署文件，而应该立刻做：

1. `docker compose ps`
2. `docker compose logs --tail=100 freight-agent-app`
3. `curl http://127.0.0.1/health`
4. `curl http://47.101.141.117/health`
5. 测试 `/api/chat`
6. 检查 `/data/logs/freight-agent`

如果这几步都正常，那你现在这个项目就已经能先通过公网 IP 访问和联调了。
