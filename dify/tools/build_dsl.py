"""Build the Dify DSL for《译者城市：第 13 号片区》.

Usage (from dify/):
    python tools/build_dsl.py

Output: app/district13-game.yml
"""

import json
import os

import yaml

import content as c

APP_NAME = "译者城市：第 13 号片区"
MODEL = {
    "provider": "langgenius/deepseek/deepseek",
    "name": "deepseek-flash",
    "mode": "chat",
}

INITIAL_STATE = {
    "turn": 0,
    "tide": 2.4,
    "trust": {"archivist": 0, "sean": 0, "ye": 0},
    "evidence": {
        "wall_height": False,
        "prefix_low": False,
        "deleted_category": False,
        "roster": False,
    },
    "flags": {
        "intro": False,
        "sean_shaken": False,
        "ye_contacted": False,
        "accusations": 0,
    },
    "ending": "",
    "renamed": "",
    "last_target": "none",
    "log": [],
}

DATASET_PLACEHOLDER = "REPLACE_WITH_DATASET_ID"
SCOPE_PLACEHOLDER = "REPLACE_WITH_SCOPE_ID"


def model(temperature):
    cfg = json.loads(json.dumps(MODEL))
    cfg["completion_params"] = {"temperature": temperature}
    return cfg


def node(node_id, node_type, title, x, y, **data):
    payload = {"type": node_type, "title": title, "desc": ""}
    payload.update(data)
    return {
        "id": node_id,
        "type": "custom",
        "position": {"x": x, "y": y},
        "data": payload,
    }


def edge(source, target, source_handle="source", source_type=None, target_type=None):
    return {
        "id": "e-%s-%s-%s" % (source, source_handle, target),
        "source": source,
        "sourceHandle": source_handle,
        "target": target,
        "targetHandle": "target",
        "data": {
            "sourceType": source_type or source,
            "targetType": target_type or target,
            "isInIteration": False,
        },
    }


def select(name, var):
    return {"variable": name, "value_selector": var}


def build_graph():
    nodes = []
    edges = []

    nodes.append(node("start", "start", "开始", 0, 300, variables=[]))

    nodes.append(node(
        "recall", "http-request", "PowerContext · 记忆召回", 280, 300,
        variables=[],
        method="post",
        url="{{#env.POWERCONTEXT_URL#}}/v1/memory/search",
        authorization={"type": "no-auth", "config": None},
        headers="Content-Type: application/json",
        params="",
        body={
            "type": "json",
            "data": [{
                "id": "b1", "key": "", "type": "text",
                "value": json.dumps({
                    "scope_id": "{{#env.POWERCONTEXT_SCOPE_ID#}}",
                    "query": "第13号片区 玩家 回合 线索 信任 潮时 结局",
                    "mode": "auto",
                }, ensure_ascii=False),
            }],
        },
        ssl_verify=True,
        timeout={"max_connect_timeout": 10, "max_read_timeout": 20, "max_write_timeout": 10},
        retry_config={"retry_enabled": True, "max_retries": 2, "retry_interval": 100},
    ))

    nodes.append(node(
        "intent", "llm", "意图解析 · 结构化", 560, 300,
        model=model(0.1),
        prompt_template=[
            {"role": "system", "text": c.INTENT_PROMPT},
            {"role": "user", "text": "{{#sys.query#}}"},
        ],
        context={"enabled": False, "variable_selector": []},
        vision={"enabled": False},
        variables=[],
    ))

    nodes.append(node(
        "judge", "code", "裁判 · 状态机与结局", 840, 300,
        code_language="python3",
        code=c.JUDGE_CODE,
        variables=[
            select("query", ["sys", "query"]),
            select("intent_text", ["intent", "text"]),
            select("state_json", ["conversation", "game_state"]),
            select("recall_body", ["recall", "body"]),
        ],
        outputs={
            "state_json": {"type": "string", "children": None},
            "route": {"type": "string", "children": None},
            "brief": {"type": "string", "children": None},
            "memory_note": {"type": "string", "children": None},
            "memory_text": {"type": "string", "children": None},
            "retrieval_query": {"type": "string", "children": None},
            "reply": {"type": "string", "children": None},
        },
    ))

    nodes.append(node(
        "set_state", "assigner", "写入本回合状态", 1120, 300,
        version="2",
        items=[{
            "variable_selector": ["conversation", "game_state"],
            "input_type": "variable",
            "operation": "over-write",
            "value": ["judge", "state_json"],
        }],
    ))

    cases = [
        ("archivist", "档案员"),
        ("sean", "塞恩"),
        ("ye", "叶"),
    ]
    nodes.append(node(
        "route", "if-else", "路由 · 谁在说话", 1400, 300,
        _targetBranches=[{"id": cid, "name": name} for cid, name in cases]
        + [{"id": "false", "name": "ELSE"}],
        logical_operator="and",
        cases=[{
            "case_id": cid,
            "logical_operator": "and",
            "conditions": [{
                "id": "cond-" + cid,
                "variable_selector": ["judge", "route"],
                "comparison_operator": "is",
                "value": cid,
            }],
        } for cid, _ in cases],
    ))

    nodes.append(node(
        "archive_kr", "knowledge-retrieval", "检索 · 档案馆", 1680, 160,
        query_variable_selector=["judge", "retrieval_query"],
        query_attachment_selector=[],
        dataset_ids=[DATASET_PLACEHOLDER],
        retrieval_mode="multiple",
        multiple_retrieval_config={
            "top_k": 4,
            "score_threshold": None,
            "reranking_enable": False,
            "reranking_mode": "reranking_model",
        },
        metadata_filtering_mode="disabled",
    ))

    nodes.append(node(
        "archivist_llm", "llm", "档案员 · 纪", 1960, 160,
        model=model(0.3),
        prompt_template=[
            {"role": "system", "text": c.ARCHIVIST_PROMPT},
            {"role": "user", "text": "{{#sys.query#}}"},
        ],
        context={"enabled": True, "variable_selector": ["archive_kr", "result"]},
        vision={"enabled": False},
        variables=[],
    ))

    nodes.append(node(
        "sean_llm", "llm", "复核员 · 塞恩", 1960, 320,
        model=model(0.7),
        prompt_template=[
            {"role": "system", "text": c.SEAN_PROMPT},
            {"role": "user", "text": "{{#sys.query#}}"},
        ],
        context={"enabled": False, "variable_selector": []},
        vision={"enabled": False},
        variables=[],
    ))

    nodes.append(node(
        "ye_llm", "llm", "测绘员 · 叶（手机）", 1960, 480,
        model=model(0.6),
        prompt_template=[
            {"role": "system", "text": c.YE_PROMPT},
            {"role": "user", "text": "{{#sys.query#}}"},
        ],
        context={"enabled": False, "variable_selector": []},
        vision={"enabled": False},
        variables=[],
    ))

    nodes.append(node(
        "merge", "variable-aggregator", "汇合 · 谁的回答", 2240, 300,
        output_type="string",
        variables=[
            ["archivist_llm", "text"],
            ["sean_llm", "text"],
            ["ye_llm", "text"],
            ["judge", "reply"],
        ],
    ))

    nodes.append(node(
        "finalize", "code", "整理 · 去思考链与状态栏", 2520, 300,
        code_language="python3",
        code=c.FINALIZE_CODE,
        variables=[
            select("text", ["merge", "output"]),
            select("state_json", ["judge", "state_json"]),
        ],
        outputs={"text": {"type": "string", "children": None}},
    ))

    nodes.append(node(
        "remember", "http-request", "PowerContext · 记忆写入", 2800, 300,
        variables=[],
        method="post",
        url="{{#env.POWERCONTEXT_URL#}}/v1/memory/remember",
        authorization={"type": "no-auth", "config": None},
        headers="Content-Type: application/json",
        params="",
        body={
            "type": "json",
            "data": [{
                "id": "b1", "key": "", "type": "text",
                "value": json.dumps({
                    "scope_id": "{{#env.POWERCONTEXT_SCOPE_ID#}}",
                    "kind": "district13_turn",
                    "text": "{{#judge.memory_text#}}",
                    "reason": "player turn",
                }, ensure_ascii=False),
            }],
        },
        ssl_verify=True,
        timeout={"max_connect_timeout": 10, "max_read_timeout": 20, "max_write_timeout": 10},
        retry_config={"retry_enabled": True, "max_retries": 2, "retry_interval": 100},
    ))

    nodes.append(node(
        "answer", "answer", "回答", 3080, 300,
        answer="{{#finalize.text#}}",
        variables=[],
    ))

    edges.append(edge("start", "recall"))
    edges.append(edge("recall", "intent"))
    edges.append(edge("intent", "judge"))
    edges.append(edge("judge", "set_state"))
    edges.append(edge("set_state", "route"))
    edges.append(edge("route", "archive_kr", "archivist"))
    edges.append(edge("archive_kr", "archivist_llm"))
    edges.append(edge("route", "sean_llm", "sean"))
    edges.append(edge("route", "ye_llm", "ye"))
    edges.append(edge("archivist_llm", "merge"))
    edges.append(edge("sean_llm", "merge"))
    edges.append(edge("ye_llm", "merge"))
    edges.append(edge("route", "merge", "false"))
    edges.append(edge("merge", "finalize"))
    edges.append(edge("finalize", "remember"))
    edges.append(edge("remember", "answer"))

    return {"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 0.7}}


def build_dsl():
    graph = build_graph()
    return {
        "app": {
            "description": "一场关于名字、分类与潮水的多智能体审讯游戏。",
            "icon": "📜",
            "icon_background": "#FFEAD5",
            "icon_type": "emoji",
            "mode": "advanced-chat",
            "name": APP_NAME,
            "use_icon_as_answer_icon": False,
        },
        "dependencies": [{
            "current_identifier": None,
            "type": "marketplace",
            "value": {
                "marketplace_plugin_unique_identifier": (
                    "langgenius/deepseek:0.0.26@"
                    "bdf47cb41e9062bba00d26625d2a795c1874011d8ce64bff738c44b5a31787ea"
                ),
                "version": None,
            },
        }],
        "kind": "app",
        "site": {
            "chat_color_theme": None,
            "chat_color_theme_inverted": False,
            "copyright": None,
            "custom_disclaimer": "",
            "default_language": "zh-Hans",
            "description": "潮水三点到。第 13 号片区在名册上没有名字。",
            "icon": "📜",
            "icon_background": "#FFEAD5",
            "icon_type": "emoji",
            "input_placeholder": "对纪、塞恩或叶说点什么……",
            "privacy_policy": None,
            "show_workflow_steps": True,
            "title": APP_NAME,
            "use_icon_as_answer_icon": False,
        },
        "version": "0.7.0",
        "workflow": {
            "conversation_variables": [{
                "id": "cv-game-state",
                "name": "game_state",
                "value_type": "string",
                "value": json.dumps(INITIAL_STATE, ensure_ascii=False),
                "description": "本局潮时、信任、线索与结局",
            }],
            "environment_variables": [
                {
                    "id": "ev-pc-url",
                    "name": "POWERCONTEXT_URL",
                    "value": "http://host.docker.internal:8100",
                    "value_type": "string",
                    "description": "PowerContext 服务地址",
                },
                {
                    "id": "ev-pc-scope",
                    "name": "POWERCONTEXT_SCOPE_ID",
                    "value": SCOPE_PLACEHOLDER,
                    "value_type": "string",
                    "description": "本次演示使用的 PowerContext scope",
                },
            ],
            "features": {
                "file_upload": {"enabled": False},
                "opening_statement": c.OPENING_STATEMENT,
                "retriever_resource": {"enabled": True},
                "sensitive_word_avoidance": {"enabled": False},
                "speech_to_text": {"enabled": False},
                "suggested_questions": c.SUGGESTED_QUESTIONS,
                "suggested_questions_after_answer": {"enabled": False},
                "text_to_speech": {"enabled": False, "language": "", "voice": ""},
            },
            "graph": graph,
            "rag_pipeline_variables": [],
        },
    }


class BlockDumper(yaml.SafeDumper):
    pass


def _str_representer(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


BlockDumper.add_representer(str, _str_representer)


def main():
    dsl = build_dsl()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "district13-game.yml")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        yaml.dump(dsl, fh, Dumper=BlockDumper, allow_unicode=True, sort_keys=False,
                  default_flow_style=False, width=1000)
    print("wrote", os.path.normpath(out))


if __name__ == "__main__":
    main()
