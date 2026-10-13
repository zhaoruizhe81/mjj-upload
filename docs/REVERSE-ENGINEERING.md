# 逆向记录：mjj.today 上传接口

> 目标：`https://mjj.today/` — **Chevereto 4.0.8**（Peafowl 传统主题，Cloudflare 后面）
> 目的：把网页上传器抽成命令行可调用的接口
> 方法：浏览器运行时读取 + 前端 JS 静态分析 + 服务端探针矩阵，三方交叉验证
> 记录时间：2026-10-13

本文只记录协议事实与验证方式。文中出现的令牌均为**已失效的会话值**，且已截断。

---

## 1. 先判断它是什么

首页 `<meta name="generator" content="Chevereto 4">`、资源路径 `/content/legacy/themes/Peafowl/...`。
Chevereto 是开源图床程序，前端上传器有固定的实现形态，知道这点能省掉一半摸索。

页面内联脚本里直接摊着入口和令牌：

```js
var CHEVERETO = {"edition":"Chevereto","version":"4.0.8", ...};

PF.obj.config.base_url  = "/";
PF.obj.config.json_api  = "/json";                              // 统一 JSON 入口
PF.obj.config.auth_token = "cc91e2dc…d75";                      // 会话令牌（每会话不同）
```

同一个页面还带着全部限制条件：

```js
CHV.obj.config = {
  image:   { max_filesize: "10 MB", max_width: "16360", max_height: "16360" },
  upload:  { url: false, threads: "5", moderation: false,
             image_types: ["jpg","jpeg","png","bmp","gif","webp","jpeg"] },
  captcha: { isNeeded: false, enabled: false, sitekey: "" }     // ← 没有验证码
};
```

`upload.url = false` 在这里就已经预告了「远程 URL 拉图」被关掉（后文探针确认）。

> **为什么要先读运行时**：`auth_token` 每个会话都不一样（同一时刻从 curl 和浏览器拿到的值不同），
> 它是**按会话签发**的，必须和 `Set-Cookie` 下发的 `PHPSESSID` 配对使用。

---

## 2. 字段表：前端 JS 里是明码

Chevereto 的 `chevereto.min.js` 里，上传器 `CHV.fn.uploader` 构造请求的代码没有被混淆，
就是一段明码常量（压缩包里 offset ≈ 75429）：

```js
var l = new FormData,
    d = {
      source:      null,
      type:        n ? "url" : "file",
      action:      "upload",
      privacy:     $("[data-privacy]", this.selectors.root).first().data("privacy"),
      timestamp:   this.timestamp,                             // 队列开始时 (new Date).getTime()
      auth_token:  PF.obj.config.auth_token,
      expiration:  $("[name=upload-expiration]", root).val() || "",
      category_id: $("[name=upload-category-id]", root).val() || null,
      nsfw:        $("[name=upload-nsfw]", root).prop("checked") ? 1 : 0,
      album_id:    $("[name=upload-album-id]", root).val() || null
    };
n ? d.source = s : l.append("source", s, i.name);         // 文件字段名就是 source
$.each(d, function (e, t) { if (null === t) return true; l.append(e, t); });

this.files[t].xhr.open("POST", PF.obj.config.json_api, true);      // → POST /json
this.files[t].xhr.setRequestHeader("Accept", "application/json");
```

`expiration` 的合法取值直接来自页面上那个 `<select name="upload-expiration">`：

```
""  PT5M  PT15M  PT30M  PT1H  PT3H  PT6H  PT12H
P1D P2D P3D P4D P5D P6D P1W P2W P3W
P1M P2M P3M P4M P5M P6M P1Y
```

---

## 3. 浏览器抓包交叉验证

光读代码不够 —— 压缩版的变量名和分支会骗人，必须拿真实请求对一遍。

做法：在页面上用 `DataTransfer` 往文件输入框 `#anywhere-upload-input` 注入一张生成的 PNG，
再点站点的「上传」按钮，让**站点自己的 JS** 发请求，然后从 DevTools Network 读原始请求：

```
POST https://mjj.today/json                                    →  200
accept: application/json
content-type: multipart/form-data; boundary=----WebKitFormBoundary…
cookie: PHPSESSID=<会话>
origin: https://mjj.today
referer: https://mjj.today/
```

请求体（拆开 boundary 后的字段顺序）：

```
source       filename="cli-probe.png"  Content-Type: image/png     ← 文件二进制
type         file
action       upload
timestamp    1791906613210
auth_token   cc91e2dc…d75
expiration   （空）
nsfw         0
—— 注意：抓到的请求里没有 privacy / category_id / album_id
```

响应结构：

```json
{
  "status_code": 200,
  "success": { "message": "image uploaded", "code": 200 },
  "image": {
    "id_encoded": "QyuPCh0",
    "url":         "https://i.mji.rip/2026/10/13/<md5>.png",
    "url_viewer":  "https://mjj.today/i/QyuPCh0",
    "thumb":       { "url": "https://i.mji.rip/2026/10/13/<md5>.th.png" },
    "delete_url":  "https://mjj.today/i/QyuPCh0/delete/<64hex>",
    "filename": "<md5>.png", "mime": "image/png", "extension": "png",
    "size": 5254, "width": "64", "height": "64", "md5": "37367cd8…",
    "storage_mode": "datefolder", "is_approved": "1",
    "expiration_date_gmt": null
  },
  "request": { "type": "file", "action": "upload", "nsfw": "0", "expiration": "" },
  "status_txt": "OK"
}
```

错误统一形状：

```json
{"status_code":500,"error":{"message":"…","code":401,"id":"<incident id>"}}
```

---

## 4. 服务端探针矩阵（全部实测）

拿会话直接打接口，把「必填 / 可选 / 不能用」三类边界钉死：

| 探针 | 结果 | 结论 |
|---|---|---|
| `type=file` + 正确 token + cookie | `200` + 图片 URL | ✅ 主路径 |
| 同会话连续上传两次 | 两次都 `200` | 令牌可复用，不必每次重握手 |
| 不带 `auth_token` | `500 {"message":"请求被拒绝 (401)"}` | 令牌是硬门槛 |
| 伪造 `auth_token` | `500 {"message":"请求被拒绝 (401)"}` | 服务端按会话校验 |
| **不带 `timestamp`** | `200` | 可选 |
| **不带 `privacy`** | `200` | 可选（默认 public） |
| `type=url` + 站内图片 URL | `500 {"message":"URL uploading is disabled (403)"}` | 远程拉图关闭 |
| `type=base64` | `500 TypeError` | 不支持 |
| `privacy=private` | `500`（通用报错） | 游客不能私密上传 |
| `expiration=300`（误当秒数） | `200` 但 `expiration_date_gmt = null` | 只认 ISO-8601 |
| `expiration=PT5M` | `200`，`expiration_date_gmt = 上传时刻 +5min` | ✅ |
| `expiration=P1W` | `200`，`+7 天` | ✅ |
| `title=测试 标题` / `description=…` | `200`，字段原样回显 | 支持中文 |
| `.txt` 伪装上传 | `500 ⭕️ Something went wrong • Incident ID:…` | 类型错只有通用错 |
| 11 MB 的 PNG | 同样只有通用错 + Incident ID | 体积超限同理 → 客户端要本地预检 |
| `POST /api/1/upload`（无 key） | `400 {"message":"No key provided","code":100}` | 官方 API v1 开着 |
| `POST /api/1/upload`（假 key） | `400 {"message":"Invalid guest API key.","code":100}` | 需要账号自己的 key |

两点值得注意：

- **服务端错误信息很贫瘠**。超限、格式错、参数非法都只回一句通用错误 + Incident ID。
  所以客户端的本地预检（体积、后缀）不是多余的，它是唯一能给出可读提示的地方。
- **`privacy` 在浏览器抓包里根本不存在**。压缩代码里 `privacy` 取到 `undefined` 被 jQuery 过滤掉了，
  所以「传 `public`」和「完全不传」都行 —— 这种「代码读起来要传、实际抓包没传」的差异，
  只有把两边都做一遍才能发现。

---

## 5. 删除链路

`delete_url` 是上传响应里**只给一次**的一次性凭据：

```
GET https://mjj.today/i/QyuPZLU/delete/<64hex>
  → HTTP 404，但 URL 落到 https://mjj.today/i/QyuPZLU/?deleted     ← 删除成功（404 是预期行为）
  → 复查信息页 https://mjj.today/i/QyuPZLU ：200 → 404              ← 确认已删
```

**别被 404 骗了**：删除成功的响应就是 404 + 跳 `?deleted`。判断依据是 URL 里的 `deleted` 标记和信息页的复查结果，
不是状态码。这也是本项目把 `delete_url` 存进本地历史（`~/.cache/mjj-uploader/history.jsonl`）的原因 ——
它只出现一次，丢了就只能去站点后台删。

CDN 直链 `i.mji.rip/<date>/<md5>.png` 因为 Cloudflare 边缘缓存，短时间仍可能返回 200。

另外接口返回的 CDN 域名 `i.mji.rip` 是**跳转域名**，`301 → i.mij.rip`（真身，注意 `mji` / `mij` 之别）。

---

## 6. 最小复现

```bash
# 1) 握手
curl -s -c cookies.txt https://mjj.today/ -o page.html
TOKEN=$(grep -o 'auth_token = "[a-f0-9]*"' page.html | head -1 | sed 's/.*"\([a-f0-9]*\)"/\1/')

# 2) 上传
curl -s -b cookies.txt -X POST https://mjj.today/json \
  -H "Accept: application/json" \
  -H "Origin: https://mjj.today" -H "Referer: https://mjj.today/" \
  -F "source=@test.png;type=image/png" \
  -F "type=file" -F "action=upload" -F "privacy=public" \
  -F "timestamp=$(python3 -c 'import time;print(int(time.time()*1000))')" \
  -F "auth_token=$TOKEN" -F "expiration=" -F "nsfw=0"
```

跑通之后把字段搬进 `mjj_upload.py` 的 `upload_file()` 即可，等价实现见仓库根目录脚本。

---

## 7. 关于本文的边界

- 文中所有令牌、id、删除凭据都来自**本项目作者自己的临时上传**，且已失效/截断。
- 逆向时抓取的站点 JS / HTML 产物**没有**放进仓库（那是第三方版权资源）。
  你需要时可按上面第 1、2 节的方法自行从站点获取：`/content/legacy/themes/Peafowl/lib/chevereto.min.js`。
- 复现路径只依赖浏览器自带的开发者工具与 `curl`，没有任何绕过或破解动作 —— 用的是站点给游客的正常上传通道。

## 8. 站点改版了怎么办

1. **令牌还在不在**：`curl -s <base>/ | grep -o 'auth_token = "[a-f0-9]*"'`
2. **入口和限制**：页面源码找 `PF.obj.config.json_api`、`CHV.obj.config.upload.image_types`、`CHV.obj.config.captcha.isNeeded`
3. **字段表**：站点 JS 里搜 `new FormData`，紧随的 `{source, type, action, …}` 对象就是协议；curl 打通后改脚本的 `fields`
4. **换站**：任意自建 Chevereto 4 都是同一套前端，`mjj --base-url https://your-host/` 直接复用
