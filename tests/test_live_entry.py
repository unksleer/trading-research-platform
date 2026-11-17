"""
Live has one way in, and it is not an environment variable.

Until 2026-11-17 a stock bot went live when ALPACA_PAPER was false. That is a
variable every bot reads from .env and that a `pm2 restart --update-env`
copies in from the calling shell, so real-money trading was one stray line
away from all twelve registered bots. stock_bot.py now refuses to start with
it. live_bot.py is the way in: ticker, trade size and the words --real-money
on its command line, nothing taken from the environment, a hard cap on trade
size, and only the calm six.

Nothing here reaches a broker. Live is not authorised and has never run.
"""
import os
import sys
import types

import pytest

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIR)

import live_bot  # noqa: E402
from stock_bot_harness import load_stock_bot  # noqa: E402
from utils import env_loader, execution_mode  # noqa: E402

GOOD = ["--ticker", "SPY", "--usd", "16", "--real-money"]


def found(argv, env=None):
    return live_bot.problems(live_bot.parse(argv), env or {})


# ── stock_bot.py cannot be made live from outside ───────────────────────────

@pytest.mark.parametrize("value", ["False", "false", "0", "no", " FALSE "])
def test_alpaca_paper_false_no_longer_starts_a_live_bot(monkeypatch, value):
    with pytest.raises(SystemExit, match="no longer trades live on an environment variable"):
        load_stock_bot(monkeypatch, env={"ALPACA_PAPER": value})


@pytest.mark.parametrize("value", ["True", "true", "1", "", "yes", "f", "off", "garbage"])
def test_a_stock_bot_process_only_ever_simulates(monkeypatch, value):
    """Whatever the variable says, a process whose script is stock_bot.py
    either refuses to start or sends no orders."""
    bot = load_stock_bot(monkeypatch, env={"ALPACA_PAPER": value})
    assert bot.MODE == "PAPER" and not bot.SENDS_ORDERS and not bot.LIVE
    assert bot.STATE_PATH.endswith("state_stock_zztest_paper.json")


def test_live_keys_in_the_environment_do_not_make_a_bot_live(monkeypatch):
    bot = load_stock_bot(monkeypatch, test_keys=False, env={
        "ALPACA_API_KEY": "paper", "ALPACA_SECRET_KEY": "paper-secret",
        "ALPACA_LIVE_API_KEY": "live", "ALPACA_LIVE_SECRET_KEY": "live-secret"})
    assert not bot.SENDS_ORDERS and bot.API_KEY == "paper"


def test_live_mode_on_the_paper_setting_refuses(monkeypatch):
    with pytest.raises(SystemExit, match="paper endpoint"):
        load_stock_bot(monkeypatch, live=True, env={"ALPACA_PAPER": "True"})


@pytest.mark.parametrize("usd, starts", [("16", True), ("166", True), ("166.01", False),
                                         ("1000", False), ("0", False), ("-5", False)])
def test_the_cap_is_checked_again_inside_stock_bot(monkeypatch, usd, starts):
    """live_bot.py checks it first. This is the second lock on the same door:
    anything else that loads stock_bot in live mode meets it too."""
    if starts:
        assert load_stock_bot(monkeypatch, live=True,
                              env={"TRADE_AMOUNT_USD": usd}).TRADE_AMOUNT == float(usd)
    else:
        with pytest.raises(SystemExit, match="live trade size"):
            load_stock_bot(monkeypatch, live=True, env={"TRADE_AMOUNT_USD": usd})


def test_the_cap_and_the_tickers_are_the_plan_on_record():
    # $1,000 in the account across six stocks, rounded down: stage 4's trade.
    assert execution_mode.LIVE_MAX_TRADE_USD == 1000 // 6 == 166
    assert set(execution_mode.LIVE_TICKERS) == {"XLP", "JNJ", "PG", "SPY", "XLU", "WMT"}


# ── what live_bot.py insists on ─────────────────────────────────────────────

def test_everything_spelled_out_is_accepted():
    assert found(GOOD) == []
    assert found(GOOD, {"name": "spy-live"}) == []
    for stage_trade in ("16", "41", "83", "166"):            # the four agreed sizes
        assert found(["--ticker", "xlu", "--usd", stage_trade, "--real-money"]) == []


def test_nothing_has_a_default():
    assert len(found([])) == 3
    (problem,) = found(["--usd", "100", "--real-money"])
    assert "--ticker is missing" in problem
    (problem,) = found(["--ticker", "SPY", "--real-money"])
    assert "--usd is missing" in problem
    (problem,) = found(["--ticker", "SPY", "--usd", "16"])
    assert "--real-money is missing" in problem


def test_the_environment_supplies_nothing(monkeypatch):
    """The variables that tell every other bot what it is are not read."""
    env = {"STOCK_TICKER": "SPY", "TRADE_AMOUNT_USD": "100", "ALPACA_PAPER": "False"}
    assert len(found([], env)) == 3


@pytest.mark.parametrize("usd", ["0", "-100", "abc", "nan", ""])
def test_a_trade_size_that_is_not_a_positive_number_is_refused(usd):
    (problem,) = found(["--ticker", "SPY", "--usd", usd, "--real-money"])
    assert "not a positive number" in problem


@pytest.mark.parametrize("usd", ["166.01", "250", "1000", "1e9", "inf"])
def test_a_trade_size_above_the_cap_is_refused(usd):
    (problem,) = found(["--ticker", "SPY", "--usd", usd, "--real-money"])
    assert "above the most a live bot may put into one trade, $166" in problem


@pytest.mark.parametrize("ticker", ["TSLA", "NVDA", "QQQ", "BTC-USD", "ZZTEST"])
def test_only_the_calm_six_may_be_traded_live(ticker):
    (problem,) = found(["--ticker", ticker, "--usd", "16", "--real-money"])
    assert "not one of the stocks a live bot may trade" in problem


def test_the_pm2_name_must_say_the_ticker():
    (problem,) = found(GOOD, {"name": "wmt-live"})
    assert "not named for SPY" in problem
    (problem,) = found(GOOD, {"name": "spy-bot"})          # a simulated bot's name
    assert "expected 'spy-live'" in problem
    (problem,) = found(GOOD, {"name": "spy-brokerpaper"})  # a rehearsal bot's name
    assert "expected 'spy-live'" in problem


# ── what it does once it agrees to start ────────────────────────────────────

@pytest.fixture
def started(monkeypatch):
    """live_bot.main with stock_bot replaced by something that records what
    it would have been loaded with. No real stock_bot is imported."""
    seen = {}

    def fake_main():
        seen.update(ticker=os.environ.get("STOCK_TICKER"),
                    usd=os.environ.get("TRADE_AMOUNT_USD"),
                    paper=os.environ.get("ALPACA_PAPER"),
                    mode=execution_mode.REQUESTED)

    monkeypatch.setitem(sys.modules, "stock_bot", types.SimpleNamespace(main=fake_main))
    monkeypatch.setattr(execution_mode, "REQUESTED", None)
    for key in ("STOCK_TICKER", "TRADE_AMOUNT_USD", "ALPACA_PAPER", "name"):
        monkeypatch.delenv(key, raising=False)
    return seen


def test_it_starts_stock_bot_in_live_mode_with_what_the_command_line_said(started):
    live_bot.main(["--ticker", "xlp", "--usd", "83", "--real-money"])
    assert started == {"ticker": "XLP", "usd": "83.0", "paper": "False",
                       "mode": execution_mode.LIVE}


def test_the_command_line_wins_over_a_leaked_environment(started, monkeypatch, capsys):
    """A restart with --update-env from a shell that had .env loaded. The
    ticker and the size the bot was started with must survive it."""
    monkeypatch.setenv("STOCK_TICKER", "TSLA")
    monkeypatch.setenv("TRADE_AMOUNT_USD", "5000")
    monkeypatch.setenv("ALPACA_PAPER", "True")
    live_bot.main(GOOD)
    assert started == {"ticker": "SPY", "usd": "16.0", "paper": "False",
                       "mode": execution_mode.LIVE}
    assert "ignoring STOCK_TICKER='TSLA'" in capsys.readouterr().err


def test_dotenv_cannot_change_what_a_live_bot_trades(started, monkeypatch, tmp_path):
    """stock_bot loads .env after live_bot has set these. The real loader,
    against a .env that says something else about every one of them."""
    live_bot.main(GOOD)
    for key in ("STOCK_RSI_OVERSOLD", "SPY_TRADE_AMOUNT_USD"):
        monkeypatch.delenv(key, raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text("STOCK_TICKER=TSLA\nTRADE_AMOUNT_USD=5000\nALPACA_PAPER=True\n"
                      "SPY_TRADE_AMOUNT_USD=5000\nSTOCK_RSI_OVERSOLD=35\n")
    env_loader.load(env_path=str(dotenv))
    assert os.environ["STOCK_TICKER"] == "SPY"
    assert os.environ["TRADE_AMOUNT_USD"] == "16.0"
    assert os.environ["ALPACA_PAPER"] == "False"
    assert "SPY_TRADE_AMOUNT_USD" not in os.environ     # the per-ticker variant is stripped
    assert os.environ["STOCK_RSI_OVERSOLD"] == "35"     # tuning is still .env's


def test_a_refusal_starts_nothing(started, capsys):
    with pytest.raises(SystemExit) as stopped:
        live_bot.main(["--ticker", "SPY", "--usd", "16"])
    assert stopped.value.code == 1
    assert started == {} and execution_mode.REQUESTED is None
    assert "ALPACA_PAPER" not in os.environ
    assert "REFUSING TO START. Nothing was sent." in capsys.readouterr().err


def test_a_live_bot_without_live_keys_does_not_run(monkeypatch, caplog):
    """The paper keys are in .env for every simulated bot. A live bot must not
    fall back to them."""
    import logging
    monkeypatch.delenv("ALPACA_LIVE_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_LIVE_SECRET_KEY", raising=False)
    live = load_stock_bot(monkeypatch, live=True, test_keys=False, env={
        "ALPACA_API_KEY": "paper", "ALPACA_SECRET_KEY": "paper-secret"})
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as stopped:
        live.main()
    assert stopped.value.code == 1
    assert "ALPACA_LIVE_API_KEY and ALPACA_LIVE_SECRET_KEY must be set" in caplog.text
