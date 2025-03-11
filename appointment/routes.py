from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from .schemas import AppointmentCreate, AppointmentUpdate, AppointmentResponse
from .models import Appointment, AppointmentStatus
from db.db import get_db
from auth.models import User
from patient.models import Patient
from utils.auth import verify_token
from utils.appointment_msg import send_appointment_email
from sqlalchemy.orm import joinedload
from datetime import datetime, timedelta
from sqlalchemy import or_, and_
from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler
scheduler = BackgroundScheduler()
scheduler.start()

appointment_router = APIRouter()

@appointment_router.post("/create",
    response_model=dict,
    status_code=201,
    summary="Create new appointment",
    description="""
    Create a new appointment for a patient.
    
    Required parameters:
    - patient_id: ID of the patient
    - notes: Notes for the appointment
    - appointment_date: Date of appointment
    - checked_in_at: Check-in time
    - checked_out_at: Check-out time
    - status: Status of the appointment (SCHEDULED, CONFIRMED, CANCELLED, COMPLETED)
    - share_on_email: Whether to share appointment details via email
    - share_on_sms: Whether to share appointment details via SMS
    - share_on_whatsapp: Whether to share appointment details via WhatsApp
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        201: {"description": "Appointment created successfully"},
        401: {"description": "Unauthorized - Invalid token or non-doctor user"},
        404: {"description": "Patient not found"},
        500: {"description": "Internal server error"}
    }
)
async def create_appointment(request: Request, appointment: AppointmentCreate, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)

        user_id = decoded_token.get("user_id") if decoded_token else None
        
        user = db.query(User).filter(User.id == user_id).first()

        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        patient = db.query(Patient).filter(Patient.id == appointment.patient_id).first()

        if not patient:
            return JSONResponse(status_code=404, content={"message": "Patient not found"})
        
        new_appointment = Appointment(
            patient_id=appointment.patient_id,
            doctor_id=user.id,
            patient_number=patient.patient_number if patient.patient_number else "",
            patient_name=patient.name,
            doctor_name=user.name,
            notes=appointment.notes,
            appointment_date=appointment.appointment_date,
            checked_in_at=appointment.checked_in_at,
            checked_out_at=appointment.checked_out_at,
            status=appointment.status,
            share_on_email=appointment.share_on_email,
            share_on_sms=appointment.share_on_sms,
            share_on_whatsapp=appointment.share_on_whatsapp
        )

        db.add(new_appointment)
        db.commit()
        db.refresh(new_appointment)

        reminder_time = new_appointment.appointment_date - timedelta(hours=1, minutes=15)
        scheduler.add_job(send_appointment_email, 'date', run_date=reminder_time, args=[db, new_appointment.id])

        if new_appointment.share_on_email:
            await send_appointment_email(db, new_appointment.id)

        return JSONResponse(status_code=201, content={"message": "Appointment created successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@appointment_router.get("/all",
    response_model=dict,
    status_code=200,
    summary="Get all appointments",
    description="""
    Get all appointments for a doctor.
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "Appointments retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token or non-doctor user"},
        500: {"description": "Internal server error"}
    }
)
async def get_all_appointments(request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)

        user_id = decoded_token.get("user_id") if decoded_token else None
        
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})

        appointments = (
            db.query(Appointment, Patient, User)
            .join(Patient, Appointment.patient_id == Patient.id)
            .join(User, Appointment.doctor_id == User.id)
            .filter(Appointment.doctor_id == user.id)
            .all()
        )

        appointment_list = []
        for appointment, patient, doctor in appointments:
            appointment_data = {
                "id": appointment.id,
                "patient_id": appointment.patient_id,
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
        
        return JSONResponse(status_code=200, content={"appointments": appointment_list})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@appointment_router.get("/patient-appointments/{patient_id}",
    response_model=dict,
    status_code=200,
    summary="Get all appointments for a patient",
    description="""
    Get all appointments for a patient.
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "Appointments retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token or non-doctor user"},
        404: {"description": "Patient not found"},
        500: {"description": "Internal server error"}
    }
)
async def get_patient_appointments(request: Request, patient_id: str, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        user_id = decoded_token.get("user_id") if decoded_token else None
        
        user = db.query(User).filter(User.id == user_id).first()

        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})

        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return JSONResponse(status_code=404, content={"message": "Patient not found"})
        
        appointments = db.query(Appointment).filter(Appointment.patient_id == patient.id).all()
        
        appointment_list = []
        for appointment in appointments:
            appointment_data = {
                "id": appointment.id,
                "patient_id": appointment.patient_id,
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
            }
            appointment_list.append(appointment_data)

        return JSONResponse(status_code=200, content={"appointments": appointment_list})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@appointment_router.get("/search",
    response_model=dict,
    status_code=200,
    summary="Search and filter appointments",
    description="""
    Search appointments with search terms and/or filters. Both are optional and independent.
    
    Search parameters (optional):
    - patient_name: Patient's name
    - patient_email: Patient's email
    - patient_phone: Patient's phone
    - doctor_name: Doctor's name  
    - doctor_email: Doctor's email
    - doctor_phone: Doctor's phone
    
    Filter parameters (optional):
    - patient_gender: Patient's gender
    - status: Appointment status (SCHEDULED, CONFIRMED, CANCELLED, COMPLETED)
    - appointment_date: Appointment date (ISO format)
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "Search results retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token or non-doctor user"},
        500: {"description": "Internal server error"}
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
    status: Optional[str] = None,
    appointment_date: Optional[datetime] = None,
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

        search_filters = []
        if patient_name:
            search_filters.append(or_(
                Patient.name.ilike(f"%{patient_name}%"),
            ))
        if patient_email:
            search_filters.append(Patient.email.ilike(f"%{patient_email}%"))
        if patient_phone:
            search_filters.append(Patient.phone.ilike(f"%{patient_phone}%"))
        if doctor_name:
            search_filters.append(User.name.ilike(f"%{doctor_name}%"))
        if doctor_email:
            search_filters.append(User.email.ilike(f"%{doctor_email}%"))
        if doctor_phone:
            search_filters.append(User.phone.ilike(f"%{doctor_phone}%"))

        filter_conditions = []
        if patient_gender:
            filter_conditions.append(Patient.gender == patient_gender)
        if status:
            filter_conditions.append(Appointment.status == status)
        if appointment_date:
            filter_conditions.append(Appointment.appointment_date >= appointment_date)

        if search_filters:
            query = query.filter(or_(*search_filters))
        if filter_conditions:
            query = query.filter(and_(*filter_conditions))

        appointments = query.all()

        appointment_list = []
        for appointment, patient, doctor in appointments:
            appointment_data = {
                "id": appointment.id,
                "patient_id": appointment.patient_id,
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

        return JSONResponse(status_code=200, content={"appointments": appointment_list})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@appointment_router.get("/details/{appointment_id}",
    response_model=dict,
    status_code=200,
    summary="Get appointment details",
    description="""
    Get details of a specific appointment by ID.
    
    Required parameters:
    - appointment_id: ID of the appointment
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "Appointment details retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token or non-doctor user"},
        404: {"description": "Appointment not found"},
        500: {"description": "Internal server error"}
    }
)
async def get_appointment_details(request: Request, appointment_id: str, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        user_id = decoded_token.get("user_id") if decoded_token else None
    
        user = db.query(User).filter(User.id == user_id).first()
        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
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
        
        appointment_data = {
                "id": appointment.id,
                "patient_id": appointment.patient_id,
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

        return JSONResponse(status_code=200, content={"appointment": appointment_data})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@appointment_router.patch("/update/{appointment_id}",
    response_model=dict,
    status_code=200,
    summary="Update appointment details",
    description="""
    Update details of a specific appointment by ID.

    Required parameters:
    - appointment_id: ID of the appointment
    - notes: Notes for the appointment (optional)
    - appointment_date: Date of appointment (optional)
    - checked_in_at: Check-in time (optional)
    - checked_out_at: Check-out time (optional)
    - status: Status of the appointment (optional)
    - share_on_email: Whether to share via email (optional)
    - share_on_sms: Whether to share via SMS (optional)
    - share_on_whatsapp: Whether to share via WhatsApp (optional)
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "Appointment updated successfully"},
        401: {"description": "Unauthorized - Invalid token or non-doctor user"},
        404: {"description": "Appointment not found"},
        500: {"description": "Internal server error"}
    }
)
async def update_appointment(request: Request, appointment_id: str, appointment_update: AppointmentUpdate, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        user_id = decoded_token.get("user_id") if decoded_token else None
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user or str(user.user_type) != "doctor":
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        
        if not appointment:
            return JSONResponse(status_code=404, content={"message": "Appointment not found"})
        
        if appointment_update.notes is not None:
            appointment.notes = appointment_update.notes
        if appointment_update.appointment_date is not None:
            appointment.appointment_date = appointment_update.appointment_date
        if appointment_update.checked_in_at is not None:
            appointment.checked_in_at = appointment_update.checked_in_at
        if appointment_update.checked_out_at is not None:
            appointment.checked_out_at = appointment_update.checked_out_at
        if appointment_update.status is not None:
            appointment.status = appointment_update.status
        if appointment_update.share_on_email is not None:
            appointment.share_on_email = appointment_update.share_on_email
        if appointment_update.share_on_sms is not None:
            appointment.share_on_sms = appointment_update.share_on_sms
        if appointment_update.share_on_whatsapp is not None:
            appointment.share_on_whatsapp = appointment_update.share_on_whatsapp
        
        db.commit()
        db.refresh(appointment)
        
        return JSONResponse(status_code=200, content={"message": "Appointment updated successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@appointment_router.delete("/delete/{appointment_id}",
    response_model=dict,
    status_code=200,
    summary="Delete appointment",
    description="""
    Delete a specific appointment by ID.
    
    Required parameters:
    - appointment_id: ID of the appointment

    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "Appointment deleted successfully"},
        401: {"description": "Unauthorized - Invalid token or non-doctor user"},
        404: {"description": "Appointment not found"},
        500: {"description": "Internal server error"}
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