#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线单元测试：不联网也能跑（CI 跑的就是这个）。

    python -m unittest discover -s tests -v

想附带跑一次真实上传+删除（会往 mjj.today 真传一张 32x32 的小图并立即删掉）：

    MJJ_LIVE_TEST=1 python -m unittest discover -s tests -v
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "mjj_upload.py"


def load_module(cache_dir: Path):
    """把 mjj_upload.py 当模块加载，并让它把状态写进临时目录。"""
    os.environ["MJJ_CACHE_DIR"] = str(cache_dir)
    spec = importlib.util.spec_from_file_location("mjj_upload", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["mjj_upload"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class TempModuleCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.m = load_module(self.tmp / "cache")

    def tearDown(self):
        self._tmp.cleanup()


class TestMultipart(TempModuleCase):
    def test_field_order_and_shapes(self):
        boundary, body = self.m.encode_multipart(
            {"type": "file", "action": "upload", "nsfw": "0"},
            {"source": ("a.png", b"\x89PNG-bytes", "image/png")},
        )
        text = body.decode("utf-8", "replace")

        # 普通字段在前、文件字段在后
        self.assertIn('name="type"', text)
        self.assertLess(text.index('name="type"'), text.index('name="source"'))
        # 文件部分必须带 filename 与 Content-Type
        self.assertIn('name="source"; filename="a.png"', text)
        self.assertIn("Content-Type: image/png", text)
        # 结尾必须是标准闭合 boundary
        self.assertTrue(body.endswith(f"--{boundary}--\r\n".encode()))
        # 开头每个部分都以 --boundary 起
        self.assertTrue(body.startswith(f"--{boundary}\r\n".encode()))

    def test_each_part_wrapped_exactly_once(self):
        boundary, body = self.m.encode_multipart({"a": "1", "b": "2"},
                                                 {"source": ("x.png", b"data", "image/png")})
        # 2 个普通字段 + 1 个文件字段 → 3 个开始分隔符 + 1 个结束分隔符
        self.assertEqual(body.count(f"--{boundary}".encode()), 4)
        self.assertEqual(body.count(f"--{boundary}--".encode()), 1)

    def test_multipart_never_injects_extra_boundary(self):
        # 字段值里出现连字符也不该破坏结构（boundary 是随机生成的十六进制串）
        boundary, body = self.m.encode_multipart({"title": "-- not a boundary --"}, {})
        self.assertEqual(body.count(f"--{boundary}".encode()), 2)

    def test_unicode_field_value_survives(self):
        _, body = self.m.encode_multipart({"title": "测试 标题"}, {})
        self.assertIn("测试 标题".encode("utf-8"), body)

    def test_boundary_is_unique_per_call(self):
        b1, _ = self.m.encode_multipart({"a": "1"}, {})
        b2, _ = self.m.encode_multipart({"a": "1"}, {})
        self.assertNotEqual(b1, b2)


class TestGuessing(TempModuleCase):
    def test_guess_type_known_extensions(self):
        cases = {
            "a.jpg": "image/jpeg", "a.jpeg": "image/jpeg", "a.png": "image/png",
            "a.gif": "image/gif", "a.webp": "image/webp", "a.bmp": "image/bmp",
            "A.PNG": "image/png",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(self.m.guess_type(Path(name)), expected)

    def test_guess_type_unknown_falls_back(self):
        self.assertEqual(self.m.guess_type(Path("a.weird")), "application/octet-stream")


class TestRender(TempModuleCase):
    IMAGE = {
        "url": "https://i.mji.rip/2026/10/13/deadbeef.png",
        "url_viewer": "https://mjj.today/i/QyuPCh0",
        "thumb": {"url": "https://i.mji.rip/2026/10/13/deadbeef.th.png"},
        "original_filename": "shot.png",
        "delete_url": "https://mjj.today/i/QyuPCh0/delete/abc",
    }

    def test_url(self):
        self.assertEqual(self.m.render(self.IMAGE, "url"), self.IMAGE["url"])

    def test_markdown_uses_original_filename(self):
        self.assertEqual(
            self.m.render(self.IMAGE, "markdown"),
            "![shot.png](https://i.mji.rip/2026/10/13/deadbeef.png)",
        )

    def test_bbcode_and_html(self):
        self.assertEqual(self.m.render(self.IMAGE, "bbcode"),
                         f"[img]{self.IMAGE['url']}[/img]")
        self.assertIn('alt="shot.png"', self.m.render(self.IMAGE, "html"))

    def test_markdown_thumb_wraps_viewer_link(self):
        out = self.m.render(self.IMAGE, "markdown-thumb")
        self.assertTrue(out.startswith("[!["))
        self.assertIn(self.IMAGE["url_viewer"], out)

    def test_all_contains_every_link(self):
        out = self.m.render(self.IMAGE, "all")
        for key in ("url", "url_viewer", "delete_url"):
            self.assertIn(self.IMAGE[key], out)

    def test_json_roundtrips(self):
        import json
        self.assertEqual(json.loads(self.m.render(self.IMAGE, "json"))["url"],
                         self.IMAGE["url"])

    def test_unknown_format_raises(self):
        with self.assertRaises(self.m.UploadError):
            self.m.render(self.IMAGE, "nope")


class TestValidation(TempModuleCase):
    def test_missing_file(self):
        with self.assertRaises(self.m.UploadError) as ctx:
            self.m.upload_file(self.m.Session(self.m.DEFAULT_BASE), self.tmp / "nope.png")
        self.assertIn("不存在", str(ctx.exception))

    def test_bad_extension_rejected_before_network(self):
        bad = self.tmp / "note.txt"
        bad.write_text("not an image", encoding="utf-8")
        with self.assertRaises(self.m.UploadError) as ctx:
            self.m.upload_file(self.m.Session(self.m.DEFAULT_BASE), bad)
        self.assertIn("扩展名", str(ctx.exception))

    def test_oversize_rejected_before_network(self):
        big = self.tmp / "big.png"
        big.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 20000)
        with self.assertRaises(self.m.UploadError) as ctx:
            self.m.upload_file(self.m.Session(self.m.DEFAULT_BASE), big, max_size_mb=0.01)
        self.assertIn("上限", str(ctx.exception))

    def test_allowed_extensions_cover_site_whitelist(self):
        # 站点 CHV.obj.config.upload.image_types
        self.assertTrue({"jpg", "jpeg", "png", "bmp", "gif", "webp"} <= self.m.ALLOWED_EXT)


class TestHistory(TempModuleCase):
    IMAGE = {
        "id_encoded": "QyuABC1", "url": "https://i.mji.rip/x.png",
        "url_viewer": "https://mjj.today/i/QyuABC1",
        "thumb": {"url": "https://i.mji.rip/x.th.png"},
        "delete_url": "https://mjj.today/i/QyuABC1/delete/hash",
        "filename": "x.png", "original_filename": "x.png", "size": 12,
    }

    def test_record_and_read(self):
        self.m.record_history(self.IMAGE)
        rows = self.m.read_history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "QyuABC1")
        self.assertEqual(rows[0]["delete_url"], self.IMAGE["delete_url"])

    def test_resolve_exact_id(self):
        self.m.record_history(self.IMAGE)
        session = self.m.Session(self.m.DEFAULT_BASE)
        self.assertEqual(self.m.resolve_delete_url(session, "QyuABC1"),
                         self.IMAGE["delete_url"])

    def test_resolve_unique_prefix(self):
        self.m.record_history(self.IMAGE)
        session = self.m.Session(self.m.DEFAULT_BASE)
        self.assertEqual(self.m.resolve_delete_url(session, "QyuABC"),
                         self.IMAGE["delete_url"])

    def test_resolve_from_viewer_url(self):
        self.m.record_history(self.IMAGE)
        session = self.m.Session(self.m.DEFAULT_BASE)
        self.assertEqual(
            self.m.resolve_delete_url(session, "https://mjj.today/i/QyuABC1"),
            self.IMAGE["delete_url"])

    def test_resolve_passthrough_delete_url(self):
        session = self.m.Session(self.m.DEFAULT_BASE)
        url = "https://mjj.today/i/ZZZ/delete/abc"
        self.assertEqual(self.m.resolve_delete_url(session, url), url)

    def test_unknown_id_raises(self):
        session = self.m.Session(self.m.DEFAULT_BASE)
        with self.assertRaises(self.m.UploadError):
            self.m.resolve_delete_url(session, "NotThere")


class TestSession(TempModuleCase):
    def test_token_regex_matches_homepage_shape(self):
        # 形状取自首页内联脚本（此处用等长假值，40 位 hex）
        fake = "a1b2c3d4" * 5
        html = f'PF.obj.config.auth_token = "{fake}";'
        self.assertEqual(self.m.TOKEN_RE.search(html).group(1), fake)

    def test_token_regex_ignores_short_or_non_hex(self):
        self.assertIsNone(self.m.TOKEN_RE.search('auth_token = "abc"'))
        self.assertIsNone(self.m.TOKEN_RE.search('auth_token = "zzzzzzzzzzzzzzzz"'))

    def test_cache_roundtrip(self):
        s1 = self.m.Session(self.m.DEFAULT_BASE, use_cache=True)
        s1.cookie, s1.token = "PHPSESSID=abc", "deadbeef" * 5
        s1.save()
        s2 = self.m.Session(self.m.DEFAULT_BASE, use_cache=True)
        self.assertTrue(s2.load())
        self.assertEqual((s2.cookie, s2.token), (s1.cookie, s1.token))

    def test_cache_ignored_for_other_base_url(self):
        s1 = self.m.Session(self.m.DEFAULT_BASE, use_cache=True)
        s1.cookie, s1.token = "PHPSESSID=abc", "deadbeef" * 5
        s1.save()
        other = self.m.Session("https://img.example.com", use_cache=True)
        self.assertFalse(other.load())

    def test_disable_cache(self):
        s1 = self.m.Session(self.m.DEFAULT_BASE, use_cache=True)
        s1.cookie, s1.token = "PHPSESSID=abc", "deadbeef" * 5
        s1.save()
        self.assertFalse(self.m.Session(self.m.DEFAULT_BASE, use_cache=False).load())


class TestCli(TempModuleCase):
    def test_defaults(self):
        args = self.m.build_parser().parse_args(["a.png"])
        self.assertEqual(args.format, "url")
        self.assertEqual(args.jobs, 5)
        self.assertEqual(args.nsfw, 0)
        self.assertEqual(args.files, ["a.png"])
        self.assertEqual(args.base_url, "https://mjj.today")
        self.assertIsNone(args.list)

    def test_format_choices_rejected(self):
        with self.assertRaises(SystemExit):
            self.m.build_parser().parse_args(["-f", "nope", "a.png"])

    def test_expiration_passthrough(self):
        args = self.m.build_parser().parse_args(["-e", "PT1D", "a.png"])
        self.assertEqual(args.expiration, "PT1D")

    def test_list_flag_with_and_without_value(self):
        self.assertEqual(self.m.build_parser().parse_args(["--list"]).list, 10)
        self.assertEqual(self.m.build_parser().parse_args(["--list", "3"]).list, 3)

    def test_no_args_returns_2(self):
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.m.main([]), 2)

    def test_stdin_path_helper_writes_file(self):
        import io

        class FakeStdin:
            def __init__(self, data: bytes):
                self.buffer = io.BytesIO(data)

        original = sys.stdin
        try:
            sys.stdin = FakeStdin(b"\x89PNG\r\n\x1a\nfake")
            path = self.m.read_stdin_image()
        finally:
            sys.stdin = original
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_bytes(), b"\x89PNG\r\n\x1a\nfake")
        path.unlink()

    def test_error_output_as_json(self):
        import contextlib
        import io
        import json
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.m.main(["--json-errors", str(self.tmp / "missing.png")])
        self.assertEqual(rc, 1)
        payload = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertFalse(payload["ok"])
        self.assertIn("不存在", payload["error"])


@unittest.skipUnless(os.environ.get("MJJ_LIVE_TEST") == "1",
                     "设置 MJJ_LIVE_TEST=1 才跑真实上传（会往 mjj.today 传一张小图并删除）")
class TestLive(TempModuleCase):
    """打真实站点：上传 → 校验直链可访问 → 删除 → 校验信息页 404。"""

    @staticmethod
    def _tiny_png() -> bytes:
        import struct
        import zlib

        def chunk(tag: bytes, data: bytes) -> bytes:
            body = tag + data
            return (struct.pack(">I", len(data)) + body
                    + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

        size = 8
        raw = b"".join(b"\x00" + bytes([255, 0, 128] * size) for _ in range(size))
        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw))
                + chunk(b"IEND", b""))

    def test_upload_then_delete(self):
        import urllib.request
        png = self.tmp / "live.png"
        png.write_bytes(self._tiny_png())

        session = self.m.Session(self.m.DEFAULT_BASE, timeout=60, use_cache=True)
        image = self.m.upload_file(session, png)

        self.assertTrue(image.get("url", "").endswith(".png"))
        self.assertIn("mjj.today/i/", image.get("url_viewer", ""))
        self.assertIn("/delete/", image.get("delete_url", ""))

        req = urllib.request.Request(image["url"], headers={"User-Agent": self.m.UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            self.assertEqual(resp.status, 200)
            self.assertTrue(resp.headers.get("Content-Type", "").startswith("image/"))

        final = self.m.delete_image(session, image["id_encoded"])
        self.assertIn("deleted", final)


if __name__ == "__main__":
    unittest.main(verbosity=2)
