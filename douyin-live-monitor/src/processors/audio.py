#!/usr/bin/env python3
"""
音频处理器：从直播流提取音频 + Whisper 转写
"""
import asyncio
import subprocess
import tempfile
import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable

logger = logging.getLogger("AudioProcessor")

# FFmpeg 路径（优先用 imageio-ffmpeg 自带的，否则用系统 ffmpeg）
try:
    import imageio_ffmpeg
    FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_BIN = "ffmpeg"


class AudioProcessor:
    """
    从直播流实时提取音频片段并转写
    
    使用方式：
        processor = AudioProcessor(stream_url, session_id, db_path)
        await processor.start(duration=300)  # 录制并转写 5 分钟
    """
    
    def __init__(
        self,
        stream_url: str,
        session_id: str,
        db_path: str = "livescope.db",
        segment_seconds: int = 30,
        whisper_model: str = "base",  # tiny/base/small/medium/large
        on_transcription: Optional[Callable] = None,
    ):
        self.stream_url = stream_url
        self.session_id = session_id
        self.db_path = db_path
        self.segment_seconds = segment_seconds
        self.whisper_model = whisper_model
        self.on_transcription = on_transcription
        
        self._running = False
        self._whisper = None  # lazy load
        self._temp_dir = tempfile.mkdtemp(prefix="douyin_audio_")
        
    async def start(self, duration: int = 300):
        """
        开始录制并转写
        
        Args:
            duration: 总录制时长（秒）
        """
        self._running = True
        logger.info(f"[Audio] 开始音频采集 session={self.session_id}")
        
        # 启动 FFmpeg 拉流
        segment_idx = 0
        start_time = datetime.now()
        
        while self._running:
            elapsed = (datetime.now() - start_time).total_seconds()
            if elapsed >= duration:
                break
            
            # 录制一个音频片段
            segment_file = os.path.join(
                self._temp_dir,
                f"segment_{segment_idx:04d}.wav"
            )
            
            logger.info(f"[Audio] 录制片段 {segment_idx} ({self.segment_seconds}s)")
            success = await self._record_segment(segment_file)
            
            if success:
                # 转写
                logger.info(f"[Audio] 转写片段 {segment_idx}")
                text = await self._transcribe(segment_file)
                
                if text:
                    logger.info(f"[Audio] 转写结果: {text[:100]}...")
                    # 保存到数据库
                    await self._save_transcription(text, segment_idx)
                    
                    # 回调
                    if self.on_transcription:
                        self.on_transcription(text, segment_idx)
                else:
                    logger.warning(f"[Audio] 片段 {segment_idx} 转写失败或为空")
                
                # 清理音频文件
                try:
                    os.remove(segment_file)
                except:
                    pass
            else:
                logger.warning(f"[Audio] 片段 {segment_idx} 录制失败")
                await asyncio.sleep(5)  # 等一下再重试
            
            segment_idx += 1
        
        logger.info(f"[Audio] 音频采集结束，共 {segment_idx} 个片段")
    
    async def _record_segment(self, output_file: str) -> bool:
        """用 FFmpeg 录制一个音频片段"""
        cmd = [
            FFMPEG_BIN,
            "-i", self.stream_url,
            "-t", str(self.segment_seconds),  # 时长
            "-ac", "1",  # 单声道
            "-ar", "16000",  # 16kHz（Whisper 推荐）
            "-acodec", "pcm_s16le",  # WAV PCM
            "-y",  # 覆盖输出文件
            output_file,
        ]
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            
            if proc.returncode == 0 and os.path.exists(output_file):
                return True
            else:
                err_msg = stderr.decode('utf-8', errors='ignore') if stderr else 'unknown error'
                logger.warning(f"[Audio] FFmpeg 错误: {err_msg[-200:]}")
                return False
        except Exception as e:
            logger.error(f"[Audio] FFmpeg 执行失败: {e}")
            return False
    
    async def _transcribe(self, audio_file: str) -> str:
        """用 Whisper 转写音频文件"""
        # Lazy load Whisper（避免启动时加载大模型）
        if self._whisper is None:
            try:
                import whisper
                logger.info(f"[Audio] 加载 Whisper 模型: {self.whisper_model}")
                self._whisper = whisper.load_model(self.whisper_model)
                logger.info(f"[Audio] Whisper 模型加载完成")
            except ImportError:
                logger.error("[Audio] Whisper 未安装，请运行: pip install openai-whisper")
                return ""
        
        try:
            # Whisper 转写（在独立线程中运行，避免阻塞事件循环）
            result = await asyncio.to_thread(
                self._whisper.transcribe,
                audio_file,
                language="zh",  # 指定中文
                fp16=False,  # CPU 模式
            )
            return result["text"].strip()
        except Exception as e:
            logger.error(f"[Audio] 转写失败: {e}")
            return ""
    
    async def _save_transcription(self, text: str, segment_idx: int):
        """保存转写结果到数据库"""
        from sqlalchemy import create_engine, text
        from datetime import datetime
        
        engine = create_engine(f"sqlite:///{self.db_path}")
        with engine.connect() as conn:
            # 创建 audio_transcriptions 表（如果不存在）
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS audio_transcriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    segment_idx INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                )
            """))
            conn.execute(text("""
                INSERT INTO audio_transcriptions (session_id, segment_idx, text, timestamp)
                VALUES (:sid, :idx, :text, :ts)
            """), {
                "sid": self.session_id,
                "idx": segment_idx,
                "text": text,
                "ts": datetime.now(),
            })
            conn.commit()
    
    def stop(self):
        """停止采集"""
        self._running = False
        logger.info("[Audio] 收到停止信号")


async def get_stream_url(room_id: str, ttwid: str = "") -> str:
    """
    获取抖音直播间流地址
    
    这是一个简化实现，实际需要调用抖音 API。
    如果失败，返回空字符串。
    
    用户可以手动提供流地址作为备用。
    """
    # TODO: 实现完整的流地址获取逻辑
    # 参考：https://github.com/... (抖音直播流地址获取)
    
    # 临时方案：尝试从配置文件读取
    config_file = Path("stream_urls.json")
    if config_file.exists():
        import json
        urls = json.loads(config_file.read_text())
        if room_id in urls:
            return urls[room_id]
    
    logger.warning(f"[Audio] 无法自动获取流地址 for room {room_id}")
    logger.warning("[Audio] 请手动在 stream_urls.json 中配置流地址")
    return ""


if __name__ == "__main__":
    # 测试：转写一个本地音频文件
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python audio.py <audio_file>")
        sys.exit(1)
    
    audio_file = sys.argv[1]
    
    async def test():
        processor = AudioProcessor(
            stream_url="",  # 不需要流地址，直接转写文件
            session_id="test",
            whisper_model="base",
        )
        
        # 直接测试转写
        if processor._whisper is None:
            import whisper
            processor._whisper = whisper.load_model("base")
        
        print("转写中...")
        result = await processor._transcribe(audio_file)
        print(f"结果: {result}")
    
    asyncio.run(test())
