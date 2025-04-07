# /// script
# requires-python = "==3.11.11"
# dependencies = [
# "aiohttp",
# "python-socketio",
# ]
# ///


import base64
import os
import ssl
import uuid

import socketio
from aiohttp import web

sio = socketio.AsyncServer(
    cors_allowed_origins="*", max_http_buffer_size=50 * 1024 * 1024
)
app = web.Application()
sio.attach(app)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

file_chunks = {}


async def index(request):
    with open("index.html") as f:
        return web.Response(text=f.read(), content_type="text/html")


async def download_file(request):
    filename = request.match_info["filename"]
    original_name = request.query.get("name", filename)

    filepath = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(filepath):
        resp = web.FileResponse(filepath)
        resp.headers["Content-Disposition"] = f'attachment; filename="{original_name}"'
        return resp
    return web.Response(status=404, text="File not found")


@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")


@sio.event
async def chat_message(sid, data):
    print(f"Message from {sid}: {data}")
    await sio.emit("chat_message", data, skip_sid=sid)


@sio.event
async def file_chunk(sid, data):
    try:
        chunk_id = data.get("chunkId")
        total_chunks = data.get("totalChunks")
        current_chunk = data.get("currentChunk")
        file_id = data.get("fileId")
        original_name = data.get("originalName", "")
        file_data = data.get("chunk")

        if file_id not in file_chunks:
            file_chunks[file_id] = {
                "chunks": [""] * total_chunks,
                "received": 0,
                "originalName": original_name,
            }

        file_chunks[file_id]["chunks"][current_chunk] = file_data
        file_chunks[file_id]["received"] += 1

        await sio.emit(
            "chunk_received",
            {
                "fileId": file_id,
                "chunkId": chunk_id,
                "progress": (file_chunks[file_id]["received"] / total_chunks) * 100,
            },
            room=sid,
        )

        if file_chunks[file_id]["received"] == total_chunks:
            complete_data = "".join(file_chunks[file_id]["chunks"])

            file_ext = (
                os.path.splitext(original_name)[1] if "." in original_name else ""
            )
            unique_filename = f"{uuid.uuid4()}{file_ext}"

            file_path = os.path.join(UPLOAD_DIR, unique_filename)
            file_content = base64.b64decode(
                complete_data.split(",")[1] if "," in complete_data else complete_data
            )

            with open(file_path, "wb") as f:
                f.write(file_content)

            file_info = {
                "id": unique_filename,
                "filename": original_name,
                "url": f"/download/{unique_filename}?name={original_name}",
                "sender": sid,
                "size": len(file_content),
            }

            print(f"File uploaded: {original_name} ({len(file_content)} bytes)")

            await sio.emit("file_message", file_info, skip_sid=sid)

            file_info["isSender"] = True
            await sio.emit("file_message", file_info, room=sid)

            del file_chunks[file_id]

    except Exception as e:
        print(f"Error handling file chunk: {str(e)}")
        await sio.emit(
            "error", {"message": f"Failed to process file: {str(e)}"}, room=sid
        )


@sio.event
async def disconnect(sid):
    print(f"Client disconnected: {sid}")
    for file_id in list(file_chunks.keys()):
        if "sender" in file_chunks[file_id] and file_chunks[file_id]["sender"] == sid:
            del file_chunks[file_id]


app.router.add_static("/static", "static")
app.router.add_get("/", index)
app.router.add_get("/download/{filename}", download_file)

ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
ssl_context.load_cert_chain("fullchain.pem", "privkey.pem")


if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=443, ssl_context=ssl_context)
