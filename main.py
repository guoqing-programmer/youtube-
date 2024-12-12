from fastapi import FastAPI, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
import os
import asyncio
from datetime import datetime, timedelta
import humanize
import logging
import platform
import subprocess
from typing import Dict

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 创建必要的目录
STATIC_DIR = "static"
DOWNLOAD_DIR = "downloads"
TEMPLATES_DIR = "templates"

# 确保所有必要的目录都存在
for directory in [STATIC_DIR, DOWNLOAD_DIR, TEMPLATES_DIR]:
    try:
        os.makedirs(directory, exist_ok=True)
    except Exception as e:
        logger.error(f"Could not create directory {directory}: {str(e)}")
        raise

app = FastAPI()

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录
app.mount("/downloads", StaticFiles(directory=DOWNLOAD_DIR), name="downloads")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 初始化模板引擎
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# 存储视频信息的列表
videos = []

# 添加下载进度存储
download_progress: Dict[str, dict] = {}

@app.get("/")
async def home(request: Request):
    logger.info("Accessing home page")
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "videos": videos}
    )

@app.post("/download")
async def download_video(request: Request):
    try:
        data = await request.json()
        url = data.get("url", "").strip()
        
        logger.info(f"Received download request for URL: {url}")
        
        if not url:
            return JSONResponse({
                "status": "error",
                "message": "URL is required"
            }, status_code=400)
        
        # 更新的 yt-dlp 配置
        ydl_opts = {
            'format': 'best',
            'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': False,
            'progress_hooks': [progress_hook],  # 添加进度钩子
            'nocheckcertificate': True,
            'ignoreerrors': True,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info("Extracting video info...")
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    raise Exception("Could not fetch video info")
                
                # 初始化进度信息
                download_id = str(len(download_progress))
                download_progress[download_id] = {
                    'status': 'starting',
                    'progress': 0,
                    'title': info.get('title', 'Unknown'),
                    'speed': '0 KB/s',
                    'eta': 'Unknown',
                    'file_path': ''
                }
                
                # 开始异步下载
                asyncio.create_task(download_task(url, ydl_opts, info, download_id))
                
                return JSONResponse({
                    "status": "success",
                    "message": "Download started",
                    "title": info.get("title", "Unknown"),
                    "download_id": download_id
                })
                
        except Exception as e:
            logger.error(f"Error during video info extraction: {str(e)}")
            return JSONResponse({
                "status": "error",
                "message": f"Could not fetch video info: {str(e)}"
            }, status_code=400)
            
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        return JSONResponse({
            "status": "error",
            "message": f"Request processing failed: {str(e)}"
        }, status_code=400)

# 添加进度钩子函数
def progress_hook(d):
    if d['status'] == 'downloading':
        download_id = d.get('download_id', '0')
        if download_id in download_progress:
            download_progress[download_id].update({
                'status': 'downloading',
                'progress': d.get('percentage', 0),
                'speed': d.get('speed', 0),
                'eta': d.get('eta', 'Unknown')
            })
    elif d['status'] == 'finished':
        download_id = d.get('download_id', '0')
        if download_id in download_progress:
            download_progress[download_id]['status'] = 'finished'

# 修改下载任务函数
async def download_task(url: str, ydl_opts: dict, info: dict, download_id: str):
    try:
        filename = os.path.join(DOWNLOAD_DIR, f"{info['title']}.mp4")
        logger.info(f"Starting download for video: {info['title']}")
        
        # 更新ydl_opts添加download_id
        ydl_opts['progress_hooks'][0].__defaults__ = ({'download_id': download_id},)
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # 获取文件大小
        file_size = os.path.getsize(filename)
        
        # 获取当前时间
        current_time = datetime.now()
        
        # 获取绝对路径
        abs_path = os.path.abspath(filename)
        
        # 创建视频信息
        video_info = {
            "title": info["title"],
            "url": url,
            "download_time": current_time.strftime("%Y-%m-%d %H:%M:%S"),
            "file_size": humanize.naturalsize(file_size),
            "duration": str(timedelta(seconds=int(info.get("duration", 0)))),
            "filename": os.path.basename(filename),
            "file_path": abs_path,
            "folder_path": os.path.dirname(abs_path)
        }
        
        videos.append(video_info)
        
        # 更新下载进度信息
        if download_id in download_progress:
            download_progress[download_id].update({
                'status': 'completed',
                'progress': 100,
                'file_path': abs_path
            })
        
        logger.info(f"Successfully downloaded and processed video: {filename}")
        
    except Exception as e:
        logger.error(f"Download task error: {str(e)}")
        if download_id in download_progress:
            download_progress[download_id].update({
                'status': 'error',
                'error': str(e)
            })
        raise

# 添加获取下载进度的端点
@app.get("/progress/{download_id}")
async def get_progress(download_id: str):
    if download_id not in download_progress:
        raise HTTPException(status_code=404, detail="Download not found")
    return JSONResponse(download_progress[download_id])

# 添加打开文件夹的端点
@app.post("/open-folder")
async def open_folder(request: Request):
    try:
        data = await request.json()
        folder_path = data.get("path")
        
        if not folder_path or not os.path.exists(folder_path):
            return JSONResponse({
                "status": "error",
                "message": "Invalid folder path"
            }, status_code=400)
        
        # 根据操作系统打开文件夹
        if platform.system() == "Windows":
            os.startfile(folder_path)
        elif platform.system() == "Darwin":  # macOS
            subprocess.Popen(["open", folder_path])
        else:  # Linux
            subprocess.Popen(["xdg-open", folder_path])
            
        return JSONResponse({
            "status": "success",
            "message": "Folder opened"
        })
        
    except Exception as e:
        logger.error(f"Error opening folder: {str(e)}")
        return JSONResponse({
            "status": "error",
            "message": str(e)
        }, status_code=500)

@app.get("/videos")
async def get_videos():
    return JSONResponse({"videos": videos})

# 添加错误处理
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception handler caught: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"message": f"Internal server error: {str(exc)}"}
    ) 