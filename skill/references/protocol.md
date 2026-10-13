# mjj.today 上传协议速查（逆向实测）

目标：`https://mjj.today/` — Chevereto **4.0.8**（Peafowl 主题），Cloudflare 后面，无 JS 挑战、无验证码。
完整逆向记录（含抓包、探针矩阵、删除链路）见仓库 `docs/REVERSE-ENGINEERING.md`。

## 1. 会话握手

```bash
curl -s -c cookies.txt https://mjj.today/ -o page.html
grep -o 'auth_token = "[a-f0-9]*"' page.html
# → PF.obj.config.auth_token = "cc91e2dc…d75"
# 同时 Set-Cookie: PHPSESSID=…      ← 这一对必须配对使用
```

- `auth_token`：首页内联脚本 `PF.obj.config.auth_token`，40 位 hex，**每会话不同**，与 `PHPSESSID` 绑定
- 令牌在同一会话内**可复用**（连续多次上传均 200），无需每次重新握手
- 缺令牌 / 伪造令牌 → `500 {"message":"请求被拒绝 (401)"}`

## 2. 上传：`POST /json`

`Content-Type: multipart/form-data`，头部带 `Accept: application/json`、`Origin`、`Referer` 即可。

| 字段 | 必填 | 值 |
|---|---|---|
| `source` | ✅ | 文件二进制；`filename=` 用真实文件名，`Content-Type` 用图片 MIME |
| `type` | ✅ | `file` |
| `action` | ✅ | `upload` |
| `auth_token` | ✅ | 见上 |
| `timestamp` | ❌ | 毫秒时间戳（网页端 `(new Date).getTime()`，实测省掉也是 200） |
| `expiration` | ❌ | `""` 或 ISO-8601 duration |
| `nsfw` | ❌ | `0` / `1` |
| `privacy` | ❌ | `public`。**`private` → 500**（游客不允许私密上传） |
| `title` / `description` | ❌ | UTF-8 中文正常回显 |
| `category_id` / `album_id` | ❌ | 游客场景用不上 |

`expiration` 合法值（网页 select 全量）：
`""` `PT5M` `PT15M` `PT30M` `PT1H` `PT3H` `PT6H` `PT12H` `P1D` `P2D` `P3D` `P4D` `P5D` `P6D` `P1W` `P2W` `P3W` `P1M` `P2M` `P3M` `P4M` `P5M` `P6M` `P1Y`
（传秒数 `300` 会被接受但忽略，`expiration_date_gmt` 保持 `null`）

字段名出处 —— 站点 `chevereto.min.js` 压缩包 offset ≈ 75429，明码常量：

```js
d = { source: null, type: n ? "url" : "file", action: "upload",
      privacy: $("[data-privacy]", root).first().data("privacy"),
      timestamp: this.timestamp, auth_token: PF.obj.config.auth_token,
      expiration: $("[name=upload-expiration]").val() || "",
      category_id: …, nsfw: …?1:0, album_id: … };
n ? d.source = s : l.append("source", s, i.name);
xhr.open("POST", PF.obj.config.json_api, true);            // "/json"
xhr.setRequestHeader("Accept", "application/json");
```

## 3. 响应

```json
{"status_code":200,"success":{"message":"image uploaded","code":200},
 "image":{"id_encoded":"QyuPCh0",
   "url":"https://i.mji.rip/2026/10/13/<md5>.png",          // CDN 直链
   "url_viewer":"https://mjj.today/i/QyuPCh0",              // 信息页
   "thumb":{"url":"…/<md5>.th.png"},                        // 缩略图
   "delete_url":"https://mjj.today/i/QyuPCh0/delete/<64hex>",
   "filename":"<md5>.png","mime":"image/png","extension":"png",
   "size":5254,"width":"64","height":"64","md5":"37367cd8…",
   "storage_mode":"datefolder","expiration_date_gmt":null,
   "is_approved":"1","views":"0","likes":"0"},
 "request":{"type":"file","action":"upload","nsfw":"0","expiration":""},
 "status_txt":"OK"}
```

错误统一形状：`{"status_code":500,"error":{"message":"…","code":401,"id":"<incident>"}}`。

**CDN 跳转**：`image.url` 给的 `https://i.mji.rip/<date>/<md5>.png` 是跳转域名，
`301 → https://i.mij.rip/<date>/<md5>.png`（真身，注意 `mji` / `mij` 之别）。
浏览器与 Markdown 渲染器自动跟随；不跟随 301 的下游程序请直接用 `i.mij.rip` 主机名。

## 4. 探针矩阵（全部实测）

| 输入 | 结果 |
|---|---|
| 正常 file 上传 | `200` ✅ |
| 同会话连传两次 | 两次 `200` ✅ |
| 不带 `auth_token` | `500 请求被拒绝 (401)` |
| 伪造 `auth_token` | `500 请求被拒绝 (401)` |
| 不带 `timestamp` / 不带 `privacy` | `200`（均可选） |
| `type=url`（站内图片 URL） | `500 URL uploading is disabled (403)` |
| `type=base64` | `500 TypeError` |
| `privacy=private` | `500`（通用报错） |
| `.txt` 伪装图片 | `500 ⭕️ Something went wrong • Incident ID:…`（无细节） |
| 11 MB PNG | 同上（无细节 → 必须本地预检 10 MB） |
| `POST /api/1/upload` 无 key | `400 {"message":"No key provided","code":100}` |
| `POST /api/1/upload` 假 key | `400 {"message":"Invalid guest API key.","code":100}` |

站点自报限制（首页 `CHV.obj.config`）：
`image.max_filesize = "10 MB"`，`upload.image_types = ["jpg","jpeg","png","bmp","gif","webp"]`，
`upload.threads = "5"`，`upload.url = false`，`captcha.isNeeded = false`。

## 5. 删除

`delete_url` 为一次性凭据（只在上传响应中出现）：

```
GET https://mjj.today/i/<id>/delete/<64hex>
 → 404 且 URL 落到 https://mjj.today/i/<id>/?deleted   ← 删除成功（404 是预期行为）
 → 复查信息页 https://mjj.today/i/<id> ：404            ← 已确认删除
```

CDN 直链因 Cloudflare 边缘缓存可能短时间仍返回 200。

## 6. 换成自建 Chevereto 时的再推导顺序

1. 首页找 `PF.obj.config.auth_token` / `PF.obj.config.json_api`；
2. 首页 `CHV.obj.config.*` 看限额、白名单、验证码开关；
3. 站点 JS 搜 `new FormData` → 紧随的字段对象即协议（Chevereto 官方包未混淆这段）；
4. curl 打通后把字段同步进 `mjj_upload.py` 的 `upload_file()`。
