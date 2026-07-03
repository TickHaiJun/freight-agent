# 阿里云 Docker Nginx 启用 HTTPS 操作方案

## 1. 目标

当前项目已经采用：

- `Docker Compose`
- `Nginx` 容器反向代理
- `freight-agent-app` 应用容器

当前外部访问方式还是：

```text
http://域名
```

本次目标是把它切换成：

```text
https://域名
```

并且实现：

1. `http://域名` 自动跳转到 `https://域名`
2. `https://域名` 由 Docker 中的 Nginx 容器处理证书
3. `Nginx` 继续反向代理到 `freight-agent-app:8012`
4. 保持当前 SSE 聊天接口可用，不破坏 `/api/chat` 流式返回

---

## 2. 当前项目状态

根据当前项目文件，现状是：

### 2.1 `docker-compose.yml`

当前只有：

- `80:80`

还没有：

- `443:443`

### 2.2 `deploy/nginx/default.conf`

当前配置是：

- `listen 80;`
- `server_name 47.101.141.117;`
- 代理到：
  - `http://freight-agent-app:8012`

说明它现在是：

- 仅支持 HTTP
- 仅支持 IP 访问
- 还没有 SSL 证书配置

### 2.3 当前部署方式

你现在的线上结构是：

```text
浏览器
  -> 公网域名
  -> Docker Nginx 容器
  -> freight-agent-app 容器
```

这个结构是对的，HTTPS 也应该继续沿用这套结构，不需要改成宿主机单独装 Nginx。

---

## 3. 我推荐的实施方案

## 3.1 总体原则

继续使用 **Docker 内的 Nginx 容器** 管理证书和 HTTPS，不切回宿主机 Nginx。

原因：

1. 当前项目已经是 Docker Compose 架构，继续沿用最稳。
2. 配置和应用一起管理，后续迁移、备份、重建都更清晰。
3. 不会出现“宿主机 Nginx 一套、容器内 Nginx 一套”的双层维护问题。

## 3.2 证书文件不进 Git

证书和私钥不能提交到 GitHub。

建议证书只放在服务器上，例如：

```text
/data/docker/freight-agent/nginx/certs/
```

推荐结构：

```text
/data/docker/freight-agent/nginx/
├── certs/
│   ├── fullchain.pem
│   └── privkey.key
```

如果阿里云证书下载下来是：

- `xxx.pem`
- `xxx.key`

你可以统一重命名成：

- `fullchain.pem`
- `privkey.key`

方便后续 Nginx 配置固定。

---

## 4. 前置检查

在正式改配置前，先确认这 5 件事。

### 4.1 域名已解析到当前服务器公网 IP

你的域名必须已经有：

- `A` 记录
- 指向当前 ECS 公网 IP

如果要同时支持：

- `example.com`
- `www.example.com`

那两者都要正确解析。

### 4.2 证书覆盖的域名正确

证书必须和你要访问的域名匹配。

例如：

- 如果访问 `www.example.com`
- 证书里也要包含 `www.example.com`

否则浏览器会提示证书不匹配。

### 4.3 阿里云安全组已放通 `443`

当前安全组如果只有：

- `22`
- `80`

还不够。

必须新增：

- `443/TCP`

### 4.4 服务器本机没有额外拦截 `443`

如果启用了防火墙，也要确认：

- `443` 已放通

### 4.5 当前项目域名确定

在改 Nginx 前，先确定最终 `server_name` 是什么。

例如：

```nginx
server_name example.com www.example.com;
```

不要再继续保留 IP 作为正式 `server_name`。

---

## 5. 服务器目录规划建议

结合你当前项目，建议把 HTTPS 相关文件统一放在：

```text
/data/docker/freight-agent/nginx/
```

结构建议：

```text
/data/docker/freight-agent/nginx/
├── certs/
│   ├── fullchain.pem
│   └── privkey.key
```

说明：

- 证书目录不放在 Git 仓库里
- 只在服务器保留
- Docker Compose 通过挂载方式映射进 Nginx 容器

---

## 6. 需要改动的地方

本次主要会改两处：

1. `docker-compose.yml`
2. `deploy/nginx/default.conf`

说明：

- 证书文件本身不进仓库
- 证书路径通过服务器挂载处理

---

## 7. `docker-compose.yml` 应如何调整

## 7.1 增加 `443:443`

当前：

```yaml
ports:
  - "80:80"
```

改成：

```yaml
ports:
  - "80:80"
  - "443:443"
```

## 7.2 增加证书目录挂载

当前 Nginx volumes 只有：

```yaml
- ./deploy/nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
```

建议新增服务器证书目录挂载，例如：

```yaml
- /data/docker/freight-agent/nginx/certs:/etc/nginx/certs:ro
```

这样容器里证书路径就是：

```text
/etc/nginx/certs/fullchain.pem
/etc/nginx/certs/privkey.key
```

### 为什么这样做

原因很明确：

1. 证书只保留在服务器，不进 Git
2. Nginx 容器可以稳定读到证书
3. 后续证书续签或更换时，只替换服务器文件即可

---

## 8. `deploy/nginx/default.conf` 应如何调整

建议拆成两个 `server` 块。

## 8.1 第一个 `server`：监听 80，负责跳转到 HTTPS

作用：

- 接收 `http://域名`
- 全部 301 跳转到 `https://域名`

示意结构：

```nginx
server {
    listen 80;
    server_name example.com www.example.com;

    return 301 https://$host$request_uri;
}
```

## 8.2 第二个 `server`：监听 443，负责正式 HTTPS 服务

作用：

- 处理 TLS 证书
- 反向代理到 `freight-agent-app:8012`
- 保持 SSE 相关配置

示意结构：

```nginx
server {
    listen 443 ssl http2;
    server_name example.com www.example.com;

    ssl_certificate /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.key;

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
        proxy_request_buffering off;
        proxy_cache off;
        chunked_transfer_encoding off;
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }
}
```

### 为什么要保留这些 SSE 配置

因为你的 `/api/chat` 是 SSE 流式接口。

如果你只加 HTTPS，不保留这些配置，最常见的问题就是：

- 前端连接成功
- 但流式输出被缓冲
- 看起来像“卡住不出字”

所以这些配置不能丢：

- `proxy_buffering off`
- `proxy_request_buffering off`
- `proxy_read_timeout 3600`
- `proxy_send_timeout 3600`

---

## 9. 实际操作流程

下面这套步骤，按顺序执行就行。

## 第一步：确认域名解析

在阿里云 DNS 或你的域名管理平台确认：

- `A` 记录已指向服务器公网 IP

如果同时有裸域和 `www`：

- 两者都解析

## 第二步：确认安全组

在阿里云安全组里确认已放通：

- `80/TCP`
- `443/TCP`
- `22/TCP`

## 第三步：把证书上传到服务器

在服务器创建目录：

```bash
mkdir -p /data/docker/freight-agent/nginx/certs
```

然后把阿里云下载的证书上传进去。

最终建议变成：

```text
/data/docker/freight-agent/nginx/certs/fullchain.pem
/data/docker/freight-agent/nginx/certs/privkey.key
```

## 第四步：修改 `docker-compose.yml`

要点：

1. 增加：
   - `443:443`
2. 增加：
   - `/data/docker/freight-agent/nginx/certs:/etc/nginx/certs:ro`

## 第五步：修改 `deploy/nginx/default.conf`

要点：

1. `server_name` 改成正式域名，不再使用 IP
2. 增加 80 -> 443 跳转 `server`
3. 增加 `listen 443 ssl http2`
4. 增加证书路径
5. 保留 SSE 代理配置

## 第六步：检查 Nginx 配置是否正确

重启前建议先检查：

```bash
docker compose config
```

如果你已经改完并启动过容器，也可以用：

```bash
docker compose exec freight-agent-nginx nginx -t
```

如果返回 `syntax is ok` / `test is successful`，再继续。

## 第七步：重建并启动 Nginx

执行：

```bash
cd /data/apps/freight-agent
docker compose up -d --force-recreate freight-agent-nginx
```

如果你同时修改了应用相关内容，也可以整体执行：

```bash
docker compose up -d --force-recreate
```

## 第八步：查看容器状态

```bash
docker compose ps
docker compose logs --tail=100 freight-agent-nginx
```

确认：

- `freight-agent-nginx` 正常启动
- 没有证书路径不存在
- 没有 `ssl_certificate` 相关报错

## 第九步：本机测试

先测 HTTP 是否跳转：

```bash
curl -I http://你的域名
```

期望结果：

- `301`
- `Location: https://你的域名/...`

再测 HTTPS 是否可用：

```bash
curl -I https://你的域名
```

如果 `/health` 已代理，则可以直接：

```bash
curl -I https://你的域名/health
```

期望：

- `200 OK`

## 第十步：浏览器验证

在浏览器里测试：

```text
http://你的域名
https://你的域名/health
https://你的域名/api/chat
```

重点确认：

1. 浏览器不再提示“不安全”
2. HTTP 会自动跳到 HTTPS
3. 前端聊天流式输出正常

---

## 10. 当前项目特别要注意的点

## 10.1 `server_name` 不要继续写 IP

现在的配置是：

```nginx
server_name 47.101.141.117;
```

这只适合临时公网 IP 联调。

正式上 HTTPS 时，应改成：

```nginx
server_name 你的域名 www.你的域名;
```

## 10.2 证书不要放到仓库里

不要把：

- `.pem`
- `.key`

提交到 GitHub。

建议继续让它们只存在服务器：

```text
/data/docker/freight-agent/nginx/certs/
```

## 10.3 聊天 SSE 配置不能丢

你当前最敏感的是 `/api/chat`。

所以改 HTTPS 时，不要把现有反代块简化成普通代理模板，否则很容易出现 SSE 被缓存的问题。

## 10.4 如果以后启用 HSTS，要分阶段

第一版先不要急着上：

```nginx
add_header Strict-Transport-Security ...
```

原因：

- 一旦配错，浏览器会强制记住 HTTPS 策略
- 初期排障反而不方便

建议：

- 先跑通 HTTPS
- 稳定后再考虑 HSTS

---

## 11. 我推荐的实施方式

如果只给一个推荐，我建议这样做：

### 推荐方案

1. 域名先完成 A 记录解析
2. 证书上传到：
   - `/data/docker/freight-agent/nginx/certs/`
3. `docker-compose.yml` 增加：
   - `443:443`
   - 证书目录挂载
4. `deploy/nginx/default.conf` 改为：
   - 80 跳 443
   - 443 正式代理
   - 保留 SSE 配置
5. `docker compose up -d --force-recreate freight-agent-nginx`
6. 用 `curl` 和浏览器双重验证

这是最符合你当前项目结构的路径。

---

## 12. 风险点

本次切 HTTPS，最容易出问题的地方有 5 个：

1. 域名没解析对
2. 安全组没开 `443`
3. 证书文件路径挂载错
4. `server_name` 和证书域名不匹配
5. 改 Nginx 时把 SSE 代理配置弄丢

所以排查顺序建议永远是：

1. DNS
2. 安全组
3. 证书路径
4. `nginx -t`
5. `docker compose logs`
6. `curl http://域名`
7. `curl https://域名/health`

---

## 13. 结论

对你当前项目来说，最合理的 HTTPS 接入方式不是换架构，而是：

> 在现有 Docker Compose + Nginx 容器架构上，给 Nginx 增加 443 监听、证书挂载和 80 -> 443 跳转。

这样改动最小、风险最低、最符合你当前部署方式。

如果后续真正实施，我建议按这份文档一步一步做，不要一次性同时改：

- 域名
- 证书
- 反代逻辑
- 应用层路径

优先先把 HTTPS 跑通，再做后续优化。
