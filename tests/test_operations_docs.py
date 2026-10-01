from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = (ROOT / "docs" / "operations.md").read_text()
README = (ROOT / "README.md").read_text()


def test_operations_guide_covers_startup_and_runtime_boundaries() -> None:
    required_sections = (
        "## 运行时拓扑",
        "## 准备服务器配置",
        "## 演示环境启动",
        "## 生产环境启动",
        "## 数据库迁移与健康检查",
        "## 创建真实账户",
        "## HTTPS、JWT 与密钥",
        "## 数据卷生命周期",
    )
    assert all(section in OPERATIONS for section in required_sections)
    assert "docs/operations.md" in README
    assert "唯一配置了主机 `ports` 端口映射的服务" in OPERATIONS
    assert "JWT_SIGNING_KEY" in OPERATIONS


def test_operations_guide_covers_coordinated_backup_restore() -> None:
    required_terms = (
        "## 协调一致的备份与恢复",
        "维护窗口",
        "pg_dump",
        "pg_restore",
        "materials.tar.gz",
        "SHA256SUMS",
        "check_backup_restore.py",
        "storage_key` 和 SHA-256",
    )
    assert all(term in OPERATIONS for term in required_terms)


def test_operations_guide_matches_semester_non_goals() -> None:
    required_limits = (
        "一个 API 写入实例",
        "本地具名数据卷",
        "OCR",
        "恶意软件扫描",
        "内容执行",
        "内联渲染",
        "多轮智能对话",
        "自主 Agent",
        "模型工具调用",
        "作业提交",
        "学情诊断",
        "教案/命题生成",
        "用户注册",
        "密码找回",
        "技能/功能开关",
        "MCP",
        "多智能体",
        "知识图谱",
        "每个账户只能属于一个班级",
    )
    assert all(limit in OPERATIONS for limit in required_limits)
    assert "不提供教学资料搜索、全文检索、向量检索、问答、RAG" not in OPERATIONS
