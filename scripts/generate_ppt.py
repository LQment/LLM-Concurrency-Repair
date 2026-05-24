"""生成中期检查 PPT"""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)

# 颜色方案
DARK_BLUE = RGBColor(0x1B, 0x2A, 0x4A)
ACCENT_BLUE = RGBColor(0x2E, 0x86, 0xAB)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT_GRAY = RGBColor(0xF0, 0xF2, 0xF5)
DARK_TEXT = RGBColor(0x2D, 0x2D, 0x2D)
GREEN = RGBColor(0x27, 0xAE, 0x60)
RED = RGBColor(0xE7, 0x4C, 0x3C)
ORANGE = RGBColor(0xF3, 0x9C, 0x12)


def set_bg(slide, color):
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_title_bar(slide, text, y=Inches(0), h=Inches(1.2)):
    """深色标题栏"""
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), y, prs.slide_width, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = DARK_BLUE
    shape.line.fill.background()
    tf = shape.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(32)
    p.font.color.rgb = WHITE
    p.font.bold = True
    p.alignment = PP_ALIGN.LEFT
    tf.margin_left = Inches(0.8)
    tf.margin_top = Inches(0.15)


def add_body_text(slide, text, left, top, width, height, size=Pt(18), bold=False, color=DARK_TEXT):
    """正文文本框"""
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = size
    p.font.color.rgb = color
    p.font.bold = bold
    return tf


def add_bullet_list(slide, items, left, top, width, height, size=Pt(16)):
    """带要点的文本框"""
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True
    for i, item in enumerate(items):
        if i == 0:
            p = tf.paragraphs[0]
        else:
            p = tf.add_paragraph()
        p.text = item
        p.font.size = size
        p.font.color.rgb = DARK_TEXT
        p.space_after = Pt(8)
        p.level = 0
    return tf


def add_card(slide, title, content, left, top, width, height, color=ACCENT_BLUE):
    """卡片组件"""
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = LIGHT_GRAY
    shape.line.color.rgb = color
    shape.line.width = Pt(2)
    tf = shape.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.2)
    tf.margin_right = Inches(0.2)
    tf.margin_top = Inches(0.15)
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(18)
    p.font.bold = True
    p.font.color.rgb = color
    p2 = tf.add_paragraph()
    p2.text = content
    p2.font.size = Pt(14)
    p2.font.color.rgb = DARK_TEXT
    p2.space_before = Pt(6)


# ============================================================
# Slide 1: 封面
# ============================================================
slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
set_bg(slide, DARK_BLUE)

# 装饰线
line = slide.shapes.add_shape(
    MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(3.0), Inches(2), Inches(0.06))
line.fill.solid()
line.fill.fore_color.rgb = ACCENT_BLUE
line.line.fill.background()

add_body_text(slide, "CHATREPAIR", Inches(0.8), Inches(1.2), Inches(11), Inches(1.5),
              size=Pt(56), bold=True, color=WHITE)
add_body_text(slide, "基于大语言模型的多轮对话自动程序修复", Inches(0.8), Inches(2.2), Inches(11), Inches(0.8),
              size=Pt(24), color=RGBColor(0xBB, 0xCC, 0xDD))
add_body_text(slide, "中期检查汇报", Inches(0.8), Inches(3.4), Inches(11), Inches(0.6),
              size=Pt(20), color=RGBColor(0x99, 0xAA, 0xBB))
add_body_text(slide, "Defects4J · DeepSeek-v4-pro · 54 个真实 Java Bug", Inches(0.8), Inches(4.2), Inches(11), Inches(0.6),
              size=Pt(16), color=RGBColor(0x88, 0x99, 0xAA))

# ============================================================
# Slide 2: 项目背景
# ============================================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_bg(slide, WHITE)
add_title_bar(slide, "项目背景与研究动机")

items = [
    "▎软件维护中 bug 修复是最耗时的环节之一，占据开发成本的 50% 以上",
    "▎自动程序修复 (APR) 旨在自动生成补丁，减少人工干预",
    "▎传统 APR 方法依赖人工定义修复模板，覆盖面有限",
    "▎CHATREPAIR 利用大语言模型的代码理解能力，通过多轮对话+反馈循环自动修复 bug",
    "▎核心思路：LLM 生成补丁 → 编译/测试验证 → 错误反馈 → 迭代改进",
]
add_bullet_list(slide, items, Inches(0.8), Inches(1.6), Inches(11.5), Inches(5), size=Pt(20))

# 关键数字
for i, (num, label) in enumerate([
    ("6", "Java 项目"), ("54", "真实 Bug"), ("3 种", "修复模式"),
    ("6 类", "反馈信号"), ("24", "最大迭代轮次")
]):
    left = Inches(0.8 + i * 2.5)
    add_body_text(slide, num, left, Inches(4.8), Inches(2), Inches(1),
                  size=Pt(42), bold=True, color=ACCENT_BLUE)
    add_body_text(slide, label, left, Inches(5.6), Inches(2), Inches(0.6),
                  size=Pt(16), color=DARK_TEXT)

# ============================================================
# Slide 3: 系统架构
# ============================================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_bg(slide, WHITE)
add_title_bar(slide, "系统架构与工作流程")

# 流程步骤
steps = [
    ("1. 输入", "Defects4J 检出\nbuggy 源码\n+ 补丁元信息"),
    ("2. Prompt\n构造", "few-shot 示例\n+ buggy 函数\n+ 失败测试信息"),
    ("3. LLM\n生成补丁", "DeepSeek-v4-pro\n生成修复后\n函数代码"),
    ("4. 代码\n提取", "正则匹配\n去除 markdown\n提取纯 Java"),
    ("5. 验证\n反馈", "编译项目\n运行测试\n分类错误类型"),
    ("6. 迭代/\n终止", "通过→输出补丁\n失败→反馈回第3步\n最多 24 轮"),
]

for i, (title, desc) in enumerate(steps):
    left = Inches(0.5 + i * 2.15)
    # 步骤编号圆
    circle = slide.shapes.add_shape(
        MSO_SHAPE.OVAL, left + Inches(0.55), Inches(1.5), Inches(0.5), Inches(0.5))
    circle.fill.solid()
    circle.fill.fore_color.rgb = ACCENT_BLUE if i < 5 else GREEN
    circle.line.fill.background()
    tf = circle.text_frame
    p = tf.paragraphs[0]
    p.text = str(i + 1)
    p.font.size = Pt(18)
    p.font.color.rgb = WHITE
    p.font.bold = True
    p.alignment = PP_ALIGN.CENTER

    add_body_text(slide, title, left, Inches(2.2), Inches(2), Inches(0.6),
                  size=Pt(16), bold=True, color=DARK_TEXT)
    add_body_text(slide, desc, left, Inches(2.7), Inches(2), Inches(2),
                  size=Pt(12), color=DARK_TEXT)

    if i < 5:
        arrow = slide.shapes.add_shape(
            MSO_SHAPE.RIGHT_ARROW, left + Inches(1.65), Inches(1.6), Inches(0.4), Inches(0.3))
        arrow.fill.solid()
        arrow.fill.fore_color.rgb = RGBColor(0xBB, 0xCC, 0xDD)
        arrow.line.fill.background()

# 底部：三种运行模式
add_body_text(slide, "三种运行模式", Inches(0.8), Inches(5.2), Inches(3), Inches(0.4),
              size=Pt(18), bold=True, color=ACCENT_BLUE)
add_card(slide, "initial-save", "预生成 prompt 并保存\n供人工检查或复用", Inches(0.8), Inches(5.7), Inches(3.5), Inches(1.2))
add_card(slide, "initial-chat", "一次性 LLM 对话修复\n无反馈循环", Inches(4.8), Inches(5.7), Inches(3.5), Inches(1.2))
add_card(slide, "chatrepair ★", "多轮对话 + 反馈循环\n核心方法", Inches(8.8), Inches(5.7), Inches(3.8), Inches(1.2), GREEN)

# ============================================================
# Slide 4: 技术工作
# ============================================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_bg(slide, WHITE)
add_title_bar(slide, "已完成的工程技术工作")

works = [
    ("环境适配", [
        "DeepSeek SDK 兼容 (openai → OpenAI client)",
        "WSL ↔ Windows 跨环境命令执行 (bash -c 回退)",
        "编码统一：全部 latin-1 → UTF-8",
        "模型切换：deepseek-chat → deepseek-v4-pro",
    ]),
    ("Bug 修复", [
        "failingtests_path 未定义导致崩溃",
        "patch=='' 无限循环不递增计数器",
        "LLM 无 markdown 回复时代码提取失败",
        "rmtree 重 checkout 破坏 Defects4J 元数据",
    ]),
    ("功能增强", [
        "单 bug 运行模式 (第4个命令行参数)",
        "API 密钥 .env 安全化 + python-dotenv",
        "进度输出：关键步骤可视化",
        "纯 Java 代码提取策略 (去除 markdown)",
    ]),
]

for col, (title, items) in enumerate(works):
    left = Inches(0.6 + col * 4.2)
    add_body_text(slide, title, left, Inches(1.5), Inches(3.5), Inches(0.5),
                  size=Pt(22), bold=True, color=ACCENT_BLUE)
    add_bullet_list(slide, [f"• {x}" for x in items], left, Inches(2.1), Inches(3.8), Inches(4.5), size=Pt(15))

# ============================================================
# Slide 5: 实验方案
# ============================================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_bg(slide, WHITE)
add_title_bar(slide, "实验方案设计")

experiment_items = [
    "▎数据集：Defects4J — 6 个 Java 项目 (Chart/Closure/Lang/Math/Mockito/Time)，共 54 个真实 bug",
    "▎修复粒度：Single-function — LLM 直接输出完整修复后的函数体",
    "▎模型：DeepSeek-v4-pro，通过 OpenAI 兼容 API 调用",
    "▎反馈类型 (6 种)：",
    "    0 = FNT 新测试失败  |  1 = FOT 旧测试仍失败  |  2 = CE 编译错误(有信息)",
    "    3 = CE 编译错误(无信息)  |  4 = TOUT 超时(60s)  |  5 = P 通过全部测试",
    "▎终止条件：找到 P(Plausible Patch) 或达到 Max_Tries=24 轮",
    "▎单轮对话长度：Max_Conv_len=3，超过后自动重置上下文开始新一轮",
    "▎已测试范围：Lang 项目 10 个 bug (1/10/11/12/14/24/29/42/43/51)",
]
add_bullet_list(slide, experiment_items, Inches(0.8), Inches(1.6), Inches(11.5), Inches(5.5), size=Pt(18))

# ============================================================
# Slide 6: 实验结果（核心页）
# ============================================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_bg(slide, WHITE)
add_title_bar(slide, "实验结果")

# 左侧：汇总表
add_body_text(slide, "Lang 项目运行结果", Inches(0.8), Inches(1.5), Inches(5), Inches(0.5),
              size=Pt(22), bold=True, color=ACCENT_BLUE)

# 简化表格用文字
table_text = """┌──────────┬──────────┬─────────────────────┬──────────┐
│  Bug ID  │  总轮次  │    主要反馈类型      │   结果   │
├──────────┼──────────┼─────────────────────┼──────────┤
│  Lang-1  │    26    │  编译错误 (2)        │   失败   │
│ Lang-10  │   46+    │  旧测试仍失败 (1)     │   失败   │
│ Lang-11  │    12    │  超时 (4)            │   失败   │
│ Lang-12  │    24    │  编译错误 (2)        │   失败   │
│ Lang-14  │     2    │  超时→通过 [4,5]    │  ★成功   │
│ Lang-24  │     6    │  超时 (4)            │   失败   │
│ Lang-29  │   进行中 │  —                   │   —      │
│ Lang-42  │   进行中 │  —                   │   —      │
│ Lang-43  │   进行中 │  —                   │   —      │
│ Lang-51  │   进行中 │  —                   │   —      │
└──────────┴──────────┴─────────────────────┴──────────┘"""
add_body_text(slide, table_text, Inches(0.5), Inches(2.2), Inches(6), Inches(5),
              size=Pt(12), color=DARK_TEXT)

# 右侧：关键指标
right_x = Inches(7.5)
add_body_text(slide, "关键指标", right_x, Inches(1.5), Inches(4), Inches(0.5),
              size=Pt(22), bold=True, color=ACCENT_BLUE)

metrics = [
    ("1 / 10", "当前成功率 (10%)", GREEN),
    ("60%", "编译错误占比", RED),
    ("25%", "超时占比", ORANGE),
    ("15%", "测试失败占比", ORANGE),
    ("2 轮", "成功修复所需轮次", GREEN),
]
for i, (num, label, color) in enumerate(metrics):
    y = Inches(2.3 + i * 0.9)
    # 数字
    add_body_text(slide, num, right_x, y, Inches(2.5), Inches(0.7),
                  size=Pt(36), bold=True, color=color)
    # 标签
    add_body_text(slide, label, right_x + Inches(1.8), y + Inches(0.1), Inches(3), Inches(0.6),
                  size=Pt(16), color=DARK_TEXT)

# ============================================================
# Slide 7: 成功案例
# ============================================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_bg(slide, WHITE)
add_title_bar(slide, "成功案例：Lang-14")

# 左侧：Bug 描述
add_body_text(slide, "Bug 信息", Inches(0.8), Inches(1.6), Inches(5), Inches(0.5),
              size=Pt(22), bold=True, color=ACCENT_BLUE)
bug_info = [
    "• 文件：StringUtils.java",
    "• 函数：equals(CharSequence, CharSequence)",
    "• 问题：cs1.equals(cs2) 无法正确比较 String 和 StringBuilder",
    "• 测试：testEquals — assertTrue(equals(\"foo\", new StringBuilder(\"foo\"))) → 失败",
]
add_bullet_list(slide, bug_info, Inches(0.8), Inches(2.2), Inches(5.5), Inches(3), size=Pt(16))

# 右侧：修复对比
add_body_text(slide, "修复对比", Inches(7.5), Inches(1.6), Inches(5), Inches(0.5),
              size=Pt(22), bold=True, color=GREEN)

# 修复前
add_body_text(slide, "修复前 ✗", Inches(7.5), Inches(2.3), Inches(5), Inches(0.4),
              size=Pt(16), bold=True, color=RED)
add_body_text(slide, 'return cs1.equals(cs2);', Inches(7.5), Inches(2.7), Inches(5), Inches(0.5),
              size=Pt(15), color=DARK_TEXT)

# 修复后
add_body_text(slide, "修复后 ✓ (第2轮生成)", Inches(7.5), Inches(3.5), Inches(5), Inches(0.4),
              size=Pt(16), bold=True, color=GREEN)
add_body_text(slide, 'return cs1.toString().equals(cs2.toString());', Inches(7.5), Inches(3.9), Inches(5), Inches(0.5),
              size=Pt(15), color=DARK_TEXT)

# 分析
add_body_text(slide, "分析", Inches(7.5), Inches(4.8), Inches(5), Inches(0.4),
              size=Pt(18), bold=True, color=ACCENT_BLUE)
add_body_text(slide, "将两个 CharSequence 都转成 String 再比较，\n确保 StringBuilder 等实现也能正确逐字符对比。\n第1轮修复导致超时 → 反馈后第2轮成功。",
              Inches(7.5), Inches(5.3), Inches(5), Inches(1.5), size=Pt(14), color=DARK_TEXT)

# 底部
add_body_text(slide, "反馈列表: [4, 5]  →  第2次尝试通过  →  First plausible patch at 2 tries!",
              Inches(0.8), Inches(6.5), Inches(11), Inches(0.5), size=Pt(16), bold=True, color=GREEN)

# ============================================================
# Slide 8: 问题与方案
# ============================================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_bg(slide, WHITE)
add_title_bar(slide, "遇到的问题与解决方案")

problems = [
    ("API 兼容性", "SDK v2.28.0 不支持模块级配置", "改用 OpenAI() client 模式"),
    ("WSL 跨环境", "Windows Python 找不到 Linux 命令", "bash -c 回退机制"),
    ("编码混乱", "latin-1 解码含特殊字符的源码崩溃", "统一 UTF-8 + safe_decode 容错"),
    ("代码提取失败", "LLM 不遵循 markdown 格式要求", "新增纯 Java 代码识别策略"),
    ("密钥泄露风险", "API key 硬编码在 constants.py", ".env 环境变量 + .gitignore"),
    ("LLM 生成质量", "经常产生语法错误的 Java 代码", "多轮反馈纠正 + 编译错误信息回传"),
]

for i, (problem, cause, solution) in enumerate(problems):
    y = Inches(1.6 + i * 0.85)
    add_body_text(slide, f"{problem}", Inches(0.8), y, Inches(2.2), Inches(0.5),
                  size=Pt(16), bold=True, color=ACCENT_BLUE)
    add_body_text(slide, f"问题：{cause}", Inches(3.2), y, Inches(4.5), Inches(0.5),
                  size=Pt(14), color=RED)
    add_body_text(slide, f"→ {solution}", Inches(7.8), y, Inches(5), Inches(0.5),
                  size=Pt(14), color=GREEN)

# ============================================================
# Slide 9: 后续计划
# ============================================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_bg(slide, WHITE)
add_title_bar(slide, "后续工作计划")

plans = [
    ("短期\n(2-4周)", [
        "完成 Lang 项目全部 10 个 bug 实验",
        "扩展到 Chart、Math 等项目",
        "增加 single-line/hunk 粒度对比实验",
    ]),
    ("中期\n(1-2月)", [
        "多模型对比：GPT-4、Claude vs DeepSeek",
        "分析 LLM 修复失败的根因模式",
        "引入 AST 结构信息辅助 prompt 构造",
    ]),
    ("长期\n(3月+)", [
        "优化反馈策略：减少编译错误类无效反馈",
        "探索 few-shot 示例的动态选择机制",
        "撰写论文、整理实验数据",
    ]),
]

for i, (phase, items) in enumerate(plans):
    left = Inches(0.6 + i * 4.2)
    # 阶段标签
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, left, Inches(1.6), Inches(3.8), Inches(0.8))
    shape.fill.solid()
    shape.fill.fore_color.rgb = ACCENT_BLUE
    shape.line.fill.background()
    tf = shape.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = phase
    p.font.size = Pt(20)
    p.font.color.rgb = WHITE
    p.font.bold = True
    p.alignment = PP_ALIGN.CENTER

    add_bullet_list(slide, [f"• {x}" for x in items],
                    left, Inches(2.7), Inches(3.8), Inches(3.5), size=Pt(15))

# ============================================================
# Slide 10: 结尾
# ============================================================
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_bg(slide, DARK_BLUE)

line = slide.shapes.add_shape(
    MSO_SHAPE.RECTANGLE, Inches(5.5), Inches(3.2), Inches(2.5), Inches(0.05))
line.fill.solid()
line.fill.fore_color.rgb = ACCENT_BLUE
line.line.fill.background()

add_body_text(slide, "谢谢！", Inches(0), Inches(1.5), prs.slide_width, Inches(1.5),
              size=Pt(56), bold=True, color=WHITE)
add_body_text(slide, "请评委老师批评指正", Inches(0), Inches(3.6), prs.slide_width, Inches(0.8),
              size=Pt(24), color=RGBColor(0xBB, 0xCC, 0xDD))

# 保存到 docs/ 目录（脚本位于 scripts/ 下，上一层即项目根）
import os as _os
_project_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
output_path = _os.path.join(_project_root, "docs", "中期检查_CHATREPAIR.pptx")
prs.save(output_path)
print(f"PPT saved to: {output_path}")
