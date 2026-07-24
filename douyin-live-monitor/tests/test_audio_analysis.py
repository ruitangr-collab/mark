#!/usr/bin/env python3
"""
音频转写 + 话题分析 完整流程测试
支持两种模式：
1. 真实模式：需要安装 Whisper（会自动检测）
2. 模拟模式：用模拟数据测试分析流程（默认）

使用：
  # 模拟模式（快速测试分析流程）
  python3 test_audio_analysis.py --mock
  
  # 真实模式（需要 Whisper）
  python3 test_audio_analysis.py /path/to/audio.aac
  
  # 只分析已有的转写文本
  python3 test_audio_analysis.py --text "这是一段测试文本..."
"""
import asyncio
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime

# 添加项目路径
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.processors.topic import analyze_text, generate_text_report


def convert_audio_to_wav(audio_file: str, output_wav: str = None) -> str:
    """
    将音频文件转换为 WAV 格式（16kHz, mono）
    需要 ffmpeg 或 imageio-ffmpeg
    """
    if output_wav is None:
        output_wav = audio_file.rsplit('.', 1)[0] + '.wav'
    
    # 尝试用 imageio-ffmpeg
    try:
        import imageio_ffmpeg
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg_bin = 'ffmpeg'
    
    cmd = [
        ffmpeg_bin,
        '-i', audio_file,
        '-ac', '1',      # 单声道
        '-ar', '16000',  # 16kHz
        '-y',            # 覆盖
        output_wav
    ]
    
    print(f"[转换] {audio_file} -> {output_wav}")
    ret = os.system(' '.join(cmd))
    if ret != 0:
        raise RuntimeError("FFmpeg 转换失败，请检查 ffmpeg 是否安装")
    
    return output_wav


def transcribe_audio(audio_file: str, model_size: str = 'base') -> str:
    """
    使用 Whisper 转写音频文件
    """
    try:
        import whisper
    except ImportError:
        print("[错误] Whisper 未安装！")
        print("[安装] 请运行: pip install openai-whisper")
        print("[备用] 或使用模拟模式: python3 test_audio_analysis.py --mock")
        sys.exit(1)
    
    print(f"[转写] 加载 Whisper 模型: {model_size}")
    model = whisper.load_model(model_size)
    
    print(f"[转写] 开始转写: {audio_file}")
    result = model.transcribe(audio_file, language='zh', fp16=False)
    
    text = result['text'].strip()
    print(f"[转写] 完成！文本长度: {len(text)} 字符")
    
    return text


def analyze_transcription(text: str, output_report: str = None):
    """
    分析转写文本的话题
    """
    print(f"\n[分析] 开始分析转写文本...")
    print(f"[分析] 文本长度: {len(text)} 字符")
    
    # 使用 topic 模块分析
    analysis = analyze_text(text)
    
    print(f"\n[结果] 高频关键词 (Top 20):")
    for word, weight in analysis['keywords'][:20]:
        print(f"  {word}\t权重 {weight:.4f}")
    
    # 生成报告
    if output_report:
        report_path = generate_text_report(
            analysis, 
            output_report,
            title="音频转写话题分析报告"
        )
        print(f"\n[报告] 已生成: {report_path}")
        return report_path
    
    return None


def mock_test():
    """
    模拟测试：用模拟的转写文本测试分析流程
    """
    print("[模拟] 使用模拟数据测试分析流程...")
    
    # 模拟的转写文本（模拟一个卖衣服的直播间）
    mock_text = """
    欢迎新进来的朋友，今天给大家带来的是我们的新款格子裤。
    这条格子裤是红格子的，非常显白，黑皮黄皮都可以穿。
    格子裤的面料是铜氨丝的，非常透气，夏天穿也不会闷。
    有没有想要九分裤的？有的扣一。
    这条裤子有大码，大码可以穿到160斤。
    格子的颜色有红色、蓝色、白色、粉色，还有杏色。
    裤脚是抽绳的，可以调节松紧。
    谢谢抱抱，感谢支持。
    再试一下红色格子裤，大家看这个颜色是不是很显白？
    工装裤也有，工装裤是宽松版的，遮肉效果很好。
    运动裤是新款，侧边有条纹，很减龄。
    谢谢亲亲的礼物，感谢支持。
    有没有想要看格子上衣的？有的扣一。
    半袖也有，格子半袖搭配格子裤，一套效果很好。
    衣服的面料是棉的，很舒服。
    谢谢大家的关注，喜欢的抓紧时间拍。
    """
    
    return mock_text


def main():
    parser = argparse.ArgumentParser(description='音频转写 + 话题分析')
    parser.add_argument('audio_file', nargs='?', help='音频文件路径')
    parser.add_argument('--text', help='直接提供转写文本（跳过转写步骤）')
    parser.add_argument('--mock', action='store_true', help='模拟模式（用模拟数据测试）')
    parser.add_argument('--model', default='base', help='Whisper 模型大小 (tiny/base/small/medium/large)')
    parser.add_argument('--output', '-o', help='报告输出路径')
    
    args = parser.parse_args()
    
    # 确定要分析的文本
    if args.mock:
        text = mock_test()
    elif args.text:
        text = args.text
        print(f"[输入] 使用提供的文本（{len(text)} 字符）")
    elif args.audio_file:
        audio_file = args.audio_file
        
        # 转换音频格式
        if not audio_file.endswith('.wav'):
            wav_file = convert_audio_to_wav(audio_file)
        else:
            wav_file = audio_file
        
        # 转写
        text = transcribe_audio(wav_file, args.model)
        
        # 保存转写结果
        transcript_file = wav_file.rsplit('.', 1)[0] + '_transcript.txt'
        with open(transcript_file, 'w') as f:
            f.write(text)
        print(f"[转写] 转写结果已保存: {transcript_file}")
    else:
        parser.print_help()
        sys.exit(1)
    
    # 分析
    output = args.output or f"audio_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report = analyze_transcription(text, output)
    
    print(f"\n[完成] 分析完成！")
    if report:
        print(f"[报告] {report}")


if __name__ == '__main__':
    main()
