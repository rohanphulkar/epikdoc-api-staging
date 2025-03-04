from fastapi import APIRouter, Request, Depends, File, UploadFile, status
from sqlalchemy.orm import Session
from .schemas import *
from .models import *
from db.db import get_db
from auth.models import User
from fastapi.responses import JSONResponse
from utils.auth import verify_token
from sqlalchemy import insert, select, update, delete
import os
from sqlalchemy.exc import SQLAlchemyError
from PIL import Image
import io
import numpy as np
import pydicom
from datetime import datetime
from typing import Optional, List

patient_router = APIRouter()

def calculate_age(date_of_birth: datetime) -> str:
    if not date_of_birth:
        return None
    today = datetime.today()
    age = today.year - date_of_birth.year
    return str(age)

@patient_router.post(
    "/create", 
    status_code=status.HTTP_201_CREATED,
    response_description="Patient created successfully",
    responses={
        201: {"description": "Patient created successfully"},
        400: {"description": "Invalid request data or database error"},
        401: {"description": "Unauthorized access"},
        500: {"description": "Internal server error"}
    }
)
async def create_patient(
    request: Request, 
    patient: PatientCreateSchema, 
    db: Session = Depends(get_db)
):
    try:
        # Verify user authentication
        decoded_token = verify_token(request)
        user = db.execute(select(User).filter(User.id == decoded_token.get("id"))).scalar_one_or_none()
        if not user:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                content={"message": "Unauthorized"}
            )
        
        # calculate age
        age = calculate_age(patient.date_of_birth)
        
        # Create new patient record
        new_patient = Patient(
            doctor_id=user.id,
            name=patient.name,
            mobile_number=patient.mobile_number,
            gender=patient.gender,
            email=patient.email,
            date_of_birth=patient.date_of_birth,
            age=age
        )

        # Save to database
        db.add(new_patient)
        db.commit()
        db.refresh(new_patient)
        
        return {
            "message": "Patient created successfully",
            "patient_id": new_patient.id
        }
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST, 
            content={"message": f"Database error: {str(e)}"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )

@patient_router.get(
    "/get-all",
    status_code=status.HTTP_200_OK,
    response_description="All patients retrieved successfully",
    responses={
        200: {"description": "All patients retrieved successfully"},
        401: {"description": "Unauthorized access"},
        500: {"description": "Internal server error"}
    }
)
async def get_all_patients(
    request: Request,
    db: Session = Depends(get_db)
):
    try:
        # Verify user authentication
        decoded_token = verify_token(request)
        
        # Get all patients for the authenticated doctor
        patients = db.execute(
            select(Patient).filter(Patient.doctor_id == decoded_token.get("id"))
        ).scalars().all()
        
        return patients
    except SQLAlchemyError as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )

@patient_router.get(
    "/get-by-id/{patient_id}",
    status_code=status.HTTP_200_OK,
    response_description="Patient retrieved successfully",
    responses={
        200: {"description": "Patient retrieved successfully"},
        401: {"description": "Unauthorized access"},
        404: {"description": "Patient not found"},
        500: {"description": "Internal server error"}
    }
)
async def get_patient_by_id(
    patient_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    try:
        # Verify user authentication
        decoded_token = verify_token(request)
        
        # Get patient by ID
        patient = db.execute(
            select(Patient).filter(
                Patient.id == patient_id,
                Patient.doctor_id == decoded_token.get("id")
            )
        ).scalar_one_or_none()

        if not patient:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"message": "Patient not found"}
            )

        patient_data = {
            "id": patient.id,
            "doctor_id": patient.doctor_id,
            "patient_number": patient.patient_number,
            "name": patient.name,
            "mobile_number": patient.mobile_number,
            "contact_number": patient.contact_number,
            "email": patient.email,
            "secondary_mobile": patient.secondary_mobile,
            "gender": patient.gender,
            "address": patient.address,
            "locality": patient.locality,
            "city": patient.city,
            "pincode": patient.pincode,
            "national_id": patient.national_id,
            "date_of_birth": patient.date_of_birth,
            "age": patient.age,
            "anniversary_date": patient.anniversary_date,
            "blood_group": patient.blood_group,
            "remarks": patient.remarks,
            "medical_history": patient.medical_history,
            "referred_by": patient.referred_by,
            "groups": patient.groups,
            "patient_notes": patient.patient_notes,
            "created_at": patient.created_at,
            "treatments": patient.treatments,
            "clinical_notes": patient.clinical_notes,
            "treatment_plans": patient.treatment_plans,
            "medical_records": patient.medical_records
        }

        return patient_data
        
    except SQLAlchemyError as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )

@patient_router.get("/search", status_code=status.HTTP_200_OK, response_description="Search patients by name, mobile, ID, email, gender and age range", responses={
    200: {"description": "Returns list of matching patients"},
    401: {"description": "Unauthorized - Invalid or missing authentication token"},
    500: {"description": "Internal server error - Database or server-side error"}
})
async def search_patients(
    request: Request,
    search_query: Optional[str] = None,
    gender: Optional[Gender] = None,
    min_age: Optional[int] = None,
    max_age: Optional[int] = None,
    db: Session = Depends(get_db)
):
    try:
        # Verify user authentication
        decoded_token = verify_token(request)
        
        # Base query
        query = select(Patient).filter(Patient.doctor_id == decoded_token.get("id"))
        
        # Add search filters if search_query provided
        if search_query:
            from sqlalchemy import or_
            query = query.filter(
                or_(
                    Patient.name.ilike(f"%{search_query}%"),
                    Patient.mobile_number.ilike(f"%{search_query}%"),
                    Patient.id.ilike(f"%{search_query}%"),
                    Patient.email.ilike(f"%{search_query}%")
                )
            )
            
        # Add gender filter if provided
        if gender:
            query = query.filter(Patient.gender == gender)
            
        # Add age filter if provided
        if min_age:
            from sqlalchemy import cast, Integer
            query = query.filter(cast(Patient.age, Integer) >= min_age)
        if max_age:
            from sqlalchemy import cast, Integer
            query = query.filter(cast(Patient.age, Integer) <= max_age)
            
        # Execute query
        patients = db.execute(query).scalars().all()
        
        return patients
        
    except SQLAlchemyError as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )

@patient_router.patch(
    "/update/{patient_id}",
    status_code=status.HTTP_200_OK,
    response_description="Updates an existing patient's information",
    responses={
        200: {
            "description": "Patient updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Patient updated successfully",
                        "patient": {
                            "id": "uuid",
                            "name": "John Doe",
                            "email": "john@example.com",
                            "mobile_number": "+1234567890",
                            "gender": "male",
                            "age": "45"
                        }
                    }
                }
            }
        },
        400: {
            "description": "Invalid request data or database error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error: [error details]"}
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid or missing authentication token",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "Patient with specified ID not found or does not belong to authenticated doctor",
            "content": {
                "application/json": {
                    "example": {"message": "Patient not found"}
                }
            }
        },
        500: {
            "description": "Internal server error occurred while processing request",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error: [error details]"}
                }
            }
        }
    }
)
async def update_patient(
    request: Request,
    patient_id: str,
    patient_update: PatientUpdateSchema,
    db: Session = Depends(get_db)
):
    try:
        # Verify user authentication
        decoded_token = verify_token(request)
        
        # Get patient
        patient = db.execute(
            select(Patient).filter(
                Patient.id == patient_id,
                Patient.doctor_id == decoded_token.get("id")
            )
        ).scalar_one_or_none()
        
        if not patient:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"message": "Patient not found"}
            )

        # Update patient fields
        update_data = patient_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(patient, field, value)
            
        # Update age if date_of_birth is updated
        if 'date_of_birth' in update_data and patient.date_of_birth is not None:
            patient.age = calculate_age(patient.date_of_birth)

        db.commit()
        db.refresh(patient)
        
        return {
            "message": "Patient updated successfully",
            "patient": patient
        }
        
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"message": f"Database error: {str(e)}"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )

@patient_router.delete(
    "/delete/{patient_id}",
    status_code=status.HTTP_200_OK,
    response_description="Delete a patient record from the system",
    responses={
        200: {
            "description": "Patient deleted successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Patient deleted successfully"
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized access - Invalid or missing authentication token",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Invalid or expired token"
                    }
                }
            }
        },
        404: {
            "description": "Patient not found - No patient exists with the provided ID for the authenticated doctor",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Patient not found"
                    }
                }
            }
        },
        500: {
            "description": "Internal server error - Database error or unexpected server error",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Internal server error: error details"
                    }
                }
            }
        }
    }
)
async def delete_patient(
    request: Request,
    patient_id: str,
    db: Session = Depends(get_db)
):
    try:
        # Verify user authentication
        decoded_token = verify_token(request)
        
        # Get patient
        patient = db.execute(
            select(Patient).filter(
                Patient.id == patient_id,
                Patient.doctor_id == decoded_token.get("id")
            )
        ).scalar_one_or_none()
        
        if not patient:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"message": "Patient not found"}
            )

        # Delete patient
        db.delete(patient)
        db.commit()
        
        return {
            "message": "Patient deleted successfully"
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
            content={"message": f"Internal server error: {str(e)}"}
        )

@patient_router.post(
    "/create-medical-record",
    status_code=status.HTTP_201_CREATED,
    response_description="Create a new medical record for a patient with treatments, medicines and attachments",
    responses={
        201: {
            "description": "Medical record created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Medical record created successfully",
                        "medical_record_id": "550e8400-e29b-41d4-a716-446655440000",
                    }
                }
            }
        },
        400: {
            "description": "Invalid request data or validation error",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Invalid request data",
                        "detail": "Required field 'complaint' is missing"
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid or missing authentication token",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized access - Please login"}
                }
            }
        },
        404: {
            "description": "Patient not found or no access to patient record",
            "content": {
                "application/json": {
                    "example": {"message": "Patient with ID not found or access denied"}
                }
            }
        },
        500: {
            "description": "Internal server error during processing",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Internal server error",
                        "detail": "Error processing file upload"
                    }
                }
            }
        }
    }
)
async def create_medical_record(
    request: Request,
    patient_id: str,
    medical_record: MedicalRecordCreateSchema,
    files: Optional[List[UploadFile]] = File(None),
    db: Session = Depends(get_db)
):
    """
    Create a new medical record for a patient with optional file attachments.
    
    Args:
        request: The HTTP request containing medical record data
        patient_id: ID of the patient
        medical_record: Medical record data schema
        files: Optional list of files to attach
        db: Database session
        
    Returns:
        JSON response with success/error message
    """
    try:
        # Verify user authentication
        decoded_token = verify_token(request)
        
        # Get patient
        patient = db.execute(
            select(Patient).filter(
                Patient.id == patient_id,
                Patient.doctor_id == decoded_token.get("id")
            )
        ).scalar_one_or_none()
        
        if not patient:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"message": "Patient not found"}
            )

        # Create medical record
        medical_record_db = MedicalRecord(
            patient_id=patient_id,
            complaint=medical_record.complaint,
            diagnosis=medical_record.diagnosis,
            vital_signs=medical_record.vital_signs
        )

        # Save to database
        db.add(medical_record_db)
        db.commit()
        db.refresh(medical_record_db)
        
        # Handle attachments
        attachments = []
        if files:
            for file in files:
                file_content = await file.read()
                # Create uploads directory if it doesn't exist
                os.makedirs("uploads/medical_records", exist_ok=True)
                
                # Generate unique filename
                file_ext = os.path.splitext(str(file.filename))[1]
                unique_filename = f"{generate_uuid()}{file_ext}"
                file_path = f"uploads/medical_records/{unique_filename}"
                
                with open(file_path, "wb") as f:
                    f.write(file_content)

                attachment = MedicalRecordAttachment(
                    medical_record_id=medical_record_db.id,
                    attachment=file_path,
                )
                attachments.append(attachment)

            # Save attachments
            db.add_all(attachments)
            db.commit()
        
        # Add medical record treatments
        if medical_record.treatments:
            for treatment in medical_record.treatments:
                medical_record_treatment = MedicalRecordTreatment(
                    medical_record_id=medical_record_db.id,
                    name=treatment.name,
                    )
                db.add(medical_record_treatment)

        # Add medicines
        if medical_record.medicines:
            for medicine in medical_record.medicines:
                medicine_amount = medicine.price * medicine.quantity
                medical_record_medicine = Medicine(
                    medical_record_id=medical_record_db.id,
                    item_name=medicine.name,
                    quantity=medicine.quantity,
                    price=medicine.price,
                    amount=medicine_amount,
                    dosage=medicine.dosage,
                    instructions=medicine.instructions
                )
                db.add(medical_record_medicine)

        db.commit()
        
        return {
            "message": "Medical record created successfully",
            "medical_record_id": medical_record_db.id
        }
        
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"message": f"Database error: {str(e)}"}
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": f"Internal server error: {str(e)}"}
        )