"""Replay the scripted verification scenarios against the published app.

Reads .runtime/install.json (written by tools/setup.py) or takes
DIFY_URL / DIFY_API_KEY from the environment. Nothing is written back to
Dify except normal chat messages, so it is safe to run against a live app.

Usage:
  python verification/verify.py            # full run
  python verification/verify.py best late  # selected scenarios
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_PATH = os.path.join(os.path.dirname(HERE), ".runtime", "install.json")

BEST = "地图上的新词"
GOOD = "钟声里的新词"
CONFESSION = "检查站后面"
LATE = "词进了档案，钟没有响"
FAILURE = "你没有标出的那一侧"


def load_runtime():
    if os.path.exists(RUNTIME_PATH):
        with open(RUNTIME_PATH, encoding="utf-8") as fh:
            runtime = json.load(fh)
    else:
        runtime = {}
    runtime.setdefault("dify_url", os.environ.get("DIFY_URL", "http://127.0.0.1:8080"))
    runtime.setdefault("api_key", os.environ.get("DIFY_API_KEY", ""))
    if not runtime["api_key"]:
        raise SystemExit("no api key: run tools/setup.py or set DIFY_API_KEY")
    return runtime


class Game:
    def __init__(self, base, key, user):
        self.base = base.rstrip("/")
        self.key = key
        self.user = user
        self.conversation = ""

    def say(self, query):
        payload = {
            "inputs": {},
            "query": query,
            "response_mode": "blocking",
            "conversation_id": self.conversation,
            "user": self.user,
        }
        req = urllib.request.Request(
            self.base + "/v1/chat-messages",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + self.key)
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")[:400]
            raise RuntimeError("chat failed: %s %s" % (err.code, detail))
        self.conversation = body.get("conversation_id", self.conversation)
        answer = body.get("answer", "")
        print("  你：%s" % query)
        print("  %s\n" % answer.replace("\n", "\n  ").rstrip())
        return answer


def new_game(runtime, scenario):
    return Game(runtime["dify_url"], runtime["api_key"],
                "verify-%s-%d" % (scenario, int(time.time())))


def expect(name, answer, *needles):
    missing = [n for n in needles if n not in answer]
    if missing:
        raise AssertionError("%s: missing %r" % (name, missing))
    print("[PASS] %s\n" % name)


def scenario_onboarding(runtime):
    print("== 新手引导：开场目标、状态、帮助、任务 ==")
    g = new_game(runtime, "onboarding")
    intro = g.say("开始调查")
    expect("intro", intro, "【任务】", "lo-ul-dom", "两份")
    status = g.say("状态")
    expect("status", status, "目标", "下一步")
    help_text = g.say("帮助")
    expect("help", help_text, "改名为 lo-ul-dom", "塞恩", "叶")
    mission = g.say("任务")
    expect("mission", mission, "胜利条件", "还缺")


def scenario_best(runtime):
    print("== 结局「%s」：三条线索后改名 ==" % BEST)
    g = new_game(runtime, "best")
    g.say("开始调查")
    g.say("档案员，铜牌上的 2.90 米是什么高度？")
    g.say("档案员，撤离名册里有多少人？")
    g.say("叶，旧路牌上的 lo 是什么意思？")
    answer = g.say("把片区改名为 lo-ul-dom")
    expect("best", answer, BEST, "4,207")


def scenario_good(runtime):
    print("== 结局「%s」：两条线索后改名 ==" % GOOD)
    g = new_game(runtime, "good")
    g.say("开始调查")
    g.say("档案员，铜牌上的 2.90 米是什么高度？")
    g.say("叶，旧路牌上的 lo 是什么意思？")
    answer = g.say("把片区改名为 lo-ul-dom")
    expect("good", answer, GOOD, "待补高程依据")


def scenario_confession(runtime):
    print("== 结局「%s」：数字核对 + 旧档分类 + 指控 ==" % CONFESSION)
    g = new_game(runtime, "confession")
    g.say("开始调查")
    roster = g.say("档案员，撤离名册总人数是多少？")
    expect("roster number", roster, "18,000")
    g.say("档案员，海关旧档的分类栏为什么不见了？")
    g.say("塞恩，旧档最后一页是你调阅的吗？")
    answer = g.say("指控塞恩")
    expect("confession", answer, CONFESSION)


def scenario_failure(runtime):
    print("== 结局「%s」：无证据连续指控 ==" % FAILURE)
    g = new_game(runtime, "failure")
    g.say("开始调查")
    g.say("指控塞恩")
    answer = g.say("我还是指控塞恩")
    expect("failure", answer, FAILURE)


def scenario_late(runtime):
    print("== 结局「%s」：潮水到 3.00 m ==" % LATE)
    g = new_game(runtime, "late")
    g.say("开始调查")
    for name in ("tor-ul-dom", "ka-ul", "ul-dom", "tor-ka-ul", "x-lan", "ul"):
        answer = g.say("把片区改名为 %s" % name)
    expect("late", answer, LATE, "3.00 m")


def scenario_recall(runtime):
    print("== 跨会话记忆：上一局的 PowerContext 记录 ==")
    first = new_game(runtime, "recall-a")
    first.say("开始调查")
    first.say("档案员，铜牌上的 2.90 米是什么高度？")
    second = new_game(runtime, "recall-b")
    second.say("开始调查")
    answer = second.say("上次我们查到哪了？")
    expect("recall", answer, "PowerContext", "回合")


SCENARIOS = {
    "onboarding": scenario_onboarding,
    "recall": scenario_recall,
    "best": scenario_best,
    "good": scenario_good,
    "confession": scenario_confession,
    "failure": scenario_failure,
    "late": scenario_late,
}


def main():
    runtime = load_runtime()
    print("dify: %s\napp: %s\n" % (runtime["dify_url"], runtime.get("app_id", "?")))
    selected = sys.argv[1:] or list(SCENARIOS)
    failures = []
    for name in selected:
        try:
            SCENARIOS[name](runtime)
        except AssertionError as err:
            failures.append(name)
            print("[FAIL] %s: %s\n" % (name, err))
    print("=" * 48)
    print("scenarios: %s" % ", ".join(selected))
    print("result: %s" % ("all passed" if not failures else "failed " + ", ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
