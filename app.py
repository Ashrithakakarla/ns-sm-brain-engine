"""NS SM Brain Engine v6 — SQL + Spreadsheets, all prompt fixes applied."""
from flask import Flask, render_template_string, jsonify, request
import json, os, datetime
from openai import OpenAI

app = Flask(__name__)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
DATA_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_refresh.json")
THRESH_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "thresholds.json")
HISTORY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.json")

llm_client = OpenAI(api_key=OPENAI_API_KEY)
LLM_LABEL  = "GPT-4.1 Mini"
LLM_IN     = 0.40 / 1_000_000
LLM_OUT    = 1.60 / 1_000_000
USE_CLAUDE = False

token_log = []

def load_data():
    if not os.path.exists(DATA_PATH): return {"students": []}
    with open(DATA_PATH) as f: return json.load(f)

def load_history():
    if not os.path.exists(HISTORY_PATH): return []
    with open(HISTORY_PATH) as f: return json.load(f)

def normalized_score(c):
    if not c or c.get("score") is None: return None
    return c.get("normalized_score",
                 round(c["score"] / c["max_marks"] * 100, 1) if c.get("max_marks") else 0)

# ─────────────────────────────────────────────────────────────────────────────
# PLAYLIST LABELS (Spreadsheets)
# ─────────────────────────────────────────────────────────────────────────────
PLAYLIST_LABELS = {
    5:  "General Practice (VLOOKUP, Pivot, Charts)",
    7:  "SQL Practice",
    8:  "SQL Practice",
    9:  "SQL Practice",
    12: "Contest Practice — Bonus/Salary/Feedback",
    13: "Contest Practice — Customer/Employee Analysis",
    14: "Contest Practice — Data Analysis",
    20: "Mid Module Contest Practice",
    21: "Mid Module Contest Practice",
}

# ─────────────────────────────────────────────────────────────────────────────
# SPREADSHEETS PHASE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
PHASE_CFG = {
    1: {
        "name": "Attendance & First Steps (E1–E3)",
        "next": "Assignment momentum + Mid MC prep",
        "p0": "ATTENDANCE ≥80% + FIRST ASSIGNMENT",
        "p0_detail": "North star: Clear MC1 or MC2. Foundation first: hit ≥80% attendance and get first questions solved. Every class missed = missed practice.",
        "p1": "ENGAGEMENT & TA SESSIONS",
        "p1_detail": "Book first TA session if stuck. Even 1 solved topic builds momentum toward MC clearance.",
    },
    2: {
        "name": "Assignment + Mid MC Prep (E4–E6)",
        "next": "Mid Module Contest",
        "p0": "ATTENDANCE ≥80% + ASSIGNMENT ≥80%",
        "p0_detail": "North star: Clear MC1 or MC2. Mid MC is the practice run. Attendance ≥80% non-negotiable. Assignment ≥80%: name specific unsolved topics and how much % each adds. TA=0 with pending topics = must book TA.",
        "p1": "MID MODULE CONTEST PREP",
        "p1_detail": "Mid MC topics: Ticket Resolution SLA Analysis, Employee Work Hours Payout, Talent Acquisition Data Cleaning, Employee Appraisal Payout, Sales Data Zone-wise Performance. Push Playlist Week 1 once assignment >75%. Hype up: Mid MC is practice for the real thing!",
    },
    3: {
        "name": "Main MC Prep (E7–E10)",
        "next": "Module Contest 1 (MC1) — NORTH STAR",
        "p0": "ATTENDANCE ≥80% + ASSIGNMENT ≥80%",
        "p0_detail": "North star: Clear MC1 (≥64/100). Attendance ≥82% — E7-E10 classes are contest-critical. Assignment ≥80%: unsolved topics = contest failures. Name weak topics. Book TA for hard ones. Push Playlist W2 & W3 once assignment >75%.",
        "p1": "MC1 PREP — WEAK TOPIC TARGETING",
        "p1_detail": "MC1 is the real exam. RCA on weak topics from assignments. Push Playlist W2 & W3 for targeted practice. Re-practice suspiciously fast solves. Congratulate if Mid MC cleared! Goal: ≥64/100 on MC1.",
    },
    4: {
        "name": "Contest & Project (E11+)",
        "next": "MC1 + MC2 clearance + Project submission",
        "p0": "ATTENDANCE ≥80% + ASSIGNMENT ≥80% + MC CLEARANCE",
        "p0_detail": "North star: Clear MC1 or MC2. If MC1 cleared — CONGRATULATE! Push MC2 as backup. If MC1 not cleared — urgent MC2 prep, push Playlist W2 & W3 + weak topics. Project: ONLY if released. If all assignments solved — push Spreadsheet Intake Preparation Playlist 1.",
        "p1": "PLAYLIST + WEAK TOPIC DRILL",
        "p1_detail": "Push Playlist W2 & W3. Re-practice weak topics. If all assignments solved — recommend Spreadsheet Intake Preparation Playlist 1 to recall and reinforce. Book TA for remaining hard topics.",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# SQL MODULE CONFIG — Sunday contest calendar
# ─────────────────────────────────────────────────────────────────────────────
SQL_MODULE_CONFIG = {
    "total_classes":           30,
    "project_release_after":   30,
    "playlist_push_threshold": 80,
    "mc_clearing_marks":       64,

    "contest_playlists": {
        "mid_mc1":  ["SQL Playlist Week 4", "SQL Playlist Week 5"],
        "mid_mc2":  ["SQL Playlist Week 4", "SQL Playlist Week 5",
                     "Previous Mid Module Contest Questions"],
        "main_mc1": ["SQL Playlist Week 4", "SQL Playlist Week 5",
                     "SQL Playlist Week 6", "SQL Playlist Week 7"],
        "main_mc2": ["SQL Playlist Week 4", "SQL Playlist Week 5",
                     "Previous Main Module Contest Questions",
                     "SQL Playlist Week 6", "SQL Playlist Week 7"],
    },

    "playlist_by_class": {
        (1,  7):  ["SQL Playlist Week 1"],
        (8,  9):  ["SQL Playlist Week 1", "SQL Playlist Week 2"],
        (10, 12): ["SQL Playlist Week 2", "SQL Playlist Week 3"],
        (13, 14): ["SQL Playlist Week 3", "SQL Playlist Week 4"],
        (15, 19): ["SQL Playlist Week 1", "SQL Playlist Week 2",
                   "SQL Playlist Week 3", "SQL Playlist Week 4"],
        (20, 20): ["SQL Playlist Week 1", "SQL Playlist Week 2",
                   "SQL Playlist Week 3", "SQL Playlist Week 4",
                   "SQL Playlist Week 5"],
        (21, 30): ["SQL Playlist Week 4", "SQL Playlist Week 5",
                   "SQL Playlist Week 6", "SQL Playlist Week 7",
                   "Re-practice weak questions"],
    },

    "important_assignments": [
        "Viewer but Streamer",
        "My SQL — Recent Refinance Submissions",
        "User Retention",
        "Analyzing Stock Performance, Volume, and Identifying Top Gainers",
        "SQL — Overall Average (MySQL)",
        "Premium Customers",
        "Suppliers Order",
    ],

    "phase_map": {
        (1,  4):  1,
        (5,  9):  2,
        (10, 14): 3,
        (15, 20): 4,
        (21, 21): 5,
        (22, 30): 6,
        (31, 99): 7,
    },

    "mid_mc1_after_class":  20,
    "mid_mc2_after_class":  21,
    "main_mc1_after_class": 30,
    "main_mc2_after_class": 32,
}

SQL_PHASE_CFG = {
    1: {"name": "Foundation (S1–S4)",              "next": "Assignment ≥80% + Playlist Week 1"},
    2: {"name": "Assignment + Playlist W1-W2 (S5–S9)",   "next": "Playlist W2 & W3 + assignment ≥80%"},
    3: {"name": "Assignment + Playlist W2-W4 (S10–S14)", "next": "Assignment ≥80% → Playlist W3-W4"},
    4: {"name": "Mid MC Prep (S15–S20)",           "next": "SQL Mid Module Contest 1 (Sunday after class 20)"},
    5: {"name": "Post Mid MC Triage (S21)",        "next": "Mid MC 2 → Main MC prep"},
    6: {"name": "Main MC Prep (S22–S30)",          "next": "SQL Main Module Contest 1 — NORTH STAR"},
    7: {"name": "Post Main MC + Project (S31+)",   "next": "Project clearance + MC2 if needed"},
}

def _get_sql_phase(cls):
    for (lo, hi), phase in SQL_MODULE_CONFIG["phase_map"].items():
        if lo <= cls <= hi: return phase
    return 7

def _get_sql_phase_cfg(cls):
    return SQL_PHASE_CFG.get(_get_sql_phase(cls), SQL_PHASE_CFG[6])

def _get_sql_playlists_for_class(cls):
    for (lo, hi), playlists in SQL_MODULE_CONFIG["playlist_by_class"].items():
        if lo <= cls <= hi: return playlists
    return ["SQL Playlist Week 4", "SQL Playlist Week 5",
            "SQL Playlist Week 6", "SQL Playlist Week 7"]

def _get_sql_contest_window(cls):
    mid1 = SQL_MODULE_CONFIG["mid_mc1_after_class"]
    mc1  = SQL_MODULE_CONFIG["main_mc1_after_class"]
    if cls < mid1 - 4:
        return f"Mid MC 1 coming (Sunday after class {mid1}) — {mid1-cls} classes away"
    elif cls < mid1:
        return f"⚠ Mid MC 1 in {mid1-cls} class(es) — URGENT PREP window"
    elif cls == mid1:
        return "🔴 Mid MC 1 this Sunday — final push"
    elif cls <= mid1 + 1:
        return "Mid MC 1 done — Mid MC 2 this Sunday — push for failed/missed students"
    elif cls < mc1 - 4:
        return f"Main MC 1 coming (Sunday after class {mc1}) — {mc1-cls} classes away. Inform every call."
    elif cls < mc1:
        return f"⚠ Main MC 1 in {mc1-cls} class(es) — CRITICAL PREP WINDOW"
    elif cls == mc1:
        return "🔴 Main MC 1 this Sunday — final push"
    else:
        return "Main MC 1 done — Main MC 2 coming. Push for failed/missed students."

# ─────────────────────────────────────────────────────────────────────────────
# PROMPT BUILDER
# ─────────────────────────────────────────────────────────────────────────────
def build_gpt_prompt(student):
    batch_name = student.get("batch", "")
    is_sql     = "sql" in batch_name.lower()
    module_key = "SQL" if is_sql else "Spreadsheets"
    mod        = student.get("mods", {}).get(module_key, {})
    if not mod:
        mod = student.get("mods", {}).get("Spreadsheets", {})

    cls           = mod.get("current_class", 1)
    total_classes = SQL_MODULE_CONFIG["total_classes"] if is_sql else 16

    if is_sql:
        phase = _get_sql_phase(cls)
        cfg   = _get_sql_phase_cfg(cls)
    else:
        phase = mod.get("current_phase", 2)
        cfg   = PHASE_CFG.get(phase, PHASE_CFG[2])

    att      = student.get("avg_att", 0)
    days_ia  = student.get("days_inactive", 0)
    ta_count = mod.get("ta_count", 0)

    # ── Assignment ────────────────────────────────────────────────────────────
    learn    = mod.get("asgn_detail", [])
    app_d    = mod.get("app_detail", [])
    all_d    = learn + app_d

    learn_solved = mod.get("learn_solved", sum(d.get("solved", 0) for d in learn))
    learn_total  = mod.get("learn_total",  sum(d.get("total_released", 0) for d in learn))
    app_solved   = mod.get("app_solved",   sum(d.get("solved", 0) for d in app_d))
    app_total    = mod.get("app_total",    sum(d.get("total_released", 0) for d in app_d))
    total_solved = learn_solved + app_solved
    total_qs     = learn_total  + app_total
    real_asgn_pct = round(total_solved / total_qs * 100, 1) if total_qs > 0 else student.get("avg_asgn", 0)

    unsolved_topics = list({d["topic"] for d in all_d
                            if d.get("solved", 0) == 0 and d.get("attempted", 0) > 0})
    not_att_topics  = list({d["topic"] for d in all_d
                            if d.get("attempted", 0) == 0 and d.get("total_released", 0) > 0})
    quick_topics    = [f"{d['topic']} ({d['avg_time_mins']}m avg)" for d in all_d
                       if d.get("avg_time_mins") and d["avg_time_mins"] < 3 and d.get("solved", 0) > 0]

    unsolved_q_count  = sum(d.get("total_released", 0) - d.get("solved", 0) for d in all_d
                            if d.get("solved", 0) == 0 and d.get("attempted", 0) > 0)
    est_pct_if_solved = round((total_solved + unsolved_q_count) / total_qs * 100, 1) if total_qs > 0 else real_asgn_pct

    topic_gains = []
    for d in all_d:
        uq = d.get("total_released", 0) - d.get("solved", 0)
        if uq > 0 and total_qs > 0:
            topic_gains.append(f"{d['topic']} +{round(uq/total_qs*100,1)}%")
    topic_gains = topic_gains[:6]

    # ── Contest analysis ──────────────────────────────────────────────────────
    conts = mod.get("contests", {})
    mid   = conts.get("mid_mc") or conts.get("mid_mc1")
    mc1   = conts.get("mc1")
    mc2   = conts.get("mc2")
    mid_n = normalized_score(mid)
    mc1_n = normalized_score(mc1)
    mc2_n = normalized_score(mc2)

    mid_mc_held      = mid  is not None
    mc1_held         = mc1  is not None
    mc2_held         = mc2  is not None
    mid_mc_attempted = mid_n is not None
    mc1_attempted    = mc1_n is not None
    mc2_attempted    = mc2_n is not None

    final_mc_cleared = (mc1_n is not None and mc1_n >= 64) or (mc2_n is not None and mc2_n >= 64)
    mid_mc_cleared   = mid_n is not None and mid_n >= 64
    all_assignments_done = len(not_att_topics) == 0 and len(unsolved_topics) == 0

    past_cleared, past_failed, not_attempted = [], [], []
    if mc1_n is not None and mc1_n >= 64: past_cleared.append("MC1")
    if mc2_n is not None and mc2_n >= 64: past_cleared.append("MC2")
    if mid_n is not None and mid_n >= 64: past_cleared.append("Mid MC")
    if mc1_n is not None and mc1_n < 64:  past_failed.append(f"MC1 ({mc1_n}/100)")
    if mc2_n is not None and mc2_n < 64:  past_failed.append(f"MC2 ({mc2_n}/100)")
    if mid_n is not None and mid_n < 64 and not final_mc_cleared:
        past_failed.append(f"Mid MC ({mid_n}/100)")
    if mc1_held and not mc1_attempted:    not_attempted.append("MC1")
    if mc2_held and not mc2_attempted:    not_attempted.append("MC2")
    if mid_mc_held and not mid_mc_attempted and not final_mc_cleared:
        not_attempted.append("Mid MC")

    def fmt_c(c, n, label):
        if c is None:  return f"{label}: Not held yet"
        if n is None:  return f"{label}: Contest held — not attempted"
        clr = "CLEARED ✓" if n >= 64 else f"NOT CLEARED — need +{round(64-n,1)} pts"
        return f"{label}: {n}/100 ({clr})"

    mid_str = fmt_c(mid, mid_n, "Mid MC")
    mc1_str = fmt_c(mc1, mc1_n, "MC Attempt 1")
    mc2_str = fmt_c(mc2, mc2_n, "MC Attempt 2")

    # ── Project ───────────────────────────────────────────────────────────────
    proj = mod.get("project")
    if proj:
        hist     = proj.get("submission_history", [])
        hist_str = " | ".join(
            [f"Sub{h['submission']}: {h['marks']}/10"
             if h["marks"] is not None else f"Sub{h['submission']}: pending"
             for h in hist]) if hist else ""
        if proj.get("cleared"):
            proj_str = f"Project CLEARED ✓ {proj['marks']}/{proj.get('max_marks',10)}"
        else:
            subs = proj.get("submissions", 0)
            fb   = proj.get("feedback_count", 0)
            score= proj.get("marks")
            if subs > 0 and fb > 0:
                proj_str = (f"Submitted {subs}x [{hist_str}], {fb} feedbacks received "
                            f"(latest {proj.get('last_feedback','?')}) — "
                            f"{'Score <8 — MUST resubmit with feedback implemented' if score is not None and score < 8 else 'Awaiting evaluation'}")
            elif subs > 0:
                proj_str = f"Submitted {subs}x [{hist_str}] — awaiting evaluation"
            else:
                proj_str = "NOT submitted"
    else:
        proj_str = ("Not yet released for this batch"
                    if (not is_sql and phase < 4) or
                       (is_sql and cls <= SQL_MODULE_CONFIG["project_release_after"])
                    else "NOT submitted — critical")

    # ── Missed classes ────────────────────────────────────────────────────────
    lectures     = mod.get("lectures", [])
    missed_count = sum(1 for l in lectures
                       if l.get("attended") is False or l.get("attended") == 0)
    if not lectures and mod.get("total_lec"):
        missed_count = round(int(mod.get("total_lec", 0)) * (1 - att / 100))

    # ── Playlists (Spreadsheets) ──────────────────────────────────────────────
    playlists          = mod.get("playlist_detail", [])
    relevant_playlists = []
    for p in playlists:
        pid   = p.get("playlist_id", 0)
        label = PLAYLIST_LABELS.get(pid, f"Playlist {pid}")
        if not p.get("completed") and pid in [5, 12, 13, 14, 20, 21]:
            relevant_playlists.append(
                f"Playlist {pid} — {label} ({p.get('total_questions',0)} questions, in-progress)")
        elif p.get("completed") and pid in [5, 12, 13, 14, 20, 21]:
            relevant_playlists.append(
                f"Playlist {pid} — {label} ({p.get('total_questions',0)} questions, COMPLETED ✓)")

    # ── Shared flags ──────────────────────────────────────────────────────────
    att_ok         = att >= 80
    asgn_ok        = real_asgn_pct >= 80
    topics_pending = unsolved_topics + not_att_topics
    ta_needed      = ta_count == 0 and len(topics_pending) > 0

    # ─────────────────────────────────────────────────────────────────────────
    # SQL CONTEXT + P0/P1
    # ─────────────────────────────────────────────────────────────────────────
    if is_sql:
        mid1_after   = SQL_MODULE_CONFIG["mid_mc1_after_class"]
        mid2_after   = SQL_MODULE_CONFIG["mid_mc2_after_class"]
        mc1_after    = SQL_MODULE_CONFIG["main_mc1_after_class"]
        proj_released= cls > SQL_MODULE_CONFIG["project_release_after"]
        cw           = _get_sql_contest_window(cls)
        sql_playlists= _get_sql_playlists_for_class(cls)
        sql_imp      = SQL_MODULE_CONFIG["important_assignments"]
        threshold    = SQL_MODULE_CONFIG["playlist_push_threshold"]

        if not proj_released:
            proj_str = f"Not yet released (releases after class {SQL_MODULE_CONFIG['project_release_after']})"

        can_push = real_asgn_pct >= threshold
        playlist_gate = (
            f"Push: {', '.join(sql_playlists[:3])}"
            if can_push
            else f"Assignment {real_asgn_pct}% < {threshold}% — complete topics first, THEN playlists"
        )

        proj_cleared  = proj is not None and proj.get("cleared", False)
        proj_subs     = proj.get("submissions", 0) if proj else 0
        proj_score    = proj.get("marks") if proj else None
        proj_fb       = proj.get("feedback_count", 0) if proj else 0
        all_done      = final_mc_cleared and proj_cleared and len(topics_pending) == 0

        # ── RULE 1: Fundamentals always first ────────────────────────────────
        if not att_ok or not asgn_ok:
            p0_items = []
            if not att_ok:
                p0_items.append(
                    f"Attendance {att}% (missed {missed_count} classes) — must reach ≥80%."
                )
            if not asgn_ok:
                gains_str = " | ".join(topic_gains[:3]) if topic_gains else ", ".join(topics_pending[:3])
                p0_items.append(
                    f"Assignment {real_asgn_pct}% — solve: {gains_str}. "
                    + ("TA=0 with pending topics → MUST book TA." if ta_needed else "")
                )
            dyn_p0_label  = "ATTENDANCE & ASSIGNMENT — FIX FUNDAMENTALS"
            dyn_p0_detail = " | ".join(p0_items)
            dyn_p1_label  = "CONTEST AWARENESS"
            dyn_p1_detail = f"{cw}. Fix fundamentals first — playlists only after assignment ≥{threshold}%."

        # ── RULE 2: All done → SQL Intake Playlist ───────────────────────────
        elif all_done:
            dyn_p0_label  = "SQL INTAKE PREPARATION PLAYLIST"
            dyn_p0_detail = (
                "MC cleared ✓ + Project cleared ✓ + All assignments done ✓. "
                "Push SQL Intake Preparation Playlist to revise all module topics before next intake."
            )
            dyn_p1_label  = "MAINTAIN ENGAGEMENT"
            dyn_p1_detail = "Keep attending remaining classes. Congratulate on full module completion!"

        # ── RULE 3: Phase 7 — Post Main MC ───────────────────────────────────
        elif phase == 7:
            if final_mc_cleared:
                if proj_cleared:
                    dyn_p0_label  = "SQL INTAKE PREPARATION PLAYLIST"
                    dyn_p0_detail = "MC cleared ✓ + Project cleared ✓. Push SQL Intake Playlist to revise all module topics."
                    dyn_p1_label  = "MAINTAIN ENGAGEMENT"
                    dyn_p1_detail = "Congratulate on full module completion!"
                elif not proj_released:
                    dyn_p0_label  = "AWAIT PROJECT RELEASE"
                    dyn_p0_detail = f"MC cleared ✓. Project releases after class {SQL_MODULE_CONFIG['project_release_after']}. Stay engaged."
                    dyn_p1_label  = "PLAYLIST REVISION"
                    dyn_p1_detail = "Push SQL Playlist W6 & W7 to stay sharp while waiting."
                elif proj_subs > 0 and proj_score is not None and proj_score < 8:
                    if proj_fb > 0:
                        dyn_p0_label  = "PROJECT RESUBMISSION AFTER FEEDBACK"
                        dyn_p0_detail = (
                            f"Project score {proj_score}/10 (need ≥8). "
                            f"{proj_fb} feedback(s) received. MUST resubmit implementing feedback. "
                            "If feedback unclear → book TA to understand it first."
                        )
                    else:
                        dyn_p0_label  = "PROJECT — AWAITING EVALUATION"
                        dyn_p0_detail = f"Submitted {proj_subs}x — awaiting evaluation. Stay engaged."
                    dyn_p1_label  = "PLAYLIST REVISION"
                    dyn_p1_detail = "Continue SQL Playlist W6 & W7 while waiting."
                else:
                    dyn_p0_label  = "PROJECT SUBMISSION — CRITICAL"
                    dyn_p0_detail = f"MC cleared ✓ but project NOT submitted. Submit now. {proj_str}"
                    dyn_p1_label  = "PLAYLIST REVISION"
                    dyn_p1_detail = "Push SQL Playlist W6 & W7 alongside project."
            else:
                # MC not cleared
                if mc2_held and not mc2_attempted:
                    dyn_p0_label  = "MAIN MC2 — NOT ATTEMPTED (URGENT)"
                    dyn_p0_detail = (
                        "MC2 held but not attempted — understand why, give warning. "
                        "This is the LAST chance to clear the module. Push immediately."
                    )
                elif mc2_attempted:
                    best = mc2_n if mc2_n is not None else mc1_n
                    need = round(64-best,1) if best else "—"
                    dyn_p0_label  = "MAIN MC NOT CLEARED — ESCALATE"
                    dyn_p0_detail = (
                        f"Best score: {best}/100 — need +{need} pts. "
                        "Both MC1 and MC2 attempted. Escalate to senior SM."
                    )
                else:
                    need = round(64-(mc1_n or 0),1) if mc1_n else "—"
                    dyn_p0_label  = "MAIN MC2 — LAST CHANCE PREP"
                    dyn_p0_detail = (
                        f"MC1: {mc1_n}/100 (need +{need} pts on MC2). "
                        f"Push: {', '.join(SQL_MODULE_CONFIG['contest_playlists']['main_mc2'][:3])}. "
                        "RCA on MC1 weak topics."
                    )
                dyn_p1_label  = "PROJECT SUBMISSION"
                dyn_p1_detail = (proj_str if proj_released
                                 else f"Releases after class {SQL_MODULE_CONFIG['project_release_after']}. Focus on MC2 now.")

        # ── RULE 4: Phase 5 — Post Mid MC triage ─────────────────────────────
        elif phase == 5:
            mid_pl = SQL_MODULE_CONFIG["contest_playlists"]["mid_mc2"]
            main_pl = SQL_MODULE_CONFIG["contest_playlists"]["main_mc1"]

            # Check if Mid MC is cleared
            mid_mc_cleared = mid_mc_attempted and mid_n is not None and mid_n >= 64

            # CASE 1: Main MC already cleared (highest priority)
            if final_mc_cleared:
                dyn_p0_label  = "MAIN MC CLEARED ✓"
                dyn_p0_detail = (
                    f"Main MC cleared ✓ (Best: {max(mc1_n or 0, mc2_n or 0)}/100). "
                    "Excellent work! Focus on project or maintain sharpness."
                )
                dyn_p1_label  = "ASSIGNMENT + PROJECT"
                dyn_p1_detail = (
                    f"Assignment {real_asgn_pct}%. "
                    + (f"Pending: {', '.join(topics_pending[:3])}." if topics_pending else "All done ✓. ")
                    + ("Project prep." if proj_released else "Stay sharp for project release.")
                )

            # CASE 2: Mid MC CLEARED (≥64) → Recommend MAIN MC prep
            elif mid_mc_cleared:
                dyn_p0_label  = "MID MC CLEARED ✓ — FOCUS ON MAIN MC PREP"
                dyn_p0_detail = (
                    f"Mid MC cleared ✓ ({mid_n}/100). Great practice run! "
                    f"Now focus on MAIN MC {cw} — this is the real exam. "
                    + (f"Push: {', '.join(main_pl[:3])}." if can_push
                       else f"Assignment {real_asgn_pct}% — complete to ≥80% first, then push playlists.")
                )
                dyn_p1_label  = "KEY ASSIGNMENTS FOR MAIN MC"
                dyn_p1_detail = (
                    f"Critical topics for Main MC: {', '.join(sql_imp[:3])}. "
                    "These patterns appear in Main MC. "
                    + (f"Book TA for: {', '.join(topics_pending[:2])}." if ta_needed else "On track ✓")
                )

            # CASE 3: Mid MC FAILED (<64) → Recommend Mid MC Attempt 2
            elif mid_mc_attempted and mid_n < 64:
                need = round(64 - mid_n, 1)
                if can_push:
                    dyn_p0_label  = "MID MC FAILED — ATTEMPT MID MC 2"
                    dyn_p0_detail = (
                        f"Mid MC 1: {mid_n}/100 (need +{need} pts to clear). "
                        f"Assignment ≥80% ✓. Push Mid MC 2 playlists: {', '.join(mid_pl)}. "
                        "Clear Mid MC (≥64) before focusing on Main MC."
                    )
                else:
                    dyn_p0_label  = "MID MC FAILED — FIX ASSIGNMENT FIRST"
                    dyn_p0_detail = (
                        f"Mid MC 1: {mid_n}/100 (need +{need} pts). "
                        f"Assignment {real_asgn_pct}% < 80% — complete topics first: {', '.join(topics_pending[:3])}. "
                        + (f"Book TA for: {', '.join(topics_pending[:2])}." if ta_needed else "")
                    )
                dyn_p1_label  = "MID MC 2 PREP"
                dyn_p1_detail = (
                    "Mid MC 2 prep: " + ', '.join(mid_pl) + ". "
                    "Review Mid MC 1 mistakes. Practice previous Mid MC questions. Target ≥64/100."
                )

            # CASE 4: Did NOT attempt Mid MC → Recommend Mid MC 2 (or Main MC if too late)
            else:
                if mc1_held:
                    # Main MC already started, skip Mid MC
                    dyn_p0_label  = "MAIN MC STARTED — FOCUS ON MAIN MC"
                    dyn_p0_detail = (
                        f"Main MC {cw}. Mid MC not attempted. "
                        f"Focus directly on Main MC prep now. "
                        + (f"Push: {', '.join(main_pl[:3])}" if can_push
                           else f"Complete assignment first ({real_asgn_pct}%)")
                    )
                    dyn_p1_label  = "KEY ASSIGNMENTS"
                    dyn_p1_detail = (
                        f"Focus: {', '.join(sql_imp[:3])}. "
                        + (f"Book TA: {', '.join(topics_pending[:2])}." if ta_needed else "On track ✓")
                    )
                else:
                    # Mid MC 2 still available
                    dyn_p0_label  = "DID NOT ATTEMPT MID MC — WARNING"
                    dyn_p0_detail = (
                        "Understand why student missed Mid MC 1. Give clear warning. "
                        f"Mid MC 2 {cw} — this is practice before Main MC. "
                        + (f"Push: {', '.join(mid_pl)}" if can_push
                           else f"Complete assignment first ({real_asgn_pct}%)")
                    )
                    dyn_p1_label  = "MID MC 2 PREP"
                    dyn_p1_detail = (
                        f"Assignment {real_asgn_pct}%. "
                        f"Focus: {', '.join(topics_pending[:3])}. "
                        + (f"Book TA." if ta_needed else "On track ✓")
                    )

        # ── RULE 5: Phase 4 — Mid MC prep ────────────────────────────────────
        elif phase == 4:
            mid_pl = SQL_MODULE_CONFIG["contest_playlists"]["mid_mc1"]
            dyn_p0_label  = "MID MC 1 PREP — PRACTICE RUN FOR MAIN MC"
            dyn_p0_detail = (
                f"{cw}. "
                + (f"Push: {', '.join(mid_pl)}" if can_push
                   else f"Assignment {real_asgn_pct}% < 80% — complete topics first")
                + ". Inform about Mid MC every call — it is the practice run for Main MC."
            )
            if att < 70:
                dyn_p1_label  = "⚠ ATTENDANCE CRITICAL"
                dyn_p1_detail = (
                    f"Attendance {att}% < 70% — pre-contest window. "
                    "Call and warn. Not watching recordings = missing key SQL patterns."
                )
            else:
                dyn_p1_label  = "ASSIGNMENT COMPLETION"
                dyn_p1_detail = (
                    f"Assignment {real_asgn_pct}%. "
                    + (f"Pending: {', '.join(topics_pending[:3])}. " if topics_pending else "On track ✓. ")
                    + ("Book TA." if ta_needed else "")
                )

        # ── RULE 6: Phase 6 — Main MC prep ───────────────────────────────────
        elif phase == 6:
            main_pl = SQL_MODULE_CONFIG["contest_playlists"]["main_mc1"]
            mid_pl = SQL_MODULE_CONFIG["contest_playlists"]["mid_mc2"]

            # Check if Mid MC cleared
            mid_mc_cleared = mid_mc_attempted and mid_n is not None and mid_n >= 64

            if mid_mc_cleared or mc1_held:
                # Mid MC cleared OR Main MC already started → Full Main MC prep
                dyn_p0_label  = "MAIN MC PREP — NORTH STAR"
                dyn_p0_detail = (
                    f"{cw}. "
                    + ("Mid MC cleared ✓. " if mid_mc_cleared else "")
                    + (f"Push: {', '.join(main_pl)} + re-practice weak questions" if can_push
                       else f"Assignment {real_asgn_pct}% < 80% — complete topics first")
                    + f". Key assignments: {', '.join(sql_imp[:3])}…"
                )
                dyn_p1_label  = "KEY ASSIGNMENTS + WEAK TOPICS"
                dyn_p1_detail = (
                    f"Critical: {', '.join(sql_imp[:4])}. "
                    "These map directly to Main MC patterns. "
                    + (f"Book TA for: {', '.join(topics_pending[:2])}." if ta_needed else "On track ✓")
                )
            else:
                # Mid MC not cleared yet → Must clear Mid MC first
                dyn_p0_label  = "⚠️ MID MC NOT CLEARED — CLEAR THIS FIRST"
                dyn_p0_detail = (
                    f"Mid MC: {mid_str} — NOT cleared yet. "
                    f"Must clear Mid MC (≥64/100) before Main MC prep. "
                    + (f"Push: {', '.join(mid_pl)}" if can_push
                       else f"Complete assignment first ({real_asgn_pct}%)")
                )
                dyn_p1_label  = "MID MC CLEARANCE + ASSIGNMENT"
                dyn_p1_detail = (
                    f"Assignment {real_asgn_pct}%. "
                    f"Focus: {', '.join(topics_pending[:3])}. "
                    + (f"Book TA for: {', '.join(topics_pending[:2])}." if ta_needed else "")
                    + " Mid MC is the foundation for Main MC success."
                )

        # ── RULE 7: Phase 1/2/3 — progressive foundation ─────────────────────
        else:
            dyn_p0_label  = f"ATTENDANCE ≥80% + ASSIGNMENT ≥80%"
            dyn_p0_detail = (
                f"North star: Clear Main MC1 or MC2. "
                f"Attendance {att}% {'✓' if att_ok else '— BELOW 80%, must improve'}. "
                f"Assignment {real_asgn_pct}% {'✓' if asgn_ok else '— BELOW 80%'}. "
                + (f"Pending topics: {', '.join(topics_pending[:3])}. " if topics_pending else "")
                + (f"TA=0 with pending topics → book TA." if ta_needed else "")
            )
            if can_push:
                dyn_p1_label  = "PLAYLIST PROGRESSION"
                dyn_p1_detail = f"Assignment ≥80% ✓. Push: {', '.join(sql_playlists[:2])}."
            else:
                dyn_p1_label  = "COMPLETE REMAINING TOPICS"
                dyn_p1_detail = (
                    f"Focus on: {', '.join(topics_pending[:4])}. "
                    "Playlists only after assignment ≥80%."
                )

        # SQL-specific prompt additions
        mid_mc_cleared = mid_mc_attempted and mid_n is not None and mid_n >= 64

        sql_contest_rules = f"""
CONTEST HIERARCHY (SQL): Main MC2 > Main MC1 > Mid MC2 > Mid MC1.

CRITICAL RECOMMENDATION RULE:
✅ Mid MC CLEARED (≥64) → Recommend MAIN MC prep
❌ Mid MC FAILED (<64) → Recommend Mid MC Attempt 2 (must clear Mid MC first)
⚠️ Mid MC NOT ATTEMPTED → Recommend Mid MC Attempt 2 (gateway to Main MC)

NEVER recommend Main MC prep until Mid MC is cleared (≥64/100).
Mid MC is the GATEWAY to Main MC prep.

CURRENT STATUS:
- Mid MC: {mid_str} {'✅ CLEARED' if mid_mc_cleared else '❌ NOT CLEARED'}
- Main MC1: {mc1_str}
- Main MC2: {mc2_str}

WHAT TO RECOMMEND NOW:
{"→ MAIN MC PREP (Mid MC cleared ✅)" if mid_mc_cleared else "→ MID MC ATTEMPT 2 (clear Mid MC first ❌)"}

PLAYLIST GATE: NEVER push playlists if assignment <80%. Name assignment topics first.
TA RULE: If TA=0 and any topics pending → MUST recommend booking TA.

FAST SOLVED TOPICS (<3 min):
If student has topics completed in <3 minutes → recommend: "Re-practice [topic names] — solved quickly, ensure deep understanding for MC."

ALL TOPICS CLEARED:
If ALL assignments done + MC cleared → SQL Intake Preparation Playlist.
"Revise all module topics to maintain sharpness."

PROJECT RULE: Only mention project if released (after class {SQL_MODULE_CONFIG['project_release_after']}).
  Score <8 + feedback received → resubmit implementing feedback.
  Score <8 + feedback unclear → book TA first to understand feedback.
  Not submitted → push submission now.

CONTEST PREP PLAYLISTS:
  Mid MC 1:  {', '.join(SQL_MODULE_CONFIG['contest_playlists']['mid_mc1'])}
  Mid MC 2:  {', '.join(SQL_MODULE_CONFIG['contest_playlists']['mid_mc2'])}
  Main MC 1: {', '.join(SQL_MODULE_CONFIG['contest_playlists']['main_mc1'])}
  Main MC 2: {', '.join(SQL_MODULE_CONFIG['contest_playlists']['main_mc2'])}

INTAKE PLAYLIST: Only suggest SQL Intake Playlist when ALL THREE true:
  1. Main MC cleared (≥64/100)  2. Project cleared (≥8/10)  3. All assignments done."""

        cw_str = cw

    # ─────────────────────────────────────────────────────────────────────────
    # SPREADSHEETS P0/P1
    # ─────────────────────────────────────────────────────────────────────────
    else:
        proj_released = proj is not None
        cw_str        = ""
        sql_contest_rules = ""

        if not att_ok or not asgn_ok:
            p0_items = []
            if not att_ok:
                p0_items.append(f"Attendance {att}% (missed {missed_count} classes) — must reach ≥80%")
            if not asgn_ok:
                gains_str = " | ".join(topic_gains[:3]) if topic_gains else ", ".join(topics_pending[:3])
                p0_items.append(f"Assignment {real_asgn_pct}% — solve: {gains_str}")
            if ta_needed:
                p0_items.append(f"TA=0 — book TA for: {', '.join(topics_pending[:2])}")
            dyn_p0_label  = "ATTENDANCE & ASSIGNMENT — FIX FUNDAMENTALS"
            dyn_p0_detail = " | ".join(p0_items)
            if final_mc_cleared and proj_released:
                dyn_p1_label  = "PROJECT SUBMISSION"
                dyn_p1_detail = proj_str
            elif final_mc_cleared and all_assignments_done:
                dyn_p1_label  = "SPREADSHEET INTAKE PREPARATION PLAYLIST"
                dyn_p1_detail = "MC cleared and all assignments done. Push Spreadsheet Intake Preparation Playlist 1."
            else:
                dyn_p1_label  = "COMPLETE REMAINING TOPICS"
                dyn_p1_detail = f"Focus on: {', '.join(topics_pending[:4])}"

        elif final_mc_cleared:
            proj_cleared = proj and proj.get("cleared")
            if proj_cleared or not proj_released:
                dyn_p0_label  = "SPREADSHEET INTAKE PREPARATION PLAYLIST"
                dyn_p0_detail = (
                    "MC cleared ✓ and project done. "
                    "Push Spreadsheet Intake Preparation Playlist 1 — recall and reinforce all module concepts."
                )
                dyn_p1_label  = "MAINTAIN ENGAGEMENT"
                dyn_p1_detail = "Keep solving to stay sharp. Attend remaining classes. Congratulate on module completion!"
            else:
                proj_score = proj.get("marks") if proj else None
                proj_fb    = proj.get("feedback_count", 0) if proj else 0
                dyn_p0_label  = "PROJECT SUBMISSION"
                if proj_score is not None and proj_score < 8 and proj_fb > 0:
                    dyn_p0_detail = (
                        f"MC cleared ✓. Project score {proj_score}/10 (need ≥8). "
                        f"{proj_fb} feedback(s) received — MUST resubmit implementing feedback. "
                        "If feedback unclear → book TA first."
                    )
                else:
                    dyn_p0_detail = f"MC cleared ✓ — {proj_str}. Submit or resubmit with feedback incorporated."
                if all_assignments_done:
                    dyn_p1_label  = "SPREADSHEET INTAKE PREPARATION PLAYLIST"
                    dyn_p1_detail = "All assignments done. Push Spreadsheet Intake Preparation Playlist 1 alongside project."
                else:
                    dyn_p1_label  = "COMPLETE REMAINING ASSIGNMENTS"
                    dyn_p1_detail = f"Pending: {', '.join(topics_pending[:4])}"

        elif phase == 4 and (mc1_held or mc2_held):
            if mc2_held and not mc2_attempted:
                dyn_p0_label  = "MC2 — MUST ATTEMPT (FINAL CHANCE)"
                dyn_p0_detail = (
                    f"MC2 has not been attempted — last chance to clear the module. "
                    f"MC1 result: {mc1_str}. "
                    "Identify weak topics, do targeted practice. Goal: ≥64/100 on MC2."
                )
            elif mc1_held and not mc1_attempted:
                dyn_p0_label  = "MC1 — NOT YET ATTEMPTED"
                dyn_p0_detail = (
                    "MC1 has not been attempted. Highest priority — attempt MC1 and score ≥64/100. "
                    "Push Playlist W2 & W3 + weak topic drill immediately."
                )
            else:
                best_failed = mc2_n if mc2_n is not None else mc1_n
                need        = round(64-best_failed,1) if best_failed else "—"
                dyn_p0_label  = "MC CLEARANCE — URGENT"
                dyn_p0_detail = (
                    f"Best score so far: {best_failed}/100 — need +{need} pts to clear. "
                    "Push Playlist W2 & W3. Drill weak topics from assignment."
                )
            dyn_p1_label  = "PROJECT SUBMISSION"
            dyn_p1_detail = proj_str

        else:
            if not mid_mc_held and "MID MODULE" in cfg.get("p1", ""):
                dyn_p0_label  = cfg["p0"]
                dyn_p0_detail = cfg.get("p0_detail", "")
                dyn_p1_label  = cfg["p1"]
                dyn_p1_detail = cfg.get("p1_detail", "") + (
                    f" Book TA for: {', '.join(topics_pending[:2])}." if ta_needed else "")
            elif mid_mc_held and not mc1_held:
                dyn_p0_label  = "ASSIGNMENT & MC1 PREP"
                dyn_p0_detail = f"Mid MC done ({mid_str}). Focus on weak topics for MC1. Assignment: {real_asgn_pct}%."
                dyn_p1_label  = "PLAYLIST W2 & W3"
                dyn_p1_detail = "Push Playlist W2 & W3 for targeted MC1 practice." + (
                    f" Book TA for: {', '.join(topics_pending[:2])}." if ta_needed else "")
            else:
                dyn_p0_label  = cfg["p0"]
                dyn_p0_detail = cfg.get("p0_detail", "")
                dyn_p1_label  = cfg["p1"]
                dyn_p1_detail = cfg.get("p1_detail", "") + (
                    f" Book TA for: {', '.join(topics_pending[:2])}." if ta_needed else "")

    # ── Intake note ───────────────────────────────────────────────────────────
    if not is_sql:
        if final_mc_cleared and all_assignments_done:
            intake_note = "\nINTAKE PLAYLIST: MC cleared + all assignments done → MUST suggest Spreadsheet Intake Preparation Playlist 1."
        elif final_mc_cleared:
            intake_note = "\nINTAKE PLAYLIST: MC cleared. If all assignments done → suggest Spreadsheet Intake Preparation Playlist 1."
        else:
            intake_note = ""
    else:
        intake_note = ""

    # ── Build prompt strings ──────────────────────────────────────────────────
    unsolved_str   = json.dumps(unsolved_topics[:6])
    not_att_str    = json.dumps(not_att_topics[:6])
    topic_gain_str = " | ".join(topic_gains) if topic_gains else "No unsolved topics"
    ta_rec         = ("Book TA for: " + ", ".join(topics_pending[:2])) if ta_needed else "On track"
    proj_short     = proj_str[:100].replace('"', "'")
    phase_name     = cfg.get("name", f"Phase {phase}")
    phase_next     = cfg.get("next", "")

    system = f"""You are a Newton School Success Manager. Write a crisp pre-call brief for {student['name']}.
Class {cls}/{total_classes} | Phase {phase} — {phase_name} | Next: {phase_next}

P0 — {dyn_p0_label}: {dyn_p0_detail}
P1 — {dyn_p1_label}: {dyn_p1_detail}

RULES:
1. Attendance {att}% ({missed_count} missed). ONLY flag if <80%. Do NOT mention if ≥80%.
2. Assignment {real_asgn_pct}% ({total_solved}/{total_qs} Qs | Learn:{learn_solved}/{learn_total} | App:{app_solved}/{app_total}).
   Unsolved (tried, not passed): {unsolved_topics}
   Not attempted: {not_att_topics}
   Topic gains if solved: {topic_gain_str}
   ALWAYS name specific topic names. NEVER say "complete assignments" generically.
   If TA=0 and topics pending → MUST say "Book TA for [topic name]".
3. Project: {proj_str}. If not released → do NOT suggest submitting.
   If score <8 and feedback received → resubmit implementing feedback.
   If feedback unclear → book TA first to understand feedback.
4. Contest status: cleared={past_cleared} | failed={past_failed} | not attempted={not_attempted}.
   {cw_str}
   NEVER recommend Mid MC prep if MC1 or MC2 is already cleared.
   NEVER recommend Mid MC prep if Mid MC is already over (mid_mc_held={mid_mc_held}).
   If MC1 and MC2 both over and not cleared → focus only on what's remaining.
5. Only recommend playlists if assignment ≥80% OR upcoming contest within 2 classes.
{intake_note}
{sql_contest_rules}
6. P0 and P1 each have EXACTLY 2 bullet points. NO P2. NO generic advice.

Return ONLY valid JSON (no markdown):
{{
  "call_type": "3-word label",
  "phase_context": "Class {cls}/{total_classes} — {phase_name} — Next: {phase_next}",
  "attendance": {{"flag": "ok|warn|critical", "missed_count": {missed_count}, "note": "null if att>=80%"}},
  "assignment": {{
    "flag": "ok|warn|critical",
    "completion": "{real_asgn_pct}% (Learn:{learn_solved}/{learn_total} | App:{app_solved}/{app_total})",
    "unsolved_topics": {unsolved_str},
    "not_attempted_topics": {not_att_str},
    "topic_gains": {json.dumps(topic_gains)},
    "ta_recommendation": "{ta_rec}"
  }},
  "mc_score": {{
    "flag": "ok|warn|critical",
    "mid_mc": "{mid_str}",
    "mc1": "{mc1_str}",
    "mc2": "{mc2_str}",
    "next_action": "specific next step — never suggest already-completed contests"
  }},
  "project": {{"flag": "ok|warn|critical", "status": "{proj_short}", "action": "specific or null"}},
  "recommendation": {{
    "p0": {{"label": "{dyn_p0_label}", "items": ["specific action with topic/data", "second specific action"]}},
    "p1": {{"label": "{dyn_p1_label}", "items": ["specific action 1", "specific action 2"]}},
    "immediate_action": "single most important thing RIGHT NOW"
  }},
  "sm_questions": {{
    "q1": "attendance/engagement question with specific data point",
    "q2": "question about a specific unsolved topic or contest gap",
    "q3": "contest or project question — only about what is still pending",
    "q4": "empathetic custom question based on their specific situation"
  }},
  "priority": "high|medium|low"
}}"""

    user = f"""Student: {student['name']} | Batch: {batch_name} | Class {cls}/{total_classes}
Risk: {student['risk']}/100 | Days inactive: {days_ia} | TA sessions: {ta_count}
Attendance: {att}% | Missed: {missed_count} classes
Assignment: {real_asgn_pct}% ({total_solved}/{total_qs} Qs)
Unsolved topics: {unsolved_topics[:6]}
Not attempted: {not_att_topics[:6]}
Topic gains: {topic_gains}
Quick solves (<3m): {quick_topics[:3]}
Contests: {mid_str} | {mc1_str} | {mc2_str}
Mid MC held: {mid_mc_held} | MC1 held: {mc1_held} | MC2 held: {mc2_held}
Final MC cleared: {final_mc_cleared} | All assignments done: {all_assignments_done}
Playlists: {relevant_playlists if relevant_playlists else 'none'}
Project: {proj_str}"""

    return system, user


# ─────────────────────────────────────────────────────────────────────────────
# GPT CALL
# ─────────────────────────────────────────────────────────────────────────────
def _strip_fences(raw):
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
    return raw.strip()


def generate_action_plan(student):
    system, user = build_gpt_prompt(student)
    resp = llm_client.chat.completions.create(
        model="gpt-4.1-mini",
        max_tokens=2000,
        messages=[{"role": "system", "content": system},
                  {"role": "user",   "content": user}],
    )
    msg = resp.choices[0].message
    raw = (msg.content or "").strip()
    if not raw and hasattr(msg, "reasoning"):
        raw = (msg.reasoning or "").strip()
    if not raw:
        raise ValueError(f"Empty response. Finish reason: {resp.choices[0].finish_reason}")
    plan = json.loads(_strip_fences(raw))
    u    = resp.usage
    cost = u.prompt_tokens * LLM_IN + u.completion_tokens * LLM_OUT
    token_log.append({"student": student["name"], "in": u.prompt_tokens,
                       "out": u.completion_tokens, "cost": round(cost, 6), "model": "gpt-4.1-mini"})
    return plan


# ─────────────────────────────────────────────────────────────────────────────
# FLASK ROUTES
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    data = load_data()
    return render_template_string(HTML, data_json=json.dumps(data))

@app.route("/api/action-plan/<int:sid>")
def action_plan(sid):
    data = load_data()
    s = next((x for x in data["students"] if x["id"] == sid), None)
    if not s: return jsonify({"error": "Not found"}), 404
    try:
        plan = generate_action_plan(s)
        return jsonify({"plan": plan, "token_usage": token_log[-1]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/token-usage")
def token_usage():
    return jsonify({"calls": len(token_log),
                    "total_cost": round(sum(t["cost"] for t in token_log), 6),
                    "breakdown": token_log})

@app.route("/api/data")
def api_data(): return jsonify(load_data())

@app.route("/api/history")
def api_history(): return jsonify(load_history())

@app.route("/api/playlist-attempts")
def playlist_attempts():
    student_id = request.args.get("student_id", type=int)
    if not student_id: return jsonify({"error": "student_id required"}), 400
    try:
        import requests as req
        metabase_url   = os.environ.get("METABASE_URL",      "https://metabase-lierhfgoeiwhr.newtonschool.co")
        metabase_email = os.environ.get("METABASE_EMAIL",    "ashritha.k@newtonschool.co")
        metabase_pass  = os.environ.get("METABASE_PASSWORD", "H0CcPtgDa3ZN9b")
        r = req.post(f"{metabase_url}/api/session",
                     json={"username": metabase_email, "password": metabase_pass},
                     headers={"Content-Type": "application/json"}, timeout=15)
        token   = r.json().get("id") or r.json().get("token")
        headers = {"X-Metabase-Session": token, "Content-Type": "application/json"}
        resp    = req.post(f"{metabase_url}/api/card/9194/query/json",
                           headers=headers, json={}, timeout=120)
        req.delete(f"{metabase_url}/api/session", headers=headers, timeout=10)
        if resp.status_code != 200:
            return jsonify({"error": f"Card 9194 failed: {resp.status_code}", "rows": []}), 200
        raw  = resp.json()
        rows = []
        if isinstance(raw, list):
            for row in raw:
                if int(row.get("user_id") or 0) != student_id: continue
                completed_at = str(row.get("question_completed_at") or "")[:10]
                rows.append({
                    "playlist_name":   str(row.get("playlist_title") or "—"),
                    "question_title":  str(row.get("question_title")  or "—"),
                    "is_solved":       bool(row.get("is_completed")),
                    "score":           row.get("score_achieved"),
                    "max_score":       None,
                    "attempts":        1 if row.get("is_attempted") else 0,
                    "time_taken_mins": float(row.get("time_spent_mins") or 0),
                    "solved_at":       completed_at if row.get("is_completed") else "",
                    "difficulty":      str(row.get("difficulty_level") or ""),
                })
        return jsonify({"rows": rows, "count": len(rows)})
    except Exception as e:
        return jsonify({"error": str(e), "rows": []}), 200


# ─────────────────────────────────────────────────────────────────────────────
# HTML — unchanged from v5 (full frontend preserved)
# ─────────────────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NS · SM Brain Engine v6</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#07080a;--bg2:#0d1018;--bg3:#141820;--bg4:#1a1f2a;--border:#1a2030;--border2:#252d3d;--text:#ccd2e0;--muted:#465060;--accent:#4f8ef7;--red:#ef4444;--amber:#f59e0b;--green:#10b981;--teal:#14b8a6;--purple:#8b5cf6;--indigo:#6366f1;--orange:#f97316}
*{box-sizing:border-box;margin:0;padding:0}body{font-family:'IBM Plex Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;font-size:13px}
.mono{font-family:'IBM Plex Mono',monospace}
nav{background:var(--bg2);border-bottom:1px solid var(--border);padding:0 20px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:200;height:46px}
.logo{display:flex;align-items:center;gap:8px}
.logo-box{width:26px;height:26px;background:var(--accent);border-radius:5px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:10px;color:#fff;font-family:'IBM Plex Mono',monospace}
.logo-text{font-weight:600;font-size:13px}
.nav-tabs{display:flex;height:100%}
.nav-tab{padding:0 14px;font-size:11px;font-weight:500;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;display:flex;align-items:center;gap:5px;transition:all .15s}
.nav-tab:hover{color:var(--text)}.nav-tab.active{color:var(--accent);border-bottom-color:var(--accent)}
.nav-right{display:flex;gap:8px;align-items:center}
.nbtn{background:var(--bg3);border:1px solid var(--border2);color:var(--muted);font-size:10px;padding:4px 10px;border-radius:4px;cursor:pointer;font-family:'IBM Plex Mono',monospace;transition:all .15s}
.nbtn:hover{border-color:var(--accent);color:var(--text)}
.live-dot{width:6px;height:6px;border-radius:50%;background:var(--green);animation:pulse 2s infinite;display:inline-block;margin-right:5px}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.page{display:none}.page.active{display:block}
.summary-strip{display:grid;grid-template-columns:repeat(5,1fr);background:var(--border)}
.sc{background:var(--bg2);padding:10px 16px}
.sc-val{font-size:19px;font-weight:700;font-family:'IBM Plex Mono',monospace;line-height:1}
.sc-lbl{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-top:3px}
.ctrl{display:flex;gap:8px;padding:10px 20px;border-bottom:1px solid var(--border);flex-wrap:wrap;align-items:center}
.search-inp{flex:1;min-width:180px;background:var(--bg2);border:1px solid var(--border2);color:var(--text);padding:6px 11px;border-radius:5px;font-size:12px;outline:none}
.search-inp:focus{border-color:var(--accent)}
.fsel{background:var(--bg2);border:1px solid var(--border2);color:var(--text);padding:6px 10px;border-radius:5px;font-size:12px;outline:none;cursor:pointer}
.cnt-lbl{font-size:10px;color:var(--muted);margin-left:auto;font-family:'IBM Plex Mono',monospace}
.list-wrap{padding:12px 20px;display:flex;flex-direction:column;gap:6px}
.scard{background:var(--bg2);border:1px solid var(--border);border-radius:7px;display:flex;align-items:center;gap:10px;padding:10px 14px;cursor:pointer;transition:all .15s}
.scard:hover{border-color:var(--border2);background:var(--bg3)}.scard.open{border-color:var(--accent);border-bottom-left-radius:0;border-bottom-right-radius:0}
.risk-bar{width:3px;height:32px;border-radius:2px;flex-shrink:0}
.batch-tag{font-size:9px;color:var(--muted);background:var(--bg4);padding:2px 6px;border-radius:3px;white-space:nowrap;font-family:'IBM Plex Mono',monospace;flex-shrink:0}
.sinfo{flex:1;min-width:0}
.sname{font-weight:600;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.semail{font-size:10px;color:var(--muted);font-family:'IBM Plex Mono',monospace;margin-top:1px}
.sreason{font-size:11px;color:var(--muted);flex:2;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.inact-badge{font-size:9px;font-family:'IBM Plex Mono',monospace;padding:2px 6px;border-radius:3px;white-space:nowrap;flex-shrink:0}
.inact-hot{background:#1c0a0a;color:var(--red);border:1px solid #3d1010}
.inact-warn{background:#1c1308;color:var(--amber);border:1px solid #3d2808}
.inact-ok{background:var(--bg4);color:var(--muted);border:1px solid var(--border2)}
.tier-badge{padding:3px 8px;border-radius:4px;font-size:10px;font-weight:600;font-family:'IBM Plex Mono',monospace;white-space:nowrap;flex-shrink:0}
.rscore{font-family:'IBM Plex Mono',monospace;font-size:16px;font-weight:700;width:38px;text-align:right;flex-shrink:0}
.ibtn{width:24px;height:24px;border-radius:4px;border:1px solid var(--border2);background:var(--bg3);color:var(--muted);display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:12px;transition:all .15s;flex-shrink:0}
.ibtn:hover{border-color:var(--accent);color:var(--accent)}
.chev{color:var(--muted);font-size:14px;transition:transform .2s;flex-shrink:0}.scard.open .chev{transform:rotate(180deg)}
.expand{display:none;background:var(--bg3);border:1px solid var(--accent);border-top:none;border-radius:0 0 7px 7px;padding:14px;margin-top:-6px}
.expand.open{display:block}
.plan-loading{text-align:center;padding:20px;color:var(--muted);font-size:12px}
.spin{display:inline-block;width:13px;height:13px;border:2px solid var(--border2);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite;margin-right:7px;vertical-align:middle}
@keyframes spin{to{transform:rotate(360deg)}}
.plan-ctx{background:var(--bg4);border:1px solid var(--border2);border-radius:4px;padding:5px 12px;font-size:10px;font-family:'IBM Plex Mono',monospace;color:var(--muted);margin-bottom:10px}
.plan-header{display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap}
.call-lbl{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:var(--muted);font-family:'IBM Plex Mono',monospace}
.pri-tag{padding:2px 8px;border-radius:3px;font-size:10px;font-family:'IBM Plex Mono',monospace;font-weight:600}
.pri-high{background:#1c0a0a;color:var(--red);border:1px solid #3d1010}
.pri-medium{background:#1c1308;color:var(--amber);border:1px solid #3d2808}
.pri-low{background:#071a10;color:var(--green);border:1px solid #0d3520}
.inact-box{background:var(--bg4);border-radius:6px;padding:8px 12px;margin-bottom:8px;display:flex;align-items:center;gap:10px;border-left:3px solid var(--orange)}
.inact-box.ok{border-left-color:var(--green)}.inact-box.warn{border-left-color:var(--amber)}.inact-box.hot{border-left-color:var(--red)}
.inact-days{font-size:22px;font-weight:700;font-family:'IBM Plex Mono',monospace}
.inact-lbl{font-size:10px;color:var(--muted)}
.data-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-bottom:8px}
.dblk{background:var(--bg4);border-radius:6px;padding:9px 11px;border-left:3px solid var(--border2)}
.dblk.fl-ok{border-left-color:var(--green)}.dblk.fl-warn{border-left-color:var(--amber)}.dblk.fl-critical{border-left-color:var(--red)}
.blk-title{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;margin-bottom:7px;font-family:'IBM Plex Mono',monospace;display:flex;align-items:center;gap:5px}
.flag-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.fl-ok .flag-dot{background:var(--green)}.fl-warn .flag-dot{background:var(--amber)}.fl-critical .flag-dot{background:var(--red)}
.dr{display:flex;justify-content:space-between;align-items:baseline;padding:2px 0;border-bottom:1px solid var(--border);font-size:11px}
.dr:last-child{border:none}.dk{color:var(--muted);font-family:'IBM Plex Mono',monospace;font-size:10px}.dv{font-family:'IBM Plex Mono',monospace;font-weight:500}
.blist{list-style:none;margin-top:4px}
.blist li{font-size:11px;padding:2px 0;display:flex;gap:5px;font-family:'IBM Plex Mono',monospace;color:var(--text)}
.blist li::before{content:"▸";flex-shrink:0}
.blist.red li::before{color:var(--red)}.blist.amber li::before{color:var(--amber)}.blist.green li::before{color:var(--green)}.blist.blue li::before{color:var(--accent)}.blist.orange li::before{color:var(--orange)}
.p-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-bottom:8px}
.p-blk{background:var(--bg4);border-radius:5px;padding:8px 10px;border:1px solid var(--border)}
.p-blk-0{border-left:3px solid var(--red)}.p-blk-1{border-left:3px solid var(--amber)}
.p-lbl{font-size:9px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:5px;font-weight:700;font-family:'IBM Plex Mono',monospace}
.p-item{font-size:11px;padding:2px 0;font-family:'IBM Plex Mono',monospace;display:flex;gap:5px}
.p-item::before{content:"→";flex-shrink:0}
.rec-extra{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:7px}
.rec-card{background:var(--bg3);border-radius:5px;padding:7px 10px;border:1px solid var(--border)}
.rec-card-title{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);font-family:'IBM Plex Mono',monospace;margin-bottom:5px}
.sm-block{background:var(--bg4);border-radius:6px;padding:10px 12px;margin-bottom:8px;border-left:3px solid var(--purple)}
.sm-title{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:var(--purple);font-family:'IBM Plex Mono',monospace;margin-bottom:8px}
.sm-q{font-size:12px;padding:5px 0;border-bottom:1px solid var(--border);display:flex;gap:9px;align-items:flex-start}
.sm-q:last-child{border:none}
.sm-qn{color:var(--purple);font-size:10px;font-family:'IBM Plex Mono',monospace;font-weight:600;flex-shrink:0;margin-top:2px}
.imm-action{margin-top:8px;padding:7px 11px;background:var(--bg3);border-radius:4px;font-size:12px;color:var(--accent);font-family:'IBM Plex Mono',monospace;border:1px solid var(--border2)}
.token-mini{font-size:10px;color:var(--muted);font-family:'IBM Plex Mono',monospace;margin-top:8px;padding-top:8px;border-top:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
.regen-btn{background:var(--bg4);border:1px solid var(--border2);color:var(--muted);font-size:10px;padding:3px 10px;border-radius:4px;cursor:pointer;font-family:'IBM Plex Mono',monospace;transition:all .15s}
.regen-btn:hover{border-color:var(--accent);color:var(--accent)}
.overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.87);z-index:300;overflow-y:auto;padding:20px}
.overlay.open{display:block}
.modal{background:var(--bg2);border:1px solid var(--border2);border-radius:10px;max-width:940px;margin:0 auto;overflow:hidden}
.modal-hdr{padding:12px 20px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center}
.modal-title{font-size:14px;font-weight:600}.modal-sub{font-size:11px;color:var(--muted);margin-top:2px;font-family:'IBM Plex Mono',monospace}
.close-btn{background:none;border:none;color:var(--muted);font-size:22px;cursor:pointer;line-height:1;padding:0 4px}
.modal-body{padding:14px 20px}
.stats-row{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:12px}
.stat-box{background:var(--bg3);border-radius:6px;padding:10px;text-align:center;border:1px solid var(--border)}
.stat-v{font-size:16px;font-weight:700;font-family:'IBM Plex Mono',monospace}.stat-l{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-top:3px}
.mtabs{display:flex;border-bottom:1px solid var(--border);margin-bottom:12px;overflow-x:auto;gap:0}
.mtab{padding:6px 13px;font-size:11px;font-weight:500;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;transition:all .15s;white-space:nowrap;flex-shrink:0}
.mtab:hover{color:var(--text)}.mtab.active{color:var(--accent);border-bottom-color:var(--accent)}
.tpanel{display:none}.tpanel.active{display:block}
.asgn-summary{display:grid;grid-template-columns:repeat(6,1fr);gap:6px;margin-bottom:10px}
.as-box{background:var(--bg3);border-radius:5px;padding:7px;text-align:center;border:1px solid var(--border)}
.as-v{font-size:15px;font-weight:700;font-family:'IBM Plex Mono',monospace}
.as-l{font-size:9px;color:var(--muted);text-transform:uppercase;margin-top:2px}
.dtbl{width:100%;border-collapse:collapse;font-size:11px}
.dtbl th{padding:6px 10px;text-align:left;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.4px;border-bottom:1px solid var(--border);font-family:'IBM Plex Mono',monospace;cursor:pointer;user-select:none;white-space:nowrap}
.dtbl th:hover{color:var(--text)}.dtbl th.sa::after{content:" ↑";color:var(--accent)}.dtbl th.sd::after{content:" ↓";color:var(--accent)}
.dtbl td{padding:6px 10px;border-bottom:1px solid var(--border);vertical-align:middle}
.dtbl tr:last-child td{border:none}.dtbl tbody tr:hover td{background:var(--bg4)}
.sbar{display:flex;align-items:center;gap:5px}
.sbar-bg{width:40px;height:4px;background:var(--border2);border-radius:2px}.sbar-fill{height:100%;border-radius:2px}
.na-tag{font-size:9px;color:var(--orange);font-family:'IBM Plex Mono',monospace;margin-left:4px}
.quick-tag{font-size:9px;color:var(--red);font-family:'IBM Plex Mono',monospace;margin-left:4px;cursor:help}
.slow-tag{font-size:9px;color:var(--amber);font-family:'IBM Plex Mono',monospace;margin-left:4px}
.ct-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}
.ct-card{background:var(--bg3);border-radius:7px;border:1px solid var(--border);overflow:hidden}
.ct-hdr{padding:8px 12px;background:var(--bg4);border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center}
.ct-title{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;font-family:'IBM Plex Mono',monospace}
.ct-score-100{font-size:22px;font-weight:700;font-family:'IBM Plex Mono',monospace;line-height:1}
.ct-score-label{font-size:9px;color:var(--muted);font-family:'IBM Plex Mono',monospace}
.ct-body{padding:8px 12px}
.ct-row{display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid var(--border);font-size:10px;font-family:'IBM Plex Mono',monospace}
.ct-row:last-child{border:none}.ct-k{color:var(--muted)}.ct-v{font-weight:500}
.ct-sect{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--accent);margin:6px 0 3px;font-family:'IBM Plex Mono',monospace}
.ct-nh{text-align:center;padding:16px;color:var(--muted);font-size:11px;font-family:'IBM Plex Mono',monospace}
.clr-y{font-size:8px;padding:2px 5px;border-radius:2px;font-weight:700;font-family:'IBM Plex Mono',monospace;background:#071a10;color:var(--green);border:1px solid #0d3520}
.clr-n{font-size:8px;padding:2px 5px;border-radius:2px;font-weight:700;font-family:'IBM Plex Mono',monospace;background:#1c0a0a;color:var(--red);border:1px solid #3d1010}
.proj-card{background:var(--bg3);border-radius:7px;border:1px solid var(--border);padding:12px 14px}
.proj-title{font-size:13px;font-weight:600;margin-bottom:8px}
.proj-row{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border);font-size:11px}
.proj-row:last-child{border:none}.proj-k{color:var(--muted)}.proj-v{font-family:'IBM Plex Mono',monospace;font-weight:500}
.proj-note{margin-top:10px;padding:8px 10px;background:var(--bg4);border-radius:4px;font-size:11px;color:var(--amber);font-family:'IBM Plex Mono',monospace;border-left:3px solid var(--amber)}
.prog-card{background:var(--bg3);border:1px solid var(--border);border-radius:7px;padding:12px 14px;margin-bottom:10px}
.prog-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.prog-title{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);font-family:'IBM Plex Mono',monospace}
.prog-verdict{font-size:11px;font-weight:700;font-family:'IBM Plex Mono',monospace;padding:3px 10px;border-radius:4px}
.prog-verdict.good{background:#071a10;color:var(--green);border:1px solid #0d3520}
.prog-verdict.warn{background:#1c1308;color:var(--amber);border:1px solid #3d2808}
.prog-verdict.bad{background:#1c0a0a;color:var(--red);border:1px solid #3d1010}
.prog-row{display:grid;grid-template-columns:110px 72px 72px 72px 60px 60px;gap:5px;align-items:center;padding:4px 0;border-bottom:1px solid var(--border);font-size:11px;font-family:'IBM Plex Mono',monospace}
.prog-row:last-child{border:none}
.prog-metric{color:var(--muted);font-size:10px}
.prog-empty{font-size:10px;color:var(--muted);text-align:center;padding:12px 0;font-family:'IBM Plex Mono',monospace}
.sess-empty{text-align:center;padding:20px;color:var(--muted);font-size:12px;font-family:'IBM Plex Mono',monospace}
.batch-page{padding:18px 20px}
.batch-hdr{font-size:17px;font-weight:600;margin-bottom:3px}
.batch-sub{font-size:12px;color:var(--muted);margin-bottom:18px}
.bc-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-bottom:18px}
.bc-card{background:var(--bg2);border:1px solid var(--border);border-radius:8px;overflow:hidden}
.bc-hdr{padding:10px 14px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center}
.bc-name{font-size:13px;font-weight:600}.bc-meta{font-size:10px;color:var(--muted);font-family:'IBM Plex Mono',monospace;background:var(--bg4);padding:2px 7px;border-radius:3px}
.bc-body{padding:12px 14px}
.bc-bar{display:flex;align-items:center;gap:9px;margin-bottom:7px}
.bc-bar-lbl{font-size:10px;color:var(--muted);width:78px;flex-shrink:0}
.bc-bar-bg{flex:1;height:7px;background:var(--border2);border-radius:3px}
.bc-bar-fill{height:100%;border-radius:3px}
.bc-bar-val{font-size:10px;font-family:'IBM Plex Mono',monospace;width:32px;text-align:right;flex-shrink:0}
.bc-badges{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:12px;padding-top:10px;border-top:1px solid var(--border)}
.bc-badge{text-align:center}
.bc-bv{font-size:16px;font-weight:700;font-family:'IBM Plex Mono',monospace}
.bc-bl{font-size:9px;color:var(--muted);margin-top:2px}
.cmp-section{background:var(--bg2);border:1px solid var(--border);border-radius:7px;overflow:hidden;margin-bottom:14px}
.cmp-hdr{padding:10px 14px;border-bottom:1px solid var(--border);font-size:13px;font-weight:600;display:flex;align-items:center;gap:7px}
.cmp-tbl{width:100%;border-collapse:collapse;font-size:12px}
.cmp-tbl th{padding:7px 12px;text-align:center;color:var(--muted);font-size:10px;text-transform:uppercase;border-bottom:1px solid var(--border);font-family:'IBM Plex Mono',monospace;background:var(--bg3)}
.cmp-tbl th:first-child{text-align:left}
.cmp-tbl td{padding:7px 12px;text-align:center;border-bottom:1px solid var(--border);font-family:'IBM Plex Mono',monospace}
.cmp-tbl td:first-child{text-align:left;font-family:'IBM Plex Sans',sans-serif;color:var(--muted);font-size:11px}
.cmp-tbl tr:last-child td{border:none}.cmp-tbl tbody tr:hover td{background:var(--bg4)}
.best{font-weight:700;color:var(--green)}.worst{color:var(--red)}
.empty{text-align:center;padding:50px;color:var(--muted)}
.frow{display:flex;gap:7px;margin-bottom:10px;flex-wrap:wrap;align-items:center}
.frow label{font-size:10px;color:var(--muted);font-family:'IBM Plex Mono',monospace}
.frow input,.frow select{background:var(--bg3);border:1px solid var(--border2);color:var(--text);padding:4px 8px;border-radius:4px;font-size:11px;outline:none}
.frow input:focus,.frow select:focus{border-color:var(--accent)}
.reset-btn{background:var(--bg3);border:1px solid var(--border2);color:var(--muted);font-size:10px;padding:4px 9px;border-radius:4px;cursor:pointer;font-family:'IBM Plex Mono',monospace}
.reset-btn:hover{border-color:var(--accent);color:var(--text)}
.row-count{font-size:10px;color:var(--muted);font-family:'IBM Plex Mono',monospace;margin-left:auto}
</style>
</head>
<body>
<nav>
  <div class="logo">
    <div class="logo-box">NS</div>
    <span class="logo-text">SM Brain Engine</span>
    <span style="font-size:9px;color:var(--muted);margin-left:4px;font-family:'IBM Plex Mono',monospace">v6</span>
  </div>
  <div class="nav-tabs">
    <div class="nav-tab active" onclick="showPage('students',this)">🎓 Students</div>
    <div class="nav-tab" onclick="showPage('batch',this)">📊 Batch Analytics</div>
  </div>
  <div class="nav-right">
    <button class="nbtn" onclick="openTokenModal()">💰 Token Cost</button>
    <span style="font-size:11px;color:var(--muted)"><span class="live-dot"></span>Live</span>
  </div>
</nav>

<div id="page-students" class="page active">
  <div class="summary-strip" id="strip"></div>
  <div class="ctrl">
    <input class="search-inp" id="searchBox" placeholder="Search name, email…" oninput="filter()">
    <select class="fsel" id="batchF" onchange="filter()"><option value="">All Batches</option></select>
    <select class="fsel" id="moduleF" onchange="filter()">
      <option value="">All Modules</option>
      <option value="spreadsheets">Spreadsheets</option>
      <option value="sql">SQL</option>
    </select>
    <select class="fsel" id="tierF" onchange="filter()">
      <option value="">All Tiers</option>
      <option>High Risk</option><option>Medium Risk</option><option>Low Risk</option><option>Strong</option>
    </select>
    <select class="fsel" id="inactF" onchange="filter()">
      <option value="">All Activity</option>
      <option value="hot">Inactive 14+ days</option>
      <option value="warn">Inactive 7+ days</option>
    </select>
    <span class="cnt-lbl" id="cntLbl"></span>
  </div>
  <div class="list-wrap" id="studentList"></div>
</div>

<div id="page-batch" class="page">
  <div class="batch-page" id="batchContent"></div>
</div>

<div class="overlay" id="infoModal" onclick="closeInfo(event)">
  <div class="modal">
    <div class="modal-hdr">
      <div><div class="modal-title" id="infoTitle"></div><div class="modal-sub" id="infoSub"></div></div>
      <button class="close-btn" onclick="closeInfo()">×</button>
    </div>
    <div class="modal-body" id="infoBody"></div>
  </div>
</div>

<div class="overlay" id="tokenModal" onclick="closeToken(event)">
  <div class="modal" style="max-width:620px">
    <div class="modal-hdr">
      <div><div class="modal-title">Token Usage & Cost</div><div class="modal-sub">GPT-4.1 Mini · $0.40/1M in · $1.60/1M out</div></div>
      <button class="close-btn" onclick="closeToken()">×</button>
    </div>
    <div class="modal-body" id="tokenBody">Loading…</div>
  </div>
</div>

<script>
const DATA  = {{ data_json|safe }};
const STUDS = DATA.students||[];
let filtered=[], expandedId=null, planCache={};
let asgnSort={key:'topic',dir:1};
let _curSt=null, _plData=[], _lecFeedback=[];

function rc(r){return r>=75?'var(--red)':r>=55?'var(--amber)':r>=35?'var(--green)':'var(--teal)'}
function bc(p){return p>=75?'var(--green)':p>=50?'var(--amber)':'var(--red)'}
function ts(t){if(t==='High Risk')return 'background:#1c0a0a;color:var(--red);border:1px solid #3d1010';if(t==='Medium Risk')return 'background:#1c1308;color:var(--amber);border:1px solid #3d2808';if(t==='Low Risk')return 'background:#071a10;color:var(--green);border:1px solid #0d3520';return 'background:#061416;color:var(--teal);border:1px solid #0d2e30'}
function rsc(t){if(t==='High Risk')return 'var(--red)';if(t==='Medium Risk')return 'var(--amber)';if(t==='Low Risk')return 'var(--green)';return 'var(--teal)'}
function inactClass(d){if(d>=14)return 'hot';if(d>=7)return 'warn';return 'ok'}
function inactBadge(d){if(d>=999)return 'Never active';if(d>=14)return d+'d inactive';if(d>=7)return d+'d ago';return d===0?'Active today':d+'d ago'}
function getMod(s){return s.mods?.SQL||s.mods?.Spreadsheets||{}}

function showPage(id,el){
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(t=>t.classList.remove('active'));
  document.getElementById('page-'+id).classList.add('active');el.classList.add('active');
  if(id==='batch')renderBatch();
}

function initFilters(){
  const batches=[...new Set(STUDS.map(s=>s.batch))];
  const sel=document.getElementById('batchF');
  batches.forEach(b=>{const o=document.createElement('option');o.value=b;o.textContent=b.replace(' 2026','');sel.appendChild(o);});
}

function buildStrip(arr){
  const c={total:arr.length,high:0,med:0,low:0,str:0};
  arr.forEach(s=>{if(s.tier==='High Risk')c.high++;else if(s.tier==='Medium Risk')c.med++;else if(s.tier==='Low Risk')c.low++;else c.str++;});
  document.getElementById('strip').innerHTML=`
    <div class="sc"><div class="sc-val">${c.total}</div><div class="sc-lbl">Total</div></div>
    <div class="sc"><div class="sc-val" style="color:var(--red)">${c.high}</div><div class="sc-lbl">High Risk</div></div>
    <div class="sc"><div class="sc-val" style="color:var(--amber)">${c.med}</div><div class="sc-lbl">Medium</div></div>
    <div class="sc"><div class="sc-val" style="color:var(--green)">${c.low}</div><div class="sc-lbl">Low Risk</div></div>
    <div class="sc"><div class="sc-val" style="color:var(--teal)">${c.str}</div><div class="sc-lbl">Strong</div></div>`;
}

function filter(){
  const q=(document.getElementById('searchBox').value||'').toLowerCase();
  const batch=document.getElementById('batchF').value;
  const modF=document.getElementById('moduleF').value;
  const tier=document.getElementById('tierF').value;
  const inact=document.getElementById('inactF').value;
  filtered=STUDS.filter(s=>{
    if(q&&!s.name.toLowerCase().includes(q)&&!s.email.toLowerCase().includes(q))return false;
    if(batch&&s.batch!==batch)return false;
    if(modF&&s.module_type!==modF)return false;
    if(tier&&s.tier!==tier)return false;
    if(inact==='hot'&&(s.days_inactive||0)<14)return false;
    if(inact==='warn'&&(s.days_inactive||0)<7)return false;
    return true;
  });
  filtered.sort((a,b)=>b.risk-a.risk);
  document.getElementById('cntLbl').textContent=filtered.length+' students';
  buildStrip(filtered);
  renderList();
}

let HISTORY=[];
fetch('/api/history').then(r=>r.json()).then(d=>{HISTORY=d||[];}).catch(()=>{});

function renderProgressCard(sid){
  const id=String(sid);
  const snaps=HISTORY.map(h=>({date:h.date,data:h.students?.[id]||null})).filter(s=>s.data);
  if(!snaps.length)return`<div class="prog-card"><div class="prog-empty">📈 No history yet — will appear after first refresh</div></div>`;
  const curr=snaps[snaps.length-1].data;
  const currDate=new Date(snaps[snaps.length-1].date);
  function findSnap(days){let best=null,bestDiff=Infinity;for(let i=0;i<snaps.length-1;i++){const d=Math.round((currDate-new Date(snaps[i].date))/(1000*60*60*24));if(Math.abs(d-days)<bestDiff){bestDiff=Math.abs(d-days);best=snaps[i];}}return best&&Math.round((currDate-new Date(best.date))/(1000*60*60*24))>0?best:null;}
  const snap10=findSnap(10),snap5=findSnap(5);
  const p10=snap10?snap10.data:null,p5=snap5?snap5.data:null;
  const l10=snap10?snap10.date.slice(5)+'('+Math.round((currDate-new Date(snap10.date))/(1000*60*60*24))+'d)':'—';
  const l5=snap5?snap5.date.slice(5)+'('+Math.round((currDate-new Date(snap5.date))/(1000*60*60*24))+'d)':'—';
  const metrics=[
    {key:'risk',label:'Risk Score',fmt:v=>v,invert:true,good:v=>v<0,fd:d=>(d>0?'+':'')+d},
    {key:'att',label:'Attendance',fmt:v=>v+'%',invert:false,good:v=>v>0,fd:d=>(d>0?'+':'')+d+'%'},
    {key:'asgn',label:'Assignment',fmt:v=>v+'%',invert:false,good:v=>v>0,fd:d=>(d>0?'+':'')+d+'%'},
    {key:'mc',label:'MC Best',fmt:v=>v>0?v+'/100':'—',invert:false,good:v=>v>0,fd:d=>(d>0?'+':'')+d},
    {key:'ta',label:'TA Sessions',fmt:v=>v,invert:false,good:v=>v>0,fd:d=>(d>0?'+':'')+d},
    {key:'inactive',label:'Days Inact',fmt:v=>v+'d',invert:true,good:v=>v<0,fd:d=>(d>0?'+':'')+d+'d'},
  ];
  function deltaCell(base,curr2,m){if(!base)return`<span style="color:var(--muted)">—</span>`;const bv=parseFloat(base[m.key]||0),cv2=parseFloat(curr2[m.key]||0),d=Math.round((cv2-bv)*10)/10;if(d===0)return`<span style="color:var(--muted)">→</span>`;const good=m.good(d),col=good?'var(--green)':'var(--red)',arr=d>0?(m.invert?'↓':'↑'):(m.invert?'↑':'↓');return`<span style="color:${col};font-weight:600">${arr} ${m.fd(d)}</span>`;}
  let improving=0,declining=0;
  const rows=metrics.map(m=>{const cv=parseFloat(curr[m.key]||0),ref=p5||p10;if(ref){const rv=parseFloat(ref[m.key]||0),d=Math.round((cv-rv)*10)/10;if(d!==0){m.good(d)?improving++:declining++;}}return`<div class="prog-row"><span class="prog-metric">${m.label}</span><span style="color:var(--muted)">${p10?m.fmt(parseFloat(p10[m.key]||0)):'—'}</span><span style="color:var(--muted)">${p5?m.fmt(parseFloat(p5[m.key]||0)):'—'}</span><span style="font-weight:700">${m.fmt(cv)}</span>${deltaCell(p10,curr,m)}${deltaCell(p5,curr,m)}</div>`;}).join('');
  let verdict,vclass;
  if(!p5&&!p10){verdict='📊 Baseline';vclass='warn';}else if(improving>=4){verdict='✓ Progressing well';vclass='good';}else if(declining>=4){verdict='✗ Declining';vclass='bad';}else if(improving>declining){verdict='↑ Mostly improving';vclass='good';}else if(declining>improving){verdict='↓ More declining';vclass='bad';}else{verdict='→ Stagnating';vclass='warn';}
  return`<div class="prog-card"><div class="prog-header"><div><div class="prog-title">📈 Progress Tracker · ${snaps.length} snapshots</div></div><div class="prog-verdict ${vclass}">${verdict}</div></div><div class="prog-row" style="font-size:9px;color:var(--muted);border-bottom:1px solid var(--border);padding-bottom:4px;margin-bottom:2px"><span>METRIC</span><span title="${l10}">~10d ago</span><span title="${l5}">~5d ago</span><span>NOW</span><span>Δ 10d</span><span>Δ 5d</span></div>${rows}</div>`;
}

function renderList(){
  const el=document.getElementById('studentList');
  if(!filtered.length){el.innerHTML='<div class="empty">No students match filters</div>';return;}
  el.innerHTML=filtered.map(s=>{
    const mod=getMod(s);
    const ph=mod.current_phase||mod.sql_phase||'?';
    const cl=mod.current_class||'?';
    const di=s.days_inactive||0;
    const ic=inactClass(di);
    const modTag=s.module_type==='sql'?'SQL':'SS';
    return`<div>
      <div class="scard" id="card-${s.id}" onclick="toggleCard(${s.id})">
        <div class="risk-bar" style="background:${rsc(s.tier)}"></div>
        <div class="batch-tag">${s.batch.replace(' 2026','')}</div>
        <div class="sinfo"><div class="sname">${s.name}</div><div class="semail">${s.email}</div></div>
        <div class="sreason">${s.reason||''}</div>
        <div class="inact-badge inact-${ic}">${inactBadge(di)}</div>
        <span style="font-size:9px;color:var(--muted);font-family:'IBM Plex Mono',monospace;background:var(--bg4);padding:2px 6px;border-radius:3px;white-space:nowrap">${modTag} Ph${ph} C${cl}</span>
        <span class="tier-badge" style="${ts(s.tier)}">${s.tier}</span>
        <div class="rscore" style="color:${rc(s.risk)}">${s.risk}</div>
        <div class="ibtn" onclick="openInfo(event,${s.id})">ⓘ</div>
        <div class="chev">⌄</div>
      </div>
      <div class="expand" id="panel-${s.id}">
        <div class="plan-loading" id="ld-${s.id}"><span class="spin"></span>Generating call brief…</div>
        <div id="plan-${s.id}" style="display:none"></div>
      </div>
    </div>`;
  }).join('');
}

function toggleCard(id){
  const card=document.getElementById('card-'+id),panel=document.getElementById('panel-'+id);
  if(expandedId===id){card.classList.remove('open');panel.classList.remove('open');expandedId=null;return;}
  if(expandedId!=null){document.getElementById('card-'+expandedId)?.classList.remove('open');document.getElementById('panel-'+expandedId)?.classList.remove('open');}
  card.classList.add('open');panel.classList.add('open');expandedId=id;
  if(planCache[id])showPlan(id,planCache[id].plan,planCache[id].tok);else fetchPlan(id);
}

async function fetchPlan(id){
  try{
    const r=await fetch('/api/action-plan/'+id);
    const d=await r.json();
    if(d.error)throw new Error(d.error);
    planCache[id]={plan:d.plan,tok:d.token_usage};
    showPlan(id,d.plan,d.token_usage);
  }catch(e){const _ld=document.getElementById('ld-'+id);if(_ld){_ld.style.display='block';_ld.innerHTML=`<div style="color:var(--red);padding:8px;font-family:monospace;font-size:12px">Error: ${e.message}</div>`;}}
}

async function regenPlan(id){
  delete planCache[id];
  const ld=document.getElementById('ld-'+id);
  ld.innerHTML='<span class="spin"></span>Regenerating…';ld.style.display='block';
  document.getElementById('plan-'+id).style.display='none';
  await fetchPlan(id);
}

function showPlan(id,plan,tok){
  document.getElementById('ld-'+id).style.display='none';
  const el=document.getElementById('plan-'+id);el.style.display='block';
  const s=STUDS.find(x=>x.id===id)||{};
  const di=s.days_inactive||0;
  const mod=getMod(s);
  const A=plan.attendance||{},G=plan.assignment||{},M=plan.mc_score||{},PJ=plan.project||{},R=plan.recommendation||{},Q=plan.sm_questions||{};
  const fl=f=>`fl-${f||'ok'}`;
  const ic=inactClass(di);
  const icColor=ic==='hot'?'var(--red)':ic==='warn'?'var(--amber)':'var(--green)';
  const inactBlock=`<div class="inact-box ${ic}" style="margin-bottom:8px">
    <div class="inact-days" style="color:${icColor}">${di>=999?'—':di+'d'}</div>
    <div>
      <div style="font-size:11px;font-weight:600;color:${icColor}">${di>=999?'Never active':di===0?'Active today':di+' days since last activity'}</div>
      <div class="inact-lbl">Last solve: ${mod.last_solve||'—'} &nbsp;|&nbsp; Assignment: ${s.avg_asgn||0}% (${s.asgn_solved||0}/${s.asgn_total||0} Qs) &nbsp;|&nbsp; Attendance: ${s.avg_att||0}%</div>
    </div>
  </div>`;
  const attMissed=A.missed_count||0,attFlag=A.flag||'ok';
  const attColor=attFlag==='critical'?'var(--red)':attFlag==='warn'?'var(--amber)':'var(--green)';
  const showFullAtt=attFlag!=='ok'||attMissed>0;
  const attBlock=showFullAtt
    ?`<div class="dblk ${fl(attFlag)}"><div class="blk-title"><span class="flag-dot"></span>📅 ATTENDANCE</div><div class="dr"><span class="dk">Overall</span><span class="dv" style="color:${attColor}">${s.avg_att||0}%</span></div><div class="dr"><span class="dk">Missed</span><span class="dv" style="color:${attColor}">${attMissed} classes</span></div>${A.note?`<div class="dr"><span class="dk">Note</span><span class="dv" style="font-size:10px">${A.note}</span></div>`:''}</div>`
    :`<div class="dblk fl-ok" style="display:flex;align-items:center;gap:10px;padding:8px 12px"><span class="flag-dot" style="background:var(--green);flex-shrink:0"></span><span style="font-size:10px;font-family:'IBM Plex Mono',monospace;color:var(--muted)">📅 ATTENDANCE</span><span style="font-size:14px;font-weight:700;font-family:'IBM Plex Mono',monospace;color:var(--green)">${s.avg_att||0}%</span><span style="font-size:10px;color:var(--green)">— No concerns</span>${attMissed>0?`<span style="font-size:10px;color:var(--amber);margin-left:auto">${attMissed} missed</span>`:''}</div>`;
  const uns=G.unsolved_topics||[],na=G.not_attempted_topics||[];
  const asgnBlock=`<div class="dblk ${fl(G.flag)}"><div class="blk-title"><span class="flag-dot"></span>📝 ASSIGNMENT</div><div class="dr"><span class="dk">Completion</span><span class="dv">${G.completion||'—'}</span></div>${uns.length?`<div style="margin-top:5px"><div style="font-size:9px;color:var(--muted);margin-bottom:2px;font-family:'IBM Plex Mono',monospace">UNSOLVED</div><ul class="blist red">${uns.map(t=>`<li>${t}</li>`).join('')}</ul></div>`:''}${na.length?`<div style="margin-top:5px"><div style="font-size:9px;color:var(--muted);margin-bottom:2px;font-family:'IBM Plex Mono',monospace">NOT ATTEMPTED</div><ul class="blist amber">${na.map(t=>`<li>${t}</li>`).join('')}</ul></div>`:''}<div style="margin-top:4px;font-size:10px;font-family:'IBM Plex Mono',monospace;color:var(--muted)">${G.ta_recommendation||''}</div></div>`;
  const pj_col=PJ.flag==='ok'?'var(--green)':PJ.flag==='warn'?'var(--amber)':'var(--red)';
  const projData=mod.project;
  const projHist=projData?.submission_history||[];
  const projHistHtml=projHist.length?projHist.map(h=>{const sc=h.marks!=null?h.marks:null;const scCol=sc==null?'var(--muted)':sc>=8?'var(--green)':sc>=5?'var(--amber)':'var(--red)';return`<div class="dr"><span class="dk">Sub ${h.submission} — ${h.date||''}</span><span class="dv" style="color:${scCol};font-size:13px;font-weight:700">${sc!=null?sc+'/10':'Pending'}</span></div>`;}).join(''):'';
  const projBlock=`<div class="dblk ${fl(PJ.flag)}"><div class="blk-title"><span class="flag-dot"></span>📁 PROJECT</div>${projHist.length?projHistHtml:`<div class="dr"><span class="dk">Status</span><span class="dv" style="color:${pj_col};font-size:10px">${PJ.status||'—'}</span></div>`}${projHist.length&&projData?.feedback_count?`<div class="dr"><span class="dk">Feedbacks</span><span class="dv" style="color:var(--amber)">${projData.feedback_count} received — last ${projData.last_feedback||'?'}</span></div>`:''}${PJ.action?`<div style="margin-top:5px;padding:5px 8px;background:var(--bg3);border-radius:3px;font-size:10px;font-family:'IBM Plex Mono',monospace;color:var(--amber);border-left:2px solid var(--amber)">▶ ${PJ.action}</div>`:''}</div>`;
  const mcBlock=`<div class="dblk ${fl(M.flag)}"><div class="blk-title"><span class="flag-dot"></span>🏆 MC CONTESTS (normalized /100, clearance=64)</div><div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:10px"><div><div class="dk">Mid MC</div><div class="dv" style="font-size:13px;color:var(--muted)">${M.mid_mc||'—'}</div></div><div><div class="dk">MC Attempt 1</div><div class="dv" style="font-size:13px;color:var(--muted)">${M.mc1||'—'}</div></div><div><div class="dk">MC Attempt 2</div><div class="dv" style="font-size:13px;color:var(--muted)">${M.mc2||'—'}</div></div><div><div class="dk">Next Action</div><div class="dv" style="font-size:10px;color:var(--amber)">${M.next_action||'—'}</div></div></div></div>`;
  const p0=R.p0||{},p1=R.p1||{};
  const atop=R.assignment_topics_to_solve||[],plrec=R.playlist_recommendation||[];
  const recBlock=`<div class="dblk" style="grid-column:1/-1;border-left-color:var(--accent);background:var(--bg4);border-radius:6px;padding:9px 11px"><div class="blk-title" style="color:var(--accent)">▶ RECOMMENDATION</div><div class="p-grid"><div class="p-blk p-blk-0"><div class="p-lbl" style="color:var(--red)">P0 — ${p0.label||'Critical'}</div>${(p0.items||[]).map(i=>`<div class="p-item" style="color:var(--red)">${i}</div>`).join('')}</div><div class="p-blk p-blk-1"><div class="p-lbl" style="color:var(--amber)">P1 — ${p1.label||'Important'}</div>${(p1.items||[]).map(i=>`<div class="p-item" style="color:var(--amber)">${i}</div>`).join('')}</div></div>${(atop.length||plrec.length)?`<div class="rec-extra">${atop.length?`<div class="rec-card"><div class="rec-card-title">📝 Assignments → % Gain</div><ul class="blist blue">${atop.map(t=>`<li>${t}</li>`).join('')}</ul></div>`:''} ${plrec.length?`<div class="rec-card"><div class="rec-card-title">🎵 Recommended Playlists</div><ul class="blist green">${plrec.map(t=>`<li>${t}</li>`).join('')}</ul></div>`:''}</div>`:''} ${R.immediate_action?`<div class="imm-action">▶ ${R.immediate_action}</div>`:''}</div>`;
  const qKeys=Object.keys(Q).filter(k=>Q[k]);
  const smBlock=qKeys.length?`<div class="sm-block"><div class="sm-title">💬 SM Call Questions</div>${qKeys.map((k,i)=>`<div class="sm-q"><span class="sm-qn">Q${i+1}</span><span>${Q[k]}</span></div>`).join('')}</div>`:'';
  el.innerHTML=`${renderProgressCard(id)}<div class="plan-ctx">${plan.phase_context||''}</div><div class="plan-header"><span class="call-lbl">${plan.call_type||'SM Call'}</span><span class="pri-tag pri-${plan.priority||'medium'}">Priority: ${plan.priority||'—'}</span></div>${inactBlock}<div class="data-grid" style="grid-template-columns:1fr 1fr">${attBlock}${asgnBlock}${mcBlock}${projBlock}</div>${recBlock}${smBlock}<div class="token-mini"><span>${tok?`${tok.model||'GPT-5'} · ${tok.in} in + ${tok.out} out · $${tok.cost}`:''}</span><button class="regen-btn" onclick="regenPlan(${id})">↻ Regenerate</button></div>`;
}

function openInfo(e,id){
  e.stopPropagation();
  const s=STUDS.find(x=>x.id===id);if(!s)return;
  _curSt=s;
  const mod=getMod(s);
  _lecFeedback=mod.lec_feedback||[];
  _plData=(mod.playlist_detail||[]).map(p=>({playlist_title:p.playlist_title||p.playlist_name||'—',total_qs:p.total_questions||0,solved:p.solved||0,attempted:p.attempted||0,not_attempted:p.not_attempted||0,completion_pct:p.completion_pct||0,avg_time_mins:p.avg_time_mins||null,last_activity:(p.last_solved_date||'').slice(0,10)||null,questions:p.questions||[]}));
  document.getElementById('infoTitle').textContent=s.name;
  document.getElementById('infoSub').textContent=s.email+' · '+s.batch;
  const mc=s.avg_mc||0,di=s.days_inactive||0;
  const allQ=[...(mod.asgn_detail||[]).map(r=>({...r,_t:'Learn'})),...(mod.app_detail||[]).map(r=>({...r,_t:'App'}))];
  const topics=[...new Set(allQ.map(d=>d.topic||''))].filter(Boolean).sort();
  document.getElementById('infoBody').innerHTML=`
    <div class="stats-row">
      <div class="stat-box"><div class="stat-v" style="color:${rc(s.risk)}">${s.risk}</div><div class="stat-l">Risk Score</div></div>
      <div class="stat-box"><div class="stat-v" style="color:${bc(s.avg_att)}">${s.avg_att}%</div><div class="stat-l">Attendance</div></div>
      <div class="stat-box"><div class="stat-v" style="color:${bc(s.avg_asgn)}">${s.avg_asgn}%</div><div class="stat-l">Assignment</div></div>
      <div class="stat-box"><div class="stat-v" style="color:${mc>=64?'var(--green)':mc>0?'var(--amber)':'var(--muted)'}">${mc>0?mc+'/100':'—'}</div><div class="stat-l">MC Best</div></div>
      <div class="stat-box"><div class="stat-v" style="color:${di>=14?'var(--red)':di>=7?'var(--amber)':'var(--green)'}">${di>=999?'∞':di+'d'}</div><div class="stat-l">Days Inactive</div></div>
    </div>
    <div class="mtabs">
      <div class="mtab active" onclick="switchTab('asgn',this)">📝 Assignment</div>
      <div class="mtab" onclick="switchTab('playlist',this)">🎵 Playlist</div>
      <div class="mtab" onclick="switchTab('lec',this)">📅 Lectures</div>
      <div class="mtab" onclick="switchTab('ta',this)">🧑‍🏫 TA Sessions</div>
      <div class="mtab" onclick="switchTab('mentor',this)">🤝 Mentor</div>
      <div class="mtab" onclick="switchTab('contests',this)">🏆 Contests</div>
      <div class="mtab" onclick="switchTab('project',this)">📁 Project</div>
    </div>
    <div class="tpanel active" id="tab-asgn">
      <div class="frow">
        <label>Type</label>
        <select id="qType" onchange="renderAsgn()"><option value="all">All</option><option value="Learn">📘 Learning</option><option value="App">📝 Application</option></select>
        <select id="qTopic" onchange="renderAsgn()"><option value="">All Topics</option>${topics.map(t=>`<option>${t}</option>`).join('')}</select>
        <label>From</label><input type="date" id="qFrom" onchange="renderAsgn()">
        <label>To</label><input type="date" id="qTo" onchange="renderAsgn()">
        <button class="reset-btn" onclick="resetAsgnFilters()">Reset</button>
        <span class="row-count" id="asgnCount"></span>
      </div>
      <div class="asgn-summary" id="asgnSummary"></div>
      <table class="dtbl"><thead><tr>
        <th onclick="sortA('topic',this)" class="sa">Topic</th>
        <th onclick="sortA('total_released',this)">Released</th>
        <th onclick="sortA('attempted',this)">Attempted</th>
        <th onclick="sortA('solved',this)">Solved</th>
        <th onclick="sortA('avg_time_mins',this)">Avg Time</th>
        <th onclick="sortA('last_solved_date',this)">Last Solved</th>
      </tr></thead><tbody id="asgnBody"></tbody></table>
    </div>
    <div class="tpanel" id="tab-playlist">
      <div class="frow">
        <select id="plFilter" onchange="renderPlaylistTab()"><option value="">All Playlists</option></select>
        <select id="plStatus" onchange="renderPlaylistTab()"><option value="">All Status</option><option value="solved">Completed</option><option value="unsolved">In Progress</option><option value="not_attempted">Not Started</option></select>
        <button class="reset-btn" onclick="resetPlFilters()">Reset</button>
        <span class="row-count" id="plCount"></span>
      </div>
      <div class="asgn-summary" id="plSummary"></div>
      <table class="dtbl"><thead><tr><th>PLAYLIST</th><th>TOTAL Qs</th><th>SOLVED</th><th>COMPLETION</th><th>AVG TIME</th><th>LAST SOLVED</th></tr></thead>
      <tbody id="plBody"><tr><td colspan="6" style="text-align:center;color:var(--muted);padding:20px">Loading…</td></tr></tbody></table>
    </div>
    <div class="tpanel" id="tab-lec">
      <table class="dtbl"><thead><tr><th>Date</th><th>Lecture</th><th>Type</th><th>Watch %</th><th>Feedback</th></tr></thead>
      <tbody>${(mod.lectures||[]).length?(mod.lectures||[]).map(l=>`<tr><td class="mono">${(l.date||'').slice(0,10)}</td><td style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${l.title}</td><td style="font-size:11px;font-weight:600;color:${l.type==='Live'?'var(--green)':l.type==='Absent'?'var(--red)':'var(--amber)'}">${l.type}</td><td class="mono" style="color:${l.attended?'var(--green)':l.watch_pct>0&&l.watch_pct>=40?'var(--amber)':'var(--red)'}">${l.watch_pct?l.watch_pct+'%':'—'}</td><td><span style="color:var(--muted);font-size:10px">—</span></td></tr>`).join(''):'<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:20px">No lecture data</td></tr>'}</tbody></table>
    </div>
    <div class="tpanel" id="tab-ta">${renderSessions(mod.ta_sessions||[],'TA Doubt Sessions')}</div>
    <div class="tpanel" id="tab-mentor">${renderSessions(mod.mentor_sessions||[],'Mentor Connect Sessions',['module','feedback'])}</div>
    <div class="tpanel" id="tab-contests">${renderContests(mod.contests||{})}</div>
    <div class="tpanel" id="tab-project">${renderProject(mod.project)}</div>`;
  renderAsgn();renderPlaylistTab();
  document.getElementById('infoModal').classList.add('open');
}

function resetAsgnFilters(){document.getElementById('qType').value='all';document.getElementById('qTopic').value='';document.getElementById('qFrom').value='';document.getElementById('qTo').value='';renderAsgn();}

function renderPlaylistTab(){
  const plF=document.getElementById('plFilter')?.value||'';
  const stF=document.getElementById('plStatus')?.value||'';
  const pf=document.getElementById('plFilter');
  if(pf&&pf.options.length<=1&&_plData.length){const names=[...new Set(_plData.map(r=>r.playlist_title).filter(Boolean))].sort();names.forEach(n=>{const o=document.createElement('option');o.value=n;o.textContent=n;pf.appendChild(o);});}
  let rows=[..._plData];
  if(plF)rows=rows.filter(r=>r.playlist_title===plF);
  if(stF==='solved')rows=rows.filter(r=>(r.completion_pct||0)===100);
  else if(stF==='unsolved')rows=rows.filter(r=>(r.completion_pct||0)>0&&(r.completion_pct||0)<100);
  else if(stF==='not_attempted')rows=rows.filter(r=>!(r.completion_pct||0));
  const totQ=rows.reduce((a,r)=>a+(r.total_qs||0),0),solQ=rows.reduce((a,r)=>a+(r.solved||0),0);
  const pct=totQ>0?Math.round(solQ/totQ*100):0;
  const times=rows.filter(r=>r.avg_time_mins>0).map(r=>r.avg_time_mins);
  const avgT=times.length?Math.round(times.reduce((a,b)=>a+b,0)/times.length):null;
  const notAtt=rows.filter(r=>!(r.completion_pct||0)).length;
  const plCountEl=document.getElementById('plCount');if(plCountEl)plCountEl.textContent=rows.length+' playlists';
  const plSumEl=document.getElementById('plSummary');
  if(plSumEl)plSumEl.innerHTML=`<div class="as-box"><div class="as-v" style="color:${pct>=75?'var(--green)':pct>=40?'var(--amber)':'var(--red)'}">${solQ}/${totQ}</div><div class="as-l">Solved</div></div><div class="as-box"><div class="as-v" style="color:${pct>=75?'var(--green)':pct>=40?'var(--amber)':'var(--red)'}">${pct}%</div><div class="as-l">Completion</div></div><div class="as-box"><div class="as-v" style="color:var(--muted)">${avgT?avgT+'m':'—'}</div><div class="as-l">Avg Time</div></div><div class="as-box"><div class="as-v" style="color:${notAtt>0?'var(--amber)':'var(--green)'}">${notAtt}</div><div class="as-l">Not Started</div></div>`;
  const body=document.getElementById('plBody');if(!body)return;
  if(!rows.length){body.innerHTML=`<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:18px">${_plData.length===0?'No playlist data':'No playlists match filter'}</td></tr>`;return;}
  body.innerHTML=rows.map(r=>{const pct2=r.completion_pct||0,col=pct2===100?'var(--green)':pct2>0?'var(--amber)':'var(--red)';const bar=`<div style="display:flex;align-items:center;gap:6px"><div style="width:70px;height:5px;background:var(--border);border-radius:3px"><div style="width:${Math.min(pct2,100)}%;height:100%;background:${col};border-radius:3px"></div></div><span style="color:${col};font-size:11px">${r.solved||0}/${r.total_qs||0}</span></div>`;return`<tr><td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.playlist_title||'—'}</td><td class="mono">${r.total_qs||0}</td><td>${bar}</td><td class="mono" style="color:${col}">${Math.round(pct2)}%</td><td class="mono" style="color:var(--muted)">${r.avg_time_mins?Math.round(r.avg_time_mins*10)/10+'m':'—'}</td><td class="mono" style="color:var(--muted)">${r.last_activity||'—'}</td></tr>`;}).join('');
}
function resetPlFilters(){document.getElementById('plFilter').value='';document.getElementById('plStatus').value='';renderPlaylistTab();}

function renderSessions(sess,label,hide=[]){
  if(!sess||!sess.length)return`<div class="sess-empty">No ${label} on record</div>`;
  const sh=c=>!hide.includes(c);
  return`<table class="dtbl"><thead><tr><th>#</th><th>DATE</th><th>MENTOR / TA</th>${sh('module')?'<th>MODULE</th>':''}<th>DURATION</th><th>RATING</th><th>STATUS</th>${sh('feedback')?'<th>FEEDBACK</th>':''}</tr></thead><tbody>${sess.map((s,i)=>{const rv=s.rating&&String(s.rating)!=='0'?String(s.rating):'—';const col=rv!=='—'?'var(--green)':'var(--muted)';return`<tr><td class="mono">${i+1}</td><td class="mono">${(s.date||'—').slice(0,10)}</td><td>${s.mentor||'—'}</td>${sh('module')?`<td style="font-size:11px;color:var(--muted)">${s.module||s.topic||'—'}</td>`:''}<td class="mono">${s.duration_mins?s.duration_mins+'m':'—'}</td><td class="mono" style="color:${col}">${rv!=='—'?rv+'/5':rv}</td><td style="font-size:11px;color:var(--muted)">${s.status||'—'}</td>${sh('feedback')?`<td style="font-size:11px;color:var(--muted);max-width:200px;white-space:pre-wrap">${s.subjective_feedback||s.feedback_given||'—'}</td>`:''}</tr>`;}).join('')}</tbody></table>`;
}

function renderContests(conts){
  function norm(c){if(!c)return null;if(c.percentage!=null)return c.percentage;if(c.normalized_score!=null)return c.normalized_score;if(c.score!=null&&c.max_marks>0)return Math.round(c.score/c.max_marks*100*10)/10;return null;}
  function card(c,label){
    if(c===null)return`<div class="ct-card"><div class="ct-hdr"><div class="ct-title">${label}</div><span style="font-size:9px;color:var(--muted)">Not held</span></div><div class="ct-nh">Not yet scheduled</div></div>`;
    const n=norm(c);
    if(n===null)return`<div class="ct-card"><div class="ct-hdr"><div class="ct-title">${label}</div><span style="font-size:9px;color:var(--muted)">Not attempted</span></div><div class="ct-nh">Contest held — not attempted</div></div>`;
    const cl=n>=64,scol=cl?'var(--green)':n>=45?'var(--amber)':'var(--red)';
    return`<div class="ct-card"><div class="ct-hdr"><div><div class="ct-title">${label}</div><div class="ct-score-label">${(c.date||'').slice(0,10)||'—'}</div></div><div style="text-align:right"><span class="${cl?'clr-y':'clr-n'}">${cl?'CLEARED':'BELOW 64'}</span><div class="ct-score-100" style="color:${scol}">${n}<span style="font-size:11px;color:var(--muted)">/100</span></div></div></div><div class="ct-body"><div class="ct-sect">MCQ</div><div class="ct-row"><span class="ct-k">Score</span><span class="ct-v">${c.mcq_score!=null?c.mcq_score:'—'}/100</span></div><div class="ct-row"><span class="ct-k">Questions</span><span class="ct-v">${c.mcq_marked_qs||0}/${c.mcq_total_qs||0} · ${c.mcq_correct_qs||0} correct</span></div><div class="ct-sect">Coding</div><div class="ct-row"><span class="ct-k">Score</span><span class="ct-v">${c.coding_score!=null?c.coding_score:'—'}/100</span></div><div class="ct-row"><span class="ct-k">Problems</span><span class="ct-v">${c.coding_qs_completed||0}/${c.coding_total_qs||0}</span></div><div class="ct-sect">Total</div><div class="ct-row"><span class="ct-k">MCQ×0.4 + Code×0.6</span><span class="ct-v" style="color:${scol};font-weight:700">${n}/100</span></div></div></div>`;
  }
  const mc1n=norm(conts.mc1),mc2n=norm(conts.mc2);
  const finalCleared=(mc1n!=null&&mc1n>=64)||(mc2n!=null&&mc2n>=64);
  const banner=finalCleared
    ?`<div style="background:#071a10;border:1px solid #0d3520;border-radius:5px;padding:8px 12px;margin-bottom:10px;font-size:11px;font-family:'IBM Plex Mono',monospace;color:var(--green)">✓ MODULE CLEARED — ${mc1n!=null&&mc1n>=64?'MC1: '+mc1n:'MC2: '+mc2n}/100 ≥ 64</div>`
    :`<div style="background:#1c0a0a;border:1px solid #3d1010;border-radius:5px;padding:8px 12px;margin-bottom:10px;font-size:11px;font-family:'IBM Plex Mono',monospace;color:var(--amber)">⚠ Module not yet cleared — need MC1 or MC2 ≥ 64/100</div>`;
  return banner+`<div class="ct-grid">${card(conts.mid_mc1,'Mid MC — Attempt 1')}${conts.mid_mc2?card(conts.mid_mc2,'Mid MC — Attempt 2'):''}${card(conts.mc1,'Main MC 1 ← REAL EXAM')}${card(conts.mc2,'Main MC 2 ← REAL EXAM')}</div>`;
}

function renderProject(proj){
  if(!proj)return'<div class="sess-empty">No project submission on record.<br><span style="font-size:10px;margin-top:4px;display:block">Project not yet released for this batch.</span></div>';
  const cl=proj.cleared,col=cl?'var(--green)':proj.submissions>0?'var(--amber)':'var(--red)';
  const hist=proj.submission_history||[];
  const histHtml=hist.length?`<div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border)"><div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);font-family:'IBM Plex Mono',monospace;margin-bottom:7px">Submission History</div><table class="dtbl"><thead><tr><th>#</th><th>Submitted</th><th>Score</th><th>Evaluator</th><th>Feedback At</th></tr></thead><tbody>${hist.map(h=>{const sc=h.marks!=null?h.marks:null;const scCol=sc==null?'var(--muted)':sc>=8?'var(--green)':sc>=5?'var(--amber)':'var(--red)';return`<tr><td class="mono">Sub ${h.submission}</td><td class="mono" style="font-size:10px">${h.timestamp||h.date||'—'}</td><td class="mono" style="color:${scCol};font-size:14px;font-weight:700">${sc!=null&&sc>0?sc+'/10':(sc===0?'Not evaluated':'Pending')}</td><td style="font-size:10px;color:var(--muted)">${h.evaluator||'—'}</td><td style="font-size:10px;color:var(--muted)">${h.feedback_given_time||'—'}</td></tr>`;}).join('')}</tbody></table></div>`:'';
  return`<div class="proj-card"><div class="proj-title">${proj.project||'Project'}</div><div class="proj-row"><span class="proj-k">Question</span><span class="proj-v">${proj.question||'—'}</span></div><div class="proj-row"><span class="proj-k">Release / Deadline</span><span class="proj-v">${proj.release_date||'—'} → ${proj.deadline||'—'}</span></div><div class="proj-row"><span class="proj-k">Submissions</span><span class="proj-v">${proj.submissions||0}</span></div><div class="proj-row"><span class="proj-k">Best Score</span><span class="proj-v" style="color:${col};font-size:15px;font-weight:700">${proj.marks!=null&&proj.marks>0?proj.marks+'/'+(proj.max_marks||10):(proj.marks===0?'Not evaluated':'—')}</span></div><div class="proj-row"><span class="proj-k">Cleared (≥8/10)</span><span class="proj-v" style="color:${col}">${cl?'✓ YES':'✗ NOT CLEARED'}</span></div><div class="proj-row"><span class="proj-k">Feedbacks</span><span class="proj-v">${proj.feedback_count||0} &nbsp;|&nbsp; Last: ${proj.last_feedback||'—'}</span></div>${proj.note?`<div class="proj-note">⚠ ${proj.note}</div>`:''}${histHtml}</div>`;
}

function switchTab(tab,el){
  document.querySelectorAll('.mtab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.tpanel').forEach(p=>p.classList.remove('active'));
  el.classList.add('active');document.getElementById('tab-'+tab)?.classList.add('active');
  if(tab==='playlist')renderPlaylistTab();
}

function renderAsgn(){
  const mod=getMod(_curSt)||{};
  const typeF=document.getElementById('qType')?.value||'all';
  const topicF=document.getElementById('qTopic')?.value||'';
  const fromF=document.getElementById('qFrom')?.value||'';
  const toF=document.getElementById('qTo')?.value||'';
  let rows=[];
  if(typeF==='all')rows=[...(mod.asgn_detail||[]).map(r=>({...r,_t:'Learn'})),...(mod.app_detail||[]).map(r=>({...r,_t:'App'}))];
  else if(typeF==='Learn')rows=(mod.asgn_detail||[]).map(r=>({...r,_t:'Learn'}));
  else rows=(mod.app_detail||[]).map(r=>({...r,_t:'App'}));
  rows=rows.filter(d=>{if(topicF&&d.topic!==topicF)return false;const ld=(d.last_solved_date||'').slice(0,10);if(fromF&&ld&&ld<fromF)return false;if(toF&&ld&&ld>toF)return false;return true;});
  rows.sort((a,b)=>{let va=a[asgnSort.key]??'',vb=b[asgnSort.key]??'';if(typeof va==='number')return asgnSort.dir*(va-vb);return asgnSort.dir*String(va).localeCompare(String(vb));});
  const totalRel=rows.reduce((a,r)=>a+r.total_released,0),totalSol=rows.reduce((a,r)=>a+r.solved,0),totalAtt=rows.reduce((a,r)=>a+r.attempted,0);
  const times=rows.filter(r=>r.avg_time_mins!=null&&r.solved>0).map(r=>r.avg_time_mins);
  const avgTime=times.length?Math.round(times.reduce((a,b)=>a+b,0)/times.length):null;
  const notAtt=rows.filter(r=>r.attempted===0&&r.total_released>0).length;
  const slow=rows.filter(r=>r.avg_time_mins>60&&r.solved>0).length;
  const pct=totalRel>0?Math.round(totalSol/totalRel*100):0;
  const asgnCountEl=document.getElementById('asgnCount');if(asgnCountEl)asgnCountEl.textContent=`${rows.length} rows · ${totalSol}/${totalRel} solved`;
  const sumEl=document.getElementById('asgnSummary');
  if(sumEl)sumEl.innerHTML=`<div class="as-box"><div class="as-v" style="color:${pct>=75?'var(--green)':pct>=50?'var(--amber)':'var(--red)'}">${totalSol}/${totalRel}</div><div class="as-l">Solved</div></div><div class="as-box"><div class="as-v" style="color:${pct>=75?'var(--green)':pct>=50?'var(--amber)':'var(--red)'}">${pct}%</div><div class="as-l">Completion</div></div><div class="as-box"><div class="as-v">${totalAtt}</div><div class="as-l">Attempted</div></div><div class="as-box"><div class="as-v" style="color:${avgTime&&avgTime>45?'var(--amber)':'var(--green)'}">${avgTime?avgTime+'m':'—'}</div><div class="as-l">Avg Time</div></div><div class="as-box"><div class="as-v" style="color:${notAtt>0?'var(--orange)':'var(--green)'}">${notAtt}</div><div class="as-l">Not Attempted</div></div><div class="as-box"><div class="as-v" style="color:${slow>0?'var(--amber)':'var(--green)'}">${slow}</div><div class="as-l">Slow (>60m)</div></div>`;
  const body=document.getElementById('asgnBody');if(!body)return;
  if(!rows.length){body.innerHTML=`<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:18px">No data</td></tr>`;return;}
  const topicMap=new Map();
  rows.forEach(d=>{const key=d.topic;if(!topicMap.has(key))topicMap.set(key,{topic:d.topic,total_released:0,attempted:0,solved:0,avg_time_mins:null,_times:[],last_solved_date:null,isNA:false,hasQuick:false,hasSlow:false});const m=topicMap.get(key);m.total_released+=d.total_released||0;m.attempted+=d.attempted||0;m.solved+=d.solved||0;if(d.avg_time_mins!=null&&d.solved>0)m._times.push(d.avg_time_mins);if(d.last_solved_date&&(!m.last_solved_date||d.last_solved_date>m.last_solved_date))m.last_solved_date=d.last_solved_date;if(d.attempted===0&&d.total_released>0)m.isNA=true;if(d.avg_time_mins!=null&&d.avg_time_mins<3&&d.solved>0)m.hasQuick=true;if(d.avg_time_mins!=null&&d.avg_time_mins>60&&d.solved>0)m.hasSlow=true;});
  const merged=[...topicMap.values()].map(m=>{m.avg_time_mins=m._times.length?Math.round(m._times.reduce((a,b)=>a+b,0)/m._times.length):null;return m;});
  body.innerHTML=merged.map(d=>{const pct2=d.total_released>0?Math.round(d.solved/d.total_released*100):0;const sc=d.solved===d.total_released&&d.total_released>0?'var(--green)':d.solved>0?'var(--amber)':'var(--red)';const timeCol=d.hasQuick?'var(--red)':d.hasSlow?'var(--amber)':'var(--text)';return`<tr><td>${d.topic}${d.isNA?'<span class="na-tag">NOT ATTEMPTED</span>':''}</td><td class="mono">${d.total_released}</td><td class="mono">${d.attempted}</td><td><div class="sbar"><div class="sbar-bg"><div class="sbar-fill" style="width:${pct2}%;background:${sc}"></div></div><span class="mono" style="color:${sc}">${d.solved}/${d.total_released}</span></div></td><td class="mono" style="color:${timeCol}">${d.avg_time_mins!=null?d.avg_time_mins+'m':'—'}${d.hasQuick?'<span class="quick-tag">⚡</span>':''}${d.hasSlow?'<span class="slow-tag">🐌</span>':''}</td><td class="mono" style="color:var(--muted)">${(d.last_solved_date||'—').slice(0,10)}</td></tr>`;}).join('');
}

function sortA(key,th){document.querySelectorAll('#tab-asgn .dtbl th').forEach(t=>{t.classList.remove('sa','sd')});if(asgnSort.key===key)asgnSort.dir*=-1;else{asgnSort.key=key;asgnSort.dir=1;}th.classList.add(asgnSort.dir===1?'sa':'sd');renderAsgn();}
function closeInfo(e){if(!e||e.target===document.getElementById('infoModal'))document.getElementById('infoModal').classList.remove('open');}

async function openTokenModal(){
  document.getElementById('tokenModal').classList.add('open');
  const el=document.getElementById('tokenBody');el.innerHTML='<span class="spin"></span>';
  try{const d=await(await fetch('/api/token-usage')).json();if(!d.calls){el.innerHTML='<div class="sess-empty">No calls yet</div>';return;}el.innerHTML=`<table class="dtbl"><thead><tr><th>Student</th><th>In</th><th>Out</th><th>Cost</th></tr></thead><tbody>${d.breakdown.map(t=>`<tr><td>${t.student}</td><td class="mono">${t.in}</td><td class="mono">${t.out}</td><td class="mono" style="color:var(--green)">$${t.cost}</td></tr>`).join('')}</tbody></table><div style="font-size:12px;font-weight:600;margin-top:10px;padding:10px;background:var(--bg3);border-radius:5px;font-family:'IBM Plex Mono',monospace;text-align:right">${d.calls} calls · <span style="color:var(--green)">$${d.total_cost} total</span></div>`;}catch(e){el.innerHTML=`<span style="color:var(--red)">${e.message}</span>`;}
}
function closeToken(e){if(!e||e.target===document.getElementById('tokenModal'))document.getElementById('tokenModal').classList.remove('open');}

function renderBatch(){
  const batches=[...new Set(STUDS.map(s=>s.batch))];
  const bd=batches.map(b=>{
    const ss=STUDS.filter(s=>s.batch===b);
    const avg=k=>ss.length?Math.round(ss.reduce((a,s)=>a+(s[k]||0),0)/ss.length):0;
    const mod=getMod(ss[0]||{});
    return{name:b,ss,count:ss.length,ph:mod.current_phase||mod.sql_phase||'?',cl:mod.current_class||'?',avgRisk:avg('risk'),avgAtt:avg('avg_att'),avgAsgn:avg('avg_asgn'),avgMC:avg('avg_mc'),high:ss.filter(s=>s.tier==='High Risk').length,cleared:ss.filter(s=>(s.avg_mc||0)>=64).length,ghost:ss.filter(s=>(s.avg_att||0)===0).length,projCleared:ss.filter(s=>s.proj_passed).length,avgInact:Math.round(ss.filter(s=>(s.days_inactive||0)<999).reduce((a,s)=>a+(s.days_inactive||0),0)/Math.max(ss.filter(s=>(s.days_inactive||0)<999).length,1))};
  });
  const metrics=[{k:'avgRisk',l:'Avg Risk',u:'',lb:true},{k:'avgAtt',l:'Avg Attendance',u:'%',lb:false},{k:'avgAsgn',l:'Avg Assignment',u:'%',lb:false},{k:'avgMC',l:'Avg MC Score',u:'/100',lb:false},{k:'high',l:'High Risk',u:'',lb:true},{k:'cleared',l:'MC Cleared',u:'',lb:false},{k:'ghost',l:'Ghosts',u:'',lb:true},{k:'projCleared',l:'Project Cleared',u:'',lb:false},{k:'avgInact',l:'Avg Inactive',u:'d',lb:true}];
  const getBest=(k,lb)=>{const v=bd.map(b=>b[k]);return lb?Math.min(...v):Math.max(...v);};
  const getWorst=(k,lb)=>{const v=bd.map(b=>b[k]);return lb?Math.max(...v):Math.min(...v);};
  const cardsHtml=bd.map(b=>`<div class="bc-card"><div class="bc-hdr"><div class="bc-name">${b.name.replace(' 2026','')}</div><div class="bc-meta">Ph${b.ph} · C${b.cl} · ${b.count} students</div></div><div class="bc-body">${[['Risk',b.avgRisk,b.avgRisk>=75?'var(--red)':b.avgRisk>=55?'var(--amber)':'var(--green)'],['Attendance',b.avgAtt,bc(b.avgAtt)],['Assignment',b.avgAsgn,bc(b.avgAsgn)],['MC Score',b.avgMC,b.avgMC>=64?'var(--green)':b.avgMC>0?'var(--amber)':'var(--red)']].map(([lbl,val,col])=>`<div class="bc-bar"><div class="bc-bar-lbl">${lbl}</div><div class="bc-bar-bg"><div class="bc-bar-fill" style="width:${Math.min(val,100)}%;background:${col}"></div></div><div class="bc-bar-val" style="color:${col}">${val}</div></div>`).join('')}<div class="bc-badges"><div class="bc-badge"><div class="bc-bv" style="color:var(--red)">${b.high}</div><div class="bc-bl">High Risk</div></div><div class="bc-badge"><div class="bc-bv" style="color:${b.cleared>0?'var(--green)':'var(--muted)'}">${b.cleared}</div><div class="bc-bl">MC Cleared</div></div><div class="bc-badge"><div class="bc-bv" style="color:${b.ghost>0?'var(--red)':'var(--green)'}">${b.ghost}</div><div class="bc-bl">Ghosts</div></div><div class="bc-badge"><div class="bc-bv" style="color:${b.avgInact>=14?'var(--red)':b.avgInact>=7?'var(--amber)':'var(--green)'}">${b.avgInact}d</div><div class="bc-bl">Avg Inactive</div></div></div></div></div>`).join('');
  const cmpRows=metrics.map(m=>{const best=getBest(m.k,m.lb),worst=getWorst(m.k,m.lb);return`<tr><td>${m.l}</td>${bd.map(b=>{const v=b[m.k];const isBest=v===best,isWorst=v===worst&&best!==worst;return`<td class="${isBest?'best':isWorst?'worst':''}">${v}${m.u}</td>`;}).join('')}</tr>`;}).join('');
  const ctRows=['mid_mc1','mid_mc2','mc1','mc2'].map(ct=>{const labels={mid_mc1:'Mid MC 1',mid_mc2:'Mid MC 2',mc1:'Main MC 1',mc2:'Main MC 2'};return`<tr><td>${labels[ct]}</td>${bd.map(b=>{const mod0=getMod(b.ss[0]||{});const att=b.ss.filter(s=>getMod(s).contests?.[ct]?.normalized_score!=null);const clr=att.filter(s=>getMod(s).contests?.[ct]?.normalized_score>=64);const nh=b.ss.every(s=>getMod(s).contests?.[ct]===null);if(nh)return`<td style="color:var(--muted)">—</td>`;if(!att.length)return`<td style="color:var(--muted)">0 attempted</td>`;const avg=Math.round(att.reduce((a,s)=>a+(getMod(s).contests[ct].normalized_score||0),0)/att.length);return`<td><span style="font-weight:700">${avg}/100</span> <span style="color:var(--muted);font-size:10px">${clr.length}/${att.length} cleared</span></td>`;}).join('')}</tr>`;}).join('');
  document.getElementById('batchContent').innerHTML=`<div class="batch-hdr">Batch Analytics</div><div class="batch-sub">${STUDS.length} students across ${bd.length} batches</div><div class="bc-grid">${cardsHtml}</div><div class="cmp-section"><div class="cmp-hdr">📊 Cross-Batch Comparison <span style="font-size:10px;color:var(--muted);font-weight:400">green=best · red=worst</span></div><table class="cmp-tbl"><thead><tr><th>Metric</th>${bd.map(b=>`<th>${b.name.replace(' 2026','')}</th>`).join('')}</tr></thead><tbody>${cmpRows}</tbody></table></div><div class="cmp-section"><div class="cmp-hdr">🏆 Contest Clearance</div><table class="cmp-tbl"><thead><tr><th>Contest</th>${bd.map(b=>`<th>${b.name.replace(' 2026','')}</th>`).join('')}</tr></thead><tbody>${ctRows}</tbody></table></div>`;
}

document.addEventListener('keydown',e=>{if(e.key==='Escape'){document.getElementById('infoModal').classList.remove('open');document.getElementById('tokenModal').classList.remove('open');}});
initFilters();filter();
</script>
</body></html>"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)