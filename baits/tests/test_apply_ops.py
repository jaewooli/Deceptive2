"""apply_ops 파일 시각 처리(11/23: 스위치 끄고 켜기 뒤 ~/.ssh·~/.aws가 오늘 시각, 키 파일들이 같은 초)
실행: python3 -m unittest discover -s baits/tests
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import apply_ops as A  # noqa: E402

OLD = time.mktime((2024, 7, 2, 10, 16, 41, 0, 0, -1))


def stamp(t):
    return time.strftime("%Y%m%d%H%M.%S", time.localtime(t))


class Mtimes(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.utime(self.d, (OLD, OLD))

    def test_create_and_remove_keep_parent_mtime(self):
        p = os.path.join(self.d, "k")
        self.assertEqual(A.do({"kind": "file", "path": p, "content": "x\n", "mtime": stamp(OLD - 128)}, "apply"), "changed")
        self.assertEqual(os.stat(self.d).st_mtime, OLD)
        self.assertEqual(A.do({"kind": "file", "path": p, "content": "x\n"}, "absent"), "absent")
        self.assertEqual(os.stat(self.d).st_mtime, OLD)

    def test_rewrite_existing_file_keeps_parent_mtime(self):
        p = os.path.join(self.d, "authorized_keys")
        open(p, "w").write("ssh-ed25519 A x\n")
        os.utime(self.d, (OLD, OLD))
        A.do({"kind": "block", "path": p, "block": "ssh-ed25519 B y\n"}, "apply")      # 임시 파일 + 바꿔치기
        self.assertEqual(os.stat(self.d).st_mtime, OLD)

    def test_ok_file_gets_its_mtime_back(self):
        p = os.path.join(self.d, "k")
        open(p, "w").write("x\n")
        self.assertEqual(A.do({"kind": "file", "path": p, "content": "x\n", "mtime": stamp(OLD - 128)}, "apply"), "ok")
        self.assertEqual(os.stat(p).st_mtime, OLD - 128)

    def test_block_own_mtime_only_when_owned(self):
        p = os.path.join(self.d, "config")
        open(p, "w").write("Host a\n")
        now = os.stat(p).st_mtime
        A.do({"kind": "block", "path": p, "block": "Host a\n", "mtime": stamp(OLD)}, "apply")
        self.assertEqual(os.stat(p).st_mtime, now)          # 원래 있던 파일 — 시각은 서버 것
        A.do({"kind": "block", "path": p, "block": "Host a\n", "mtime": stamp(OLD), "own_mtime": True}, "apply")
        self.assertEqual(os.stat(p).st_mtime, OLD)          # 미끼가 만든 파일 — 미끼 시각

    def test_main_reapplies_dir_mtime_after_children(self):
        sub = os.path.join(self.d, "s")
        ops = [{"kind": "dir", "path": sub, "mode": "0700", "mtime": stamp(OLD)},
               {"kind": "file", "path": os.path.join(sub, "a"), "content": "1"}]
        f = os.path.join(self.d, "ops.json")
        open(f, "w").write(__import__("json").dumps(ops))
        sys.argv = ["apply_ops", f, "apply"]
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            A.main()
        self.assertEqual(os.stat(sub).st_mtime, OLD)


if __name__ == "__main__":
    unittest.main()


class RunOp(unittest.TestCase):
    """11/24: 스크립트를 쓰는 줄이 주석 안에 들어가 빈 스크립트가 '성공'하던 회귀"""

    def test_script_runs_and_collects(self):
        A.RUN_DIR = tempfile.mkdtemp()
        A.DATA.clear()
        st = A.do({"kind": "run", "argv": ["x"], "collect": ["v"], "script": 'echo "v=got-$1"\n'}, "apply")
        self.assertEqual(st, "changed")
        self.assertEqual(A.DATA.get("v"), "got-x")
        self.assertEqual(os.listdir(A.RUN_DIR), [])   # 임시 파일 남기지 않음

    def test_failing_script_fails(self):
        A.RUN_DIR = tempfile.mkdtemp()
        self.assertEqual(A.do({"kind": "run", "argv": [], "script": "exit 3\n"}, "apply"), "failed")
