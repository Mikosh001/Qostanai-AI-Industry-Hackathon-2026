"""Bound actual ASGI body bytes, including chunked bodies without Content-Length."""

from starlette.responses import JSONResponse
import asyncio


class RequestBodyLimit:
    def __init__(self, app, max_bytes=30_000_000):
        self.app = app
        self.max_bytes = max_bytes
        self.large_uploads = None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        length=dict(scope.get('headers',[])).get(b'content-length')
        large=scope.get('path')=='/api/hub/ingest' and (not length or (length.isdigit() and int(length)>256_000))
        if large:
            if self.large_uploads is None:self.large_uploads=asyncio.Semaphore(4)
            try:await asyncio.wait_for(self.large_uploads.acquire(),8)
            except TimeoutError:
                return await JSONResponse({'detail':'Evidence upload busy; retry later'},status_code=429,headers={'Retry-After':'5'})(scope,receive,send)
            try:return await self.bounded(scope,receive,send)
            finally:self.large_uploads.release()
        return await self.bounded(scope,receive,send)

    async def bounded(self,scope,receive,send):
        headers = dict(scope.get("headers", []))
        length = headers.get(b"content-length")
        if length is not None and (
            not length.isdigit() or len(length) > 12 or int(length) > self.max_bytes
        ):
            status = 413 if length.isdigit() else 400
            return await JSONResponse(
                {"detail": "Invalid or oversized request body"}, status_code=status
            )(scope, receive, send)
        chunks = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > self.max_bytes:
                return await JSONResponse(
                    {"detail": "Request too large"}, status_code=413
                )(scope, receive, send)
            chunks.append(body)
            if not message.get("more_body", False):
                break
        buffered = b"".join(chunks)
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": buffered, "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)
