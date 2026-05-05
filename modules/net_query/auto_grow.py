# auto_grow.py
import pandas as pd
import yaml
import os

# 配置路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "query_logs.csv")
YAML_PATH = os.path.join(BASE_DIR, "schema.yaml")

def auto_grow():
    if not os.path.exists(LOG_PATH):
        print("❌ 暂无日志文件。")
        return

    # 1. 读取日志并筛选点赞记录
    try:
        df = pd.read_csv(LOG_PATH, encoding='utf-8-sig')
        # 筛选被用户认可且成功的查询
        good_samples = df[df['状态'] == 'FEEDBACK_GOOD'].copy()
    except Exception as e:
        print(f"❌ 读取日志失败: {e}")
        return

    if good_samples.empty:
        print("💡 目前还没有用户点赞的记录，继续加油！")
        return

    # 2. 获取现有知识库，防止重复
    try:
        with open(YAML_PATH, 'r', encoding='utf-8') as f:
            original_text = f.read()
            config = yaml.safe_load(original_text) or {}
            existing_questions = {item.get('question', '') for item in config.get('golden_sqls', [])}
    except Exception as e:
        print(f"❌ 读取YAML失败: {e}")
        return

    # 3. 构造新语料文本
    new_blocks = []
    for _, row in good_samples.iterrows():
        q = str(row['用户问题']).strip()
        s = str(row['执行SQL']).strip()
        
        if q not in existing_questions:
            # 简单清理SQL中的换行
            s_clean = s.replace('\n', ' ').replace('  ', ' ')
            new_blocks.append(f"  - question: \"{q}\"\n    sql: '{s_clean}'")
            existing_questions.add(q)

    if not new_blocks:
        print("✨ 所有点赞的案例已经在知识库中了。")
        return

    # 4. 无损追加到 golden_sqls 节点下
    lines = original_text.split('\n')
    insert_idx = -1
    for i, line in enumerate(lines):
        if line.strip().startswith("golden_sqls:"):
            insert_idx = i + 1
            break
            
    if insert_idx != -1:
        updated_content = '\n'.join(lines[:insert_idx] + new_blocks + lines[insert_idx:])
        with open(YAML_PATH, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        print(f"✅ 自动进化成功！新增 {len(new_blocks)} 条用户认可的案例到知识库。")
    else:
        print("❌ 找不到 golden_sqls 节点，自动进化失败。")

if __name__ == "__main__":
    auto_grow()