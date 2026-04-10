# 从根目录迁移到二级目录访问的经验手册

这份文档总结了把一个原本部署在根目录 `/` 的 Web 项目，迁移到二级目录（例如 `/notebooks`）时的沟通要点、改造范围、排查方式，以及哪些地方通常不用改。

文档以 Open Notebook 为例，但思路可以复用于大多数 `浏览器前端 + 应用服务 + API` 的项目。

---

## 1. 先和公司 Nginx/网关确认什么

迁移前最重要的不是先改代码，而是先确认公司侧的反向代理到底怎么转发。

最关键的问题只有一个：

**代理到应用时，是否保留二级目录前缀？**

### 方式 A：保留前缀

Nginx 示例：

```nginx
location /notebooks/ {
    proxy_pass http://10.x.x.x:8502/notebooks/;
}
```

或者等价配置，效果是用户请求里的 `/notebooks` 仍然会传到你的服务。

结果：

| 用户请求 | 应用实际收到 |
|---|---|
| `GET /notebooks` | `GET /notebooks` |
| `GET /notebooks/login` | `GET /notebooks/login` |
| `GET /notebooks/api/config` | `GET /notebooks/api/config` |

这种方式下，**你的应用本身必须知道自己运行在 `/notebooks` 下**。

---

### 方式 B：去掉前缀

Nginx 示例：

```nginx
location /notebooks/ {
    proxy_pass http://10.x.x.x:8502/;
}
```

结果：

| 用户请求 | 应用实际收到 |
|---|---|
| `GET /notebooks/` | `GET /` |
| `GET /notebooks/login` | `GET /login` |
| `GET /notebooks/api/config` | `GET /api/config` |

这种方式下，**应用通常不需要 basePath/subdirectory 配置**，因为前缀已经被代理层吃掉了。

---

## 2. 如何选方案

推荐先按公司现有网关能力来定，不要让项目和运维各自假设。

### 如果公司是方式 A：保留前缀

项目需要进入“二级目录模式”：

- 前端路由需要知道 base path，例如 `/notebooks`
- 浏览器访问的静态资源需要带前缀
- 浏览器发起的 API 请求需要带前缀
- 后端如果直接收到带前缀路径，也需要能识别

### 如果公司是方式 B：去掉前缀

项目可以继续按“根目录模式”运行：

- 前端仍然认为自己运行在 `/`
- API 仍然按 `/api/...`
- 静态资源仍然按 `/logo.svg`、`/_next/static/...`

---

## 3. Open Notebook 的例子

假设公司给你的外部访问地址是：

```text
https://portal.example.com/notebooks
```

并且公司 Nginx 采用的是“保留前缀”。

这时一次典型请求的路径变化是：

```text
浏览器访问:
https://portal.example.com/notebooks

浏览器请求配置:
GET https://portal.example.com/notebooks/config

浏览器请求 API:
GET https://portal.example.com/notebooks/api/config

Next.js/应用服务收到:
GET /notebooks/api/config

如果 Next.js 再把 /api/* 转给 FastAPI:
内部目标通常还是 http://localhost:5055/api/config
```

这类项目迁移的本质不是“只改一个 API 地址”，而是让**所有浏览器会访问到的 URL**都和 `/notebooks` 对齐。

---

## 4. 应该修改哪些地方

下面这份清单适合给任何“根目录改二级目录”的项目复用。

### 4.1 先改部署与环境变量

先确定二级目录字符串，例如：

```env
SUBDIR=/notebooks
```

对于 Open Notebook，这一层对应的是：

```env
OPEN_NOTEBOOK_BASE_PATH=/notebooks
API_URL=https://portal.example.com/notebooks
INTERNAL_API_URL=http://localhost:5055
```

注意：

- `API_URL` 写公开访问地址
- `API_URL` 不要手动加 `/api`
- `INTERNAL_API_URL` 是内部服务地址，通常还是根路径内部地址，不走公司公网二级目录

---

### 4.2 前端框架层要改

如果前端框架支持 base path，要优先用框架内置能力。

需要检查：

- 路由根路径是否支持配置 `basePath`
- 静态资源前缀是否支持配置 `assetPrefix`
- 根路径 `/` 是否需要重定向到 `/notebooks`
- 构建产物是否在 build 时固化了子路径

Open Notebook 对应修改：

- Next.js `basePath`
- Next.js `assetPrefix`
- 根路径重定向到子路径入口

### Open Notebook 的特殊点：已经基本支持“一键切换 basePath”

Open Notebook 和很多普通项目不一样，它现在已经把二级目录支持收敛到了比较集中的几处配置上。

对 Open Notebook 来说，核心开关主要是：

```env
OPEN_NOTEBOOK_BASE_PATH=/notebooks
API_URL=https://portal.example.com/notebooks
INTERNAL_API_URL=http://localhost:5055
```


- 前端框架层已经支持 `basePath`
- 静态资源前缀已经支持 `assetPrefix`
- 前端很多浏览器访问路径已经统一走 `withBasePath(...)`
- API 地址拼接已经集中封装
- 后端也兼容了带前缀的 API 路由

因此在 Open Notebook 里，通常不需要你再去一页页、一个组件一个组件手工改 URL。

---

### 其他项目不要直接照抄这一点

其他项目常见问题是：

- 框架本身支持 `basePath`，但业务代码里大量手写了 `/login`、`/api/...`
- 图片、字体、下载链接仍然写死根路径
- `fetch('/api/...')` 分散在各页面里，没有统一 API 客户端
- 登录跳转、401 跳转、`window.open(...)` 没有统一封装
- 后端只注册了根路径版接口，没有兼容带前缀入口

所以对于其他项目，不能只改一个 `basePath` 配置就结束，还是要按下面这些项逐个检查：

- 页面路由
- 静态资源
- API 请求
- 登录/登出跳转
- 打开新标签页的链接
- 运行时配置接口
- 错误提示页里的调试 URL
- 后端路由和鉴权白名单

---

### 4.3 浏览器里直接访问的 URL 要改

只要是**浏览器直接请求**的地址，都要检查是否需要加二级目录前缀。

常见包括：

- 页面跳转链接
- `window.location.href`
- `window.open(...)`
- 登录页、登出后跳转页
- 401 后自动跳转登录
- 图片、图标、字体
- `favicon.ico`
- 前端运行时配置接口，例如 `/config`
- 调试页里显示给用户看的诊断 URL

Open Notebook 这类项目里，容易漏改的是：

- `/login`
- `/config`
- `/logo.svg`
- `/sources/...`
- 错误页里显示的 `/api/config`

经验上，最好统一封装一个类似 `withBasePath(path)` 的函数，避免手写字符串。

---

### 4.4 浏览器发起的 API 请求要改

如果浏览器请求仍然打到域名根下：

```text
/api/notebooks
```

在二级目录场景中就可能失败，因为正确入口已经变成：

```text
/notebooks/api/notebooks
```

建议做法：

- 不要在组件里到处手拼 URL
- 统一做一个 `buildApiEndpoint(baseUrl, path)` 或 `apiClient`
- 把 `basePath`、`API_URL`、相对路径逻辑集中处理

需要检查：

- `axios` 实例的 `baseURL`
- `fetch('/api/...')`
- 登录请求
- 鉴权状态检测
- SSE/流式接口
- 上传接口
- 下载接口

---

### 4.5 后端入口是否也要改

这取决于公司代理方式。

如果公司采用“保留前缀”，后端可能直接收到：

```text
/notebooks/api/...
```

这时后端要检查：

- 路由是否只注册了 `/api/...`
- 鉴权白名单是否只写了根路径版本
- `/health`、`/docs`、`/openapi.json` 是否需要前缀版本
- 是否有重定向、回调 URL、下载 URL、公开 URL 是后端拼的

Open Notebook 的做法是同时注册：

- `/api/...`
- `/notebooks/api/...`

这样更稳，便于兼容不同代理链路。

---

## 5. 哪些通常不用改

这是最容易“过度修改”的部分。

### 5.1 后端内部访问数据库通常不用改

例如：

- `ws://surrealdb:8000/rpc`
- `postgres://...`
- `redis://...`

这些不是浏览器访问的公网 URL，不受 `/notebooks` 影响。

---

### 5.2 后端访问外部第三方服务通常不用改

例如：

- `https://api.openai.com/...`
- `https://api.anthropic.com/...`
- 对象存储、消息队列、向量库

这些 URL 也不走公司前端入口，不需要因为二级目录而修改。

---

### 5.3 业务逻辑本身通常不用改

例如：

- 数据库存取
- 搜索逻辑
- 排序逻辑
- AI 调用流程
- 权限判断规则

二级目录改造本质上是“访问入口层”的问题，不应该把和路径无关的业务逻辑一起改乱。

---

### 5.4 HTTP 方法通常不用改

从根目录迁移到二级目录，不会改变：

- `GET`
- `POST`
- `PUT`
- `DELETE`

要改的是**URL 前缀**，不是接口语义。

---

### 5.5 内部服务间地址通常不需要带二级目录

例如：

```env
INTERNAL_API_URL=http://localhost:5055
```

这类地址是容器内、主机内、服务网格内的内部调用，通常不通过公司 Nginx，也就不需要 `/notebooks`。

---

## 6. 迁移时最常见的漏项

下面这些很容易漏掉：

- 登录页跳转仍然是 `/login`
- Logo、favicon、字体仍然走根路径
- 前端配置接口仍然写死 `/config`
- 连接错误提示页显示的 URL 还是根路径
- `window.open('/xxx')` 忘了加前缀
- SSE/streaming 请求没走统一 API 客户端
- 后端鉴权排除列表没有带前缀版本
- `/health` 或 `/docs` 在二级目录下打不开
- `API_URL` 错写成 `https://domain/notebooks/api`

---

## 7. 给其他项目复用时的检查清单

迁移任何项目到二级目录时，都可以按下面顺序检查。

### 第一步：先问清公司网关

- 外部访问路径是什么
- 代理到应用时是否保留前缀
- 是否需要 HTTPS
- 是否会改写 Host / X-Forwarded-Proto
- 文件上传大小限制是多少

### 第二步：确认前端框架能力

- React Router / Next.js / Vue Router 是否支持 base path
- 静态资源是否支持前缀
- 打包后路径是否会固化

### 第三步：排查浏览器直接访问的 URL

- 页面路由
- API 请求
- 静态资源
- 登录跳转
- 下载链接
- 新开标签页链接
- 运行时配置接口

### 第四步：排查后端对路径的假设

- 路由注册
- 鉴权白名单
- 健康检查
- Swagger/OpenAPI
- 回调地址
- 重定向地址
- 后端拼装的公开 URL

### 第五步：做真实环境验证

至少验证这些地址：

- `https://portal.example.com/notebooks`
- `https://portal.example.com/notebooks/login`
- `https://portal.example.com/notebooks/api/config`
- `https://portal.example.com/notebooks/_next/static/...`
- 上传文件
- 登录/登出
- 打开新页面
- 401 后自动跳转

---

## 8. 一个实用判断标准

迁移时可以用一句话快速判断是否该改：

**这个 URL 是不是浏览器直接访问的？**

如果答案是“是”，大概率要考虑二级目录前缀。

如果答案是“不是，而是后端内部服务调用或第三方接口”，通常不用因为二级目录而改。

---

## 9. 对 Open Notebook 这类项目的最终建议

如果公司 Nginx 采用“保留前缀”的方式，并给出入口 `/notebooks`，推荐采用下面这组原则：

- 前端构建时设置 `OPEN_NOTEBOOK_BASE_PATH=/notebooks`
- 公网配置里设置 `API_URL=https://your-domain/notebooks`
- 内部转发保留 `INTERNAL_API_URL=http://localhost:5055`
- 所有浏览器访问的页面、静态资源、API 都按 `/notebooks/...` 处理
- 后端尽量兼容 `/api/...` 和 `/notebooks/api/...` 两套入口
- 不要把和路径无关的数据库、AI、业务逻辑一起修改

---

## 10. 一句话总结

根目录改二级目录，本质不是“改一个 API 地址”，而是：

**把所有浏览器可见的入口统一迁移到新的前缀下，同时避免误改后端内部调用和业务逻辑。**
