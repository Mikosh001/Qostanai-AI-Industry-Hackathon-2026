"""TLS termination for the loopback-only PHP development server. Local lab only."""

import httpx, uvicorn, os, json, time
from http.cookies import SimpleCookie
from pathlib import Path
from fastapi import FastAPI, Request, Response

lab = Path(os.environ["SERGEK_LAB"])
app = FastAPI(docs_url=None, redoc_url=None)


class CookieRotations:
    """A late request with a retired SID must not overwrite a fresh login cookie.

    Only suppress stale response headers. Never inject an authenticated cookie
    into a request, grant authentication or alter CSRF tokens.
    """
    def __init__(self): self.retired = {}

    @staticmethod
    def sessions(header):
        value = SimpleCookie()
        try: value.load(header)
        except Exception: return {}
        return {k:m.value for k,m in value.items() if k.startswith('MoodleSession')}

    def filter(self, method, path, status, incoming, headers, now=None):
        now = time.monotonic() if now is None else now
        self.retired = {k:v for k,v in self.retired.items() if v > now}
        old = self.sessions(incoming)
        login = method == 'POST' and path == 'login/index.php' and status == 303
        if login:
            for k,v in headers:
                if k.lower() == b'set-cookie':
                    for name,sid in self.sessions(v.decode('latin1')).items():
                        if old.get(name) and sid and sid != old[name]:
                            self.retired[(name,old[name])] = now + 120
        result=[]
        for k,v in headers:
            if not login and k.lower() == b'set-cookie':
                changes=self.sessions(v.decode('latin1'))
                if any((name,old.get(name)) in self.retired and sid != old.get(name) for name,sid in changes.items()):
                    continue
            result.append((k,v))
        return result


rotations = CookieRotations()


def preference_body(path, body):
    # Moodle 4.5 can store BOOL false as ""; its REST BOOL validator requires "0".
    # Canonicalise only this known boolean preference, retaining all authentication.
    if path == "r.php/api/rest/v2/user/current/preferences/qbank_managecategories_includesubcategories_filter_default":
        try:
            value = json.loads(body)
            if value == {"value": False} or value == {"value": ""}:
                return b'{"value":"0"}'
        except (ValueError, TypeError):
            pass
    return body


@app.api_route(
    "/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
)
async def proxy(request: Request, path: str):
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in ("host", "connection", "content-length")
    }
    headers.update({"host": "localhost", "x-forwarded-proto": "https"})
    async with httpx.AsyncClient(follow_redirects=False, timeout=90) as client:
        target = (
            "http://127.0.0.1:8088/"
            + path
            + ("?" + request.url.query if request.url.query else "")
        )
        body=await request.body()
        if request.method == "POST":body=preference_body(path,body)
        r = await client.request(request.method, target, headers=headers, content=body)
    response = Response(r.content, status_code=r.status_code)
    response.raw_headers = [
        (k, v)
        for k, v in rotations.filter(request.method, path, r.status_code,
                                    request.headers.get('cookie',''), r.headers.raw)
        if k.lower()
        not in (
            b"transfer-encoding",
            b"connection",
            b"content-encoding",
            b"content-length",
        )
    ]
    response.headers["content-length"] = str(len(r.content))
    return response


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=443,
        ssl_certfile=str(lab / "localhost.crt"),
        ssl_keyfile=str(lab / "localhost.key"),
        access_log=False,
    )
