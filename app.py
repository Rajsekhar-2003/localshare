import os
import shutil
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi import WebSocket, WebSocketDisconnect
from typing import List

# Configuration
UPLOAD_DIR = Path("./uploads")
CHUNK_DIR = Path("./chunks")

# Create directories if they don't exist
UPLOAD_DIR.mkdir(exist_ok=True)
CHUNK_DIR.mkdir(exist_ok=True)

app = FastAPI(title="LocalShare LAN File Sharing")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

active_connections: List[WebSocket] = []

@app.get("/files")
async def list_files():
    """List all shared files"""
    files = []
    for f in UPLOAD_DIR.iterdir():
        if f.is_file():
            stat = f.stat()
            files.append({
                "name": f.name,
                "size": stat.st_size,
                "modified": stat.st_mtime
            })
    return sorted(files, key=lambda x: x["modified"], reverse=True)

@app.delete("/files/{filename}")
async def delete_file(filename: str):
    """Delete a file"""
    file_path = UPLOAD_DIR / filename
    if file_path.exists():
        file_path.unlink()
        return {"ok": True}
    raise HTTPException(404, "File not found")

@app.get("/download/{filename}")
async def download_file(filename: str):
    """Download a file"""
    file_path = UPLOAD_DIR / filename
    if not file_path.exists():
        raise HTTPException(404)
    return FileResponse(file_path, filename=filename)

@app.post("/upload/chunk")
async def upload_chunk(
    filename: str = Form(...),
    chunkIndex: int = Form(...),
    totalChunks: int = Form(...),
    uploadId: str = Form(...),
    fileSize: int = Form(...),
    chunk: UploadFile = File(...),
):
    """Handle chunked upload with resume support"""
    chunk_dir = CHUNK_DIR / uploadId
    chunk_dir.mkdir(exist_ok=True)
    chunk_path = chunk_dir / f"{chunkIndex}"
    content = await chunk.read()
    with open(chunk_path, "wb") as f:
        f.write(content)
    
    # Check if all chunks received
    uploaded_chunks = len(list(chunk_dir.iterdir()))
    if uploaded_chunks == totalChunks:
        # Assemble final file
        final_path = UPLOAD_DIR / filename
        with open(final_path, "wb") as outfile:
            for i in range(totalChunks):
                part = chunk_dir / str(i)
                if part.exists():
                    outfile.write(part.read_bytes())
                    part.unlink()
        shutil.rmtree(chunk_dir)
        
        # Notify all WebSocket clients
        for ws in active_connections:
            await ws.send_json({"type": "upload_complete", "filename": filename})
        
        return {"status": "complete"}
    
    return {"status": "chunk_received", "chunk": chunkIndex}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for live updates"""
    await websocket.accept()
    active_connections.append(websocket)
    
    # Send current file list
    files = []
    for f in UPLOAD_DIR.iterdir():
        if f.is_file():
            stat = f.stat()
            files.append({
                "name": f.name,
                "size": stat.st_size,
                "modified": stat.st_mtime
            })
    await websocket.send_json({"type": "file_list", "files": files})
    
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)

@app.get("/manifest.json")
async def manifest():
    """PWA manifest"""
    return JSONResponse({
        "name": "LocalShare",
        "short_name": "LocalShare",
        "start_url": "/",
        "display": "standalone",
        "theme_color": "#0f172a",
        "background_color": "#0f172a",
        "icons": [
            {
                "src": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect width='100' height='100' fill='%233b82f6'/%3E%3Ctext x='50' y='67' font-size='50' text-anchor='middle' fill='white'%3E📡%3C/text%3E%3C/svg%3E",
                "sizes": "192x192",
                "type": "image/png"
            }
        ]
    })

@app.get("/sw.js")
async def sw():
    from fastapi.responses import Response
    return Response(
        """self.addEventListener('fetch', event => {});
        self.addEventListener('install', () => self.skipWaiting());
        """,
        media_type="application/javascript"
    )

@app.get("/")
async def root():
    with open("index.html", "r") as f:
        return HTMLResponse(f.read())

if __name__ == "__main__":
    import uvicorn
    import socket
    
    # Get local IP
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = '127.0.0.1'
    finally:
        s.close()
    
    print("\n" + "="*50)
    print("🚀 LocalShare Server Running (No Login Required)")
    print("="*50)
    print(f"📁 Upload directory: {UPLOAD_DIR.absolute()}")
    print(f"\n📍 Access URLs:")
    print(f"   → Local:    http://localhost:8000")
    print(f"   → LAN:      http://{local_ip}:8000")
    print(f"\n📱 QR Code URL: http://{local_ip}:8000")
    print("\n💡 Features:")
    print("   • No password required")
    print("   • All devices on same Wi-Fi/LAN can connect")
    print("   • Drag & drop files/folders")
    print("   • Supports 5GB+ files with resume")
    print("   • Dark mode available")
    print("\n⚠️  Press Ctrl+C to stop server")
    print("="*50 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
