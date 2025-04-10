from fastapi import APIRouter, Depends, Request, Query, status, BackgroundTasks, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from .schemas import AppointmentCreate, AppointmentUpdate, AppointmentResponse, AppointmentReminder, AppointmentFileCreate, AppointmentFile, AppointmentFileUpdate
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
from prediction.routes import update_image_url


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
        if appointment.clinic_id:
            clinic_id = appointment.clinic_id or user.default_clinic_id
            if not clinic_id:
                return JSONResponse(status_code=400, content={"message": "Clinic ID is required"})
                
            clinic = db.query(Clinic).filter(Clinic.id == clinic_id).first()
            if not clinic:
                return JSONResponse(status_code=404, content={"message": "Clinic not found"})
        else:
            clinic = None

        # Validate status
        status = appointment.status
        if status.upper() not in ["SCHEDULED", "CANCELLED", "CHECKED_IN", "COMPLETED"]:
            return JSONResponse(status_code=400, content={"message": "Invalid status. Must be either 'SCHEDULED', 'CANCELLED', 'CHECKED_IN' or 'COMPLETED'"})

        new_appointment = Appointment(
            patient_id=patient.id,
            patient_number=patient.patient_number if hasattr(patient, 'patient_number') else None,
            patient_name=patient.name,
            doctor_id=doctor.id,
            doctor_name=doctor.name,
            notes=appointment.notes,
            appointment_date=appointment.appointment_date,
            start_time=appointment.start_time,
            end_time=appointment.end_time,
            status=AppointmentStatus(status),
            share_on_email=appointment.share_on_email,
            share_on_sms=appointment.share_on_sms,
            share_on_whatsapp=appointment.share_on_whatsapp,
        )
        if clinic:
            new_appointment.clinic_id = clinic.id

        db.add(new_appointment)
        db.commit()
        db.refresh(new_appointment)

        if new_appointment.share_on_email:
            background_tasks.add_task(send_appointment_email, db, new_appointment.id)

        return JSONResponse(status_code=201, content={"message": "Appointment created successfully", "appointment_id": new_appointment.id})
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

        # Base query - get all appointments for the doctor
        query = db.query(Appointment)

        # Add sorting
        if hasattr(Appointment, sort_by):
            sort_column = getattr(Appointment, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(sort_column.desc())
            else:
                query = query.order_by(sort_column.asc())
        else:
            # Default sort if invalid column provided
            query = query.order_by(Appointment.appointment_date.desc())

        # Get total count for pagination
        total = query.count()

        # Add pagination
        query = query.offset((page - 1) * per_page).limit(per_page)
        
        # Execute query
        appointments = query.all()

        # Get statistics
        today = datetime.now().date()
        today_start = datetime.combine(today, time.min)
        today_end = datetime.combine(today, time.max)

        # Count appointments for today
        today_count = db.query(Appointment).filter(
            Appointment.doctor_id == user_id,
            Appointment.appointment_date.between(today_start, today_end)
        ).count()

        # Count appointments for this month
        first_day_of_month = today.replace(day=1)
        month_count = db.query(Appointment).filter(
            Appointment.doctor_id == user_id,
            Appointment.appointment_date >= first_day_of_month
        ).count()

        # Count appointments for this year
        first_day_of_year = today.replace(month=1, day=1)
        year_count = db.query(Appointment).filter(
            Appointment.doctor_id == user_id,
            Appointment.appointment_date >= first_day_of_year
        ).count()

        # Count all appointments
        total_count = db.query(Appointment).filter(
            Appointment.doctor_id == user_id
        ).count()

        # Format response
        appointment_list = []
        for appointment in appointments:
            # Fetch patient and doctor separately
            patient = db.query(Patient).filter(Patient.id == appointment.patient_id).first()
            doctor = db.query(User).filter(User.id == appointment.doctor_id).first()

            patient_data = None
            doctor_data = None

            if patient:
                patient_data = {
                    "id": patient.id,
                    "name": patient.name,
                    "email": patient.email,
                    "mobile_number": patient.mobile_number,
                    "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else None,
                    "gender": patient.gender.value if hasattr(patient.gender, 'value') else str(patient.gender)
                }

            if doctor:
                doctor_data = {
                    "id": doctor.id,
                    "name": doctor.name,
                    "email": doctor.email,
                    "phone": doctor.phone,
                    "color_code": doctor.color_code if hasattr(doctor, 'color_code') else None
                }
            
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
                "start_time": appointment.start_time.isoformat() if appointment.start_time else None,
                "end_time": appointment.end_time.isoformat() if appointment.end_time else None,
                "checked_in_at": appointment.checked_in_at.isoformat() if appointment.checked_in_at else None,
                "checked_out_at": appointment.checked_out_at.isoformat() if appointment.checked_out_at else None,
                "status": appointment.status.value if hasattr(appointment.status, 'value') else str(appointment.status),
                "send_reminder": appointment.send_reminder,
                "remind_time_before": appointment.remind_time_before,
                "created_at": appointment.created_at.isoformat() if appointment.created_at else None,
                "updated_at": appointment.updated_at.isoformat() if appointment.updated_at else None,
                "doctor": doctor_data,
                "patient": patient_data
            }

            appointment_list.append(appointment_data)
        
        return JSONResponse(status_code=200, content={
            "appointments": appointment_list,
            "pagination": {
                "total": total,
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
        import traceback
        traceback.print_exc()
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
                .filter(ClinicalNote.appointment_id == appointment.id)
                .all()
            )

            # Get treatment plans first
            treatment_plans = (
                db.query(TreatmentPlan)
                .options(joinedload(TreatmentPlan.treatments))
                .filter(TreatmentPlan.appointment_id == appointment.id)
                .all()
            )

            # Get all treatments
            treatments = (
                db.query(Treatment)
                .filter(Treatment.appointment_id == appointment.id)
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
                .filter(Payment.appointment_id == appointment.id)
                .all()
            )

            completed_procedures = (
                db.query(CompletedProcedure)
                .filter(CompletedProcedure.appointment_id == appointment.id)
                .all()
            )

            doctor = db.query(User).filter(User.id == appointment.doctor_id).first()
            patient = db.query(Patient).filter(Patient.id == appointment.patient_id).first()

            doctor_data = None
            patient_data = None

            if doctor:
                doctor_data = {
                    "id": doctor.id,
                    "name": doctor.name,
                    "email": doctor.email,
                    "phone": doctor.phone,
                    "color_code": doctor.color_code
                }

            if patient:
                patient_data = {
                    "id": patient.id,
                    "name": patient.name,
                    "email": patient.email,
                    "mobile_number": patient.mobile_number,
                    "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else None,
                    "gender": patient.gender.value
                }
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
                "start_time": appointment.start_time.isoformat() if appointment.start_time else None,
                "end_time": appointment.end_time.isoformat() if appointment.end_time else None,
                "checked_in_at": appointment.checked_in_at.isoformat() if appointment.checked_in_at else None,
                "checked_out_at": appointment.checked_out_at.isoformat() if appointment.checked_out_at else None,
                "status": appointment.status.value,
                "send_reminder": appointment.send_reminder,
                "remind_time_before": appointment.remind_time_before,
                "created_at": appointment.created_at.isoformat() if appointment.created_at else None,
                "updated_at": appointment.updated_at.isoformat() if appointment.updated_at else None,
                "doctor": doctor_data,
                "patient": patient_data,
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
                "completed_procedures": [{
                    "id": cp.id,
                    "procedure_name": cp.procedure_name,
                    "unit_cost": cp.unit_cost,
                    "quantity": cp.quantity,
                    "amount": cp.amount,
                    "procedure_description": cp.procedure_description,
                    "created_at": cp.created_at.isoformat() if cp.created_at else None,
                    "updated_at": cp.updated_at.isoformat() if cp.updated_at else None
                } for cp in completed_procedures],
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
    - doctor_id (str, optional): Search by doctor id
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
    - today (bool, optional): Filter appointments scheduled for today (default: false)
    - recent (bool, optional): Filter appointments from the last 7 days (default: false)
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
    doctor_id: Optional[str] = None,
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
    today: Optional[bool] = False,
    recent: Optional[bool] = False,
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
        if doctor_id:
            filter_conditions.append(Appointment.doctor_id == doctor_id)
        if patient_gender:
            filter_conditions.append(Patient.gender == patient_gender)
        if clinic_id:
            filter_conditions.append(Appointment.clinic_id == clinic_id)
        if status:
            filter_conditions.append(Appointment.status == status)
        if appointment_date:
            filter_conditions.append(Appointment.appointment_date >= appointment_date)
            
        # Add today filter
        if today:
            today_date = datetime.now().date()
            today_start = datetime.combine(today_date, time.min)
            today_end = datetime.combine(today_date, time.max)
            filter_conditions.append(Appointment.appointment_date.between(today_start, today_end))
        
        # Add recent (last 7 days) filter
        elif recent:
            today_date = datetime.now().date()
            seven_days_ago = today_date - timedelta(days=7)
            seven_days_ago_start = datetime.combine(seven_days_ago, time.min)
            today_end = datetime.combine(today_date, time.max)
            filter_conditions.append(Appointment.appointment_date.between(seven_days_ago_start, today_end))

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
                "start_time": appointment.start_time.isoformat() if appointment.start_time else None,
                "end_time": appointment.end_time.isoformat() if appointment.end_time else None,
                "checked_in_at": appointment.checked_in_at.isoformat() if appointment.checked_in_at else None,
                "checked_out_at": appointment.checked_out_at.isoformat() if appointment.checked_out_at else None,
                "status": appointment.status.value,
                "created_at": appointment.created_at.isoformat() if appointment.created_at else None,
                "updated_at": appointment.updated_at.isoformat() if appointment.updated_at else None,
                "doctor": {
                    "id": doctor.id,
                    "name": doctor.name,
                    "email": doctor.email,
                    "phone": doctor.phone,
                    "color_code": doctor.color_code
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
                .filter(ClinicalNote.appointment_id == appointment.id)
                .all()
            )

        # Get treatment plans first
        treatment_plans = (
            db.query(TreatmentPlan)
            .options(joinedload(TreatmentPlan.treatments))
            .filter(TreatmentPlan.appointment_id == appointment.id)
            .all()
        )

        # Get all treatments
        treatments = (
            db.query(Treatment)
            .filter(Treatment.appointment_id == appointment.id)
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
            .filter(Payment.appointment_id == appointment.id)
            .all()
        )

        completed_procedures = (
            db.query(CompletedProcedure)
            .filter(CompletedProcedure.appointment_id == appointment.id)
            .all()
        )

        doctor_data = None
        patient_data = None

        if doctor:
            doctor_data = {
                "id": doctor.id,
                "name": doctor.name,
                "email": doctor.email,
                "phone": doctor.phone,
                "color_code": doctor.color_code
            }

        if patient:
            patient_data = {
                "id": patient.id,
                "name": patient.name,
                "email": patient.email,
                "mobile_number": patient.mobile_number,
                "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else None,
                "gender": patient.gender.value
            }
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
            "start_time": appointment.start_time.isoformat() if appointment.start_time else None,
            "end_time": appointment.end_time.isoformat() if appointment.end_time else None,
            "checked_in_at": appointment.checked_in_at.isoformat() if appointment.checked_in_at else None,
            "checked_out_at": appointment.checked_out_at.isoformat() if appointment.checked_out_at else None,
            "status": appointment.status.value,
            "send_reminder": appointment.send_reminder,
            "remind_time_before": appointment.remind_time_before,
            "created_at": appointment.created_at.isoformat() if appointment.created_at else None,
            "updated_at": appointment.updated_at.isoformat() if appointment.updated_at else None,
            "doctor": doctor_data,
            "patient": patient_data,
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
            "completed_procedures": [{
                "id": cp.id,
                "procedure_name": cp.procedure_name,
                "unit_cost": cp.unit_cost,
                "quantity": cp.quantity,
                "amount": cp.amount,
                "procedure_description": cp.procedure_description,
                "created_at": cp.created_at.isoformat() if cp.created_at else None,
                "updated_at": cp.updated_at.isoformat() if cp.updated_at else None
            } for cp in completed_procedures],            
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
    - start_time (datetime): New start time
    - end_time (datetime): New end time
    - checked_in_at (datetime): New check-in time
    - checked_out_at (datetime): New check-out time
    - status (str): New status [SCHEDULED, CONFIRMED, CANCELLED, COMPLETED]
    - doctor_id (UUID): New doctor assignment
    - clinic_id (UUID): New clinic assignment
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

        if appointment_update.doctor_id is not None:
            doctor = db.query(User).filter(User.id == appointment_update.doctor_id).first()
            if not doctor:
                return JSONResponse(status_code=404, content={"message": "Doctor not found"})
            appointment.doctor_id = appointment_update.doctor_id
        if appointment_update.clinic_id is not None:
            clinic = db.query(Clinic).filter(Clinic.id == appointment_update.clinic_id).first()
            if not clinic:
                return JSONResponse(status_code=404, content={"message": "Clinic not found"})
            appointment.clinic_id = appointment_update.clinic_id

        # Update fields if provided
        if appointment_update.notes is not None:
            appointment.notes = appointment_update.notes
        if appointment_update.appointment_date is not None:
            appointment.appointment_date = appointment_update.appointment_date
        if appointment_update.start_time is not None:
            appointment.start_time = appointment_update.start_time
        if appointment_update.end_time is not None:
            appointment.end_time = appointment_update.end_time
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
        
        if appointment.status == AppointmentStatus.CANCELLED:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Cannot check in to cancelled appointments"})
        
        # Check if already checked in
        if appointment.status == AppointmentStatus.CHECKED_IN:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Appointment already checked in"})
        
        # Update appointment status and check-in time
        appointment.checked_in_at = datetime.now()
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
        
        if appointment.status == AppointmentStatus.CANCELLED:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Cannot check out from cancelled appointments"})
        
        # Check if already checked out
        if appointment.status == AppointmentStatus.COMPLETED:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Appointment already completed"})
        
        # Update appointment status and check-out time
        appointment.checked_out_at = datetime.now()
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
       
@appointment_router.patch("/update-appointment-status/{appointment_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Update appointment status",
    description="""
    Update the status of a specific appointment by its ID.
    
    **Path parameter:**
    - appointment_id (UUID): Appointment's unique identifier
    
    **Status Flow:**
    1. SCHEDULED → CHECKED_IN (when doctor checks in the patient)
    2. CHECKED_IN → ENGAGED (when doctor starts the appointment)
    3. ENGAGED → CHECKED_OUT (when doctor checks out the patient)
    4. CHECKED_OUT → COMPLETED (when appointment is finalized)
    
    Each status change happens with a single API call in sequence.
    """
)
async def update_appointment_status(request: Request, appointment_id: str, db: Session = Depends(get_db)):
    try:
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
    
        user_id = decoded_token.get("user_id")
        user = db.query(User).filter(User.id == user_id).first()
        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Unauthorized - doctor access required"})
        
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not appointment:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Appointment not found"})
        
        if appointment.status == AppointmentStatus.CANCELLED:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Cannot update status of cancelled appointments"})
        
        # Status transition logic
        if appointment.status == AppointmentStatus.SCHEDULED:
            # First click: Check-in the patient
            appointment.status = AppointmentStatus.CHECKED_IN
            appointment.checked_in_at = datetime.now()
            status_message = "Patient checked in successfully"

        elif appointment.status == AppointmentStatus.CHECKED_IN:
            # Second click: Start engagement
            appointment.status = AppointmentStatus.ENGAGED
            status_message = "Appointment marked as engaged"

        elif appointment.status == AppointmentStatus.ENGAGED:
            # Third click: Check-out
            appointment.status = AppointmentStatus.CHECKED_OUT
            appointment.checked_out_at = datetime.now()
            status_message = "Patient checked out successfully"

        elif appointment.status == AppointmentStatus.CHECKED_OUT:
            # Final click: Complete the appointment
            appointment.status = AppointmentStatus.COMPLETED
            status_message = "Appointment completed successfully"
            
        else:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": f"Cannot update from current status: {appointment.status.value}"})
        
        db.commit()
        db.refresh(appointment)
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": status_message,
            "appointment_id": appointment_id,
            "status": str(appointment.status.value)
        })
    
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        db.rollback()
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
        
        if appointment.status == AppointmentStatus.CANCELLED:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "Cannot add reminder for cancelled appointments"})
        
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

async def save_file(file: UploadFile):
    """Helper function to save uploaded file to disk"""
    import os
    save_dir = "uploads/appointment_files"
    os.makedirs(save_dir, exist_ok=True)
    
    # Generate unique filename to prevent overwrites
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
    file_path = os.path.join(save_dir, filename)
    
    with open(file_path, "wb") as f:
        contents = await file.read()
        f.write(contents)
    return file_path

@appointment_router.post("/add-appointment-files/{appointment_id}",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="Add file to appointment", 
    description="""
    Upload and attach a file to an existing appointment.
    
    **Path Parameter:**
    - appointment_id (UUID): Appointment's unique identifier
    
    **Request Body:**
    - files (List[File]): List of files to upload (max 10MB each)
    - remark (str, optional): Notes about the uploaded files
    
    **Authentication:**
    - Requires valid doctor Bearer token
    
    **Returns:**
    - File metadata including generated ID and path
    
    **Errors:**
    - 401: Authentication required or unauthorized access
    - 404: Appointment not found
    - 413: File too large
    - 500: Server error
    """,
    responses={
        201: {
            "description": "File successfully uploaded",
            "content": {
                "application/json": {
                    "example": {
                        "message": "File uploaded successfully"
                    }
                }
            }
        }
    }
)
async def add_file_to_appointment(
    request: Request,
    appointment_id: str,
    remark: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"message": "Authentication required"}
            )
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"message": "Unauthorized - doctor access required"}
            )
        
        # Check appointment exists
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not appointment:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"message": "Appointment not found"}
            )

        form = await request.form()
        files = form.getlist("files")
        remark = form.get("remark")

        if not files:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"message": "No files provided"}
            )
            
        # Save files and create DB records
        for file in files:
            file_path = await save_file(file)
            new_file = AppointmentFile(
                remark=remark,
                file_path=file_path,
                appointment_id=appointment_id
            )
            
            db.add(new_file)
            db.commit()
            db.refresh(new_file)

        return {
            "message": "Files uploaded successfully"
        }

    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Database error: {str(e)}"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"An unexpected error occurred: {str(e)}"}
        )
    
@appointment_router.get("/get-appointment-files/{appointment_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Get files for an appointment",
    description="""
    Retrieve all files associated with a specific appointment.

    **Path Parameter:**
    - appointment_id (UUID): Appointment's unique identifier

    **Authentication:**
    - Requires valid doctor Bearer token

    **Response:**
    ```json
    {
        "message": "Files retrieved successfully",
        "data": [
            {
                "id": "uuid",
                "remark": "Optional note about the file",
                "file_path": "path/to/file.pdf",
                "appointment_id": "uuid",
                "created_at": "2023-01-01T10:00:00",
                "updated_at": "2023-01-01T10:00:00"
            }
        ]
    }
    ```
    """)
async def get_files_for_appointment(request: Request, appointment_id: str, db: Session = Depends(get_db)):
    try:
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Unauthorized - doctor access required"})
        
        # Check appointment exists
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not appointment:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Appointment not found"})
        
        # Get files for appointment
        files = db.query(AppointmentFile).filter(AppointmentFile.appointment_id == appointment_id).order_by(AppointmentFile.created_at.desc()).all()

        files_data = []
        for file in files:
            file_data = {
                "id": file.id,
                "remark": file.remark,
                "file_path": update_image_url(file.file_path, request),
                "appointment_id": file.appointment_id,
                "created_at": file.created_at.isoformat() if file.created_at else None,
                "updated_at": file.updated_at.isoformat() if file.updated_at else None
            }
            files_data.append(file_data)
        
        return {
            "message": "Files retrieved successfully",
            "data": files_data
        }

    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"An unexpected error occurred: {str(e)}"})
    
@appointment_router.get("/search-appointment-files",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Search appointment files",
    description="""
    Search for appointment files by remark text.

    **Query Parameter:**
    - remark (str): Search text to match against file remarks

    **Authentication:**
    - Requires valid doctor Bearer token

    **Returns:**
    - List of matching appointment files
    """,
    responses={
        401: {
            "description": "Authentication required or unauthorized access",
            "content": {"application/json": {"example": {"message": "Authentication required"}}}
        },
        500: {
            "description": "Internal server error",
            "content": {"application/json": {"example": {"message": "Database error details"}}}
        }
    }
)
async def search_appointment_files(request: Request, remark: str, db: Session = Depends(get_db)):
    try:
        # Validate authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Unauthorized - doctor access required"})
        
        # Search files by remark
        files = db.query(AppointmentFile).filter(AppointmentFile.remark.ilike(f"%{remark}%")).order_by(AppointmentFile.created_at.desc()).all()

        files_data = []
        for file in files:
            file_data = {
                "id": file.id,
                "remark": file.remark,
                "file_path": update_image_url(file.file_path, request),
                "appointment_id": file.appointment_id,
                "created_at": file.created_at.isoformat() if file.created_at else None,
                "updated_at": file.updated_at.isoformat() if file.updated_at else None
            }
            files_data.append(file_data)
        

        return {
            "message": "Files found successfully",
            "data": files_data
        }

    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"An unexpected error occurred: {str(e)}"})
    
@appointment_router.patch("/update-appointment-file/{appointment_file_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Update appointment file details",
    description="""
    Update details of an existing appointment file.

    **Path Parameter:**
    - appointment_file_id (UUID): File's unique identifier

    **Request Body:**
    - remark (str, optional): Updated remark text

    **Authentication:**
    - Requires valid doctor Bearer token

    **Returns:**
    - Updated appointment file details
    """,
    responses={
        401: {
            "description": "Authentication required or unauthorized access",
            "content": {"application/json": {"example": {"message": "Authentication required"}}}
        },
        404: {
            "description": "File not found",
            "content": {"application/json": {"example": {"message": "Appointment file not found"}}}
        },
        500: {
            "description": "Internal server error",
            "content": {"application/json": {"example": {"message": "Database error details"}}}
        }
    }
)
async def update_appointment_file(request: Request, appointment_file_id: str, file_update: AppointmentFileUpdate, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Unauthorized - doctor access required"})
        
        file = db.query(AppointmentFile).filter(AppointmentFile.id == appointment_file_id).first()
        if not file:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Appointment file not found"})
        
        update_data = file_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(file, key, value)
        
        db.commit()
        db.refresh(file)

        file_data = {
            "id": file.id,
            "remark": file.remark,
            "file_path": update_image_url(file.file_path, request),
            "appointment_id": file.appointment_id,
            "created_at": file.created_at.isoformat() if file.created_at else None,
            "updated_at": file.updated_at.isoformat() if file.updated_at else None
        }
        return {
            "message": "File updated successfully",
            "data": file_data
        }

    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"An unexpected error occurred: {str(e)}"})
    
@appointment_router.delete("/delete-appointment-file/{appointment_file_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete appointment file",
    description="""
    Permanently delete an appointment file.

    **Path Parameter:**
    - appointment_file_id (UUID): File's unique identifier

    **Authentication:**
    - Requires valid doctor Bearer token

    **Returns:**
    - Success message
    """,
    responses={
        200: {
            "description": "File deleted successfully",
            "content": {"application/json": {"example": {"message": "Appointment file deleted successfully"}}}
        },
        401: {
            "description": "Authentication required or unauthorized access", 
            "content": {"application/json": {"example": {"message": "Authentication required"}}}
        },
        404: {
            "description": "File not found",
            "content": {"application/json": {"example": {"message": "Appointment file not found"}}}
        },
        500: {
            "description": "Internal server error",
            "content": {"application/json": {"example": {"message": "Database error details"}}}
        }
    }
)
async def delete_appointment_file(request: Request, appointment_file_id: str, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Authentication required"})
        
        user = db.query(User).filter(User.id == decoded_token.get("user_id")).first()
        if not user:
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "Unauthorized - doctor access required"})
        
        appointment_file = db.query(AppointmentFile).filter(AppointmentFile.id == appointment_file_id).first()
        if not appointment_file:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Appointment file not found"})
        
        db.delete(appointment_file)
        db.commit()

        return JSONResponse(status_code=status.HTTP_200_OK, content={"message": "Appointment file deleted successfully"})
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"Database error: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": f"An unexpected error occurred: {str(e)}"})