import os
import sys
import json
import traceback

# CRITICAL: Add current api dir and backend dir to sys.path so imports succeed in Vercel AWS Lambda
_api_dir = os.path.dirname(os.path.abspath(__file__))
if _api_dir not in sys.path:
    sys.path.insert(0, _api_dir)

_root_dir = os.path.dirname(_api_dir)
_backend_dir = os.path.join(_root_dir, "backend")
if os.path.isdir(_backend_dir) and _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from flask import Flask, request, Response, stream_with_context
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

IMPORT_ERROR = None
try:
    from index import (
        get_threads,
        create_thread,
        delete_thread,
        chat_streaming,
        get_email_health,
        send_test_email,
        summarize_thread,
        create_share_link,
        import_shared_thread,
        render_shared_link_page,
    )
except Exception:
    IMPORT_ERROR = traceback.format_exc()
    print(f"[FATAL_IMPORT_ERROR]\n{IMPORT_ERROR}")


@app.route("/api/health", methods=["GET"])
def route_health():
    if IMPORT_ERROR:
        return Response(json.dumps({"status": "error", "import_error": IMPORT_ERROR}), status=500, mimetype="application/json")
    return Response(json.dumps({"status": "ok", "api_dir": _api_dir}), status=200, mimetype="application/json")


@app.route("/api/get_threads", methods=["POST", "GET"])
def route_get_threads():
    if IMPORT_ERROR:
        return Response(json.dumps({"error": "import_failed", "details": IMPORT_ERROR}), status=500, mimetype="application/json")
    try:
        args = request.json or {}
    except Exception:
        args = {}
    result = get_threads(**args)
    return json.dumps(result)


@app.route("/api/create_thread", methods=["POST"])
def route_create_thread():
    if IMPORT_ERROR:
        return Response(json.dumps({"error": "import_failed", "details": IMPORT_ERROR}), status=500, mimetype="application/json")
    try:
        args = request.json or {}
    except Exception:
        args = {}
    result = create_thread(**args)
    return json.dumps(result)


@app.route("/api/delete_thread", methods=["POST"])
def route_delete_thread():
    if IMPORT_ERROR:
        return Response(json.dumps({"error": "import_failed", "details": IMPORT_ERROR}), status=500, mimetype="application/json")
    try:
        args = request.json or {}
    except Exception:
        args = {}
    result = delete_thread(**args)
    return json.dumps(result)


@app.route("/api/summarize_thread", methods=["POST"])
def route_summarize_thread():
    if IMPORT_ERROR:
        return Response(json.dumps({"error": "import_failed", "details": IMPORT_ERROR}), status=500, mimetype="application/json")
    try:
        args = request.json or {}
    except Exception:
        args = {}
    result = summarize_thread(**args)
    return json.dumps(result)


@app.route("/api/create_share_link", methods=["POST"])
def route_create_share_link():
    if IMPORT_ERROR:
        return Response(json.dumps({"error": "import_failed", "details": IMPORT_ERROR}), status=500, mimetype="application/json")
    try:
        args = request.json or {}
    except Exception:
        args = {}
    result = create_share_link(**args)
    return json.dumps(result)


@app.route("/api/import_shared_thread", methods=["POST"])
def route_import_shared_thread():
    if IMPORT_ERROR:
        return Response(json.dumps({"error": "import_failed", "details": IMPORT_ERROR}), status=500, mimetype="application/json")
    try:
        args = request.json or {}
    except Exception:
        args = {}
    result = import_shared_thread(**args)
    return json.dumps(result)


@app.route("/api/chat_streaming", methods=["POST"])
def route_chat_streaming():
    if IMPORT_ERROR:
        def err_gen():
            yield f"data: {json.dumps({'type': 'error', 'message': f'Server error: {IMPORT_ERROR}'})}\n\n"
        return Response(err_gen(), mimetype="text/event-stream")

    try:
        args = request.json or {}
    except Exception:
        args = {}

    forwarded = request.headers.get("x-forwarded-for", "")
    args["client_ip"] = (forwarded.split(",")[0].strip() if forwarded else request.remote_addr or "").strip()

    def generate():
        try:
            for chunk in chat_streaming(**args):
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@app.route("/api/admin_email_health", methods=["GET"])
def route_admin_email_health():
    key = request.args.get("key", "")
    if key != os.environ.get("ADMIN_KEY", "echoo"):
        return Response("Unauthorized", status=401)
    if IMPORT_ERROR:
        return Response(json.dumps({"error": IMPORT_ERROR}), status=500, mimetype="application/json")
    return json.dumps(get_email_health(), ensure_ascii=False)


@app.route("/api/admin_send_test_email", methods=["POST"])
def route_admin_send_test_email():
    key = request.args.get("key", "")
    if key != os.environ.get("ADMIN_KEY", "echoo"):
        return Response("Unauthorized", status=401)
    if IMPORT_ERROR:
        return Response(json.dumps({"error": IMPORT_ERROR}), status=500, mimetype="application/json")
    try:
        args = request.json or {}
    except Exception:
        args = {}
    result = send_test_email(**args)
    code = 200 if result.get("success") else 400
    return Response(json.dumps(result, ensure_ascii=False), status=code, mimetype="application/json")


@app.route("/shared/<share_id>", methods=["GET"])
def route_shared_page(share_id: str):
    if IMPORT_ERROR:
        return Response(f"<h1>Error loading shared page</h1><pre>{IMPORT_ERROR}</pre>", mimetype="text/html", status=500)
    page = render_shared_link_page(share_id=share_id)
    return Response(page, mimetype="text/html")


if __name__ == "__main__":
    app.run(port=5328)
