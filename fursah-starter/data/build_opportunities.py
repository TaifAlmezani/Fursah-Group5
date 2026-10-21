"""Build data/prepared/opportunities.json from the raw announcements.

Run from fursah-starter/:   python data/build_opportunities.py

Step 1 of the FURSAH backend. The raw CSV stays unchanged; this script is the
reproducible preparation process. It works in two stages:

  1. extract_facts(): read ONE announcement and pull out the facts it states.
  2. build_opportunity(): group announcements about the SAME activity
     (same info link) into one opportunity, keeping every source ID and
     recording conflicts instead of silently picking a winner.

Policy for unknowns (also in data/README.md):
  - Missing fee   -> cost_sar = None (unknown), NOT 0. Only "المشاركة مجانية" gives 0.
  - Missing skills -> required_skills = None (unknown).
  - No conditions found -> eligibility_mandatory = None (unknown), never "eligible".
  - Deadlines are dates only (no cutoff time), so we never invent an hour.
  - Expiry is NOT decided here; the backend decides it at request time.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
RAW_PATH = DATA_DIR / "raw" / "raw_opportunities.csv"
OUT_PATH = DATA_DIR / "prepared" / "opportunities.json"

# --------------------------------------------------------------------------
# Vocabulary (taken from the actual wording found in the 1,000 announcements)
# --------------------------------------------------------------------------
MONTHS = {
    "يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "مايو": 5, "يونيو": 6,
    "يوليو": 7, "أغسطس": 8, "سبتمبر": 9, "أكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12,
}
DATE = r"(\d{1,2}) (" + "|".join(MONTHS) + r") (\d{4})"

# Arabic phrase -> frontend opportunity type. Longer phrases first so that
# "دورة من عدة لقاءات" is not mistaken for something shorter.
TYPE_PHRASES = [
    ("فرصة تدريب ميداني بإشراف الفريق", "internship"),
    ("تدريب عملي داخل مقر العمل", "internship"),
    ("تدريب مهني داخل المؤسسة", "internship"),
    ("برنامج تعليمي متسلسل", "course"),
    ("دورة من عدة لقاءات", "course"),
    ("دورة تدريبية", "course"),
    ("جلسة تدريبية عملية", "workshop"),
    ("ورشة تطبيقية", "workshop"),
    ("ورشة عمل", "workshop"),
    ("منافسة لتطوير فكرة", "competition"),
    ("تحدي تنافسي", "competition"),
    ("مسابقة فرق", "competition"),
    ("مهمة تطوعية مجتمعية", "volunteering"),
    ("نشاط تطوعي", "volunteering"),
    ("فرصة للتطوع", "volunteering"),
    ("فعالية حوارية", "event"),
    ("لقاء مفتوح", "event"),
    ("أمسية معرفية", "event"),
]

# Short city names used in the text -> the frontend's city list.
CITY_ALIASES = {"مكة": "مكة المكرمة", "المدينة": "المدينة المنورة"}

# Base topic -> frontend interests. This is a team editorial decision
# (documented here), not a fact stated by the source.
TOPIC_INTERESTS = {
    "أفكار للمساحات العامة": ["خدمة المجتمع", "العمارة"],
    "إدارة مشروع صغير": ["إدارة المشاريع", "ريادة الأعمال"],
    "إعداد أنشطة تعلم تفاعلية": ["التعليم", "التدريب"],
    "إنتاج قصة صوتية قصيرة": ["صناعة المحتوى", "الإعلام"],
    "استعلامات SQL للبيانات": ["البيانات", "البرمجة", "علم البيانات"],
    "استقبال زوار المعرض": ["الضيافة", "الثقافة"],
    "الترجمة للمحتوى التعليمي": ["الترجمة", "اللغات", "التعليم"],
    "التوعية بالنوم الصحي": ["الصحة", "الصحة العامة"],
    "القراءة مع الأطفال": ["القراءة", "التعليم"],
    "الكتابة العربية الواضحة": ["الكتابة", "اللغات"],
    "المحادثة الإنجليزية في العمل": ["اللغات"],
    "الميزانية الشخصية": ["المالية"],
    "تجربة المستخدم للخدمات المحلية": ["تجربة المستخدم", "التصميم"],
    "تحرير نشرة مجتمعية": ["الكتابة", "الإعلام", "خدمة المجتمع"],
    "تحليل البيانات باستخدام Excel": ["البيانات", "علم البيانات"],
    "ترشيد المياه في المباني": ["المياه", "الاستدامة", "البيئة"],
    "تصميم الملصق الثقافي": ["التصميم", "الفنون", "الثقافة"],
    "تصميم رسائل صحية مفهومة": ["الصحة العامة", "التسويق", "الصحة"],
    "تصميم هوية مبسطة": ["التصميم", "التسويق"],
    "تصوير القصص بالهاتف": ["التصوير", "صناعة المحتوى"],
    "تنظيم الملاحظات البحثية": ["البحث العلمي"],
    "تنظيم مكتبة الحي": ["القراءة", "خدمة المجتمع"],
    "خدمة العملاء في المتاجر": ["الأعمال", "التسويق"],
    "رصد المساحات الخضراء": ["البيئة", "الاستدامة"],
    "صياغة سؤال بحثي": ["البحث العلمي"],
    "عرض الأفكار أمام الجمهور": ["القيادة", "ريادة الأعمال"],
    "فرز النفايات في الأحياء": ["البيئة", "الاستدامة", "خدمة المجتمع"],
    "قراءة التقارير المالية": ["المالية", "المحاسبة"],
    "لوحات Power BI": ["البيانات", "علم البيانات"],
    "مبادئ المحاسبة العملية": ["المحاسبة", "المالية"],
    "مقدمة في Python": ["البرمجة", "التقنية"],
}
TITLE_SUFFIXES = r" (خطوة بخطوة|للمجتمع|للمهتمين|في الممارسة|من الفكرة إلى التطبيق)$"

# Registration statements. Order matters: cancellation beats everything.
REGISTRATION_PATTERNS = [
    ("cancelled", r"أُلغيت هذه الفرصة|تم إلغاء النشاط|ألغوه"),
    ("closed", r"أُغلق التسجيل لاكتمال المقاعد"),
    ("closed", r"انتهى استقبال الطلبات|باب التقديم مغلق"),
    ("not_yet_open", r"لم يبدأ التسجيل بعد|سيُفتح التسجيل مجدداً"),
    ("open", r"تُستقبل الطلبات الآن|باب المشاركة مفتوح|التسجيل مفتوح حالياً"),
]

# Fields where two announcements may disagree. Used when merging a group.
MERGED_FACTS = [
    "title", "opportunity_type", "delivery_mode", "location", "start_date",
    "end_date", "deadline_date", "cost_sar", "registration_statement",
    "session_count", "hours_per_session",
]


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def parse_date(day: str, month: str, year: str) -> str:
    return date(int(year), MONTHS[month], int(day)).isoformat()


def find_date(pattern: str, text: str) -> str | None:
    match = re.search(pattern.replace("{D}", DATE), text)
    return parse_date(*match.groups()[:3]) if match else None


def base_topic(title: str | None) -> str | None:
    return re.sub(TITLE_SUFFIXES, "", title) if title else None


def normalize_city(city: str) -> str:
    return CITY_ALIASES.get(city.strip(), city.strip())


# --------------------------------------------------------------------------
# Stage 1: facts stated by ONE announcement
# --------------------------------------------------------------------------
def extract_facts(row: dict[str, str]) -> dict:
    text = row["content"]
    org = row["source_name"]
    facts: dict = {"source_id": row["source_id"], "published_at": row["published_at"]}

    # Kind of announcement: helps decide whose facts win when merging.
    if re.search(r"تحديث من .+? بتاريخ", text):
        facts["kind"] = "update"
    elif "معلومة مختلفة" in text:
        facts["kind"] = "conflicting_repost"
    elif re.search(r"تذكير من|إعادة نشر", text):
        facts["kind"] = "reminder"
    else:
        facts["kind"] = "announcement"

    # Title: the first «…» quote that is not the organizer's own name.
    quotes = [q for q in re.findall(r"«([^»]+)»", text) if q.strip() != org]
    facts["title"] = quotes[0].strip() if quotes else None

    # Opportunity type.
    facts["opportunity_type"] = facts["type_label_ar"] = None
    for phrase, kind in TYPE_PHRASES:
        if phrase in text:
            facts["opportunity_type"], facts["type_label_ar"] = kind, phrase
            break

    # Delivery mode, city and attendance. Only these explicit sentences count;
    # an opening like "من مكة، نشارككم" is NOT the activity location.
    facts["delivery_mode"] = facts["location"] = None
    facts["physical_attendance_required"] = facts["remote_participation_allowed"] = None
    if m := re.search(r"البداية حضورية في ([^،]+)، ثم تُعقد جلسة متابعة عن بعد", text):
        facts.update(delivery_mode="hybrid", location=normalize_city(m.group(1)),
                     physical_attendance_required=True)
    elif "المشاركة عن بعد بالكامل" in text:
        facts.update(delivery_mode="online", physical_attendance_required=False,
                     remote_participation_allowed=True)
    elif m := (re.search(r"الحضور في (.+?) داخل مقر", text)
               or re.search(r"العمل حضوري داخل مقر .+? في ([^\.\n]+)", text)):
        facts.update(delivery_mode="in_person", location=normalize_city(m.group(1)),
                     physical_attendance_required=True, remote_participation_allowed=False)

    # Activity dates (the body always states the CURRENT dates, even in updates).
    facts["start_date"] = find_date(r"يبدأ البرنامج يوم {D}", text)
    facts["end_date"] = find_date(r"وينتهي يوم {D}", text)
    if one_day := find_date(r"نشاط ليوم واحد بتاريخ {D}", text):
        facts["start_date"] = facts["end_date"] = one_day

    # Sessions and hours are separate from calendar duration.
    facts["session_count"] = facts["hours_per_session"] = None
    if m := re.search(r"يشمل (\d+) لقاءات، مدة كل لقاء ساعتان", text):
        facts["session_count"], facts["hours_per_session"] = int(m.group(1)), 2.0

    # Deadline: the LAST "آخر يوم للتقديم <date>" sentence that is not the
    # "from A to B" part of an update line.
    body = re.sub(r"ومُدد آخر يوم للتقديم من .+? إلى " + DATE, "", text)
    facts["deadline_date"] = find_date(r"آخر يوم للتقديم {D}", body)
    # An update states the new deadline as "من <old> إلى <new>"; the new one wins.
    facts["deadline_extended"] = False
    if m := re.search(r"ومُدد آخر يوم للتقديم من " + DATE + " إلى " + DATE, text):
        facts["deadline_date"] = parse_date(*m.groups()[3:6])
        facts["deadline_extended"] = True

    # Registration statement (what the source said at publication time).
    facts["registration_statement"] = None
    for status, pattern in REGISTRATION_PATTERNS:
        if re.search(pattern, text):
            facts["registration_statement"] = status
            break
    facts["registration_opens_date"] = find_date(r"يفتح يوم {D}", text)

    # Fee: 0 only when explicitly free; unknown stays None.
    if m := re.search(r"رسوم المشاركة (\d+) ريال", text):
        facts["cost_sar"], facts["cost_evidence"] = float(m.group(1)), m.group(0)
    elif "المشاركة مجانية" in text:
        facts["cost_sar"], facts["cost_evidence"] = 0.0, "المشاركة مجانية"
    else:
        facts["cost_sar"] = None
        facts["cost_evidence"] = "لم تُحدد رسوم المشاركة" if "لم تُحدد رسوم" in text else None

    # Skills: required vs. merely preferred.
    required = re.findall(r"معرفة (.+?) مطلوبة", text)
    preferred = re.findall(r"تُعد معرفة (.+?) ميزة إضافية", text)
    facts["required_skills"] = required or None
    facts["preferred_skills"] = preferred or None

    # Mandatory conditions, kept as the source's own sentences.
    mandatory = [f"معرفة {s} مطلوبة" for s in required]
    min_age = None
    if m := re.search(r"يشترط أن يكون عمر المشارك (\d+) سنة فأكثر", text):
        min_age = int(m.group(1))
        mandatory.append(m.group(0))
    final_year_field = None
    if m := re.search(r"يشترط أن يكون المتقدم طالباً في السنة الأخيرة من تخصص ذي صلة بـ\s*(\S+(?: \S+)?)", text):
        final_year_field = m.group(1).rstrip(".،")
        mandatory.append(f"يشترط أن يكون المتقدم طالباً في السنة الأخيرة من تخصص ذي صلة بـ{final_year_field}")
    facts["eligibility_mandatory"] = mandatory or None
    facts["eligibility_preferred"] = [f"معرفة {s} ميزة إضافية وليست شرطاً" for s in preferred] or None
    facts["min_age"] = min_age
    facts["final_year_student_field"] = final_year_field

    facts["application_url"] = (re.search(r"https?://\S+", text) or [None])[0]
    return facts


# --------------------------------------------------------------------------
# Stage 2: merge announcements about the same activity
# --------------------------------------------------------------------------
def build_opportunity(rows: list[dict], facts: list[dict]) -> dict:
    # Oldest first; the first announcement gives the stable opportunity ID.
    order = sorted(range(len(rows)), key=lambda i: rows[i]["published_at"])
    rows = [rows[i] for i in order]
    facts = [facts[i] for i in order]
    primary = next((f for f in facts if f["kind"] == "announcement"), facts[0])
    updates = [f for f in facts if f["kind"] == "update"]

    merged: dict = {}
    conflicts: list[dict] = []
    warnings: list[str] = []

    for field in MERGED_FACTS:
        # An explicit update announcement corrects every fact it states.
        # Facts the update does not mention keep the earlier value.
        stated = [u[field] for u in updates if u[field] is not None]
        if stated:
            merged[field] = stated[-1]
            continue
        values = {}
        for f in facts:
            if f[field] is not None:
                values.setdefault(json.dumps(f[field], ensure_ascii=False), []).append(f["source_id"])
        if len(values) <= 1:
            merged[field] = next((f[field] for f in facts if f[field] is not None), None)
        else:
            # Unresolved disagreement: keep both claims, do not choose one.
            merged[field] = None
            conflicts.append({
                "field": field,
                "claims": [{"value": json.loads(v), "source_ids": ids} for v, ids in values.items()],
            })

    if any(u["deadline_extended"] and u["registration_statement"] == "closed" for u in updates):
        u = updates[-1]
        conflicts.append({"field": "registration_statement", "claims": [
            {"value": f"مُدد آخر يوم للتقديم إلى {u['deadline_date']}", "source_ids": [u["source_id"]]},
            {"value": "انتهى استقبال الطلبات", "source_ids": [u["source_id"]]},
        ]})
        merged["registration_statement"] = None
    if updates:
        warnings.append(f"عُدّل الموعد أو آخر يوم للتقديم بإعلان تحديث لاحق ({updates[-1]['source_id']}).")
    labels = {"cost_sar": "الرسوم", "deadline_date": "آخر يوم للتقديم", "start_date": "تاريخ البداية",
              "end_date": "تاريخ النهاية", "location": "المدينة", "delivery_mode": "طريقة الحضور",
              "registration_statement": "حالة التسجيل", "title": "العنوان", "opportunity_type": "نوع الفرصة"}
    for c in conflicts:
        claims = "، ".join(f"{cl['value']} ({'/'.join(cl['source_ids'])})" for cl in c["claims"])
        warnings.append(f"تعارض بين المصادر حول {labels.get(c['field'], c['field'])}: {claims}.")

    # Facts that are only stated by the primary announcement.
    keep_primary = ["type_label_ar", "physical_attendance_required", "remote_participation_allowed",
                    "registration_opens_date", "cost_evidence",
                    "required_skills", "preferred_skills", "eligibility_mandatory",
                    "eligibility_preferred", "min_age", "final_year_student_field", "application_url"]
    for field in keep_primary:
        merged[field] = primary[field]
    if any(c["field"] == "cost_sar" for c in conflicts):
        merged["cost_evidence"] = None
    if merged["delivery_mode"] == "hybrid":
        warnings.append("البرنامج مدمج: اللقاء الأول حضوري وإلزامي، وجلسة المتابعة عن بعد.")

    # Calendar duration in days (inclusive) is separate from hours.
    duration = None
    if merged["start_date"] and merged["end_date"]:
        duration = (date.fromisoformat(merged["end_date"]) - date.fromisoformat(merged["start_date"])).days + 1
        duration = duration if duration > 0 else None
    total_hours = None
    if merged["session_count"] and merged["hours_per_session"]:
        total_hours = merged["session_count"] * merged["hours_per_session"]

    if merged["title"] is None:
        warnings.append("تعذر استخراج عنوان النشاط من النص.")
    if merged["deadline_date"] is None:
        warnings.append("آخر يوم للتقديم غير مذكور أو غير مؤكد.")
    elif merged["deadline_date"]:
        warnings.append("آخر يوم للتقديم مذكور بالتاريخ فقط دون ساعة محددة.")
    if merged["cost_sar"] is None and not any(c["field"] == "cost_sar" for c in conflicts):
        warnings.append("الرسوم غير مذكورة؛ القيمة مجهولة وليست مجانية.")
    if merged["eligibility_mandatory"] is None:
        warnings.append("لم يذكر المصدر شروطاً إلزامية؛ لا يعني ذلك تأكيد الأهلية.")

    topic = base_topic(merged["title"])
    source_ids = [r["source_id"] for r in rows]

    # evidence_version changes whenever any supporting text changes.
    digest = hashlib.sha256()
    for r in rows:
        digest.update(f"{r['source_id']}\n{r['published_at']}\n{r['content']}\n".encode("utf-8"))

    return {
        "opportunity_id": primary["source_id"],
        "source_ids": source_ids,
        "evidence_version": digest.hexdigest()[:16],
        "title": merged["title"],
        "organizer": rows[0]["source_name"],
        "topic": topic,
        "topics": TOPIC_INTERESTS.get(topic, []),
        "description": next(r["content"] for r in rows if r["source_id"] == primary["source_id"]),
        **{k: merged[k] for k in merged if k != "title"},
        "duration_days": duration,
        "total_hours": total_hours,
        "latest_published_at": rows[-1]["published_at"],
        "sources": [{"source_id": f["source_id"], "kind": f["kind"], "published_at": f["published_at"]}
                    for f in facts],
        "conflicts": conflicts,
        "data_warnings": warnings,
    }


def group_key(row: dict, facts: dict) -> str:
    """Announcements about one activity share its info link."""
    return facts["application_url"] or f"no-url:{row['source_id']}"


def main() -> None:
    with RAW_PATH.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))

    groups: dict[str, tuple[list, list]] = defaultdict(lambda: ([], []))
    for row in rows:
        facts = extract_facts(row)
        bucket = groups[group_key(row, facts)]
        bucket[0].append(row)
        bucket[1].append(facts)

    opportunities = [build_opportunity(r, f) for r, f in groups.values()]
    opportunities.sort(key=lambda o: o["opportunity_id"])

    covered = sum(len(o["source_ids"]) for o in opportunities)
    assert covered == len(rows), "every raw announcement must belong to exactly one opportunity"

    OUT_PATH.write_text(json.dumps(opportunities, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(rows)} announcements -> {len(opportunities)} opportunities -> {OUT_PATH}")


if __name__ == "__main__":
    main()