"""Update check, apply and restart endpoints."""
import threading

from . import routes, updater


@routes.get("/api/update")
def update_status(h, q):
    h._send(200, updater.status())


@routes.post("/api/update/check")
def update_check(h, body):
    h._send(200, updater.check(force=True))


@routes.post("/api/update/apply")
def update_apply(h, body):
    h._send(200, updater.apply())   # an UpdateError is a StoreError: the server turns it into a 400 with its sentence


@routes.post("/api/restart")
def restart(h, body):
    h._send(200, {"ok": True})
    threading.Timer(0.5, updater.restart_safely).start()
