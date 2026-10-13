<div align="center">

# mjj-upload

**mjj.today 图床的命令行上传器** — 纯标准库 Python，无需登录、无需浏览器、无需 `pip install`

[![CI](https://github.com/zhaoruizhe81/mjj-upload/actions/workflows/ci.yml/badge.svg)](https://github.com/zhaoruizhe81/mjj-upload/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B%20tested-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](#)

</div>

```console
$ mjj photo.png
https://i.mji.rip/2026/10/13/10a8418643f6e72d22774bb9a113db38.png

$ mjj -f markdown shot.jpg
![shot.jpg](https://i.mji.rip/2026/10/13/d1eaad72ca864182fd964a9b43b4b914.png)

$ mjj - < screenshot.png          # 截图直接管道进来
https://i.mji.rip/2026/10/13/384b25a13cada76f86b19d133636ca9b.png
```

---

## 这是什么

[mjj.today](https://mjj.today/) 是个免费图床（后端是 **Chevereto 4**）。它只有网页上传，写文档、发帖、贴截图时每次都要开浏览器拖一次，很烦。

这个项目把它网页上传器的接口逆了出来（`POST /json`），做成一个**可以直接在终端里用**的脚本：

- **零依赖** —— 只用 Python 标准库（`urllib` + 手搓 multipart），不装 `requests` 也能跑
- **零配置** —— 首次运行自动握手拿会话，之后缓存在本地，失效自动续期
- **批量并发** —— 默认 5 线程（与网页端一致），几条命令传一堆图
- **直接出你要的格式** —— 直链 / Markdown / 带缩略图的 Markdown / BBCode / HTML / JSON
- **能撤销** —— 上传返回的删除凭据存进本地历史，事后 `mjj --delete <id>` 删掉
- **不止 mjj.today** —— `--base-url` 指向任何自建 Chevereto 4 站点一样用

## 安装

**方式一：直接用（推荐）**

```bash
git clone https://github.com/zhaoruizhe81/mjj-upload.git
cd mjj-upload
./mjj_upload.py --help

# 想在任何目录都能敲 `mjj`：
mkdir -p ~/.local/bin
ln -sf "$PWD/mjj_upload.py" ~/.local/bin/mjj     # 确保 ~/.local/bin 在 PATH 里
```

**方式二：单文件**

就一个 `mjj_upload.py`，`curl` 下来加个执行位就能用，没有任何其他文件依赖。

**方式三：装成 dsh / Claude 技能**

```bash
./skill/install.sh              # 安装到 ~/.dsh/skills/mjj-image-host/
./skill/install.sh --link       # 软链方式（改代码即时生效，适合开发）
./skill/install.sh --uninstall  # 卸载
```

装完 AI 助手在你说「上传这张图拿外链」时会自动用上它。技能说明见 [`skill/SKILL.md`](skill/SKILL.md)。

## 用法

```
用法: mjj_upload.py [选项] 图片路径...

  -f, --format {url,markdown,markdown-thumb,bbcode,html,json,all}   输出格式（默认 url）
  -e, --expiration ISO8601    自动删除时长: PT5M PT1H P1D P1W P1M P1Y（默认不删）
  -t, --title / -d, --description     标题 / 描述
  -n, --nsfw {0,1}            标记敏感图
  -j, --jobs N                并发数（默认 5）
      --timeout S             单请求超时（默认 60）
      --max-size MB           本地体积预检（默认 10）
      --base-url URL          换站点（默认 https://mjj.today）
      --api-key KEY           改走官方 /api/1/upload（需自己的 key）
  -o, --output FILE           结果同时追加写入文件
  -q, --quiet                 多文件时不加 "# 文件名" 注释行
      --refresh-session       强制重新握手
      --no-cache              不用本地会话缓存
      --json-errors           失败时输出 JSON 错误对象
      --list [N]              看本地上传历史
      --delete ID|URL         删除（id_encoded / 信息页 URL / delete_url）
```

文件参数支持 `-`，表示从 **stdin** 读二进制 —— 配合 `screencapture`、`pngpaste` 之类非常顺手。

**退出码**：`0` 至少一张成功；`1` 全部失败；`2` 参数错误。

### 十几个实际场景

```bash
# 批量传一整个目录，出 Markdown 列表
mjj -f markdown -j 8 shots/*.png > album.md

# 传完直接写进剪贴板（macOS）
mjj shot.png | pbcopy

# 截图 → 直链，一步到位
screencapture -i -c && pbpaste > /tmp/s.png && mjj /tmp/s.png

# 临时图，1 天后自动删
mjj -e PT1D 临时凭证.png

# 传一整套，把直链存文件
mjj -q *.jpg -o urls.txt

# 事后反悔
mjj --list 20
mjj --delete QyugSqw

# 自建 Chevereto 也能用
mjj --base-url https://img.example.com -f bbcode a.png
```

`examples/` 里还有几个可以直接抄的小脚本。

## 输出格式对照

| `-f` | 结果 |
|---|---|
| `url`（默认） | `https://i.mji.rip/2026/10/13/xxx.png` |
| `markdown` | `![name.png](https://...)` |
| `markdown-thumb` | `[![name.png](缩略图)](信息页)` |
| `bbcode` | `[img]https://...[/img]` |
| `html` | `<img src="https://..." alt="name.png">` |
| `json` | 接口返回的完整 `image` 对象 |
| `all` | 直链 / 缩略图 / 信息页 / 删除页 / Markdown / BBCode 一次给全 |

## 本地状态

| 路径 | 内容 | 清除 |
|---|---|---|
| `~/.cache/mjj-uploader/session.json` | `PHPSESSID` + `auth_token`（权限 `0600`），失效自动重握手 | `rm -rf ~/.cache/mjj-uploader` |
| `~/.cache/mjj-uploader/history.jsonl` | 每次上传的 id / 直链 / 信息页 / `delete_url`，`--list` 与 `--delete` 都靠它 | 同上 |

可用环境变量 `MJJ_CACHE_DIR` 换目录。

> 登录状态（401）时脚本会**自动重新握手并重试一次**，正常使用不会感知到中断。

## 站点限制（实测）

| 项目 | 值 |
|---|---|
| 单文件体积 | **10 MB** |
| 允许格式 | `jpg` `jpeg` `png` `bmp` `gif` `webp` |
| 验证码 | 无 |
| 上传并发 | 网页端 5 线程 |
| 远程 URL 拉图（`type=url`） | **已关闭**（`403 URL uploading is disabled`） |
| base64 上传 | 不支持 |
| 私密上传（`privacy=private`） | 游客会 500 |

超限或格式不对时，服务端只回一句通用错误（`⭕️ Something went wrong • Incident ID:...`），所以脚本本地就先做体积/后缀预检，给出的提示更有用。

## 常见问题

**Q：链接里 `i.mji.rip` 和 `i.mij.rip` 是同一个吗？**
是同一个 CDN，接口返回 `i.mji.rip`，它会 `301 → i.mij.rip`（真身）。浏览器和 Markdown 渲染器都会自动跟随；如果你的下游程序不跟随跳转，把主机名换成 `i.mij.rip` 即可。

**Q：为什么不走官方 API `POST /api/1/upload`？**
那个端点开着，但需要账号自己的 API key（在站点 `/settings/api` 生成）。有 key 的话直接 `mjj --api-key YOUR_KEY`，脚本支持这条路径。

**Q：需要注册账号吗？**
不需要。走的是网页游客上传通道，`auth_token` 是按会话下发的。

**Q：图被删了直链还能打开？**
Cloudflare 边缘缓存，短时间仍可能 200；以信息页 `https://mjj.today/i/<id>` 返回 404 为准。

**Q：会不会被滥用限速？**
脚本内置 5 并发、失败即退出，不做重试轰炸。

## 逆向细节

接口协议、字段表、抓包原文与 12 项探针矩阵见 **[docs/REVERSE-ENGINEERING.md](docs/REVERSE-ENGINEERING.md)**；速查版见 [`skill/references/protocol.md`](skill/references/protocol.md)。

一句话版本：`POST https://mjj.today/json`，`multipart/form-data`，字段 `source`(文件) + `type=file` + `action=upload` + `auth_token`(取自首页内联脚本，与 `PHPSESSID` 绑定) + `expiration` + `nsfw`。

## 说明

- 接口来自目标站点的公开前端，**非官方 API**，站点改版或封禁可能随时失效；文末的「再推导流程」写了怎么修。
- 请把它用在自用、小规模的场景，并遵守目标站点的使用条款。
- 本项目仅供学习与个人效率使用，不对上传内容的合规性负责。

## 开发

```bash
python -m unittest discover -s tests -v     # 离线单测（不联网）
MJJ_LIVE_TEST=1 python -m unittest discover -s tests -v   # 追加一次真实上传+删除
```

代码全部在 `mjj_upload.py` 一个文件里，分四段：会话握手 → multipart 编码 → 上传/删除 → CLI。

站点改版后的再推导流程（三步）：

1. `curl -s https://mjj.today/ | grep -o 'auth_token = "[a-f0-9]*"'` —— 令牌还在首页内联脚本里吗
2. 页面源码找 `PF.obj.config.json_api`（接口路径）、`CHV.obj.config.upload.image_types`（白名单）、`CHV.obj.config.captcha.isNeeded`（验证码）
3. 站点 JS 里搜 `new FormData`，紧随的 `{source, type, action, ...}` 对象就是字段表；curl 打通后改 `upload_file()` 里的 `fields`

## License

[MIT](LICENSE) © 2026 赵瑞哲 ([@zhaoruizhe81](https://github.com/zhaoruizhe81))

---

<details>
<summary><b>English</b></summary>

**mjj-upload** is a zero-dependency Python CLI for uploading images to [mjj.today](https://mjj.today/) (a Chevereto 4 image host).

The web uploader's `POST /json` endpoint was reverse engineered, so you get a plain terminal workflow:
batch upload with concurrency, copy-paste-ready Markdown/BBCode links, optional auto-expiry, and a local history
that lets you delete an upload afterwards.

```bash
git clone https://github.com/zhaoruizhe81/mjj-upload.git && cd mjj-upload
./mjj_upload.py -f markdown *.png        # markdown links
./mjj_upload.py - < shot.png             # read from stdin
./mjj_upload.py --list 10                # history
./mjj_upload.py --delete <id>            # delete
```

Standard library only (Python 3.9+, tested on 3.9 & 3.13). No account required — it reuses the guest upload session
(`PHPSESSID` + a session-bound `auth_token` scraped from the homepage). `--base-url` points it at any
self-hosted Chevereto instance.

Protocol details: [docs/REVERSE-ENGINEERING.md](docs/REVERSE-ENGINEERING.md). MIT licensed.

</details>
