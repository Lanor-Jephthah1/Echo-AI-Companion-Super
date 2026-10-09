import os
import json
from flask import Flask, request, Response, stream_with_context
from flask_cors import CORS
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

app = Flask(__name__)
CORS(app)

@app.route("/api/get_threads", methods=["POST"])
def route_get_threads():
    args = request.json or {}
    result = get_threads(**args)
    return json.dumps(result)

@app.route("/api/create_thread", methods=["POST"])
def route_create_thread():
    args = request.json or {}
    result = create_thread(**args)
    return json.dumps(result)

@app.route("/api/delete_thread", methods=["POST"])
def route_delete_thread():
    args = request.json or {}
    result = delete_thread(**args)
    return json.dumps(result)

@app.route("/api/summarize_thread", methods=["POST"])
def route_summarize_thread():
    args = request.json or {}
    result = summarize_thread(**args)
    return json.dumps(result)

@app.route("/api/create_share_link", methods=["POST"])
def route_create_share_link():
    args = request.json or {}
    result = create_share_link(**args)
    return json.dumps(result)

@app.route("/api/import_shared_thread", methods=["POST"])
def route_import_shared_thread():
    args = request.json or {}
    result = import_shared_thread(**args)
    return json.dumps(result)

@app.route("/api/chat_streaming", methods=["POST"])
def route_chat_streaming():
    args = request.json or {}
    
    def generate():
        for chunk in chat_streaming(**args):
            yield f"data: {json.dumps(chunk)}\n\n"
            
    return Response(stream_with_context(generate()), mimetype="text/event-stream")


@app.route("/api/admin_email_health", methods=["GET"])
def route_admin_email_health():
    key = request.args.get("key", "")
    if key != os.environ.get("ADMIN_KEY", "echoo"):
        return Response("Unauthorized", status=401)
    return json.dumps(get_email_health(), ensure_ascii=False)


@app.route("/api/admin_send_test_email", methods=["POST"])
def route_admin_send_test_email():
    key = request.args.get("key", "")
    if key != os.environ.get("ADMIN_KEY", "echoo"):
        return Response("Unauthorized", status=401)
    args = request.json or {}
    result = send_test_email(**args)
    code = 200 if result.get("success") else 400
    return Response(json.dumps(result, ensure_ascii=False), status=code, mimetype="application/json")


@app.route("/shared/<share_id>", methods=["GET"])
def route_shared_page(share_id: str):
    page = render_shared_link_page(share_id=share_id)
    return Response(page, mimetype="text/html")

# For local testing
if __name__ == "__main__":
    app.run(port=5328)
