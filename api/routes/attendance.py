"""Attendance routes — records, finalization, notifications, statistics."""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from api.dependencies import get_attendance_service, get_notification_service
from api.security import get_current_user, require_role
from core.exceptions import NotFoundError
from services.attendance_service import AttendanceService
from services.notification_service import NotificationService

router = APIRouter(prefix="/attendance", tags=["Attendance"])


class AttendanceRecordOut(BaseModel):
    id: int
    student_uid: str
    course_id: int
    date: date
    sign_in_time: Optional[str]
    sign_out_time: Optional[str]
    duration_minutes: Optional[float]
    status: str


class AttendanceStats(BaseModel):
    total_records: int
    present: int
    absent: int
    attendance_rate: float
    unique_students: int
    unique_dates: int


class FinalizeResponse(BaseModel):
    open_marked_absent: int
    newly_absent: int
    total_affected: int


class NotifyResponse(BaseModel):
    notified: int
    sent: int
    logged: int
    failed: int


@router.get(
    "/",
    response_model=List[AttendanceRecordOut],
    summary="List attendance records",
    dependencies=[Depends(require_role("admin", "teacher", "student"))],
)
def list_attendance(
    course_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user),
    svc: AttendanceService = Depends(get_attendance_service),
) -> List[AttendanceRecordOut]:
    teacher_id = None
    if current_user["role"] == "teacher":
        teacher_id = current_user["account_id"]

    records = svc.get_attendance(course_id=course_id, teacher_account_id=teacher_id)
    return [
        AttendanceRecordOut(
            id=r.id,
            student_uid=r.student_uid,
            course_id=r.course_id,
            date=r.date,
            sign_in_time=r.sign_in_time.isoformat() if r.sign_in_time else None,
            sign_out_time=r.sign_out_time.isoformat() if r.sign_out_time else None,
            duration_minutes=r.duration_minutes,
            status=r.status,
        )
        for r in records
    ]


@router.get(
    "/stats/{course_id}",
    response_model=AttendanceStats,
    summary="Get attendance statistics for a course",
    dependencies=[Depends(require_role("admin", "teacher"))],
)
def attendance_stats(
    course_id: int,
    current_user: dict = Depends(get_current_user),
    svc: AttendanceService = Depends(get_attendance_service),
) -> AttendanceStats:
    teacher_id = current_user["account_id"] if current_user["role"] == "teacher" else None
    stats = svc.get_attendance_statistics(course_id, teacher_id)
    return AttendanceStats(**stats)


@router.post(
    "/sign-in/{course_id}/{student_uid}",
    response_model=AttendanceRecordOut,
    summary="Manual sign-in",
    dependencies=[Depends(require_role("admin", "teacher"))],
)
def manual_sign_in(
    course_id: int,
    student_uid: str,
    svc: AttendanceService = Depends(get_attendance_service),
) -> AttendanceRecordOut:
    try:
        record = svc.sign_in(student_uid, course_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return AttendanceRecordOut(
        id=record.id, student_uid=record.student_uid, course_id=record.course_id,
        date=record.date,
        sign_in_time=record.sign_in_time.isoformat() if record.sign_in_time else None,
        sign_out_time=record.sign_out_time.isoformat() if record.sign_out_time else None,
        duration_minutes=record.duration_minutes, status=record.status,
    )


@router.post(
    "/sign-out/{course_id}/{student_uid}",
    response_model=Optional[AttendanceRecordOut],
    summary="Manual sign-out",
    dependencies=[Depends(require_role("admin", "teacher"))],
)
def manual_sign_out(
    course_id: int,
    student_uid: str,
    svc: AttendanceService = Depends(get_attendance_service),
) -> Optional[AttendanceRecordOut]:
    try:
        record = svc.sign_out(student_uid, course_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if not record:
        return None
    return AttendanceRecordOut(
        id=record.id, student_uid=record.student_uid, course_id=record.course_id,
        date=record.date,
        sign_in_time=record.sign_in_time.isoformat() if record.sign_in_time else None,
        sign_out_time=record.sign_out_time.isoformat() if record.sign_out_time else None,
        duration_minutes=record.duration_minutes, status=record.status,
    )


@router.post(
    "/finalize/{course_id}",
    response_model=FinalizeResponse,
    summary="Finalize a course session (anti-proxy policy)",
    dependencies=[Depends(require_role("admin", "teacher"))],
)
def finalize_session(
    course_id: int,
    on_date: Optional[date] = Query(None, description="Date to finalize; defaults to today"),
    svc: AttendanceService = Depends(get_attendance_service),
) -> FinalizeResponse:
    try:
        result = svc.finalize_session(course_id, on_date)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return FinalizeResponse(**result)


@router.post(
    "/notify-absent/{course_id}",
    response_model=NotifyResponse,
    summary="Send absence notifications for a course",
    dependencies=[Depends(require_role("admin", "teacher"))],
)
def notify_absent(
    course_id: int,
    on_date: Optional[date] = Query(None, description="Date to check; defaults to today"),
    notif_svc: NotificationService = Depends(get_notification_service),
) -> NotifyResponse:
    result = notif_svc.notify_absent_students(course_id, on_date)
    return NotifyResponse(**result)


@router.get(
    "/overview/{course_id}",
    summary="Per-student attendance overview for a course",
    dependencies=[Depends(require_role("admin", "teacher"))],
)
def course_overview(
    course_id: int,
    on_date: Optional[date] = Query(None),
    current_user: dict = Depends(get_current_user),
    svc: AttendanceService = Depends(get_attendance_service),
) -> list:
    teacher_id = current_user["account_id"] if current_user["role"] == "teacher" else None
    return svc.get_course_overview(course_id, on_date, teacher_id)
