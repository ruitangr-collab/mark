#!/usr/bin/env python3
"""
抖音评论提取公共模块（2026-09 验证版）
keyword_extract.py / account_analyzer.py 共享：
  - RENDER_DATA 解码（URL编码优先，base64 回退）
  - 登录态判断与扫码等待
  - 评论文本过滤（含播放器控件/时间戳噪音）
  - 评论提取（RENDER_DATA + DOM 文本双通道）
"""
import re, time, base64, html as html_mod
from urllib.parse import unquote

# 页面控件/导航噪音词（评论区抓取时剔除）
CONTROL_WORDS = [
    '许可证', '备案', '举报', '电话', '邮箱', '京ICP', '©', '版权',
    '算法', '饭圈', '广播', '网络文化', '互联网', '药品', '器械',
    '宗教', '投诉', '客服', '登录', '注册', '搜索', '首页',
    '电子营业执照', '广告投放', '友情链接', '站点地图', '加入我们',
    '联系我们', '用户服务协议', '隐私政策', '账号找回', '抖音电商',
    '观看历史', '连播', '我的作品', '点击加载更多', '放映厅',
    '阅读全文', '短视频', '直播', '下载抖音', '创作者学习中心',
    '创作者中心', '作者赞过', '听抖音', 'AI抖音', '读屏',
    '在线状态', '隐私设置', '热门：', '大家都在搜', '作品数据',
    '稍后再看', '网页全屏', '进入全屏', '高清', '清屏', '倍速',
    '画质', '弹幕', '音效', '字幕', '暂停', '静音', '下载抖音精选',
    '电子营业执照', '人服证字', '网络谣言', '曝光台', '举报',
    # 2026-09 新增：右侧信息流/侧栏/章节摘要等 UI 噪音
    '壁纸', '重播', '投稿', '充钻石', '客户端', '截图', '小窗模式',
    '抢首评', '暂无评论', '暂无会话', '全部评论', '我的收藏', '我的喜欢',
    '我的预约', '我的订单', '认证徽章', '视频管理', '推荐视频', '店铺账号',
    '章节要点', '见面会内容', 'AI音乐创作', '拖动视频',
    '留下你的精彩评论',
    # 2026-09-04 新增：平台插在评论区的推广卡片（实测三个园区号全部命中同一条）
    '大学生免费用', '3个月会员', '免费领取会员', '会员免费领',
    '开通会员', '会员权益', '立即开通', '首月优惠',
]

# 播放器/交互控件词（精确匹配或起始匹配）
PLAYER_WORDS = [
    '播放中', '暂停', '全屏', '倍速', '画质', '弹幕', '发送',
    '评论', '点赞', '收藏', '分享', '转发', '推荐', '关注',
    '展开', '收起', '精选', '作者', '回复', '下载', '自动播放',
    '静音', '音量', '竖屏', '横屏', '拖动', '进度', '暂停',
    '上滑', '下滑', '实时', '连麦', '加号', '拍摄', '道具',
    '音乐', '原声', '合拍', '剪映', '话题', '定位', '经验',
    '3s 后播放', '3s 后播放下一个视频', '3s 后循环播放当前视频',
]


def decode_render_data(raw: str) -> str:
    """RENDER_DATA 解码：优先 URL 编码（新版），回退 base64（旧版）"""
    if raw.startswith('%'):
        return unquote(raw)
    rem = len(raw) % 4
    if rem:
        raw += '=' * (4 - rem)
    try:
        return base64.b64decode(raw).decode('utf-8', errors='replace')
    except Exception:
        return unquote(raw)


def get_render_data(page) -> str:
    html = page.html
    m = re.search(r'<script[^>]*id="RENDER_DATA"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return ""
    return decode_render_data(m.group(1).strip())


def is_logged_in(page) -> bool:
    """用 RENDER_DATA 的 isLogin 字段判断真实登录态"""
    decoded = get_render_data(page)
    if decoded:
        m = re.search(r'"isLogin"\s*:\s*(true|false)', decoded)
        if m:
            return m.group(1) == 'true'
    return 'passport' not in page.url


def wait_for_login(page) -> bool:
    """检测是否需要登录，如需则弹出浏览器等待扫码"""
    time.sleep(3)
    if is_logged_in(page):
        print("  ✅ 已登录")
        return True
    print("\n" + "=" * 50)
    print("⚠️  需要登录抖音！请在弹出的浏览器里用抖音 APP 扫码")
    print("=" * 50 + "\n")
    for _ in range(72):  # 最多等 6 分钟
        time.sleep(5)
        if is_logged_in(page):
            print("  ✅ 登录成功！")
            time.sleep(2)
            return True
    print("  ⚠️  登录等待超时")
    return False


def is_comment_text(text: str) -> bool:
    """判断是否为有效评论文本（过滤页脚/导航/播放器控件/时间戳噪音）"""
    if len(text) < 2 or len(text) > 500:
        return False
    if not any('\u4e00' <= c <= '\u9fff' for c in text):
        return False
    if any(kw in text for kw in CONTROL_WORDS):
        return False
    # 播放器/交互控件：精确或起始匹配
    if text in PLAYER_WORDS:
        return False
    if text in ('作者', '作者回复过', '回复'):
        return False
    # 时间戳 + 地域（"1周前·湖北"、"6月前·浙江"、"1年前·重庆"）
    if re.match(r'^\d+(小时|分钟|天|周|月|年)前(·\S+)?$', text):
        return False
    if re.match(r'^(展开|收起)\d*条?回复', text):
        return False
    if text.startswith('发布时间') or text.startswith('下载'):
        return False
    if text.startswith('大家都在搜'):
        return False
    # 标签密集的长文案 = 账号自述/营销话术，不是真实用户评论
    if text.count('#') >= 3:
        return False
    return True


def _own_prefix(text: str) -> str:
    """归一化前缀：去空白后取前 30 字，用于兼容 DOM 截断后的文案比对"""
    return re.sub(r'\s+', '', text)[:30]


def make_own_matcher(own_texts: set) -> callable:
    """构造「是否像视频简介」判定器

    2026-09-04 补充修复：`own_texts` 精确匹配挡不住 DOM 通道抓到的**截断版简介**
    （右侧推荐流里其它视频的文案，如「白鹤滩水电站…」「越南国会…」），
    精确比对一律漏网。改用前缀索引：任一方向互为前缀即判定为简介。
    """
    prefixes = {_own_prefix(t) for t in own_texts if len(_own_prefix(t)) >= 12}

    def looks_like_own(text: str) -> bool:
        n = _own_prefix(text)
        if len(n) < 12:
            return False
        if n in prefixes:
            return True
        return any(p.startswith(n) or n.startswith(p) for p in prefixes)
    return looks_like_own


def extract_comments_from_page(page) -> list[str]:
    """从当前视频页提取评论文本（RENDER_DATA + DOM 双通道）

    坑（2026-09-03 修复）：视频**自身简介**在 RENDER_DATA 里同样存在 "text"/"content"
    字段，会被误当评论抓进来。实测园区官方号有 28-31% 的"评论"其实是账号自己发的视频
    文案（带 #话题标签的长句），把话题分析严重带偏。
    对策：先取视频 desc 加入排除集，再过滤掉标签密集的营销长文案。
    """
    texts = []
    decoded = get_render_data(page)

    # 视频自身简介 → 排除集（RENDER_DATA 里视频描述字段为 "desc"）
    own_texts = set()
    if decoded:
        for t in re.findall(r'"desc"\s*:\s*"((?:[^"\\]|\\.){2,})"', decoded):
            t = t.strip()
            if t:
                own_texts.add(t)

    looks_like_own = make_own_matcher(own_texts)

    def keep(t: str) -> bool:
        t = t.strip()
        if not t:
            return False
        # 简介污染双保险：精确命中 + 前缀命中（挡 DOM 截断版 / 推荐流文案）
        if t in own_texts or looks_like_own(t):
            return False
        return is_comment_text(t) and t not in texts

    if decoded:
        for pat in [r'"text"\s*:\s*"((?:[^"\\]|\\.){2,})"',
                    r'"content"\s*:\s*"((?:[^"\\]|\\.){2,})"']:
            for t in re.findall(pat, decoded):
                if keep(t):
                    texts.append(t.strip())

    try:
        body_lines = [l.strip() for l in page('tag:body').text.split('\n') if l.strip()]
        for line in body_lines:
            if keep(line):
                texts.append(line.strip())
    except Exception:
        pass

    return texts
