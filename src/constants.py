import os

# 项目根目录（constants.py 位于 src/ 下）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ============================================================
# 项目名称常量（Defects4J 中的 6 个 Java 项目）
# ============================================================
CHART = "Chart"
CLOSURE = "Closure"
LANG = "Lang"
MATH = "Math"
MOCKITO = "Mockito"
TIME = "Time"

PROJECTS = ["Chart", "Closure", "Lang", "Math", "Mockito", "Time"]

# ============================================================
# 补丁类型（对应开发者修复的三种方式）
# ============================================================
PATCH_TYPE_REPLACE = 'replace'  # 替换型补丁：修改某几行代码
PATCH_TYPE_INSERT = 'insert'    # 插入型补丁：在某位置新增代码
PATCH_TYPE_DELETE = 'delete'    # 删除型补丁：删除整个函数后替换为新函数

LOG_FILE = os.path.join(PROJECT_ROOT, "logs.txt")

# ============================================================
# 数据目录路径（相对于项目根目录 PROJECT_ROOT）
# ============================================================
PATCH_JSON_FOLDER = os.path.join(PROJECT_ROOT, "patches")
CHATREPAIR_FOLDER = os.path.join(PROJECT_ROOT, "chatrepair")
INITIALCHAT_FOLDER = os.path.join(PROJECT_ROOT, "initialchat")
INITIAL_PROMPT_FOLDER = os.path.join(PROJECT_ROOT, "initial")

BUGGY_PROJECT_FOLDER = os.path.join(PROJECT_ROOT, "bugs")
FAILING_TEST_FILE = "failing_tests"                # 文件名，在 BUGGY_PROJECT_FOLDER 下使用

# 不同项目源码目录下测试文件的前缀路径（用于定位测试文件）
TEST_FILEPATH_PREFIX = {"Closure": "test", "Mockito": "test", "Chart": "tests", "Lang": "src/test/java",
                        "Math": "src/test/java", "Time": "src/test/java"}
TEST_FILEPATH_PREFIX_1 = "src/test"                # 备选路径

# ============================================================
# Defects4J 命令模板
# %s 会被替换为项目名、bug 版本号、工作目录
# ============================================================
DEFECTS4J_CHECKOUT = "defects4j checkout -p %s -v %s -w %s"  # 检出 buggy 版本
DEFECTS4J_COMPILE = "defects4j compile"                       # 编译项目
DEFECTS4J_TEST = "defects4j test"                             # 运行测试
DEFECTS4J_COMPILE_TEST = "defects4j compile ; defects4j test"  # 编译并测试
TEST_TIMEOUT_MAX_S = 60                                       # 测试超时时间（秒）

# ============================================================
# Prompt 模板 — INFILL 标记
# ============================================================
INFILL = ">>>[INFILL]<<<\n"  # 在代码中标记需要修复的位置，让 LLM 在此处填补正确代码

# ============================================================
# Prompt 模板 — 角色设定 & Few-Shot 示例
# ============================================================
INITIAL_APR_TOOL = "You are an Automated Program Repair Tool.\n"
INTIIAL_APR_EXAMPLE = "Here is an example of a repair job:\n"

# ============================================================
# Prompt 模板 — 不同粒度的开头描述
# ============================================================
INITIAL_Single_line = "The following code contains a buggy line that has been removed:\n"
INITIAL_Single_hunk = "The following code contains a buggy hunk that has been removed:\n"
INITIAL_Single_function = "The following code contains a bug:\n"

# ============================================================
# Prompt 模板 — 展示被删除的原始 buggy 代码
# ============================================================
INITIAL_Single_line_2 = "This was the original buggy line which was removed by the infill location\n"
INITIAL_Single_hunk_2 = "This was the original buggy hunk which was removed by the infill location\n"

# ============================================================
# Prompt 模板 — 测试失败信息
# ============================================================
Failure_Test = "The code fails on this test:\n"
Failure_Test_line = "\non this test line:\n"
Failure_Test_error = "with the following test error:\n"

# 旧版本 prompt 结尾（已注释掉，保留供参考）：
# INITIAL_Single_line_final = "\nPlease provide the correct line at the infill location.\n"
# INITIAL_Single_hunk_final = "\nPlease provide the correct hunk at the infill location.\n"
# INITIAL_Single_function_final = "\nPlease provide the correct function.\n"

# ============================================================
# Prompt 模板 — 结尾引导语（要求 LLM 返回 Java markdown 代码块）
# ============================================================
INITIAL_Single_line_final = "\nPlease provide an analysis of the problem and the expected behaviour of the correct fix, and then output the correct line of code. Return only the pure Java code without markdown code block formatting.\n"
INITIAL_Single_hunk_final = "\nPlease provide an analysis of the problem and the expected behaviour of the correct fix, and then output the correct code. Return only the pure Java code without markdown code block formatting.\n"
INITIAL_Single_function_final = "\nPlease provide an analysis of the problem and the expected behaviour of the correct fix, and then output the complete corrected function. Return only the pure Java code without markdown code block formatting.\n"

# ============================================================
# 反馈话术 — 根据验证结果分类
# 这些反馈会追加到下一轮对话的 prompt 中，告诉 LLM 出了什么问题
#
# fb_list 反馈编码含义：
#   0 = FNT:  产生了新的测试失败 (Failure New Test)
#   1 = FOT:  原来的测试仍然失败 (Failure Old Test)
#   2 = CE:   编译错误，有具体错误信息 (Compilation Error, with message)
#   3 = CE:   编译错误，无具体信息 (Compilation Error, generic)
#   4 = TOUT: 测试执行超时 (Timeout)
#   5 = P:    补丁通过所有测试 (Plausible / Pass)
# ============================================================
FeedBack_0 = "The fixed version is still not correct."
FeedBack_1 = "It still does not fix the original test failure."
FeedBack_2 = "Code has the following compilation error: "
FeedBack_3 = "Code has compilation error."
FeedBack_4 = "The program timed out while executing the test cases in 60s."

# ============================================================
# Alternative Patch 阶段的 prompt
# 当找到一个 plausible patch 后，要求 LLM 基于已有补丁生成更多替代方案
# ============================================================
Alt_Instruct_1 = "It can be fixed by these possible patches:\n"
Alt_Instruct_2 = "Please generate an alternative patch in the form of Java Markdown code block."

Alt_Instruct_3 = "It can be fixed by these possible correct version:\n"
Alt_Instruct_4 = "Please generate an alternative correct version of the function in the form of Java Markdown code block."

# ============================================================
# 统计文件名
# ============================================================
FEEDBACK_STATISTICS_FILE = 'feedback_statistics.csv'             # 反馈统计：记录每轮反馈类型
ALTERNATIVES_STATISTICS_FILE = 'alternatives_statistics.csv'     # 替代补丁统计：记录各类补丁数量
INITIALCHAT_STATISTIFCS_FILE = 'initialchat_statistics.csv'     # 初始对话统计

# ============================================================
# initial-chat 模式配置
# ============================================================
NUMOFREPEAT_PER_BUG = 24  # 每个 bug 的最大重复尝试次数
# 补丁结果分类标签：FNT=新测试失败, FOT=旧测试仍失败, CE=编译错误, TOUT=超时, P=通过
PATCH_FAILURE_CATEGORY = ['FNT','FOT','CE','CE','TOUT','P']

# ============================================================
# chatrepair 模式配置
# ============================================================
Max_Tries = 24        # 每个 bug 的最大总尝试次数（包含 initial repair + alternative 两个阶段）
Max_Conv_len = 3      # 单轮对话的最大轮次（到达后重新开始一轮新的 dialogue）

# ============================================================
# API 配置 — 从环境变量读取，避免密钥泄漏
# 复制 .env.example 为 .env 并填入真实密钥，或直接设置环境变量：
#   export CHATREPAIR_API_KEY="sk-xxx"
#   export CHATREPAIR_MODEL="deepseek-v4-pro"
#   export CHATREPAIR_BASE_URL="https://api.deepseek.com/v1"
# ============================================================
# 尝试从 .env 文件加载（如果安装了 python-dotenv）
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(PROJECT_ROOT, '.env')
    load_dotenv(_env_path)
except ImportError:
    pass

MODEL = os.environ.get("CHATREPAIR_MODEL", "deepseek-v4-pro")
API_KEY = os.environ.get("CHATREPAIR_API_KEY", "")
BASE_URL = os.environ.get("CHATREPAIR_BASE_URL", "https://api.deepseek.com/v1")