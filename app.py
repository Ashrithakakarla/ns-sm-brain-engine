"""NS SM Brain Engine v5 — All 12 improvements applied."""
from flask import Flask, render_template_string, jsonify, request
import json, os, datetime
from openai import OpenAI

app = Flask(__name__)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "sk-YOUR_KEY_HERE")
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_refresh.json")
THRESH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "thresholds.json")
openai_client = OpenAI(api_key=OPENAI_API_KEY)
GPT4O_IN = 3.0 / 1_000_000;
GPT4O_OUT = 15.0 / 1_000_000
token_log = []


def load_data():
    if not os.path.exists(DATA_PATH): return {"students": []}
    with open(DATA_PATH) as f: return json.load(f)


# Contest score formula (matches Python script):
# Spreadsheets: MCQ*0.4 + Coding*0.6, normalized /max * 100
# Clearance: normalized >= 64
def normalized_score(c):
    if not c or c.get('score') is None: return None
    return c.get('normalized_score', round(c['score'] / c['max_marks'] * 100, 1) if c['max_marks'] else 0)


# Playlist IDs that are contest-relevant for Spreadsheets
# Based on fetched data: playlist 20,21 = Mid MC, 12,13,14 = MC practice, 5 = General practice
PLAYLIST_LABELS = {
    5: "General Practice (VLOOKUP, Pivot, Charts)",
    8: "SQL Practice",
    7: "SQL Practice",
    9: "SQL Practice",
    12: "Contest Practice — Bonus/Salary/Feedback",
    13: "Contest Practice — Customer/Employee Analysis",
    14: "Contest Practice — Data Analysis",
    20: "Mid Module Contest Practice",
    21: "Mid Module Contest Practice",
}

PHASE_CFG = {
    1: {
        "name": "Attendance & Habit (E1–E3)",
        "next": "Phase 2: Assignment momentum",
        "p0": "ATTENDANCE",
        "p0_detail": "Must hit ≥85% attendance. Without attendance, no content = no progress.",
        "p1": "FIRST ASSIGNMENT",
        "p1_detail": "Get at least 1 question solved. Build the habit.",
        "p2": "Portal familiarity",
    },
    2: {
        "name": "Assignment + Mid MC Prep (E4–E6)",
        "next": "Mid Module Contest",
        # P0 = Mid MC is coming → practice the topics that will appear via assignments + playlist
        "p0": "MID MODULE CONTEST PREP",
        "p0_detail": "Mid MC is the next milestone. Recommend specific assignment topics and playlists to practice. Target: attempt all released questions in topics that appear in Mid MC. Use contest-specific playlist (Playlist 20 or 21).",
        "p1": "ASSIGNMENT COMPLETION + TA SESSIONS",
        "p1_detail": "Complete ≥75% assignments. If stuck → book TA session. Late/pending topics drag the MC score.",
        "p2": "ATTENDANCE",
        "p2_detail": "Attendance ≥75%. Each missed class = missed practice questions.",
    },
    3: {
        "name": "MC Preparation (E7–E9)",
        "next": "Module Contest 1 (MC1) — REAL EXAM",
        # P0 = MC1 is the real exam → targeted practice on weak topics
        "p0": "MC1 PREP — TARGET WEAK TOPICS",
        "p0_detail": "MC1 is the real module exam. Identify weak topics from assignments and recommend targeted playlist practice. Goal: ≥64/100 normalized.",
        "p1": "ASSIGNMENT COMPLETION",
        "p1_detail": "≥75% assignment completion. Unsolved topics = likely contest failures. Book TA for hard topics.",
        "p2": "ATTENDANCE",
        "p2_detail": "Attendance ≥72%. Each class covers contest-relevant material.",
    },
    4: {
        "name": "Contest & Project (E10+)",
        "next": "Module Contest 1+2 + Project submission",
        # P0 = Project + MC2 if MC1 not cleared
        "p0": "PROJECT SUBMISSION + MC CLEARANCE",
        "p0_detail": "If project not cleared → resubmit with feedback incorporated. If MC1 not cleared → prepare for MC2. These are the final gates.",
        "p1": "ASSIGNMENT COMPLETION + PLAYLIST",
        "p1_detail": "≥75% assignments, ≥65% playlist. Directly feeds contest preparation.",
        "p2": "ATTENDANCE",
        "p2_detail": "Attendance ≥70%.",
    },
}


def build_gpt_prompt(student):
    mod = student.get("mods", {}).get("Spreadsheets", {})
    phase = mod.get("current_phase", 2)
    cls = mod.get("current_class", 1)
    cfg = PHASE_CFG.get(phase, PHASE_CFG[2])
    p0_label = cfg["p0"]
    p0_detail = cfg.get("p0_detail", "")
    p1_label = cfg["p1"]
    p1_detail = cfg.get("p1_detail", "")
    p2_label = cfg.get("p2", "Monitor")
    p2_detail = cfg.get("p2_detail", "")
    today = datetime.date(2026, 4, 22)

    # --- Dynamic Phase 4 P0/P1 override based on MC attempt status ---
    # Evaluated after contest data is loaded below, but we flag intent here.
    # Actual override applied after conts/mc1_n/mc2_n are computed.
    _phase4_mc_not_attempted = False  # will be set below

    att = student.get("avg_att", 0)
    asgn_pct = student.get("avg_asgn", 0)  # pre-calculated, overridden below
    days_ia = student.get("days_inactive", 0)
    ta_count = mod.get("ta_count", 0)

    learn = mod.get("asgn_detail", [])
    app_d = mod.get("app_detail", [])
    all_d = learn + app_d
    # Use actual solved counts (questions solved, not topic rows)
    learn_solved = mod.get("learn_solved", sum(d.get("solved", 0) for d in learn))
    learn_total = mod.get("learn_total", sum(d.get("total_released", 0) for d in learn))
    app_solved = mod.get("app_solved", sum(d.get("solved", 0) for d in app_d))
    app_total = mod.get("app_total", sum(d.get("total_released", 0) for d in app_d))
    total_solved = learn_solved + app_solved
    total_qs = learn_total + app_total
    # Recalculate real pct from actual questions (not pre-stored field)
    real_asgn_pct = round(total_solved / total_qs * 100, 1) if total_qs > 0 else 0

    # Unsolved topics (group by topic, deduplicate)
    unsolved_topics = list({d['topic'] for d in all_d if d.get('solved', 0) == 0 and d.get('attempted', 0) > 0})
    not_att_topics = list({d['topic'] for d in all_d if d.get('attempted', 0) == 0 and d.get('total_released', 0) > 0})
    # Quick solve (avg <3 min) — suspicious
    quick_topics = [f"{d['topic']} ({d['avg_time_mins']}m avg)" for d in all_d if
                    d.get('avg_time_mins') and d['avg_time_mins'] < 3 and d.get('solved', 0) > 0]
    slow_topics = [f"{d['topic']} ({d['avg_time_mins']}m avg)" for d in all_d if
                   d.get('avg_time_mins') and d['avg_time_mins'] > 60 and d.get('solved', 0) > 0]

    # Estimate % if unsolved topics solved
    unsolved_q_count = sum(d.get('total_released', 0) - d.get('solved', 0) for d in all_d if
                           d.get('solved', 0) == 0 and d.get('attempted', 0) > 0)
    if total_qs > 0:
        est_pct_if_solved = round((total_solved + unsolved_q_count) / total_qs * 100, 1)
    else:
        est_pct_if_solved = asgn_pct

    # Contest analysis — use normalized scores
    conts = mod.get("contests", {})
    mid = conts.get("mid_mc")
    mc1 = conts.get("mc1")
    mc2 = conts.get("mc2")
    mid_n = normalized_score(mid)
    mc1_n = normalized_score(mc1)
    mc2_n = normalized_score(mc2)
    best_mc = max(x for x in [mid_n, mc1_n, mc2_n] if x is not None) if any(
        x is not None for x in [mid_n, mc1_n, mc2_n]) else 0

    def fmt_c(c, n, label):
        if c is None: return f"{label}: Not held yet"
        if n is None: return f"{label}: Contest held — not attempted"
        clr = "CLEARED ✓" if n >= 64 else f"NOT CLEARED — need +{round(64 - n, 1)} pts"
        return f"{label}: {n}/100 ({clr})"

    mid_str = fmt_c(mid, mid_n, "Mid MC")
    mc1_str = fmt_c(mc1, mc1_n, "MC1")
    mc2_str = fmt_c(mc2, mc2_n, "MC2")

    # Contest hierarchy: MC1 or MC2 is the REAL goal (final exam)
    # Mid MC is practice/bonus — if MC1 or MC2 is cleared, student has passed
    # NEVER recommend improving Mid MC if MC1 or MC2 is already cleared
    final_mc_cleared = (mc1_n is not None and mc1_n >= 64) or (mc2_n is not None and mc2_n >= 64)
    mid_mc_cleared = mid_n is not None and mid_n >= 64

    past_cleared = []
    if mc1_n is not None and mc1_n >= 64: past_cleared.append("MC1")
    if mc2_n is not None and mc2_n >= 64: past_cleared.append("MC2")
    if mid_n is not None and mid_n >= 64: past_cleared.append("Mid MC")

    past_failed = []
    if mc1_n is not None and mc1_n < 64: past_failed.append(f"MC1 ({mc1_n}/100)")
    if mc2_n is not None and mc2_n < 64: past_failed.append(f"MC2 ({mc2_n}/100)")
    if mid_n is not None and mid_n < 64 and not final_mc_cleared: past_failed.append(f"Mid MC ({mid_n}/100)")

    not_attempted = []
    if mc1_n is None and mc1 is not None: not_attempted.append("MC1")

    # --- Phase 4 dynamic P0/P1 override ---
    # If neither MC1 nor MC2 has been attempted yet, MC prep is the burning P0.
    # Project becomes P1 (still important, but MC is the immediate gate).
    mc1_not_attempted = (mc1 is not None and mc1_n is None)
    mc2_not_attempted = (mc2 is not None and mc2_n is None)
    mc1_not_held = (mc1 is None)
    neither_mc_attempted = not final_mc_cleared and mc1_not_attempted
    mc1_never_attempted_no_mc2 = not final_mc_cleared and mc1_not_attempted and mc2_not_attempted

    if phase == 4 and not final_mc_cleared and (mc1_not_attempted or mc1_never_attempted_no_mc2):
        # Override: MC prep is P0, project is P1
        p0_label = "MC1 PREP — NOT YET ATTEMPTED"
        p0_detail = ("MC1 has not been attempted yet — this is the highest priority. "
                     "Identify weak topics from assignments, recommend targeted playlist practice. "
                     "Goal: attempt MC1 and score ≥64/100. Do NOT defer this for project.")
        p1_label = "PROJECT SUBMISSION"
        p1_detail = ("Project is the second gate. If not submitted → submit now. "
                     "If submitted with feedback → resubmit incorporating feedback. "
                     "Cannot clear module without both MC and project.")
    if mc2_n is None and mc2 is not None: not_attempted.append("MC2")
    if mid_n is None and mid is not None and not final_mc_cleared: not_attempted.append("Mid MC")

    # Playlist recommendations based on contest gaps
    playlists = mod.get("playlist_detail", [])
    relevant_playlists = []
    for p in playlists:
        pid = p.get("playlist_id", 0)
        label = PLAYLIST_LABELS.get(pid, f"Playlist {pid}")
        if not p.get("completed") and pid in [5, 12, 13, 14, 20, 21]:
            relevant_playlists.append(
                f"Playlist {pid} — {label} ({p.get('total_questions', 0)} questions, in-progress)")
        elif p.get("completed") and pid in [5, 12, 13, 14, 20, 21]:
            relevant_playlists.append(
                f"Playlist {pid} — {label} ({p.get('total_questions', 0)} questions, COMPLETED ✓ — re-attempt recommended)")

    # Project
    proj = mod.get("project")
    if proj:
        hist = proj.get("submission_history", [])
        hist_str = " | ".join(
            [f"Sub{h['submission']}: {h['marks']}/10" if h['marks'] is not None else f"Sub{h['submission']}: pending"
             for h in hist]) if hist else ""
        if proj.get("cleared"):
            proj_str = f"Project CLEARED ✓ {proj['marks']}/{proj['max_marks']}"
        else:
            subs = proj.get("submissions", 0)
            fb = proj.get("feedback_count", 0)
            if subs > 0 and fb > 0:
                proj_str = f"Submitted {subs}x [{hist_str}], {fb} feedbacks received (latest {proj.get('last_feedback', '?')}) — MUST resubmit incorporating feedback"
            elif subs > 0:
                proj_str = f"Submitted {subs}x [{hist_str}] — awaiting evaluation"
            else:
                proj_str = "NOT submitted"
    else:
        proj_str = "Not yet released for this batch" if phase < 4 else "NOT submitted — critical"

    suppress_att = att >= 100

    system = f"""You are a Newton School Success Manager writing a crisp pre-call brief for {student['name']}.
Today: Class {cls} | Phase {phase} — {cfg['name']}

THIS WEEK'S PRIORITY (STRICTLY FOLLOW THIS ORDER):
P0 — MUST address on call: {p0_label}
     Detail: {p0_detail}
P1 — Important: {p1_label}
     Detail: {p1_detail}
P2 — Monitor: {p2_label}
     Detail: {p2_detail}
Next milestone: {cfg['next']}

STRICT RULES:

0. P0/P1/P2 ORDER IS MANDATORY — the phase determines priority, never swap:
   Phase 2 (upcoming Mid MC): P0=Mid MC prep (specific topics+playlist for contest), P1=assignments+TA sessions, P2=attendance
   Phase 3 (upcoming MC1):    P0=MC1 prep (weak topics+playlist), P1=assignment completion+TA, P2=attendance
   Phase 4 — DEFAULT:         P0=project submission+MC clearance, P1=assignments+playlist, P2=attendance
   Phase 4 — MC NOT ATTEMPTED: If MC1 has not been attempted yet → P0=MC1 prep (attempt the exam NOW), P1=project submission, P2=attendance
     Rule: A student who has never sat MC1 must be pushed to attempt it before anything else. Project is secondary.

1. ATTENDANCE: If attendance ≥100% → do NOT mention it anywhere. If ≥85% → positive only. Only flag if <85%.

2. CONTEST HIERARCHY — CRITICAL:
   - REAL GOAL = clear MC1 or MC2 (final module exams). These MATTER for progression.
   - Mid MC = practice/bonus. It is IRRELEVANT if MC1 or MC2 is already cleared.
   - If MC1 or MC2 is CLEARED → student has passed the module. Congratulate and move on.
   - If MC1 or MC2 cleared: {past_cleared} → DO NOT recommend "prepare for Mid MC" — it is past and irrelevant.
   - If neither MC1 nor MC2 cleared yet → recommend practice for the NEXT upcoming final MC (MC1 or MC2).
   - NEVER say "prepare for Mid MC" if MC1 or MC2 is already cleared.
   - Still needs improvement: {past_failed} | Not yet attempted: {not_attempted}

3. ASSIGNMENTS: 
   - Recommend by TOPIC NAME only (not difficulty level)
   - Estimate what assignment % will be if they complete unsolved topics
   - If TA sessions = 0 and unsolved topics exist → ALWAYS ask about booking TA

4. PLAYLISTS:
   - Recommend SPECIFIC playlists from this list: {relevant_playlists if relevant_playlists else 'Check playlists section'}
   - Don't invent playlist names. Only recommend from the actual list above.
   - For failed/upcoming contests → recommend the contest-specific playlist
   - If already completed a playlist → suggest re-attempting it

5. PROJECT: 
   - Already submitted + feedback → "resubmit incorporating feedback" (NEVER say submit for first time)
   - Already cleared → don't mention project negatively

6. QUICK SOLVES:
   - If student solved questions in <3 minutes on average → flag this as suspicious, ask if they really understood

7. INACTIVITY:
   - {days_ia} days since last activity — mention if >14 days

8. SM QUESTIONS: Real, open-ended, empathetic. Specific to their data. Q4 must be custom.

Return ONLY valid JSON:
{{
  "call_type": "3-word label",
  "phase_context": "Class {cls}/N — {cfg['name']} — Next: {cfg['next']}",
  "attendance": {{"flag":"ok|warn|critical","missed_count":N,"note":"null if att>=100","last3":["date — type — watch%"]}},
  "assignment": {{
    "flag":"ok|warn|critical",
    "completion": "{real_asgn_pct}% (Learn: {learn_solved}/{learn_total} | App: {app_solved}/{app_total})",
    "last_solved":"YYYY-MM-DD (Nd ago)",
    "unsolved_topics":["topic name only"],
    "not_attempted_topics":["topic name only"],
    "slow_topics":["topic — Xm avg"],
    "quick_solve_flag":"null or topic if suspiciously fast",
    "est_pct_if_completed":"{est_pct_if_solved}% if all unsolved topics completed"
  }},
  "mc_score": {{
    "flag":"ok|warn|critical",
    "mid_mc":"X/100 or not held",
    "mc1":"X/100 or not held",
    "mc2":"X/100 or not held",
    "next_action":"what to focus on for NEXT contest (not past ones already cleared)"
  }},
  "project": {{"flag":"ok|warn|critical","status":"one line","action":"specific action or null"}},
  "recommendation": {{
    "p0":{{"label":"{p0_label}","items":["specific action referencing actual topics/playlists"]}},
    "p1":{{"label":"{p1_label}","items":["action — name specific topics and TA recommendation"]}},
    "p2":{{"label":"{p2_label}","items":["action"]}},
    "assignment_topics_to_solve":["topic — estimated +X% if solved"],
    "playlist_recommendation":["Playlist ID — title — why relevant"],
    "immediate_action":"single most important thing RIGHT NOW"
  }},
  "sm_questions":{{"q1":"P0 question","q2":"assignment/topic question","q3":"contest/project question","q4":"custom based on their specific data"}},
  "priority":"high|medium|low"
}}"""

    user = f"""Student: {student['name']} | Risk: {student['risk']}/100 | Tier: {student['tier']}
Batch: {student['batch']} | Class {cls} | Phase {phase}
Days since last activity: {days_ia}

ATTENDANCE: {att}% overall | {len([l for l in mod.get('lectures', []) if not l.get('attended', True)])} classes missed
TA sessions: {ta_count} | Mentor sessions: {mod.get('mentor_count', 0)}

ASSIGNMENT: {asgn_pct}% overall
Learning: {learn_solved}/{learn_total} | Application: {app_solved}/{app_total}
Last solved: {mod.get('last_solve', '—')} ({days_ia}d ago)
Unsolved topics (attempted, not passed): {unsolved_topics[:6]}
Not attempted topics: {not_att_topics[:6]}
Suspicious quick solves (<3m): {quick_topics[:3]}
If completes unsolved topics → estimated {est_pct_if_solved}% completion

CONTESTS (normalized /100, clearance=64):
{mid_str}
{mc1_str}
{mc2_str}

PLAYLISTS: {relevant_playlists if relevant_playlists else 'No playlist activity'}

PROJECT: {proj_str}"""

    return system, user


def generate_action_plan(student):
    system, user = build_gpt_prompt(student)
    resp = openai_client.chat.completions.create(
        model="gpt-5.4",
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_completion_tokens=1200,
    )
    u = resp.usage
    cost = u.prompt_tokens * GPT4O_IN + u.completion_tokens * GPT4O_OUT
    token_log.append(
        {"student": student["name"], "in": u.prompt_tokens, "out": u.completion_tokens, "cost": round(cost, 6)})
    raw = (resp.choices[0].message.content or '').strip()
    # Strip markdown fences if model wraps JSON
    if '```' in raw:
        raw = raw.split('```')[1]
        if raw.startswith('json'): raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)


@app.route('/')
def index():
    data = load_data()
    return render_template_string(HTML, data_json=json.dumps(data))


@app.route('/api/action-plan/<int:sid>')
def action_plan(sid):
    data = load_data()
    s = next((x for x in data["students"] if x["id"] == sid), None)
    if not s: return jsonify({"error": "Not found"}), 404
    try:
        plan = generate_action_plan(s)
        return jsonify({"plan": plan, "token_usage": token_log[-1]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/token-usage')
def token_usage():
    return jsonify(
        {"calls": len(token_log), "total_cost": round(sum(t["cost"] for t in token_log), 6), "breakdown": token_log})


@app.route('/api/data')
def api_data(): return jsonify(load_data())


@app.route('/api/playlist-attempts')
def playlist_attempts():
    """Fetch question-level playlist attempt data from Metabase card 9292."""
    student_id = request.args.get('student_id', type=int)
    if not student_id:
        return jsonify({"error": "student_id required"}), 400
    try:
        import requests as req
        metabase_url = "https://metabase-lierhfgoeiwhr.newtonschool.co"
        metabase_email = os.environ.get("METABASE_EMAIL", "ashritha.k@newtonschool.co")
        metabase_pass = os.environ.get("METABASE_PASSWORD", "H0CcPtgDa3ZN9b")
        # Auth
        auth = req.post(f"{metabase_url}/api/session",
            json={"username": metabase_email, "password": metabase_pass},
            headers={"Content-Type": "application/json"}, timeout=30)
        token = auth.json().get("id") or auth.json().get("token")
        if not token:
            return jsonify({"error": "Metabase auth failed"}), 500
        # Query card 9292 with student filter
        resp = req.post(f"{metabase_url}/api/card/9292/query/json",
            json={"parameters": [{"type": "number", "target": ["variable", ["template-tag", "user_id"]], "value": student_id}]},
            headers={"X-Metabase-Session": token, "Content-Type": "application/json"}, timeout=60)
        req.delete(f"{metabase_url}/api/session", headers={"X-Metabase-Session": token}, timeout=10)
        if resp.status_code != 200:
            return jsonify({"error": f"Card query failed: {resp.status_code}", "rows": []}), 200
        raw = resp.json()
        rows = []
        if isinstance(raw, list):
            for r in raw:
                rows.append({
                    "playlist_name":    r.get("playlist_name") or r.get("Playlist Name") or r.get("playlist") or "—",
                    "question_title":   r.get("question_title") or r.get("Question Title") or r.get("title") or r.get("question") or "—",
                    "is_solved":        bool(r.get("is_solved") or r.get("solved") or r.get("Is Solved")),
                    "score":            r.get("score") or r.get("Score"),
                    "max_score":        r.get("max_score") or r.get("Max Score"),
                    "attempts":         int(r.get("attempts") or r.get("Attempts") or 0),
                    "time_taken_mins":  float(r.get("time_taken_mins") or r.get("time_mins") or r.get("Time (mins)") or 0),
                    "solved_at":        str(r.get("solved_at") or r.get("Solved At") or r.get("last_solved") or ""),
                })
        return jsonify({"rows": rows, "count": len(rows)})
    except Exception as e:
        return jsonify({"error": str(e), "rows": []}), 200


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NS · SM Brain Engine v5</title>
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
/* SUMMARY */
.summary-strip{display:grid;grid-template-columns:repeat(5,1fr);background:var(--border)}
.sc{background:var(--bg2);padding:10px 16px}
.sc-val{font-size:19px;font-weight:700;font-family:'IBM Plex Mono',monospace;line-height:1}
.sc-lbl{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px;margin-top:3px}
/* CONTROLS */
.ctrl{display:flex;gap:8px;padding:10px 20px;border-bottom:1px solid var(--border);flex-wrap:wrap;align-items:center}
.search-inp{flex:1;min-width:180px;background:var(--bg2);border:1px solid var(--border2);color:var(--text);padding:6px 11px;border-radius:5px;font-size:12px;outline:none}
.search-inp:focus{border-color:var(--accent)}
.fsel{background:var(--bg2);border:1px solid var(--border2);color:var(--text);padding:6px 10px;border-radius:5px;font-size:12px;outline:none;cursor:pointer}
.cnt-lbl{font-size:10px;color:var(--muted);margin-left:auto;font-family:'IBM Plex Mono',monospace}
/* STUDENT CARDS */
.list-wrap{padding:12px 20px;display:flex;flex-direction:column;gap:6px}
.scard{background:var(--bg2);border:1px solid var(--border);border-radius:7px;display:flex;align-items:center;gap:10px;padding:10px 14px;cursor:pointer;transition:all .15s}
.scard:hover{border-color:var(--border2);background:var(--bg3)}.scard.open{border-color:var(--accent);border-bottom-left-radius:0;border-bottom-right-radius:0}
.risk-bar{width:3px;height:32px;border-radius:2px;flex-shrink:0}
.batch-tag{font-size:9px;color:var(--muted);background:var(--bg4);padding:2px 6px;border-radius:3px;white-space:nowrap;font-family:'IBM Plex Mono',monospace;flex-shrink:0}
.sinfo{flex:1;min-width:0}
.sname{font-weight:600;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.semail{font-size:10px;color:var(--muted);font-family:'IBM Plex Mono',monospace;margin-top:1px}
.sreason{font-size:11px;color:var(--muted);flex:2;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* Inactivity badge */
.inact-badge{font-size:9px;font-family:'IBM Plex Mono',monospace;padding:2px 6px;border-radius:3px;white-space:nowrap;flex-shrink:0}
.inact-hot{background:#1c0a0a;color:var(--red);border:1px solid #3d1010}
.inact-warn{background:#1c1308;color:var(--amber);border:1px solid #3d2808}
.inact-ok{background:var(--bg4);color:var(--muted);border:1px solid var(--border2)}
.tier-badge{padding:3px 8px;border-radius:4px;font-size:10px;font-weight:600;font-family:'IBM Plex Mono',monospace;white-space:nowrap;flex-shrink:0}
.rscore{font-family:'IBM Plex Mono',monospace;font-size:16px;font-weight:700;width:38px;text-align:right;flex-shrink:0}
.ibtn{width:24px;height:24px;border-radius:4px;border:1px solid var(--border2);background:var(--bg3);color:var(--muted);display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:12px;transition:all .15s;flex-shrink:0}
.ibtn:hover{border-color:var(--accent);color:var(--accent)}
.chev{color:var(--muted);font-size:14px;transition:transform .2s;flex-shrink:0}.scard.open .chev{transform:rotate(180deg)}
/* EXPAND PANEL */
.expand{display:none;background:var(--bg3);border:1px solid var(--accent);border-top:none;border-radius:0 0 7px 7px;padding:14px;margin-top:-6px}
.expand.open{display:block}
.plan-loading{text-align:center;padding:20px;color:var(--muted);font-size:12px}
.spin{display:inline-block;width:13px;height:13px;border:2px solid var(--border2);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite;margin-right:7px;vertical-align:middle}
@keyframes spin{to{transform:rotate(360deg)}}
/* ACTION PLAN */
.plan-ctx{background:var(--bg4);border:1px solid var(--border2);border-radius:4px;padding:5px 12px;font-size:10px;font-family:'IBM Plex Mono',monospace;color:var(--muted);margin-bottom:10px}
.plan-header{display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap}
.call-lbl{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:var(--muted);font-family:'IBM Plex Mono',monospace}
.pri-tag{padding:2px 8px;border-radius:3px;font-size:10px;font-family:'IBM Plex Mono',monospace;font-weight:600}
.pri-high{background:#1c0a0a;color:var(--red);border:1px solid #3d1010}
.pri-medium{background:#1c1308;color:var(--amber);border:1px solid #3d2808}
.pri-low{background:#071a10;color:var(--green);border:1px solid #0d3520}
/* Inactivity box */
.inact-box{background:var(--bg4);border-radius:6px;padding:8px 12px;margin-bottom:8px;display:flex;align-items:center;gap:10px;border-left:3px solid var(--orange)}
.inact-box.ok{border-left-color:var(--green)}.inact-box.warn{border-left-color:var(--amber)}.inact-box.hot{border-left-color:var(--red)}
.inact-days{font-size:22px;font-weight:700;font-family:'IBM Plex Mono',monospace}
.inact-lbl{font-size:10px;color:var(--muted)}
/* Data blocks */
.data-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-bottom:8px}
.dblk{background:var(--bg4);border-radius:6px;padding:9px 11px;border-left:3px solid var(--border2)}
.dblk.wide2{grid-column:span 2}.dblk.wide4{grid-column:span 4}
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
/* Priority grid */
.p-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:7px;margin-bottom:8px}
.p-blk{background:var(--bg4);border-radius:5px;padding:8px 10px;border:1px solid var(--border)}
.p-blk-0{border-left:3px solid var(--red)}.p-blk-1{border-left:3px solid var(--amber)}.p-blk-2{border-left:3px solid var(--green)}
.p-lbl{font-size:9px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:5px;font-weight:700;font-family:'IBM Plex Mono',monospace}
.p-item{font-size:11px;padding:2px 0;font-family:'IBM Plex Mono',monospace;display:flex;gap:5px}
.p-item::before{content:"→";flex-shrink:0}
/* Assignment + playlist recommendation section */
.rec-extra{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:7px}
.rec-card{background:var(--bg3);border-radius:5px;padding:7px 10px;border:1px solid var(--border)}
.rec-card-title{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);font-family:'IBM Plex Mono',monospace;margin-bottom:5px}
/* SM Questions */
.sm-block{background:var(--bg4);border-radius:6px;padding:10px 12px;margin-bottom:8px;border-left:3px solid var(--purple)}
.sm-title{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:var(--purple);font-family:'IBM Plex Mono',monospace;margin-bottom:8px}
.sm-q{font-size:12px;padding:5px 0;border-bottom:1px solid var(--border);display:flex;gap:9px;align-items:flex-start}
.sm-q:last-child{border:none}
.sm-qn{color:var(--purple);font-size:10px;font-family:'IBM Plex Mono',monospace;font-weight:600;flex-shrink:0;margin-top:2px}
.imm-action{margin-top:8px;padding:7px 11px;background:var(--bg3);border-radius:4px;font-size:12px;color:var(--accent);font-family:'IBM Plex Mono',monospace;border:1px solid var(--border2)}
.token-mini{font-size:10px;color:var(--muted);font-family:'IBM Plex Mono',monospace;margin-top:8px;padding-top:8px;border-top:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
.regen-btn{background:var(--bg4);border:1px solid var(--border2);color:var(--muted);font-size:10px;padding:3px 10px;border-radius:4px;cursor:pointer;font-family:'IBM Plex Mono',monospace;transition:all .15s}
.regen-btn:hover{border-color:var(--accent);color:var(--accent)}
/* MODAL */
.overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.87);z-index:300;overflow-y:auto;padding:20px}
.overlay.open{display:block}
.modal{background:var(--bg2);border:1px solid var(--border2);border-radius:10px;max-width:940px;margin:0 auto;overflow:hidden}
.modal-hdr{padding:12px 20px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center}
.modal-title{font-size:14px;font-weight:600}.modal-sub{font-size:11px;color:var(--muted);margin-top:2px;font-family:'IBM Plex Mono',monospace}
.close-btn{background:none;border:none;color:var(--muted);font-size:22px;cursor:pointer;line-height:1;padding:0 4px}
.modal-body{padding:14px 20px}
/* Stats row with inactivity */
.stats-row{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:12px}
.stat-box{background:var(--bg3);border-radius:6px;padding:10px;text-align:center;border:1px solid var(--border)}
.stat-v{font-size:16px;font-weight:700;font-family:'IBM Plex Mono',monospace}.stat-l{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-top:3px}
/* Modal tabs */
.mtabs{display:flex;border-bottom:1px solid var(--border);margin-bottom:12px;overflow-x:auto;gap:0}
.mtab{padding:6px 13px;font-size:11px;font-weight:500;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;transition:all .15s;white-space:nowrap;flex-shrink:0}
.mtab:hover{color:var(--text)}.mtab.active{color:var(--accent);border-bottom-color:var(--accent)}
.tpanel{display:none}.tpanel.active{display:block}
/* Assignment table enhancements */
.asgn-summary{display:grid;grid-template-columns:repeat(6,1fr);gap:6px;margin-bottom:10px}
.as-box{background:var(--bg3);border-radius:5px;padding:7px;text-align:center;border:1px solid var(--border)}
.as-v{font-size:15px;font-weight:700;font-family:'IBM Plex Mono',monospace}
.as-l{font-size:9px;color:var(--muted);text-transform:uppercase;margin-top:2px}
.dtbl{width:100%;border-collapse:collapse;font-size:11px}
.dtbl th{padding:6px 10px;text-align:left;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.4px;border-bottom:1px solid var(--border);font-family:'IBM Plex Mono',monospace;cursor:pointer;user-select:none;white-space:nowrap}
.dtbl th:hover{color:var(--text)}.dtbl th.sa::after{content:" ↑";color:var(--accent)}.dtbl th.sd::after{content:" ↓";color:var(--accent)}
.dtbl td{padding:6px 10px;border-bottom:1px solid var(--border);vertical-align:middle}
.dtbl tr:last-child td{border:none}.dtbl tbody tr:hover td{background:var(--bg4)}
.type-learn{color:var(--teal);font-size:9px;font-family:'IBM Plex Mono',monospace;background:var(--bg4);padding:2px 5px;border-radius:3px}
.type-app{color:var(--amber);font-size:9px;font-family:'IBM Plex Mono',monospace;background:var(--bg4);padding:2px 5px;border-radius:3px}
.sbar{display:flex;align-items:center;gap:5px}
.sbar-bg{width:40px;height:4px;background:var(--border2);border-radius:2px}.sbar-fill{height:100%;border-radius:2px}
.na-tag{font-size:9px;color:var(--orange);font-family:'IBM Plex Mono',monospace;margin-left:4px}
.quick-tag{font-size:9px;color:var(--red);font-family:'IBM Plex Mono',monospace;margin-left:4px;cursor:help}
.slow-tag{font-size:9px;color:var(--amber);font-family:'IBM Plex Mono',monospace;margin-left:4px}
.att-Live{color:var(--green)}.att-Recorded{color:var(--amber)}.att-Absent{color:var(--red)}
/* Contest cards - normalized /100 */
.ct-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
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
/* Playlist */
.pl-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}
.pl-card{background:var(--bg3);border-radius:6px;border:1px solid var(--border);padding:10px 12px}
.pl-title{font-size:11px;font-weight:600;margin-bottom:5px}
.pl-meta{display:flex;gap:10px;margin-bottom:6px;font-size:10px;font-family:'IBM Plex Mono',monospace;color:var(--muted);flex-wrap:wrap}
.pl-qs{list-style:none}
.pl-qs li{font-size:10px;padding:2px 0;border-bottom:1px solid var(--border);color:var(--text);font-family:'IBM Plex Mono',monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pl-qs li:last-child{border:none}
.pl-prog-bar{height:4px;background:var(--border2);border-radius:2px;margin-top:5px}
.pl-prog-fill{height:100%;border-radius:2px}
/* Lecture table */
.lec-feedback-pill{display:inline-block;font-size:9px;padding:1px 6px;border-radius:3px;font-family:'IBM Plex Mono',monospace;background:var(--bg4);color:var(--muted)}
/* Project */
.proj-card{background:var(--bg3);border-radius:7px;border:1px solid var(--border);padding:12px 14px}
.proj-title{font-size:13px;font-weight:600;margin-bottom:8px}
.proj-row{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border);font-size:11px}
.proj-row:last-child{border:none}.proj-k{color:var(--muted)}.proj-v{font-family:'IBM Plex Mono',monospace;font-weight:500}
.proj-note{margin-top:10px;padding:8px 10px;background:var(--bg4);border-radius:4px;font-size:11px;color:var(--amber);font-family:'IBM Plex Mono',monospace;border-left:3px solid var(--amber)}
.sess-empty{text-align:center;padding:20px;color:var(--muted);font-size:12px;font-family:'IBM Plex Mono',monospace}
/* Batch page */
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
    <span style="font-size:9px;color:var(--muted);margin-left:4px;font-family:'IBM Plex Mono',monospace">v5</span>
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
    <select class="fsel" id="tierF" onchange="filter()">
      <option value="">All Tiers</option>
      <option>High Risk</option><option>Medium Risk</option><option>Low Risk</option><option>Strong</option>
    </select>
    <select class="fsel" id="phaseF" onchange="filter()">
      <option value="">All Phases</option>
      <option value="1">Phase 1</option><option value="2">Phase 2</option>
      <option value="3">Phase 3</option><option value="4">Phase 4</option>
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

<!-- INFO MODAL -->
<div class="overlay" id="infoModal" onclick="closeInfo(event)">
  <div class="modal">
    <div class="modal-hdr">
      <div><div class="modal-title" id="infoTitle"></div><div class="modal-sub" id="infoSub"></div></div>
      <button class="close-btn" onclick="closeInfo()">×</button>
    </div>
    <div class="modal-body" id="infoBody"></div>
  </div>
</div>

<!-- TOKEN MODAL -->
<div class="overlay" id="tokenModal" onclick="closeToken(event)">
  <div class="modal" style="max-width:620px">
    <div class="modal-hdr">
      <div><div class="modal-title">Token Usage & Cost</div><div class="modal-sub">GPT-4o Mini · $0.15/1M in · $0.60/1M out</div></div>
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
let _curSt=null;

// Helpers
function rc(r){return r>=75?'var(--red)':r>=55?'var(--amber)':r>=35?'var(--green)':'var(--teal)'}
function bc(p){return p>=75?'var(--green)':p>=50?'var(--amber)':'var(--red)'}
function ts(t){if(t==='High Risk')return 'background:#1c0a0a;color:var(--red);border:1px solid #3d1010';if(t==='Medium Risk')return 'background:#1c1308;color:var(--amber);border:1px solid #3d2808';if(t==='Low Risk')return 'background:#071a10;color:var(--green);border:1px solid #0d3520';return 'background:#061416;color:var(--teal);border:1px solid #0d2e30'}
function rsc(t){if(t==='High Risk')return 'var(--red)';if(t==='Medium Risk')return 'var(--amber)';if(t==='Low Risk')return 'var(--green)';return 'var(--teal)'}
function inactClass(d){if(d>=14) return 'hot';if(d>=7) return 'warn';return 'ok'}
function inactBadge(d){if(d>=999) return 'Never active';if(d>=14) return d+'d inactive';if(d>=7) return d+'d ago';return d===0?'Active today':d+'d ago'}

// Page switch
function showPage(id,el){
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(t=>t.classList.remove('active'));
  document.getElementById('page-'+id).classList.add('active'); el.classList.add('active');
  if(id==='batch') renderBatch();
}

// Init filters
function initFilters(){
  const batches=[...new Set(STUDS.map(s=>s.batch))];
  const sel=document.getElementById('batchF');
  batches.forEach(b=>{const o=document.createElement('option');o.value=b;o.textContent=b.replace(' Spreadsheets - ','·').replace(' 2026','');sel.appendChild(o);});
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
  const tier=document.getElementById('tierF').value;
  const phase=document.getElementById('phaseF').value;
  const inact=document.getElementById('inactF').value;
  filtered=STUDS.filter(s=>{
    if(q&&!s.name.toLowerCase().includes(q)&&!s.email.toLowerCase().includes(q)) return false;
    if(batch&&s.batch!==batch) return false;
    if(tier&&s.tier!==tier) return false;
    if(phase&&String(s.mods?.Spreadsheets?.current_phase||'')!==phase) return false;
    if(inact==='hot'&&(s.days_inactive||0)<14) return false;
    if(inact==='warn'&&(s.days_inactive||0)<7) return false;
    return true;
  });
  filtered.sort((a,b)=>b.risk-a.risk);
  document.getElementById('cntLbl').textContent=filtered.length+' students';
  buildStrip(filtered);
  renderList();
}

function renderList(){
  const el=document.getElementById('studentList');
  if(!filtered.length){el.innerHTML='<div class="empty">No students match filters</div>';return;}
  el.innerHTML=filtered.map(s=>{
    const ph=s.mods?.Spreadsheets?.current_phase||'?';
    const cl=s.mods?.Spreadsheets?.current_class||'?';
    const di=s.days_inactive||0;
    const ic=inactClass(di);
    return `<div>
      <div class="scard" id="card-${s.id}" onclick="toggleCard(${s.id})">
        <div class="risk-bar" style="background:${rsc(s.tier)}"></div>
        <div class="batch-tag">${s.batch.replace(' Spreadsheets - ','·').replace(' 2026','')}</div>
        <div class="sinfo">
          <div class="sname">${s.name}</div>
          <div class="semail">${s.email}</div>
        </div>
        <div class="sreason">${s.reason||''}</div>
        <div class="inact-badge inact-${ic}">${inactBadge(di)}</div>
        <span style="font-size:9px;color:var(--muted);font-family:'IBM Plex Mono',monospace;background:var(--bg4);padding:2px 6px;border-radius:3px;white-space:nowrap">Ph${ph} E${cl}</span>
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
  if(planCache[id]) showPlan(id,planCache[id].plan,planCache[id].tok); else fetchPlan(id);
}

async function fetchPlan(id){
  try{
    const r=await fetch('/api/action-plan/'+id);
    const d=await r.json();
    if(d.error) throw new Error(d.error);
    planCache[id]={plan:d.plan,tok:d.token_usage};
    showPlan(id,d.plan,d.token_usage);
  }catch(e){document.getElementById('ld-'+id).innerHTML=`<span style="color:var(--red)">Error: ${e.message}</span>`;}
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
  const el=document.getElementById('plan-'+id); el.style.display='block';
  const s=STUDS.find(x=>x.id===id)||{};
  const di=s.days_inactive||0;
  const A=plan.attendance||{},G=plan.assignment||{},M=plan.mc_score||{},PJ=plan.project||{},R=plan.recommendation||{},Q=plan.sm_questions||{};
  const fl=f=>`fl-${f||'ok'}`;

  // Inactivity box
  const ic=inactClass(di);
  const icColor=ic==='hot'?'var(--red)':ic==='warn'?'var(--amber)':'var(--green)';
  const inactBlock=`<div class="inact-box ${ic}" style="margin-bottom:8px">
    <div class="inact-days" style="color:${icColor}">${di>=999?'—':di+'d'}</div>
    <div>
      <div style="font-size:11px;font-weight:600;color:${icColor}">${di>=999?'Never active':di===0?'Active today':di+' days since last activity'}</div>
      <div class="inact-lbl">Last solve: ${s.mods?.Spreadsheets?.last_solve||'—'} &nbsp;|&nbsp; Assignment: ${s.avg_asgn||0}% (${s.asgn_solved||0}/${s.asgn_total||0} Qs) &nbsp;|&nbsp; Attendance: ${s.avg_att||0}%</div>
    </div>
  </div>`;

  // Attendance block — compact when no issues, full when flagged
  const attMissed = A.missed_count||0;
  const attFlag = A.flag||'ok';
  const attColor = attFlag==='critical'?'var(--red)':attFlag==='warn'?'var(--amber)':'var(--green)';
  const showFullAtt = attFlag!=='ok' || attMissed > 0;
  const attBlock = showFullAtt
    ? `<div class="dblk ${fl(attFlag)}">
        <div class="blk-title"><span class="flag-dot"></span>📅 ATTENDANCE</div>
        <div class="dr"><span class="dk">Overall</span><span class="dv" style="color:${attColor}">${s.avg_att||0}%</span></div>
        <div class="dr"><span class="dk">Missed</span><span class="dv" style="color:${attColor}">${attMissed} classes</span></div>
        ${A.note?`<div class="dr"><span class="dk">Note</span><span class="dv" style="font-size:10px">${A.note}</span></div>`:''}
        ${(A.last3||[]).length?`<ul class="blist" style="margin-top:5px">${(A.last3||[]).map(l=>`<li style="font-size:10px">${l}</li>`).join('')}</ul>`:''}
      </div>`
    : `<div class="dblk fl-ok" style="display:flex;align-items:center;gap:10px;padding:8px 12px">
        <span class="flag-dot" style="background:var(--green);flex-shrink:0"></span>
        <span style="font-size:10px;font-family:'IBM Plex Mono',monospace;color:var(--muted)">📅 ATTENDANCE</span>
        <span style="font-size:14px;font-weight:700;font-family:'IBM Plex Mono',monospace;color:var(--green)">${s.avg_att||0}%</span>
        <span style="font-size:10px;color:var(--green)">— No concerns</span>
        ${attMissed>0?`<span style="font-size:10px;color:var(--amber);margin-left:auto">${attMissed} missed</span>`:''}
      </div>`;

  const uns=(G.unsolved_topics||[]),na=(G.not_attempted_topics||[]);
  const asgnBlock=`<div class="dblk ${fl(G.flag)}">
    <div class="blk-title"><span class="flag-dot"></span>📝 ASSIGNMENT</div>
    <div class="dr"><span class="dk">Completion</span><span class="dv">${G.completion||'—'}</span></div>
    <div class="dr"><span class="dk">Last solved</span><span class="dv">${G.last_solved||'—'}</span></div>
    ${G.est_pct_if_completed?`<div class="dr"><span class="dk">If unsolved done</span><span class="dv" style="color:var(--green)">${G.est_pct_if_completed}</span></div>`:''}
    ${uns.length?`<div style="margin-top:5px"><div style="font-size:9px;color:var(--muted);margin-bottom:2px;font-family:'IBM Plex Mono',monospace">UNSOLVED</div><ul class="blist red">${uns.map(t=>`<li>${t}</li>`).join('')}</ul></div>`:''}
    ${na.length?`<div style="margin-top:5px"><div style="font-size:9px;color:var(--muted);margin-bottom:2px;font-family:'IBM Plex Mono',monospace">NOT ATTEMPTED</div><ul class="blist amber">${na.map(t=>`<li>${t}</li>`).join('')}</ul></div>`:''}

    ${G.quick_solve_flag?`<div style="margin-top:5px;padding:4px 8px;background:#1c0a0a;border-radius:3px;border-left:2px solid var(--red);font-size:10px;font-family:'IBM Plex Mono',monospace;color:var(--red)">⚠ Quick solve: ${G.quick_solve_flag}</div>`:''}
  </div>`;

  const pj_col=PJ.flag==='ok'?'var(--green)':PJ.flag==='warn'?'var(--amber)':'var(--red)';
  // Pull actual submission history from student data
  const projData = s.mods?.Spreadsheets?.project;
  const projHist = projData?.submission_history||[];
  const projHistHtml = projHist.length ? projHist.map(h=>{
    const sc = h.marks!=null ? h.marks : null;
    const scCol = sc==null?'var(--muted)':sc>=8?'var(--green)':sc>=5?'var(--amber)':'var(--red)';
    return `<div class="dr">
      <span class="dk">Sub ${h.submission} — ${h.date||''}</span>
      <span class="dv" style="color:${scCol};font-size:13px;font-weight:700">${sc!=null?sc+'/10':'Pending evaluation'}</span>
    </div>`;
  }).join('') : '';
  const projBlock=`<div class="dblk ${fl(PJ.flag)}">
    <div class="blk-title"><span class="flag-dot"></span>📁 PROJECT</div>
    ${projHist.length ? projHistHtml : `<div class="dr"><span class="dk">Status</span><span class="dv" style="color:${pj_col};font-size:10px">${PJ.status||'—'}</span></div>`}
    ${projHist.length && projData?.feedback_count ? `<div class="dr"><span class="dk">Feedbacks</span><span class="dv" style="color:var(--amber)">${projData.feedback_count} received — last ${projData.last_feedback||'?'}</span></div>` : ''}
    ${PJ.action?`<div style="margin-top:5px;padding:5px 8px;background:var(--bg3);border-radius:3px;font-size:10px;font-family:'IBM Plex Mono',monospace;color:var(--amber);border-left:2px solid var(--amber)">▶ ${PJ.action}</div>`:''}
  </div>`;

  // MC block — show normalized /100
  const mcBlock=`<div class="dblk ${fl(M.flag)}">
    <div class="blk-title"><span class="flag-dot"></span>🏆 MC CONTESTS (normalized /100, clearance=64)</div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:10px">
      <div><div class="dk">Mid MC</div><div class="dv" style="font-size:14px;color:${M.mid_mc&&!M.mid_mc.includes('not')&&!M.mid_mc.includes('Not')?parseFloat(M.mid_mc)>=64?'var(--green)':'var(--red)':'var(--muted)'}">${M.mid_mc||'—'}</div></div>
      <div><div class="dk">MC Attempt 1</div><div class="dv" style="font-size:14px;color:${M.mc1&&!M.mc1.includes('not')&&!M.mc1.includes('Not')?parseFloat(M.mc1)>=64?'var(--green)':'var(--amber)':'var(--muted)'}">${M.mc1||'—'}</div></div>
      <div><div class="dk">MC Attempt 2</div><div class="dv" style="font-size:14px;color:${M.mc2&&!M.mc2.includes('not')&&!M.mc2.includes('Not')?parseFloat(M.mc2)>=64?'var(--green)':'var(--amber)':'var(--muted)'}">${M.mc2||'—'}</div></div>
      <div><div class="dk">Next Action</div><div class="dv" style="font-size:10px;color:var(--amber)">${M.next_action||'—'}</div></div>
    </div>
  </div>`;

  const p0=R.p0||{},p1=R.p1||{},p2=R.p2||{};
  const atop=R.assignment_topics_to_solve||[];
  const plrec=R.playlist_recommendation||[];

  const recBlock=`<div class="dblk" style="grid-column:1/-1;border-left-color:var(--accent);background:var(--bg4);border-radius:6px;padding:9px 11px">
    <div class="blk-title" style="color:var(--accent)">▶ RECOMMENDATION</div>
    <div class="p-grid">
      <div class="p-blk p-blk-0">
        <div class="p-lbl" style="color:var(--red)">P0 — ${p0.label||'Critical'}</div>
        ${(p0.items||[]).map(i=>`<div class="p-item" style="color:var(--red)">${i}</div>`).join('')}
      </div>
      <div class="p-blk p-blk-1">
        <div class="p-lbl" style="color:var(--amber)">P1 — ${p1.label||'Important'}</div>
        ${(p1.items||[]).map(i=>`<div class="p-item" style="color:var(--amber)">${i}</div>`).join('')}
      </div>
      <div class="p-blk p-blk-2">
        <div class="p-lbl" style="color:var(--green)">P2 — ${p2.label||'Monitor'}</div>
        ${(p2.items||[]).map(i=>`<div class="p-item" style="color:var(--green)">${i}</div>`).join('')}
      </div>
    </div>
    ${(atop.length||plrec.length)?`<div class="rec-extra">
      ${atop.length?`<div class="rec-card">
        <div class="rec-card-title">📝 Assignments to Solve → Estimated % Gain</div>
        <ul class="blist blue">${atop.map(t=>`<li>${t}</li>`).join('')}</ul>
      </div>`:''}
      ${plrec.length?`<div class="rec-card">
        <div class="rec-card-title">🎵 Recommended Playlists</div>
        <ul class="blist green">${plrec.map(t=>`<li>${t}</li>`).join('')}</ul>
      </div>`:''}
    </div>`:''}
    ${R.immediate_action?`<div class="imm-action">▶ ${R.immediate_action}</div>`:''}
  </div>`;

  const qKeys=Object.keys(Q).filter(k=>Q[k]);
  const smBlock=qKeys.length?`<div class="sm-block">
    <div class="sm-title">💬 SM Call Questions</div>
    ${qKeys.map((k,i)=>`<div class="sm-q"><span class="sm-qn">Q${i+1}</span><span>${Q[k]}</span></div>`).join('')}
  </div>`:'';

  el.innerHTML=`
    <div class="plan-ctx">${plan.phase_context||''}</div>
    <div class="plan-header">
      <span class="call-lbl">${plan.call_type||'SM Call'}</span>
      <span class="pri-tag pri-${plan.priority||'medium'}">Priority: ${plan.priority||'—'}</span>
    </div>
    ${inactBlock}
    <div class="data-grid" style="grid-template-columns:1fr 1fr;grid-template-rows:auto auto">${attBlock}${asgnBlock}${mcBlock}${projBlock}</div>
    ${recBlock}
    ${smBlock}
    <div class="token-mini">
      <span>${tok?`GPT-4o Mini · ${tok.in} in + ${tok.out} out · $${tok.cost}`:''}</span>
      <button class="regen-btn" onclick="regenPlan(${id})">↻ Regenerate</button>
    </div>`;
}

// ── INFO MODAL ──
function openInfo(e,id){
  e.stopPropagation();
  const s=STUDS.find(x=>x.id===id); if(!s) return;
  _curSt=s; _plLoaded=false; _plData=[];
  document.getElementById('infoTitle').textContent=s.name;
  document.getElementById('infoSub').textContent=s.email+' · '+s.batch;
  const mod=s.mods?.Spreadsheets||{};
  const mc=s.avg_mc||0;
  const di=s.days_inactive||0;

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

    <!-- ASSIGNMENT TAB: merged topics, summary bar, filters -->
    <div class="tpanel active" id="tab-asgn">
      <div class="frow">
        <label>Type</label>
        <select id="qType" onchange="renderAsgn()"><option value="all">All</option><option value="Learn">📘 Learning</option><option value="App">📝 Application</option></select>
        <select id="qTopic" onchange="renderAsgn()"><option value="">All Topics</option>${topics.map(t=>`<option>${t}</option>`).join('')}</select>
        <select id="qDiff" onchange="renderAsgn()"><option value="">All Difficulty</option><option>Beginner</option><option>Easy</option><option>Medium</option><option>Hard</option></select>
        <label>From</label><input type="date" id="qFrom" onchange="renderAsgn()">
        <label>To</label><input type="date" id="qTo" onchange="renderAsgn()">
        <button class="reset-btn" onclick="resetAsgnFilters()">Reset</button>
        <span class="row-count" id="asgnCount"></span>
      </div>
      <!-- Summary stat bar -->
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

    <!-- PLAYLIST -->
    <div class="tpanel" id="tab-playlist">
      <div class="frow">
        <select id="plFilter" onchange="renderPlaylistTab()"><option value="">All Playlists</option></select>
        <select id="plStatus" onchange="renderPlaylistTab()"><option value="">All Status</option><option value="solved">Solved</option><option value="unsolved">Unsolved</option><option value="not_attempted">Not Attempted</option></select>
        <button class="reset-btn" onclick="resetPlFilters()">Reset</button>
        <span class="row-count" id="plCount"></span>
      </div>
      <div class="asgn-summary" id="plSummary"></div>
      <table class="dtbl"><thead><tr>
        <th onclick="sortPL('playlist_name',this)" class="sa">Playlist</th>
        <th onclick="sortPL('question_title',this)">Question</th>
        <th onclick="sortPL('status',this)">Status</th>
        <th onclick="sortPL('score',this)">Score</th>
        <th onclick="sortPL('attempts',this)">Attempts</th>
        <th onclick="sortPL('time_taken_mins',this)">Time Taken</th>
        <th onclick="sortPL('solved_at',this)">Solved At</th>
      </tr></thead><tbody id="plBody"><tr><td colspan="7" style="text-align:center;color:var(--muted);padding:20px">Select a student to load playlist data</td></tr></tbody></table>
    </div>

    <!-- LECTURES -->
    <div class="tpanel" id="tab-lec">
      <table class="dtbl"><thead><tr><th>Date</th><th>Lecture</th><th>Type</th><th>Watch %</th><th>Feedback</th></tr></thead>
      <tbody>${(mod.lectures||[]).length?
        (mod.lectures||[]).map(l=>`<tr>
          <td class="mono">${l.date}</td>
          <td style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${l.title}</td>
          <td class="att-${l.type}">${l.type}</td>
          <td class="mono" style="color:${l.type==='Live'?'var(--green)':l.watch_pct>=70?'var(--green)':l.watch_pct>=40?'var(--amber)':'var(--red)'}">${l.watch_pct?l.watch_pct+'%':'—'}</td>
          <td>${l.feedback?`<span class="lec-feedback-pill">${l.feedback}</span>`:'<span style="color:var(--muted);font-size:10px">—</span>'}</td>
        </tr>`).join(''):
        '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:20px">No lecture data</td></tr>'
      }</tbody></table>
    </div>

    <!-- TA SESSIONS -->
    <div class="tpanel" id="tab-ta">
      ${renderSessions(mod.ta_sessions||[],'TA Doubt Sessions')}
    </div>

    <!-- MENTOR -->
    <div class="tpanel" id="tab-mentor">
      ${renderSessions(mod.mentor_sessions||[],'Mentor Connect Sessions')}
    </div>

    <!-- CONTESTS - normalized /100 with full breakdown -->
    <div class="tpanel" id="tab-contests">
      ${renderContests(mod.contests||{})}
    </div>

    <!-- PROJECT -->
    <div class="tpanel" id="tab-project">
      ${renderProject(mod.project)}
    </div>`;

  renderAsgn();
  document.getElementById('infoModal').classList.add('open');
}

function resetAsgnFilters(){
  document.getElementById('qType').value='all';
  document.getElementById('qTopic').value='';
  document.getElementById('qDiff').value='';
  document.getElementById('qFrom').value='';
  document.getElementById('qTo').value='';
  renderAsgn();
}

// ── PLAYLIST TAB ──
let _plData = [];
let plSort = {key:'playlist_name', dir:1};

async function loadPlaylistData(studentId){
  const body = document.getElementById('plBody');
  if(!body) return;
  body.innerHTML='<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:20px"><span class="spin"></span> Loading...</td></tr>';
  try{
    const resp = await fetch('/api/playlist-attempts?student_id='+studentId);
    const data = await resp.json();
    _plData = data.rows || [];
    // Populate playlist filter
    const pf = document.getElementById('plFilter');
    if(pf){
      const names = [...new Set(_plData.map(r=>r.playlist_name).filter(Boolean))].sort();
      pf.innerHTML='<option value="">All Playlists</option>'+names.map(n=>`<option>${n}</option>`).join('');
    }
    renderPlaylistTab();
  } catch(err){
    if(body) body.innerHTML=`<tr><td colspan="7" style="text-align:center;color:var(--red);padding:20px">Error: ${err.message}</td></tr>`;
  }
}

function resetPlFilters(){
  document.getElementById('plFilter').value='';
  document.getElementById('plStatus').value='';
  renderPlaylistTab();
}

function sortPL(key,th){
  document.querySelectorAll('#tab-playlist .dtbl th').forEach(t=>t.classList.remove('sa','sd'));
  if(plSort.key===key) plSort.dir*=-1; else{plSort.key=key;plSort.dir=1;}
  th.classList.add(plSort.dir===1?'sa':'sd');
  renderPlaylistTab();
}

function renderPlaylistTab(){
  const plF = document.getElementById('plFilter')?.value||'';
  const stF = document.getElementById('plStatus')?.value||'';
  let rows = [..._plData];
  if(plF) rows=rows.filter(r=>r.playlist_name===plF);
  if(stF==='solved') rows=rows.filter(r=>r.is_solved);
  else if(stF==='unsolved') rows=rows.filter(r=>!r.is_solved && r.attempts>0);
  else if(stF==='not_attempted') rows=rows.filter(r=>!r.attempts||r.attempts===0);

  rows.sort((a,b)=>{
    let va=a[plSort.key]??'', vb=b[plSort.key]??'';
    if(typeof va==='number') return plSort.dir*(va-vb);
    return plSort.dir*String(va).localeCompare(String(vb));
  });

  // Summary stats
  const total=rows.length;
  const solved=rows.filter(r=>r.is_solved).length;
  const attempted=rows.filter(r=>(r.attempts||0)>0).length;
  const notAtt=rows.filter(r=>!r.attempts||r.attempts===0).length;
  const pct=total>0?Math.round(solved/total*100):0;
  const times=rows.filter(r=>r.time_taken_mins>0&&r.is_solved).map(r=>r.time_taken_mins);
  const avgTime=times.length?Math.round(times.reduce((a,b)=>a+b,0)/times.length):null;
  const quick=rows.filter(r=>r.time_taken_mins>0&&r.time_taken_mins<3&&r.is_solved).length;

  document.getElementById('plCount').textContent=`${total} questions · ${solved} solved`;
  document.getElementById('plSummary').innerHTML=`
    <div class="as-box"><div class="as-v" style="color:${pct>=75?'var(--green)':pct>=50?'var(--amber)':'var(--red)'}">${solved}/${total}</div><div class="as-l">Solved</div></div>
    <div class="as-box"><div class="as-v" style="color:${pct>=75?'var(--green)':pct>=50?'var(--amber)':'var(--red)'}">${pct}%</div><div class="as-l">Completion</div></div>
    <div class="as-box"><div class="as-v">${attempted}</div><div class="as-l">Attempted</div></div>
    <div class="as-box"><div class="as-v" style="color:var(--muted)">${avgTime?avgTime+'m':'—'}</div><div class="as-l">Avg Time</div></div>
    <div class="as-box"><div class="as-v" style="color:${notAtt>0?'var(--orange)':'var(--green)'}">${notAtt}</div><div class="as-l">Not Attempted</div></div>
    <div class="as-box"><div class="as-v" style="color:${quick>0?'var(--red)':'var(--green)'}">${quick}</div><div class="as-l">⚡ Quick (<3m)</div></div>`;

  const body=document.getElementById('plBody'); if(!body) return;
  if(!rows.length){body.innerHTML='<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:18px">No questions match filter</td></tr>';return;}
  body.innerHTML=rows.map(r=>{
    const sc=r.is_solved?'var(--green)':(r.attempts||0)>0?'var(--amber)':'var(--red)';
    const status=r.is_solved?'<span class="clr-y">✓ Solved</span>':(r.attempts||0)>0?'<span style="color:var(--amber);font-size:10px">Attempted</span>':'<span class="na-tag">NOT ATTEMPTED</span>';
    const isQuick=r.time_taken_mins>0&&r.time_taken_mins<3&&r.is_solved;
    const timeCol=isQuick?'var(--red)':'var(--text)';
    const scoreVal=r.score!=null?r.score+(r.max_score?'/'+r.max_score:''):'—';
    return `<tr>
      <td style="max-width:130px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:10px;color:var(--muted)">${r.playlist_name||'—'}</td>
      <td style="max-width:220px">${r.question_title||'—'}</td>
      <td>${status}</td>
      <td class="mono" style="color:${sc}">${scoreVal}</td>
      <td class="mono">${r.attempts||0}</td>
      <td class="mono" style="color:${timeCol}">${r.time_taken_mins>0?r.time_taken_mins+'m':'—'}${isQuick?'<span class="quick-tag">⚡ fast</span>':''}</td>
      <td class="mono" style="color:var(--muted)">${(r.solved_at||'—').slice(0,10)}</td>
    </tr>`;
  }).join('');
}
function renderSessions(sess,label){
  if(!sess||!sess.length) return `<div class="sess-empty">No ${label} on record</div>`;
  return `<table class="dtbl"><thead><tr><th>#</th><th>Date</th><th>Mentor / TA</th><th>Duration</th><th>Rating</th></tr></thead>
    <tbody>${sess.map((s,i)=>`<tr>
      <td class="mono">${i+1}</td><td class="mono">${s.date||'—'}</td><td>${s.mentor||'—'}</td>
      <td class="mono">${s.duration_mins?s.duration_mins+'m':'—'}</td>
      <td class="mono" style="color:${(s.rating||0)>=4?'var(--green)':(s.rating||0)>=3?'var(--amber)':'var(--muted)'}">${s.rating?s.rating+'/5':'—'}</td>
    </tr>`).join('')}</tbody></table>`;
}

function renderContests(conts){
  function norm(c){
    if(!c||c.score==null) return null;
    return c.normalized_score!=null?c.normalized_score:Math.round(c.score/c.max_marks*100*10)/10;
  }
  function card(c,label){
    if(c===null) return `<div class="ct-card"><div class="ct-hdr"><div class="ct-title">${label}</div><span style="font-size:9px;color:var(--muted)">Not held</span></div><div class="ct-nh">Not yet scheduled</div></div>`;
    const n=norm(c);
    if(n===null) return `<div class="ct-card"><div class="ct-hdr"><div class="ct-title">${label}</div><span style="font-size:9px;color:var(--muted)">Not attempted</span></div><div class="ct-nh">Contest held — not attempted</div></div>`;
    const cl=n>=64;
    const scol=cl?'var(--green)':n>=45?'var(--amber)':'var(--red)';
    const mcq=c.mcq||{},cod=c.coding||{};
    const mcqPct=mcq.total>0?Math.round(mcq.correct/mcq.total*100):0;
    return `<div class="ct-card">
      <div class="ct-hdr">
        <div>
          <div class="ct-title">${label}</div>
          <div class="ct-score-label">${c.date||''}</div>
        </div>
        <div style="text-align:right">
          <span class="${cl?'clr-y':'clr-n'}">${cl?'CLEARED':'BELOW 64'}</span>
          <div class="ct-score-100" style="color:${scol}">${n}<span style="font-size:11px;color:var(--muted)">/100</span></div>
        </div>
      </div>
      <div class="ct-body">
        <div class="ct-sect">MCQ Section</div>
        <div class="ct-row"><span class="ct-k">Score</span><span class="ct-v">${mcq.marks||0}/${mcq.max_marks||0} marks</span></div>
        <div class="ct-row"><span class="ct-k">Correct</span><span class="ct-v" style="color:${mcqPct>=70?'var(--green)':mcqPct>=50?'var(--amber)':'var(--red)'}">${mcq.correct||0}/${mcq.total||0} (${mcqPct}%)</span></div>
        <div class="ct-row"><span class="ct-k">Attempted</span><span class="ct-v">${mcq.attempted||0}/${mcq.total||0}</span></div>
        <div class="ct-sect">Coding Section</div>
        <div class="ct-row"><span class="ct-k">Score</span><span class="ct-v">${cod.marks||0}/${cod.max_marks||0} marks</span></div>
        <div class="ct-row"><span class="ct-k">Solved</span><span class="ct-v">${cod.solved!=null?cod.solved:'—'}</span></div>
      </div>
    </div>`;
  }
  // Hierarchy: MC1 or MC2 is the REAL exam. Mid MC = practice/bonus.
  const mc1n=norm(conts.mc1), mc2n=norm(conts.mc2);
  const finalCleared=(mc1n!=null&&mc1n>=64)||(mc2n!=null&&mc2n>=64);
  const statusBanner=finalCleared
    ?`<div style="background:#071a10;border:1px solid #0d3520;border-radius:5px;padding:8px 12px;margin-bottom:10px;font-size:11px;font-family:'IBM Plex Mono',monospace;color:var(--green);display:flex;align-items:center;gap:8px"><span style="font-size:16px">✓</span><span><strong>MODULE CLEARED</strong> — ${mc1n!=null&&mc1n>=64?'MC1: '+mc1n:'MC2: '+mc2n}/100 ≥ 64. Project eligibility confirmed.</span></div>`
    :`<div style="background:#1c0a0a;border:1px solid #3d1010;border-radius:5px;padding:8px 12px;margin-bottom:10px;font-size:11px;font-family:'IBM Plex Mono',monospace;color:var(--amber)">⚠ Module not yet cleared — need MC1 or MC2 ≥ 64/100. Mid MC score is practice only.</div>`;
  return statusBanner+`<div class="ct-grid">
    ${card(conts.mid_mc,'Mid Module Contest (Practice)')}
    ${card(conts.mc1,'Module Contest 1 ← REAL EXAM')}
    ${card(conts.mc2,'Module Contest 2 ← REAL EXAM')}
  </div>`;
}

function renderProject(proj){
  if(!proj) return '<div class="sess-empty">No project submission on record.<br><span style="font-size:10px;margin-top:4px;display:block">Project not yet released for this batch.</span></div>';
  const cl=proj.cleared;
  const col=cl?'var(--green)':proj.submissions>0?'var(--amber)':'var(--red)';
  const hist=proj.submission_history||[];

  // Build submission history table
  const histHtml=hist.length?`
    <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border)">
      <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);font-family:'IBM Plex Mono',monospace;margin-bottom:7px">Submission History</div>
      <table class="dtbl"><thead><tr><th>#</th><th>Date</th><th>Score</th><th>Status</th></tr></thead>
      <tbody>${hist.map(h=>{
        const sc=h.marks!=null?h.marks:null;
        const scCol=sc==null?'var(--muted)':sc>=8?'var(--green)':sc>=5?'var(--amber)':'var(--red)';
        return `<tr>
          <td class="mono">Sub ${h.submission}</td>
          <td class="mono">${h.date||'—'}</td>
          <td class="mono" style="color:${scCol};font-size:14px;font-weight:700">${sc!=null?sc+'/10':'Pending'}</td>
          <td style="font-size:10px;color:var(--muted)">${h.notes||'—'}</td>
        </tr>`;
      }).join('')}</tbody></table>
    </div>`:
    '';

  return `<div class="proj-card">
    <div class="proj-title">${proj.project||'Spreadsheet Project'}</div>
    <div class="proj-row"><span class="proj-k">Question</span><span class="proj-v">${proj.question||'—'}</span></div>
    <div class="proj-row"><span class="proj-k">Release / Deadline</span><span class="proj-v">${proj.release_date||'—'} → ${proj.deadline||'—'}</span></div>
    <div class="proj-row"><span class="proj-k">Total Submissions</span><span class="proj-v">${proj.submissions||0}</span></div>
    <div class="proj-row"><span class="proj-k">Best Score</span><span class="proj-v" style="color:${col};font-size:15px;font-weight:700">${proj.marks??'—'}/${proj.max_marks||10}</span></div>
    <div class="proj-row"><span class="proj-k">Cleared (≥8/10)</span><span class="proj-v" style="color:${col}">${cl?'✓ YES':'✗ NOT CLEARED'}</span></div>
    <div class="proj-row"><span class="proj-k">Feedbacks received</span><span class="proj-v">${proj.feedback_count||0} &nbsp;|&nbsp; Last: ${proj.last_feedback||'—'}</span></div>
    ${proj.note?`<div class="proj-note">⚠ ${proj.note}</div>`:''}
    ${histHtml}
  </div>`;
}

function switchTab(tab,el){
  document.querySelectorAll('.mtab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.tpanel').forEach(p=>p.classList.remove('active'));
  el.classList.add('active'); document.getElementById('tab-'+tab)?.classList.add('active');
  if(tab==='playlist'&&_curSt&&!_plLoaded){
    _plLoaded=true;
    loadPlaylistData(_curSt.id);
  }
}

// Assignment rendering — grouped by topic (not repeated rows for same topic+type)
function renderAsgn(){
  const mod=_curSt?.mods?.Spreadsheets||{};
  const typeF=document.getElementById('qType')?.value||'all';
  const topicF=document.getElementById('qTopic')?.value||'';
  const diffF=document.getElementById('qDiff')?.value||'';
  const fromF=document.getElementById('qFrom')?.value||'';
  const toF=document.getElementById('qTo')?.value||'';

  let rows=[];
  if(typeF==='all') rows=[...(mod.asgn_detail||[]).map(r=>({...r,_t:'Learn'})),...(mod.app_detail||[]).map(r=>({...r,_t:'App'}))];
  else if(typeF==='Learn') rows=(mod.asgn_detail||[]).map(r=>({...r,_t:'Learn'}));
  else rows=(mod.app_detail||[]).map(r=>({...r,_t:'App'}));

  rows=rows.filter(d=>{
    if(topicF&&d.topic!==topicF) return false;
    if(diffF&&d.difficulty!==diffF) return false;
    const ld=(d.last_solved_date||'').slice(0,10);
    if(fromF&&ld&&ld<fromF) return false;
    if(toF&&ld&&ld>toF) return false;
    return true;
  });

  // Sort
  const dO={Beginner:1,Easy:2,Medium:3,Hard:4};
  rows.sort((a,b)=>{
    let va=a[asgnSort.key]??'', vb=b[asgnSort.key]??'';
    if(asgnSort.key==='difficulty') return asgnSort.dir*((dO[va]||0)-(dO[vb]||0));
    if(typeof va==='number') return asgnSort.dir*(va-vb);
    return asgnSort.dir*String(va).localeCompare(String(vb));
  });

  // Summary stats
  const totalRel=rows.reduce((a,r)=>a+r.total_released,0);
  const totalAtt=rows.reduce((a,r)=>a+r.attempted,0);
  const totalSol=rows.reduce((a,r)=>a+r.solved,0);
  const times=rows.filter(r=>r.avg_time_mins!=null&&r.solved>0).map(r=>r.avg_time_mins);
  const avgTime=times.length?Math.round(times.reduce((a,b)=>a+b,0)/times.length):null;
  const notAtt=rows.filter(r=>r.attempted===0&&r.total_released>0).length;
  const slow=rows.filter(r=>r.avg_time_mins>60&&r.solved>0).length;
  const pct=totalRel>0?Math.round(totalSol/totalRel*100):0;
  document.getElementById('asgnCount').textContent=`${rows.length} rows · ${totalSol}/${totalRel} solved · ${avgTime?'avg '+avgTime+'m':''}`;
  document.getElementById('asgnSummary').innerHTML=`
    <div class="as-box"><div class="as-v" style="color:${pct>=75?'var(--green)':pct>=50?'var(--amber)':'var(--red)'}">${totalSol}/${totalRel}</div><div class="as-l">Solved</div></div>
    <div class="as-box"><div class="as-v" style="color:${pct>=75?'var(--green)':pct>=50?'var(--amber)':'var(--red)'}">${pct}%</div><div class="as-l">Completion</div></div>
    <div class="as-box"><div class="as-v">${totalAtt}</div><div class="as-l">Attempted</div></div>
    <div class="as-box"><div class="as-v" style="color:${avgTime&&avgTime>45?'var(--amber)':'var(--green)'}">${avgTime?avgTime+'m':'—'}</div><div class="as-l">Avg Time</div></div>
    <div class="as-box"><div class="as-v" style="color:${notAtt>0?'var(--orange)':'var(--green)'}">${notAtt}</div><div class="as-l">Not Attempted</div></div>
    <div class="as-box"><div class="as-v" style="color:${slow>0?'var(--amber)':'var(--green)'}">${slow}</div><div class="as-l">Slow (>60m)</div></div>`;

  const body=document.getElementById('asgnBody'); if(!body) return;
  if(!rows.length){body.innerHTML=`<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:18px">No data for selection</td></tr>`;return;}

  // Deduplicate by topic — merge Learn + App rows for same topic
  const topicMap=new Map();
  rows.forEach(d=>{
    const key=d.topic;
    if(!topicMap.has(key)){
      topicMap.set(key,{
        topic:d.topic,
        total_released:0,attempted:0,solved:0,
        avg_time_mins:null,_times:[],last_solved_date:null,
        isNA:false,hasQuick:false,hasSlow:false
      });
    }
    const m=topicMap.get(key);
    m.total_released+=d.total_released||0;
    m.attempted+=d.attempted||0;
    m.solved+=d.solved||0;
    if(d.avg_time_mins!=null&&d.solved>0) m._times.push(d.avg_time_mins);
    if(d.last_solved_date&&(!m.last_solved_date||d.last_solved_date>m.last_solved_date)) m.last_solved_date=d.last_solved_date;
    if(d.attempted===0&&d.total_released>0) m.isNA=true;
    if(d.avg_time_mins!=null&&d.avg_time_mins<3&&d.solved>0) m.hasQuick=true;
    if(d.avg_time_mins!=null&&d.avg_time_mins>60&&d.solved>0) m.hasSlow=true;
  });
  const merged=[...topicMap.values()].map(m=>{
    m.avg_time_mins=m._times.length?Math.round(m._times.reduce((a,b)=>a+b,0)/m._times.length):null;
    return m;
  });

  body.innerHTML=merged.map(d=>{
    const pct2=d.total_released>0?Math.round(d.solved/d.total_released*100):0;
    const sc=d.solved===d.total_released&&d.total_released>0?'var(--green)':d.solved>0?'var(--amber)':'var(--red)';
    const timeCol=d.hasQuick?'var(--red)':d.hasSlow?'var(--amber)':'var(--text)';
    const topicDisplay=`${d.topic}${d.isNA?'<span class="na-tag">NOT ATTEMPTED</span>':''}`;
    return `<tr>
      <td style="max-width:260px">${topicDisplay}</td>
      <td class="mono">${d.total_released}</td>
      <td class="mono">${d.attempted}</td>
      <td><div class="sbar"><div class="sbar-bg"><div class="sbar-fill" style="width:${pct2}%;background:${sc}"></div></div><span class="mono" style="color:${sc}">${d.solved}/${d.total_released}</span></div></td>
      <td class="mono" style="color:${timeCol}">${d.avg_time_mins!=null?d.avg_time_mins+'m':'—'}${d.hasQuick?'<span class="quick-tag" title="Solved suspiciously fast — check understanding">⚡ fast</span>':''}${d.hasSlow?'<span class="slow-tag">🐌</span>':''}</td>
      <td class="mono" style="color:var(--muted)">${(d.last_solved_date||'—').slice(0,10)}</td>
    </tr>`;
  }).join('');
}

function sortA(key,th){
  document.querySelectorAll('#tab-asgn .dtbl th').forEach(t=>{t.classList.remove('sa','sd')});
  if(asgnSort.key===key) asgnSort.dir*=-1; else{asgnSort.key=key;asgnSort.dir=1;}
  th.classList.add(asgnSort.dir===1?'sa':'sd');
  renderAsgn();
}

function closeInfo(e){if(!e||e.target===document.getElementById('infoModal'))document.getElementById('infoModal').classList.remove('open');}

// TOKEN MODAL
async function openTokenModal(){
  document.getElementById('tokenModal').classList.add('open');
  const el=document.getElementById('tokenBody'); el.innerHTML='<span class="spin"></span>';
  try{
    const d=await (await fetch('/api/token-usage')).json();
    if(!d.calls){el.innerHTML='<div class="sess-empty">No calls yet</div>';return;}
    el.innerHTML=`<table class="dtbl"><thead><tr><th>Student</th><th>In</th><th>Out</th><th>Cost</th></tr></thead>
      <tbody>${d.breakdown.map(t=>`<tr><td>${t.student}</td><td class="mono">${t.in}</td><td class="mono">${t.out}</td><td class="mono" style="color:var(--green)">$${t.cost}</td></tr>`).join('')}</tbody></table>
    <div style="font-size:12px;font-weight:600;margin-top:10px;padding:10px;background:var(--bg3);border-radius:5px;font-family:'IBM Plex Mono',monospace;text-align:right">${d.calls} calls · <span style="color:var(--green)">$${d.total_cost} total</span></div>`;
  }catch(e){el.innerHTML=`<span style="color:var(--red)">${e.message}</span>`;}
}
function closeToken(e){if(!e||e.target===document.getElementById('tokenModal'))document.getElementById('tokenModal').classList.remove('open');}

// BATCH ANALYTICS
function renderBatch(){
  const batches=[...new Set(STUDS.map(s=>s.batch))];
  const bd=batches.map(b=>{
    const ss=STUDS.filter(s=>s.batch===b);
    const avg=k=>ss.length?Math.round(ss.reduce((a,s)=>a+(s[k]||0),0)/ss.length):0;
    const ph=ss[0]?.mods?.Spreadsheets?.current_phase||'?';
    const cl=ss[0]?.mods?.Spreadsheets?.current_class||'?';
    return {
      name:b,ss,count:ss.length,ph,cl,
      avgRisk:avg('risk'),avgAtt:avg('avg_att'),avgAsgn:avg('avg_asgn'),avgMC:avg('avg_mc'),
      high:ss.filter(s=>s.tier==='High Risk').length,
      cleared:ss.filter(s=>(s.avg_mc||0)>=64).length,
      ghost:ss.filter(s=>(s.avg_att||0)===0).length,
      projCleared:ss.filter(s=>s.proj_passed).length,
      avgInact:Math.round(ss.filter(s=>(s.days_inactive||0)<999).reduce((a,s)=>a+(s.days_inactive||0),0)/Math.max(ss.filter(s=>(s.days_inactive||0)<999).length,1)),
    };
  });

  const metrics=[
    {k:'avgRisk',l:'Avg Risk Score',u:'',lb:true},
    {k:'avgAtt',l:'Avg Attendance',u:'%',lb:false},
    {k:'avgAsgn',l:'Avg Assignment',u:'%',lb:false},
    {k:'avgMC',l:'Avg MC Score',u:'/100',lb:false},
    {k:'high',l:'High Risk Students',u:'',lb:true},
    {k:'cleared',l:'MC Cleared (≥64)',u:'',lb:false},
    {k:'ghost',l:'Ghost Students',u:'',lb:true},
    {k:'projCleared',l:'Project Cleared',u:'',lb:false},
    {k:'avgInact',l:'Avg Days Inactive',u:'d',lb:true},
  ];
  const getBest=(k,lb)=>{const v=bd.map(b=>b[k]);return lb?Math.min(...v):Math.max(...v);};
  const getWorst=(k,lb)=>{const v=bd.map(b=>b[k]);return lb?Math.max(...v):Math.min(...v);};

  const cardsHtml=bd.map(b=>`
    <div class="bc-card">
      <div class="bc-hdr">
        <div class="bc-name">${b.name.replace(' Spreadsheets - ','·').replace(' 2026','')}</div>
        <div class="bc-meta">Ph${b.ph} · E${b.cl} · ${b.count} students</div>
      </div>
      <div class="bc-body">
        ${[['Risk Score',b.avgRisk,b.avgRisk>=75?'var(--red)':b.avgRisk>=55?'var(--amber)':'var(--green)'],['Attendance',b.avgAtt,bc(b.avgAtt)],['Assignment',b.avgAsgn,bc(b.avgAsgn)],['MC Score',b.avgMC,b.avgMC>=64?'var(--green)':b.avgMC>0?'var(--amber)':'var(--red)']].map(([lbl,val,col])=>`
          <div class="bc-bar">
            <div class="bc-bar-lbl">${lbl}</div>
            <div class="bc-bar-bg"><div class="bc-bar-fill" style="width:${Math.min(val,100)}%;background:${col}"></div></div>
            <div class="bc-bar-val" style="color:${col}">${val}</div>
          </div>`).join('')}
        <div class="bc-badges">
          <div class="bc-badge"><div class="bc-bv" style="color:var(--red)">${b.high}</div><div class="bc-bl">High Risk</div></div>
          <div class="bc-badge"><div class="bc-bv" style="color:${b.cleared>0?'var(--green)':'var(--muted)'}">${b.cleared}</div><div class="bc-bl">MC Cleared</div></div>
          <div class="bc-badge"><div class="bc-bv" style="color:${b.ghost>0?'var(--red)':'var(--green)'}">${b.ghost}</div><div class="bc-bl">Ghosts</div></div>
          <div class="bc-badge"><div class="bc-bv" style="color:${b.avgInact>=14?'var(--red)':b.avgInact>=7?'var(--amber)':'var(--green)'}">${b.avgInact}d</div><div class="bc-bl">Avg Inactive</div></div>
        </div>
      </div>
    </div>`).join('');

  const cmpRows=metrics.map(m=>{
    const best=getBest(m.k,m.lb),worst=getWorst(m.k,m.lb);
    return `<tr><td>${m.l}</td>${bd.map(b=>{const v=b[m.k];const isBest=v===best;const isWorst=v===worst&&best!==worst;return `<td class="${isBest?'best':isWorst?'worst':''}">${v}${m.u}</td>`}).join('')}</tr>`;
  }).join('');

  const ctRows=['mid_mc','mc1','mc2'].map(ct=>{
    const labels={mid_mc:'Mid Module Contest',mc1:'MC Attempt 1',mc2:'MC Attempt 2'};
    return `<tr><td>${labels[ct]}</td>${bd.map(b=>{
      const att=b.ss.filter(s=>s.mods?.Spreadsheets?.contests?.[ct]?.normalized_score!=null);
      const clr=att.filter(s=>s.mods?.Spreadsheets?.contests?.[ct]?.normalized_score>=64);
      const nh=b.ss.every(s=>s.mods?.Spreadsheets?.contests?.[ct]===null);
      if(nh) return `<td style="color:var(--muted)">—</td>`;
      if(!att.length) return `<td style="color:var(--muted)">0 attempted</td>`;
      const avg=Math.round(att.reduce((a,s)=>a+(s.mods.Spreadsheets.contests[ct].normalized_score||0),0)/att.length);
      return `<td><span style="font-weight:700">${avg}/100</span> <span style="color:var(--muted);font-size:10px">${clr.length}/${att.length} cleared</span></td>`;
    }).join('')}</tr>`;
  }).join('');

  document.getElementById('batchContent').innerHTML=`
    <div class="batch-hdr">Batch Analytics</div>
    <div class="batch-sub">DS Spreadsheets 2026 · ${STUDS.length} sampled students across ${bd.length} batches</div>
    <div class="bc-grid">${cardsHtml}</div>
    <div class="cmp-section">
      <div class="cmp-hdr">📊 Cross-Batch Comparison <span style="font-size:10px;color:var(--muted);font-weight:400">green=best · red=worst</span></div>
      <table class="cmp-tbl"><thead><tr><th>Metric</th>${bd.map(b=>`<th>${b.name.replace(' Spreadsheets - ','·').replace(' 2026','')}</th>`).join('')}</tr></thead>
      <tbody>${cmpRows}</tbody></table>
    </div>
    <div class="cmp-section">
      <div class="cmp-hdr">🏆 Contest Clearance (normalized /100)</div>
      <table class="cmp-tbl"><thead><tr><th>Contest</th>${bd.map(b=>`<th>${b.name.replace(' Spreadsheets - ','·').replace(' 2026','')}</th>`).join('')}</tr></thead>
      <tbody>${ctRows}</tbody></table>
    </div>`;
}

document.addEventListener('keydown',e=>{if(e.key==='Escape'){document.getElementById('infoModal').classList.remove('open');document.getElementById('tokenModal').classList.remove('open');}});
initFilters(); filter();
</script>
</body></html>"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=False)