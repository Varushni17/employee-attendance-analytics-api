"""Employee Attendance & Analytics API. Run: python -m uvicorn app.main:app --port 8000 --reload"""

import os, re

from datetime import datetime, date, timedelta, timezone

from decimal import Decimal, ROUND_HALF_UP

from typing import Optional, Literal, Any

from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Query

from pydantic import BaseModel, Field, ConfigDict, field_validator

from pymongo import MongoClient, ASCENDING, DESCENDING, ReturnDocument

from pymongo.errors import DuplicateKeyError, PyMongoError



load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"), tz_aware=True, serverSelectionTimeoutMS=3000)

db = client[os.getenv("MONGO_DB", "attendance_db")]

employees, attendance = db["employees"], db["attendance_logs"]

IST = timezone(timedelta(hours=5, minutes=30))

UTC = timezone.utc

PRESENCE = ["PRESENT", "WFH", "ON_DUTY"]

STATUSES = PRESENCE + ["ABSENT", "LEAVE"]

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")



# ----------------------------- Helpers ---------------------------------------

def now_utc():

    return datetime.now(UTC).replace(microsecond=0)



def utc(dt):

    if dt is None: return None

    if dt.tzinfo is None: dt = dt.replace(tzinfo=UTC)

    return dt.astimezone(UTC).replace(microsecond=0)



def from_ms(value):

    if value is None: return None

    if isinstance(value, bool) or not isinstance(value, int) or not 100_000_000_000 <= value <= 4_102_444_800_000:

        raise HTTPException(422, "timestamp must be integer epoch milliseconds in the supported range")

    return datetime.fromtimestamp(value // 1000, UTC).replace(microsecond=0)



def to_ms(dt):

    return int(utc(dt).timestamp()) * 1000 if dt is not None else None



def rounded(value, places=2):

    q = Decimal("1").scaleb(-places)

    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))



def parse_day(s, name="date"):

    try:

        d = date.fromisoformat(s)

        if d.isoformat() != s: raise ValueError()

        return d

    except (ValueError, TypeError):

        raise HTTPException(422, f"{name} must use YYYY-MM-DD")



def month_range(month):

    if not re.fullmatch(r"\d{4}-\d{2}", month or ""): raise HTTPException(422, "month must use YYYY-MM")

    try: start = date.fromisoformat(month + "-01")

    except ValueError: raise HTTPException(422, "invalid month")

    end = date(start.year + (start.month == 12), 1 if start.month == 12 else start.month + 1, 1) - timedelta(days=1)

    return start, end



def clock(s):

    if not isinstance(s, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", s):

        raise HTTPException(422, "time must use HH:MM")

    h, m = map(int, s.split(":")); return h, m



def local(dt): return utc(dt).astimezone(IST)



def shift_start(day, start):

    h, m = clock(start); d = parse_day(day)

    return datetime(d.year, d.month, d.day, h, m, tzinfo=IST).astimezone(UTC).replace(microsecond=0)



def shift_end(day, start, end):

    sh, sm = clock(start); eh, em = clock(end); d = parse_day(day)

    if eh * 60 + em <= sh * 60 + sm: d += timedelta(days=1)

    return datetime(d.year, d.month, d.day, eh, em, tzinfo=IST).astimezone(UTC).replace(microsecond=0)



def record_day(punch, start, end):

    l = local(punch); sh, sm = clock(start); eh, em = clock(end)

    if eh * 60 + em <= sh * 60 + sm and l.hour * 60 + l.minute < eh * 60 + em:

        return (l.date() - timedelta(days=1)).isoformat()

    return l.date().isoformat()



def late_minutes(punch, day, start):

    if punch is None: return 0

    seconds = (utc(punch) - shift_start(day, start)).total_seconds()

    return int(seconds // 60) if seconds > 600 else 0



def work_hours(pin, pout):

    if pin is None or pout is None: return None

    return rounded((utc(pout) - utc(pin)).total_seconds() / 3600, 2)




def overtime_minutes(pin, pout, day, start, end):
    # If either punch is missing, there is no overtime.
    if pin is None or pout is None:
        return 0

    # Find the scheduled shift end.
    scheduled_end = shift_end(day, start, end)

    # A punch-in at or after shift end should not earn overtime.
    if utc(pin) >= scheduled_end:
        return 0

    # Calculate whole minutes worked after shift end.
    mins = int((utc(pout) - scheduled_end).total_seconds() // 60)

    # Count overtime only when it reaches 30 minutes.
    return mins if mins >= 30 else 0




def half_day(hours): return hours is not None and hours < 4.5



def require_employee(code):

    e = employees.find_one({"emp_code": code})

    if not e: raise HTTPException(404, "employee not found")

    return e



def public_record(d):

    result = {k: d.get(k) for k in ("emp_code", "date", "status", "work_hours")}

    result.update(punch_in=to_ms(d.get("punch_in")), punch_out=to_ms(d.get("punch_out")),

                  late_minutes=int(d.get("late_minutes", 0) or 0),

                  overtime_minutes=int(d.get("overtime_minutes", 0) or 0),

                  half_day=bool(d.get("half_day", False)), history=[])

    for h in d.get("history", []):

        changes = {}

        for key, v in (h.get("changes") or {}).items():

            changes[key] = {"from": to_ms(v.get("from")) if key in ("punch_in","punch_out") and isinstance(v.get("from"), datetime) else v.get("from"),

                            "to": to_ms(v.get("to")) if key in ("punch_in","punch_out") and isinstance(v.get("to"), datetime) else v.get("to")}

        result["history"].append({"at": to_ms(h.get("at")), "by": h.get("by"), "reason": h.get("reason"), "changes": changes})

    return result



def indexes():

    employees.create_index([("emp_code", ASCENDING)], unique=True, name="uq_employee_code")

    employees.create_index([("department", ASCENDING), ("emp_code", ASCENDING)], name="ix_employee_department")

    employees.create_index([("joined_on", ASCENDING), ("department", ASCENDING)], name="ix_employee_joined")

    attendance.create_index([("emp_code", ASCENDING), ("date", ASCENDING)], unique=True, name="uq_attendance_emp_date")

    attendance.create_index([("date", DESCENDING), ("emp_code", ASCENDING)], name="ix_attendance_date_emp")

    attendance.create_index([("emp_code", ASCENDING), ("date", DESCENDING)], name="ix_attendance_emp_date")

    attendance.create_index([("status", ASCENDING), ("date", DESCENDING)], name="ix_attendance_status_date")



@app.on_event("startup")

def startup():

    indexes()



# -------------------------------- Models --------------------------------------

class EmployeeCreate(BaseModel):

    model_config = ConfigDict(extra="forbid")

    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")

    name: str = Field(min_length=1, max_length=100)

    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    department: str = Field(min_length=1, max_length=50)

    shift_start: str = "09:30"

    shift_end: str = "18:30"

    joined_on: str

    @field_validator("shift_start", "shift_end")

    @classmethod

    def valid_clock(cls, v): clock(v); return v

    @field_validator("joined_on")

    @classmethod

    def valid_joined(cls, v): parse_day(v, "joined_on"); return v



class PunchInRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    emp_code: str

    punched_at: Optional[int] = None

    status: Literal["PRESENT", "WFH", "ON_DUTY"] = "PRESENT"

    @field_validator("punched_at", mode="before")

    @classmethod

    def valid_ms(cls, v):

        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not 100_000_000_000 <= v <= 4_102_444_800_000): raise ValueError("use integer epoch milliseconds")

        return v



class PunchOutRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    emp_code: str

    punched_at: Optional[int] = None

    @field_validator("punched_at", mode="before")

    @classmethod

    def valid_ms(cls, v):

        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not 100_000_000_000 <= v <= 4_102_444_800_000): raise ValueError("use integer epoch milliseconds")

        return v



class RegularizeRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    status: Optional[Literal["PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"]] = None

    punch_in: Optional[int] = None

    punch_out: Optional[int] = None

    reason: str = Field(min_length=5, max_length=200)

    regularized_by: str = Field(min_length=1, max_length=50)

    @field_validator("punch_in", "punch_out", mode="before")

    @classmethod

    def valid_ms(cls, v):

        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not 100_000_000_000 <= v <= 4_102_444_800_000): raise ValueError("use integer epoch milliseconds")

        return v



# -------------------------------- Health --------------------------------------

@app.get("/health")

def health():

    try: client.admin.command("ping"); return {"status": "ok"}

    except PyMongoError: raise HTTPException(503, "MongoDB unavailable")



# -------------------------------- Employees -----------------------------------

@app.post("/employees", status_code=201)

def create_employee(body: EmployeeCreate):

    if body.shift_start == body.shift_end: raise HTTPException(422, "shift_start and shift_end must differ")

    doc = body.model_dump(); doc["created_at"] = now_utc()

    try: employees.insert_one(doc)

    except DuplicateKeyError: raise HTTPException(409, "emp_code already exists")

    doc.pop("_id", None); return doc



@app.get("/employees")

def list_employees(department: Optional[str] = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):

    q = {"department": department} if department else {}

    return {"items": list(employees.find(q, {"_id":0}).sort("emp_code", ASCENDING).skip((page-1)*page_size).limit(page_size)),

            "total": employees.count_documents(q), "page": page, "page_size": page_size}



# -------------------------------- Attendance ----------------------------------

@app.post("/attendance/punch-in", status_code=201)

def punch_in(body: PunchInRequest):

    emp = require_employee(body.emp_code)

    ts = from_ms(body.punched_at) if body.punched_at is not None else now_utc()

    day = record_day(ts, emp["shift_start"], emp["shift_end"])

    doc = {"emp_code": body.emp_code, "date": day, "status": body.status, "punch_in": ts, "punch_out": None,

           "work_hours": None, "late_minutes": late_minutes(ts, day, emp["shift_start"]),

           "overtime_minutes": 0, "half_day": False, "history": []}

    try: attendance.insert_one(doc)

    except DuplicateKeyError: raise HTTPException(409, "attendance already exists for this employee and date")

    return public_record(doc)



@app.post("/attendance/punch-out")

def punch_out(body: PunchOutRequest):

    emp = require_employee(body.emp_code)

    ts = from_ms(body.punched_at) if body.punched_at is not None else now_utc()

    today = local(ts).date()

    days = [(today-timedelta(days=i)).isoformat() for i in range(3)]

    doc = attendance.find_one(
        {
            "emp_code": body.emp_code,
            "date": {"$in": days},
            "punch_in": {"$lte": ts},
            "punch_out": None,
            "status": {"$in": PRESENCE},
        },
        sort=[("punch_in", DESCENDING), ("date", DESCENDING)],
    )

    if not doc:

        closed = attendance.find_one({"emp_code":body.emp_code,"date":{"$in":days},"punch_in":{"$lte":ts},"punch_out":{"$ne":None}})

        if closed: raise HTTPException(409, "already punched out")

        raise HTTPException(404, "no open punch-in found")

    if ts <= utc(doc["punch_in"]): raise HTTPException(422, "punch-out must be after punch-in")

    if (ts-utc(doc["punch_in"])).total_seconds() > 86400: raise HTTPException(422, "punch-out cannot be more than 24 hours after punch-in")

    hours = work_hours(doc["punch_in"], ts)

    updated = attendance.find_one_and_update({"_id":doc["_id"],"punch_out":None},

        {"$set":{"punch_out":ts,"work_hours":hours,"overtime_minutes":overtime_minutes(doc["punch_in"], ts, doc["date"], emp["shift_start"], emp["shift_end"]),"half_day":half_day(hours)}},

        return_document=ReturnDocument.AFTER)

    if not updated: raise HTTPException(409, "record changed concurrently")

    return public_record(updated)



@app.get("/attendance")

def list_attendance(emp_code: Optional[str]=None, date_from: Optional[str]=None, date_to: Optional[str]=None,

                    status: Optional[str]=None, page: int=Query(1,ge=1), page_size: int=Query(20,ge=1,le=100)):

    q: dict[str,Any] = {}

    if emp_code: q["emp_code"] = emp_code

    if status:

        if status not in STATUSES: raise HTTPException(422, "invalid status")

        q["status"] = status

    if date_from: parse_day(date_from,"date_from")

    if date_to: parse_day(date_to,"date_to")

    if date_from and date_to and date_from > date_to: raise HTTPException(422, "date_from must not exceed date_to")

    if date_from or date_to:

        q["date"] = {}

        if date_from: q["date"]["$gte"] = date_from

        if date_to: q["date"]["$lte"] = date_to

    docs = list(attendance.find(q,{"_id":0}).sort([("date",DESCENDING),("emp_code",ASCENDING)]).skip((page-1)*page_size).limit(page_size))

    for d in docs:

        d["punch_in"], d["punch_out"] = to_ms(d.get("punch_in")), to_ms(d.get("punch_out"))

        d.setdefault("late_minutes",0); d.setdefault("overtime_minutes",0); d.setdefault("half_day",False); d.setdefault("history",[])

        for h in d["history"]:

            h["at"] = to_ms(h.get("at"))

            for k,v in (h.get("changes") or {}).items():

                if k in ("punch_in","punch_out"):

                    for side in ("from","to"):

                        if isinstance(v.get(side),datetime): v[side] = to_ms(v[side])

    return {"items":docs,"total":attendance.count_documents(q),"page":page,"page_size":page_size}



@app.patch("/attendance/{emp_code}/{day}")

def regularize(emp_code: str, day: str, body: RegularizeRequest):

    parse_day(day); emp = require_employee(emp_code)

    old = attendance.find_one({"emp_code":emp_code,"date":day})

    if not old: raise HTTPException(404,"attendance record not found")

    changes = body.model_dump(exclude_unset=True); reason=changes.pop("reason"); by=changes.pop("regularized_by")

    status = changes.get("status",old["status"])

    pin = from_ms(changes["punch_in"]) if "punch_in" in changes and changes["punch_in"] is not None else (None if "punch_in" in changes else old.get("punch_in"))

    pout = from_ms(changes["punch_out"]) if "punch_out" in changes and changes["punch_out"] is not None else (None if "punch_out" in changes else old.get("punch_out"))

    if status in ("ABSENT","LEAVE"):

        if changes.get("punch_in") is not None or changes.get("punch_out") is not None: raise HTTPException(422,"ABSENT/LEAVE cannot have punch times")

        pin=pout=None

    elif pin is None: raise HTTPException(422,"presence status requires punch_in")

    if pin and record_day(pin,emp["shift_start"],emp["shift_end"]) != day: raise HTTPException(422,"punch_in must belong to attendance date")

    if pout and (pin is None or pout <= utc(pin) or (pout-utc(pin)).total_seconds()>86400): raise HTTPException(422,"invalid punch_out")

    newhours = work_hours(pin,pout) if status in PRESENCE else None

    late = late_minutes(pin,day,emp["shift_start"]) if status in PRESENCE else 0

    ot = overtime_minutes(pin, pout, day, emp["shift_start"],emp["shift_end"]) if status in PRESENCE else 0

    half = half_day(newhours) if status in PRESENCE else False

    before={"status":old.get("status"),"punch_in":old.get("punch_in"),"punch_out":old.get("punch_out"),

            "work_hours":old.get("work_hours"),"late_minutes":old.get("late_minutes",0),"overtime_minutes":old.get("overtime_minutes",0),"half_day":old.get("half_day",False)}

    after={"status":status,"punch_in":pin,"punch_out":pout,"work_hours":newhours,"late_minutes":late,"overtime_minutes":ot,"half_day":half}

    audit={}

    for k,v in after.items():

        a=before.get(k)

        if isinstance(a,datetime): a=utc(a)

        b=utc(v) if isinstance(v,datetime) else v

        if a != b: audit[k]={"from":before.get(k),"to":v}

    if not audit: raise HTTPException(422,"regularization would not change the record")

    history={"at":now_utc(),"by":by,"reason":reason,"changes":audit}

    updated=attendance.find_one_and_update({"_id":old["_id"],"punch_in":old.get("punch_in"),"punch_out":old.get("punch_out"),"status":old.get("status")},

       {"$set":after,"$push":{"history":history}},return_document=ReturnDocument.AFTER)

    if not updated: raise HTTPException(409,"record changed concurrently; reload and retry")

    return public_record(updated)



# ------------------------------- Analytics -----------------------------------

@app.get("/analytics/employees/{emp_code}/monthly")

def employee_monthly(emp_code: str, month: str):

    emp=require_employee(emp_code); start,end=month_range(month)

    pipeline=[{"$match":{"emp_code":emp_code,"date":{"$gte":start.isoformat(),"$lte":end.isoformat()}}},

      {"$group":{"_id":None,

        "present_days":{"$sum":{"$cond":[{"$and":[{"$in":["$status",PRESENCE]},{"$in":[{"$dayOfWeek":{"$dateFromString":{"dateString":"$date"}}},[2,3,4,5,6]]}]},{"$cond":[{"$eq":[{"$ifNull":["$half_day",False]},True]},0.5,1.0]},0]}},

        "leave_days":{"$sum":{"$cond":[{"$eq":["$status","LEAVE"]},1,0]}},

        "late_count":{"$sum":{"$cond":[{"$gt":[{"$ifNull":["$late_minutes",0]},0]},1,0]}}}}]

    row=next(iter(attendance.aggregate(pipeline)),{})

    first=max(start,parse_day(emp["joined_on"]))

    working=sum(1 for i in range((end-first).days+1) if (first+timedelta(days=i)).weekday()<5) if first<=end else 0

    present=rounded(row.get("present_days",0))

    return {"emp_code":emp_code,"month":month,"working_days":working,"present_days":present,

            "leave_days":row.get("leave_days",0),"late_count":row.get("late_count",0),

            "attendance_pct":rounded(present/working*100,4) if working else None}


@app.get("/analytics/departments/summary")
def department_summary(department: Optional[str] = None):
    # Include employees who have joined by today, even if they have no logs.
    current = local(now_utc()).date().isoformat()

    pipeline = [
        {
            "$match": {
                "joined_on": {"$lte": current},
                **({"department": department} if department else {})
            }
        },
        {
            "$lookup": {
                "from": "attendance_logs",
                "localField": "emp_code",
                "foreignField": "emp_code",
                "as": "logs"
            }
        },
        {
            "$unwind": {
                "path": "$logs",
                "preserveNullAndEmptyArrays": True
            }
        },
        {
            "$addFields": {
                "is_presence": {
                    "$in": ["$logs.status", PRESENCE]
                },
                "is_weekday": {
                    "$cond": [
                        {"$eq": [{"$ifNull": ["$logs.date", None]}, None]},
                        False,
                        {
                            "$in": [
                                {
                                    "$dayOfWeek": {
                                        "$dateFromString": {
                                            "dateString": "$logs.date"
                                        }
                                    }
                                },
                                [2, 3, 4, 5, 6]
                            ]
                        }
                    ]
                }
            }
        },
        {
            "$group": {
                "_id": {
                    "department": "$department",
                    "emp_code": "$emp_code"
                },
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {"$and": ["$is_presence", "$is_weekday"]},
                            {
                                "$cond": [
                                    {"$eq": [{"$ifNull": ["$logs.half_day", False]}, True]},
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },
                "hours_sum": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    "$is_presence",
                                    {"$ne": [{"$ifNull": ["$logs.work_hours", None]}, None]}
                                ]
                            },
                            "$logs.work_hours",
                            0
                        ]
                    }
                },
                "hours_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    "$is_presence",
                                    {"$ne": [{"$ifNull": ["$logs.work_hours", None]}, None]}
                                ]
                            },
                            1,
                            0
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": [{"$ifNull": ["$logs.late_minutes", 0]}, 0]},
                            1,
                            0
                        ]
                    }
                },
                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$logs.late_minutes", 0]}
                },
                "leave_count": {
                    "$sum": {"$cond": [{"$eq": ["$logs.status", "LEAVE"]}, 1, 0]}
                },
                "on_duty_count": {
                    "$sum": {"$cond": [{"$eq": ["$logs.status", "ON_DUTY"]}, 1, 0]}
                }
            }
        },
        {
            "$group": {
                "_id": "$_id.department",
                "headcount": {"$sum": 1},
                "present_days": {"$sum": "$present_days"},
                "hours_sum": {"$sum": "$hours_sum"},
                "hours_count": {"$sum": "$hours_count"},
                "late_count": {"$sum": "$late_count"},
                "total_late_minutes": {"$sum": "$total_late_minutes"},
                "leave_count": {"$sum": "$leave_count"},
                "on_duty_count": {"$sum": "$on_duty_count"}
            }
        },
        {"$sort": {"_id": 1}},
        {
            "$project": {
                "_id": 0,
                "department": "$_id",
                "headcount": 1,
                "present_days": 1,
                "hours_sum": 1,
                "hours_count": 1,
                "late_count": 1,
                "total_late_minutes": 1,
                "leave_count": 1,
                "on_duty_count": 1
            }
        }
    ]

    results = []
    for row in employees.aggregate(pipeline):
        count = row["hours_count"]
        results.append({
            "department": row["department"],
            "headcount": row["headcount"],
            "present_days": rounded(row["present_days"]),
            "avg_work_hours": rounded(row["hours_sum"] / count) if count else None,
            "late_count": row["late_count"],
            "total_late_minutes": row["total_late_minutes"],
            "leave_count": row["leave_count"],
            "on_duty_count": row["on_duty_count"]
        })

    return results




@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str,
    limit: int = Query(10, ge=1, le=100),
    department: Optional[str] = None
):
    start, end = month_range(month)

    # First, select attendance records with late minutes in this month.
    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": start.isoformat(),
                    "$lte": end.isoformat()
                },
                "late_minutes": {"$gt": 0}
            }
        },

        # Calculate total late minutes for each employee.
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"}
            }
        },

        # Attach employee details and optionally filter by department.
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee"
            }
        },
        {"$unwind": "$employee"},

        *(
            [{"$match": {"employee.department": department}}]
            if department else []
        ),

        # Sort before assigning competition ranks.
        {
            "$sort": {
                "total_late_minutes": -1,
                "_id": 1
            }
        },

        # Employees with equal late minutes receive the same rank.
        {
            "$setWindowFields": {
                "sortBy": {"total_late_minutes": -1},
                "output": {
                    "rank": {"$rank": {}}
                }
            }
        },

        # Keep the requested top ranks, including ties at the cutoff.
        {"$match": {"rank": {"$lte": limit}}},

        {
            "$project": {
                "_id": 0,
                "rank": 1,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1
            }
        },

        # Stable display order when employees share a rank.
        {
            "$sort": {
                "rank": 1,
                "emp_code": 1
            }
        }
    ]

    return list(attendance.aggregate(pipeline))




@app.get("/analytics/departments/{department}/trend")

def department_trend(department: str, from_date: str=Query(...,alias="from"), to_date: str=Query(...,alias="to")):

    start,end=parse_day(from_date,"from"),parse_day(to_date,"to")

    if end<start or (end-start).days+1>92: raise HTTPException(422,"invalid date range; maximum 92 days")

    if employees.count_documents({"department":department})==0: raise HTTPException(404,"department not found")

    # MongoDB generates missing calendar dates; Python only formats returned results.

    pipeline=[

      {"$match":{"date":{"$gte":from_date,"$lte":to_date}}},

      {"$lookup":{"from":"employees","localField":"emp_code","foreignField":"emp_code","as":"emp"}},

      {"$unwind":"$emp"},{"$match":{"emp.department":department}},

      {"$group":{"_id":{"$dateFromString":{"dateString":"$date"}},

        "present_count":{"$sum":{"$cond":[{"$in":["$status",PRESENCE]},{"$cond":[{"$eq":[{"$ifNull":["$half_day",False]},True]},0.5,1]},0]}},

        "late_count":{"$sum":{"$cond":[{"$gt":[{"$ifNull":["$late_minutes",0]},0]},1,0]}}}},

      {"$project":{"_id":0,"date":"$_id","present_count":1,"late_count":1}},

      {"$densify":{"field":"date","range":{"step":1,"unit":"day","bounds":[datetime(start.year,start.month,start.day,tzinfo=UTC),datetime((end+timedelta(days=1)).year,(end+timedelta(days=1)).month,(end+timedelta(days=1)).day,tzinfo=UTC)]}}},

      {"$sort":{"date":1}},

      {"$set":{"present_count":{"$ifNull":["$present_count",0]},"late_count":{"$ifNull":["$late_count",0]},

        "is_working_day":{"$not":[{"$in":[{"$dayOfWeek":"$date"},[1,7]]}]}}},

      {"$lookup":{"from":"employees","let":{"d":{"$dateToString":{"format":"%Y-%m-%d","date":"$date"}}},"pipeline":[{"$match":{"$expr":{"$and":[{"$eq":["$department",department]},{"$lte":["$joined_on","$$d"]}]}}},{"$count":"n"}],"as":"hc"}},

      {"$set":{"headcount":{"$ifNull":[{"$arrayElemAt":["$hc.n",0]},0]}}},

      {"$set":{"attendance_rate":{"$cond":[{"$and":["$is_working_day",{"$gt":["$headcount",0]}]},{"$multiply":[{"$divide":["$present_count","$headcount"]},100]},None]}}},

      {"$setWindowFields":{"sortBy":{"date":1},"output":{"moving_avg_7d":{"$avg":"$attendance_rate","window":{"documents":[-6,0]}}}}},

      {"$project":{"_id":0,"date":1,"is_working_day":1,"headcount":1,"present_count":1,"late_count":1,"attendance_rate":1,"moving_avg_7d":1}}]

    result=[]

    for r in attendance.aggregate(pipeline):

        d=r["date"].date().isoformat() if isinstance(r["date"],datetime) else str(r["date"])[:10]

        result.append({"date":d,"is_working_day":r.get("is_working_day",parse_day(d).weekday()<5),"headcount":r.get("headcount",0),

          "present_count":rounded(r.get("present_count",0)),"late_count":r.get("late_count",0),

          "attendance_rate":rounded(r["attendance_rate"],4) if r.get("attendance_rate") is not None else None,

          "moving_avg_7d":rounded(r["moving_avg_7d"],4) if r.get("moving_avg_7d") is not None else None})

    return [r for r in result if from_date<=r["date"]<=to_date]



@app.get("/admin/explain/{endpoint}")

def explain(endpoint: Literal["attendance_list","employee_monthly","department_summary","late_leaderboard","department_trend"],

            emp_code: Optional[str]=None,date_from: Optional[str]=None,date_to: Optional[str]=None,status: Optional[str]=None,

            page: int=Query(1,ge=1),page_size: int=Query(20,ge=1,le=100),month: Optional[str]=None,department: Optional[str]=None,

            limit: int=Query(10,ge=1,le=100),from_date: Optional[str]=Query(None,alias="from"),to_date: Optional[str]=Query(None,alias="to")):

    if endpoint=="attendance_list":

        q={}

        if emp_code:q["emp_code"]=emp_code

        if status:q["status"]=status

        if date_from:parse_day(date_from,"date_from")

        if date_to:parse_day(date_to,"date_to")

        if date_from and date_to and date_from>date_to:raise HTTPException(422,"invalid date range")

        if date_from or date_to:

            q["date"]={}

            if date_from:q["date"]["$gte"]=date_from

            if date_to:q["date"]["$lte"]=date_to

        return db.command("explain",{"find":"attendance_logs","filter":q,"sort":{"date":-1,"emp_code":1},"skip":(page-1)*page_size,"limit":page_size},verbosity="executionStats")

    if endpoint=="employee_monthly":

        if not emp_code or not month:raise HTTPException(422,"emp_code and month are required")

        a,b=month_range(month); p=[{"$match":{"emp_code":emp_code,"date":{"$gte":a.isoformat(),"$lte":b.isoformat()}}},{"$group":{"_id":"$emp_code","n":{"$sum":1}}}]

        return db.command("explain",{"aggregate":"attendance_logs","pipeline":p,"cursor":{}},verbosity="executionStats")

    if endpoint=="department_summary":

        p=[{"$match":{"department":department}}] if department else [{"$match":{}}]

        return db.command("explain",{"aggregate":"employees","pipeline":p,"cursor":{}},verbosity="executionStats")

    if endpoint=="late_leaderboard":

        if not month:raise HTTPException(422,"month is required")

        a,b=month_range(month); p=[{"$match":{"date":{"$gte":a.isoformat(),"$lte":b.isoformat()},"late_minutes":{"$gt":0}}},{"$group":{"_id":"$emp_code","total":{"$sum":"$late_minutes"}}},{"$sort":{"total":-1,"_id":1}}]

        return db.command("explain",{"aggregate":"attendance_logs","pipeline":p,"cursor":{}},verbosity="executionStats")

    if not department or not from_date or not to_date:raise HTTPException(422,"department, from and to are required")

    a,b=parse_day(from_date,"from"),parse_day(to_date,"to")

    if b<a or (b-a).days+1>92:raise HTTPException(422,"invalid date range")

    p=[{"$match":{"date":{"$gte":from_date,"$lte":to_date}}}]

    return db.command("explain",{"aggregate":"attendance_logs","pipeline":p,"cursor":{}},verbosity="executionStats")
