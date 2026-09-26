"""Fast unit tests: context rules, fusion, challenge matching, ring buffer (no models)."""
import numpy as np
import pytest

from vshield.fusion import band_for, fuse
from vshield.policy import MATCH_OK, phrase_match
from vshield.session import RingBuffer
from vshield.signals.context import ContextState, analyse_text, parse_amounts

CEO = "+91-98100-00001"
UNKNOWN = "+91-77777-12345"

FRAUD = [
    "Transfer 25 lakh rupees to this new vendor account right now, and don't call me back, I'm in a meeting.",
    "Pachees lakh abhi transfer karo, call back mat karna, kisi ko mat batana.",
    "पच्चीस लाख अभी ट्रांसफर करो, कॉल बैक मत करना।",
    # what Whisper's translate mode produced from the Hindi test clip
    "Listen, this is very important. Rs. 25 lakh, now, transfer to the account of the new vendor. Do not call me, or tell anyone.",
]
ROUTINE = [
    "Hi, can you send me the Q3 deck before the board meeting?",
    "Now let's go over the agenda for the board meeting.",
    "Did you tell anyone about the offsite?",
]


@pytest.mark.parametrize("text", FRAUD)
def test_fraud_requests_score_high(text):
    st = ContextState(caller_id=CEO)
    st.add_utterance(text)
    assert st.score()["C"] >= 0.7


@pytest.mark.parametrize("text", ROUTINE)
def test_routine_requests_stay_low(text):
    st = ContextState(caller_id=CEO)
    st.add_utterance(text)
    assert st.score()["C"] < 0.3


@pytest.mark.parametrize("text,amount", [
    ("transfer 25 lakh", 2_500_000), ("pay ₹4,50,000 today", 450_000), ("do crore bhejo", 20_000_000),
    ("पच्चीस लाख", 2_500_000), ("send 50k", 50_000), ("Rs. 1,20,000", 120_000),
])
def test_amount_parsing(text, amount):
    assert max(a for a, _ in parse_amounts(text)) == amount


def test_context_is_call_level():
    st = ContextState(caller_id=CEO)
    st.add_utterance("Transfer 25 lakh to the new vendor.")
    st.add_utterance("Thanks, bye.")
    assert st.score()["C"] >= 0.7  # a risky request stays on the record


def test_unknown_caller_claiming_authority():
    known, unknown = ContextState(caller_id=CEO), ContextState(caller_id=UNKNOWN)
    for st in (known, unknown):
        st.add_utterance("This is the CEO. Buy gift cards worth 50k.")
    assert "authority_claim" not in known.score()["terms"]
    assert unknown.score()["terms"]["authority_claim"] >= 0.3


def test_highlight_spans_point_at_the_words():
    text = "Transfer 25 lakh now, don't call me back"
    spans = analyse_text(text)["spans"]
    assert {text[s["start"]:s["end"]].lower() for s in spans} >= {"transfer", "25 lakh", "don't call me back"}


# ------------------------------------------------------------------ fusion
def test_bands():
    assert [band_for(r) for r in (0, 29.9, 30, 59.9, 60, 79.9, 80, 100)] == \
        ["low", "low", "medium", "medium", "high", "high", "critical", "critical"]


def test_genuine_routine_is_low():
    assert fuse({"A": 0.05, "S": 0.1, "B": 0.1, "C": 0.0})["band"] == "low"


def test_clone_plus_fraud_request_is_critical():
    out = fuse({"A": 0.8, "S": 0.3, "B": 0.3, "C": 0.9})
    assert out["band"] == "critical" and out["rules"]


def test_genuine_voice_with_fraud_request_is_verified_not_blocked():
    out = fuse({"A": 0.05, "S": 0.05, "B": 0.1, "C": 0.9})
    assert out["band"] == "medium"


def test_missing_signal_renormalises():
    assert fuse({"A": 1.0, "S": None, "B": 1.0, "C": 1.0})["R"] == 100.0


def test_failed_challenge_escalates():
    assert fuse({"A": 0.1, "S": 0.1, "B": 0.1, "C": 0.0}, events={"challenge_failed": True})["R"] >= 70


def test_contributions_sum_to_r():
    out = fuse({"A": 0.5, "S": 0.2, "B": 0.3, "C": 0.4})
    assert abs(sum(out["contributions"].values()) - out["R"]) < 0.5


# ------------------------------------------------------------------ challenge + buffer
@pytest.mark.parametrize("heard,ok", [
    ("Green rocket 68.", True), ("green rocket sixty-eight", True), ("green, uh, rocket", True),
    ("Blue mango seventeen.", False), ("sorry?", False),
])
def test_phrase_match(heard, ok):
    assert (phrase_match("green rocket sixty eight", heard) >= MATCH_OK) is ok


def test_ring_buffer_keeps_absolute_positions():
    rb = RingBuffer(seconds=1.0)
    x = np.arange(40_000, dtype=np.float32)
    for i in range(0, len(x), 1600):
        rb.push(x[i:i + 1600])
    assert rb.total == 40_000
    assert np.array_equal(rb.get(30_000, 40_000), x[30_000:])


# ------------------------------------------------------------------ scam-script stages
DIGITAL_ARREST = [
    "Hello, this is Inspector Sharma from the CBI cyber cell.",
    "A parcel in your name was seized by customs and drugs were found. You are under digital arrest.",
    "Do not hang up and don't talk to anyone about this, it is confidential.",
    "To clear your name, install AnyDesk and transfer two lakh rupees right now.",
]


def test_scam_script_stages_in_order():
    st = ContextState(caller_id=UNKNOWN)
    seen = []
    for line in DIGITAL_ARREST:
        st.add_utterance(line)
        seen.append(list(st.score()["stages"]))
    assert seen[0] == ["hook", "pressure"]
    assert seen[2] == ["hook", "pressure", "isolation"]
    assert seen[3] == ["hook", "pressure", "isolation", "ask"]
    assert st.score()["C"] >= 0.9


@pytest.mark.parametrize("text", [
    "Hi, calling from head office about the Q3 report.",
    "The police are closing Main Street for the parade.",
    "Did you get the refund for the flight?",
])
def test_one_stage_never_escalates(text):
    st = ContextState(caller_id=CEO)
    st.add_utterance(text)
    sc = st.score()
    out = fuse({"A": 0.05, "S": 0.05, "B": 0.1, "C": sc["C"]}, events={"stages": sc["stages"]})
    assert len(sc["stages"]) <= 1 and out["band"] == "low"


def test_heading_into_scam_territory_warns_before_the_ask():
    genuine_voice = {"A": 0.05, "S": 0.05, "B": 0.1, "C": 0.6}
    assert fuse(genuine_voice, events={"stages": ["hook", "pressure"]})["band"] == "medium"
    assert fuse(genuine_voice, events={"stages": ["hook", "pressure", "isolation"]})["band"] == "high"


def test_spoofed_caller_id_still_records_the_hook():
    st = ContextState(caller_id=CEO)          # scammer spoofs the CEO's registered number
    st.add_utterance("This is the CEO speaking.")
    assert "hook" in st.score()["stages"]
