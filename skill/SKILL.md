---
name: mjj-image-host
description: 用 mjj.today 图床做命令行图片上传/外链生成。当用户要"上传图片拿外链""图床""把截图传上去""生成 Markdown 图片链接""mjj.today 上传"时使用。已逆向其 Chevereto 4 上传接口 (POST /json)，带纯标准库 Python CLI，支持批量并发、Markdown/BBCode 输出、定时自动删除、删除回滚。同样适用于任何自建 Chevereto 站点 (--base-url)。
---

# mjj.today 图床上传

mjj.today（Chevereto 4.0.8）网页上传器的接口已逆向下游，封装成纯标准库 CLI：
**不需要登录、不需要浏览器、不需要 pip install**。

## ACTION REQUIRED（读完立刻执行）

1. `NOW`：确认要传的文件路径存在（缺路径就问用户要，别猜）。
2. `ACT`：直接跑脚本，别先讲原理：

```bash
SD=$HOME/.dsh/skills/mjj-image-host/scripts
python3 "$SD/mjj_upload.py" 图片1.png 图片2.jpg            # 直链，一行一个
python3 "$SD/mjj_upload.py" -f markdown *.png              # Markdown
python3 "$SD/mjj_upload.py" -f all shot.png                # 直链/缩略图/信息页/删除页/两种代码
python3 "$SD/mjj_upload.py" - < screenshot.png             # 从 stdin 读二进制
python3 "$SD/mjj_upload.py" -e PT1D a.png                  # 1 天后自动删
python3 "$SD/mjj_upload.py" --list 10                      # 本地历史
python3 "$SD/mjj_upload.py" --delete <id或URL>              # 删除
```

3. `NEXT`：把脚本 stdout 的直链**原样**给用户（别改写 URL）。
4. `NEXT`：报错按下面「错误对照表」处置，不要重试超过一次。

## 核心协议（逆向结论，别再重新抓包）

`POST https://mjj.today/json`，`multipart/form-data`：

| 字段 | 值 |
|---|---|
| `source` | 文件二进制（字段名就是 `source`） |
| `type` | `file` |
| `action` | `upload` |
| `auth_token` | 首页内联 `PF.obj.config.auth_token`，**与 `PHPSESSID` 绑定** |
| `timestamp` | 毫秒时间戳（可省） |
| `expiration` | `""` 或 `PT5M`/`PT1H`/`P1D`/`P1W`/`P1M`/`P1Y` |
| `nsfw` | `0`/`1` |
| `privacy` | `public`（**`private` 会 500**） |
| `title`/`description` | 可选，UTF-8 中文 OK |

成功返回 `image.url`（CDN 直链）、`image.url_viewer`（信息页）、`image.thumb.url`、`image.delete_url`。
限额：单文件 **10 MB**，`jpg/jpeg/png/bmp/gif/webp`；无验证码。
禁用路径：`type=url` 与 `type=base64` 都是 500；`/api/1/upload` 需要账号自己的 key（`--api-key`）。

完整字段表、请求/响应原文、全部探针结果见 `references/protocol.md`；
带抓包与探针矩阵的完整逆向记录见仓库 `docs/REVERSE-ENGINEERING.md`。

## 错误对照表

| 现象 | 处置 |
|---|---|
| `请求被拒绝 (401)` | 会话过期 —— 脚本已自动重握手重试一次；仍失败加 `--refresh-session` |
| `⭕️ Something went wrong • Incident ID:` | 服务端通用错：体积超 10 MB / 格式不在白名单 / 传了 `private` |
| `URL uploading is disabled (403)` | `type=url` 被站点关闭，只能传本地文件 |
| `No key provided` | 走了 `--api-key` 但没给 key；去掉该参数走会话通道 |
| 删除后 CDN 直链还能打开 | Cloudflare 边缘缓存，信息页 404 即为删除成功 |
| 下游程序拿 `i.mji.rip` 直链报错 | 该域名 `301 → i.mij.rip`（真身）；不跟随跳转的程序请换成 `i.mij.rip` |
| 删除报「找不到 delete_url」 | `delete_url` 只在上传响应里给一次，本地历史在 `~/.cache/mjj-uploader/history.jsonl` |

## 状态文件

| 路径 | 内容 |
|---|---|
| `~/.cache/mjj-uploader/session.json` | `PHPSESSID` + `auth_token` 缓存（0600），失效自动续 |
| `~/.cache/mjj-uploader/history.jsonl` | 每次上传的 id / 直链 / 信息页 / delete_url |

清缓存：`rm -rf ~/.cache/mjj-uploader`（下次运行自动重新握手）。
可用 `MJJ_CACHE_DIR` 环境变量改目录。

## 站点改版 / 换站（自建 Chevereto）

`--base-url https://your-chevereto/` 即可复用；若字段变了，按这套顺序重新推导：

1. `curl -s <base>/ | grep -o 'auth_token = "[a-f0-9]*"'` —— 令牌还在不在首页内联脚本里。
2. 页面源码找 `PF.obj.config.json_api`（接口路径）、`CHV.obj.config.upload.image_types`（白名单）、
   `CHV.obj.config.captcha.isNeeded`（有没有验证码）。
3. 站点 JS 里搜 `new FormData`，紧跟的 `{source, type, action, ...}` 对象就是字段表
   （Chevereto 官方压缩包里这段是明码常量，不用去混淆）。
4. 用 curl 按新字段跑一次，再改脚本 `upload_file()` 里的 `fields`。
