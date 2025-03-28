from fastapi import APIRouter, Depends, Request, Query, status, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from .schemas import AppointmentCreate, AppointmentUpdate, AppointmentResponse, AppointmentReminder
from db.db import get_db

from .models import *
from auth.models import *
from patient.models import *
from catalog.models import *
from payment.models import *

from utils.auth import verify_token
from utils.appointment_msg import send_appointment_email
from sqlalchemy.orm import joinedload
from datetime import datetime, timedelta, time
from sqlalchemy import or_, and_, func, select
from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler
import asyncio


scheduler = BackgroundScheduler()
scheduler.start()

def send_email_sync(db, appointment_id):
    """Helper function to run async function inside sync context"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(send_appointment_email(db, appointment_id))
    loop.close()

appointment_router = APIRouter()

@appointment_router.post("/create",
    response_model=dict,
    status_code=201,
    summary="Create new appointment",
    description="""
    Create a new appointment for a patient.

    **Required fields:**
    - patient_id (UUID): Patient's unique identifier
    - appointment_date (datetime): Scheduled date and time
    
    **Optional fields:**
    - doctor_id (str): Doctor's unique identifier (defaults to authenticated doctor)
    - clinic_id (str): Clinic's unique identifier (defaults to doctor's default clinic)
    - notes (str): Appointment notes/description
    - checked_in_at (datetime): Patient check-in time
    - checked_out_at (datetime): Patient check-out time
    - status (str): One of [SCHEDULED, CANCELLED, COMPLETED] (default: SCHEDULED)
    - share_on_email (bool): Enable email notifications (default: False)
    - share_on_sms (bool): Enable SMS notifications (default: False)
    - share_on_whatsapp (bool): Enable WhatsApp notifications (default: False)

    **Authentication:**
    - Requires valid doctor Bearer token

    **Response:**
    ```json
    {
        "message": "Appointment created successfully"
    }
    ```
    """,
    responses={
        201: {
            "description": "Successfully created new appointment",
            "content": {
                "application/json": {
                    "example": {"message": "Appointment created successfully"}
                }
            }
        },
        400: {
            "description": "Invalid input",
            "content": {
                "application/json": {
                    "example": {"message": "Invalid status. Must be either 'SCHEDULED', 'CANCELLED' or 'COMPLETED'"}
                }
            }
        },
        401: {
            "description": "Authentication failed or non-doctor user",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "Referenced entity not found",
            "content": {
                "application/json": {
                    "example": {"message": "Patient/Doctor/Clinic not found"}
                }
            }
        },
        500: {
            "description": "Server error occurred",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error message"}
                }
            }
        }
    }
)
async def create_appointment(request: Request, appointment: AppointmentCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        # Verify doctor authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})

        user_id = decoded_token.get("user_id")
        user = db.query(User).filter(User.id == user_id).first()

        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=401, content={"message": "Unauthorized - doctor access required"})
        
        # Validate patient
        if not appointment.patient_id:
            return JSONResponse(status_code=400, content={"message": "Patient ID is required"})
            
        patient = db.query(Patient).filter(Patient.id == appointment.patient_id).first()
        if not patient:
            return JSONResponse(status_code=404, content={"message": "Patient not found"})

        # Validate/set doctor
        doctor = user
        if appointment.doctor_id:
            doctor = db.query(User).filter(User.id == appointment.doctor_id).first()
            if not doctor or str(doctor.user_type) != "doctor":
                return JSONResponse(status_code=404, content={"message": "Doctor not found"})

        # Validate/set clinic
        clinic_id = appointment.clinic_id or user.default_clinic_id
        if not clinic_id:
            return JSONResponse(status_code=400, content={"message": "Clinic ID is required"})
            
        clinic = db.query(Clinic).filter(Clinic.id == clinic_id).first()
        if not clinic:
            return JSONResponse(status_code=404, content={"message": "Clinic not found"})

        # Validate status
        status = appointment.status.upper()
        if status not in ["SCHEDULED", "CANCELLED", "COMPLETED"]:
            return JSONResponse(status_code=400, content={"message": "Invalid status. Must be either 'SCHEDULED', 'CANCELLED' or 'COMPLETED'"})

        new_appointment = Appointment(
            patient_id=patient.id,
            clinic_id=clinic.id,
            patient_number=patient.patient_number if hasattr(patient, 'patient_number') else None,
            patient_name=patient.name,
            doctor_id=doctor.id,
            doctor_name=doctor.name,
            notes=appointment.notes,
            appointment_date=appointment.appointment_date,
            checked_in_at=appointment.checked_in_at,
            checked_out_at=appointment.checked_out_at,
            status=AppointmentStatus(status),
            share_on_email=appointment.share_on_email,
            share_on_sms=appointment.share_on_sms,
            share_on_whatsapp=appointment.share_on_whatsapp,
        )

        db.add(new_appointment)
        db.commit()
        db.refresh(new_appointment)

        if new_appointment.share_on_email:
            background_tasks.add_task(send_appointment_email, db, new_appointment.id)

        return JSONResponse(status_code=201, content={"message": "Appointment created successfully"})
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@appointment_router.get("/all",
    response_model=dict,
    status_code=200,
    summary="List all appointments with statistics",
    description="""
    Retrieve all appointments for the authenticated doctor with pagination and statistics.
    
    **Query Parameters:**
    - page (int): Page number for pagination (default: 1)
    - per_page (int): Number of items per page (default: 10, max: 100)
    - sort_by (str): Field to sort by (default: appointment_date)
    - sort_order (str): Sort direction - asc or desc (default: desc)
    
    **Statistics Returned:**
    - Today: Number of appointments today
    - This Month: Number of appointments in current month  
    - This Year: Number of appointments in current year
    - Overall: Total number of appointments
    
    **Authentication:**
    - Requires valid doctor Bearer token
    
    **Response:**
    ```json
    {
        "appointments": [
            {
                "id": "uuid",
                "patient_id": "uuid",
                "clinic_id": "uuid",
                "patient_number": "P001", 
                "patient_name": "John Doe",
                "doctor_id": "uuid",
                "doctor_name": "Dr. Smith",
                "notes": "Regular checkup",
                "appointment_date": "2023-01-01T10:00:00",
                "checked_in_at": "2023-01-01T10:00:00",
                "checked_out_at": "2023-01-01T10:30:00",
                "status": "COMPLETED",
                "created_at": "2023-01-01T09:00:00",
                "updated_at": "2023-01-01T10:30:00",
                "doctor": {
                    "id": "uuid",
                    "name": "Dr. Smith",
                    "email": "dr.smith@example.com",
                    "phone": "1234567890"
                },
                "patient": {
                    "id": "uuid", 
                    "name": "John Doe",
                    "email": "john@example.com",
                    "mobile_number": "9876543210",
                    "date_of_birth": "1990-01-01",
                    "gender": "MALE"
                }
            }
        ],
        "pagination": {
            "total": 100,
            "page": 1,
            "per_page": 10,
            "pages": 10
        },
        "stats": {
            "today": 5,
            "this_month": 45,
            "this_year": 450,
            "overall": 1000
        }
    }
    ```
    """,
    responses={
        200: {
            "description": "Successfully retrieved appointments list with statistics",
            "content": {
                "application/json": {
                    "example": {
                        "appointments": [],
                        "pagination": {
                            "total": 0,
                            "page": 1,
                            "per_page": 10,
                            "pages": 0
                        },
                        "stats": {
                            "today": 0,
                            "this_month": 0,
                            "this_year": 0,
                            "overall": 0
                        }
                    }
                }
            }
        },
        401: {
            "description": "Authentication failed or non-doctor user",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        500: {
            "description": "Server error occurred",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error message"}
                }
            }
        }
    }
)
async def get_all_appointments(
    request: Request,
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Items per page"),
    sort_by: str = Query(default="appointment_date", description="Field to sort by"),
    sort_order: str = Query(default="desc", description="Sort direction (asc/desc)")
):
    try:
        decoded_token = verify_token(request)
        user_id = decoded_token.get("user_id") if decoded_token else None
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})

        # Base query
        query = (
            db.query(Appointment, Patient, User)
            .join(Patient, Appointment.patient_id == Patient.id)
            .join(User, Appointment.doctor_id == User.id)
            .filter(Appointment.doctor_id == user.id)
        )

        # Add sorting
        sort_column = getattr(Appointment, sort_by)
        if sort_order == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())

        # Get total count
        total = db.execute(select(func.count()).select_from(query.subquery())).scalar()

        # Add pagination
        query = query.offset((page - 1) * per_page).limit(per_page)
        
        # Execute query
        appointments = query.all()

        # Get statistics
        today = datetime.now().date()
        today_start = datetime.combine(today, time.min)
        today_end = datetime.combine(today, time.max)

        today_count = db.execute(
            select(func.count(Appointment.id))
            .where(Appointment.doctor_id == user.id)
            .where(Appointment.created_at.between(today_start, today_end))
        ).scalar() or 0

        month_count = db.execute(
            select(func.count(Appointment.id))
            .where(Appointment.doctor_id == user.id)
            .where(Appointment.created_at >= today.replace(day=1))
        ).scalar() or 0

        year_count = db.execute(
            select(func.count(Appointment.id))
            .where(Appointment.doctor_id == user.id)
            .where(Appointment.created_at >= today.replace(month=1, day=1))
        ).scalar() or 0

        total_count = db.execute(
            select(func.count(Appointment.id))
            .where(Appointment.doctor_id == user.id)
        ).scalar() or 0

        # Format response
        appointment_list = []
        for appointment, patient, doctor in appointments:
            appointment_data = {
                "id": appointment.id,
                "patient_id": appointment.patient_id,
                "clinic_id": appointment.clinic_id,
                "patient_number": appointment.patient_number,
                "patient_name": appointment.patient_name,
                "doctor_id": appointment.doctor_id,
                "doctor_name": appointment.doctor_name,
                "notes": appointment.notes,
                "appointment_date": appointment.appointment_date.isoformat() if appointment.appointment_date else None,
                "checked_in_at": appointment.checked_in_at.isoformat() if appointment.checked_in_at else None,
                "checked_out_at": appointment.checked_out_at.isoformat() if appointment.checked_out_at else None,
                "status": appointment.status.value,
                "created_at": appointment.created_at.isoformat() if appointment.created_at else None,
                "updated_at": appointment.updated_at.isoformat() if appointment.updated_at else None,
                "doctor": {
                    "id": doctor.id,
                    "name": doctor.name,
                    "email": doctor.email,
                    "phone": doctor.phone
                },
                "patient": {
                    "id": patient.id,
                    "name": patient.name,
                    "email": patient.email,
                    "mobile_number": patient.mobile_number,
                    "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else None,
                    "gender": patient.gender.value
                }
            }
            appointment_list.append(appointment_data)
        
        return JSONResponse(status_code=200, content={
            "appointments": appointment_list,
            "pagination": {
                "total": total or 0,
                "page": page,
                "per_page": per_page,
                "pages": (total + per_page - 1) // per_page if total else 0
            },
            "stats": {
                "today": today_count,
                "this_month": month_count,
                "this_year": year_count,
                "overall": total_count
            }
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@appointment_router.get("/patient-appointments/{patient_id}",
    response_model=dict,
    status_code=200,
    summary="Get patient appointments with statistics",
    description="""
    Retrieve all appointments for a specific patient with pagination and statistics.
    
    **Path Parameter:**
    - patient_id (UUID): Patient's unique identifier
    
    **Query Parameters:**
    - page (int): Page number for pagination (default: 1)
    - per_page (int): Number of items per page (default: 10, max: 100)
    - sort_by (str): Field to sort by (default: appointment_date)
    - sort_order (str): Sort direction - asc or desc (default: desc)
    
    **Statistics Returned:**
    - Today: Number of appointments today
    - This Month: Number of appointments in current month
    - This Year: Number of appointments in current year
    - Overall: Total number of appointments
    
    **Authentication:**
    - Requires valid doctor Bearer token
    
    **Response:**
    ```json
    {
        "appointments": [
            {
                "id": "uuid",
                "patient_id": "uuid", 
                "clinic_id": "uuid",
                "patient_number": "P001",
                "patient_name": "John Doe",
                "doctor_id": "uuid",
                "doctor_name": "Dr. Smith",
                "notes": "Regular checkup",
                "appointment_date": "2023-01-01T10:00:00",
                "checked_in_at": "2023-01-01T10:00:00",
                "checked_out_at": "2023-01-01T10:30:00",
                "status": "COMPLETED",
                "created_at": "2023-01-01T09:00:00",
                "updated_at": "2023-01-01T10:30:00"
            }
        ],
        "pagination": {
            "total": 100,
            "page": 1,
            "per_page": 10,
            "pages": 10
        },
        "stats": {
            "today": 5,
            "this_month": 45,
            "this_year": 450,
            "overall": 1000
        }
    }
    ```
    """,
    responses={
        200: {
            "description": "Successfully retrieved patient's appointments with statistics",
            "content": {
                "application/json": {
                    "example": {
                        "appointments": [],
                        "pagination": {
                            "total": 0,
                            "page": 1,
                            "per_page": 10,
                            "pages": 0
                        },
                        "stats": {
                            "today": 0,
                            "this_month": 0,
                            "this_year": 0,
                            "overall": 0
                        }
                    }
                }
            }
        },
        401: {
            "description": "Authentication failed or non-doctor user",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "Patient not found",
            "content": {
                "application/json": {
                    "example": {"message": "Patient not found"}
                }
            }
        }
    }
)
async def get_patient_appointments(
    request: Request,
    patient_id: str,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(10, ge=1, le=100, description="Items per page"),
    sort_by: str = Query("appointment_date", description="Field to sort by"),
    sort_order: str = Query("desc", description="Sort direction (asc/desc)")
):
    try:
        decoded_token = verify_token(request)
        user_id = decoded_token.get("user_id") if decoded_token else None
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})

        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return JSONResponse(status_code=404, content={"message": "Patient not found"})

        # Calculate offset
        offset = (page - 1) * per_page

        # Get current date info
        today = datetime.now().date()
        month_start = today.replace(day=1)
        year_start = today.replace(month=1, day=1)

        # Get statistics
        today_count = db.query(Appointment).filter(
            Appointment.patient_id == patient_id,
            func.date(Appointment.appointment_date) == today
        ).count()

        month_count = db.query(Appointment).filter(
            Appointment.patient_id == patient_id,
            func.date(Appointment.appointment_date) >= month_start
        ).count()

        year_count = db.query(Appointment).filter(
            Appointment.patient_id == patient_id,
            func.date(Appointment.appointment_date) >= year_start
        ).count()

        total_count = db.query(Appointment).filter(
            Appointment.patient_id == patient_id
        ).count()

        # Get paginated appointments
        query = db.query(Appointment).filter(Appointment.patient_id == patient_id)
        
        # Apply sorting
        if sort_order == "asc":
            query = query.order_by(getattr(Appointment, sort_by).asc())
        else:
            query = query.order_by(getattr(Appointment, sort_by).desc())

        appointments = query.order_by(Appointment.appointment_date.desc(), Appointment.created_at.desc()).offset(offset).limit(per_page).all()
        
        appointment_list = []
        for appointment in appointments:
            appointment_data = {
                "id": appointment.id,
                "patient_id": appointment.patient_id,
                "clinic_id": appointment.clinic_id,
                "patient_number": appointment.patient_number,
                "patient_name": appointment.patient_name,
                "doctor_id": appointment.doctor_id,
                "doctor_name": appointment.doctor_name,
                "notes": appointment.notes,
                "appointment_date": appointment.appointment_date.isoformat() if appointment.appointment_date else None,
                "checked_in_at": appointment.checked_in_at.isoformat() if appointment.checked_in_at else None,
                "checked_out_at": appointment.checked_out_at.isoformat() if appointment.checked_out_at else None,
                "status": appointment.status.value,
                "created_at": appointment.created_at.isoformat() if appointment.created_at else None,
                "updated_at": appointment.updated_at.isoformat() if appointment.updated_at else None
            }
            appointment_list.append(appointment_data)

        return JSONResponse(status_code=200, content={
            "appointments": appointment_list,
            "pagination": {
                "total": total_count,
                "page": page,
                "per_page": per_page,
                "pages": (total_count + per_page - 1) // per_page
            },
            "stats": {
                "today": today_count,
                "this_month": month_count,
                "this_year": year_count,
                "overall": total_count
            }
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@appointment_router.get("/search",
    response_model=dict,
    status_code=200,
    summary="Search appointments with statistics",
    description="""
    Search and filter appointments using various criteria with pagination and statistics.
    
    **Query Parameters:**
    - patient_name (str, optional): Search by patient name (case-insensitive partial match)
    - patient_email (str, optional): Search by patient email (case-insensitive partial match) 
    - patient_phone (str, optional): Search by patient phone number
    - doctor_name (str, optional): Search by doctor name (case-insensitive partial match)
    - doctor_email (str, optional): Search by doctor email (case-insensitive partial match)
    - doctor_phone (str, optional): Search by doctor phone number
    - patient_gender (str, optional): Filter by patient gender (MALE/FEMALE/OTHER)
    - clinic_id (str, optional): Filter by clinic ID
    - status (str, optional): Filter by appointment status [SCHEDULED, CONFIRMED, CANCELLED, COMPLETED]
    - appointment_date (datetime, optional): Filter appointments from this date onwards (ISO format)
    - page (int): Page number for pagination (default: 1, min: 1)
    - per_page (int): Number of items per page (default: 10, min: 1, max: 100)
    
    **Statistics Returned:**
    - Today: Number of appointments today
    - This Month: Number of appointments in current month
    - This Year: Number of appointments in current year
    - Overall: Total number of appointments
    
    **Authentication:**
    - Requires valid doctor Bearer token
    
    **Response:**
    ```json
    {
        "appointments": [
            {
                "id": "uuid",
                "patient_id": "uuid",
                "clinic_id": "uuid",
                "patient_number": "P001",
                "patient_name": "John Doe",
                "doctor_id": "uuid",
                "doctor_name": "Dr. Smith",
                "notes": "Regular checkup",
                "appointment_date": "2023-01-01T10:00:00",
                "checked_in_at": "2023-01-01T10:00:00",
                "checked_out_at": "2023-01-01T10:30:00",
                "status": "COMPLETED",
                "created_at": "2023-01-01T09:00:00",
                "updated_at": "2023-01-01T10:30:00",
                "doctor": {
                    "id": "uuid",
                    "name": "Dr. Smith",
                    "email": "dr.smith@example.com",
                    "phone": "1234567890"
                },
                "patient": {
                    "id": "uuid",
                    "name": "John Doe",
                    "email": "john@example.com",
                    "mobile_number": "9876543210",
                    "date_of_birth": "1990-01-01",
                    "gender": "MALE"
                }
            }
        ],
        "pagination": {
            "total": 100,
            "page": 1,
            "per_page": 10,
            "pages": 10
        },
        "stats": {
            "today": 5,
            "this_month": 45,
            "this_year": 450,
            "overall": 1000
        }
    }
    ```
    """,
    responses={
        200: {
            "description": "Successfully retrieved search results with statistics",
            "content": {
                "application/json": {
                    "example": {
                        "appointments": [],
                        "pagination": {
                            "total": 0,
                            "page": 1,
                            "per_page": 10,
                            "pages": 0
                        },
                        "stats": {
                            "today": 0,
                            "this_month": 0,
                            "this_year": 0,
                            "overall": 0
                        }
                    }
                }
            }
        },
        401: {
            "description": "Authentication failed or non-doctor user",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        500: {
            "description": "Server error occurred",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error message"}
                }
            }
        }
    }
)
async def search_appointments(
    request: Request,
    patient_name: Optional[str] = None,
    patient_email: Optional[str] = None,
    patient_phone: Optional[str] = None,
    doctor_name: Optional[str] = None,
    doctor_email: Optional[str] = None,
    doctor_phone: Optional[str] = None,
    patient_gender: Optional[str] = None,
    clinic_id: Optional[str] = None,
    status: Optional[str] = None,
    appointment_date: Optional[datetime] = None,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(10, ge=1, le=100, description="Items per page"),
    sort_by: str = Query("appointment_date", description="Field to sort by"),
    sort_order: str = Query("desc", description="Sort direction (asc/desc)"),
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        user_id = decoded_token.get("user_id") if decoded_token else None
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})

        query = db.query(Appointment, Patient, User)\
            .join(Patient, Appointment.patient_id == Patient.id)\
            .join(User, Appointment.doctor_id == User.id)

        # Search filters
        search_filters = []
        if patient_name:
            search_filters.append(Patient.name.ilike(f"%{patient_name}%"))
        if patient_email:
            search_filters.append(Patient.email.ilike(f"%{patient_email}%"))
        if patient_phone:
            search_filters.append(Patient.mobile_number.ilike(f"%{patient_phone}%"))
        if doctor_name:
            search_filters.append(User.name.ilike(f"%{doctor_name}%"))
        if doctor_email:
            search_filters.append(User.email.ilike(f"%{doctor_email}%"))
        if doctor_phone:
            search_filters.append(User.phone.ilike(f"%{doctor_phone}%"))


        # Filter conditions
        filter_conditions = []
        if patient_gender:
            filter_conditions.append(Patient.gender == patient_gender)
        if clinic_id:
            filter_conditions.append(Appointment.clinic_id == clinic_id)
        if status:
            filter_conditions.append(Appointment.status == status)
        if appointment_date:
            filter_conditions.append(Appointment.appointment_date >= appointment_date)

        if search_filters:
            query = query.filter(or_(*search_filters))
        if filter_conditions:
            query = query.filter(and_(*filter_conditions))

        # Get statistics
        today = datetime.now().date()
        today_start = datetime.combine(today, time.min)
        today_end = datetime.combine(today, time.max)

        today_count = db.execute(
            select(func.count(Appointment.id))
            .where(Appointment.doctor_id == user.id)
            .where(Appointment.created_at.between(today_start, today_end))
        ).scalar() or 0

        month_count = db.execute(
            select(func.count(Appointment.id))
            .where(Appointment.doctor_id == user.id)
            .where(Appointment.created_at >= today.replace(day=1))
        ).scalar() or 0

        year_count = db.execute(
            select(func.count(Appointment.id))
            .where(Appointment.doctor_id == user.id)
            .where(Appointment.created_at >= today.replace(month=1, day=1))
        ).scalar() or 0

        # Get total count for pagination
        total_count = query.count()

        # Apply pagination
        offset = (page - 1) * per_page
        query = query.offset(offset).limit(per_page)

        appointments = query.all()
        if sort_order == "asc":
            appointments = sorted(appointments, key=lambda x: getattr(x[0], sort_by))
        else:
            appointments = sorted(appointments, key=lambda x: getattr(x[0], sort_by), reverse=True)

        # Format response
        appointment_list = []
        for appointment, patient, doctor in appointments:
            appointment_data = {
                "id": appointment.id,
                "patient_id": appointment.patient_id,
                "clinic_id": appointment.clinic_id,
                "patient_number": appointment.patient_number,
                "patient_name": appointment.patient_name,
                "doctor_id": appointment.doctor_id,
                "doctor_name": appointment.doctor_name,
                "notes": appointment.notes,
                "appointment_date": appointment.appointment_date.isoformat() if appointment.appointment_date else None,
                "checked_in_at": appointment.checked_in_at.isoformat() if appointment.checked_in_at else None,
                "checked_out_at": appointment.checked_out_at.isoformat() if appointment.checked_out_at else None,
                "status": appointment.status.value,
                "created_at": appointment.created_at.isoformat() if appointment.created_at else None,
                "updated_at": appointment.updated_at.isoformat() if appointment.updated_at else None,
                "doctor": {
                    "id": doctor.id,
                    "name": doctor.name,
                    "email": doctor.email,
                    "phone": doctor.phone
                },
                "patient": {
                    "id": patient.id,
                    "name": patient.name,
                    "email": patient.email,
                    "mobile_number": patient.mobile_number,
                    "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else None,
                    "gender": patient.gender.value
                }
            }
            appointment_list.append(appointment_data)

        return JSONResponse(status_code=200, content={
            "appointments": appointment_list,
            "pagination": {
                "total": total_count,
                "page": page,
                "per_page": per_page,
                "pages": (total_count + per_page - 1) // per_page
            },
            "stats": {
                "today": today_count,
                "this_month": month_count,
                "this_year": year_count,
                "overall": total_count
            }
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@appointment_router.get("/details/{appointment_id}",
    response_model=dict,
    status_code=200,
    summary="Get appointment details with related records",
    description="""
    Retrieve detailed information for a specific appointment including clinical notes, treatments, treatment plans, payments and invoices.
    
    **Path parameter:**
    - appointment_id (UUID): Appointment's unique identifier
    
    **Authentication:**
    - Requires valid doctor Bearer token
    
    **Response:**
    ```json
    {
        "appointment": {
            "id": "uuid",
            "patient_id": "uuid", 
            "clinic_id": "uuid",
            "patient_number": "P001",
            "patient_name": "John Doe",
            "doctor_id": "uuid",
            "doctor_name": "Dr. Smith",
            "notes": "Regular checkup",
            "appointment_date": "2023-01-01T10:00:00",
            "checked_in_at": "2023-01-01T10:00:00",
            "checked_out_at": "2023-01-01T10:30:00",
            "status": "completed",
            "send_reminder": true,
            "remind_time_before": 30,
            "created_at": "2023-01-01T09:00:00",
            "updated_at": "2023-01-01T10:30:00",
            "doctor": {
                "id": "uuid",
                "name": "Dr. Smith", 
                "email": "dr.smith@example.com",
                "phone": "1234567890"
            },
            "patient": {
                "id": "uuid",
                "name": "John Doe",
                "email": "john@example.com", 
                "mobile_number": "9876543210",
                "date_of_birth": "1990-01-01",
                "gender": "male"
            },
            "clinical_notes": [{
                "id": "uuid",
                "date": "2023-01-01",
                "attachments": [{"id": "uuid", "attachment": "path/to/file"}],
                "treatments": [{"id": "uuid", "name": "Cleaning"}],
                "medicines": [{
                    "id": "uuid",
                    "item_name": "Medicine",
                    "price": 10.00,
                    "quantity": 1,
                    "dosage": "1x daily",
                    "instructions": "After meals",
                    "amount": 10.00
                }],
                "complaints": [{"id": "uuid", "complaint": "Pain"}],
                "diagnoses": [{"id": "uuid", "diagnosis": "Cavity"}],
                "vital_signs": [{"id": "uuid", "vital_sign": "BP: 120/80"}],
                "notes": [{"id": "uuid", "note": "Patient notes"}]
            }],
            "treatments": [{
                "id": "uuid",
                "treatment_date": "2023-01-01T10:00:00",
                "treatment_name": "Cleaning",
                "tooth_number": "18",
                "treatment_notes": "Deep cleaning performed",
                "quantity": 1,
                "unit_cost": 100.00,
                "amount": 100.00,
                "discount": 0,
                "discount_type": "percentage",
                "completed": true
            }],
            "treatment_plans": [{
                "id": "uuid",
                "date": "2023-01-01T10:00:00",
                "treatments": [{
                    "id": "uuid",
                    "treatment_name": "Root Canal",
                    "tooth_number": "16",
                    "quantity": 1,
                    "unit_cost": 500.00,
                    "amount": 500.00,
                    "completed": false
                }]
            }],
            "payments": [{
                "id": "uuid",
                "date": "2023-01-01T10:30:00",
                "receipt_number": "R001",
                "amount_paid": 100.00,
                "payment_mode": "cash",
                "status": "completed",
                "refund": false,
                "refunded_amount": null,
                "cancelled": false,
                "invoices": [{
                    "id": "uuid",
                    "invoice_number": "INV001",
                    "total_amount": 100.00,
                    "invoice_items": [{
                        "treatment_name": "Cleaning",
                        "quantity": 1,
                        "unit_cost": 100.00,
                        "discount": 0,
                        "tax_percent": 0
                    }]
                }]
            }]
        }
    }
    ```
    """,
    responses={
        200: {"description": "Successfully retrieved appointment details"},
        401: {"description": "Authentication failed or non-doctor user"},
        404: {"description": "Appointment not found"},
        500: {"description": "Server error occurred"}
    }
)
async def get_appointment_details(
    request: Request, 
    appointment_id: str,
    db: Session = Depends(get_db)
):
    try:
        # Verify doctor authentication
        decoded_token = verify_token(request)
        user_id = decoded_token.get("user_id")
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})

        # Get appointment with patient and doctor in single query
        result = (
            db.query(Appointment, Patient, User)
            .join(Patient, Appointment.patient_id == Patient.id)
            .join(User, Appointment.doctor_id == User.id)
            .filter(Appointment.id == appointment_id)
            .first()
        )
        
        if not result:
            return JSONResponse(status_code=404, content={"message": "Appointment not found"})
            
        appointment, patient, doctor = result

        # Get related records with optimized queries
        clinical_notes = (
            db.query(ClinicalNote)
            .options(
                joinedload(ClinicalNote.attachments),
                joinedload(ClinicalNote.treatments),
                joinedload(ClinicalNote.medicines),
                joinedload(ClinicalNote.complaints),
                joinedload(ClinicalNote.diagnoses),
                joinedload(ClinicalNote.vital_signs),
                joinedload(ClinicalNote.notes)
            )
            .filter(ClinicalNote.appointment_id == appointment_id)
            .all()
        )

        # Get treatment plans first
        treatment_plans = (
            db.query(TreatmentPlan)
            .options(joinedload(TreatmentPlan.treatments))
            .filter(TreatmentPlan.appointment_id == appointment_id)
            .all()
        )

        # Get all treatments
        treatments = (
            db.query(Treatment)
            .filter(Treatment.appointment_id == appointment_id)
            .all()
        )

        # Create a set of treatment IDs that are in plans
        planned_treatment_ids = set()
        for plan in treatment_plans:
            for treatment in plan.treatments:
                planned_treatment_ids.add(str(treatment.id))

        # Filter out treatments that are already in treatment plans
        standalone_treatments = [t for t in treatments if str(t.id) not in planned_treatment_ids]

        payments = (
            db.query(Payment)
            .filter(Payment.appointment_id == appointment_id)
            .all()
        )

        # Format response data
        appointment_data = {
            "id": appointment.id,
            "patient_id": appointment.patient_id,
            "clinic_id": appointment.clinic_id,
            "patient_number": appointment.patient_number,
            "patient_name": appointment.patient_name,
            "doctor_id": appointment.doctor_id,
            "doctor_name": appointment.doctor_name,
            "notes": appointment.notes,
            "appointment_date": appointment.appointment_date.isoformat() if appointment.appointment_date else None,
            "checked_in_at": appointment.checked_in_at.isoformat() if appointment.checked_in_at else None,
            "checked_out_at": appointment.checked_out_at.isoformat() if appointment.checked_out_at else None,
            "status": appointment.status.value,
            "send_reminder": appointment.send_reminder,
            "remind_time_before": appointment.remind_time_before,
            "created_at": appointment.created_at.isoformat() if appointment.created_at else None,
            "updated_at": appointment.updated_at.isoformat() if appointment.updated_at else None,
            "doctor": {
                "id": doctor.id,
                "name": doctor.name,
                "email": doctor.email,
                "phone": doctor.phone
            },
            "patient": {
                "id": patient.id,
                "name": patient.name,
                "email": patient.email,
                "mobile_number": patient.mobile_number,
                "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else None,
                "gender": patient.gender.value
            },
            "clinical_notes": [{
                "id": note.id,
                "date": note.date.isoformat() if note.date else None,
                "attachments": [{"id": a.id, "attachment": a.attachment} for a in note.attachments],
                "treatments": [{"id": t.id, "name": t.name} for t in note.treatments],
                "medicines": [{
                    "id": m.id,
                    "item_name": m.item_name,
                    "price": m.price,
                    "quantity": m.quantity,
                    "dosage": m.dosage,
                    "instructions": m.instructions,
                    "amount": m.amount
                } for m in note.medicines],
                "complaints": [{"id": c.id, "complaint": c.complaint} for c in note.complaints],
                "diagnoses": [{"id": d.id, "diagnosis": d.diagnosis} for d in note.diagnoses],
                "vital_signs": [{"id": v.id, "vital_sign": v.vital_sign} for v in note.vital_signs],
                "notes": [{"id": n.id, "note": n.note} for n in note.notes]
            } for note in clinical_notes],
            "treatments": [{
                "id": t.id,
                "treatment_date": t.treatment_date.isoformat() if t.treatment_date else None,
                "treatment_name": t.treatment_name,
                "tooth_number": t.tooth_number,
                "treatment_notes": t.treatment_notes,
                "quantity": t.quantity,
                "unit_cost": t.unit_cost,
                "amount": t.amount,
                "discount": t.discount,
                "discount_type": t.discount_type,
                "completed": t.completed
            } for t in standalone_treatments],
            "treatment_plans": [{
                "id": plan.id,
                "date": plan.date.isoformat() if plan.date else None,
                "treatments": [{
                    "id": t.id,
                    "treatment_date": t.treatment_date.isoformat() if t.treatment_date else None,
                    "treatment_name": t.treatment_name,
                    "tooth_number": t.tooth_number,
                    "treatment_notes": t.treatment_notes,
                    "quantity": t.quantity,
                    "unit_cost": t.unit_cost,
                    "amount": t.amount,
                    "discount": t.discount,
                    "discount_type": t.discount_type,
                    "completed": t.completed
                } for t in plan.treatments]
            } for plan in treatment_plans],
            "payments": [{
                "id": payment.id,
                "date": payment.date.isoformat() if payment.date else None,
                "receipt_number": payment.receipt_number,
                "amount_paid": payment.amount_paid,
                "payment_mode": payment.payment_mode,
                "status": payment.status,
                "refund": payment.refund,
                "refunded_amount": payment.refunded_amount,
                "cancelled": payment.cancelled,
                "invoices": [{
                    "id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "total_amount": invoice.total_amount,
                    "invoice_items": [{
                        "treatment_name": item.treatment_name,
                        "quantity": item.quantity,
                        "unit_cost": item.unit_cost,
                        "discount": item.discount,
                        "tax_percent": item.tax_percent
                    } for item in invoice.invoice_items]
                } for invoice in db.query(Invoice).filter(Invoice.payment_id == payment.id).all()]
            } for payment in payments]
        }

        return JSONResponse(status_code=200, content={"appointment": appointment_data})

    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
@appointment_router.patch("/update/{appointment_id}",
    response_model=dict,
    status_code=200,
    summary="Update appointment details",
    description="""
    Update details of a specific appointment.

    **Path parameter:**
    - appointment_id (UUID): Appointment's unique identifier

    **Request body (optional fields):**
    - notes (str): Updated notes
    - appointment_date (datetime): New appointment date/time
    - checked_in_at (datetime): New check-in time
    - checked_out_at (datetime): New check-out time
    - status (str): New status [SCHEDULED, CONFIRMED, CANCELLED, COMPLETED]
    - share_on_email (bool): Update email sharing preference
    - share_on_sms (bool): Update SMS sharing preference
    - share_on_whatsapp (bool): Update WhatsApp sharing preference

    **Authentication:**
    - Requires valid doctor Bearer token

    **Response:**
    ```json
    {
        "message": "Appointment updated successfully",
        "appointment_id": "uuid"
    }
    ```
    """,
    responses={
        200: {
            "description": "Successfully updated appointment",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Appointment updated successfully",
                        "appointment_id": "123e4567-e89b-12d3-a456-426614174000"
                    }
                }
            }
        },
        400: {
            "description": "Invalid input",
            "content": {
                "application/json": {
                    "example": {"message": "Invalid status value"}
                }
            }
        },
        401: {
            "description": "Authentication failed or non-doctor user",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "Appointment not found",
            "content": {
                "application/json": {
                    "example": {"message": "Appointment not found"}
                }
            }
        },
        500: {
            "description": "Server error occurred",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error message"}
                }
            }
        }
    }
)
async def update_appointment(request: Request, appointment_id: str, appointment_update: AppointmentUpdate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        # Verify authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})

        user_id = decoded_token.get("user_id")
        user = db.query(User).filter(User.id == user_id).first()
        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=401, content={"message": "Unauthorized - doctor access required"})

        # Get appointment
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not appointment:
            return JSONResponse(status_code=404, content={"message": "Appointment not found"})

        # Validate status if provided
        if appointment_update.status:
            status = appointment_update.status.upper()
            if status not in ["SCHEDULED", "CONFIRMED", "CANCELLED", "COMPLETED"]:
                return JSONResponse(status_code=400, content={
                    "message": "Invalid status. Must be either 'SCHEDULED', 'CONFIRMED', 'CANCELLED' or 'COMPLETED'"
                })
            appointment.status = AppointmentStatus(status.lower())

        # Update fields if provided
        if appointment_update.notes is not None:
            appointment.notes = appointment_update.notes
        if appointment_update.appointment_date is not None:
            appointment.appointment_date = appointment_update.appointment_date
        if appointment_update.checked_in_at is not None:
            appointment.checked_in_at = appointment_update.checked_in_at
        if appointment_update.checked_out_at is not None:
            appointment.checked_out_at = appointment_update.checked_out_at
        if appointment_update.share_on_email is not None:
            appointment.share_on_email = appointment_update.share_on_email
        if appointment_update.share_on_sms is not None:
            appointment.share_on_sms = appointment_update.share_on_sms
        if appointment_update.share_on_whatsapp is not None:
            appointment.share_on_whatsapp = appointment_update.share_on_whatsapp
        
        db.commit()
        db.refresh(appointment)

        # Send email notification if enabled
        if appointment.share_on_email:
            background_tasks.add_task(send_appointment_email, db, appointment.id)

        return JSONResponse(status_code=200, content={
            "message": "Appointment updated successfully",
            "appointment_id": appointment.id
        })

    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@appointment_router.delete("/delete/{appointment_id}",
    response_model=dict,
    status_code=200,
    summary="Delete appointment",
    description="""
    Delete a specific appointment.
    
    **Path parameter:**
    - appointment_id (UUID): Appointment's unique identifier
    
    **Authentication:**
    - Requires valid doctor Bearer token
    
    **Response:**
    ```json
    {
        "message": "Appointment deleted successfully"
    }
    ```
    """,
    responses={
        200: {
            "description": "Successfully deleted appointment",
            "content": {
                "application/json": {
                    "example": {"message": "Appointment deleted successfully"}
                }
            }
        },
        401: {
            "description": "Authentication failed or non-doctor user",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "Appointment not found",
            "content": {
                "application/json": {
                    "example": {"message": "Appointment not found"}
                }
            }
        },
        500: {
            "description": "Server error occurred",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error message"}
                }
            }
        }
    }
)
async def delete_appointment(request: Request, appointment_id: str, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        user_id = decoded_token.get("user_id") if decoded_token else None
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        
        if not appointment:
            return JSONResponse(status_code=404, content={"message": "Appointment not found"})

        db.delete(appointment)
        db.commit()
        
        return JSONResponse(status_code=200, content={"message": "Appointment deleted successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@appointment_router.patch("/check-in/{appointment_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Check in to an appointment",
    description="""
    Check in to a specific appointment by its ID.
    
    This endpoint allows doctors to check in to an appointment.
    The appointment must exist and must not already be in a checked-in state.
    
    Returns a success message upon successful check-in with the appointment ID and updated status.
    """,
    responses={
        200: {
            "description": "Appointment checked in successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Appointment checked in successfully",
                        "appointment_id": "123e4567-e89b-12d3-a456-426614174000",
                        "status": "checked_in"
                    }
                }
            }
        },
        400: {
            "description": "Bad Request - Appointment already checked in",
            "content": {
                "application/json": {
                    "example": {"message": "Appointment already checked in"}
                }
            }
        },
        401: {
            "description": "Unauthorized - Authentication required or non-doctor user",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized - doctor access required"}
                }
            }
        },
        404: {
            "description": "Appointment not found",
            "content": {
                "application/json": {
                    "example": {"message": "Appointment not found"}
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "An unexpected error occurred"}
                }
            }
        }
    }
)
async def check_in_appointment(request: Request, appointment_id: str, db: Session = Depends(get_db)):
    try:
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user_id = decoded_token.get("user_id")
        user = db.query(User).filter(User.id == user_id).first()
        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Unauthorized - doctor access required"})
        
        # Find appointment
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not appointment:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Appointment not found"})
        
        # Check if already checked in
        if appointment.status == AppointmentStatus.CHECKED_IN:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Appointment already checked in"})
        
        # Update appointment status and check-in time
        appointment.status = AppointmentStatus.CHECKED_IN
        db.commit()
        db.refresh(appointment)
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Appointment checked in successfully",
            "appointment_id": appointment_id,
            "status": str(appointment.status.value)
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"An unexpected error occurred: {str(e)}"})

@appointment_router.patch("/check-out/{appointment_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Check out from an appointment",
    description="""
    Check out from a specific appointment by its ID.
    
    This endpoint allows doctors to check out from an appointment.
    The appointment must exist and must not already be in a completed state.
    
    Returns a success message upon successful check-out with the appointment ID and updated status.
    """,
    responses={
        200: {
            "description": "Appointment checked out successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Appointment checked out successfully",
                        "appointment_id": "123e4567-e89b-12d3-a456-426614174000",
                        "status": "completed"
                    }
                }
            }
        },
        400: {
            "description": "Bad Request - Appointment already completed",
            "content": {
                "application/json": {
                    "example": {"message": "Appointment already completed"}
                }
            }
        },
        401: {
            "description": "Unauthorized - Authentication required or non-doctor user",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized - doctor access required"}
                }
            }
        },
        404: {
            "description": "Appointment not found",
            "content": {
                "application/json": {
                    "example": {"message": "Appointment not found"}
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "An unexpected error occurred"}
                }
            }
        }
    }
)
async def check_out_appointment(request: Request, appointment_id: str, db: Session = Depends(get_db)):
    try:
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user_id = decoded_token.get("user_id")
        user = db.query(User).filter(User.id == user_id).first()
        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Unauthorized - doctor access required"})
        
        # Find appointment
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not appointment:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Appointment not found"})
        
        # Check if already checked out
        if appointment.status == AppointmentStatus.COMPLETED:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Appointment already completed"})
        
        # Update appointment status and check-out time
        appointment.status = AppointmentStatus.COMPLETED
        db.commit()
        db.refresh(appointment)
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Appointment checked out successfully",
            "appointment_id": appointment_id,
            "status": str(appointment.status.value)
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"An unexpected error occurred: {str(e)}"})
       
@appointment_router.patch("/cancel/{appointment_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Cancel an appointment",
    description="""
    Cancel a specific appointment by its ID.
    
    This endpoint allows doctors to mark an appointment as cancelled.
    The appointment must exist and must not already be in a cancelled state.
    
    Returns a success message upon successful cancellation with the appointment ID and updated status.
    """,
    responses={
        200: {
            "description": "Appointment cancelled successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Appointment cancelled successfully",
                        "appointment_id": "123e4567-e89b-12d3-a456-426614174000",
                        "status": "cancelled"
                    }
                }
            }
        },
        400: {
            "description": "Bad Request - Appointment already cancelled",
            "content": {
                "application/json": {
                    "example": {"message": "Appointment already cancelled"}
                }
            }
        },
        401: {
            "description": "Unauthorized - Authentication required or non-doctor user",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized - doctor access required"}
                }
            }
        },
        404: {
            "description": "Appointment not found",
            "content": {
                "application/json": {
                    "example": {"message": "Appointment not found"}
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "An unexpected error occurred"}
                }
            }
        }
    }
)
async def cancel_appointment(request: Request, appointment_id: str, db: Session = Depends(get_db)):
    try:
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user_id = decoded_token.get("user_id")
        user = db.query(User).filter(User.id == user_id).first()
        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Unauthorized - doctor access required"})
        
        # Find appointment
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not appointment:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Appointment not found"})
        
        # Check if already cancelled
        if appointment.status == AppointmentStatus.CANCELLED:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Appointment already cancelled"})
        
        # Update appointment status
        appointment.status = AppointmentStatus.CANCELLED
        db.commit()
        db.refresh(appointment)
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Appointment cancelled successfully",
            "appointment_id": appointment_id,
            "status": str(appointment.status.value)
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"An unexpected error occurred: {str(e)}"})
    
@appointment_router.post("/add-reminder/{appointment_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Add appointment reminder",
    description="""
    Add an appointment reminder for a specific appointment.
    
    **Path parameter:**
    - appointment_id (UUID): Appointment's unique identifier
    
    **Request body:**
    - send_reminder (bool): Whether to send a reminder
    - remind_time_before (int): Minutes before appointment to send reminder
    
    **Authentication:**
    - Requires valid doctor Bearer token
    
    **Response:**
    ```json
    {
        "message": "Appointment reminder added successfully",
        "reminder_time": "2023-01-01T10:30:00"
    }
    ```
    """,
    responses={
        200: {
            "description": "Successfully added appointment reminder",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Appointment reminder added successfully",
                        "reminder_time": "2023-01-01T10:30:00"
                    }
                }
            }
        },
        400: {
            "description": "Bad request - invalid reminder settings",
            "content": {
                "application/json": {
                    "example": {"message": "Reminder time is in the past"}
                }
            }
        },
        401: {
            "description": "Authentication failed or non-doctor user",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "Appointment not found",
            "content": {
                "application/json": {
                    "example": {"message": "Appointment not found"}
                }
            }
        },
        500: {
            "description": "Server error occurred",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error message"}
                }
            }
        }
    }
)
async def add_appointment_reminder(request: Request, appointment_id: str, appointment_reminder: AppointmentReminder, db: Session = Depends(get_db)):
    try:
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user_id = decoded_token.get("user_id")
        user = db.query(User).filter(User.id == user_id).first()
        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Unauthorized - doctor access required"})
        
        # Find appointment
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not appointment:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Appointment not found"})
        
        # Validate appointment date
        current_time = datetime.now()
        if appointment.appointment_date <= current_time:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Cannot add reminder for past appointments"})
        
        # Update appointment with reminder details
        appointment.send_reminder = appointment_reminder.send_reminder
        appointment.remind_time_before = appointment_reminder.remind_time_before
        
        # If not sending reminder, just save the preferences
        if not appointment_reminder.send_reminder:
            db.commit()
            return JSONResponse(status_code=status.HTTP_200_OK, content={"message": "Reminder preferences updated"})
        
        # Calculate reminder time
        reminder_time = appointment.appointment_date - timedelta(minutes=appointment_reminder.remind_time_before)
        
        # Check if reminder time is in the past
        if reminder_time <= current_time:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST, 
                content={"message": "Reminder time is in the past. Please choose a shorter reminder time."}
            )
        
        # Remove any existing scheduled reminders for this appointment
        for job in scheduler.get_jobs():
            if job.id and job.id.startswith(f"reminder_{appointment.id}_"):
                scheduler.remove_job(job.id)
        
        # Schedule the reminder
        job_id = f"reminder_{appointment.id}_{reminder_time.timestamp()}"
        scheduler.add_job(
            send_email_sync, 
            'date', 
            run_date=reminder_time, 
            args=[db, appointment.id],
            id=job_id,
            replace_existing=True
        )
        
        # Save changes to database
        db.commit()
        db.refresh(appointment)
        
        return JSONResponse(
            status_code=status.HTTP_200_OK, 
            content={
                "message": "Appointment reminder added successfully",
                "reminder_time": reminder_time.isoformat(),
                "job_id": job_id
            }
        )
        
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"An unexpected error occurred: {str(e)}"})
    
@appointment_router.patch("/cancel-reminder/{appointment_id}",
    response_model=dict,
    status_code=200,
    summary="Cancel appointment reminder",
    description="""
    Cancel a scheduled reminder for a specific appointment.
    
    **Path parameter:**
    - appointment_id (UUID): Appointment's unique identifier
    
    **Authentication:**
    - Requires valid doctor Bearer token
    
    **Response:**
    ```json
    {
        "message": "Appointment reminder cancelled successfully"
    }
    ```
    """,
    responses={
        200: {
            "description": "Successfully cancelled reminder",
            "content": {
                "application/json": {
                    "example": {"message": "Appointment reminder cancelled successfully"}
                }
            }
        },
        400: {
            "description": "No reminder scheduled",
            "content": {
                "application/json": {
                    "example": {"message": "No reminder scheduled for this appointment"}
                }
            }
        },
        401: {
            "description": "Authentication failed or non-doctor user",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized - doctor access required"}
                }
            }
        },
        404: {
            "description": "Appointment not found",
            "content": {
                "application/json": {
                    "example": {"message": "Appointment not found"}
                }
            }
        },
        500: {
            "description": "Server error occurred",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error message"}
                }
            }
        }
    }
)
async def cancel_appointment_reminder(request: Request, appointment_id: str, db: Session = Depends(get_db)):
    try:
        # Validate authentication
        decoded_token = verify_token(request)
        user_id = decoded_token.get("user_id") if decoded_token else None
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Unauthorized - doctor access required"})
        
        # Find appointment
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not appointment:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Appointment not found"})
        
        # Check if reminder is scheduled
        if not appointment.send_reminder:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "No reminder scheduled for this appointment"})
        
        # Remove any existing scheduled reminders for this appointment
        jobs_removed = 0
        for job in scheduler.get_jobs():
            if job.id and job.id.startswith(f"reminder_{appointment.id}_"):
                scheduler.remove_job(job.id)
                jobs_removed += 1
        
        # Update appointment to remove reminder
        appointment.send_reminder = False
        appointment.remind_time_before = 0
        db.commit()
        db.refresh(appointment)
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Appointment reminder cancelled successfully",
            "jobs_removed": jobs_removed
        })
    
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"An unexpected error occurred: {str(e)}"})
