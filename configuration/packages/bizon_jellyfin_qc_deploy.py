#!/usr/bin/env python3
"""Deploy the optional Google / QR (Quick Connect) login for jf.yuriip4.duckdns.org (NPM host on rpi4).

Run on rpi4 from this directory:  python3 bizon_jellyfin_qc_deploy.py
Idempotent. Needs: ~/.secrets/jellyfin (Jellyfin admin API key), bizon awake (user ids are read
from Jellyfin), files bizon_jellyfin_qc_nginx.conf, bizon_jellyfin_qc_ui.js, bizon_jellyfin_qc_qrcode.js.
Steps: oauth2-proxy-lp also serves jf (whitelist + callback map), UI script -> nginx custom dir,
NPM Advanced section (replaces the old shared-token "Jellyfin web auto-login" section).
"""
import json, os, re, subprocess, sys, tempfile, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
JF = "jf.yuriip4.duckdns.org"
STAMP = "20261120-jfqc"
JELLYFIN = "http://192.168.1.4:8096"

# Google email -> Jellyfin user (same people/accounts as the Lampa Google login, chosen by the user)
MAP = {
    "yurii.pachevskyi@gmail.com": "yurii",
    "milapachevska@gmail.com": "yurii",
    "galakks@gmail.com": "katerynas",
    "kateryna.pachevska@gmail.com": "katerynai",
    "nataliya.galak@gmail.com": "sony",
    "mr.alexandervn@gmail.com": "oleksandr",
}
OLD = ("# --- Jellyfin web auto-login", "# --- end Jellyfin web auto-login ---")
NEW = ("# --- Jellyfin Google / QR login", "# --- end Jellyfin Google / QR login ---")


def run(*a, **k):
    return subprocess.run(list(a), check=True, capture_output=True, text=True, **k)


def nginx_ok():
    t = subprocess.run(["docker", "exec", "nginx", "nginx", "-t"], capture_output=True, text=True)
    return "successful" in t.stderr + t.stdout, t.stderr[-600:]


KEY = open(f"{HOME}/.secrets/jellyfin").read().strip()
req = urllib.request.Request(JELLYFIN + "/Users", headers={"Authorization": f'MediaBrowser Token="{KEY}"'})
users = {u["Name"]: u["Id"] for u in json.load(urllib.request.urlopen(req, timeout=10))}
missing = sorted(set(MAP.values()) - set(users))
if missing:
    sys.exit("Jellyfin users missing: " + ", ".join(missing))

# 1. oauth2-proxy-lp: allow jf as redirect target, make sure all MAP emails are allowed
od = f"{HOME}/docker/oauth2-proxy"
ef = f"{od}/emails-lp.txt"
have = [l.strip().lower() for l in open(ef) if l.strip()]
add = [e for e in MAP if e not in have]
if add:
    open(ef, "a").write("".join(e + "\n" for e in add))
comp = open(f"{od}/docker-compose.yml").read()
if f"--whitelist-domain={JF}" not in comp:
    run("cp", f"{od}/docker-compose.yml", f"{od}/docker-compose.yml.bak-{STAMP}")
    comp, k = re.subn(r"^(\s*- --whitelist-domain=lp\.yuriip4\.duckdns\.org\n)",
                      lambda m: m.group(1) + m.group(1).replace("lp.yuriip4", "jf.yuriip4"), comp, count=1, flags=re.M)
    assert k == 1, "oauth2-proxy-lp whitelist line not found"
    open(f"{od}/docker-compose.yml", "w").write(comp)
    run("docker", "compose", "up", "-d", "oauth2-proxy-lp", cwd=od)
    print("oauth2-proxy-lp: + jf whitelist (recreated)")
elif add:
    run("docker", "restart", "oauth2-proxy-lp")
    print("oauth2-proxy-lp: emails added, restarted")

# 2. callback map: jf logins now belong to oauth2-proxy-lp (:4183)
C = "/data/nginx/custom/http.conf"
s = run("docker", "exec", "nginx", "cat", C).stdout
n = s
n = n.replace('"~(/|%2F)lp\\.yuriip4\\.duckdns"', '"~(/|%2F)(lp|jf)\\.yuriip4\\.duckdns"')
n = re.sub(r"\(im\|js\|ha\|han\|jf\)", "(im|js|ha|han)", n)
assert "(lp|jf)" in n, "callback map line for lp not found"


def put(path, text):
    fd, tmp = tempfile.mkstemp(); os.write(fd, text.encode()); os.close(fd)
    try:
        run("docker", "cp", tmp, "nginx:" + path)
        run("docker", "exec", "nginx", "chmod", "644", path)
    finally:
        os.unlink(tmp)


if n != s:
    run("docker", "exec", "nginx", "cp", C, C + ".bak-" + STAMP)
    put(C, n)
    ok, err = nginx_ok()
    if not ok:
        run("docker", "exec", "nginx", "cp", C + ".bak-" + STAMP, C)
        sys.exit("nginx -t failed, http.conf reverted: " + err)
    run("docker", "exec", "nginx", "nginx", "-s", "reload")
    print("http.conf: jf callback -> 4183")

# 3. UI script (QR encoder wrapped so it never touches window.define / module)
lib = open(f"{HERE}/bizon_jellyfin_qc_qrcode.js").read()
lib = lib[:lib.index("(function (factory) {")]
ui = open(f"{HERE}/bizon_jellyfin_qc_ui.js").read()
put("/data/nginx/custom/jfqc-ui.js", "var __jfqr = (function () {\n" + lib + "\nreturn qrcode;\n})();\n" + ui)
print("jfqc-ui.js copied")

# 4. NPM Advanced config of jf host
rows = "\n".join(f'    ["{e}"] = {{ "", "{users[nm]}", "{nm}" }},' for e, nm in MAP.items())
adv_sec = open(f"{HERE}/bizon_jellyfin_qc_nginx.conf").read().replace("__USERS__", rows).replace("__KEY__", KEY).strip()
MJS = r'''
import T from "./models/token.js";
const { token } = await T().create({ iss: "api", attrs: { id: 1 }, scope: ["user"], expiresIn: "1h" });
const H = { Authorization: "Bearer " + token, "Content-Type": "application/json" };
const hosts = await (await fetch("http://127.0.0.1:81/api/nginx/proxy-hosts", { headers: H })).json();
const h = hosts.find(x => x.domain_names.includes(P.domain));
if (!h) { console.log(JSON.stringify({ error: "no host" })); process.exit(0); }
const prev = h.advanced_config || "";
let adv = prev, placed = false;
for (const [a0, b0] of P.cut) {
  const a = adv.indexOf(a0), b = adv.indexOf(b0);
  if (a >= 0 && b > a) {
    adv = adv.slice(0, a) + (placed ? "" : P.sec) + adv.slice(b + b0.length);
    placed = true;
  }
}
if (!placed) adv = adv.trimEnd() + "\n\n" + P.sec + "\n";
if (adv === prev) { console.log(JSON.stringify({ id: h.id, status: 200, same: true, prev })); process.exit(0); }
const r = await fetch(`http://127.0.0.1:81/api/nginx/proxy-hosts/${h.id}`, { method: "PUT", headers: H, body: JSON.stringify({ advanced_config: adv }) });
console.log(JSON.stringify({ id: h.id, status: r.status, prev }));
process.exit(0);
'''
src = "const P = " + json.dumps({"domain": JF, "sec": adv_sec, "cut": [NEW, OLD]}) + ";\n" + MJS
fd, tmp = tempfile.mkstemp(suffix=".mjs"); os.write(fd, src.encode()); os.close(fd)
try:
    run("docker", "cp", tmp, "nginx:/app/zz-jfqc.mjs")
    p = subprocess.run(["docker", "exec", "-w", "/app", "nginx", "node", "zz-jfqc.mjs"], capture_output=True, text=True)
finally:
    os.unlink(tmp)
    subprocess.run(["docker", "exec", "nginx", "rm", "-f", "/app/zz-jfqc.mjs"], capture_output=True)
res = [l for l in p.stdout.splitlines() if l.startswith("{")]
r = json.loads(res[-1]) if res else {"error": (p.stderr or p.stdout)[-600:]}
if r.get("error") or r.get("status") != 200:
    sys.exit("NPM update failed: " + json.dumps({k: v for k, v in r.items() if k != "prev"}))
bak = f"{HOME}/.cache/npm-host-{r['id']}-adv.bak-{STAMP}.conf"
if not os.path.exists(bak):
    fd = os.open(bak, os.O_WRONLY | os.O_CREAT, 0o600)
    os.write(fd, r["prev"].encode()); os.close(fd)
ok, err = nginx_ok()
print("NPM host", r["id"], "unchanged" if r.get("same") else "updated", "; nginx -t", "ok" if ok else "FAILED " + err)
