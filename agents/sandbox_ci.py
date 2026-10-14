"""Strands sandbox backed by AgentCore Code Interpreter.

The agent "brain" runs in AgentCore Runtime (which holds AWS credentials and the gateway token);
every command the agent issues runs in a separate Code Interpreter session instead. The default
interpreter (aws.codeinterpreter.v1) has no internet and no AWS credentials, so generated code
can neither exfiltrate secrets nor reach the network. Third-party wheels are fetched by the
runtime (which has internet) and pushed in as files, the same split CodeBuild uses later.
"""
import asyncio
import io
import os
import shlex
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from bedrock_agentcore.tools.code_interpreter_client import CodeInterpreter
from strands.sandbox.posix_shell import PosixShellSandbox, build_shell_env_prefix
from strands.sandbox.types import ExecutionResult, StreamChunk

INTERPRETER_ID = os.environ.get("CODE_INTERPRETER_ID", "aws.codeinterpreter.v1")
WS = "ws"  # workspace dir, relative to the interpreter's working directory
MAX_OUT = 20_000  # keep tool results bounded: context compaction is off, so output must stay small


class CodeInterpreterSandbox(PosixShellSandbox):
    def __init__(self, region: str = "us-east-1", session_timeout: int = 3600) -> None:
        super().__init__()
        self.ci = CodeInterpreter(region)
        self.session_timeout = session_timeout
        self.root: str | None = None

    # -- lifecycle ---------------------------------------------------------------------------
    def start(self) -> None:
        self.ci.start(identifier=INTERPRETER_ID, session_timeout_seconds=self.session_timeout)
        out = self._run_sync(f"mkdir -p {WS} && cd {WS} && pwd")
        self.root = out.stdout.strip().splitlines()[-1]

    def stop(self) -> None:
        try:
            self.ci.stop()
        except Exception:
            pass

    # -- core contract -----------------------------------------------------------------------
    def _run_sync(self, command: str) -> ExecutionResult:
        resp = self.ci.execute_command(command)
        stdout, stderr, code = [], [], 0
        for ev in resp["stream"]:
            sc = ev.get("result", {}).get("structuredContent", {})
            stdout.append(sc.get("stdout", ""))
            stderr.append(sc.get("stderr", ""))
            code = sc.get("exitCode", code)
        return ExecutionResult(exit_code=int(code), stdout="".join(stdout)[-MAX_OUT:],
                               stderr="".join(stderr)[-MAX_OUT:])

    async def execute_streaming(self, command: str, *, timeout: float | None = None,
                                cwd: str | None = None, env: dict[str, str] | None = None,
                                **kwargs: Any) -> AsyncGenerator[StreamChunk | ExecutionResult, None]:
        target = cwd or self.root or WS
        body = f"{build_shell_env_prefix(env)}{command}"
        limit = int(timeout or 600)
        full = f"cd {shlex.quote(target)} && timeout {limit} sh -c {shlex.quote(body)}"
        result = await asyncio.to_thread(self._run_sync, full)
        yield result

    # Binary-safe file writes through the native API instead of base64-over-shell.
    async def write_file(self, path: str, content: bytes, **kwargs: Any) -> None:
        rel = self._rel(path)
        await asyncio.to_thread(self.ci.upload_file, rel, content)

    def _rel(self, path: str) -> str:
        p = path
        if self.root and p.startswith(self.root):
            p = os.path.relpath(p, Path(self.root).parent)
        elif not p.startswith(WS + "/") and not p.startswith("/"):
            p = f"{WS}/{p}"
        if p.startswith("/"):
            raise ValueError(f"path outside workspace: {path}")
        return p

    # -- workspace sync ----------------------------------------------------------------------
    def push_dir(self, local: Path) -> None:
        """Copy a local workspace into the sandbox (zip, upload, unzip)."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in local.rglob("*"):
                if f.is_file() and ".git" not in f.parts:
                    z.write(f, f.relative_to(local))
        self.ci.upload_file(f"{WS}.push.zip", buf.getvalue())
        self._run_sync(f"python3 -m zipfile -e {WS}.push.zip {WS} && rm {WS}.push.zip")

    def pull_dir(self, local: Path) -> None:
        """Copy the sandbox workspace back (zip in sandbox, download, extract)."""
        self._run_sync(f"cd {WS} && rm -f ../{WS}.pull.zip && python3 -m zipfile -c ../{WS}.pull.zip "
                       f"$(ls -A | grep -v -e '^.venv$' -e '^__pycache__$' -e '^wheels$')")
        with zipfile.ZipFile(io.BytesIO(self._read_bytes(f"{WS}.pull.zip"))) as z:
            z.extractall(local)

    def _read_bytes(self, path: str) -> bytes:
        # download_file() may decode blobs to str; read the raw resource instead.
        for ev in self.ci.invoke("readFiles", {"paths": [path]}).get("stream", []):
            for item in ev.get("result", {}).get("content", []):
                res = item.get("resource", {}) if item.get("type") == "resource" else {}
                if "blob" in res:
                    return res["blob"]
                if "text" in res:
                    return res["text"].encode()
        raise FileNotFoundError(path)

    def install_requirements(self, requirements: Path) -> ExecutionResult:
        """Fetch wheels on the runtime (internet) and install them in the sandbox (no internet)."""
        arch = self._run_sync("uname -m").stdout.strip() or "x86_64"
        reqs = ["pytest"] + ([requirements.read_text()] if requirements.exists() else [])
        with tempfile.TemporaryDirectory() as tmp:
            rf = Path(tmp) / "req.txt"
            rf.write_text("\n".join(reqs))
            # pip ships inside the runtime package; run it with this interpreter and package path.
            env = {**os.environ, "PYTHONPATH": os.path.dirname(os.path.abspath(__file__))}
            dl = subprocess.run(
                [sys.executable, "-m", "pip", "download", "-q", "--only-binary=:all:", "-d", f"{tmp}/w",
                 "--platform", f"manylinux_2_28_{arch}", "--platform", f"manylinux2014_{arch}", "--python-version", "3.12", "-r", str(rf)],
                capture_output=True, text=True, timeout=600, env=env)
            if dl.returncode != 0:
                return ExecutionResult(exit_code=dl.returncode, stdout=dl.stdout[-4000:], stderr=dl.stderr[-4000:])
            for whl in Path(f"{tmp}/w").glob("*.whl"):
                self.ci.upload_file(f"wheels/{whl.name}", whl.read_bytes())
        return self._run_sync("python3 -m pip install -q --no-index --find-links wheels wheels/*.whl 2>&1 | tail -5")
