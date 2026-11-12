"""Route tables for the web API. Handlers are registered with decorators and dispatched by Handler.

    @routes.get("/api/thing")        def thing(h, q): h._send(200, {...})        # q: query dict
    @routes.post("/api/thing")       def thing(h, body): h._send(200, {...})     # body: parsed JSON
    @routes.get_prefix("/fonts/")    def fonts(h, rest, q): ...                  # rest: path after the prefix

Handlers reply with h._send(code, body, ctype=...) and raise StoreError for a 400.
"""
GET = {}
POST = {}
PREFIX_GET = []


def get(path):
    def deco(fn):
        GET[path] = fn
        return fn
    return deco


def post(path):
    def deco(fn):
        POST[path] = fn
        return fn
    return deco


def get_prefix(prefix):
    def deco(fn):
        PREFIX_GET[:] = [(p, f) for p, f in PREFIX_GET if p != prefix]
        PREFIX_GET.append((prefix, fn))
        return fn
    return deco
