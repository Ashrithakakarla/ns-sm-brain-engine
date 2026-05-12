"""
NS SM Brain Engine — Daily Data Refresh (March + April 2026 Spreadsheets — All Students)
Run:  python3 refresh_data.py
"""

import numpy as np
import pandas as pd
import requests, json, datetime, os, sys

METABASE_URL   = "https://metabase-lierhfgoeiwhr.newtonschool.co"
METABASE_EMAIL = os.environ.get("METABASE_EMAIL",    "ashritha.k@newtonschool.co")
METABASE_PASS  = os.environ.get("METABASE_PASSWORD", "H0CcPtgDa3ZN9b")
THRESHOLDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "thresholds.json")
OUTPUT_PATH     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_refresh.json")

BATCH_CONFIGS = {
       # "February 2026 Spreadsheets": {"au_id": 2622, "lu_id": 3308},
       "February 2026 SQL": {"au_id": 2622, "lu_id": 3380},
       "Jan 2026 SQL": {"au_id": 2621, "lu_id": 3327},
       # "March 2026 Spreadsheets": {"au_id": 3240, "lu_id": 3355},
       "April 2026 Spreadsheets": {"au_id": 3241, "lu_id": 3402},
       "May 2026 Spreadsheets": {"au_id": 3242, "lu_id": 3478},
       "March 2026 SQL": {"au_id": 3240, "lu_id": 3461}

      }
EXCLUDED_LABELS = (677, 717, 722)

LOG_PREFIX = lambda: f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"
def log(msg): print(f"{LOG_PREFIX()} {msg}", flush=True)

def get_session_token():
    log(f"Authenticating as {METABASE_EMAIL}...")
    resp = requests.post(f"{METABASE_URL}/api/session",
        json={"username": METABASE_EMAIL, "password": METABASE_PASS},
        headers={"Content-Type": "application/json"}, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Login failed ({resp.status_code}): {resp.text[:200]}")
    token = resp.json().get("id") or resp.json().get("token")
    log(f"Auth OK. Token: {token[:8]}...")
    return token

def logout(token):
    try: requests.delete(f"{METABASE_URL}/api/session", headers={"X-Metabase-Session": token}, timeout=10)
    except: pass

def run_query(token, sql, row_limit=200000):
    headers = {"Content-Type": "application/json", "X-Metabase-Session": str(token)}
    resp = requests.post(f"{METABASE_URL}/api/dataset",
        json={"database": 4, "type": "native", "native": {"query": sql}, "parameters": []},
        headers=headers, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data: raise RuntimeError(f"Query error: {data['error']}")
    cols = [c["name"] for c in data["data"]["cols"]]
    return [dict(zip(cols, row)) for row in data["data"]["rows"][:row_limit]]

def days_since(d):
    if not d or str(d) in ("None", ""): return 999
    try:
        dt = datetime.datetime.fromisoformat(str(d).replace("Z", "+00:00"))
        return (datetime.datetime.now(datetime.timezone.utc) - dt).days
    except: return 999

# ── PHASE 1: MAIN SUMMARY ─────────────────────────────────────────────────────
def fetch_summary(token, batch_name, au_id, lu_id):
    excl = ",".join(str(x) for x in EXCLUDED_LABELS)
    log(f"  Fetching summary (AU={au_id}, LU={lu_id})...")
    sql = f"""
WITH excluded AS (
    SELECT DISTINCT cum.user_id FROM courses_courseusermapping cum
    JOIN courses_courseuserlabelmapping lm ON lm.course_user_mapping_id=cum.id AND lm.label_id IN ({excl})
    WHERE cum.status=8
),
students AS (
    SELECT cum.user_id AS id, au.first_name||' '||au.last_name AS name, au.email
    FROM courses_courseusermapping cum
    JOIN auth_user au ON au.id=cum.user_id
    WHERE cum.course_id={au_id} AND cum.status=8
      AND cum.user_id NOT IN (SELECT user_id FROM excluded)
    ORDER BY cum.id
),
att AS (
    SELECT cum.user_id,
        ROUND(COUNT(DISTINCT vslcur.lecture_id) FILTER (
            WHERE vslcur.report_type=4 OR (vslcur.report_type=3
            AND EXTRACT(EPOCH FROM vslcur.total_duration)*100.0
            /NULLIF(EXTRACT(EPOCH FROM(vsl.end_timestamp-vsl.start_timestamp)),0)>=40)
        )*100.0/NULLIF(COUNT(DISTINCT vsl.id),0),1) AS att_pct,
        COALESCE(ROUND(SUM(EXTRACT(EPOCH FROM vslcur.total_duration)) FILTER(WHERE vslcur.report_type=4)/60.0,0),0) AS live_mins,
        COUNT(DISTINCT vsl.id) AS total_lec,
        ROUND(COUNT(DISTINCT vslcur.lecture_id) FILTER (
            WHERE vsl.start_timestamp>=NOW()-INTERVAL '14 days'
            AND (vslcur.report_type=4 OR (vslcur.report_type=3
            AND EXTRACT(EPOCH FROM vslcur.total_duration)*100.0
            /NULLIF(EXTRACT(EPOCH FROM(vsl.end_timestamp-vsl.start_timestamp)),0)>=40))
        )*100.0/NULLIF(COUNT(DISTINCT vsl.id) FILTER(WHERE vsl.start_timestamp>=NOW()-INTERVAL '14 days'),0),1) AS att_2w,
        COUNT(DISTINCT vsl.id) FILTER(WHERE vsl.start_timestamp>=NOW()-INTERVAL '14 days') AS lec_2w
    FROM courses_courseusermapping cum
    JOIN video_sessions_lecture vsl ON vsl.course_id={lu_id} AND vsl.mandatory=TRUE
    LEFT JOIN video_sessions_lecturecourseusercumulativereport vslcur
        ON vslcur.course_user_mapping_id=cum.id AND vslcur.lecture_id=vsl.id
    WHERE cum.course_id={lu_id} AND cum.status=8 AND cum.user_id IN (SELECT id FROM students)
    GROUP BY 1
),
asgn AS (
    SELECT cum.user_id,
        COUNT(DISTINCT aaqm.assignment_question_id) AS total_q,
        ROUND(COUNT(DISTINCT acuqm.assignment_question_id) FILTER(WHERE acuqm.all_test_case_passed=TRUE)*100.0
            /NULLIF(COUNT(DISTINCT aaqm.assignment_question_id),0),1) AS asgn_pct,
        COUNT(DISTINCT acuqm.assignment_question_id) FILTER(WHERE acuqm.all_test_case_passed=TRUE AND aq.difficulty_type=1) AS easy,
        COUNT(DISTINCT acuqm.assignment_question_id) FILTER(WHERE acuqm.all_test_case_passed=TRUE AND aq.difficulty_type=2) AS med,
        COUNT(DISTINCT acuqm.assignment_question_id) FILTER(WHERE acuqm.all_test_case_passed=TRUE AND aq.difficulty_type=3) AS hard,
        COUNT(DISTINCT aacum.id) FILTER(WHERE aacum.late_submission=TRUE) AS late_sub,
        MAX(acuqm.completed_at)::date AS last_solve
    FROM courses_courseusermapping cum
    JOIN assignments_assignmentcourseusermapping aacum ON aacum.course_user_mapping_id=cum.id
    JOIN assignments_assignment aa ON aa.id=aacum.assignment_id AND aa.original_assignment_type=1
    JOIN assignments_assignmentquestionmapping aaqm ON aaqm.assignment_id=aa.id
    JOIN assignments_assignmentquestion aq ON aq.id=aaqm.assignment_question_id
    LEFT JOIN assignments_assignmentcourseuserquestionmapping acuqm ON acuqm.assignment_course_user_mapping_id=aacum.id
    WHERE cum.course_id={lu_id} AND cum.status=8 AND cum.user_id IN (SELECT id FROM students)
    GROUP BY 1
),
mc AS (
    SELECT cum.user_id, MAX(cam.marks) AS mc_best, COUNT(DISTINCT cam.id) AS mc_attempts
    FROM courses_courseusermapping cum
    JOIN assessments_courseuserassessmentmapping cam ON cam.course_user_mapping_id=cum.id AND cam.completed=TRUE
    WHERE cum.course_id={lu_id} AND cum.status=8 AND cum.user_id IN (SELECT id FROM students)
    GROUP BY 1
),
proj AS (
    SELECT cum.user_id, MAX(aacum.marks) AS proj_best, MIN(aacum.marks) AS proj_first,
        COUNT(DISTINCT aacum.id) AS proj_subs,
        MAX(CASE WHEN aacum.late_submission THEN 1 ELSE 0 END) AS proj_late
    FROM courses_courseusermapping cum
    JOIN assignments_assignmentcourseusermapping aacum ON aacum.course_user_mapping_id=cum.id
    JOIN assignments_assignment aa ON aa.id=aacum.assignment_id AND aa.assignment_sub_type=6 AND aa.original_assignment_type=1
    WHERE cum.course_id={lu_id} AND cum.status=8 AND cum.user_id IN (SELECT id FROM students)
    GROUP BY 1
)
SELECT s.id, s.name, s.email,
    COALESCE(a.att_pct,0) AS att_pct, COALESCE(a.live_mins,0) AS live_mins,
    COALESCE(a.total_lec,0) AS total_lec, COALESCE(a.att_2w,0) AS att_2w, COALESCE(a.lec_2w,0) AS lec_2w_count,
    COALESCE(g.total_q,0) AS total_q, COALESCE(g.asgn_pct,0) AS asgn_pct,
    COALESCE(g.easy,0) AS easy, COALESCE(g.med,0) AS med, COALESCE(g.hard,0) AS hard,
    COALESCE(g.late_sub,0) AS late_sub, g.last_solve,
    COALESCE(m.mc_best,0) AS mc_best, COALESCE(m.mc_attempts,0) AS mc_attempts,
    COALESCE(p.proj_best,0) AS proj_best, COALESCE(p.proj_first,0) AS proj_first,
    COALESCE(p.proj_subs,0) AS proj_subs, COALESCE(p.proj_late,0) AS proj_late
FROM students s
LEFT JOIN att a ON a.user_id=s.id
LEFT JOIN asgn g ON g.user_id=s.id
LEFT JOIN mc m ON m.user_id=s.id
LEFT JOIN proj p ON p.user_id=s.id
ORDER BY s.name"""
    rows = run_query(token, sql)
    log(f"  {len(rows)} students")
    return rows

# ── PHASE 2a: LECTURES ────────────────────────────────────────────────────────
def fetch_lectures(token, lu_id, ids):
    log(f"  Fetching lectures...")
    id_list = ",".join(str(x) for x in ids)
    sql = f"""
SELECT user_id, title, date, attended, watch_pct, lec_type
FROM (
    SELECT cum.user_id,
        vsl.title,
        vsl.start_timestamp::date AS date,
        CASE WHEN vslcur.report_type=4 THEN TRUE
             WHEN vslcur.report_type=3 AND EXTRACT(EPOCH FROM vslcur.total_duration)*100.0
                 /NULLIF(EXTRACT(EPOCH FROM(vsl.end_timestamp-vsl.start_timestamp)),0)>=40 THEN TRUE
             ELSE FALSE END AS attended,
        ROUND(LEAST(EXTRACT(EPOCH FROM vslcur.total_duration)*100.0
            /NULLIF(EXTRACT(EPOCH FROM(vsl.end_timestamp-vsl.start_timestamp)),0),100),1) AS watch_pct,
        CASE
            WHEN vslcur.report_type=4 THEN 'Live'
            WHEN vslcur.report_type=3 THEN 'Recorded'
            WHEN vslcur.report_type IS NOT NULL THEN 'Recorded'
            ELSE 'Absent'
        END AS lec_type,
        ROW_NUMBER() OVER (
            PARTITION BY cum.user_id, vsl.start_timestamp::date
            ORDER BY CASE WHEN vslcur.report_type=4 THEN 1
                          WHEN vslcur.report_type=3 THEN 2
                          ELSE 3 END
        ) AS row_num
    FROM video_sessions_lecture vsl
    JOIN courses_courseusermapping cum ON cum.course_id={lu_id} AND cum.status=8 AND cum.user_id IN ({id_list})
    LEFT JOIN video_sessions_lecturecourseusercumulativereport vslcur
        ON vslcur.course_user_mapping_id=cum.id AND vslcur.lecture_id=vsl.id
    WHERE vsl.course_id={lu_id} AND vsl.mandatory=TRUE AND vsl.start_timestamp<=NOW()
) deduped
WHERE row_num=1
ORDER BY user_id, date
"""
    try:
        rows = run_query(token, sql)
        log(f"    {len(rows)} lecture rows")
        by = {}
        for r in rows:
            uid = r["user_id"]
            by.setdefault(uid, []).append({
                "date":      str(r.get("date", ""))[:10],
                "title":     r.get("title", ""),
                "type":      r.get("lec_type", "Absent"),
                "watch_pct": r.get("watch_pct") or 0,
                "attended":  bool(r.get("attended")),
                "watch_pct_raw": r.get("watch_pct") or 0,
            })
        return by
    except Exception as e:
        log(f"    WARNING: lectures — {e}"); return {}


def fetch_asgn_detail(token, lu_id, ids):
    """SQL-based topic-wise assignment detail. Groups by assignment id+title, no difficulty split."""
    log(f"  Fetching assignment detail (SQL)...")
    id_list = ",".join(str(x) for x in ids)
    sql = f"""
SELECT
    cum.user_id,
    technologies_topic.title                                                                                   AS topic,
    assignments_assignment.assignment_sub_type,
    COUNT(DISTINCT assignments_assignmentquestionmapping.assignment_question_id)                               AS total_released,
    COUNT(DISTINCT assignments_assignmentcourseuserquestionmapping.assignment_question_id)
        FILTER(WHERE assignments_assignmentcourseuserquestionmapping.all_test_case_passed = TRUE)              AS solved,
    COUNT(DISTINCT assignments_assignmentcourseuserquestionmapping.assignment_question_id)
        FILTER(WHERE assignments_assignmentcourseuserquestionmapping.all_test_case_passed IS NOT NULL)         AS attempted,
    MAX(assignments_assignmentcourseuserquestionmapping.completed_at)::date                                    AS last_solved_date,
    ROUND(AVG(
        CASE
            WHEN assignments_assignmentcourseuserquestionmapping.completed_at IS NOT NULL
             AND (assignments_assignmentcourseuserquestionmapping.started_at IS NOT NULL
                  OR assignments_assignmentcourseusermapping.started_at IS NOT NULL)
            THEN LEAST(
                EXTRACT(EPOCH FROM (
                    assignments_assignmentcourseuserquestionmapping.completed_at -
                    COALESCE(
                        assignments_assignmentcourseuserquestionmapping.started_at,
                        assignments_assignmentcourseusermapping.started_at
                    )
                )) / 60.0,
                60.0
            )
            ELSE NULL
        END
    ) FILTER (WHERE assignments_assignmentcourseuserquestionmapping.all_test_case_passed = TRUE)
    ::numeric, 1) AS avg_time_mins

FROM courses_courseusermapping cum
JOIN assignments_assignmentcourseusermapping ON assignments_assignmentcourseusermapping.course_user_mapping_id=cum.id

JOIN assignments_assignment
    ON assignments_assignment.id = assignments_assignmentcourseusermapping.assignment_id
    AND assignments_assignment.original_assignment_type = 1
    AND assignments_assignment.assignment_sub_type IN (1, 2)

JOIN assignments_assignmentquestionmapping
    ON assignments_assignmentquestionmapping.assignment_id = assignments_assignment.id

LEFT JOIN assignments_assignmentquestiontopicmapping
    ON assignments_assignmentquestiontopicmapping.assignment_question_id = assignments_assignmentquestionmapping.assignment_question_id

LEFT JOIN technologies_topic
    ON technologies_topic.id = assignments_assignmentquestiontopicmapping.topic_id

LEFT JOIN technologies_topicnode
    ON technologies_topicnode.topic_id = technologies_topic.id

LEFT JOIN technologies_topictemplate
    ON technologies_topictemplate.id = technologies_topicnode.topic_template_id
    AND technologies_topictemplate.id IN (208, 209, 367, 447, 489, 544, 555, 577)

LEFT JOIN assignments_assignmentcourseuserquestionmapping
    ON assignments_assignmentcourseuserquestionmapping.assignment_course_user_mapping_id = assignments_assignmentcourseusermapping.id
    AND assignments_assignmentcourseuserquestionmapping.assignment_question_id = assignments_assignmentquestionmapping.assignment_question_id

WHERE cum.course_id = {lu_id}
  AND cum.status = 8
  AND cum.user_id IN ({id_list})

GROUP BY
    cum.user_id,
    technologies_topic.title,
    assignments_assignment.assignment_sub_type

ORDER BY
    cum.user_id,
    assignments_assignment.assignment_sub_type,
    technologies_topic.title
"""
    try:
        rows = run_query(token, sql)
        log(f"    {len(rows)} asgn rows")
        learn_by, app_by = {}, {}
        for r in rows:
            uid = r["user_id"]
            sub = int(r.get("assignment_sub_type") or 1)
            entry = {
                "topic":           (r.get("topic") or "").strip(),
                "difficulty":      "",
                "total_released":  int(r.get("total_released") or 0),
                "attempted":       int(r.get("attempted")      or 0),
                "solved":          int(r.get("solved")         or 0),
                "avg_time_mins":   round(float(r["avg_time_mins"]), 1) if r.get("avg_time_mins") is not None else None,
                "last_solved_date":str(r.get("last_solved_date") or "") or None,
            }
            if sub == 2: app_by.setdefault(uid, []).append(entry)
            else:        learn_by.setdefault(uid, []).append(entry)
        return learn_by, app_by
    except Exception as e:
        log(f"    WARNING: asgn detail — {e}"); return {}, {}


def fetch_contests_card(token, lu_id, ids, batch_name=""):
    """
    Card 8057 (MCQ):    user_id, contest_id, contest_name, contest_date, module_name,
                        total_qs, marked_qs, correct_qs, obtained_numerator,
                        module_denominator, module_wise_score
    Card 6391 (Coding): user_id, contest_id, contest_title, contest_date, module_name,
                        total_qs, qs_attempted, qs_completed, obtained_numerator,
                        module_denominator, per_module_marks
    Mid MC (6396+9717+9656 MCQ, 6397 Coding) — same schema.

    Strategy:
    - Merge MCQ + Coding on [user_id, admin_unit_name, contest_date, module_name]
    - Compute total = MCQ*0.4 + Coding*0.6 for Spreadsheets
    - Sort by contest_date → MC1 (first), MC2 (second), MC3 (third)
    - mid_mc: separate mid-module contests
    """
    log(f"  Fetching contests via cards...")
    headers = {"Content-Type": "application/json", "X-Metabase-Session": str(token)}
    id_set = set(ids)

    def fetch_card(card_id):
        try:
            r = requests.post(f"{METABASE_URL}/api/card/{card_id}/query/json",
                              headers=headers, json={}, timeout=360)
            r.raise_for_status()
            rows = r.json() if isinstance(r.json(), list) else []
            log(f"    Card {card_id}: {len(rows)} rows")
            return rows
        except Exception as e:
            log(f"    Card {card_id} failed — {e}");
            return []

    mc_mcq_rows = fetch_card(8057)
    mc_coding_rows = fetch_card(6391)
    # Mid MC: card 6396 only (9717 and 9656 time out — 6396 covers current batches)
    mid_mcq_rows = fetch_card(6396) + fetch_card(9717) + fetch_card(9656)
    mid_coding_rows = fetch_card(6397)
    # Rename contest_title → contest_name to match MCQ schema
    for r in mid_coding_rows:
        if "contest_title" in r and "contest_name" not in r:
            r["contest_name"] = r["contest_title"]

    # Filter to only this batch's module — cards 8057/6391 return all modules
    _bn = batch_name.lower()
    _batch_module = "DS 04 SQL" if "sql" in _bn else "DS 05 Python" if "python" in _bn else "DS 02 Spreadsheets"
    mc_mcq_rows = [r for r in mc_mcq_rows if str(r.get("module_name", "")).strip() == _batch_module]
    mc_coding_rows = [r for r in mc_coding_rows if str(r.get("module_name", "")).strip() == _batch_module]
    log(f"  After module filter ({_batch_module}): {len(mc_mcq_rows)} MCQ rows, {len(mc_coding_rows)} Coding rows")

    def build_contests(mcq_rows, coding_rows, label):
        """
        Build per-user list of contests sorted by date.
        Each entry has full MCQ + Coding breakdown.
        Returns: {user_id: [ {contest_entry}, ... ] sorted by date asc }
        """
        # Index MCQ by (user_id, admin_unit_name, contest_date, module_name)
        mcq_idx = {}
        for r in mcq_rows:
            uid = r.get("user_id")
            try:
                uid = int(uid)
            except:
                continue
            if uid not in id_set: continue
            key = (uid, str(r.get("admin_unit_name", "")),
                   str(r.get("contest_date", ""))[:10],
                   str(r.get("module_name", "")))
            score = float(r.get("module_wise_score") or 0)
            # Keep best MCQ per key
            if key not in mcq_idx or score > mcq_idx[key].get("mcq_score", 0):
                mcq_idx[key] = {
                    "mcq_score": round(score, 2),
                    "mcq_total_qs": int(r.get("total_qs") or 0),
                    "mcq_marked": int(r.get("marked_qs") or 0),
                    "mcq_correct": int(r.get("correct_qs") or 0),
                    "mcq_obtained": float(r.get("obtained_numerator") or 0),
                    "mcq_denom": float(r.get("module_denominator") or 0),
                    "contest_name": str(r.get("contest_name") or ""),
                }

        # Index Coding by same key
        coding_idx = {}
        for r in coding_rows:
            uid = r.get("user_id")
            try:
                uid = int(uid)
            except:
                continue
            if uid not in id_set: continue
            key = (uid, str(r.get("admin_unit_name", "")),
                   str(r.get("contest_date", ""))[:10],
                   str(r.get("module_name", "")))
            score = float(r.get("per_module_marks") or 0)
            if key not in coding_idx or score > coding_idx[key].get("coding_score", 0):
                coding_idx[key] = {
                    "coding_score": round(score, 2),
                    "coding_total_qs": int(r.get("total_qs") or 0),
                    "coding_attempted": int(r.get("qs_attempted") or 0),
                    "coding_solved": int(r.get("qs_completed") or 0),
                    "coding_obtained": float(r.get("obtained_numerator") or 0),
                    "coding_denom": float(r.get("module_denominator") or 0),
                    "contest_title": str(r.get("contest_title") or ""),
                }

        # Merge all keys, compute total
        all_keys = set(mcq_idx.keys()) | set(coding_idx.keys())
        by_user = {}
        for key in all_keys:
            uid, au, date, mod = key
            mcq_d = mcq_idx.get(key, {})
            coding_d = coding_idx.get(key, {})
            mcq_s = mcq_d.get("mcq_score", 0)
            cod_s = coding_d.get("coding_score", 0)

            if mod in ["DS 02 Spreadsheets", "DS 04 SQL", "DS 05 Python",
                       "DS 06 EDA 1", "DS 08 ML 1", "DS 09 ML 2"]:
                total = mcq_s * 0.4 + cod_s * 0.6
            elif mod in ["DS 03 Power BI", "DS 07 EDA 2"]:
                total = mcq_s
            else:
                total = mcq_s * 0.4 + cod_s * 0.6

            entry = {
                "title": mcq_d.get("contest_name") or coding_d.get("contest_title", "Module Contest"),
                "contest_date": date,
                "max_marks": 100,
                "clearing_marks": 64,
                "percentage": round(total, 1),
                "score": round(total, 1),
                "cleared": round(total, 1) >= 64,
                "date": date,
                "normalized_score": round(total, 1),
                "attempted": True,
                "was_held": True,
                # MCQ breakdown
                "mcq_score": mcq_d.get("mcq_score", 0),
                "mcq_total_qs": mcq_d.get("mcq_total_qs", 0),
                "mcq_marked_qs": mcq_d.get("mcq_marked", 0),
                "mcq_correct_qs": mcq_d.get("mcq_correct", 0),
                "mcq_obtained": mcq_d.get("mcq_obtained", 0),
                "mcq_denom": mcq_d.get("mcq_denom", 0),
                # Coding breakdown
                "coding_score": coding_d.get("coding_score", 0),
                "coding_total_qs": coding_d.get("coding_total_qs", 0),
                "coding_qs_attempted": coding_d.get("coding_attempted", 0),
                "coding_qs_completed": coding_d.get("coding_solved", 0),
                "coding_obtained": coding_d.get("coding_obtained", 0),
                "coding_denom": coding_d.get("coding_denom", 0),
            }
            by_user.setdefault(uid, []).append(entry)

        # Sort each student's contests by date ascending
        for uid in by_user:
            by_user[uid].sort(key=lambda x: x["contest_date"])

        log(f"    {label}: {len(by_user)} students, "
            f"max contests={max((len(v) for v in by_user.values()), default=0)}")
        return by_user

    mc_by_user = build_contests(mc_mcq_rows, mc_coding_rows, "Module Contest")
    mid_by_user = build_contests(mid_mcq_rows, mid_coding_rows, "Mid Module Contest")

    # Build final contest dict: mc1=first attempt, mc2=second, mc3=third, mid_mc=best mid
    # Determine current module based on batch name to filter mid module contests
    _bn = batch_name.lower()
    current_module = "DS 04 SQL" if "sql" in _bn else "DS 05 Python" if "python" in _bn else "DS 02 Spreadsheets"

    mc_clearance = 64.0
    contest_by = {}
    for uid in id_set:
        mc_attempts = mc_by_user.get(uid, [])
        all_mid_attempts = mid_by_user.get(uid, [])

        # Filter mid attempts to only include current module contests
        # Check if title contains module indicator (SQL/Spreadsheet/Python)
        mid_attempts = []
        for attempt in all_mid_attempts:
            title = attempt.get("title", "").lower()
            # Include only contests matching current module
            if current_module == "DS 04 SQL" and ("sql" in title or "structured query" in title):
                mid_attempts.append(attempt)
            elif current_module == "DS 02 Spreadsheets" and ("spreadsheet" in title or "excel" in title):
                mid_attempts.append(attempt)
            elif current_module == "DS 05 Python" and "python" in title:
                mid_attempts.append(attempt)

        # MC1 = first attempt, MC2 = second, MC3 = third (by date)
        mc1 = mc_attempts[0] if len(mc_attempts) >= 1 else None
        mc2 = mc_attempts[1] if len(mc_attempts) >= 2 else None

        # mid_mc attempts — up to 2 attempts for CURRENT MODULE, sorted by date
        mid_mc1 = mid_attempts[0] if len(mid_attempts) >= 1 else None
        mid_mc2 = mid_attempts[1] if len(mid_attempts) >= 2 else None
        mid_mc = max(mid_attempts, key=lambda x: x["percentage"]) if mid_attempts else None

        contest_by[uid] = {
            "mid_mc": mid_mc,
            "mid_mc1": mid_mc1,
            "mid_mc2": mid_mc2,
            "mc1": mc1,
            "mc2": mc2,
            "mc_attempts": mc_attempts,
        }

    return contest_by


def fetch_mentor_sessions(token, ids, lu_id=None):
    """Fetch Mentor Connect sessions via card 6161, filtered to current batch students."""
    return _fetch_mentor_sessions_card(token, ids)


def _fetch_mentor_sessions_card(token, ids):
    """Fetch mentor sessions from card 6161."""
    log("Fetching Mentor sessions (card 6161)...")
    headers = {"Content-Type": "application/json", "X-Metabase-Session": str(token)}
    try:
        r = requests.post(f"{METABASE_URL}/api/card/6161/query/json", headers=headers, json={}, timeout=180)
        r.raise_for_status(); rows = r.json() if isinstance(r.json(), list) else []
        log(f"  Card 6161: {len(rows)} rows")
    except Exception as e:
        log(f"  WARNING: Card 6161 failed — {e}"); return {}
    by = {}
    for row in rows:
        uid = row.get("user_id") or row.get("student_user_id") or 0
        try: uid = int(uid)
        except: continue
        if uid not in ids: continue
        raw_dt = str(row.get("session_start_time") or row.get("date") or "")
        session_date = raw_dt[:10] if len(raw_dt) >= 10 else ""
        try: duration = round(float(row.get("over_lap_time_in_minute") or row.get("duration_mins") or 0), 1) or None
        except: duration = None
        by.setdefault(uid, []).append({
            "type":                "mentor",
            "session_id":          str(row.get("session_id") or ""),
            "date":                session_date,
            "mentor":              str(row.get("mentor_name") or row.get("counsellor_name") or "").strip(),
            "batch":               str(row.get("batch") or row.get("Batch") or "").strip(),
            "duration_mins":       duration,
            "rating":              row.get("rating"),
            "Module":              str(row.get("module_name") or "").strip(),
            "topic":               str(row.get("topic") or "").strip(),
            "feedback_given":      str(row.get("feedback_given") or "").strip(),
            "subjective_feedback": str(row.get("subjective_feedback") or "").strip(),
            "status":              str(row.get("session_status") or row.get("status") or "Conducted").strip(),
        })
    log(f"  Mentor complete: {len(by)} students ({sum(len(v) for v in by.values())} sessions)")
    return by

# ── PROJECT CONFIG ────────────────────────────────────────────────────────────
_PROJ_MAX_MARKS = 10
_PROJ_PASS_PCT = 0.8

_proj_df_cache = None  # fetched once per run, shared across batches


def _load_proj_df(token) -> "pd.DataFrame":
    """
    Fetch project submission data from Metabase cards 6578 + 6579,
    concat, deduplicate on submission_id — mirrors the notebook exactly.
    Cached after the first call so both batches share one fetch.
    """
    global _proj_df_cache
    if _proj_df_cache is not None:
        return _proj_df_cache

    headers = {"Content-Type": "application/json", "X-Metabase-Session": str(token)}
    frames = []
    for card_id in (6578, 6579):
        try:
            resp = requests.post(
                f"{METABASE_URL}/api/card/{card_id}/query/json",
                headers=headers, json={}, timeout=360,
            )
            resp.raise_for_status()
            rows = resp.json()
            if isinstance(rows, list):
                frames.append(pd.DataFrame(rows))
                log(f"  Project card {card_id}: {len(rows)} rows")
            else:
                log(f"  Project card {card_id}: unexpected response — skipping")
        except Exception as e:
            log(f"  WARNING: project card {card_id} failed — {e}")

    if not frames:
        raise RuntimeError("Both project cards (6578, 6579) returned no data.")

    df = pd.concat(frames, axis=0, ignore_index=True)
    df["Submission Time"] = pd.to_datetime(df.get("Submission Time"), errors="coerce", utc=True)
    df["feedback_given_time"] = pd.to_datetime(df.get("feedback_given_time"), errors="coerce", utc=True)
    df = df.drop_duplicates(subset="submission_id")
    # Normalise user_id column (card may return it as "User ID")
    if "User ID" in df.columns and "user_id" not in df.columns:
        df = df.rename(columns={"User ID": "user_id"})
    df["user_id"] = df["user_id"].astype(str).str.strip()
    df["marks_obtained"] = pd.to_numeric(df.get("marks_obtained", pd.Series(dtype=float)), errors="coerce")
    df["marks_submission_level"] = pd.to_numeric(df.get("marks_submission_level", pd.Series(dtype=float)),
                                                 errors="coerce")
    log(f"  Project data: {len(df)} unique submissions across both cards.")
    _proj_df_cache = df
    return df

def fetch_projects(token, lu_id, ids, batch_name=""):
    """
    Fetches project submission data from Metabase cards 6578 + 6579
    and returns a per-user dict with the same structure the rest of
    the pipeline expects:

        by[user_id] = {
            user_id, student, batch, project, module, question,
            release_date, deadline, submissions, last_submission,
            marks, max_marks, cleared, feedback_count, last_feedback,
            evaluator, status, note, submission_history
        }
    """
    log(f"  Fetching projects from Metabase cards 6578 + 6579…")
    try:
        df = _load_proj_df(token)

        # Filter to this batch's user_ids
        uid_set = {str(u) for u in ids}
        df = df[df["user_id"].isin(uid_set)].copy()

        # Also filter by batch name to avoid cross-batch contamination
        # (a student enrolled in both SQL and Spreadsheets would otherwise get both)
        if batch_name and "Batch" in df.columns:
            batch_mask = df["Batch"].str.strip().str.lower() == batch_name.lower()
            if batch_mask.any():
                df = df[batch_mask].copy()
                log(f"  Project batch filter '{batch_name}': {len(df)} rows")

        # Keep only actual submissions (mirrors notebook: filtered_df = df)
        if "Submission Status" in df.columns:
            df = df[df["Submission Status"].str.strip().str.lower() == "submitted"].copy()

        # Sort chronologically so submission_num increments correctly
        df = df.sort_values(["user_id", "Submission Time"], na_position="last").reset_index(drop=True)

        max_m = float(_PROJ_MAX_MARKS)
        by = {}

        for _, r in df.iterrows():
            uid = str(r.get("user_id", "")).strip()
            if not uid:
                continue

            # Only use per-submission mark — marks_obtained is overall best, not per-submission
            sub_mark = r.get("marks_submission_level")
            mark_val = sub_mark if pd.notna(sub_mark) else None

            sub_dt = r.get("Submission Time")
            sub_date = str(sub_dt)[:10] if pd.notna(sub_dt) else ""
            feed_dt = r.get("feedback_given_time")
            has_fb = pd.notna(feed_dt) and str(feed_dt).strip() not in ("", "NaT")
            evaluator = str(r.get("mentor_name", "") or "").strip()

            if uid not in by:
                by[uid] = {
                    "user_id": uid,
                    "student": str(r.get("student_name", "") or "").strip(),
                    "batch": str(r.get("Batch", "") or "").strip(),
                    "project": str(r.get("Project", "Spreadsheet Project") or "Spreadsheet Project").strip(),
                    "module": str(r.get("Module_name", "") or "").strip(),
                    "question": str(r.get("question_title", "") or "").strip(),
                    "release_date": str(r.get("project_release_date", "") or "")[:10],
                    "deadline": str(r.get("project_deadline_date", "") or "")[:10],
                    "submissions": 0,
                    "last_submission": sub_date,
                    "marks": None,
                    "max_marks": max_m,
                    "cleared": False,
                    "feedback_count": 0,
                    "last_feedback": None,
                    "evaluator": evaluator,
                    "status": "",
                    "note": "",
                    "submission_history": [],
                }

            p = by[uid]
            p["submissions"] += 1
            snum = p["submissions"]

            if sub_date and sub_date > (p["last_submission"] or ""):
                p["last_submission"] = sub_date

            if mark_val is not None and not pd.isna(mark_val):
                fv = float(mark_val)
                if p["marks"] is None or fv > p["marks"]:
                    p["marks"] = fv

            if has_fb:
                p["feedback_count"] += 1
                fb_str = str(feed_dt)[:10]
                if p["last_feedback"] is None or fb_str > p["last_feedback"]:
                    p["last_feedback"] = fb_str
            if evaluator:
                p["evaluator"] = evaluator

            eval_status = str(r.get("Evaluation Status", "") or "").strip().lower()
            # Full submission timestamp (includes time, not just date)
            sub_timestamp = str(sub_dt)[:19].replace("T", " ") if pd.notna(sub_dt) else sub_date
            fb_timestamp = str(feed_dt)[:19].replace("T", " ") if has_fb else None
            p["submission_history"].append({
                "submission": snum,
                "date": sub_date,
                "timestamp": sub_timestamp,
                "marks": float(mark_val) if (mark_val is not None and not pd.isna(mark_val)) else None,
                "evaluator": evaluator,
                "feedback_given_time": fb_timestamp,
                "notes": (
                    f"Evaluated {mark_val}/{int(max_m)}"
                    if eval_status == "evaluated" and mark_val is not None
                    else "Pending"
                ),
            })

        # Compute cleared / status / note after all rows processed
        for uid, p in by.items():
            m = p["marks"]
            fc = p["feedback_count"]
            if m is not None:
                p["cleared"] = m >= max_m * _PROJ_PASS_PCT
                p["status"] = (
                    f"Cleared ({m}/{int(max_m)})"
                    if p["cleared"]
                    else f"Not cleared ({m}/{int(max_m)}). Resubmit needed."
                )
                p["note"] = (
                        f"Scored {m}/{int(max_m)} — "
                        + ("cleared" if p["cleared"] else f"{fc} feedbacks. Must resubmit.")
                        + "."
                )
            else:
                p["status"] = "Submitted — awaiting evaluation."
                p["note"] = "Evaluation pending."

        log(f"    {len(by)} student project records loaded.")
        return by
    except Exception as e:
        log(f"    WARNING: projects — {e}");
        return {}

# ── PHASE 3: TA SESSIONS ──────────────────────────────────────────────────────
def fetch_ta_sessions(token, ids):
    log("Fetching TA sessions (cards 6135 + 6570)...")
    headers = {"Content-Type": "application/json", "X-Metabase-Session": str(token)}

    # ── Card 6135: session metadata (feedback, topic, module, rating, cancel) ──
    try:
        r1 = requests.post(f"{METABASE_URL}/api/card/6135/query/json",
                           headers=headers, json={}, timeout=360)
        r1.raise_for_status()
        rows1 = r1.json() if isinstance(r1.json(), list) else []
        log(f"  Card 6135: {len(rows1)} rows")
    except Exception as e:
        log(f"  WARNING: Card 6135 failed — {e}")
        rows1 = []

    # ── Card 6570: student mapping (student_user_id, session_start_time, duration, batch) ──
    try:
        r2 = requests.post(f"{METABASE_URL}/api/card/6570/query/json",
                           headers=headers, json={}, timeout=360)
        r2.raise_for_status()
        rows2 = r2.json() if isinstance(r2.json(), list) else []
        log(f"  Card 6570: {len(rows2)} rows")
    except Exception as e:
        log(f"  WARNING: Card 6570 failed — {e}")
        rows2 = []

    if not rows1 or not rows2:
        log("  WARNING: One or both TA cards returned no data — skipping merge")
        return {}

    # ── Build lookup from card 6135: (session_id, batch) → metadata row ──────
    # Mirrors: df1.rename(columns={'lu_batch_name':'Batch','module_name':'Module'})
    meta = {}
    for row in rows1:
        sid   = str(row.get("session_id", ""))
        batch = str(row.get("lu_batch_name") or row.get("Batch") or "")
        key   = (sid, batch)
        if key not in meta:
            meta[key] = {
                "subjective_feedback": row.get("subjective_feedback") or "",
                "feedback_given":      row.get("feedback_given") or "",
                "rating":              row.get("rating"),
                "description":         row.get("description") or "",
                "Module":              row.get("module_name") or row.get("Module") or "",
                "topic":               row.get("topic") or "",
                "cancel_reason":       row.get("cancel_reason") or "",
                "action_time":         str(row.get("action_time") or ""),
                "booked_time":         str(row.get("booked_time") or ""),
                "au_start_date":       str(row.get("au_start_date") or ""),
                "au_batch_name":       row.get("au_batch_name") or "",
            }

    # ── Merge on (session_id, Batch) — mirrors pd.merge(df1, df2, on=['session_id','Batch']) ──
    # Card 6570 has student_user_id, session_start_time, over_lap_time_in_minute, batch
    by = {}
    skipped = 0
    seen_sessions = set()   # for rating dedup — mirrors groupby(session_id).transform first-only

    for row in rows2:
        uid = (row.get("student_user_id") or row.get("user_id") or
               row.get("student_id") or 0)
        try:
            uid = int(uid)
        except (ValueError, TypeError):
            skipped += 1
            continue

        if uid not in ids:
            continue

        sid   = str(row.get("session_id", ""))
        batch = str(row.get("batch") or row.get("Batch") or "")
        key   = (sid, batch)

        # Get metadata from card 6135 (inner join — skip if no match)
        m = meta.get(key)
        if m is None:
            continue

        # session_start_time → clean date string
        raw_dt = str(row.get("session_start_time") or "")
        session_date = raw_dt[:10] if len(raw_dt) >= 10 else ""

        # month_diff_period — months since batch start
        month_diff = None
        try:
            import datetime
            sess_dt  = datetime.datetime.fromisoformat(raw_dt[:19])
            start_dt = datetime.datetime.fromisoformat(str(m["au_start_date"])[:10])
            month_diff = (sess_dt.year - start_dt.year) * 12 + (sess_dt.month - start_dt.month)
        except Exception:
            pass

        # year_month_date_hour — mirrors df['year_month_date_hour']
        year_month_date_hour = raw_dt[:13].replace("T", "-") if len(raw_dt) >= 13 else ""

        # Rating dedup — mirrors: keep rating only for first occurrence of session_id
        rating = m.get("rating")
        if sid in seen_sessions:
            rating = None
        else:
            seen_sessions.add(sid)

        # duration
        try:
            duration = round(float(row.get("over_lap_time_in_minute") or 0), 1) or None
        except (ValueError, TypeError):
            duration = None

        by.setdefault(uid, []).append({
            "type":                 "ta",
            "session_id":           sid,
            "date":                 session_date,
            "year_month_date_hour": year_month_date_hour,
            "month_diff":           month_diff,
            "mentor":               (row.get("mentor_name") or row.get("counsellor_name") or "").strip(),
            "duration_mins":        duration,
            "rating":               rating,
            "Module":               m["Module"],
            "topic":                m["topic"],
            "description":          m["description"],
            "feedback_given":       m["feedback_given"],
            "subjective_feedback":  m["subjective_feedback"],
            "cancel_reason":        m["cancel_reason"],
            "action_time":          m["action_time"],
            "booked_time":          m["booked_time"],
            "au_batch_name":        m["au_batch_name"],
            "status":               row.get("session_status") or row.get("status") or "Conducted",
        })

    if skipped:
        log(f"  Skipped {skipped} rows with no parseable student ID")
    log(f"  TA merge complete: {len(by)} students "
        f"({sum(len(v) for v in by.values())} total sessions)")
    return by


# ── PHASE 2e: PLAYLISTS (card 9194) ──────────────────────────────────────────
def fetch_playlists(token, lu_id, ids):
    """
    Card 9194: Question-wise time spent per playlist.
    Cols: course_id, batch_name, user_id, student_name, playlist_title,
          assignment_title, question_id, question_title, difficulty_level,
          question_opened_at, question_completed_at, time_spent_mins,
          is_attempted, is_completed, score_achieved

    - Fetches ALL rows once (card has no per-student filter)
    - Deduplicates on (user_id, question_id) IRRESPECTIVE of batch
      → a question solved in any batch counts as solved once
      → keeps best attempt: completed > attempted; on tie → higher score → more time
    - Aggregates deduped questions to playlist level
    - 9194
    """

    log("Fetching playlist data (card 10267)...")
    headers = {"Content-Type": "application/json", "X-Metabase-Session": str(token)}
    id_set = set(ids)

    try:
        resp = requests.post(f"{METABASE_URL}/api/card/10267/query/json",
                             headers=headers, json={}, timeout=300)
        resp.raise_for_status()
        all_rows = resp.json() if isinstance(resp.json(), list) else []
        log(f"  Card 10267: {len(all_rows)} total rows")
    except Exception as e:
        log(f"  Card 10267 failed — {e}")
        return {}

    from collections import defaultdict

    # ── Step 1: Deduplicate on (user_id, question_id) — keep best attempt ─────
    best = {}
    for row in all_rows:
        uid = row.get("user_id")
        try:
            uid = int(uid)
        except:
            continue
        if uid not in id_set:
            continue
        qid = str(row.get("question_id") or "")
        key = (uid, qid)
        done = str(row.get("is_completed") or "").lower() in ("true", "1", "t")
        score = float(row.get("score_achieved") or 0)
        t_mins = float(row.get("time_spent_mins") or 0)
        prev = best.get(key)
        if prev is None:
            best[key] = row
        else:
            prev_done = str(prev.get("is_completed") or "").lower() in ("true", "1", "t")
            prev_score = float(prev.get("score_achieved") or 0)
            prev_time = float(prev.get("time_spent_mins") or 0)
            if (not prev_done and done) or (prev_done == done and (score > prev_score or
                                                                   (score == prev_score and t_mins > prev_time))):
                best[key] = row

    log(f"  After dedup: {len(best)} unique (user, question) pairs")

    # ── Step 2: Aggregate to (user_id, playlist_title) ────────────────────────
    agg = defaultdict(lambda: defaultdict(lambda: {
        "questions": [], "total_qs": 0, "done_qs": 0,
        "attempted_qs": 0, "not_attempted_qs": 0,
        "total_time": 0.0, "time_count": 0, "last_activity": None,
    }))

    for (uid, qid), row in best.items():
        pl = str(row.get("playlist_title") or "Unknown Playlist").strip()
        done = str(row.get("is_completed") or "").lower() in ("true", "1", "t")
        att = str(row.get("is_attempted") or "").lower() in ("true", "1", "t")
        t_mins = float(row.get("time_spent_mins") or 0)
        score = row.get("score_achieved")
        comp_at = str(row.get("question_completed_at") or "")[:10]

        d = agg[uid][pl]
        d["total_qs"] += 1
        if done:
            d["done_qs"] += 1
            if comp_at and (not d["last_activity"] or comp_at > d["last_activity"]):
                d["last_activity"] = comp_at
        elif att:
            d["attempted_qs"] += 1
        else:
            d["not_attempted_qs"] += 1
        if t_mins > 0:
            d["total_time"] += t_mins
            d["time_count"] += 1
        d["questions"].append({
            "question_title": (row.get("question_title") or "").strip(),
            "difficulty": row.get("difficulty_level") or "",
            "is_completed": done,
            "is_attempted": att,
            "score": score,
            "time_spent_mins": round(t_mins, 1) if t_mins else None,
            "solved_at": comp_at if done else "",
        })

    # ── Step 3: Build per-student list ────────────────────────────────────────
    pl_by = {}
    for uid, playlists in agg.items():
        entries = []
        for pl_name, d in playlists.items():
            tq = d["total_qs"]
            dq = d["done_qs"]
            pct = round(dq / tq * 100, 1) if tq > 0 else 0
            avg_t = round(d["total_time"] / d["time_count"], 1) if d["time_count"] > 0 else None
            entries.append({
                "playlist_title": pl_name,
                "total_questions": tq,
                "solved": dq,
                "attempted": d["attempted_qs"],
                "not_attempted": d["not_attempted_qs"],
                "completion_pct": pct,
                "completed": dq >= tq and tq > 0,
                "avg_time_mins": avg_t,
                "last_solved_date": d["last_activity"] or "",
                "questions": sorted(d["questions"],
                                    key=lambda q: q.get("solved_at") or ""),
            })
        entries.sort(key=lambda x: x["playlist_title"])
        pl_by[uid] = entries

    log(f"  Playlists aggregated for {len(pl_by)} students")
    return pl_by


def score_and_build(summary_rows, thresholds, batch_name, course_id,
                    lec_by, learn_by, app_by, contest_by, proj_by, ta_by, pl_by=None, mentor_by=None):
    W = thresholds["risk_weights"];
    T_ATT = thresholds["attendance"]
    T_ASGN = thresholds["assignment"];
    T_MC = thresholds["mc_score"]
    T_PROJ = thresholds["project"];
    T_TIERS = thresholds["risk_tiers"]

    final = []
    for r in summary_rows:
        uid = r["id"]
        att = float(r.get("att_pct") or 0)
        asgn = float(r.get("asgn_pct") or 0)
        # Use pre-computed contest score from fetch_contests_card if available
        # Fall back to SQL mc_best from assessments table
        _contests_pre = contest_by.get(uid, {})
        _mc1_pct = (_contests_pre.get("mc1") or {}).get("percentage") or 0
        _mc2_pct = (_contests_pre.get("mc2") or {}).get("percentage") or 0
        _mid_pct = (_contests_pre.get("mid_mc") or {}).get("percentage") or 0
        mc_best = max(float(_mc1_pct or 0), float(_mc2_pct or 0), float(r.get("mc_best") or 0))
        proj_best = float(r.get("proj_best") or 0)
        proj_subs = int(r.get("proj_subs") or 0)
        # Override with richer data from fetch_projects (Metabase cards) if available
        _proj_data = proj_by.get(uid) or proj_by.get(str(uid))
        if _proj_data:
            if _proj_data.get("marks") is not None:
                proj_best = float(_proj_data["marks"])
            if _proj_data.get("submissions") is not None:
                proj_subs = int(_proj_data["submissions"])
        ta_count = len(ta_by.get(uid, []))
        att_2w = float(r.get("att_2w") or 0)
        lec_2w = int(r.get("lec_2w_count") or 0)
        total_lec = int(r.get("total_lec") or 0)

        perf = (min(att, 100) * W["attendance"] + min(asgn, 100) * W["assignment"] +
                min(mc_best, 100) * W["mc_score"] + min(proj_best * 10, 100) * W["project"] +
                min(ta_count * 5, 100) * W["ta_sessions"])
        risk = round(100 - perf, 1)
        tier = "Strong"
        for t, b in T_TIERS.items():
            if b["min"] <= risk <= b["max"]: tier = t; break

        reasons = []
        if att_2w <= T_ATT.get("ghost_2w_att_threshold", 0) and lec_2w > 0:
            reasons.append("Ghost — 0% attendance")
        elif att < T_ATT["red_threshold"]:
            reasons.append(f"Low attendance ({att:.0f}%)")
        if asgn < T_ASGN["red_threshold"]: reasons.append(f"Assignment {asgn:.0f}% — below threshold")
        if mc_best == 0:
            reasons.append("No contest attempted")
        elif mc_best < T_MC["weak_threshold"]:
            reasons.append(f"MC score {mc_best:.0f}/100")
        if proj_subs == 0: reasons.append("Project not yet submitted")
        if ta_count == 0: reasons.append("No TA sessions booked")
        if not reasons: reasons.append("Strong performer" if risk < 35 else "Routine check-in")

        contests = contest_by.get(uid, {"mid_mc": None, "mc1": None, "mc2": None})
        learn_d = learn_by.get(uid, [])
        app_d = app_by.get(uid, [])
        all_asgn = learn_d + app_d
        lec_list = lec_by.get(uid, [])
        missed = [f"{l['date']} — {l['title']}" for l in lec_list if not l["attended"]]
        unsolved = [f"{d['topic']} ({d['difficulty']})" for d in all_asgn if
                    d["total_released"] > 0 and d["solved"] < d["total_released"] and d["attempted"] > 0]
        not_attempted = [f"{d['topic']} ({d['difficulty']})" for d in all_asgn if
                         d["total_released"] > 0 and d["attempted"] == 0]

        mc1_c = contests["mc1"]["cleared"] if contests["mc1"] else False
        mc2_c = contests["mc2"]["cleared"] if contests["mc2"] else False
        mid_c = contests["mid_mc"]["cleared"] if contests["mid_mc"] else False

        mod = {
            "att": att, "live_mins": float(r.get("live_mins") or 0), "att_2w": att_2w,
            "total_lec": total_lec, "asgn": asgn, "total_q": int(r.get("total_q") or 0),
            "easy": int(r.get("easy") or 0), "med": int(r.get("med") or 0), "hard": int(r.get("hard") or 0),
            "late_sub": int(r.get("late_sub") or 0), "last_solve": r.get("last_solve"),
            "mc_best": mc_best, "mc_att": int(r.get("mc_attempts") or 0),
            "proj_best": proj_best, "proj_subs": proj_subs, "proj_late": bool(r.get("proj_late") or 0),
            "ta_count": ta_count,
            "current_class": total_lec, "current_phase": 2,
            "contests": contests, "lectures": lec_list,
            "asgn_detail": learn_d, "app_detail": app_d,
            "playlist_detail": ((pl_by or {}).get(uid) or []), "ta_sessions": ta_by.get(uid, []),
            "ta_sessions_detail": ta_by.get(uid, []),
            "mentor_sessions": (mentor_by or {}).get(uid, []), "missed_lectures": missed,
            "unsolved_topics": unsolved, "not_attempted_topics": not_attempted,
            "mentor_count": len((mentor_by or {}).get(uid, [])), "project": proj_by.get(uid) or proj_by.get(str(uid)),
            "learn_solved": sum(d["solved"] for d in learn_d),
            "learn_total": sum(d["total_released"] for d in learn_d),
            "app_solved": sum(d["solved"] for d in app_d),
            "app_total": sum(d["total_released"] for d in app_d),
            "mc1_cleared": mc1_c, "mc2_cleared": mc2_c, "mid_mc_cleared": mid_c,
            "any_final_mc_cleared": mc1_c or mc2_c,
        }
        asgn_solved = mod["learn_solved"] + mod["app_solved"]
        asgn_total = mod["learn_total"] + mod["app_total"]
        final.append({
            "id": uid, "name": r["name"], "email": r["email"], "batch": batch_name, "course_id": course_id,
            "risk": risk, "tier": tier, "reason": " · ".join(reasons),
            "avg_att": att, "avg_asgn": asgn, "avg_mc": mc_best, "avg_proj": round(proj_best, 2),
            "ta": ta_count, "att_2w": att_2w, "days_inactive": days_since(r.get("last_solve")),
            "proj_pending": proj_subs == 0, "proj_passed": proj_best >= T_PROJ["pass_threshold"],
            "asgn_solved": asgn_solved, "asgn_total": asgn_total,
            "mid_mc_score": contests["mid_mc"]["percentage"] if contests["mid_mc"] else None,
            "mc1_score": contests["mc1"]["percentage"] if contests["mc1"] else None,
            "mc2_score": contests["mc2"]["percentage"] if contests["mc2"] else None,
            "mods": {"Spreadsheets": mod},
        })
    final.sort(key=lambda x: -x["risk"])
    return final

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    log("="*60)
    log(f"NS SM Brain Engine — Refresh ({len(BATCH_CONFIGS)} batches, all students)")
    log("="*60)
    if not METABASE_PASS: log("ERROR: METABASE_PASSWORD not set."); sys.exit(1)
    with open(THRESHOLDS_PATH) as f: thresholds = json.load(f)

    all_students, all_stats = [], {}

    for batch_name, cfg in BATCH_CONFIGS.items():
        log(f"\n── Batch: {batch_name} ──")
        au_id, lu_id = cfg["au_id"], cfg["lu_id"]

        token = get_session_token()
        try: summary = fetch_summary(token, batch_name, au_id, lu_id)
        finally: logout(token); log("  Phase 1 done.")

        if not summary: log("  No data — skipping"); continue
        ids = [r["id"] for r in summary]

        token = get_session_token()
        try:
            lec_by            = fetch_lectures(token, lu_id, ids)
            learn_by, app_by  = fetch_asgn_detail(token, lu_id, ids)
            contest_by        = fetch_contests_card(token, lu_id, ids, batch_name)
            proj_by           = fetch_projects(token, lu_id, ids, batch_name)
            pl_by             = fetch_playlists(token, lu_id, ids)
        finally: logout(token); log("  Phase 2 done.")

        token = get_session_token()
        try:
            ta_by     = fetch_ta_sessions(token, set(ids))
            mentor_by = fetch_mentor_sessions(token, set(ids))
        finally: logout(token); log("  Phase 3 done.")

        scored = score_and_build(summary, thresholds, batch_name, lu_id,
                                 lec_by, learn_by, app_by, contest_by, proj_by, ta_by, pl_by, mentor_by)
        log(f"  Scored {len(scored)} students")
        stats = {"total":len(scored),"high":0,"medium":0,"low":0,"strong":0}
        for s in scored:
            t=s["tier"]
            if t=="High Risk": stats["high"]+=1
            elif t=="Medium Risk": stats["medium"]+=1
            elif t=="Low Risk": stats["low"]+=1
            else: stats["strong"]+=1
        all_students.extend(scored)
        all_stats[batch_name] = stats
        log(f"  Stats: {stats}")

    if not all_students: log("ERROR: No students."); sys.exit(1)
    all_students.sort(key=lambda x: -x["risk"])
    output = {"students":all_students,"batch_stats":all_stats,
              "refreshed_at":datetime.datetime.now().isoformat(),"thresholds":thresholds}
    with open(OUTPUT_PATH,"w") as f: json.dump(output, f, indent=2, default=str)
    log(f"\nSaved → {OUTPUT_PATH}  ({len(all_students)} students)")

    # ── Biweekly history snapshot ──────────────────────────────────────────────
    HISTORY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.json")
    snap_date = datetime.datetime.now().strftime("%Y-%m-%d")
    snapshot = {
        "date": snap_date,
        "students": {
            str(s["id"]): {
                "risk":      s["risk"],
                "att":       s["avg_att"],
                "asgn":      s["avg_asgn"],
                "mc":        s["avg_mc"],
                "proj_best": s["avg_proj"],
                "ta":        s["ta"],
                "inactive":  s["days_inactive"],
            }
            for s in all_students
        }
    }
    history = []
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH) as f: history = json.load(f)
        except Exception: history = []
    history = [h for h in history if h["date"] != snap_date]
    history.append(snapshot)
    history = sorted(history, key=lambda x: x["date"])[-20:]
    with open(HISTORY_PATH, "w") as f: json.dump(history, f, indent=2, default=str)
    log(f"History snapshot saved → {HISTORY_PATH}  ({len(history)} snapshots)")
    log("="*60)

if __name__ == "__main__":
    main()