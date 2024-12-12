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
            'format': 'best',  # 使用最宽松的格式选择
            'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': False,
            'extract_flat': False,
            'nocheckcertificate': True,
            'ignoreerrors': True,  # 忽略错误继续下载
            'logtostderr': False,
            'verbose': True,
            # 添加代理配置
            'proxy': 'http://127.0.0.1:10808',
            # 添加重试机制
            'retries': 10,
            'fragment_retries': 10,
            'skip_unavailable_fragments': True,
            'keepvideo': True,
        }
        
        try:
            # 获取视频信息
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info("Extracting video info...")
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    raise Exception("Could not fetch video info")
                
                logger.info(f"Successfully fetched info for video: {info.get('title', 'Unknown')}")
                
                # 开始异步下载
                asyncio.create_task(download_task(url, ydl_opts, info))
                
                return JSONResponse({
                    "status": "success",
                    "message": "Download started",
                    "title": info.get("title", "Unknown")
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

async def download_task(url: str, ydl_opts: dict, info: dict):
    try:
        filename = os.path.join(DOWNLOAD_DIR, f"{info['title']}.mp4")
        logger.info(f"Starting download for video: {info['title']}")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # 获取文件大小
        file_size = os.path.getsize(filename)
        
        # 获取当前时间
        current_time = datetime.now()
        
        # 创建视频信息
        video_info = {
            "title": info["title"],
            "url": url,
            "download_time": current_time.strftime("%Y-%m-%d %H:%M:%S"),
            "file_size": humanize.naturalsize(file_size),
            "duration": str(timedelta(seconds=int(info.get("duration", 0)))),
            "filename": os.path.basename(filename)
        }
        
        videos.append(video_info)
        logger.info(f"Successfully downloaded and processed video: {filename}")
        
    except Exception as e:
        logger.error(f"Download task error: {str(e)}")
        raise

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