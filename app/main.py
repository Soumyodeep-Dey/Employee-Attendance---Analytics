"""
Employee Attendance & Analytics API

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

All application code is kept here as required by the assignment. Business rules
and API shapes follow openapi.yaml; MongoDB shapes follow DATA_MODEL.md.
"""
import os
import calendar
import json
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from bson.decimal128 import Decimal128
from bson import json_util

load_dotenv(override=False)

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"), tz_aware=True,
                     serverSelectionTimeoutMS=3000)
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc

@asynccontextmanager
async def lifespan(app):
    # Unique indexes enforce correctness even when requests arrive simultaneously.
    db.employees.create_index("emp_code", unique=True)
    db.employees.create_index([("department", 1), ("emp_code", 1)])
    db.employees.create_index([("joined_on", 1), ("department", 1)])
    db.employees.create_index([("department", 1), ("joined_on", 1)])
    db.attendance_logs.create_index([("emp_code", 1), ("date", -1)], unique=True)
    db.attendance_logs.create_index([("date", -1), ("emp_code", 1)])
    db.attendance_logs.create_index([("status", 1), ("date", -1), ("emp_code", 1)])
    db.attendance_logs.create_index([("emp_code", 1), ("punch_in", -1)])
    try:
        yield
    finally:
        client.close()

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0", lifespan=lifespan)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def attendance_date(punch_in: datetime, shift_start: str, shift_end: str) -> str:
    local = punch_in.astimezone(IST)
    day = local.date()
    if shift_end <= shift_start and local.time() < time.fromisoformat(shift_end):
        day -= timedelta(days=1)
    return day.isoformat()


def shift_bounds(day: str, shift_start: str, shift_end: str):
    start = datetime.combine(date.fromisoformat(day), time.fromisoformat(shift_start), IST)
    end = datetime.combine(date.fromisoformat(day), time.fromisoformat(shift_end), IST)
    if shift_end <= shift_start:
        end += timedelta(days=1)
    return start, end


def compute_late_minutes(punch_in: datetime, shift_start: datetime) -> int:
    seconds = int((punch_in - shift_start).total_seconds())
    return seconds // 60 if seconds > 600 else 0


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    seconds = int((punch_out - punch_in).total_seconds())
    return float((Decimal(seconds) / Decimal(3600)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_overtime(punch_out: datetime, shift_end: datetime) -> int:
    minutes = int((punch_out - shift_end).total_seconds()) // 60
    return minutes if minutes >= 30 else 0


def serialize(value):
    """Convert BSON dates even inside history; never expose internal IDs."""
    if isinstance(value, datetime):
        return int(value.timestamp()) * 1000 + value.microsecond // 1000
    if isinstance(value, dict):
        return {key: serialize(item) for key, item in value.items() if key != "_id"}
    if isinstance(value, list):
        return [serialize(item) for item in value]
    return value


def attendance_response(doc):
    return serialize({"punch_in": None, "punch_out": None, "work_hours": None,
                      "late_minutes": 0, "overtime_minutes": 0, "half_day": False,
                      "history": [], **doc})


def validate_date(value: str) -> str:
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("Date must be YYYY-MM-DD")
    return value


EpochMillis = Annotated[int, Field(strict=True, ge=100000000000, le=4102444800000)]
Status = Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
ShiftTime = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    department: str = Field(min_length=1, max_length=50)
    shift_start: ShiftTime = "09:30"
    shift_end: ShiftTime = "18:30"
    joined_on: str

    @field_validator("joined_on")
    @classmethod
    def valid_joined_on(cls, value):
        return validate_date(value)

    @model_validator(mode="after")
    def different_shifts(self):
        if self.shift_start == self.shift_end:
            raise ValueError("Shift start and end must differ")
        return self


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: EpochMillis = Field(default_factory=lambda: int(datetime.now(UTC).timestamp()) * 1000)
    status: Literal["PRESENT", "WFH", "ON_DUTY"] = "PRESENT"


class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: EpochMillis = Field(default_factory=lambda: int(datetime.now(UTC).timestamp()) * 1000)


class RegularizeIn(BaseModel):
    # Defaults allow omission; explicitly supplied null is still invalid.
    status: Status = None
    punch_in: EpochMillis = None
    punch_out: EpochMillis = None
    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)


PRESENCE = {"PRESENT", "WFH", "ON_DUTY"}
MUTABLE_FIELDS = ("status", "punch_in", "punch_out", "work_hours", "late_minutes",
                  "overtime_minutes", "half_day")
FIELD_DEFAULTS = {"punch_in": None, "punch_out": None, "work_hours": None,
                  "late_minutes": 0, "overtime_minutes": 0, "half_day": False}


def invalid(message: str, field: str = "body"):
    raise HTTPException(422, [{"loc": [field], "msg": message, "type": "value_error"}])


def from_millis(value: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=value // 1000)


def require_employee(emp_code: str):
    employee = db.employees.find_one({"emp_code": emp_code})
    if employee is None:
        raise HTTPException(404, "Unknown employee")
    return employee


def validate_duration(punch_in: datetime, punch_out: datetime):
    duration = (punch_out - punch_in).total_seconds()
    if duration <= 0 or duration > 86400:
        invalid("Punch-out must be after punch-in and within 24 hours")


def derive_fields(record, employee):
    if record["status"] not in PRESENCE:
        return dict(FIELD_DEFAULTS)
    punch_in = record.get("punch_in")
    if punch_in is None:
        invalid("Presence status requires punch-in")
    if attendance_date(punch_in, employee["shift_start"], employee["shift_end"]) != record["date"]:
        invalid("Punch-in must remain on the attendance date")
    start, end = shift_bounds(record["date"], employee["shift_start"], employee["shift_end"])
    values = {"late_minutes": compute_late_minutes(punch_in, start),
              "work_hours": None, "overtime_minutes": 0, "half_day": False}
    punch_out = record.get("punch_out")
    if punch_out is not None:
        validate_duration(punch_in, punch_out)
        values["work_hours"] = compute_work_hours(punch_in, punch_out)
        values["overtime_minutes"] = compute_overtime(punch_out, end)
        values["half_day"] = values["work_hours"] < 4.50
    return values


def snapshot_filter(record):
    """Compare the read snapshot, including history, before one atomic write.

    Missing legacy fields are matched as missing, not as their display defaults.
    This detects concurrent corrections and punch-outs without schema additions.
    """
    query = {"_id": record["_id"]}
    for field in (*MUTABLE_FIELDS, "history"):
        query[field] = record[field] if field in record else {"$exists": False}
    return query


@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    employee = require_employee(body.emp_code)
    ts = from_millis(body.punched_at)
    # Include closed records: selecting only open records could close an older day.
    record = db.attendance_logs.find_one(
        {"emp_code": body.emp_code, "punch_in": {"$type": "date", "$lte": ts}},
        sort=[("punch_in", -1)],
    )
    if record is None:
        raise HTTPException(404, "No punch-in found")
    if record.get("punch_out") is not None:
        raise HTTPException(409, "Record already punched out")
    validate_duration(record["punch_in"], ts)
    _, end = shift_bounds(record["date"], employee["shift_start"], employee["shift_end"])
    hours = compute_work_hours(record["punch_in"], ts)
    updated = db.attendance_logs.find_one_and_update(
        snapshot_filter(record),
        {"$set": {"punch_out": ts, "work_hours": hours,
                  "overtime_minutes": compute_overtime(ts, end), "half_day": hours < 4.50}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(409, "Record changed concurrently; retry")
    return attendance_response(updated)


@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(emp_code: str, date: str, body: RegularizeIn):
    try:
        validate_date(date)
    except ValueError:
        invalid("Date must be YYYY-MM-DD", "path")
    employee = require_employee(emp_code)
    record = db.attendance_logs.find_one({"emp_code": emp_code, "date": date})
    if record is None:
        raise HTTPException(404, "No attendance record for this date")
    final = {**FIELD_DEFAULTS, **record}
    supplied = body.model_fields_set
    if "status" in supplied:
        final["status"] = body.status
    if final["status"] not in PRESENCE:
        if supplied & {"punch_in", "punch_out"}:
            invalid("ABSENT/LEAVE cannot have punch times")
        final["punch_in"] = final["punch_out"] = None
    else:
        for field in ("punch_in", "punch_out"):
            if field in supplied:
                final[field] = from_millis(getattr(body, field))
    final.update(derive_fields(final, employee))
    changes = {}
    for field in MUTABLE_FIELDS:
        previous = record.get(field, FIELD_DEFAULTS.get(field))
        if previous != final[field]:
            changes[field] = {"from": previous, "to": final[field]}
    if not changes:
        invalid("Correction must change at least one field")
    history = {"at": datetime.now(UTC).replace(microsecond=0), "by": body.regularized_by,
               "reason": body.reason, "changes": changes}
    updated = db.attendance_logs.find_one_and_update(
        snapshot_filter(record),
        {"$set": {field: final[field] for field in MUTABLE_FIELDS}, "$push": {"history": history}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(409, "Record changed concurrently; retry")
    return attendance_response(updated)


# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        db.command("ping")
    except PyMongoError:
        raise HTTPException(503, "MongoDB is unavailable") from None
    return {"status": "ok"}


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    doc["created_at"] = datetime.now(UTC).replace(microsecond=0)
    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "emp_code already exists") from None
    return serialize(doc)


@app.get("/employees")
def list_employees(department: Optional[str] = None, page: Page = 1, page_size: PageSize = 20):
    q = {}
    if department is not None:
        q["department"] = department
    skip = (page - 1) * page_size
    total = db.employees.count_documents(q)
    items = [serialize(d) for d in db.employees.find(q, {"_id": 0}).sort("emp_code", 1).skip(skip).limit(page_size)]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if emp is None:
        raise HTTPException(404, "Unknown employee")
    ts = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=body.punched_at // 1000)
    d = attendance_date(ts, emp["shift_start"], emp["shift_end"])
    start, _ = shift_bounds(d, emp["shift_start"], emp["shift_end"])
    doc = {
        "emp_code": body.emp_code,
        "date": d,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts, start),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }
    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "already punched in for this date") from None
    return attendance_response(doc)


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[Status] = None,
    page: Page = 1,
    page_size: PageSize = 20,
):
    command = attendance_command(emp_code, date_from, date_to, status, page, page_size)
    q = command["filter"]
    total = db.attendance_logs.count_documents(q, hint=command["hint"])
    docs = db.attendance_logs.find(q).sort(list(command["sort"].items())).skip(command["skip"]).limit(command["limit"]).hint(command["hint"])
    return {"items": [attendance_response(d) for d in docs], "total": total, "page": page, "page_size": page_size}


def attendance_command(emp_code=None, date_from=None, date_to=None, status=None, page=1, page_size=20):
    try:
        for value in (date_from, date_to):
            if value is not None:
                validate_date(value)
        if date_from and date_to and date_from > date_to:
            raise ValueError("date_from must not exceed date_to")
    except ValueError as exc:
        raise HTTPException(422, [{"loc": ["query", "date_from", "date_to"], "msg": str(exc), "type": "value_error"}]) from None
    q = {}
    if emp_code is not None:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if status:
        q["status"] = status
    hint = "emp_code_1_date_-1" if emp_code is not None else (
        "status_1_date_-1_emp_code_1" if status is not None else "date_-1_emp_code_1")
    return {"find": "attendance_logs", "filter": q, "sort": {"date": -1, "emp_code": 1},
            "skip": (page - 1) * page_size, "limit": page_size, "hint": hint}


# --------------------------------------------------------------------------- #
# Analytics query builders and execution
# --------------------------------------------------------------------------- #

Month = Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


def month_bounds(month):
    try:
        first = date.fromisoformat(month + "-01")
        last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    except ValueError:
        invalid("Invalid month", "query")
    return first.isoformat(), last.isoformat()


def mongo_half_up(expression, places=2):
    # Metrics are nonnegative. Decimal arithmetic avoids binary rounding and
    # MongoDB $round's ties-to-even behavior; retain null for undefined metrics.
    scale = 10 ** places
    return {"$cond": [{"$eq": [expression, None]}, None,
        {"$toDouble": {"$divide": [{"$floor": {"$add": [
            {"$multiply": [{"$toDecimal": expression}, scale]}, Decimal128("0.5")]}}, scale]}}]}


def is_weekday(expression):
    return {"$in": [{"$isoDayOfWeek": {"$toDate": expression}}, [1, 2, 3, 4, 5]]}


def presence_weight():
    return {"$cond": [{"$in": ["$status", sorted(PRESENCE)]},
                      {"$cond": [{"$ifNull": ["$half_day", False]}, 0.5, 1]}, 0]}


def log_totals_group():
    late = {"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}
    has_hours = {"$and": [{"$in": ["$status", sorted(PRESENCE)]},
                           {"$ne": [{"$ifNull": ["$work_hours", None]}, None]}]}
    return {"$group": {"_id": None,
        "present_days": {"$sum": {"$cond": [is_weekday("$date"), presence_weight(), 0]}},
        "leave_days": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
        "on_duty_count": {"$sum": {"$cond": [{"$eq": ["$status", "ON_DUTY"]}, 1, 0]}},
        "late_count": {"$sum": {"$cond": [late, 1, 0]}},
        "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
        "total_overtime_minutes": {"$sum": {"$ifNull": ["$overtime_minutes", 0]}},
        "hours_sum": {"$sum": {"$cond": [has_hours, {"$toDecimal": "$work_hours"}, 0]}},
        "hours_count": {"$sum": {"$cond": [has_hours, 1, 0]}}}}


def monthly_logs_lookup(first, last):
    return {"$lookup": {"from": "attendance_logs", "localField": "emp_code",
        "foreignField": "emp_code", "pipeline": [
            {"$match": {"date": {"$gte": first, "$lte": last}}}, log_totals_group()], "as": "stats"}}


def stats_value(field):
    return {"$ifNull": [{"$arrayElemAt": ["$stats." + field, 0]}, 0]}


def employee_monthly_pipeline(emp_code, month):
    first, last = month_bounds(month)
    days = calendar.monthrange(int(month[:4]), int(month[5:]))[1]
    return [{"$match": {"emp_code": emp_code}}, monthly_logs_lookup(first, last),
        {"$set": {"working_days": {"$size": {"$filter": {
            "input": {"$map": {"input": {"$range": [0, days]}, "as": "offset",
                "in": {"$dateAdd": {"startDate": {"$toDate": first}, "unit": "day", "amount": "$$offset"}}}},
            "as": "day", "cond": {"$and": [is_weekday("$$day"),
                {"$gte": ["$$day", {"$toDate": "$joined_on"}]}]}}}},
            **{field: stats_value(field) for field in ("present_days", "leave_days", "late_count",
                "total_late_minutes", "total_overtime_minutes")}}},
        {"$project": {"_id": 0, "emp_code": 1, "month": {"$literal": month},
            "working_days": 1, "present_days": 1, "leave_days": 1, "late_count": 1,
            "total_late_minutes": 1, "total_overtime_minutes": 1,
            "attendance_pct": mongo_half_up({"$cond": [{"$gt": ["$working_days", 0]},
                {"$divide": [{"$multiply": [{"$toDecimal": "$present_days"}, 100]}, "$working_days"]}, None]})}}]


def department_summary_pipeline(month, department=None):
    first, last = month_bounds(month)
    match = {"joined_on": {"$lte": last}}
    if department is not None:
        match["department"] = department
    metrics = ("present_days", "late_count", "total_late_minutes", "on_duty_count", "hours_sum", "hours_count")
    return [{"$match": match}, monthly_logs_lookup(first, last),
        {"$group": {"_id": "$department", "headcount": {"$sum": 1},
            **{field: {"$sum": stats_value(field)} for field in metrics},
            "leave_count": {"$sum": stats_value("leave_days")}}},
        {"$project": {"_id": 0, "department": "$_id", "headcount": 1,
            **{field: 1 for field in metrics if not field.startswith("hours_")}, "leave_count": 1,
            "avg_work_hours": mongo_half_up({"$cond": [{"$gt": ["$hours_count", 0]},
                {"$divide": ["$hours_sum", "$hours_count"]}, None]})}}, {"$sort": {"department": 1}}]


def late_leaderboard_pipeline(month, limit, department=None):
    first, last = month_bounds(month)
    pipeline = [{"$match": {"date": {"$gte": first, "$lte": last}}},
        {"$group": {"_id": "$emp_code", "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}},
            "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}}}},
        {"$match": {"total_late_minutes": {"$gt": 0}}},
        {"$lookup": {"from": "employees", "localField": "_id", "foreignField": "emp_code", "as": "employee"}},
        {"$unwind": "$employee"}]
    if department is not None:
        pipeline.append({"$match": {"employee.department": department}})
    pipeline.extend([
        {"$setWindowFields": {"sortBy": {"total_late_minutes": -1}, "output": {"rank": {"$rank": {}}}}},
        {"$match": {"rank": {"$lte": limit}}},
        {"$project": {"_id": 0, "emp_code": "$_id", "name": "$employee.name",
            "department": "$employee.department", "total_late_minutes": 1, "late_count": 1, "rank": 1}},
        {"$sort": {"total_late_minutes": -1, "emp_code": 1}}])
    return pipeline


def trend_bounds(first, last):
    try:
        validate_date(first)
        validate_date(last)
        days = (date.fromisoformat(last) - date.fromisoformat(first)).days + 1
        if not 1 <= days <= 92:
            raise ValueError("Range must contain 1 to 92 days")
    except ValueError as exc:
        invalid(str(exc), "query")
    return days


def department_trend_pipeline(department, first, last):
    days = trend_bounds(first, last)
    # Generate the complete calendar inside MongoDB. Starting from an employee
    # also produces rows when there are zero logs, unlike densifying empty logs.
    return [{"$match": {"department": department}}, {"$limit": 1},
        {"$project": {"_id": 0, "day": {"$map": {"input": {"$range": [0, days]}, "as": "offset",
            "in": {"$dateAdd": {"startDate": {"$toDate": first}, "unit": "day", "amount": "$$offset"}}}}}},
        {"$unwind": "$day"},
        {"$set": {"date": {"$dateToString": {"date": "$day", "format": "%Y-%m-%d"}},
                  "is_working_day": is_weekday("$day")}},
        {"$lookup": {"from": "employees", "let": {"date": "$date"}, "pipeline": [
            {"$match": {"department": department, "$expr": {"$lte": ["$joined_on", "$$date"]}}},
            {"$count": "count"}], "as": "people"}},
        {"$lookup": {"from": "attendance_logs", "localField": "date", "foreignField": "date",
            "pipeline": [
                {"$lookup": {"from": "employees", "localField": "emp_code", "foreignField": "emp_code",
                    "pipeline": [{"$match": {"department": department}}], "as": "employee"}},
                {"$match": {"employee.0": {"$exists": True}}},
                {"$group": {"_id": None, "present_count": {"$sum": presence_weight()},
                    "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}}}}
            ], "as": "logs"}},
        {"$set": {"headcount": {"$ifNull": [{"$arrayElemAt": ["$people.count", 0]}, 0]},
            "present_count": {"$ifNull": [{"$arrayElemAt": ["$logs.present_count", 0]}, 0]},
            "late_count": {"$ifNull": [{"$arrayElemAt": ["$logs.late_count", 0]}, 0]}}},
        {"$set": {"attendance_rate": mongo_half_up({"$cond": [
            {"$and": ["$is_working_day", {"$gt": ["$headcount", 0]}]},
            {"$divide": [{"$toDecimal": "$present_count"}, "$headcount"]}, None]}, 4)}},
        {"$setWindowFields": {"sortBy": {"day": 1}, "output": {
            "moving_avg_7d": {"$avg": {"$toDecimal": "$attendance_rate"}, "window": {"documents": [-6, 0]}}}}},
        {"$project": {"date": 1, "is_working_day": 1, "headcount": 1, "present_count": 1,
            "late_count": 1, "attendance_rate": 1, "moving_avg_7d": mongo_half_up("$moving_avg_7d", 4)}},
        {"$sort": {"date": 1}}]


@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: Month):
    command = analytics_command("employee_monthly", month=month, emp_code=emp_code)
    require_employee(emp_code)
    return next(execute_analytics(command))


@app.get("/analytics/departments/summary")
def department_summary(month: Month, department: str | None = None):
    return {"month": month, "items": list(execute_analytics(analytics_command("department_summary", month=month, department=department)))}


@app.get("/analytics/leaderboard/late")
def late_leaderboard(month: Month, limit: Annotated[int, Query(ge=1, le=50)] = 10,
                     department: str | None = None):
    return {"month": month, "items": list(execute_analytics(analytics_command("late_leaderboard", month=month, limit=limit, department=department)))}


@app.get("/analytics/departments/{department}/trend")
def department_trend(department: str, from_: Annotated[str, Query(alias="from")],
                     to: Annotated[str, Query()]):
    command = analytics_command("department_trend", department=department, first=from_, last=to)
    if db.employees.find_one({"department": department}) is None:
        raise HTTPException(404, "Unknown department")
    return {"department": department, "items": list(execute_analytics(command))}


def analytics_command(endpoint, month=None, emp_code=None, department=None, limit=10, first=None, last=None):
    if endpoint == "employee_monthly":
        if month is None or emp_code is None:
            invalid("emp_code and month are required", "query")
        collection, pipeline, hint = "employees", employee_monthly_pipeline(emp_code, month), "emp_code_1"
    elif endpoint == "department_summary":
        if month is None:
            invalid("month is required", "query")
        collection, pipeline = "employees", department_summary_pipeline(month, department)
        hint = "department_1_joined_on_1" if department is not None else "joined_on_1_department_1"
    elif endpoint == "late_leaderboard":
        if month is None:
            invalid("month is required", "query")
        collection, pipeline, hint = "attendance_logs", late_leaderboard_pipeline(month, limit, department), "date_-1_emp_code_1"
    else:
        if department is None or first is None or last is None:
            invalid("department, from and to are required", "query")
        collection, pipeline, hint = "employees", department_trend_pipeline(department, first, last), "department_1_joined_on_1"
    return {"aggregate": collection, "pipeline": pipeline, "cursor": {}, "hint": hint}


def execute_analytics(command):
    return db[command["aggregate"]].aggregate(command["pipeline"], hint=command["hint"])


ExplainEndpoint = Literal["attendance_list", "employee_monthly", "department_summary", "late_leaderboard", "department_trend"]


@app.get("/admin/explain/{endpoint}")
def explain_endpoint(endpoint: ExplainEndpoint, emp_code: str | None = None,
                     month: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
                     department: str | None = None,
                     limit: Annotated[int, Query(ge=1, le=50)] = 10,
                     date_from: str | None = None, date_to: str | None = None,
                     status: Status | None = None,
                     from_: Annotated[str | None, Query(alias="from")] = None, to: str | None = None,
                     page: Page = 1, page_size: PageSize = 20):
    if endpoint == "attendance_list":
        command = attendance_command(emp_code, date_from, date_to, status, page, page_size)
        collection = command["find"]
    else:
        command = analytics_command(endpoint, month, emp_code, department, limit, from_, to)
        collection = command["aggregate"]
    explanation = db.command("explain", command, verbosity="executionStats")
    # Raw plans contain BSON values such as ObjectIds and Decimal128 constants.
    # Extended JSON preserves them without inventing or removing plan fields.
    return {"endpoint": endpoint, "collection": collection,
            "explain": json.loads(json_util.dumps(explanation))}
