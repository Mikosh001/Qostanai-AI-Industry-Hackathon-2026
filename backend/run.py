import argparse, os, sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cert")
    parser.add_argument("--key")
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "::1") and (not args.cert or not args.key):
        parser.error(
            "LAN service requires --cert and --key; local HTTP only binds to loopback"
        )
    import uvicorn
    from backend.app import app

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        ssl_certfile=args.cert,
        ssl_keyfile=args.key,
        access_log=False,
        timeout_keep_alive=30,  # Agents sync every 5s; preserve the connection across that cadence.
    )


if __name__ == "__main__":
    main()
