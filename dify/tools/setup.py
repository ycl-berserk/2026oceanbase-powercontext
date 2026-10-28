"""One-shot installer for《译者城市：第 13 号片区》.

It does four things:
  1. creates a fresh PowerContext scope and seeds the case facts;
  2. creates (or reuses) the Dify knowledge base and uploads the five archives;
     the dataset description stores a hash of the archives, so edited archives
     are detected and reindexed automatically;
  3. imports app/district13-game.yml into Dify with the dataset id and
     PowerContext scope id substituted, then publishes it;
  4. creates an API key and writes .runtime/install.json for verify.py.

Required environment variables:
  DIFY_EMAIL, DIFY_PASSWORD
Optional:
  DIFY_URL                    default http://127.0.0.1:8080
  POWERCONTEXT_URL            default http://127.0.0.1:8100
  DIFY_POWERCONTEXT_URL       URL Dify containers use   default http://host.docker.internal:8100
  DIFY_DATASET_NAME           default 第13号片区档案
  DIFY_APP_NAME               default 译者城市：第 13 号片区
  DIFY_APP_ID                 overwrite this app id instead of searching by name

Usage:
  python tools/setup.py
"""

import base64
import datetime as dt
import hashlib
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
DIFY_DIR = os.path.dirname(HERE)

DIFY_URL = os.environ.get("DIFY_URL", "http://127.0.0.1:8080").rstrip("/")
DIFY_EMAIL = os.environ.get("DIFY_EMAIL", "")
DIFY_PASSWORD = os.environ.get("DIFY_PASSWORD", "")
PC_URL = os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8100").rstrip("/")
DIFY_PC_URL = os.environ.get("DIFY_POWERCONTEXT_URL", "http://host.docker.internal:8100").rstrip("/")
DATASET_NAME = os.environ.get("DIFY_DATASET_NAME", "第13号片区档案")
APP_NAME = os.environ.get("DIFY_APP_NAME", "译者城市：第 13 号片区")
APP_ID = os.environ.get("DIFY_APP_ID", "").strip()
DATASET_DESC = "第 13 号片区：海关旧档、潮位勘误、撤离名册等五份档案。"

DSL_PATH = os.path.join(DIFY_DIR, "app", "district13-game.yml")
CASE_PATH = os.path.join(DIFY_DIR, "case", "case.json")
ARCHIVE_DIR = os.path.join(DIFY_DIR, "case", "archives")
RUNTIME_DIR = os.path.join(DIFY_DIR, ".runtime")
RUNTIME_PATH = os.path.join(RUNTIME_DIR, "install.json")


# ---------------------------------------------------------------- HTTP helpers

class Http:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    def request(self, method, path, payload=None, raw=None, content_type="application/json",
                timeout=300, auth=None):
        data = raw
        if data is None and payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", content_type)
        csrf = next((c.value for c in self.jar if c.name == "csrf_token"), None)
        if csrf:
            req.add_header("X-CSRF-Token", csrf)
        if auth:
            req.add_header("Authorization", auth)
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                body = resp.read()
                try:
                    return resp.status, json.loads(body.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    return resp.status, body
        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8", "replace")
            raise RuntimeError("%s %s -> %s: %s" % (method, path, err.code, body[:800]))

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, payload=None, **kw):
        return self.request("POST", path, payload=payload, **kw)

    def put(self, path, payload=None, **kw):
        return self.request("PUT", path, payload=payload, **kw)

    def patch(self, path, payload=None, **kw):
        return self.request("PATCH", path, payload=payload, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)


def multipart(fields, filename, content):
    boundary = "----district13" + uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append(
            ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
             % (boundary, key, value)).encode("utf-8")
        )
    parts.append(
        ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
         "Content-Type: text/markdown\r\n\r\n" % (boundary, filename)).encode("utf-8")
    )
    parts.append(content.encode("utf-8"))
    parts.append(("\r\n--%s--\r\n" % boundary).encode("utf-8"))
    return b"".join(parts), "multipart/form-data; boundary=" + boundary


# ------------------------------------------------------------- PowerContext

def pc_create_scope(case):
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    payload = {
        "title": "%s · 演示 %s" % (case["name"], stamp),
        "summary": "译者城市互动游戏：第 13 号片区的调查进度、证人信任与结局记忆。",
        "idempotency_key": "district13-%s" % stamp,
    }
    status, body = Http(PC_URL).post("/v1/scopes", payload)
    scope_id = body.get("scope_id")
    print("[powercontext] scope", scope_id)
    return scope_id


def pc_seed(scope_id, case):
    texts = list(case.get("seed_memories", []))
    for w in case.get("witnesses", {}).values():
        if w.get("seed_memory"):
            texts.append(w["seed_memory"])
    client = Http(PC_URL)
    for text in texts:
        status, body = client.post("/v1/memory/remember", {
            "scope_id": scope_id,
            "kind": "district13_world",
            "text": text,
            "reason": "case seed",
        })
    print("[powercontext] seeded %d facts" % len(texts))


# --------------------------------------------------------------------- Dify

def dify_login():
    if not DIFY_EMAIL or not DIFY_PASSWORD:
        raise SystemExit("Set DIFY_EMAIL and DIFY_PASSWORD before running setup.")
    client = Http(DIFY_URL)
    encoded = base64.b64encode(DIFY_PASSWORD.encode()).decode()
    client.post("/console/api/login", {
        "email": DIFY_EMAIL,
        "password": encoded,
        "remember_me": True,
    })
    return client


def archive_digest():
    digest = hashlib.sha256()
    for name in sorted(os.listdir(ARCHIVE_DIR)):
        if not name.endswith(".md"):
            continue
        digest.update(name.encode("utf-8"))
        with open(os.path.join(ARCHIVE_DIR, name), "rb") as fh:
            digest.update(fh.read())
    return digest.hexdigest()[:12]


def dataset_description(digest):
    return "%s archive-hash:%s" % (DATASET_DESC, digest)


def ensure_dataset(client, digest):
    status, body = client.get("/console/api/datasets?page=1&limit=100")
    for item in body.get("data", []):
        if item.get("name") != DATASET_NAME:
            continue
        dataset_id = item["id"]
        stale = ("archive-hash:" + digest) not in (item.get("description") or "")
        if stale:
            print("[dify] dataset %s (archives changed, reindexing)" % dataset_id)
            purge_documents(client, dataset_id)
        else:
            print("[dify] dataset %s (archives unchanged)" % dataset_id)
        ensure_documents(client, dataset_id)
        if stale:
            client.patch("/console/api/datasets/%s" % dataset_id,
                         {"description": dataset_description(digest)})
        return dataset_id
    status, item = client.post("/console/api/datasets", {
        "name": DATASET_NAME,
        "description": dataset_description(digest),
        "indexing_technique": "economy",
        "permission": "only_me",
    })
    dataset_id = item["id"]
    print("[dify] dataset %s (new)" % dataset_id)
    ensure_documents(client, dataset_id)
    return dataset_id


def purge_documents(client, dataset_id, timeout=120):
    status, body = client.get(
        "/console/api/datasets/%s/documents?page=1&limit=100" % dataset_id
    )
    ids = [doc["id"] for doc in body.get("data", [])]
    if not ids:
        return
    query = urllib.parse.urlencode([("document_id", doc_id) for doc_id in ids])
    client.delete("/console/api/datasets/%s/documents?%s" % (dataset_id, query))
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, body = client.get(
            "/console/api/datasets/%s/documents?page=1&limit=100" % dataset_id
        )
        if not body.get("data"):
            return
        time.sleep(2)
    raise RuntimeError("documents were not removed from dataset %s" % dataset_id)


def ensure_documents(client, dataset_id):
    status, body = client.get(
        "/console/api/datasets/%s/documents?page=1&limit=100" % dataset_id
    )
    existing = {doc.get("name") for doc in body.get("data", [])}
    files = sorted(os.listdir(ARCHIVE_DIR))
    for name in files:
        if not name.endswith(".md") or name in existing:
            continue
        path = os.path.join(ARCHIVE_DIR, name)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        raw, ctype = multipart({}, name, text)
        status, upload = client.request(
            "POST", "/console/api/files/upload?source=datasets",
            raw=raw, content_type=ctype,
        )
        file_id = upload["id"]
        client.post("/console/api/datasets/%s/documents" % dataset_id, {
            "indexing_technique": "economy",
            "data_source": {
                "info_list": {
                    "data_source_type": "upload_file",
                    "file_info_list": {"file_ids": [file_id]},
                }
            },
            "process_rule": {"mode": "automatic"},
            "doc_form": "text_model",
            "doc_language": "Chinese",
            "retrieval_model": {
                "search_method": "keyword_search",
                "reranking_enable": False,
                "top_k": 4,
                "score_threshold_enabled": False,
            },
        })
        print("[dify] uploaded", name)
    wait_indexed(client, dataset_id, timeout=180)


def wait_indexed(client, dataset_id, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, body = client.get(
            "/console/api/datasets/%s/documents?page=1&limit=100" % dataset_id
        )
        docs = body.get("data", [])
        if docs and all(d.get("indexing_status") in ("completed", "error") for d in docs):
            errors = [d.get("name") for d in docs if d.get("indexing_status") == "error"]
            if errors:
                raise RuntimeError("indexing failed: %s" % errors)
            print("[dify] indexed %d documents" % len(docs))
            return
        time.sleep(2)
    raise RuntimeError("indexing timeout after %ss" % timeout)


def find_app(client):
    if APP_ID:
        return APP_ID
    status, body = client.get("/console/api/apps?page=1&limit=100")
    for item in body.get("data", []):
        if item.get("name") == APP_NAME:
            return item["id"]
    return ""


def import_app(client, app_id, dataset_id, scope_id):
    with open(DSL_PATH, encoding="utf-8") as fh:
        yaml_content = fh.read()
    yaml_content = yaml_content.replace("REPLACE_WITH_DATASET_ID", dataset_id)
    yaml_content = yaml_content.replace("REPLACE_WITH_SCOPE_ID", scope_id)
    yaml_content = yaml_content.replace("http://host.docker.internal:8100", DIFY_PC_URL)
    payload = {"mode": "yaml-content", "yaml_content": yaml_content}
    if app_id:
        payload["app_id"] = app_id
    status, body = client.post("/console/api/apps/imports", payload)
    if body.get("status") != "completed":
        raise RuntimeError("import failed: %s" % json.dumps(body, ensure_ascii=False)[:800])
    print("[dify] app", body["app_id"])
    return body["app_id"]


def publish(client, app_id):
    client.post("/console/api/apps/%s/workflows/publish" % app_id, {
        "marked_name": "district13",
        "marked_comment": "seed: kb + powercontext memory",
    })
    print("[dify] published")


def get_site_code(client, app_id):
    status, body = client.get("/console/api/apps/%s" % app_id)
    code = (body.get("site") or {}).get("code")
    if not code:
        raise RuntimeError("app %s has no site code; is the web app enabled?" % app_id)
    return code


def create_key(client, app_id):
    try:
        status, body = client.post("/console/api/apps/%s/api-keys" % app_id)
    except RuntimeError as err:
        if "max_keys_exceeded" not in str(err):
            raise
        status, listing = client.get("/console/api/apps/%s/api-keys" % app_id)
        for item in listing.get("data", []):
            client.delete("/console/api/apps/%s/api-keys/%s" % (app_id, item["id"]))
        status, body = client.post("/console/api/apps/%s/api-keys" % app_id)
    token = body.get("token")
    if not token:
        raise RuntimeError("no api key in response")
    return token


def main():
    with open(CASE_PATH, encoding="utf-8") as fh:
        case = json.load(fh)
    if not os.path.exists(DSL_PATH):
        raise SystemExit("missing %s; run tools/build_dsl.py first" % DSL_PATH)

    scope_id = pc_create_scope(case)
    pc_seed(scope_id, case)

    client = dify_login()
    dataset_id = ensure_dataset(client, archive_digest())

    existing = find_app(client)
    app_id = import_app(client, existing, dataset_id, scope_id)
    publish(client, app_id)
    api_key = create_key(client, app_id)
    site_code = get_site_code(client, app_id)

    os.makedirs(RUNTIME_DIR, exist_ok=True)
    runtime = {
        "dify_url": DIFY_URL,
        "app_id": app_id,
        "site_code": site_code,
        "api_key": api_key,
        "dataset_id": dataset_id,
        "scope_id": scope_id,
        "powercontext_url": PC_URL,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    with open(RUNTIME_PATH, "w", encoding="utf-8") as fh:
        json.dump(runtime, fh, ensure_ascii=False, indent=2)
    os.chmod(RUNTIME_PATH, 0o600)
    print("[done] runtime written to .runtime/install.json")
    print("[open] %s/chat/%s" % (DIFY_URL, site_code))


if __name__ == "__main__":
    main()
