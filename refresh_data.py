"""
NS SM Brain Engine — Daily Data Refresh (March 2026 Spreadsheets, 5 students)
Run:  python3 refresh_data.py
Cron: 0 8 * * * cd /path/to/ns_sm_brain && python3 refresh_data.py >> refresh.log 2>&1
"""

import requests, json, datetime, os, sys

# ── CONFIG ────────────────────────────────────────────────────────────────────
METABASE_URL   = "https://metabase-lierhfgoeiwhr.newtonschool.co"
METABASE_EMAIL = os.environ.get("METABASE_EMAIL",    "ashritha.k@newtonschool.co")
METABASE_PASS  = os.environ.get("METABASE_PASSWORD", "H0CcPtgDa3ZN9b")

THRESHOLDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "thresholds.json")
OUTPUT_PATH     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_refresh.json")

# ── March 2026 Spreadsheets batch config ──────────────────────────────────────
BATCH_NAME = "March 2026 Spreadsheets"
BATCH_CFG  = {
    "au_id": 3355,          # Admin course ID — DS Spreadsheets March 2026
    "lu_modules": {
        3356: "Spreadsheets"  # LU course ID → module name
    }
}
EXCLUDED_LABELS = (677, 717, 722)
MAX_STUDENTS    = 5          # Draft: only 5 students

LOG_PREFIX = lambda: f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"

def log(msg):
    print(f"{LOG_PREFIX()} {msg}", flush=True)

# ── METABASE AUTH ─────────────────────────────────────────────────────────────
def get_session_token():
    log(f"Authenticating as {METABASE_EMAIL}...")
    resp = requests.post(
        f"{METABASE_URL}/api/session",
        json={"username": METABASE_EMAIL, "password": METABASE_PASS},
        headers={"Content-Type": "application/json"},
        timeout=30
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Login failed ({resp.status_code}): {resp.text[:200]}")
    token = resp.json().get("id") or resp.json().get("token")
    if not token:
        raise RuntimeError(f"No session token: {resp.text[:200]}")
    log(f"Auth OK. Token: {token[:8]}...")
    return token

def run_query(token, sql, row_limit=1000):
    headers = {"Content-Type": "application/json", "X-Metabase-Session": str(token)}
    payload = {
        "database": 4,
        "type": "native",
        "native": {"query": sql},
        "parameters": []
    }
    resp = requests.post(
        f"{METABASE_URL}/api/dataset",
        json=payload, headers=headers, timeout=120
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Query error: {data['error']}")
    cols = [c["name"] for c in data["data"]["cols"]]
    return [dict(zip(cols, row)) for row in data["data"]["rows"][:row_limit]]

def logout(token):
    try:
        requests.delete(f"{METABASE_URL}/api/session",
                        headers={"X-Metabase-Session": token}, timeout=10)
    except Exception:
        pass

# ── FETCH BATCH DATA ──────────────────────────────────────────────────────────
def fetch_batch_data(token):
    au_id      = BATCH_CFG["au_id"]
    lu_modules = BATCH_CFG["lu_modules"]
    lu_ids     = list(lu_modules.keys())
    lu_list    = ",".join(str(x) for x in lu_ids)
    excl_list  = ",".join(str(x) for x in EXCLUDED_LABELS)

    log(f"Fetching {BATCH_NAME} (AU={au_id}, LU={lu_list})...")

    sql = f"""
WITH excluded AS (
    SELECT DISTINCT cum.user_id
    FROM courses_courseusermapping cum
    JOIN courses_courseuserlabelmapping lm ON lm.course_user_mapping_id = cum.id
        AND lm.label_id IN ({excl_list})
    WHERE cum.status = 8
),
-- Enrolled students in AU (limit to 5 for draft)
students AS (
    SELECT
        cum.user_id   AS id,
        au.first_name || ' ' || au.last_name AS name,
        au.email
    FROM courses_courseusermapping cum
    JOIN auth_user au ON au.id = cum.user_id
    WHERE cum.course_id = {au_id}
      AND cum.status = 8
      AND cum.user_id NOT IN (SELECT user_id FROM excluded)
    ORDER BY cum.id
    LIMIT {MAX_STUDENTS}
),
att AS (
    SELECT cum.user_id, lm.lu_id,
        ROUND(COUNT(DISTINCT vslcur.lecture_id) FILTER (
            WHERE vslcur.report_type=4
               OR (vslcur.report_type=3
                   AND EXTRACT(EPOCH FROM vslcur.total_duration)*100.0
                       /NULLIF(EXTRACT(EPOCH FROM(vsl.end_timestamp-vsl.start_timestamp)),0)>=40)
        )*100.0/NULLIF(COUNT(DISTINCT vsl.id),0),1)                AS att_pct,
        COALESCE(ROUND(SUM(EXTRACT(EPOCH FROM vslcur.total_duration))
            FILTER(WHERE vslcur.report_type=4)/60.0,0),0)          AS live_mins,
        COUNT(DISTINCT vsl.id)                                      AS total_lec,
        ROUND(COUNT(DISTINCT vslcur.lecture_id) FILTER (
            WHERE vsl.start_timestamp>=NOW()-INTERVAL '14 days'
            AND (vslcur.report_type=4
               OR (vslcur.report_type=3
                   AND EXTRACT(EPOCH FROM vslcur.total_duration)*100.0
                       /NULLIF(EXTRACT(EPOCH FROM(vsl.end_timestamp-vsl.start_timestamp)),0)>=40))
        )*100.0/NULLIF(
            COUNT(DISTINCT vsl.id) FILTER(WHERE vsl.start_timestamp>=NOW()-INTERVAL '14 days'),0
        ),1)                                                        AS att_2w
    FROM (SELECT unnest(ARRAY[{lu_list}]) AS lu_id) lm
    JOIN courses_courseusermapping cum ON cum.course_id=lm.lu_id AND cum.status=8
        AND cum.user_id IN (SELECT id FROM students)
    JOIN video_sessions_lecture vsl ON vsl.course_id=lm.lu_id AND vsl.mandatory=TRUE
    LEFT JOIN video_sessions_lecturecourseusercumulativereport vslcur
        ON vslcur.course_user_mapping_id=cum.id AND vslcur.lecture_id=vsl.id
    GROUP BY 1,2
),
asgn AS (
    SELECT cum.user_id, lm.lu_id,
        COUNT(DISTINCT aaqm.assignment_question_id)                 AS total_q,
        ROUND(COUNT(DISTINCT acuqm.assignment_question_id)
            FILTER(WHERE acuqm.all_test_case_passed=TRUE)*100.0
            /NULLIF(COUNT(DISTINCT aaqm.assignment_question_id),0),1) AS asgn_pct,
        COUNT(DISTINCT acuqm.assignment_question_id)
            FILTER(WHERE acuqm.all_test_case_passed=TRUE AND aq.difficulty_type=1) AS easy,
        COUNT(DISTINCT acuqm.assignment_question_id)
            FILTER(WHERE acuqm.all_test_case_passed=TRUE AND aq.difficulty_type=2) AS med,
        COUNT(DISTINCT acuqm.assignment_question_id)
            FILTER(WHERE acuqm.all_test_case_passed=TRUE AND aq.difficulty_type=3) AS hard,
        COUNT(DISTINCT aacum.id) FILTER(WHERE aacum.late_submission=TRUE) AS late_sub,
        MAX(acuqm.completed_at)::date                               AS last_solve
    FROM (SELECT unnest(ARRAY[{lu_list}]) AS lu_id) lm
    JOIN courses_courseusermapping cum ON cum.course_id=lm.lu_id AND cum.status=8
        AND cum.user_id IN (SELECT id FROM students)
    JOIN assignments_assignmentcourseusermapping aacum ON aacum.course_user_mapping_id=cum.id
    JOIN assignments_assignment aa ON aa.id=aacum.assignment_id AND aa.original_assignment_type=1
    JOIN assignments_assignmentquestionmapping aaqm ON aaqm.assignment_id=aa.id
    JOIN assignments_assignmentquestion aq ON aq.id=aaqm.assignment_question_id
    LEFT JOIN assignments_assignmentcourseuserquestionmapping acuqm
        ON acuqm.assignment_course_user_mapping_id=aacum.id
    GROUP BY 1,2
),
mc AS (
    SELECT cum.user_id, lm.lu_id,
        MAX(cam.marks)          AS mc_best,
        COUNT(DISTINCT cam.id)  AS mc_attempts
    FROM (SELECT unnest(ARRAY[{lu_list}]) AS lu_id) lm
    JOIN courses_courseusermapping cum ON cum.course_id=lm.lu_id AND cum.status=8
        AND cum.user_id IN (SELECT id FROM students)
    JOIN assessments_courseuserassessmentmapping cam
        ON cam.course_user_mapping_id=cum.id AND cam.completed=TRUE
    GROUP BY 1,2
),
proj AS (
    SELECT cum.user_id, lm.lu_id,
        MAX(aacum.marks)          AS proj_best,
        MIN(aacum.marks)          AS proj_first,
        COUNT(DISTINCT aacum.id)  AS proj_subs,
        MAX(CASE WHEN aacum.late_submission THEN 1 ELSE 0 END) AS proj_late
    FROM (SELECT unnest(ARRAY[{lu_list}]) AS lu_id) lm
    JOIN courses_courseusermapping cum ON cum.course_id=lm.lu_id AND cum.status=8
        AND cum.user_id IN (SELECT id FROM students)
    JOIN assignments_assignmentcourseusermapping aacum ON aacum.course_user_mapping_id=cum.id
    JOIN assignments_assignment aa ON aa.id=aacum.assignment_id
        AND aa.assignment_sub_type=6 AND aa.original_assignment_type=1
    GROUP BY 1,2
),
ta AS (
    SELECT cum.user_id, lm.lu_id,
        COUNT(DISTINCT ms.id) AS ta_sessions
    FROM (SELECT unnest(ARRAY[{lu_list}]) AS lu_id) lm
    JOIN courses_courseusermapping cum ON cum.course_id=lm.lu_id AND cum.status=8
        AND cum.user_id IN (SELECT id FROM students)
    JOIN counsellor_tools_meetingschedule ms ON ms.attendee=
        (SELECT email FROM auth_user WHERE id=cum.user_id)
        AND ms.meeting_type='lms_walkthrough_session'
    GROUP BY 1,2
)
SELECT
    s.id, s.name, s.email,
    lm.lu_id,
    COALESCE(a.att_pct,    0) AS att_pct,
    COALESCE(a.live_mins,  0) AS live_mins,
    COALESCE(a.total_lec,  0) AS total_lec,
    COALESCE(a.att_2w,     0) AS att_2w,
    COALESCE(g.total_q,    0) AS total_q,
    COALESCE(g.asgn_pct,   0) AS asgn_pct,
    COALESCE(g.easy,       0) AS easy,
    COALESCE(g.med,        0) AS med,
    COALESCE(g.hard,       0) AS hard,
    COALESCE(g.late_sub,   0) AS late_sub,
    g.last_solve,
    COALESCE(m.mc_best,    0) AS mc_best,
    COALESCE(m.mc_attempts,0) AS mc_attempts,
    COALESCE(p.proj_best,  0) AS proj_best,
    COALESCE(p.proj_first, 0) AS proj_first,
    COALESCE(p.proj_subs,  0) AS proj_subs,
    COALESCE(p.proj_late,  0) AS proj_late,
    COALESCE(t.ta_sessions,0) AS ta_sessions
FROM students s
CROSS JOIN (SELECT unnest(ARRAY[{lu_list}]) AS lu_id) lm
LEFT JOIN att  a ON a.user_id=s.id AND a.lu_id=lm.lu_id
LEFT JOIN asgn g ON g.user_id=s.id AND g.lu_id=lm.lu_id
LEFT JOIN mc   m ON m.user_id=s.id AND m.lu_id=lm.lu_id
LEFT JOIN proj p ON p.user_id=s.id AND p.lu_id=lm.lu_id
LEFT JOIN ta   t ON t.user_id=s.id AND t.lu_id=lm.lu_id
ORDER BY s.name, lm.lu_id
"""

    return run_query(token, sql)

# ── SCORE STUDENTS ────────────────────────────────────────────────────────────
def days_since(d):
    if not d or str(d) in ("None", ""):
        return 999
    try:
        dt = datetime.datetime.fromisoformat(str(d).replace("Z", "+00:00"))
        return (datetime.datetime.now(datetime.timezone.utc) - dt).days
    except Exception:
        return 999

def score_students(rows, thresholds):
    lu_modules = BATCH_CFG["lu_modules"]
    W          = thresholds["risk_weights"]
    T_ATT      = thresholds["attendance"]
    T_ASGN     = thresholds["assignment"]
    T_MC       = thresholds["mc_score"]
    T_PROJ     = thresholds["project"]
    T_TIERS    = thresholds["risk_tiers"]

    # Group rows by student
    students = {}
    for r in rows:
        sid = r["id"]
        if sid not in students:
            students[sid] = {"id": sid, "name": r["name"], "email": r["email"], "mods": {}}
        lu_id = r["lu_id"]
        mod_name = lu_modules.get(lu_id, f"Module {lu_id}")
        students[sid]["mods"][mod_name] = {
            "att":       float(r.get("att_pct")    or 0),
            "live_mins": float(r.get("live_mins")  or 0),
            "att_2w":    float(r.get("att_2w")     or 0),
            "total_lec": int(r.get("total_lec")    or 0),
            "asgn":      float(r.get("asgn_pct")   or 0),
            "total_q":   int(r.get("total_q")      or 0),
            "easy":      int(r.get("easy")         or 0),
            "med":       int(r.get("med")          or 0),
            "hard":      int(r.get("hard")         or 0),
            "late_sub":  int(r.get("late_sub")     or 0),
            "last_solve":r.get("last_solve"),
            "mc_best":   float(r.get("mc_best")    or 0),
            "mc_att":    int(r.get("mc_attempts")  or 0),
            "proj_best": float(r.get("proj_best")  or 0),
            "proj_first":float(r.get("proj_first") or 0),
            "proj_subs": int(r.get("proj_subs")    or 0),
            "proj_late": bool(r.get("proj_late")   or 0),
            "ta":        int(r.get("ta_sessions")  or 0),
        }

    final = []
    for s in students.values():
        mods = s["mods"]
        if not mods:
            continue

        avg_att   = sum(m["att"]      for m in mods.values()) / len(mods)
        avg_asgn  = sum(m["asgn"]     for m in mods.values()) / len(mods)
        mc_scores = [m["mc_best"]     for m in mods.values() if m["mc_best"] > 0]
        avg_mc    = sum(mc_scores) / len(mc_scores) if mc_scores else 0
        proj_sc   = [m["proj_best"]   for m in mods.values() if m["proj_best"] > 0]
        avg_proj  = sum(proj_sc)   / len(proj_sc)   if proj_sc else 0
        total_ta  = max((m["ta"]      for m in mods.values()), default=0)

        active_mods = [m for m in mods.values() if m["total_lec"] > 0]
        min_att_2w  = min((m["att_2w"] for m in active_mods), default=0)

        last_solves   = [m["last_solve"] for m in mods.values()
                         if m["last_solve"] and str(m["last_solve"]) not in ("None","")]
        days_inactive = min(days_since(d) for d in last_solves) if last_solves else 999

        proj_pending = any(m["proj_subs"] == 0 for m in mods.values())
        proj_passed  = any(m["proj_best"] >= T_PROJ["pass_threshold"] for m in mods.values())

        perf = (
            min(avg_att,  100) * W["attendance"]  +
            min(avg_asgn, 100) * W["assignment"]  +
            min(avg_mc,   100) * W["mc_score"]    +
            min(avg_proj * 10, 100) * W["project"]+
            min(total_ta * 5,  100) * W["ta_sessions"]
        )
        risk = round(100 - perf, 1)

        # Determine tier from thresholds config
        tier = "Strong"
        for tier_name, bounds in T_TIERS.items():
            if bounds["min"] <= risk <= bounds["max"]:
                tier = tier_name
                break

        # Risk reason — data-driven, not hardcoded archetype
        reasons = []
        if min_att_2w <= T_ATT["ghost_2w_att_threshold"] and any(m["total_lec"] > 0 for m in mods.values()):
            reasons.append(f"0% attendance last 2 weeks")
        if avg_att < T_ATT["red_threshold"]:
            reasons.append(f"Low attendance ({avg_att:.0f}%)")
        if avg_asgn < T_ASGN["red_threshold"]:
            reasons.append(f"Low assignment completion ({avg_asgn:.0f}%)")
        if mc_scores and avg_mc < T_MC["weak_threshold"]:
            reasons.append(f"MC score {avg_mc:.0f}/100 — below clearance")
        if proj_pending:
            reasons.append("Project not yet submitted")
        if total_ta == 0:
            reasons.append("No TA sessions booked")
        if not reasons:
            if risk < 35:
                reasons.append("Strong performer — placement ready")
            else:
                reasons.append("Moderate engagement — routine check-in")

        final.append({
            "id":            s["id"],
            "name":          s["name"],
            "email":         s["email"],
            "batch":         BATCH_NAME,
            "risk":          risk,
            "tier":          tier,
            "reason":        " · ".join(reasons),
            "avg_att":       round(avg_att,  1),
            "avg_asgn":      round(avg_asgn, 1),
            "avg_mc":        round(avg_mc,   1),
            "avg_proj":      round(avg_proj, 2),
            "ta":            total_ta,
            "att_2w":        round(min_att_2w, 1),
            "days_inactive": days_inactive,
            "proj_pending":  proj_pending,
            "proj_passed":   proj_passed,
            "mods":          mods,
        })

    # Sort by risk descending
    final.sort(key=lambda x: -x["risk"])
    return final

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    log("=" * 55)
    log("NS SM Brain Engine — Refresh (March 2026 Spreadsheets, 5 students)")
    log("=" * 55)

    if not METABASE_PASS:
        log("ERROR: METABASE_PASSWORD not set.")
        sys.exit(1)

    with open(THRESHOLDS_PATH) as f:
        thresholds = json.load(f)

    token = get_session_token()
    try:
        raw    = fetch_batch_data(token)
        log(f"Fetched {len(raw)} raw rows")
        scored = score_students(raw, thresholds)
        log(f"Scored {len(scored)} students")
    finally:
        logout(token)
        log("Session closed.")

    if not scored:
        log("ERROR: No students scored. Aborting.")
        sys.exit(1)

    stats = {"total": len(scored), "high": 0, "medium": 0, "low": 0, "strong": 0}
    for s in scored:
        t = s["tier"]
        if   t == "High Risk":   stats["high"]   += 1
        elif t == "Medium Risk": stats["medium"] += 1
        elif t == "Low Risk":    stats["low"]    += 1
        else:                    stats["strong"] += 1

    output = {
        "students":    scored,
        "batch_stats": {BATCH_NAME: stats},
        "refreshed_at": datetime.datetime.now().isoformat(),
        "thresholds":  thresholds
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2, default=str)

    log(f"Saved → {OUTPUT_PATH}")
    log(f"Stats: {stats}")
    log("=" * 55)


if __name__ == "__main__":
    main()