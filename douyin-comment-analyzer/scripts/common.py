#!/usr/bin/env python3
"""
抖音评论提取公共模块（2026-09 验证版）
keyword_extract.py / account_analyzer.py 共享：
  - RENDER_DATA 解码（URL编码优先，base64 回退）
  - 登录态判断与扫码等待
  - 评论文本过滤（含播放器控件/时间戳噪音）
  - 评论提取（RENDER_DATA + DOM 文本双通道）
"""
import os, re, time, base64, html as html_mod
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
    # 2026-09-17 新增：新版页面残留 UI 标签（实测以「独立单条」形式混进评论区，
    # 直接污染话题词频榜，见 2026-09-17 摘要中 Top10 被「短剧/通知/消息/狗杂/30天内」占据）
    '短剧', '通知', '消息', '狗杂', '30天内', '7天内', '90天内',
    '我的', '朋友', '用户', '下一章', '结语', '引言',
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

# 「用户+数字」占位昵称（未设置昵称的账号，会被 DOM 通道当成一条评论抓进来）
PLACEHOLDER_USER_RE = re.compile(r'^用户\d{6,}$')

# 播放器倒计时残留（"3s 后播放" 的秒数会变，实测出现 0s/1s/2s/3s 多种）
COUNTDOWN_RE = re.compile(r'^\d+\s*s\s*后(播放|播放下一个视频|循环播放当前视频)?$')

# UI 残留判定：命中即认为不是真实评论（播放器倒计时/占位昵称/纯控件标签）
_UI_EXACT = set(CONTROL_WORDS) | set(PLAYER_WORDS)


def is_ui_residue(text: str) -> bool:
    """判断文本是否为页面 UI 残留（非用户评论）。

    2026-09-17 新增：新版页面把播放器倒计时（"1s 后播放下一个视频"）以独立条目
    混进评论区，且秒数不定；旧版只挡了固定 "3s" 文案，故漏网并污染话题词频榜。
    """
    t = (text or '').strip()
    if not t:
        return True
    if COUNTDOWN_RE.match(t):
        return True
    if PLACEHOLDER_USER_RE.match(t):
        return True
    if t in _UI_EXACT:
        return True
    if re.match(r'^\d+(小时|分钟|天|周|月|年)前(·\S+)?$', t):
        return True
    return False

# ---------------------------------------------------------------------------
# 2026-09-18 新增：两类「非评论」残留（实测占当日语料 22%+，直接污染话题词频榜）
#
# 背景：新版视频页 DOM 通道会把【右侧推荐流的账号名】与【视频章节要点/字幕】当成
# 独立条目抓进来，且都带前导数字（粉丝数/获赞数/序号）。实测当日 3368 条语料里：
#   - 746 条是「数字前缀 + 昵称」形态（如 "4853叶镇平出海贸易"、"2.5万勇闯非洲的家敏"）
#   - 22 条是「章节要点/字幕」参数式长句（如 "沙坪河段…：水深6.3米，宽度80米"）
# 二者都不是用户评论，却让 Top10 话题榜被 "水深/宽度/最小弯曲半径" 整榜占据。
#
# ⚠️ 注意分工：账号名条目虽然**不是评论**（不该进话题榜/密度），但**是同行线索的
# 唯一来源**（daily_digest 的 PREFIX_PAT 就是剥它的前缀）。因此本模块只提供判定器，
# 由各消费方决定是否排除——话题统计要排除，同行线索提取**不要**排除。
# ---------------------------------------------------------------------------

# 账号名残留：前导「数字」或「数字+万」（粉丝数/获赞数/序号）+ 昵称
ACCOUNT_MENTION_RE = re.compile(r'^\d+(?:\.\d+)?万?\S{2,20}$')

# 真评论标记（用于防止把以数字开头的真实提问误判为账号名）
_COMMENT_MARKER_RE = re.compile(
    r'(吗|呢|怎么|我|你|想|请问|可以|有没有|多少|价格|联系|需要|麻烦|老板|请教|求|帮)'
)

# 章节要点/字幕残留：工程参数式长句（≥3 个带长度/体积单位的数值 + 含冒号）
_SPEC_UNIT = r'(?:米|公里|千米|厘米|毫米|吨|立方米|平方米|公顷|亩|节|海里)'


def is_account_mention(text: str) -> bool:
    """是否为「数字前缀 + 昵称」形态的账号名残留（非评论）。

    带真评论标记（吗/怎么/我/你/多少…）的除外——实测当日 746 条命中里
    仅 3 条是真实提问（如「40万马拉维币等于多少人民币」），该守卫可保其不被误杀。
    """
    t = (text or '').strip()
    if not ACCOUNT_MENTION_RE.match(t):
        return False
    return not _COMMENT_MARKER_RE.search(t)


def is_chapter_residue(text: str) -> bool:
    """是否为视频「章节要点/字幕」残留（非评论）。

    判定：长度 ≥28 且含冒号，且出现 ≥3 个「数值+长度/体积单位」。
    真实评论极少同时满足（价格类评论多用「元」，不在单位表内，不会误杀）。
    """
    t = (text or '').strip()
    if len(t) < 28 or '：' not in t:
        return False
    return len(re.findall(rf'\d+(?:\.\d+)?\s*{_SPEC_UNIT}', t)) >= 3


def is_topic_noise(text: str) -> bool:
    """话题词频统计专用：账号名残留 / 章节字幕残留 / 既有 UI 残留。

    仅用于【话题榜】口径。同行线索提取、提问抽取等不要用它，
    否则会连带丢掉账号名线索。
    """
    return is_ui_residue(text) or is_account_mention(text) or is_chapter_residue(text)


def cross_dataset_duplicates(per: dict, min_datasets: int = 4) -> set:
    """返回「在 ≥min_datasets 个数据集里逐字重复出现」的字符串集合。

    这类字符串是**平台注入内容**（推荐流视频标题/推广卡/公共控件），不是用户评论。
    实例：2026-09-18「以为库里南已经无敌了，结果后面还有个更猛的……」
    在 9 个 S 级账号页面里逐字一致，被切词后贡献 45 次词频，直接占据 Top10。
    用户评论即使再热门，也几乎不可能在 9 个不同账号下逐字完全相同。
    """
    from collections import Counter
    cnt = Counter()
    for cs in per.values():
        for t in set(cs):
            if isinstance(t, str):
                cnt[t.strip()] += 1
    return {t for t, c in cnt.items() if c >= min_datasets}


# 话题词频统计停用词（build_archive_docs.py 与 daily_digest.py 共用）
# ⚠️ 以前两个脚本各维护一份，2026-09-17 发现已漂移并污染话题榜，故收敛到此处单一来源。
TOPIC_STOPWORDS = {
    # 通用虚词/高频无信息词
    '非洲', '出海', '中国', '怎么', '如何', '什么', '一个', '没有', '就是',
    '这个', '那个', '自己', '我们', '你们', '他们', '现在', '可以', '不是',
    '真的', '感觉', '知道', '发现', '看到', '大家', '还有', '已经', '这样',
    '我的', '朋友', '用户', '时候', '如果', '因为', '所以', '但是', '还是',
    # 播放器/页脚/侧栏 UI 噪音
    '人服证字', '网络谣言', '曝光台', '稍后再看', '进入全屏', '网页全屏',
    '高清', '清屏', '倍速', '画质', '弹幕', '音效', '字幕', '收藏', '分享',
    '评论', '点赞', '转发', '关注', '首页', '推荐', '直播', '放映厅',
    '短剧', '下载', '我的作品', '合集', '日期筛选', '搜索', '播放', '暂停',
    '静音', '下载抖音', '电子营业执照', '许可证', '备案', '举报', '观看历史',
    '连播', '点击加载更多', '阅读全文', '短视频', '听抖音', 'AI抖音',
    '创作者', '作品数据', '开直播', '私信关注', '关注私信',
    '快乐大本营', '京公网安备', '剪映专业版', '标清', '狗杂',
    '天前', '天内', '不开启', '发布视频', '图文', '消息', '通知',
    '引言', '智能', '全屏', '自动连播', '倍速播放',
    '打开看看', '继续播放', '已关注', '回关', '互关', '粉丝团',
    '作品', '视频', '频道', '动态', '音乐', '原声', '模板', '特效',
    '万获赞', '下一章', '内容由', '生成', '加载中', '暂时没有更多',
    '第一章', '第二章', '第三章', '第1章', '第2章', '第3章',
    '字幕由', '翻译', '已重置', '拖动', '选集', '倍速', '全选',
    # 时间戳/视频简介残留
    '小时前', '分钟前', '周前', '月前', '刚刚', '结语',
    '上热门', '真实生活分享', '持续更新', '未完待续', '下集', '上集',
    '关注我', '点个赞', '感谢观看', '谢谢观看', '点赞关注',
    # 平台计数残留（"164粉丝"、"39获赞"）
    '粉丝', '获赞', '后播放',
}


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


def looks_like_feed_caption(text: str) -> bool:
    """识别「推荐流视频标题+简介」（2026-09-24 建立）

    判据（实测莱基自贸区 233 条中 31 条长文本，29 条为信息流文案）：
      1. 标题回声：首个空格/全角空格前的片段（≥8 字）在正文里再次出现
      2. 首 40 字内出现【】《》「」｜ 等标题装饰符，且全文 ≥45 字
      3. 出现栏目化措辞：本期 / 第一视角 / 免责声明 / 周报 / 新片预告
    """
    # 号主自制系列视频的「第N集 | …」简介（与长度无关，须前置）
    if re.match(r'^第\d+[集期][\s|｜]', text):
        return True
    if len(text) < 45:
        return False
    if any(k in text for k in ('本期拆解', '第一视角', '免责声明', '周报', '新片预告')):
        return True
    head = re.split(r'[  ]', text, 1)[0]
    if len(head) >= 8 and head in text[len(head):]:
        return True
    if re.search(r'[【】《》「」｜|]', text[:40]):
        return True
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
    # 推荐流视频「标题+简介」文案（跨账号复现，污染词频榜）
    if looks_like_feed_caption(text):
        return False
    # 占位昵称（"用户7048135123713"）
    if PLACEHOLDER_USER_RE.match(text):
        return False
    # 播放器倒计时残留（"1s 后播放下一个视频"）
    if COUNTDOWN_RE.match(text):
        return False
    return True


# ── 2026-09-24 新增：跨账号复现的「污染长文案」黑名单 ──────────────────
# 根因（本日排查确认）：DOM 通道原为 page('tag:body').text.split('\n')，
# 会把**右侧推荐流里其它视频的标题/简介**一并抓成评论。判据：同一条文案
# 在多个互不相干的账号里稳定复现（如「2023年厂房设备就通过了验收…通电即
# 投产！」已累计 8 个账号）。这里用「特征子串」命中即丢弃，比精确匹配稳。
POLLUTION_SUBSTRINGS = [
    '2023年厂房设备就通过了验收',
    '中设集团输变电项目投用',
    '通电即投产',
]

_BLOCKLIST_FILE = os.path.join(
    os.path.expanduser('~'), '.workbuddy', 'douyin_analysis', '_archive',
    'comment_pollution_blocklist.txt')


def _load_pollution_blocklist() -> list:
    """加载可持续追加的污染文案黑名单（一行一条，# 开头为注释）"""
    try:
        with open(_BLOCKLIST_FILE, encoding='utf-8') as f:
            return [l.strip() for l in f
                    if l.strip() and not l.startswith('#')]
    except Exception:
        return []


def _is_pollution(text: str, extra: list) -> bool:
    for s in POLLUTION_SUBSTRINGS:
        if s in text:
            return True
    for s in extra:
        if len(s) >= 8 and s in text:
            return True
    return False


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

    2026-09-24 二次修复（污染第 8 次复现后排查）：DOM 通道原取整页 body，
    右侧推荐流/侧栏其它视频的标题与简介会被当成评论，且跨账号复现同一条。
    改为**优先只取评论区容器**；容器命中且条数达标就不再回落整页，
    另叠加持久化污染黑名单。
    """
    texts = []
    decoded = get_render_data(page)
    _pollution = _load_pollution_blocklist()

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
        if _is_pollution(t, _pollution):
            return False
        return is_comment_text(t) and t not in texts

    if decoded:
        for pat in [r'"text"\s*:\s*"((?:[^"\\]|\\.){2,})"',
                    r'"content"\s*:\s*"((?:[^"\\]|\\.){2,})"']:
            for t in re.findall(pat, decoded):
                if keep(t):
                    texts.append(t.strip())

    # ── DOM 通道：先只取评论区容器，避免整页 body 混入推荐流 ──
    comment_selectors = [
        '[data-e2e="comment-list"]',
        'div[class*="comment-list"]',
        'div[class*="commentList"]',
        'div[class*="CommentList"]',
        'ul[class*="comment"]',
    ]
    scoped = []
    for sel in comment_selectors:
        try:
            nodes = page(sel)
            if not nodes:
                continue
            for node in nodes:
                for line in node.text.split('\n'):
                    line = line.strip()
                    if keep(line):
                        scoped.append(line)
            if len(scoped) >= 5:
                break
            scoped = []
        except Exception:
            continue

    if len(scoped) >= 5:
        print(f"    [DOM] 评论区容器命中 {len(scoped)} 条（未回落整页）")
        texts.extend(scoped)
        return texts
    print("    [DOM] 评论区容器未命中 → 回落整页 body（可能混入推荐流）")

    # 回落：整页 body（保守，仍带污染黑名单与简介排除）
    try:
        body_lines = [l.strip() for l in page('tag:body').text.split('\n') if l.strip()]
        for line in body_lines:
            if keep(line):
                texts.append(line.strip())
    except Exception:
        pass

    return texts
