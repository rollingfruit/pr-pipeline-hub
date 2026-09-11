"""Trusted suite selection. PR contents cannot change the acceptance policy."""

CORE = ("E01", "E02", "E03")
REQUIRED_CASES = {"E01": {"create"}, "E02": {"private"}, "E03": {"group"},
                  "E04": {"cancel"}, "E05": {"tool-failure", "terminal-failure"},
                  "E06": {"event-replay"}, "DR": {"rule", "model"},
                  "DR-contract": {"contract"}}
CATALOG = (
    {"id": "E01", "name": "创建真实机器人", "kind": "browser", "implemented": True},
    {"id": "E02", "name": "私聊执行与追问", "kind": "browser", "implemented": True},
    {"id": "E03", "name": "群聊 @ 与最终交付", "kind": "browser", "implemented": True},
    {"id": "DR", "name": "规则与模型直答", "kind": "browser", "implemented": True},
    {"id": "DR-contract", "name": "直答幂等与契约", "kind": "integration", "implemented": True},
    {"id": "E04", "name": "停止与取消", "kind": "browser", "implemented": True},
    {"id": "E05", "name": "失败可见性", "kind": "resilience", "implemented": True},
    {"id": "E06", "name": "重复事件与幂等", "kind": "hybrid", "implemented": True},
)


def select_suites(repo, number, requested=None):
    if requested is None:
        requested = list(CORE)
    if not isinstance(requested, list) or not requested or any(not isinstance(x, str) for x in requested):
        raise ValueError("suites must be a non-empty array of suite IDs")
    known = {s["id"] for s in CATALOG if s["implemented"]}
    if set(requested) - known:
        raise ValueError("Unknown or unimplemented suite")
    chosen = set(requested)
    full = set(CORE).issubset(chosen)
    reasons = {s: "用户选择" for s in chosen}
    return [{**s, "reason": reasons[s["id"]]} for s in CATALOG if s["id"] in chosen], full


def stages(suites):
    items = [("resolve", "解析 PR"), ("agent", "本机 Codex 检视"), ("preflight", "环境与构建输入"),
             ("snapshot", "固定源码与合并预演"), ("build", "构建 CCE 镜像"),
             ("baseline", "基线环境与核心回归"), ("deploy", "候选环境就绪")]
    items += [(s["id"], s["name"]) for s in suites]
    return items + [("report", "归档与版本复核"), ("github", "GitHub 检查回写")]


def validate_result(payload, suite):
    """Never infer success from exit code alone (zero/skipped tests are not passes)."""
    tests = payload.get("tests", [])
    selected = [t for t in tests if t.get("suite") == suite]
    if {t.get("id") for t in selected} != REQUIRED_CASES.get(suite, set()) or len(selected) != len(REQUIRED_CASES.get(suite, set())):
        raise ValueError(f"{suite}: required case IDs missing or duplicated")
    if not selected or any(t.get("status") != "passed" for t in selected):
        raise ValueError(f"{suite}: required tests missing, failed or skipped")
    for case in selected:
        if not case.get("evidence"):
            raise ValueError(f"{suite}: missing evidence")
    return selected
