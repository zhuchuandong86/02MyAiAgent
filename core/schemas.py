# core/schemas.py
from pydantic import BaseModel, Field
from typing import Literal

class Text2SQLOutput(BaseModel):
    """无线问数 (Text2SQL) 标准输出结构"""
    thinking: str = Field(description="简短推演过程，例如需要查哪张表、是否需要图表等内部思考逻辑")
    sql: str = Field(description="唯一可执行的完整 DuckDB/SQL 语句")
    chart_type: Literal["line", "bar", "multi_bar", "pie", "dual_axis", "none"] = Field(description="推荐的图表类型")
    chart_title: str = Field(description="极简图表标题，15字以内")
    comment: str = Field(description="数据来源表名与时间范围跨度说明")

class CodeReflection(BaseModel):
    """代码报错反思标准输出结构 (用于 Agent 自我纠错)"""
    root_cause: str = Field(description="一句话精准说清楚为什么会报错", max_length=50)
    fix_strategy: str = Field(description="具体的修改对策和代码调整方向", max_length=100)
    avoid: str = Field(description="下次写代码时必须避免的错误做法", max_length=50)

# 💡 未来如果有文档指标提取 (如 COMPARE_EXTRACT)，也可以全部收拢定义在这里