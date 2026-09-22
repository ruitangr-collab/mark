"""
v10 全语义分类器
===============
核心理念：从昵称+签名+企业认证的语义中，提取账号的"身份+领域+角色"，
让分类从数据中归纳出来，而非预设关键词桶。

分析对象：nick + sig + enterprise_verify_reason 合并为统一语义文本
分析维度：
  1. 身份类型 (identity) — 机构/企业/个人
  2. 领域信号 (domain) — 财经/贸易/旅行/军事/娱乐/体育/知识/生活方式
  3. 非洲关联 (africa) — 直接/间接/无
  4. 角色定位 (role) — 内容创作者/记者/生意人/旅行者/评论员/...

分类逻辑：身份 → 领域 → 非洲信号 → 交叉决策
"""

import json, re
from collections import Counter, defaultdict

# ============================================================
# 语义信号词典（加权，非二元）
# ============================================================

# --- 身份信号 ---

# 媒体/政府机构（高权重）
MEDIA_IDENTITY_STRONG = {
    # 官方标记
    'is_gov_media_vip': 100,
}

# 昵称中的机构模式
MEDIA_NICK_PATTERNS = [
    # XX新闻、XX日报、XX发布、XX卫视、XX融媒
    (re.compile(r'^[\u4e00-\u9fff·]{1,6}(新闻|日报|晚报|时报|商报|快报|周报|早报|导报|都市报|发布|发布厅|卫视|电视台|广播|融媒|融媒体|在线|头条|快讯|资讯|要闻|新闻网)$'), 90),
    # 外交部/商务部/国务院 开头
    (re.compile(r'^(外交部|商务部|国务院|海关总署|教育部|国防部)'), 90),
    # XX办公厅
    (re.compile(r'办公厅$'), 85),
    # XX网（需结合上下文）
    (re.compile(r'^[\u4e00-\u9fff]{2,4}网$'), 60),
]

# 媒体/机构白名单（补充无法被正则捕获的）
MEDIA_WHITELIST = {
    '人民日报', '新华社', '央视', 'cctv', '环球时报', '环球网', '参考消息',
    '中国日报', '经济日报', '光明日报', '解放军报', '中国青年报', '中国妇女报',
    '人民网', '新华网', '央视网', '央广网', '光明网', '经济网', '中华网', '中国网',
    '观察者网', '澎湃新闻', '界面新闻', '财联社', '第一财经',
    '新京报', '南方周末', '南方都市报', '红星新闻', '封面新闻', '上游新闻',
    '四川观察', '大象新闻', '极目新闻', '看看新闻', '风芒新闻', '看度新闻',
    '每日经济新闻', '中国经营报', '21世纪经济报道', '中国企业家',
    '中国新闻周刊', '新周刊', '三联生活周刊', 'vista看天下',
    '虎嗅', '36氪', '钛媒体', '蓝鲸', '中新经纬',
    '凤凰卫视', '凤凰网', '阳光卫视',
    '中国新闻网', '海报新闻', '热度新闻', '视界新闻', '豫视频',
    '荆楚网', '湖北日报', '浙江日报', '新华日报',
    '中国商报', '国际商报', '中国财经报',
    '芒果tv', '湖南卫视', '浙江卫视', '东方卫视', '北京卫视', '广东卫视', '深圳卫视',
    '荔枝网', '荔枝新闻', '海博tv',
    '中国一带一路网', '华声在线', '知株侠视频', '湖南广电金鹰955',
    '外交部发言人办公室', '温州瓯海发布', '福建发布',
    '新华每日电讯', '小央视频', '央视频',
    '大河网', '大河报', '南海网', '天山网', '东南网', '东方网',
    '深圳新闻网', '南方网', '东北网', '西部网',
    # 各省日报
    '四川日报', '江苏卫视', '湖北卫视', '山东卫视', '安徽卫视', '江西卫视',
    '河南卫视', '河北卫视', '辽宁卫视', '吉林卫视', '黑龙江卫视', '陕西卫视',
    '甘肃卫视', '宁夏卫视', '青海卫视', '西藏卫视', '新疆卫视', '海南卫视',
    '吉林日报', '云南日报', '江西日报', '广西日报', '贵州日报', '陕西日报',
    '甘肃日报', '青海日报', '西藏日报', '新疆日报', '宁夏日报', '海南日报',
    '福建日报', '安徽日报', '内蒙古日报', '山西日报', '黑龙江日报',
}

# 昵称中的企业模式
ENTERPRISE_NICK_PATTERNS = [
    # XX公司、XX集团、XX工厂
    (re.compile(r'(公司|集团|工厂|厂家|实业|企业|品牌|平台)$'), 50),
    # XX贸易、XX物流、XX机械、XX食品 等
    (re.compile(r'[\u4e00-\u9fff]{2,6}(贸易|物流|机械|食品|建材|服装|电子|化工|矿业|能源|农业|渔业|牧业|医药|汽车|房产|酒店|餐饮|旅游|教育|科技|信息|投资|金融|咨询|服务|传媒|文化|广告|设计)$'), 60),
]

# 签名中的机构身份描述
MEDIA_SIG_PATTERNS = [
    (re.compile(r'(官方账号|官方抖音|官方号|官方频道)'), 80),
    (re.compile(r'(新闻门户|主流媒体|新闻媒体|新闻网站|新闻客户端|新闻中心)'), 85),
    (re.compile(r'(报业集团|传媒集团|广播电视台|新媒体集团|融媒体中心)'), 85),
    (re.compile(r'(党委机关报|党报|官方新闻|权威新闻)'), 80),
    (re.compile(r'(互联网新闻信息|新闻采编|原创报道)'), 70),
    (re.compile(r'(省级媒体|市级媒体|国家级媒体|中央媒体)'), 70),
    (re.compile(r'(新闻频道|综合频道|新闻综合)'), 65),
]

# 个人身份信号
PERSONAL_IDENTITY_PATTERNS = [
    (re.compile(r'(本人|个人|私人|非官方|不代表)'), 40),
    (re.compile(r'(我是|我是一个|我叫|大家好我是)'), 30),
    (re.compile(r'(喜欢|爱好|热爱|梦想|兴趣)'), 15),
]

# --- 领域信号 ---

# 财经/商业（信号强度分级）
FINANCE_STRONG = ['财经', '经济', '金融', '股票', '基金', '理财', '汇率', '美元', '美金', '人民币汇率']
FINANCE_MEDIUM = ['投资', '赚钱', '变现', '营收', '月入', '年入', '盈利', '销售额', '订单']
TRADE_STRONG = ['外贸', '进出口', '出口', '进口', '跨境', '出海', '贸易']
TRADE_MEDIUM = ['清关', '报关', '货代', '批发', '采购', '供应', '货源', '选品',
               '物流', '货运', '海运', '空运', '供应链', '仓储']
BIZ_ENTITY = ['公司', '集团', '企业', '实业', '工厂', '厂家', '车间',
             '生产', '加工', '制造', '产业园', '工业园', '开发区',
             '品牌', '平台', '产品']
BIZ_ROLE = ['老板', '创始人', '合伙人', '总经理', '董事长', 'ceo', '总裁', '创业者']
BIZ_ACTIVITY = ['经营', '运营', '主营', '从事', '深耕', '专注',
               '销售', '出售', '招商', '加盟', '合作']

# 旅行
TRAVEL_STRONG = ['旅行', '旅游', '旅拍', '背包客', '穷游', '环球旅行', '自驾游']
TRAVEL_WEAK = ['自驾', '环球', '游世界', '探险', '户外', '在路上']

# 军事/时政
MILITARY_STRONG = ['军事', '军武', '军旅', '武器', '战争', '时政', '地缘政治']
MILITARY_WEAK = ['局势', '国防', '军队', '部队', '战场', '作战', '特种兵',
                '国际关系', '国际局势', '国际新闻', '地缘']

# 知识/科普
KNOWLEDGE_STRONG = ['科普', '百科', '冷知识', '奇闻', '揭秘', '探索未知']
KNOWLEDGE_WEAK = ['科学', '科技', '地理知识', '历史知识', '人文', '纪录片',
                 '课堂', '讲解', '教学', '学习', '知识分享']

# 娱乐
ENTERTAINMENT = ['搞笑', '段子', '沙雕', '娱乐', '追剧', '剧场', '短剧',
                '电影', '影视', '影业', '综艺', '剪辑', '混剪', '解说',
                '剧情', '好剧', '新剧']

# 体育/游戏
SPORTS = ['体育', '足球', '篮球', 'nba', 'cba', '英超', '西甲', '中超',
         '电竞', '游戏', '王者荣耀', '和平精英', '英雄联盟',
         'lpl', 'kpl', '解说员', '世界杯', '欧洲杯']

# 生活方式
LIFESTYLE = ['美妆', '穿搭', '时尚', '美食', '做饭', '宠物', '健身',
            '减肥', '瑜伽', '母婴', '育儿', '星座', '情感', '恋爱',
            '种草', '好物', 'vlog']

# --- 非洲信号 ---
AFRICA_DIRECT = ['非洲', '南非', '尼日利亚', '肯尼亚', '埃塞俄比亚', '埃塞', '加纳',
                '坦桑尼亚', '坦桑', '摩洛哥', '埃及', '安哥拉', '乌干达',
                '科特迪瓦', '科特', '喀麦隆', '塞内加尔', '卢旺达', '赞比亚',
                '津巴布韦', '莫桑比克', '马达加斯加', '刚果', '苏丹',
                '拉各斯', '内罗毕', '阿比让', '达累斯', '卢萨卡', '阿克拉',
                '开罗', '卡萨布兰卡', '约翰内斯堡', '坎帕拉', '达喀尔',
                '马普托', '哈拉雷', '金沙萨',
                'africa', '非漂', '非洲人', '黑人']

AFRICA_CONTEXT = ['撒哈拉', '中非', '东非', '西非', '北非', '驻华大使馆']

# --- 内容创作者信号 ---
CREATOR_SIGNALS = ['商务合作', '商务', '星图', '合作私信', '合作请私', '合作v',
                  '合作微信', '合作wx', '合作vx', '合作联系', '合作洽谈',
                  '接广', '接单', '接合作', '品牌合作', '品牌推广',
                  '招募', '招聘', '招人', '剪辑', '文案', '写手',
                  'mcn', '达人', '博主']

# ============================================================
# 特征提取函数
# ============================================================

def extract_features(a):
    """从单个账号提取语义特征向量"""
    nick = (a.get('nickname', '') or '').strip()
    sig = (a.get('signature', '') or '').strip()
    evr = (a.get('enterprise_verify_reason', '') or '').strip()
    is_gov_media = a.get('is_gov_media_vip', False)
    fans = a.get('follower_count', 0) or 0
    
    # 统一语义文本（nick + sig + evr）
    full_text = f"{nick} {sig} {evr}".lower()
    # 短文本（nick + sig，排除企业认证信息）
    short_text = f"{nick} {sig}".lower()
    nick_lower = nick.lower()
    sig_lower = sig.lower()
    
    features = {
        'nick': nick,
        'sig': sig[:200],
        'fans': fans,
        'is_gov_media_vip': is_gov_media,
    }
    
    # === 1. 身份评分 ===
    media_score = 0
    enterprise_score = 0
    personal_score = 0
    
    # 1a. 官方标记
    if is_gov_media:
        media_score += 100
    
    # 1b. 企业认证中的媒体信号
    if evr:
        evr_lower = evr.lower()
        if any(k in evr_lower for k in ['广播电视台', '报社', '报业', '日报', '新闻',
                                          '传媒集团', '融媒体', '卫视', '电视台',
                                          '官方账号', '官方抖音']):
            media_score += 90
        elif any(k in evr_lower for k in ['公司', '集团', '企业', '实业', '工厂',
                                           '银行', '保险', '证券', '基金']):
            enterprise_score += 80
        elif any(k in evr_lower for k in ['政府', '局', '委', '部', '办']):
            media_score += 85
    
    # 1c. 昵称正则模式
    for pattern, weight in MEDIA_NICK_PATTERNS:
        if pattern.search(nick):
            media_score += weight
            break
    
    for pattern, weight in ENTERPRISE_NICK_PATTERNS:
        if pattern.search(nick):
            enterprise_score += weight
            break
    
    # 1d. 媒体白名单
    if nick_lower in {n.lower() for n in MEDIA_WHITELIST}:
        media_score = max(media_score, 80)
    else:
        # 白名单模糊匹配（子串）
        for wl in MEDIA_WHITELIST:
            wl_lower = wl.lower()
            if wl_lower in nick_lower:
                idx = nick_lower.index(wl_lower)
                after = nick_lower[idx+len(wl_lower):].strip('-_·. ')
                if idx == 0 and len(after) <= 4:
                    media_score = max(media_score, 75)
                elif idx + len(wl_lower) == len(nick_lower) and idx <= 3:
                    media_score = max(media_score, 70)
    
    # 1e. 签名中的媒体身份
    for pattern, weight in MEDIA_SIG_PATTERNS:
        if pattern.search(full_text):
            media_score = max(media_score, weight)
    
    # 1f. 个人身份信号
    for pattern, weight in PERSONAL_IDENTITY_PATTERNS:
        if pattern.search(full_text):
            personal_score += weight
    
    # 1g. 内容创作者信号（表明是个人/团队创作者，不是机构）
    creator_signals = sum(1 for k in CREATOR_SIGNALS if k in short_text)
    if creator_signals >= 2:
        personal_score += 30
    elif creator_signals >= 1:
        personal_score += 15
    
    features['media_score'] = media_score
    features['enterprise_score'] = enterprise_score
    features['personal_score'] = personal_score
    
    # === 2. 领域评分 ===
    finance_score = 0
    trade_score = 0
    entertainment_score = 0
    sports_score = 0
    travel_score = 0
    military_score = 0
    knowledge_score = 0
    lifestyle_score = 0
    
    for kw in FINANCE_STRONG:
        if kw in full_text: finance_score += 15
    for kw in FINANCE_MEDIUM:
        if kw in full_text: finance_score += 8
    for kw in TRADE_STRONG:
        if kw in full_text: trade_score += 15
    for kw in TRADE_MEDIUM:
        if kw in full_text: trade_score += 8
    for kw in BIZ_ENTITY:
        if kw in full_text: trade_score += 5
    for kw in BIZ_ROLE:
        if kw in full_text: trade_score += 5
    for kw in BIZ_ACTIVITY:
        if kw in full_text: trade_score += 5
    
    # 商业总分
    biz_score = finance_score + trade_score
    
    # 娱乐（nick权重更高）
    for kw in ENTERTAINMENT:
        if kw in nick_lower:
            entertainment_score += 25
        elif kw in sig_lower:
            entertainment_score += 10
    
    # 体育
    for kw in SPORTS:
        if kw in nick_lower:
            sports_score += 25
        elif kw in sig_lower:
            sports_score += 10
    
    # 旅行
    for kw in TRAVEL_STRONG:
        if kw in full_text: travel_score += 15
    for kw in TRAVEL_WEAK:
        if kw in full_text: travel_score += 8
    
    # 军事
    for kw in MILITARY_STRONG:
        if kw in full_text: military_score += 15
    for kw in MILITARY_WEAK:
        if kw in full_text: military_score += 8
    
    # 知识
    for kw in KNOWLEDGE_STRONG:
        if kw in full_text: knowledge_score += 15
    for kw in KNOWLEDGE_WEAK:
        if kw in full_text: knowledge_score += 8
    
    # 生活方式
    for kw in LIFESTYLE:
        if kw in full_text: lifestyle_score += 10
    
    features['biz_score'] = biz_score
    features['finance_score'] = finance_score
    features['trade_score'] = trade_score
    features['entertainment_score'] = entertainment_score
    features['sports_score'] = sports_score
    features['travel_score'] = travel_score
    features['military_score'] = military_score
    features['knowledge_score'] = knowledge_score
    features['lifestyle_score'] = lifestyle_score
    
    # === 3. 非洲信号 ===
    africa_direct = sum(1 for kw in AFRICA_DIRECT if kw in full_text)
    africa_context = sum(1 for kw in AFRICA_CONTEXT if kw in full_text)
    africa_score = africa_direct * 20 + africa_context * 10
    
    features['africa_score'] = africa_score
    features['africa_direct'] = africa_direct > 0
    
    # === 4. 内容创作信号 ===
    is_creator = creator_signals >= 1
    features['is_creator'] = is_creator
    
    return features


# ============================================================
# 分类决策
# ============================================================

def classify_v10(features):
    """
    基于语义特征向量做分类决策。
    优先级：身份 > 领域 > 非洲信号
    
    分类归纳逻辑：
    1. 先判断"身份"（媒体机构/企业/个人创作者/无法判定）
    2. 再判断"领域"（财经/贸易/旅行/娱乐/体育/军事/知识/生活方式）
    3. 最后叠"非洲信号"（交叉分类）
    """
    m = features['media_score']
    e = features['enterprise_score']
    p = features['personal_score']
    
    biz = features['biz_score']
    ent = features['entertainment_score']
    sp = features['sports_score']
    tr = features['travel_score']
    mi = features['military_score']
    kn = features['knowledge_score']
    ls = features['lifestyle_score']
    af = features['africa_score']
    
    domain_scores = {
        '商业': biz,
        '娱乐': ent,
        '体育': sp,
        '旅行': tr,
        '军事': mi,
        '知识': kn,
        '生活': ls,
    }
    
    top_domain = max(domain_scores, key=domain_scores.get)
    top_score = domain_scores[top_domain]
    
    # ================================================================
    # 决策树
    # ================================================================
    
    # --- 路径 A: 媒体/新闻机构 ---
    if m >= 60:
        return '新闻媒体'
    
    # --- 路径 B: 企业/商业实体 ---
    # 企业认证 + 商业信号
    if e >= 50 and biz >= 20:
        if af >= 20:
            return '非洲商业'  # 非洲相关企业
        return '商业/企业'
    
    # --- 路径 C: 非洲信号突出的 ---
    if af >= 40:
        # 非洲+旅行 -> 非洲旅行
        if tr >= 20 and tr > biz:
            return '旅行/探险'  # 非洲旅行者，不是商业号
        # 非洲+商业 -> 非洲商业
        if biz >= 15:
            return '非洲商业'
        # 非洲+其他 -> 非洲相关
        return '非洲相关'
    
    # --- 路径 D: 领域明确的 ---
    # 必须先排除"商务合作"伪装成商业的个人创作者
    # 真正商业 = biz高 AND 有实体信号（企业认证/公司名/产品/品牌）
    
    if top_score >= 30:
        if top_domain == '娱乐':
            return '影视娱乐'
        elif top_domain == '体育':
            return '体育/游戏'
        elif top_domain == '军事':
            # 军事+知识 -> 泛知识（很多军事号实际是历史/知识类）
            if kn >= 15 or mi >= 40:
                return '军事/时政'
            return '军事/时政'
        elif top_domain == '知识':
            return '泛知识/科普'
        elif top_domain == '旅行':
            # 旅行+商业+创作者 -> 可能是旅行博主（内容创作者）
            if biz >= 15 and e < 30:
                # 检查是否真的是商业（有实体信号）还是只是创作者变现
                if features['is_creator']:
                    return '旅行/探险'  # 旅行创作者
            return '旅行/探险'
        elif top_domain == '生活':
            return '生活方式'
        elif top_domain == '商业':
            # 关键判断：真正的商业还是伪装成商业的个人创作者？
            # 真商业：有企业认证 + 实体信号 + 产品/服务描述
            # 伪商业：只是签名里有"商务合作" + 少量商业词
            if e >= 30:
                return '商业/企业'
            # 金融/财经内容方向
            if features['finance_score'] >= 20:
                if af >= 10:
                    return '非洲商业'
                return '财经内容'
            # 贸易/企业方向
            if features['trade_score'] >= 20:
                if af >= 10:
                    return '非洲商业'
                return '商业/企业'
            # 边界：有商业信号但不够强，且是创作者
            if features['is_creator'] and biz < 40:
                return '个人创作者'
            return '商业/企业'
    
    # --- 路径 E: 弱信号 ---
    # 有点非洲信号
    if af >= 10:
        return '非洲相关'
    
    # 有点商业但不明确
    if biz >= 20:
        if features['is_creator']:
            return '个人创作者'
        return '商业/企业'
    
    # 有点旅行
    if tr >= 15:
        return '旅行/探险'
    
    # 有点军事
    if mi >= 15:
        return '军事/时政'
    
    # 有点知识
    if kn >= 15:
        return '泛知识/科普'
    
    # 有点娱乐
    if ent >= 15:
        return '影视娱乐'
    
    # 有点体育
    if sp >= 15:
        return '体育/游戏'
    
    # 有点生活
    if ls >= 15:
        return '生活方式'
    
    # --- 路径 F: 极弱信号/信息不足 ---
    return '信息不足'


# ============================================================
# 向后兼容
# ============================================================
def classify_v9_wrapper(a):
    """为兼容旧代码提供的包装"""
    feats = extract_features(a)
    return classify_v10(feats)


# ============================================================
# 测试和分析
# ============================================================
if __name__ == '__main__':
    with open('00_raw/Phase2_作者画像最终采集_2026-06-11/author_profiles_cache.json', 'r', encoding='utf-8') as f:
        cache = json.load(f)
    
    # 受保护账号
    PROTECTED = {'非洲十年', '尖峰苏打', '张浩水晶矿业', '闯非洲小胖子', '明亮的车头漆',
                 '导演-罗杰', '瓦肯财经', '晓芳聊财经', '何毅财经课堂', '非洲小五',
                 '杨华说天下', '保德全'}
    
    # 提取所有特征
    all_features = []
    for uid, a in cache.items():
        nick = (a.get('nickname', '') or '').strip()
        if nick in PROTECTED:
            continue
        feats = extract_features(a)
        feats['uid'] = uid
        feats['category'] = classify_v10(feats)
        all_features.append(feats)
    
    # 分类分布
    cat_dist = Counter(f['category'] for f in all_features)
    total = len(all_features)
    
    print(f"\n{'='*60}")
    print(f"v10 语义分类结果（总 {total} 人，不含12个受保护账号）")
    print(f"{'='*60}")
    for cat, cnt in cat_dist.most_common():
        pct = cnt / total * 100
        bar = '#' * int(pct)
        print(f"  {cat:<14} {cnt:>5}  ({pct:5.1f}%)  {bar}")
    
    # 每类 Top 10 样本
    print(f"\n{'='*60}")
    print("每类 Top 10 高粉样本")
    print(f"{'='*60}")
    
    cats_grouped = defaultdict(list)
    for f in all_features:
        cats_grouped[f['category']].append(f)
    
    for cat in cat_dist:
        items = sorted(cats_grouped[cat], key=lambda x: -x['fans'])[:10]
        print(f"\n--- {cat}（共{cat_dist[cat]}人）---")
        for i, f in enumerate(items):
            fan_str = f'{f["fans"]/10000:.1f}万' if f['fans'] >= 10000 else str(int(f['fans']))
            sig_preview = f['sig'][:100] if f['sig'] else '(签名为空)'
            scores = f'biz={f["biz_score"]} af={f["africa_score"]} m={f["media_score"]}'
            print(f"  {i+1}. {f['nick']} ({fan_str}粉) [{scores}]")
            print(f"     {sig_preview}")
