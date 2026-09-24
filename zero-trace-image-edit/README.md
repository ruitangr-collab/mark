# 零痕改图 指哪改哪（Zero-Trace Image Edit）

> 中文别名：**无痕改图**
> 技能 ID：`zero-trace-image-edit` ｜ 版本：4.0.0 ｜ 分类：办公效率 ｜ 作者：stone肖深圳和AI全链路

## 一句话

一张图加一句话，把你想改的地方改掉，其余一点不动。目标区域之外的像素**零改动**，客户看不出改过。

## 能做什么

- **移除**：把图里某个东西去掉（瑕疵、路人、杂物、口袋…）
- **替换**：换成另一个东西（B 图的部件搬到 A 图）
- **添加**：在指定位置加一个新元素
- **改色**：局部改颜色 / 材质，不影响别处

## 核心方法论（双闸门，永不假图）

1. **闸门① 9 项前置确认**：动工前先把意图和验收用大白话锁死，**未签禁出图**。
2. **闸门② 9 项量化点检**：出图后校色 / 平整度 / 空间均匀性等指标实测算，打印确认表，**未签禁交付**。
3. 红线：无 GPU 且未走公开开源渠道 = 禁止出图；**绝不生成合成图 / 占位图 / 假图充数**。

## 适用场景（不止服装）

电商换配色去瑕疵、家居换软装、房产去杂物、汽车改色换轮毂、摄影去路人、装修出效果图……凡是"图里某个东西想拿掉 / 换掉 / 加上"的场景都归它管。

## 快速开始

```bash
# 1) 复制确认模板，按 9 项填全
cp gate/sample_confirmation.json 你的订单/confirm.json

# 2) 闸门①签名（签①冻结意图）
python gate/confirm.py --sign1 confirm.json --user 你的登录名 --out 表_签1.docx

# 3) 出图（自动跑环境探测 + 自适应路由）
python gate/run_pipeline.py --confirm confirm.json --a 图A.jpg --b 图B.jpg --execute

# 4) 闸门②量化点检 + 双签交付
python gate/run_pipeline.py --confirm confirm.json --a 图A.jpg --out-image out.png --checks-out checks.json
python gate/confirm.py --sign2 confirm.json --user 你的登录名 --checks checks.json --out 表_双签.docx
```

## 触发词

当你想「把图里这个东西去掉 / 换个颜色 / 把 B 图那个部件移到 A 图 / 改完别处别动 / 出张改图效果图」时就用它。

## 依赖

运行时依赖（本机需自备）：`numpy` `Pillow` `opencv-python` `python-docx`；出图云端通道需 `requests` 与对应平台凭据。本地 Fooocus-API 后端为可选（需 N 卡 + torch）。

## FAQ

- **会动到图的其他部分吗？** 不会。目标区域外像素零改动，实测框外保真 99.89%。
- **涉密图能用吗？** 生成式通道会把图传至云端，涉密图请切纯本地模式或不出图。
- **双闸门是摆设吗？** 不是。未签①不出图、未签②不交付，量化指标全部实测算，出图必为真实结果。
