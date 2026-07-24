#!/usr/bin/env python3
"""
音频转写 + 话题分析完整流程
用法：
    python3 audio_analysis.py <音频文件> [--model tiny|base|small] [--output 报告路径]
"""
import argparse
import logging
import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
_project_root = Path(__file__).parent
sys.path.insert(0, str(_project_root))

from src.processors.topic import analyze_text, generate_text_report

# 尝试导入 opencc 用于繁体转简体
try:
    import opencc
    HAS_OPENC = True
except ImportError:
    HAS_OPENC = False
    logging.warning("[Audio] opencc 未安装，将跳过繁体转简体")

# 尝试导入 whisper
try:
    import whisper
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False
    logging.warning("[Audio] whisper 未安装，将使用模拟数据")


def convert_to_simplified(text: str) -> str:
    """将繁体中文转换为简体中文"""
    if HAS_OPENC:
        converter = opencc.OpenCC('t2s')  # Traditional to Simplified
        return converter.convert(text)
    return text


def transcribe_audio(audio_path: str, model_name: str = "base") -> str:
    """使用 Whisper 转写音频文件"""
    if not HAS_WHISPER:
        raise RuntimeError("whisper 未安装，请先运行: pip install -U openai-whisper")

    print(f"[1/3] 加载 {model_name} 模型...", flush=True)
    model = whisper.load_model(model_name)

    print("[2/3] 模型加载成功！开始转写...", flush=True)
    result = model.transcribe(
        audio_path,
        language="zh",
        fp16=False,
        initial_prompt="以下是简体中文内容："  # 引导模型输出简体
    )

    text = result["text"].strip()
    print(f"[3/3] 转写完成！文本长度: {len(text)} 字符", flush=True)

    # 繁体转简体（双重保险）
    text_simplified = convert_to_simplified(text)
    if text != text_simplified:
        print("  (已自动转换繁体→简体)", flush=True)

    return text_simplified


def analyze_and_report(text: str, output_path: str | None = None) -> str:
    """分析文本并生成报告"""
    print("\n" + "=" * 60)
    print("开始话题分析...")
    print("=" * 60 + "\n")

    # 分析文本
    analysis = analyze_text(text)
    print(f"文本长度: {analysis['text_length']} 字符")
    print(f"句子数量: {analysis['sentence_count']}")
    print(f"\n高频关键词 (Top 20):")
    for word, weight in analysis["keywords"][:20]:
        print(f"  {word}\t权重 {weight:.3f}")

    # 生成报告
    if output_path is None:
        output_path = "/tmp/audio_topic_report.md"

    report_path = generate_text_report(
        analysis,
        output_path,
        title="音频转写话题分析报告"
    )
    print(f"\n报告已生成: {report_path}")

    return report_path


def main():
    parser = argparse.ArgumentParser(description="音频转写 + 话题分析")
    parser.add_argument("audio_file", nargs="?", help="音频文件路径")
    parser.add_argument("--model", default="base", choices=["tiny", "base", "small", "medium"],
                        help="Whisper 模型大小 (默认: base)")
    parser.add_argument("--output", "-o", help="报告输出路径")
    parser.add_argument("--mock", action="store_true", help="使用模拟数据测试")

    args = parser.parse_args()

    if args.mock:
        # 使用模拟数据
        print("[模拟模式] 使用模拟数据测试...\n")
        mock_text = """
        欢迎来到直播间！今天给大家带来一款超火的格子裤，
        红色格子、蓝色格子都有，还有工装裤款式。
        面料是铜氨丝的，非常透气，夏天穿特别舒服。
        尺码从M到XXL，大码也有货。
        想要的朋友扣1，我看看有多少人想要。
        感谢"小星星"的礼物！谢谢支持！
        这个裤子我们是工厂直发，价格比实体店便宜一半。
        今天下单还送运费险，不满意可以退。
        """
        text = mock_text
    else:
        if not args.audio_file:
            print("错误: 请指定音频文件或添加 --mock 参数")
            parser.print_help()
            sys.exit(1)

        if not os.path.exists(args.audio_file):
            print(f"错误: 文件不存在: {args.audio_file}")
            sys.exit(1)

        # 转写音频
        text = transcribe_audio(args.audio_file, args.model)

    # 保存转写结果
    transcription_path = "/tmp/transcription_result.txt"
    with open(transcription_path, "w") as f:
        f.write(text)
    print(f"\n转写结果已保存: {transcription_path}")
    print(f"文本内容: {text[:100]}..." if len(text) > 100 else f"文本内容: {text}")

    # 分析并生成报告
    report_path = analyze_and_report(text, args.output)

    # 显示完整报告
    with open(report_path, "r") as f:
        content = f.read()
    print("\n" + "=" * 60)
    print("完整报告:")
    print("=" * 60 + "\n")
    print(content)

    return report_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    main()
