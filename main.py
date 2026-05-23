# ============================================================
# main.py — CHATREPAIR 核心实现
# 用 LLM 对 Defects4J 数据集中的 Java bug 进行自动程序修复 (APR)
#
# 三种运行模式（通过第一个命令行参数切换）：
#   1. initial-save ：预生成初始 prompt 并保存到 initial/ 目录
#   2. initial-chat ：用初始 prompt 与 LLM 一次性对话修复（无反馈循环）
#   3. chatrepair   ：带反馈循环的多轮对话修复（CHATREPAIR 核心方法）
#
# 修复的三种粒度（通过第三个命令行参数 y/n 切换）：
#   y = single-function ：LLM 直接输出完整修复后的函数
#   n = single-line/hunk：LLM 只输出替换行/代码块（用 >>>[INFILL]<<< 标记占位）
# ============================================================

import json
import os
import re
import difflib
import sys
import time

import shutil
from openai import OpenAI
import subprocess
from constants import *

# 全局变量：记录上一轮的失败测试全名
# 用于判断补丁是产生了"新的"测试失败，还是原来的测试仍未修复
previous_failure_test = ''


# ============================================================
# 模式一：initial-save — 为所有 bug 预生成初始 prompt 并保存到文件
# 方便后续人工检查或复用
# ============================================================
def save_initial(project, all_single_function_flag, bug_no=None):
    """遍历项目 patches/ 下的 JSON 文件，生成初始 prompt 并写入 initial/ 目录。
       若指定 bug_no（如 '1'），则只处理该 bug 的 JSON 文件。"""
    files = os.listdir(os.path.join(PATCH_JSON_FOLDER, project))
    if bug_no is not None:
        files = [f for f in files if f.rstrip('.json') == bug_no]
    for file in files:
        initial_prompt = ''
        if all_single_function_flag == True:
            initial_prompt = construct_single_function_initial_prompt(project, file)
        else:
            initial_prompt = construct_initial_prompt(project, file)
        if not initial_prompt == '':
            f = open_file(os.path.join(INITIAL_PROMPT_FOLDER, project, file.rstrip(".json") + ".txt"), 'w')
            f.write(initial_prompt)
    print("Success!\nInitial Prompt is saved in " + INITIAL_PROMPT_FOLDER + "/" + project + "!")


# ============================================================
# 模式二：initial-chat — 用初始 prompt 与 LLM 一次性对话修复
# 流程：发送 prompt → 拿到回复 → 编译+测试验证 → 记录结果 → 下一个 bug
# 没有反馈循环（不管结果是成功还是失败，都不会把错误信息发给 LLM 重试）
# ============================================================
def chat_initial(project, all_single_function_flag, bug_no=None):
    """对每个 bug 发送初始 prompt，LLM 一次回复后直接验证并记录结果到 initialchat/。
       若指定 bug_no（如 '1'），则只处理该 bug。"""
    client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
    json_files = os.listdir(os.path.join(PATCH_JSON_FOLDER, project))
    if bug_no is not None:
        json_files = [f for f in json_files if f.rstrip('.json') == bug_no]
    for json_file in json_files:
        i = 0
        no = json_file.rstrip('.json')
        while i < NUMOFREPEAT_PER_BUG:  # 每个 bug 最多重复尝试 N 次
            initial_prompt = ''
            if all_single_function_flag == True:
                initial_prompt = construct_single_function_initial_prompt(project, json_file)
            else:
                initial_prompt = construct_initial_prompt(project, json_file)
            if not initial_prompt == '':
                # 构造对话上下文（只有 user ↔ assistant 两轮）
                context = [{'role': 'user', 'content': initial_prompt}]
                response = client.chat.completions.create(model=MODEL, messages=context)
                # 暂停 1 秒防止请求频率过高
                time.sleep(1)
                response_text = response.choices[0].message.content
                context.append({'role': 'assistant', 'content': response_text})
                # 从 LLM 回复中提取 Java 代码（去除 markdown 包装）
                patch = match_patch_code(response_text)
                # 没有提取到有效补丁 → 重新尝试
                if patch == '':
                    continue
                result = []
                feedback = validate_patch(patch, project, json_file, all_single_function_flag, result)
                if feedback == 'Exception':
                    continue

                # 保存本轮对话记录到文件
                context_path = os.path.join(INITIALCHAT_FOLDER, project, 'bug' + no, str(i+1) + '.txt')
                file = open_file(context_path, 'w')
                for element in context:
                    file.write(element['content'])
                    file.write('\n\n')
                if all_single_function_flag:
                    # 单函数模式下额外保存补丁与原始代码的 diff
                    diff_result = diff_buggy_and_new(project, json_file, patch)
                    file.write(diff_result)
                file.close()
                i += 1
            else:
                break
            # 将本轮结果追加到统计 CSV
            file = open_file(os.path.join(INITIALCHAT_FOLDER, INITIALCHAT_STATISTIFCS_FILE), 'a')
            file.write(project + ', ' + no + ', ' + PATCH_FAILURE_CATEGORY[result[0]] + '\n')
            file.close()


# ============================================================
# 工具函数：生成 buggy 函数和新函数的 diff 文本
# used in initial-chat
# ============================================================
def diff_buggy_and_new(project, json_file, new_function):
    """对比 buggy 函数和 LLM 生成的新函数，返回 diff 字符串"""
    no = json_file.rstrip('.json')
    with open(os.path.join(PATCH_JSON_FOLDER, project, json_file), 'r', encoding="utf-8") as f:
        data = json.load(f)
        f.close()
    if not os.path.exists(os.path.join(BUGGY_PROJECT_FOLDER, project + no)):
        os.system(DEFECTS4J_CHECKOUT % (project, no + 'b', os.path.join(BUGGY_PROJECT_FOLDER, project + no)))
    next_line_no = data['0']['next_line_no']
    file_name = data['0']['file_name']
    source_file_path = os.path.join(BUGGY_PROJECT_FOLDER, project + no, file_name)
    buggy_function = get_buggy_function(source_file_path, next_line_no, next_line_no, PATCH_TYPE_DELETE)
    diff = difflib.Differ()
    buggy_squences = [line.strip() for line in buggy_function.splitlines() if line.strip()]
    new_squences = [line.strip() for line in new_function.splitlines() if line.strip()]
    return '\n'.join(diff.compare(buggy_squences, new_squences))


# ============================================================
# 工具函数：对多个 plausible patch 分别生成 diff
# used in chatrepair
# ============================================================
def diff_buggy_and_newlist(project, json_file, new_function_list):
    """对多个 plausible patch 分别生成 diff 文本列表"""
    no = json_file.rstrip('.json')
    with open(os.path.join(PATCH_JSON_FOLDER, project, json_file), 'r', encoding="utf-8") as f:
        data = json.load(f)
        f.close()
    if not os.path.exists(os.path.join(BUGGY_PROJECT_FOLDER, project + no)):
        os.system(DEFECTS4J_CHECKOUT % (project, no + 'b', os.path.join(BUGGY_PROJECT_FOLDER, project + no)))
    next_line_no = data['0']['next_line_no']
    file_name = data['0']['file_name']
    source_file_path = os.path.join(BUGGY_PROJECT_FOLDER, project + no, file_name)
    buggy_function = get_buggy_function(source_file_path, next_line_no, next_line_no, PATCH_TYPE_DELETE)
    diff = difflib.Differ()
    buggy_squences = [line.strip() for line in buggy_function.splitlines() if line.strip()]
    diff_result = []
    for new_function in new_function_list:
        new_squences = [line.strip() for line in new_function.splitlines() if line.strip()]
        diff_result.append('\n'.join(diff.compare(buggy_squences, new_squences)))
    return diff_result


# ============================================================
# 模式三的入口：go_chat_repair — 遍历项目所有 bug，逐个调用 chat_repair
# ============================================================
def go_chat_repair(project, all_single_function_flag, bug_no=None):
    """遍历项目中的所有 bug，逐一执行 chat_repair 多轮修复流程。
       若指定 bug_no（如 '1'），则只处理该 bug。"""
    client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
    files = os.listdir(os.path.join(PATCH_JSON_FOLDER, project))
    if bug_no is not None:
        files = [f for f in files if f.rstrip('.json') == bug_no]
    if len(files) == 0:
        print("No bugs to process. Available bugs in patches/" + project + "/: " + ", ".join(sorted([f.rstrip('.json') for f in os.listdir(os.path.join(PATCH_JSON_FOLDER, project))])))
        return
    i = 0
    while i < len(files):
        bug_name = files[i].rstrip('.json')
        print(f"[{project}-{bug_name}] Constructing prompt...")
        initial_prompt = ''
        if all_single_function_flag == True:
            initial_prompt = construct_single_function_initial_prompt(project, files[i])
        else:
            initial_prompt = construct_initial_prompt(project, files[i])
        # 跳过不符合要求的 bug（如 multi-hunk 的 bug，prompt 为空）
        if initial_prompt == '':
            print(f"[{project}-{bug_name}] Skipped (empty prompt)")
            i += 1
        if not initial_prompt == '':
            print(f"[{project}-{bug_name}] Starting chatrepair (max {Max_Tries} tries)...")
            # chat_repair 抛出异常时不跳过当前 bug，保留 i 以便重试
            if chat_repair(project, initial_prompt, files[i], all_single_function_flag) != 'Exception':
                i += 1


# ============================================================
# CHATREPAIR 核心流程（单个 bug 的完整修复流程）
#
# 分两个阶段：
#   阶段一：Plausible Patch 生成
#     多轮对话 → 编译测试 → 失败则带着反馈重试 → 直到找到至少一个通过的补丁
#   阶段二：Alternative Patch 生成
#     基于已找到的补丁，让 LLM 生成更多替代方案，去重后保存
# ============================================================
def chat_repair(project, initial_prompt, json_file, all_single_function_flag):
    """
    对单个 bug 执行 CHATREPAIR 完整流程。

    参数:
        project: 项目名 (Lang/Chart/Closure/Math/Mockito/Time)
        initial_prompt: 构造好的初始 prompt
        json_file: patches/ 下的 JSON 文件名（包含补丁元数据）
        all_single_function_flag: True=single-function模式, False=single-line/hunk模式

    返回:
        plausible_patches 列表，异常时返回 'Exception'
    """
    current_tries = 0       # 当前总尝试次数（跨阶段累计）
    plausible_patches = []  # 已找到的 plausible（通过测试的）补丁列表

    client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

    # 反馈统计变量
    fa = 0  # 连续相同反馈的次数
    fb = 0  # 反馈列表总长度
    first_plausible_try = 0  # 第一次找到 plausible patch 时的尝试次数（为 0 表示一直没找到）

    # ======== 阶段一：找到第一个 Plausible Patch ========
    # 外层 while：每轮是一次新的 dialogue（换一个 conversation 从头开始）
    # 内层 while：同一轮 dialogue 中的多轮对话（Max_Conv_len 次）
    while current_tries < Max_Tries and len(plausible_patches) == 0:
        context = []       # 当前 dialogue 的对话上下文
        current_length = 0 # 当前 dialogue 的对话轮数
        prompt = initial_prompt
        feedback_list = [] # 记录每次验证的反馈编码（用于统计）

        while current_length < Max_Conv_len:
            print(f"  [Try {current_tries+1}/{Max_Tries}] Calling LLM...")
            context.append({'role': 'user', 'content': prompt})
            response = client.chat.completions.create(model=MODEL, messages=context)
            # 暂停 1 秒防止请求频率过高
            time.sleep(1)
            response_text = response.choices[0].message.content
            context.append({'role': 'assistant', 'content': response_text})

            # 从回复中提取 Java 代码
            patch = match_patch_code(response_text)
            # 格式不符合预期 → 跳出当前 dialogue，开始新一轮
            if patch == '':
                print(f"  [Try {current_tries+1}/{Max_Tries}] No code extracted, retrying...")
                current_tries += 1
                break

            print(f"  [Try {current_tries+1}/{Max_Tries}] Validating patch...")
            # 验证补丁：写入 Java 文件 → 编译 → 跑测试 → 返回反馈
            feedback = validate_patch(patch, project, json_file, all_single_function_flag, feedback_list)
            if feedback == '':
                # 空字符串 = 补丁通过所有测试！加入 plausible 列表
                plausible_patches.append(patch)
                current_length += 1
                current_tries += 1
                break
            if feedback == 'Exception':
                return 'Exception'  # 异常情况，向上抛出
            else:
                # 用反馈信息替换 prompt，让 LLM 根据错误修正代码
                prompt = feedback
            current_length += 1
            current_tries += 1

        # 记录本轮 dialogue 的反馈统计
        if feedback_list:
            a, b = process_fb_list(feedback_list)
            fa += a
            fb += b
            file = open_file(os.path.join(CHATREPAIR_FOLDER, project, json_file.rstrip('.json') + '.txt'), 'a')
            file.write('current trys: ' + str(current_tries) + ', feedback list: ' + str(feedback_list) + ' Feedback statistics: ' + str(fa) + '/' + str(fb) + '\n')
            if feedback_list[-1] == 5:  # 5 = P(通过)，标记首次找到 plausible patch 的尝试次数
                first_plausible_try = current_tries
                file.write('current trys: ' + str(current_tries) + ', feedback list: ' + str(feedback_list) + ' First plausible patch at ' + str(current_tries) + ' tries!\n')
            file.close()

        # 保存本 dialogue 的完整对话记录
        context_path = os.path.join(CHATREPAIR_FOLDER, project, 'bug' + json_file.rstrip('.json'),
                                    str(current_tries) + '.txt')
        file = open_file(context_path, 'w')
        for element in context:
            file.write(element['content'])
            file.write('\n\n')
        file.close()

    # 写入反馈统计到 CSV
    file = open_file(os.path.join(CHATREPAIR_FOLDER, FEEDBACK_STATISTICS_FILE), 'a')
    file.write(project + ', ' + json_file.rstrip('.json') + ', ' + str(fa) + ', ' + str(fb) + ', ' + str(first_plausible_try) + '\n')
    file.close()

    # ======== 阶段二：生成 Alternative Patches（替代补丁） ========
    # 当找到至少一个 plausible patch 后，列举已找到的补丁，要求 LLM 生成更多替代方案
    if len(plausible_patches) != 0:
        alternatives_list = []  # 替代补丁的反馈编码列表
        duplicates_num = 0      # 重复补丁计数
        while current_tries < Max_Tries:
            context = []
            patches_prompt = ''
            patch_or_function = 'plausible patch '
            if all_single_function_flag:
                patch_or_function = 'Correct version '
            # 列举所有已找到的 plausible patch，嵌入 prompt
            for i in range(len(plausible_patches)):
                patches_prompt += patch_or_function + str(i+1) + ' :\n' + plausible_patches[i] + '\n'
            # 构造替代补丁 prompt：初始 prompt（去掉结尾引导语）+ 已有补丁列表 + 请生成替代方案
            if all_single_function_flag:
                prompt = delete_substring_to_end(initial_prompt.split('<Example end>')[1].strip(), "Please provide") + Alt_Instruct_3 + patches_prompt + Alt_Instruct_4
            else:
                prompt = delete_substring_to_end(initial_prompt.split('<Example end>')[1].strip(), "Please provide") + Alt_Instruct_1 + patches_prompt + Alt_Instruct_2
            context.append({'role': 'user', 'content': prompt})
            response = client.chat.completions.create(model=MODEL, messages=context)
            time.sleep(1)
            response_text = response.choices[0].message.content
            context.append({'role': 'assistant', 'content': response_text})
            patch = match_patch_code(response_text)
            if patch == '':
                continue
            feedback = validate_patch(patch, project, json_file, all_single_function_flag, alternatives_list)
            if feedback == 'Exception':
                return 'Exception'
            if feedback == '':
                # 去重检查（忽略空格和换行符差异）
                if not_exist(plausible_patches, patch):
                    plausible_patches.append(patch)
                else:
                    duplicates_num += 1
            current_tries += 1
            # 保存替代补丁对话记录
            context_path = os.path.join(CHATREPAIR_FOLDER, project, 'bug' + json_file.rstrip('.json'),
                                        str(current_tries) + '.txt')
            file = open_file(context_path, 'w')
            for element in context:
                file.write(element['content'])
                file.write('\n')
            file.close()

        # 统计所有生成补丁的分类（编译错误 / 测试失败 / 超时 / 通过）
        num_ce_patches, num_f_patches, num_to_patches, num_plausible_patches = proces_alter_list(alternatives_list)
        num_plausible_patches += 1  # 把阶段一找到的那个也算上
        file = open_file(os.path.join(CHATREPAIR_FOLDER, project, json_file.rstrip('.json')) + '.txt', 'a')
        file.write('current trys: ' + str(current_tries) + '. Below is statistics of all generation patches:\n')
        file.write('\nCompilation Error patches number: ' + str(num_ce_patches) + '\nFailure patches number: '
                + str(num_f_patches) + '\nTime out patches number: ' + str(num_to_patches) + '\nPlausible patches number: '
                + str(num_plausible_patches) + '\nDuplicate plausible patches number: ' + str(duplicates_num))
        file.close()
        # 写入替代补丁统计 CSV
        file = open_file(os.path.join(CHATREPAIR_FOLDER, ALTERNATIVES_STATISTICS_FILE), 'a')
        file.write(project + ', ' + json_file.rstrip('.json') + ', ' + str(num_ce_patches) + ', ' + str(num_f_patches) + ', '
                + str(num_to_patches) + ', ' + str(num_plausible_patches) + ', ' + str(duplicates_num) + ', ' + str(len(plausible_patches)) + '\n')
        file.close()
        # 保存所有 plausible patch 与原始代码的 diff
        file = open_file(os.path.join(CHATREPAIR_FOLDER, project, 'bug' + json_file.rstrip('.json'), 'diffpatches.txt'), 'w')
        diff_result = diff_buggy_and_newlist(project, json_file, plausible_patches)
        for result in diff_result:
            file.write(result + '\n\n')
        file.close()
    return plausible_patches


# ============================================================
# 验证补丁：LLM 生成的代码 → 写入 Java 源文件 → 编译 → 运行测试
#
# 返回值含义：
#   ''         : 补丁通过所有测试（成功！）
#   'Exception': 不可恢复的异常（如 markdown 残余、解析失败）
#   其他字符串  : 补丁失败，返回值为构造好的反馈 prompt（供下一轮对话使用）
# ============================================================
def validate_patch(patch, project, json_file, all_single_function_flag, fb_list):
    """
    验证 LLM 生成的补丁是否正确。

    流程：
        1. 检查补丁格式（不能含 markdown 标记）
        2. 备份原始 Java 文件
        3. 根据补丁类型（replace/insert/delete）把 patch 写入 Java 文件
        4. 编译项目
        5. 如果编译通过，运行测试
        6. 恢复原始 Java 文件
        7. 返回反馈信息

    参数:
        patch: LLM 生成的 Java 代码
        project: 项目名
        json_file: 补丁 JSON 文件名
        all_single_function_flag: 是否单函数模式
        fb_list: 反馈编码列表（会被原地修改，追加本次反馈编码）

    返回:
        '' = 通过, 'Exception' = 异常, 非空字符串 = 失败反馈
    """
    # 防止把 markdown 语法写进 Java 文件导致语法错误
    if '```' in patch or patch.strip() == '':
        print("Invalid patch detected, skip this attempt")
        return "Exception"

    global previous_failure_test
    temp_javafile = ''   # 原始文件备份内容
    javafile_path = ''
    no = json_file.rstrip('.json')

    # 如果本地还没有该 bug 的源码，先 checkout
    if not os.path.exists(os.path.join(BUGGY_PROJECT_FOLDER, project + no)):
        os.system(DEFECTS4J_CHECKOUT % (
            project, no + 'b', os.path.join(BUGGY_PROJECT_FOLDER, project + no)))

    # 读取补丁元数据（文件名、行号、补丁类型）
    with open(os.path.join(PATCH_JSON_FOLDER, project, json_file), 'r', encoding="utf-8") as f:
        data = json.load(f)
        f.close()

    single_line = False
    single_function = False
    file_name = data['0']['file_name']
    patch_type = data['0']['patch_type']
    javafile_path = os.path.join(BUGGY_PROJECT_FOLDER, project + no, file_name)

    # ======== 备份原始 Java 文件（验证完后必须恢复） ========
    with open(javafile_path, mode='r', encoding='utf-8') as javafile:
        temp_javafile = javafile.read()
        javafile.close

    # ======== 根据补丁类型，把 LLM 代码写入 Java 文件 ========
    if all_single_function_flag == False:
        # --- Replace 替换型：删除 from~to 行，插入新代码 ---
        if patch_type == PATCH_TYPE_REPLACE:
            from_line_no = data['0']['from_line_no']
            to_line_no = data['0']['to_line_no']
            if from_line_no == to_line_no:
                single_line = True  # 单行替换
            with open(javafile_path, mode='r', encoding='utf-8') as f1:
                lines = f1.readlines()
            del lines[from_line_no - 1:to_line_no]       # 删除 buggy 行
            lines.insert(from_line_no - 1, patch)         # 插入 LLM 修复代码
            f1.close()
            with open(javafile_path, mode='w', encoding='utf-8') as f2:
                f2.writelines(lines)
            f2.close()

        # --- Insert 插入型：在 next_line_no 之前插入新代码 ---
        if patch_type == PATCH_TYPE_INSERT:
            next_line_no = data['0']['next_line_no']
            with open(javafile_path, mode='r', encoding='utf-8') as f1:
                lines = f1.readlines()
            lines.insert(next_line_no - 1, patch)
            f1.close()
            with open(javafile_path, mode='w', encoding='utf-8') as f2:
                f2.writelines(lines)
                f2.close()

        # --- Delete 删除型：替换整个函数 ---
        if patch_type == PATCH_TYPE_DELETE:
            single_function = True
            next_line_no = data['0']['next_line_no']
            rewrite_function_to_javafile(next_line_no, javafile_path, patch)

    # --- Single-function 模式：始终替换整个函数 ---
    if all_single_function_flag == True:
        next_line_no = data['0']['next_line_no']
        rewrite_function_to_javafile(next_line_no, javafile_path, patch)

    # ======== 编译 + 测试验证 ========
    feedback = construct_feedback_after_validate(project, no, fb_list)

    # ======== 恢复原始 Java 文件 ========
    if feedback == '':
        # 补丁通过！
        with open(javafile_path, mode='w', encoding='utf-8') as javafile:
            javafile.write(temp_javafile)
            javafile.close()
        return ''

    if feedback == 'Exception':
        # 异常
        with open(javafile_path, mode='w', encoding='utf-8') as javafile:
            javafile.write(temp_javafile)
            javafile.close()
        return feedback

    # 补丁失败：恢复文件，在反馈信息末尾追加对应的 prompt 结尾引导语
    with open(javafile_path, mode='w', encoding='utf-8') as javafile:
        javafile.write(temp_javafile)
        javafile.close()

    if single_line:
        feedback += INITIAL_Single_line_final
    if single_function or all_single_function_flag:
        feedback += INITIAL_Single_function_final
    if all_single_function_flag == False and not single_line and not single_function:
        feedback += INITIAL_Single_hunk_final
    return feedback


# ============================================================
# 工具函数：用 LLM 生成的新函数替换 Java 源文件中的整个旧函数
# 通过大括号匹配定位函数的起止行
# ============================================================
def rewrite_function_to_javafile(next_line_no, javafile_path, patch):
    """
    用新函数代码替换源文件中的整个旧函数。

    参数:
        next_line_no: 要替换位置的行号（函数体内部某行）
        javafile_path: Java 源文件路径
        patch: LLM 生成的新函数完整代码
    """
    # 从 next_line_no 向上搜索，找到 method declaration 的行号
    start_line = get_method_declaration_line_no(javafile_path, next_line_no)
    with open(javafile_path, "r", encoding='utf-8') as file:
        lines = file.readlines()
        file.close()
    # 通过大括号计数找到函数的结束行（{ +1, } -1, 归零即结束）
    left_open_brackets = 0
    right_open_brackets = 0
    end_line = start_line - 1
    for line in lines[start_line - 1:-1]:
        left_open_brackets += line.count('{')
        right_open_brackets += line.count('}')
        end_line += 1
        if left_open_brackets == right_open_brackets and not left_open_brackets == 0:
            break
    # 删除旧函数 → 插入新函数
    del lines[start_line - 1:end_line]
    lines.insert(start_line - 1, patch)
    file.close()
    with open(javafile_path, mode='w', encoding='utf-8') as f2:
        f2.writelines(lines)
    f2.close()


# ============================================================
# 编译 + 测试验证，并构造反馈字符串
#
# feedback 编码 (fb_list):
#   0 = FNT  新测试失败
#   1 = FOT  旧测试仍失败
#   2 = CE   编译错误（有具体信息）
#   3 = CE   编译错误（无具体信息，BUILD FAILED）
#   4 = TOUT 测试超时
#   5 = P    补丁通过（Plausible）
# ============================================================
def construct_feedback_after_validate(project, no, fb_list):
    """
    编译修改后的项目，运行 Defects4J 测试，根据结果构造反馈 prompt。

    返回:
        ''         : 补丁通过所有测试
        'Exception': 无法解析 failing_tests 文件（异常）
        其他字符串  : 包含错误信息的反馈 prompt
    """
    global previous_failure_test

    failingtests_path = os.path.join(BUGGY_PROJECT_FOLDER, project + no, FAILING_TEST_FILE)
    temp_failingtests = ""

    # ======== Step 1: 编译 ========
    flag, stdout, stderr = run_command(DEFECTS4J_COMPILE.split(' '), 'utf-8', os.path.join(BUGGY_PROJECT_FOLDER, project + no), TEST_TIMEOUT_MAX_S)
    if not flag:
        print(stderr)
    pattern = r"BUILD FAILED"
    result = re.search(pattern, stderr, re.DOTALL)
    feedback = ''
    if result:
        # 编译失败：尝试从 stderr 中提取具体错误行
        errs = stderr.split("\n")
        for i in range(len(errs)):
            if re.search(r":\serror:\s", errs[i]):
                errmsg = 'error' + errs[i].split('error')[1]
                feedback = FeedBack_0 + FeedBack_2 + errmsg  # 带具体错误信息
                fb_list.append(2)
                break
        if feedback == '':
            feedback = FeedBack_0 + FeedBack_3  # 无具体错误信息
            fb_list.append(3)
        return feedback  # 编译失败直接返回，无需跑测试

    # ======== Step 2: 编译通过 → 运行测试 ========
    else:
        # 备份 failing_tests 文件（运行测试会覆盖它）
        if os.path.exists(failingtests_path):
            with open(failingtests_path, mode='r', encoding='utf-8') as f:
                temp_failingtests = f.read()
        flag, stdout, stderr = run_command(DEFECTS4J_TEST.split(' '), 'utf-8', os.path.join(BUGGY_PROJECT_FOLDER, project + no), TEST_TIMEOUT_MAX_S)

        if not flag and stderr.count('[ERROR]') != 0:
            feedback = FeedBack_0 + FeedBack_4  # 测试超时
            fb_list.append(4)

        elif flag:
            # 测试成功运行完成，检查 failing_tests 文件
            if is_file_empty_or_not_exists(failingtests_path):
                # failing_tests 为空 = 所有测试通过！
                fb_list.append(5)
                with open(failingtests_path, mode='w', encoding='utf-8') as failingtests:
                    failingtests.write(temp_failingtests)
                    failingtests.close()
                return ''  # 返回空字符串 = 成功

            # 仍有测试失败：解析失败信息
            failure_test, test_error, test_file, test_line_no = get_failure_test_info(failingtests_path)
            if test_file == '' or test_line_no == '':
                # 无法解析，记录日志并返回异常
                print("Warning!!! Unable to handle file [" + failingtests_path + "]while validate the patch.")
                with open(LOG_FILE, 'a') as file:
                    file.write(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())) + "\nWarning!!! Unable to handle file [" + failingtests_path + "] while validate the patch.")
                    file.close()
                with open(failingtests_path, mode='w', encoding='utf-8') as failingtests:
                    failingtests.write(temp_failingtests)
                    failingtests.close()
                return 'Exception'

            # 定位测试源码文件（用于读取失败测试行内容）
            file = os.path.join(BUGGY_PROJECT_FOLDER, project + no, TEST_FILEPATH_PREFIX[project], test_file)
            if not os.path.exists(file):
                file = os.path.join(BUGGY_PROJECT_FOLDER, project + no, TEST_FILEPATH_PREFIX_1, test_file)

            # 判断：新的测试失败 vs 原来的测试仍未修复
            if failure_test == previous_failure_test:
                feedback = FeedBack_0 + FeedBack_1  # 旧失败未修复
                fb_list.append(1)
            else:
                previous_failure_test = failure_test
                fb_list.append(0)  # 新的测试失败
                # 读取失败断言行内容，嵌入反馈
                test_lines = []
                with open(file, mode='r', encoding='utf-8') as test_file:
                    lines = test_file.readlines()[test_line_no - 1:]
                    for line in lines:
                        test_lines.append(line)
                        if line.count(';') == 1:  # 读到分号 = 完整语句
                            break
                feedback = FeedBack_0 + Failure_Test + failure_test + Failure_Test_line + ''.join(
                    test_lines) + Failure_Test_error + test_error

        # 恢复 failing_tests 文件（备份还原）
        with open(failingtests_path, mode='w', encoding='utf-8') as failingtests:
            failingtests.write(temp_failingtests)
            failingtests.close()

    return feedback


# ============================================================
# 统计工具：计算反馈列表中连续相同反馈的次数
# ============================================================
def process_fb_list(fb_list):
    """
    统计反馈列表。

    返回:
        (连续相同反馈次数, 总反馈次数)
        例如 fb_list = [2, 2, 3] → (1, 3)，因为第1和第2次反馈都是2
    """
    a = 0
    for i in range(1, len(fb_list)):
        if fb_list[i] == fb_list[i-1]:
            a += 1  # 相邻两次反馈相同 → +1
    return a, len(fb_list)


# ============================================================
# 统计工具：将 alternatives 的反馈编码统计为四类
# ============================================================
def proces_alter_list(alter_list):
    """
    统计替代补丁列表中各类补丁的数量。

    返回:
        (编译错误数, 测试失败数, 超时数, 通过数)
    """
    num_ce_patches = 0       # 编译错误 (编码 2, 3)
    num_f_patches = 0        # 测试失败 (编码 0, 1)
    num_to_patches = 0       # 超时 (编码 4)
    num_plausible_patches = 0 # 通过 (编码 5)

    for alter in alter_list:
        if alter == 0 or alter == 1:
            num_f_patches += 1
        elif alter == 2 or alter == 3:
            num_ce_patches += 1
        elif alter == 4:
            num_to_patches += 1
        elif alter == 5:
            num_plausible_patches += 1
    return num_ce_patches, num_f_patches, num_to_patches, num_plausible_patches


# ============================================================
# 去重工具：检查补丁是否与已有补丁重复
# 比较时忽略空格和换行符差异
# ============================================================
def not_exist(list, s):
    """
    检查 s 是否不在 list 中（忽略空格/换行）。

    返回:
        True  = 不重复（可以加入列表）
        False = 重复（已存在）
    """
    for l in list:
        if l.replace(' ','').replace('\n','') == s.replace(' ','').replace('\n',''):
            return False
    return True


# ============================================================
# 核心工具：从 LLM 回复中提取 Java 代码块
#
# LLM 回复常见的几种格式：
#   1. ```java\n...\n```      （标准 Java markdown 代码块）
#   2. ```\n...\n```          （无语言标注的代码块）
#   3. 混合了分析文字 + 多个代码块
#   4. 嵌套 markdown
# ============================================================
def match_patch_code(response_text):
    """
    从 LLM 回复中鲁棒地提取 Java 代码。

    策略：
        1. 优先匹配 ```java ... ``` （非贪婪，只取第一个）
        2. 若无，尝试匹配普通 ``` ... ```
        3. 清洗：去掉残留 markdown 标记、java 前缀
    """
    if not response_text:
        return ''

    # 策略 1：优先匹配 ```java ... ``` 格式（非贪婪匹配）
    matches = re.findall(r"```java\s*(.*?)```", response_text, re.DOTALL)
    if matches:
        patch = matches[0]
        patch = patch.strip()
        patch = re.sub(r"```+", "", patch)
        patch = re.sub(r"^\s*java\s*", "", patch)
        return patch.strip()

    # 策略 2：fallback 匹配普通 ``` ... ``` 格式
    matches = re.findall(r"```\s*(.*?)```", response_text, re.DOTALL)
    if matches:
        patch = matches[0]
        patch = patch.strip()
        patch = re.sub(r"```+", "", patch)
        return patch.strip()

    # 策略 3：无 markdown，从回复中提取 Java 代码
    # 查找第一个 Java 特征行，从那里取到末尾
    lines = response_text.split('\n')
    for i, line in enumerate(lines):
        if re.search(r'^\s*(public|private|protected|class\s|@Override|import\s|package\s|return\s|if\s*\(|for\s*\(|while\s*\(|try\s*\{|catch\s*\(|throw\s|/\*\*|//)', line):
            return '\n'.join(lines[i:]).strip()
    return ''


# ============================================================
# 文件工具：检查文件是否为空或不存在
# ============================================================
def is_file_empty_or_not_exists(file_path):
    if not os.path.exists(file_path):
        return True
    file_size = os.path.getsize(file_path)
    if file_size == 0:
        return True
    else:
        return False


# ============================================================
# 字符串工具：截取子串之前的部分
# ============================================================
def delete_substring_to_end(s, subs):
    """
    返回 s 中 subs 之前的部分；若未找到 subs 则返回整个 s。

    用于从初始 prompt 中去除结尾引导语，以便拼接替代补丁引导语。
    """
    index = s.find(subs)
    if index != -1:
        new_string = s[:index]
        return new_string
    else:
        return s


# ============================================================
# 系统命令执行：封装 subprocess.run
# ============================================================
def _safe_decode(data, encoding='utf-8'):
    """安全解码字节数据，UTF-8 失败时回退到 latin-1"""
    try:
        return data.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        return data.decode('latin-1')


def run_command(cmd, encoding='utf-8', cwd=None, timeout=None):
    """
    执行系统命令。

    返回:
        (success: bool, stdout: str, stderr: str)
    """
    try:
        finished = subprocess.run(cmd, capture_output=True, cwd=cwd, timeout=timeout)
        finished.check_returncode()
        return True, _safe_decode(finished.stdout, encoding), _safe_decode(finished.stderr, encoding)
    except subprocess.CalledProcessError:
        return False, _safe_decode(finished.stdout, encoding), _safe_decode(finished.stderr, encoding)
    except subprocess.TimeoutExpired:
        return False, '[ERROR]:{} time out after {} seconds'.format(cmd, timeout), '[ERROR]:{} time out after {} seconds'.format(cmd, timeout)
    except FileNotFoundError:
        shell_cmd = ' '.join(cmd) if isinstance(cmd, list) else cmd
        wsl_cmd = ['bash', '-c', shell_cmd]
        try:
            finished = subprocess.run(wsl_cmd, capture_output=True, cwd=cwd, timeout=timeout)
            finished.check_returncode()
            return True, _safe_decode(finished.stdout, encoding), _safe_decode(finished.stderr, encoding)
        except subprocess.CalledProcessError:
            return False, _safe_decode(finished.stdout, encoding), _safe_decode(finished.stderr, encoding)
        except subprocess.TimeoutExpired:
            return False, '[ERROR]:{} time out after {} seconds'.format(cmd, timeout), '[ERROR]:{} time out after {} seconds'.format(cmd, timeout)


# ============================================================
# 文件操作工具：打开文件，路径不存在时自动创建父目录
# ============================================================
def open_file(path, pattern):
    """
    打开文件。

    参数:
        path: 文件路径
        pattern: 'r'（读）/ 'w'（写）/ 'a'（追加）

    返回:
        file object，如果路径的父目录不存在会自动创建
    """
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    if pattern not in ['r', 'w', 'a']:
        return ''
    file = open(path, pattern)
    return file


# ============================================================
# Prompt 构造 — single-line / single-hunk 模式
# 只处理单块补丁（num_of_hunks == 1），multi-hunk 跳过
# ============================================================
def construct_initial_prompt(project, json_file):
    """
    为 single-line 或 single-hunk 补丁构造初始 prompt。

    prompt 结构：
        1. 角色设定（You are an APR Tool）
        2. Few-Shot 示例（Lang_example.txt）
        3. 带 INFILL 标记的 buggy 代码
        4. 测试失败信息
        5. 结尾引导语（请输出分析+修复代码）

    参数:
        project: 项目名
        json_file: patches/ 下的 JSON 文件名

    返回:
        构造好的 prompt 字符串，如果条件不满足（如 multi-hunk）则返回 ''
    """
    global previous_failure_test
    no = json_file.rstrip('.json')
    with open(os.path.join(PATCH_JSON_FOLDER, project, json_file), 'r', encoding="utf-8") as f:
        data = json.load(f)
        f.close()
        num_of_hunks = data['num_of_hunks']
        # 只处理单块补丁，multi-hunk 暂不支持
        if num_of_hunks == 1:
            # 如果本地还没有该 bug 的源码，先 checkout
            bug_dir = os.path.join(BUGGY_PROJECT_FOLDER, project + no)
            if not os.path.exists(bug_dir):
                os.system(DEFECTS4J_CHECKOUT % (project, no + 'b', bug_dir))
            else:
                run_command(['git', 'checkout', '--', '.'], cwd=bug_dir)
            file_name = data['0']['file_name']
            patch_type = data['0']['patch_type']
            # prompt 开头 = 角色 + Few-Shot 示例
            initial_prompt = INITIAL_APR_TOOL + INTIIAL_APR_EXAMPLE + get_example('Lang_example.txt')
            single_line = False

            # ---- Replace 替换型 ----
            if patch_type == PATCH_TYPE_REPLACE:
                from_line_no = data['0']['from_line_no']
                to_line_no = data['0']['to_line_no']
                original_buggy_hunk = data['0']['replaced']
                source_file_path = os.path.join(BUGGY_PROJECT_FOLDER, project + no, file_name)
                # 提取函数代码，用 INFILL 替换 buggy 行
                buggy_function = get_buggy_function(source_file_path, from_line_no, to_line_no, PATCH_TYPE_REPLACE)
                if from_line_no == to_line_no:
                    single_line = True
                    # 单行修复 prompt
                    initial_prompt += INITIAL_Single_line + buggy_function + INITIAL_Single_line_2 + original_buggy_hunk
                else:
                    # 多行 hunk 修复 prompt
                    initial_prompt += INITIAL_Single_hunk + buggy_function + INITIAL_Single_hunk_2 + original_buggy_hunk

            # ---- Delete 删除型：展示完整函数，让 LLM 输出新函数 ----
            if patch_type == PATCH_TYPE_DELETE:
                from_line_no = data['0']['from_line_no']
                to_line_no = data['0']['to_line_no']
                next_line_no = data['0']['next_line_no']
                source_file_path = os.path.join(BUGGY_PROJECT_FOLDER, project + no, file_name)
                buggy_function = get_buggy_function(source_file_path, from_line_no, next_line_no, PATCH_TYPE_DELETE)
                initial_prompt += INITIAL_Single_function + buggy_function

            # ---- Insert 插入型：在需要插入的位置放 INFILL 标记 ----
            if patch_type == PATCH_TYPE_INSERT:
                next_line_no = data['0']['next_line_no']
                source_file_path = os.path.join(BUGGY_PROJECT_FOLDER, project + no, file_name)
                buggy_function = get_buggy_function(source_file_path, next_line_no, next_line_no, PATCH_TYPE_INSERT)
                initial_prompt += INITIAL_Single_function + buggy_function

            # 追加测试失败信息
            failure_info = prompt_add_failure_test_info(project, json_file)
            if failure_info != '':
                initial_prompt += failure_info
            else:
                return ''

            # 追加结尾引导语（根据补丁粒度不同）
            if patch_type == PATCH_TYPE_REPLACE or patch_type == PATCH_TYPE_INSERT:
                if single_line:
                    initial_prompt += INITIAL_Single_line_final
                else:
                    initial_prompt += INITIAL_Single_hunk_final
            else:
                initial_prompt += INITIAL_Single_function_final
            return initial_prompt
        else:
            return ''


# ============================================================
# Prompt 构造 — single-function 模式
# 所有 bug（包括 multi-hunk）都可以用这个模式
# ============================================================
def construct_single_function_initial_prompt(project, json_file):
    """
    为 single-function 修复构造初始 prompt。

    与 construct_initial_prompt 的区别：
        - Few-Shot 示例使用 Lang_single_function_example.txt
        - 不展示 INFILL 标记，而是展示完整的 buggy 函数
        - 要求 LLM 返回完整的修复后函数
    """
    global previous_failure_test
    no = json_file.rstrip('.json')
    with open(os.path.join(PATCH_JSON_FOLDER, project, json_file), 'r', encoding="utf-8") as f:
        data = json.load(f)
        f.close()
    # 如果本地还没有该 bug 的源码，先 checkout
    bug_dir = os.path.join(BUGGY_PROJECT_FOLDER, project + no)
    if not os.path.exists(bug_dir):
        os.system(DEFECTS4J_CHECKOUT % (project, no + 'b', bug_dir))
    else:
        # 重置源文件修改（上次失败运行可能留下的脏代码），保留 Defects4J 元数据
        run_command(['git', 'checkout', '--', '.'], cwd=bug_dir)
    # 角色设定 + 单函数版 Few-Shot 示例
    initial_prompt = INITIAL_APR_TOOL + INTIIAL_APR_EXAMPLE + get_example('Lang_single_function_example.txt')
    next_line_no = data['0']['next_line_no']
    file_name = data['0']['file_name']
    source_file_path = os.path.join(BUGGY_PROJECT_FOLDER, project + no, file_name)
    if not os.path.exists(source_file_path):
        print("ERROR: Source file not found: " + source_file_path)
        return ''
    # 提取完整 buggy 函数
    buggy_function = get_buggy_function(source_file_path, next_line_no, next_line_no, PATCH_TYPE_DELETE)
    failure_info = prompt_add_failure_test_info(project, json_file)
    if failure_info != '':
        initial_prompt += INITIAL_Single_function + buggy_function + failure_info + INITIAL_Single_function_final
    else:
        initial_prompt = ''
    return initial_prompt


# ============================================================
# 工具函数：构造 prompt 中的测试失败信息部分
# 从 Defects4J 的 failing_tests 文件读取并格式化
# ============================================================
def prompt_add_failure_test_info(project, json_file):
    """
    构造 prompt 中的测试失败信息。

    格式：
        The code fails on this test: <测试方法全名>
        on this test line: <失败断言行>
        with the following test error: <错误信息>

    返回:
        格式化后的失败信息字符串，出错则返回 ''
    """
    global previous_failure_test
    no = json_file.rstrip('.json')
    failure_test_path = os.path.join(BUGGY_PROJECT_FOLDER, project + no, FAILING_TEST_FILE)
    # 如果失败测试文件不存在或为空，先编译测试一次生成它
    if is_file_empty_or_not_exists(failure_test_path):
        bug_dir = os.path.join(BUGGY_PROJECT_FOLDER, project + no)
        run_command(DEFECTS4J_COMPILE.split(' '), 'utf-8', bug_dir, TEST_TIMEOUT_MAX_S)
        run_command(DEFECTS4J_TEST.split(' '), 'utf-8', bug_dir, TEST_TIMEOUT_MAX_S)

    # 解析 failing_tests 文件
    if is_file_empty_or_not_exists(failure_test_path):
        print("Warning: failing_tests not generated for " + project + no + ", skipping failure info in prompt.")
        return ''
    failure_test, test_error, test_file, test_line_no = get_failure_test_info(failure_test_path)
    if test_file == '' or test_line_no == '':
        print("Warning: Unable to parse failing_tests for " + project + no)
        return ''

    # 更新全局变量：记录当前失败测试（用于后续判断是否新失败）
    previous_failure_test = failure_test

    # 定位测试文件并读取失败断言行的内容
    file = os.path.join(BUGGY_PROJECT_FOLDER, project + no, TEST_FILEPATH_PREFIX[project], test_file)
    if is_file_empty_or_not_exists(file):
        file = os.path.join(BUGGY_PROJECT_FOLDER, project + no, TEST_FILEPATH_PREFIX_1, test_file)
    test_lines = []
    with open(file, mode='r', encoding='utf-8') as test_file:
        lines = test_file.readlines()[test_line_no - 1:]
        for line in lines:
            test_lines.append(line)
            # 忽略字符串中的分号，读到第一个真正的分号（完整语句结束）
            if re.sub(r'\".*?\"', '', line).count(';') == 1:
                break

    return Failure_Test + failure_test + Failure_Test_line + ''.join(test_lines) + Failure_Test_error + test_error


# ============================================================
# 工具函数：从源文件中提取函数代码，并按需插入 INFILL 标记
# ============================================================
def get_buggy_function(file_path, from_line_no, to_line_no, patch_type):
    """
    提取函数代码并根据补丁类型处理。

    参数:
        file_path: Java 源文件路径
        from_line_no: 替换/删除起始行号
        to_line_no: 替换/删除结束行号
        patch_type: REPLACE / INSERT / DELETE

    处理逻辑:
        - REPLACE: 删除 from~to 行的代码，插入 >>>[INFILL]<<< 标记
        - INSERT : 在 to_line_no 处插入 >>>[INFILL]<<< 标记
        - DELETE : 直接返回完整函数（由调用方处理）

    返回:
        处理后的函数代码字符串
    """
    start_line_no = get_method_declaration_line_no(file_path, from_line_no)
    function_lines = get_method_lines(file_path, start_line_no)
    if patch_type == PATCH_TYPE_REPLACE:
        # 删除 buggy 行（左闭右开），插入 INFILL 标记
        del function_lines[from_line_no - start_line_no:to_line_no - start_line_no + 1]
        function_lines.insert(from_line_no - start_line_no, INFILL)
    if patch_type == PATCH_TYPE_INSERT:
        # 在指定位置后方插入 INFILL 标记
        function_lines.insert(to_line_no - start_line_no, INFILL)
    return ''.join(function_lines)


# ============================================================
# 工具函数：解析 Defects4J 的 failing_tests 文件
#
# 文件格式示例：
#   --- org.apache.commons.lang3.time.DateUtilsTest::testIsSameLocalTime_Cal
#   junit.framework.AssertionFailedError: LANG-677
#   at org.apache.commons.lang3.time.DateUtilsTest.testIsSameLocalTime_Cal(DateUtilsTest.java:1254)
# ============================================================
def get_failure_test_info(test_file_path):
    """
    从 failing_tests 文件中提取：
        - 失败测试方法全名
        - 错误信息
        - 测试文件名（路径）
        - 失败行号

    返回:
        (failing_test, test_error, test_file, test_line_no)
        如果解析失败，test_file 和 test_line_no 为 ''
    """
    with open(test_file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()
        failing_test = lines[0].strip('--- ').rstrip()      # 第1行：测试方法全名
        test_error = lines[1].rstrip()                        # 第2行：错误信息
        test_function = failing_test.split("::")[1].rstrip()  # 纯方法名（去掉类名前缀）
        # 从第3行开始查找包含方法名的栈跟踪行
        for i in range(2, len(lines)):
            if test_function in lines[i]:
                try:
                    test_line_no = int(re.search(r'(\d+)\)', lines[i]).group(1))  # 提取行号
                    # 提取文件名：取 ".方法名" 之前的部分，转换 . 为 / ，加 .java
                    test_file = delete_substring_to_end(lines[i],'.'+test_function).split('at ')[1].replace('.', '/') + '.java'
                    return failing_test, test_error, test_file, test_line_no
                except AttributeError as e:
                    print("Warning!!! Unable to handle file [" + test_file_path + "]while get the the test info:",e)
                    with open(LOG_FILE, 'a') as file:
                        file.write(time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(time.time()))+"\nWarning!!! Unable to handle file [" + test_file_path + "] while get the the test info.")
                        file.close()
                    return failing_test, test_error, '', ''
        # 格式不符合预期
        return failing_test, test_error, '', ''


# ============================================================
# 工具函数：从源文件中向上查找最近的方法声明行号
# 从 line_no 向上搜索，找到第一个包含 public/private/protected 方法签名的行
# ============================================================
def get_method_declaration_line_no(source_file_path, line_no):
    """
    从 line_no 向上搜索，找到最近的方法声明行号。

    匹配模式：修饰符 (public|private|protected) + 方法签名 + {
    例如：public static boolean isSameLocalTime(Calendar cal1, Calendar cal2) {
    """
    with open(source_file_path, "r", encoding="utf-8") as file:
        lines = file.readlines()
    for i in range(line_no-1, -1, -1):
        if i >= len(lines):
            continue
        if re.search(r'(public|private|protected).*\(.*\)\s*\{', lines[i]):
            return i+1
    return 1


# ============================================================
# 工具函数：获取从方法声明行开始的完整函数代码行列表
# 通过大括号配对确定函数结束位置
# ============================================================
def get_method_lines(source_file_path, start_line_no):
    """
    从方法声明行开始，通过大括号匹配提取完整的函数代码行。

    参数:
        source_file_path: Java 源文件路径
        start_line_no: 方法声明所在行号

    返回:
        list[str] — 从方法声明到方法结束的所有代码行

    算法：扫描每一行，{ 计数 +1, } 计数 -1，归零即函数结束
    """
    with open(source_file_path, "r", encoding='utf-8') as file:
        lines = file.readlines()[start_line_no - 1:]
        file.close()
    left_open_brackets = 0
    right_open_brackets = 0
    function_lines = []
    for line in lines:
        function_lines.append(line)
        left_open_brackets += line.count('{')
        right_open_brackets += line.count('}')
        # 左右大括号数量相等且都不为 0 → 函数体结束
        if left_open_brackets == right_open_brackets and not left_open_brackets == 0:
            break
    return function_lines


# ============================================================
# 工具函数：读取 Few-Shot 示例文件
# ============================================================
def get_example(example_file):
    """读取 Few-Shot 示例文件内容"""
    with open(example_file, 'r') as f:
        example = f.read()
        f.close()
        return example


# ============================================================
# 程序入口
#
# 用法：python main.py <instruction> <project> <single_function_flag>
#
# 参数说明：
#   instruction      : initial-save / initial-chat / chatrepair
#   project          : Lang / Chart / Closure / Math / Mockito / Time
#   single_func_flag : y（single-function 模式）/ n（single-line/hunk 模式）
#
# 示例：
#   python main.py chatrepair Lang y    →  对 Lang 项目以 single-function 模式执行 chatrepair
#   python main.py initial-save Chart n →  对 Chart 项目以 single-line/hunk 模式生成初始 prompt
# ============================================================
if __name__ == '__main__':
    args = sys.argv[1:]
    if len(args) < 3:
        print("Usage: python main.py <mode> <project> <y/n> [bug_no]")
        print("  mode: initial-save | initial-chat | chatrepair")
        print("  project: " + " | ".join(PROJECTS))
        print("  y/n: y=single-function, n=single-line/hunk")
        print("  bug_no: (optional) specific bug number, e.g. 1 or 10. Omit to run all.")
        sys.exit(0)
    ins, p, all = args[0:3]
    bug_no = args[3] if len(args) > 3 else None
    if ins not in ["chatrepair", "initial-save", "initial-chat"]:
        print("Instruction only support \"chatrepair\"and\"initial-save\" and \"initial-chat\"")
    else:
        if p not in PROJECTS:
            print("Project only support these:\n")
            print(PROJECTS)
        else:
            if ins == "initial-save" and all == 'y':
                save_initial(p, True, bug_no)
            elif ins == "initial-save" and all == 'n':
                save_initial(p, False, bug_no)
            elif ins == "initial-chat" and all == 'y':
                chat_initial(p, True, bug_no)
            elif ins == "initial-chat" and all == 'n':
                chat_initial(p, False, bug_no)
            elif ins == "chatrepair" and all == 'y':
                go_chat_repair(p, True, bug_no)
            elif ins == "chatrepair" and all == 'n':
                go_chat_repair(p, False, bug_no)