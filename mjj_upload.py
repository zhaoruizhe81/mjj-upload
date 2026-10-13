#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mjj_upload.py — mjj.today 图床命令行上传工具 (纯标准库, 无需 pip install)

逆向自 https://mjj.today/ 前端上传器 (Chevereto 4.0.8 / Peafowl 主题)。
上游接口: POST /json  (multipart/form-data)

    source      <文件>            图片二进制; 字段名固定为 source
    type        file
    action      upload
    auth_token  <会话令牌>         取自首页内联脚本 PF.obj.config.auth_token
    timestamp   <毫秒时间戳>
    expiration  ""|PT5M|PT1H|P1D  空=不自动删除 (ISO-8601 duration)
    nsfw        0|1
    privacy     public            不要传 private (游客会 500)
    title/description 可选

会话: 同时必须携带首页拿到的 PHPSESSID Cookie, auth_token 与该会话绑定。

用法:
    ./mjj_upload.py a.png b.jpg
    ./mjj_upload.py -f markdown *.png
    ./mjj_upload.py --expiration PT1D --nsfw 1 shot.png
    ./mjj_upload.py --list 10
    ./mjj_upload.py --delete QyuPCh0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DEFAULT_BASE = "https://mjj.today"
JSON_PATH = "/json"
API_PATH = "/api/1/upload"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

ALLOWED_EXT = {"jpg", "jpeg", "png", "bmp", "gif", "webp"}
MAX_SIZE_MB = 10.0
CACHE_DIR = Path(os.environ.get("MJJ_CACHE_DIR", Path.home() / ".cache" / "mjj-uploader"))
SESSION_FILE = CACHE_DIR / "session.json"
HISTORY_FILE = CACHE_DIR / "history.jsonl"

TOKEN_RE = re.compile(r"""auth_token\s*=\s*["']([0-9a-fA-F]{16,})["']""")
ID_RE = re.compile(r"/i/([A-Za-z0-9]+)")
API_KEY_RE = re.compile(r"""(?:api[_-]?key|key)\s*[:=]\s*["']([A-Za-z0-9]{16,})["']""", re.I)


class UploadError(RuntimeError):
    """接口返回的业务错误。"""

    def __init__(self, message: str, code: int | None = None, status: int | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


# --------------------------------------------------------------------------- #
# 会话
# --------------------------------------------------------------------------- #
class Session:
    """一个 PHPSESSID + auth_token 的组合, 会缓存在本地并自动续期。"""

    def __init__(self, base: str, timeout: int = 60, use_cache: bool = True):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.use_cache = use_cache
        self.cookie = ""
        self.token = ""
        self._loaded_from_cache = False

    # -- 持久化 ------------------------------------------------------------- #
    def load(self) -> bool:
        if not self.use_cache or not SESSION_FILE.exists():
            return False
        try:
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except Exception:
            return False
        if data.get("base") != self.base or not data.get("cookie") or not data.get("token"):
            return False
        self.cookie, self.token = data["cookie"], data["token"]
        self._loaded_from_cache = True
        return True

    def save(self) -> None:
        if not self.use_cache:
            return
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(json.dumps({
            "base": self.base, "cookie": self.cookie, "token": self.token,
            "saved_at": int(time.time()),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            SESSION_FILE.chmod(0o600)
        except OSError:
            pass

    # -- 握手 --------------------------------------------------------------- #
    def refresh(self) -> None:
        """GET / -> 取 PHPSESSID + 内联脚本里的 auth_token。"""
        req = urllib.request.Request(self.base + "/", headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                html = resp.read().decode("utf-8", "replace")
                set_cookie = resp.headers.get_all("Set-Cookie") or []
        except urllib.error.HTTPError as exc:
            raise UploadError(f"握手失败: HTTP {exc.code} ({self.base}/)", status=exc.code) from exc
        except OSError as exc:
            raise UploadError(f"握手失败: {exc}") from exc

        cookie = ""
        for c in set_cookie:
            m = re.match(r"\s*(PHPSESSID=[^;]+)", c)
            if m:
                cookie = m.group(1)
                break
        if not cookie:
            raise UploadError("握手失败: 响应里没有 PHPSESSID")
        m = TOKEN_RE.search(html)
        if not m:
            raise UploadError("握手失败: 首页里找不到 auth_token (页面结构可能已变)")
        self.cookie, self.token = cookie, m.group(1)
        self.save()

    def ensure(self) -> None:
        if not self.cookie or not self.token:
            if not self.load():
                self.refresh()

    def invalidate(self) -> None:
        self.cookie = self.token = ""
        try:
            SESSION_FILE.unlink()
        except OSError:
            pass

    # -- HTTP --------------------------------------------------------------- #
    def open(self, req: urllib.request.Request, timeout: int | None = None):
        if self.cookie:
            req.add_header("Cookie", self.cookie)
        return urllib.request.urlopen(req, timeout=timeout or self.timeout)


# --------------------------------------------------------------------------- #
# multipart 编码 (标准库手搓, 与浏览器一致)
# --------------------------------------------------------------------------- #
def encode_multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]):
    boundary = "----WebKitFormBoundary" + uuid.uuid4().hex[:16]
    buf = bytearray()
    for name, value in fields.items():
        buf += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n".encode()
        buf += str(value).encode("utf-8")
        buf += b"\r\n"
    for name, (filename, data, ctype) in files.items():
        buf += (f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {ctype}\r\n\r\n").encode("utf-8")
        buf += data
        buf += b"\r\n"
    buf += f"--{boundary}--\r\n".encode()
    return boundary, bytes(buf)


def guess_type(path: Path) -> str:
    ctype = mimetypes.guess_type(path.name)[0]
    if ctype and ctype.startswith("image/"):
        return ctype
    return {
        "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
        "gif": "image/gif", "bmp": "image/bmp", "webp": "image/webp",
    }.get(path.suffix.lower().lstrip("."), "application/octet-stream")


# --------------------------------------------------------------------------- #
# 上传
# --------------------------------------------------------------------------- #
def parse_error(payload, status: int) -> UploadError:
    err = (payload or {}).get("error") or {}
    msg = err.get("message") or f"HTTP {status} 未返回有效 JSON"
    return UploadError(msg, code=err.get("code"), status=status)


def upload_file(session: Session, path: Path, *, expiration: str = "", nsfw: int = 0,
                title: str | None = None, description: str | None = None,
                retry: bool = True, max_size_mb: float = MAX_SIZE_MB) -> dict:
    """上传单个文件, 返回接口的 image 字典 (附带本地 file 信息)。"""
    path = Path(path).expanduser()
    if not path.is_file():
        raise UploadError(f"文件不存在: {path}")
    ext = path.suffix.lower().lstrip(".")
    if ext not in ALLOWED_EXT:
        raise UploadError(f"不支持的扩展名 .{ext} (仅 {', '.join(sorted(ALLOWED_EXT))})")
    size = path.stat().st_size
    if max_size_mb and size > max_size_mb * 1024 * 1024:
        raise UploadError(f"文件 {size / 1048576:.2f} MB 超过站点上限 {max_size_mb:g} MB")

    data = path.read_bytes()
    fields = {
        "type": "file",
        "action": "upload",
        "privacy": "public",
        "timestamp": str(int(time.time() * 1000)),
        "auth_token": session.token,
        "expiration": expiration or "",
        "nsfw": str(1 if nsfw else 0),
    }
    if title:
        fields["title"] = title
    if description:
        fields["description"] = description
    files = {"source": (path.name, data, guess_type(path))}

    session.ensure()
    fields["auth_token"] = session.token
    boundary, body = encode_multipart(fields, files)
    req = urllib.request.Request(session.base + JSON_PATH, data=body, headers={
        "User-Agent": UA,
        "Accept": "application/json",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Origin": session.base,
        "Referer": session.base + "/",
    })

    try:
        with session.open(req) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except OSError as exc:
        raise UploadError(f"网络错误: {exc}") from exc

    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        if retry:
            session.refresh()
            return upload_file(session, path, expiration=expiration, nsfw=nsfw, title=title,
                               description=description, retry=False, max_size_mb=max_size_mb)
        raise UploadError(f"HTTP {status}: 响应不是 JSON") from None

    err = payload.get("error") or {}
    if err.get("code") in (401, 403) and retry:
        session.invalidate()
        session.refresh()
        return upload_file(session, path, expiration=expiration, nsfw=nsfw, title=title,
                           description=description, retry=False, max_size_mb=max_size_mb)
    if payload.get("status_code") != 200 or "image" not in payload:
        raise parse_error(payload, status)

    image = payload["image"]
    image["_local"] = {
        "file": str(path.resolve()), "size": size,
        "md5": hashlib.md5(data).hexdigest(),
    }
    record_history(image)
    return image


def upload_via_api_key(session: Session, path: Path, api_key: str, *, expiration: str = "",
                       nsfw: int = 0, title: str | None = None,
                       max_size_mb: float = MAX_SIZE_MB) -> dict:
    """官方 API v1: POST /api/1/upload (需登录后在 /settings/api 生成 key)。

    实测 mjj.today 的该端点已开启, 无 key 时返回 {"message":"No key provided"}。
    """
    path = Path(path).expanduser()
    if not path.is_file():
        raise UploadError(f"文件不存在: {path}")
    size = path.stat().st_size
    if max_size_mb and size > max_size_mb * 1024 * 1024:
        raise UploadError(f"文件 {size / 1048576:.2f} MB 超过站点上限 {max_size_mb:g} MB")
    data = path.read_bytes()
    fields = {"key": api_key, "action": "upload", "format": "json"}
    if expiration:
        fields["expiration"] = expiration
    if nsfw:
        fields["nsfw"] = "1"
    if title:
        fields["title"] = title
    boundary, body = encode_multipart(fields, {"source": (path.name, data, guess_type(path))})
    req = urllib.request.Request(session.base + API_PATH, data=body, headers={
        "User-Agent": UA,
        "Accept": "application/json",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    try:
        with urllib.request.urlopen(req, timeout=session.timeout) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except OSError as exc:
        raise UploadError(f"网络错误: {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        raise UploadError(f"HTTP {status}: 响应不是 JSON") from None
    if payload.get("status_code") != 200 or "image" not in payload:
        raise parse_error(payload, status)
    image = payload["image"]
    image["_local"] = {"file": str(path.resolve()), "size": size,
                       "md5": hashlib.md5(data).hexdigest()}
    record_history(image)
    return image


# --------------------------------------------------------------------------- #
# 历史 / 删除
# --------------------------------------------------------------------------- #
def record_history(image: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": int(time.time()),
            "id": image.get("id_encoded"),
            "url": image.get("url"),
            "viewer": image.get("url_viewer"),
            "thumb": (image.get("thumb") or {}).get("url"),
            "delete_url": image.get("delete_url"),
            "filename": image.get("filename"),
            "original_filename": image.get("original_filename"),
            "size": image.get("size"),
        }
        with HISTORY_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        try:
            HISTORY_FILE.chmod(0o600)
        except OSError:
            pass
    except OSError:
        pass


def read_history(limit: int | None = None) -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    rows = []
    for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows[-limit:] if limit else rows


def resolve_delete_url(session: Session, target: str) -> str:
    """target 可以是 delete_url / 信息页 URL / id_encoded。"""
    if target.startswith("http") and "/delete/" in target:
        return target
    rows = read_history()
    key = target.rstrip("/").split("/")[-1] if target.startswith("http") else target
    if target.startswith("http"):
        m = ID_RE.search(target)
        key = m.group(1) if m else key
    for row in reversed(rows):                       # 1) 精确匹配 id
        if row.get("id") == key and row.get("delete_url"):
            return row["delete_url"]
    hits = [r["delete_url"] for r in rows
            if r.get("delete_url") and (r.get("id") or "").startswith(key)]
    if len(set(hits)) == 1:                          # 2) 唯一前缀匹配
        return hits[0]
    if len(set(hits)) > 1:                           # 3) 多个候选, 让用户说清楚
        ids = sorted({r.get("id") for r in rows if (r.get("id") or "").startswith(key)})
        raise UploadError(f"{key} 匹配到多个 id: {', '.join(ids)}")
    raise UploadError(f"本地历史里找不到 {key} 的 delete_url (删除链接只在上传时返回一次)")


def delete_image(session: Session, target: str) -> str:
    url = resolve_delete_url(session, target)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html,application/xhtml+xml",
        "Referer": session.base + "/",
    })
    try:
        with session.open(req) as resp:
            body, status = resp.read().decode("utf-8", "replace"), resp.status
            final = resp.url
    except urllib.error.HTTPError as exc:
        body, status, final = exc.read().decode("utf-8", "replace"), exc.code, exc.url
    except OSError as exc:
        raise UploadError(f"网络错误: {exc}") from exc
    if "deleted" in final or "deleted" in body or "已删除" in body:
        return final
    raise UploadError(f"删除未生效 (HTTP {status}) — 链接可能已过期或图片已被删")


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
def render(image: dict, fmt: str) -> str:
    url = image.get("url") or ""
    thumb = (image.get("thumb") or {}).get("url") or url
    viewer = image.get("url_viewer") or url
    name = image.get("original_filename") or image.get("filename") or "image"
    if fmt == "url":
        return url
    if fmt == "markdown":
        return f"![{name}]({url})"
    if fmt == "markdown-thumb":
        return f"[![{name}]({thumb})]({viewer})"
    if fmt == "bbcode":
        return f"[img]{url}[/img]"
    if fmt == "html":
        return f'<img src="{url}" alt="{name}">'
    if fmt == "json":
        return json.dumps(image, ensure_ascii=False, indent=2)
    if fmt == "all":
        return (f"直链    : {url}\n"
                f"缩略图  : {thumb}\n"
                f"信息页  : {viewer}\n"
                f"删除页  : {image.get('delete_url', '-')}\n"
                f"Markdown: ![{name}]({url})\n"
                f"BBCode  : [img]{url}[/img]")
    raise UploadError(f"未知格式: {fmt}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mjj_upload.py",
        description="mjj.today 图床上传 (逆向自 POST /json)",
        epilog="示例: mjj_upload.py -f markdown *.png",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("files", nargs="*", help="图片路径 (可多个; 支持 - 表示从 stdin 读二进制)")
    p.add_argument("-f", "--format", default="url",
                   choices=["url", "markdown", "markdown-thumb", "bbcode", "html", "json", "all"],
                   help="输出格式, 默认 url")
    p.add_argument("-e", "--expiration", default="", metavar="ISO8601",
                   help="自动删除时长: PT5M PT1H P1D P1W P1M P1Y ... (默认不删除)")
    p.add_argument("-t", "--title", default=None, help="图片标题")
    p.add_argument("-d", "--description", default=None, help="图片描述")
    p.add_argument("-n", "--nsfw", type=int, default=0, choices=[0, 1], help="标记敏感图片")
    p.add_argument("-j", "--jobs", type=int, default=5, help="并发数, 默认 5")
    p.add_argument("--timeout", type=int, default=60, help="单请求超时秒数, 默认 60")
    p.add_argument("--base-url", default=DEFAULT_BASE, help=f"站点地址, 默认 {DEFAULT_BASE}")
    p.add_argument("--api-key", default=None, help="走官方 /api/1/upload (需自己的 key)")
    p.add_argument("--max-size", type=float, default=MAX_SIZE_MB, help="本地体积预检 MB, 默认 10")
    p.add_argument("--output", "-o", default=None, help="把结果追加写入文件 (每行一条)")
    p.add_argument("--refresh-session", action="store_true", help="强制重新握手, 丢弃缓存会话")
    p.add_argument("--no-cache", action="store_true", help="不使用本地会话缓存")
    p.add_argument("--quiet", "-q", action="store_true", help="只输出结果, 不要过程信息")
    p.add_argument("--list", nargs="?", type=int, const=10, default=None, metavar="N",
                   help="列出本地历史最近 N 条上传")
    p.add_argument("--delete", metavar="ID|URL", default=None,
                   help="删除: 传 id_encoded / 信息页 URL / delete_url")
    p.add_argument("--json-errors", action="store_true", help="失败时输出 JSON 错误对象")
    return p


def read_stdin_image() -> Path:
    import tempfile
    data = sys.stdin.buffer.read()
    if not data:
        raise UploadError("stdin 没有数据")
    tmp = Path(tempfile.gettempdir()) / f"mjj-stdin-{uuid.uuid4().hex[:8]}.png"
    tmp.write_bytes(data)
    return tmp


def cmd_list(limit: int) -> int:
    rows = read_history(limit)
    if not rows:
        print("(本地历史为空)", file=sys.stderr)
        return 0
    for row in rows:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(row.get("ts", 0)))
        print(f"{when}  {row.get('id', '-'):<10} {row.get('url', '-')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list is not None:
        return cmd_list(args.list)

    session = Session(args.base_url, timeout=args.timeout, use_cache=not args.no_cache)
    try:
        if args.refresh_session:
            session.refresh()

        if args.delete:
            session.ensure()
            final = delete_image(session, args.delete)
            print(f"已删除 → {final}")
            return 0

        if not args.files:
            build_parser().print_help()
            return 2

        paths: list[Path] = []
        for item in args.files:
            if item == "-":
                paths.append(read_stdin_image())
            else:
                paths.append(Path(item).expanduser())

        for p in paths:
            if not p.is_file():
                raise UploadError(f"文件不存在: {p}")

        session.ensure()

        def work(p: Path):
            if args.api_key:
                return p, upload_via_api_key(session, p, args.api_key,
                                             expiration=args.expiration, nsfw=args.nsfw,
                                             title=args.title, max_size_mb=args.max_size), None
            return p, upload_file(session, p, expiration=args.expiration, nsfw=args.nsfw,
                                  title=args.title, description=args.description,
                                  max_size_mb=args.max_size), None

        results, failures = [], []
        if len(paths) == 1 or args.jobs <= 1:
            for p in paths:
                try:
                    _, image, _ = work(p)
                    results.append((p, image))
                except UploadError as exc:
                    failures.append((p, exc))
        else:
            with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
                for p, image, err in pool.map(lambda q: _safe(work, q), paths):
                    (results if err is None else failures).append(
                        (p, image if err is None else err))

        lines = []
        for p, image in results:
            if not args.quiet and len(results) > 1 and args.format != "json":
                lines.append(f"# {p.name}")
            lines.append(render(image, args.format))
            if not args.quiet and len(results) > 1 and args.format != "json":
                lines.append("")

        out = "\n".join(lines).rstrip("\n")
        if out:
            print(out)
        if args.output and out:
            with open(args.output, "a", encoding="utf-8") as fh:
                fh.write(out + "\n")

        for p, exc in failures:
            msg = f"[失败] {p.name}: {exc}"
            print(json.dumps({"ok": False, "file": str(p), "error": str(exc)})
                  if args.json_errors else msg, file=sys.stderr)

        return 0 if results else 1
    except UploadError as exc:
        if args.json_errors:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"错误: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def _safe(fn, item):
    try:
        _, image, _ = fn(item)
        return item, image, None
    except UploadError as exc:
        return item, None, exc
    except Exception as exc:  # noqa: BLE001
        return item, None, UploadError(str(exc))


if __name__ == "__main__":
    sys.exit(main())
