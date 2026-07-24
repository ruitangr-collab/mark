#!/usr/bin/env python3
"""
抖音直播间5分钟监控 + 话题分析
room_id: 7659205935478393651
"""
import asyncio
import sys
import os
import signal
from pathlib import Path
from datetime import datetime

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import config
from src.database.db import BatchWriter, init_db, upsert_live_session, end_live_session
from src.database.models import Platform, Session, SessionStatus, MessageType
from src.collectors.douyin import DouyinCollector
from src.processors.topic import analyze_session, generate_report

# 监控配置
ROOM_ID = "7659205935478393651"
MONITOR_SECONDS = 300  # 5分钟
DB_PATH = "livescope.db"

result_file = PROJECT_ROOT / "last_monitor_result.txt"


async def monitor_and_analyze():
    room_id = ROOM_ID
    session_id = f"douyin_{room_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    print(f"[监控] 开始监控直播间 {room_id}")
    print(f"[监控] 会话ID: {session_id}")
    print(f"[监控] 计划监控时长: {MONITOR_SECONDS} 秒 ({MONITOR_SECONDS//60} 分钟)")
    print(f"[监控] 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 50)

    session = Session(
        id=session_id,
        platform=Platform.DOUYIN,
        streamer_id=room_id,
        room_id=room_id,
        status=SessionStatus.LIVE,
    )
    await init_db()
    await upsert_live_session(session)
    
    write_q = asyncio.Queue(maxsize=10000)
    collector = DouyinCollector(session=session, queue=write_q, room_id=room_id)
    writer = BatchWriter(queue=write_q, interval=2)
    writer.start()

    # 设置超时
    try:
        await asyncio.wait_for(collector.start(), timeout=MONITOR_SECONDS)
    except asyncio.TimeoutError:
        print(f"\n[监控] 达到 {MONITOR_SECONDS} 秒，停止采集...")
    except Exception as e:
        print(f"\n[监控] 采集异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await collector.stop()
        await writer.stop()
        await end_live_session(session_id)
        print(f"[监控] 采集停止。结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 数据分析
    print("\n" + "=" * 50)
    print("[分析] 开始分析弹幕话题...")
    
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    
    engine = create_engine(f"sqlite:///{DB_PATH}")
    with engine.connect() as conn:
        # 统计消息
        result = conn.execute(text(
            "SELECT msg_type, COUNT(*) as cnt FROM messages WHERE session_id = :sid GROUP BY msg_type"
        ), {"sid": session_id})
        stats = {row[0]: row[1] for row in result}
        
        total_chat = stats.get("chat", 0)
        total_enter = stats.get("enter", 0)
        total_leave = stats.get("leave", 0)
        total_gift = stats.get("gift", 0)
        total_like = stats.get("like", 0)
    
    print(f"[分析] 采集统计:")
    print(f"  弹幕: {total_chat} 条")
    print(f"  进场: {total_enter} 条")
    print(f"  离场: {total_leave} 条")
    print(f"  礼物: {total_gift} 条")
    print(f"  点赞: {total_like} 条")
    
    if total_chat == 0:
        print("[分析] 没有弹幕数据，无法分析话题。")
        with open(result_file, "w") as f:
            f.write(f"会话ID: {session_id}\n")
            f.write(f"监控时长: {MONITOR_SECONDS} 秒\n")
            f.write(f"弹幕: 0 条（直播间可能未开播或无人发言）\n")
        return
    
    # 话题分析
    analysis = analyze_session(DB_PATH, session_id)
    
    print(f"\n[分析] 高频关键词 (Top 20):")
    for word, weight in analysis["keywords"][:20]:
        print(f"  {word}\t权重 {weight:.4f}")
    
    # 生成报告
    report_path = generate_report(analysis, str(PROJECT_ROOT / f"topic_report_{session_id}.md"))
    print(f"\n[分析] 报告已生成: {report_path}")
    
    # 写结果文件
    with open(result_file, "w") as f:
        f.write(f"会话ID: {session_id}\n")
        f.write(f"监控时长: {MONITOR_SECONDS} 秒\n")
        f.write(f"弹幕: {total_chat} 条\n")
        f.write(f"进场: {total_enter} 条\n")
        f.write(f"报告: {report_path}\n")
    
    print(f"\n[完成] 结果已保存到: {result_file}")


if __name__ == "__main__":
    asyncio.run(monitor_and_analyze())
