"""The public demo: sandboxes per visitor, the opening scenario, quotas, replay and live triage."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from evals import export_demo
from gmail_operations_agent.api.app import create_app
from gmail_operations_agent.api.routes import DEMO_COOKIE
from gmail_operations_agent.config import Settings
from gmail_operations_agent.demo import data as demo_data
from gmail_operations_agent.demo.llm import DemoLLM
from gmail_operations_agent.demo.service import SIMULATED_NOTION_ERROR, DemoService
from gmail_operations_agent.domain import Usage
from gmail_operations_agent.errors import BlockedError, PermanentError
from gmail_operations_agent.runtime import Runtime, build_demo_runtime
from gmail_operations_agent.store import Store
from tests.fakes import FakeClock, FakeLLM, make_email

PRESET = {
    "sender_name": "Priya Shah",
    "sender_address": "priya@shahdesigns.co",
}


def test_demo_data_matches_the_eval_set() -> None:
    """data.json is generated; regenerate with `python -m evals.export_demo`."""
    assert demo_data.DATA_FILE.read_text("utf-8") == export_demo.render()


def test_every_preset_replays_a_recording() -> None:
    data = demo_data.load()
    for preset in data.presets:
        email = demo_data.compose_email(
            id="x",
            sender_name=preset.sender_name,
            sender_address=preset.sender_address,
            subject=preset.subject,
            body=preset.body + "\r\n",  # browsers send CRLF; whitespace does not matter
        )
        assert demo_data.fingerprint(email) in data.recordings, preset.id


class Demo:
    def __init__(
        self, store: Store, clock: FakeClock, tmp_path: Path, live: FakeLLM | None = None
    ) -> None:
        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            openai_api_key=None,
            demo_secret="test-secret",  # type: ignore[arg-type]
            demo_replay_speed=0,
            demo_daily_quota=2,
            demo_sandboxes_per_visitor=3,
            demo_monthly_budget_usd=0.001,
            web_dist_dir=tmp_path / "no-ui",
        )
        self.runtime: Runtime = build_demo_runtime(settings, store=store, live=live, clock=clock)
        assert self.runtime.demo is not None
        self.service: DemoService = self.runtime.demo
        self.app = create_app(self.runtime, run_worker=False)

    async def settle(self) -> None:
        """Process everything due, including the scenario's delayed approvals."""
        for _ in range(4):
            await self.runtime.worker.drain()
            await asyncio.sleep(0)

    def client(self, address: str = "203.0.113.7") -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=self.app, client=(address, 4321))
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    @contextlib.asynccontextmanager
    async def visit(self, address: str = "203.0.113.7") -> AsyncIterator[httpx.AsyncClient]:
        """A browser tab: the page load (a GET) opens the sandbox before anything else."""
        async with self.client(address) as http:
            assert (await http.get("/api/status")).status_code == 200
            yield http


@pytest.fixture
def demo(store: Store, clock: FakeClock, tmp_path: Path) -> Demo:
    return Demo(store, clock, tmp_path)


@pytest.fixture
async def visitor(demo: Demo) -> AsyncIterator[httpx.AsyncClient]:
    async with demo.visit() as http:
        yield http


async def states(http: httpx.AsyncClient) -> dict[str, str]:
    items = (await http.get("/api/messages")).json()["items"]
    return {item["id"].split("-", 1)[1]: item["state"] for item in items}


async def test_first_visit_seeds_a_sandbox_that_shows_every_state(demo: Demo) -> None:
    async with demo.client() as visitor:
        await _first_visit(demo, visitor)


async def _first_visit(demo: Demo, visitor: httpx.AsyncClient) -> None:
    status = await visitor.get("/api/status")
    assert status.json()["source"] == "demo"
    assert status.json()["connections"]["notion"] == {"enabled": True, "sandbox": True}
    assert DEMO_COOKIE in visitor.cookies
    assert "httponly" in status.headers["set-cookie"].lower()

    seeded = await states(visitor)
    assert len(seeded) == len(demo_data.SEED)
    assert set(seeded.values()) == {"new"}
    newest_first = [seed.case for seed in demo_data.SEED]
    assert list(seeded) == newest_first

    await demo.settle()
    final = await states(visitor)
    assert final["lead-en-dental"] == "awaiting_approval"
    assert final["phishing-en-bank-details"] == "done"  # guardrails left nothing to approve
    assert final["invoice-ru-schet"] == "done"  # approved by the scenario
    assert final["lead-de-agency"] == "dead"  # the scenario's simulated Notion error

    page = (await visitor.get("/api/messages")).json()
    dead = next(item for item in page["items"] if item["state"] == "dead")
    detail = (await visitor.get(f"/api/messages/{dead['id']}")).json()
    assert SIMULATED_NOTION_ERROR in detail["error"]
    assert {"type": "approved", "by": "demo scenario"} in [
        {"type": e["type"], **e["data"]} for e in detail["events"]
    ]
    done_actions = {a["kind"]: a for a in detail["actions"] if a["status"] == "done"}
    assert set(done_actions) == {"sheets_row", "gmail_draft"}
    assert done_actions["gmail_draft"]["preview"]["to"] == "Jonas Weber <jonas@weber-immobilien.de>"
    assert detail["usage"]["recorded"] is True

    # Retry fixes it, and the actions that already ran are not repeated.
    assert (await visitor.post(f"/api/messages/{dead['id']}/retry")).status_code == 200
    await demo.settle()
    detail = (await visitor.get(f"/api/messages/{dead['id']}")).json()
    assert detail["state"] == "done"
    started = [e["data"]["kind"] for e in detail["events"] if e["type"] == "action_started"]
    assert started.count("sheets_row") == 1


async def test_visitors_cannot_see_each_other(demo: Demo) -> None:
    async with demo.visit("198.51.100.1") as alice, demo.visit("198.51.100.2") as bob:
        alice_ids = {item["id"] for item in (await alice.get("/api/messages")).json()["items"]}
        bob_ids = {item["id"] for item in (await bob.get("/api/messages")).json()["items"]}
        assert alice_ids.isdisjoint(bob_ids)
        some = next(iter(alice_ids))
        assert (await bob.get(f"/api/messages/{some}")).status_code == 404
        assert (await bob.post(f"/api/messages/{some}/reject")).status_code == 404
        assert all(not mid.startswith("sb") or len(mid) > 16 for mid in alice_ids)
        # The cookie token never appears in ids.
        assert alice.cookies[DEMO_COOKIE] not in "".join(alice_ids)


async def test_presets_replay_and_custom_mail_needs_the_live_model(
    demo: Demo, visitor: httpx.AsyncClient
) -> None:
    info = (await visitor.get("/api/demo")).json()
    assert info["live"] is False
    assert info["quota"] == {**info["quota"], "limit": 2, "used": 0, "left": 2}
    preset = info["presets"][0]

    sent = await visitor.post("/api/demo/emails", json={k: preset[k] for k in TEST_FIELDS})
    assert sent.status_code == 202
    assert sent.json()["recorded"] is True
    assert sent.json()["quota"]["left"] == 1
    assert sent.json()["message"]["state"] == "new"

    custom = {**PRESET, "subject": "Hello", "body": "Can we talk about a bot?"}
    refused = await visitor.post("/api/demo/emails", json=custom)
    assert refused.status_code == 503
    assert "presets still work" in refused.json()["detail"]

    await demo.settle()
    detail = (await visitor.get(f"/api/messages/{sent.json()['message']['id']}")).json()
    assert detail["state"] == "awaiting_approval"
    assert detail["category"] == "lead"


TEST_FIELDS = ("sender_name", "sender_address", "subject", "body")


async def test_daily_quota_is_per_address_not_per_cookie(demo: Demo) -> None:
    preset = demo_data.load().presets[0]
    mail = {field: getattr(preset, field) for field in TEST_FIELDS}
    async with demo.visit("192.0.2.9") as first, demo.visit("192.0.2.9") as second:
        assert (await first.post("/api/demo/emails", json=mail)).status_code == 202
        assert (await second.post("/api/demo/emails", json=mail)).status_code == 202
        over = await first.post("/api/demo/emails", json=mail)
        assert over.status_code == 429
        assert (await second.get("/api/demo")).json()["quota"]["left"] == 0


async def test_sandbox_creation_is_limited_per_address(demo: Demo) -> None:
    for _ in range(3):
        async with demo.client("192.0.2.50") as fresh:
            assert (await fresh.get("/api/status")).status_code == 200
    async with demo.client("192.0.2.50") as one_too_many:
        assert (await one_too_many.get("/api/status")).status_code == 429


async def test_test_email_input_limits(visitor: httpx.AsyncClient) -> None:
    good = {**PRESET, "subject": "Hi", "body": "Hello"}
    for bad in (
        {**good, "sender_address": "not-an-address"},
        {**good, "subject": ""},
        {**good, "body": "x" * 5_001},
        {**good, "sender_name": "n" * 101},
    ):
        assert (await visitor.post("/api/demo/emails", json=bad)).status_code == 422


async def test_live_model_handles_custom_mail_within_budget(
    store: Store, clock: FakeClock, tmp_path: Path
) -> None:
    live = FakeLLM()
    demo = Demo(store, clock, tmp_path, live=live)
    async with demo.visit() as http:
        custom = {**PRESET, "subject": "Hello", "body": "Can we talk about a bot?"}
        sent = await http.post("/api/demo/emails", json=custom)
        assert sent.status_code == 202
        assert sent.json()["recorded"] is False
        await demo.settle()
        detail = (await http.get(f"/api/messages/{sent.json()['message']['id']}")).json()
        assert detail["state"] == "awaiting_approval"
        assert detail["usage"]["recorded"] is False
        assert live.calls == [sent.json()["message"]["id"]]  # the seed inbox was all replays


async def test_monthly_budget_switches_off_the_live_model(
    store: Store, clock: FakeClock, tmp_path: Path
) -> None:
    live = FakeLLM()
    demo = Demo(store, clock, tmp_path, live=live)
    outcome = await live.triage(make_email("spent"))
    for _ in range(5):  # 5 x $0.0002 = the test's $0.001 monthly cap
        store.add_llm_call(None, outcome.usage.model_copy(update={"provider": "openai"}))
    async with demo.visit() as http:
        assert (await http.get("/api/demo")).json()["live"] is False
        custom = {**PRESET, "subject": "Hello", "body": "Can we talk about a bot?"}
        assert (await http.post("/api/demo/emails", json=custom)).status_code == 503


async def test_live_failures_stay_with_one_message() -> None:
    blocked = FakeLLM(BlockedError("openai", "insufficient_quota"))
    llm = DemoLLM({}, blocked, has_budget=lambda: True, replay_speed=0)
    with pytest.raises(PermanentError, match="insufficient_quota"):
        await llm.triage(make_email())


async def test_idle_sandboxes_are_removed_but_live_spend_is_kept(
    store: Store, clock: FakeClock, tmp_path: Path
) -> None:
    demo = Demo(store, clock, tmp_path)
    async with demo.client() as http:
        await http.get("/api/status")
        await demo.settle()
        owner = demo.service.owner_for(http.cookies[DEMO_COOKIE])
    month = clock.now - timedelta(days=1)
    assert store.llm_spend_since(month, provider="replay") > 0
    live = Usage(
        provider="openai",
        model="gpt-6-luna",
        prompt_version="v",
        input_tokens=1,
        output_tokens=1,
        latency_ms=1,
        cost_usd=0.0002,
    )
    store.add_llm_call(f"{owner}-lead-en-dental", live)  # live spend must keep counting

    clock.advance(23 * 3600)
    assert demo.service.cleanup() == 0
    clock.advance(2 * 3600)
    assert demo.service.cleanup() == 1
    assert store.list_messages(owner, limit=100) == []
    assert store.events_after(0, owner=owner) == []
    assert store.llm_spend_since(month, provider="replay") == 0
    assert store.llm_spend_since(month) == pytest.approx(0.0002)


async def test_reset_starts_a_fresh_sandbox(demo: Demo, visitor: httpx.AsyncClient) -> None:
    first = {item["id"] for item in (await visitor.get("/api/messages")).json()["items"]}
    assert (await visitor.post("/api/demo/reset")).status_code == 200
    second = {item["id"] for item in (await visitor.get("/api/messages")).json()["items"]}
    assert len(second) == len(first)
    assert first.isdisjoint(second)
    assert demo.runtime.store.get_message(next(iter(first))) is None


async def test_changes_without_a_sandbox_are_refused(demo: Demo) -> None:
    async with demo.client() as stranger:
        response = await stranger.post("/api/demo/emails", json={**PRESET, "subject": "Hi"})
        assert response.status_code == 410
        assert DEMO_COOKIE not in stranger.cookies
    assert demo.runtime.store.stale_sandboxes(keep=0) == []  # nothing was created
