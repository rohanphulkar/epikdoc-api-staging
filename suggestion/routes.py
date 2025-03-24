from fastapi import APIRouter, Request, Depends, File, UploadFile, status, Form, Query
from sqlalchemy.orm import Session
from .schemas import *
from .models import *
from patient.models import Patient
from db.db import get_db
from auth.models import User
from fastapi.responses import JSONResponse
from utils.auth import verify_token
from sqlalchemy import  func, asc, desc
import os
from sqlalchemy.exc import SQLAlchemyError
from PIL import Image
import io
import numpy as np
import json
from datetime import datetime
from typing import Optional, List, Dict
from appointment.models import Appointment
from math import ceil

suggestion_router = APIRouter()

@suggestion_router.post("/add-treatment-suggestion",response_model=Dict[str, str],
    status_code=status.HTTP_201_CREATED,
    summary="Add a new treatment suggestion",
    description="This endpoint allows authenticated users to add a new treatment suggestion to the system.",
    responses={
        201: {
            "description": "Treatment suggestion added successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Treatment suggestion added successfully",
                        "treatment_suggestion_id": 1
                    }
                }
            }
        },
        400: {
            "description": "Bad Request - Treatment suggestion already exists",
            "content": {
                "application/json": {
                    "example": {"message": "A treatment suggestion with the same name already exists"}
                }
            }
        },
        401: {
            "description": "Unauthorized - Authentication required or invalid token",
            "content": {
                "application/json": {
                    "example": {"message": "Authentication required"}
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    })
async def add_treatment_suggestion(request: Request, treatment_suggestion: TreatmentNameSuggestionSchema, db: Session = Depends(get_db)):
    try:
        existing_treatment_suggestion = db.query(TreatmentNameSuggestion).filter(TreatmentNameSuggestion.treatment_name == treatment_suggestion.treatment_name).first()
        if existing_treatment_suggestion:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "A treatment suggestion with the same name already exists"})
        treatment_suggestion = TreatmentNameSuggestion(
            treatment_name=treatment_suggestion.treatment_name,
        )
        db.add(treatment_suggestion)
        db.commit()
        db.refresh(treatment_suggestion)  # Refresh the treatment_suggestion with the latest ID from the database

        return JSONResponse(status_code=status.HTTP_201_CREATED, content={
            "message": "Treatment suggestion added successfully",
            "treatment_suggestion_id": treatment_suggestion.id
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@suggestion_router.get("/get-treatment-suggestions", response_model=Dict[str, List[Dict[str, str]]],
    summary="Retrieve all treatment suggestions",
    description="This endpoint retrieves a list of all available treatment suggestions.",
    responses={
        200: {
            "description": "List of treatment suggestions retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Treatment suggestions retrieved successfully",
                        "treatment_suggestions": [
                            {"id": 1, "treatment_name": "Physical Therapy"},
                            {"id": 2, "treatment_name": "Medication"}
                        ]
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized - Authentication required",
            "content": {
                "application/json": {
                    "example": {"message": "Authentication required"}
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    })
async def get_treatment_suggestions(request: Request, db: Session = Depends(get_db)):
    try:        
        treatment_suggestions = db.query(TreatmentNameSuggestion).order_by(TreatmentNameSuggestion.created_at.desc()).all()

        treatment_suggestions_list = []

        for treatment_suggestion in treatment_suggestions:
            treatment_suggestions_list.append({
                "id": treatment_suggestion.id,
                "treatment_name": treatment_suggestion.treatment_name
            })
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Treatment suggestions retrieved successfully",
            "treatment_suggestions": treatment_suggestions_list
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@suggestion_router.get("/search-treatment-suggestion", response_model=Dict[str, List[Dict[str, str]]],
    summary="Search treatment suggestions",
    description="Search for treatment suggestions by name using a query string.",
    responses={
        200: {
            "description": "Search results retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Treatment suggestions retrieved successfully",
                        "treatment_suggestions": [
                            {"id": 1, "treatment_name": "Physical Therapy"},
                            {"id": 2, "treatment_name": "Physiotherapy"}
                        ]
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized - Authentication required",
            "content": {
                "application/json": {
                    "example": {"message": "Authentication required"}
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    })
async def search_treatment_suggestion(request: Request, query: str, db: Session = Depends(get_db)):
    try:        
        treatment_suggestions = db.query(TreatmentNameSuggestion).filter(TreatmentNameSuggestion.treatment_name.ilike(f"%{query}%")).order_by(TreatmentNameSuggestion.treatment_name.asc()).all()

        treatment_suggestions_list = []

        for treatment_suggestion in treatment_suggestions:
            treatment_suggestions_list.append({
                "id": treatment_suggestion.id,
                "treatment_name": treatment_suggestion.treatment_name
            })
        
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Treatment suggestions retrieved successfully",
            "treatment_suggestions": treatment_suggestions_list
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    
@suggestion_router.patch("/update-treatment-suggestion/{treatment_suggestion_id}", response_model=Dict[str, str],
    summary="Update a treatment suggestion",
    description="Modify the name of an existing treatment suggestion.",
    responses={
        200: {
            "description": "Treatment suggestion updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Treatment suggestion updated successfully",
                        "treatment_suggestion": {
                            "id": 1,
                            "treatment_name": "Updated Treatment Name"
                        }
                    }
                }
            }
        },
        404: {
            "description": "Treatment suggestion not found",
            "content": {
                "application/json": {
                    "example": {"message": "Treatment suggestion not found"}
                }
            }
        },
        401: {
            "description": "Unauthorized - Authentication required",
            "content": {
                "application/json": {
                    "example": {"message": "Authentication required"}
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    })
async def update_treatment_suggestion(treatment_suggestion_id: str, request: Request, treatment_suggestion_update: TreatmentNameSuggestionSchema, db: Session = Depends(get_db)):
    try:        
        existing_treatment_suggestion = db.query(TreatmentNameSuggestion).filter(TreatmentNameSuggestion.id == treatment_suggestion_id).first()
        if not existing_treatment_suggestion:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Treatment suggestion not found"})
        
        existing_treatment_suggestion.treatment_name = treatment_suggestion_update.treatment_name
        db.commit()
        db.refresh(existing_treatment_suggestion)  # Refresh the existing_treatment_suggestion with the latest data from the database
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Treatment suggestion updated successfully",
            "treatment_suggestion": existing_treatment_suggestion
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    
@suggestion_router.delete("/delete-treatment-suggestion/{treatment_suggestion_id}", response_model=Dict[str, str],
    summary="Delete a treatment suggestion",
    description="Remove a treatment suggestion by its ID.",
    responses={
        200: {
            "description": "Treatment suggestion deleted successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Treatment suggestion deleted successfully"}
                }
            }
        },
        404: {
            "description": "Treatment suggestion not found",
            "content": {
                "application/json": {
                    "example": {"message": "Treatment suggestion not found"}
                }
            }
        },
        401: {
            "description": "Unauthorized - Authentication required",
            "content": {
                "application/json": {
                    "example": {"message": "Authentication required"}
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    })
async def delete_treatment_suggestion(treatment_suggestion_id: str, request: Request, db: Session = Depends(get_db)):
    try:        
        existing_treatment_suggestion = db.query(TreatmentNameSuggestion).filter(TreatmentNameSuggestion.id == treatment_suggestion_id).first()
        if not existing_treatment_suggestion:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Treatment suggestion not found"})
        
        db.delete(existing_treatment_suggestion)
        db.commit()
        return JSONResponse(status_code=status.HTTP_200_OK, content={"message": "Treatment suggestion deleted successfully"})
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    
@suggestion_router.post("/add-complaint-suggestion",
    response_model=Dict[str, str],
    status_code=status.HTTP_201_CREATED,
    summary="Add a new complaint suggestion",
    description="Add a new complaint suggestion to the system.",
    responses={
        201: {
            "description": "Complaint suggestion added successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Complaint suggestion added successfully",
                        "complaint_suggestion": {
                            "id": 1,
                            "complaint": "Headache"
                        }
                    }
                }
            }
        },
        409: {
            "description": "Conflict - Complaint suggestion already exists",
            "content": {
                "application/json": {
                    "example": {"message": "Complaint suggestion already exists"}
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    })
async def add_complaint_suggestion(complaint_suggestion: ComplaintSuggestionSchema, db: Session = Depends(get_db)):
    try:
        existing_suggestion = db.query(ComplaintSuggestion).filter(ComplaintSuggestion.complaint == complaint_suggestion.complaint).first()
        if existing_suggestion:
            return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"message": "Complaint suggestion already exists"})
        
        new_suggestion = ComplaintSuggestion(complaint=complaint_suggestion.complaint)
        db.add(new_suggestion)
        db.commit()
        db.refresh(new_suggestion)  # Refresh the new_suggestion with the latest data from the database
        return JSONResponse(status_code=status.HTTP_201_CREATED, content={
            "message": "Complaint suggestion added successfully",
            "complaint_suggestion": new_suggestion
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@suggestion_router.get("/get-complaint-suggestions",
    response_model=Dict[str, List[Dict[str, str]]],
    summary="Get all complaint suggestions",
    description="Retrieve a list of all complaint suggestions.",
    responses={
        200: {
            "description": "Complaint suggestions retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Complaint suggestions retrieved successfully",
                        "complaint_suggestions": [
                            {
                                "id": 1,
                                "complaint": "Headache",
                                "created_at": "2023-01-01T00:00:00"
                            }
                        ]
                    }
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    })
async def get_complaint_suggestions(request: Request, db: Session = Depends(get_db)):
    try:        
        complaint_suggestions = db.query(ComplaintSuggestion).order_by(ComplaintSuggestion.created_at.desc()).all()
        complaint_suggestions_list = []
        for suggestion in complaint_suggestions:
            complaint_suggestions_list.append({
                "id": suggestion.id,
                "complaint": suggestion.complaint,
                "created_at": suggestion.created_at
            })
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Complaint suggestions retrieved successfully",
            "complaint_suggestions": complaint_suggestions_list
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    
@suggestion_router.get("/search-complaint-suggestion", response_model=Dict[str, List[Dict[str, str]]],
    summary="Search complaint suggestions",
    description="Search for complaint suggestions by complaint using a query string.",
    responses={
        200: {
            "description": "Search results retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Complaint suggestions retrieved successfully",
                        "complaint_suggestions": [
                            {
                                "id": 1,
                                "complaint": "Headache",
                                "created_at": "2023-01-01T00:00:00"
                            }
                        ]
                    }
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    }
)
async def search_complaint_suggestion(request: Request, query: str, db: Session = Depends(get_db)):
    try:        
        complaint_suggestions = db.query(ComplaintSuggestion).filter(ComplaintSuggestion.complaint.ilike(f"%{query}%")).order_by(ComplaintSuggestion.complaint.asc()).all()
        complaint_suggestions_list = []
        for suggestion in complaint_suggestions:
            complaint_suggestions_list.append({
                "id": suggestion.id,
                "complaint": suggestion.complaint,
                "created_at": suggestion.created_at
            })
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Complaint suggestions retrieved successfully",
            "complaint_suggestions": complaint_suggestions_list
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    
@suggestion_router.patch("/update-complaint-suggestion/{complaint_suggestion_id}", response_model=Dict[str, str],
    summary="Update a complaint suggestion",
    description="Modify the complaint of an existing complaint suggestion.",
    responses={
        200: {
            "description": "Complaint suggestion updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Complaint suggestion updated successfully",
                        "complaint_suggestion": {
                            "id": 1,
                            "complaint": "Updated Complaint"
                        }
                    }
                }
            }
        },
        404: {
            "description": "Complaint suggestion not found",
            "content": {
                "application/json": {
                    "example": {"message": "Complaint suggestion not found"}
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    }
)
async def update_complaint_suggestion(complaint_suggestion_id: str, request: Request, complaint_suggestion_update: ComplaintSuggestionSchema, db: Session = Depends(get_db)):
    try:        
        existing_suggestion = db.query(ComplaintSuggestion).filter(ComplaintSuggestion.id == complaint_suggestion_id).first()
        if not existing_suggestion:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Complaint suggestion not found"})
        
        existing_suggestion.complaint = complaint_suggestion_update.complaint
        db.commit()
        db.refresh(existing_suggestion)  # Refresh the existing_suggestion with the latest data from the database
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Complaint suggestion updated successfully",
            "complaint_suggestion": existing_suggestion
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    
@suggestion_router.delete("/delete-complaint-suggestion/{complaint_suggestion_id}", response_model=Dict[str, str],
    summary="Delete a complaint suggestion",
    description="Remove a complaint suggestion by its ID.",
    responses={
        200: {
            "description": "Complaint suggestion deleted successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Complaint suggestion deleted successfully"}
                }
            }
        },
        404: {
            "description": "Complaint suggestion not found",
            "content": {
                "application/json": {
                    "example": {"message": "Complaint suggestion not found"}
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    }
)
async def delete_complaint_suggestion(complaint_suggestion_id: str, request: Request, db: Session = Depends(get_db)):
    try:        
        existing_suggestion = db.query(ComplaintSuggestion).filter(ComplaintSuggestion.id == complaint_suggestion_id).first()
        if not existing_suggestion:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Complaint suggestion not found"})
        
        db.delete(existing_suggestion)
        db.commit()
        return JSONResponse(status_code=status.HTTP_200_OK, content={"message": "Complaint suggestion deleted successfully"})
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    
@suggestion_router.post("/add-diagnosis-suggestion",
    response_model=Dict[str, str],
    status_code=status.HTTP_201_CREATED,
    summary="Add a new diagnosis suggestion",
    description="Add a new diagnosis suggestion to the system.",
    responses={
        201: {
            "description": "Diagnosis suggestion added successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Diagnosis suggestion added successfully",
                        "diagnosis_suggestion": {
                            "id": 1,
                            "diagnosis": "Migraine"
                        }
                    }
                }
            }
        },
        409: {
            "description": "Conflict - Diagnosis suggestion already exists",
            "content": {
                "application/json": {
                    "example": {"message": "Diagnosis suggestion already exists"}
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    })
async def add_diagnosis_suggestion(diagnosis_suggestion: DiagnosisSuggestionSchema, db: Session = Depends(get_db)):
    try:
        existing_suggestion = db.query(DiagnosisSuggestion).filter(DiagnosisSuggestion.diagnosis == diagnosis_suggestion.diagnosis).first()
        if existing_suggestion:
            return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"message": "Diagnosis suggestion already exists"})
        
        new_suggestion = DiagnosisSuggestion(diagnosis=diagnosis_suggestion.diagnosis)
        db.add(new_suggestion)
        db.commit()
        db.refresh(new_suggestion)  # Refresh the new_suggestion with the latest data from the database
        return JSONResponse(status_code=status.HTTP_201_CREATED, content={
            "message": "Diagnosis suggestion added successfully",
            "diagnosis_suggestion": new_suggestion
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    
@suggestion_router.get("/get-diagnosis-suggestions",
    response_model=Dict[str, List[Dict[str, str]]],
    summary="Get all diagnosis suggestions",
    description="Retrieve a list of all diagnosis suggestions.",
    responses={
        200: {
            "description": "Diagnosis suggestions retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Diagnosis suggestions retrieved successfully",
                        "diagnosis_suggestions": [
                            {
                                "id": 1,
                                "diagnosis": "Migraine",
                                "created_at": "2023-01-01T00:00:00"
                            }
                        ]
                    }
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    })
async def get_diagnosis_suggestions(request: Request, db: Session = Depends(get_db)):
    try:        
        diagnosis_suggestions = db.query(DiagnosisSuggestion).order_by(DiagnosisSuggestion.created_at.desc()).all()
        diagnosis_suggestions_list = []
        for suggestion in diagnosis_suggestions:
            diagnosis_suggestions_list.append({
                "id": suggestion.id,
                "diagnosis": suggestion.diagnosis,
                "created_at": suggestion.created_at
            })
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Diagnosis suggestions retrieved successfully",
            "diagnosis_suggestions": diagnosis_suggestions_list
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@suggestion_router.get("/search-diagnosis-suggestion",
    response_model=Dict[str, List[Dict[str, str]]],
    summary="Search diagnosis suggestions",
    description="Search for diagnosis suggestions by name using a query string.",
    responses={
        200: {
            "description": "Search results retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Diagnosis suggestions retrieved successfully",
                        "diagnosis_suggestions": [
                            {
                                "id": 1,
                                "diagnosis": "Migraine",
                                "created_at": "2023-01-01T00:00:00"
                            }
                        ]
                    }
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    })
async def search_diagnosis_suggestion(request: Request, query: str, db: Session = Depends(get_db)):
    try:        
        diagnosis_suggestions = db.query(DiagnosisSuggestion).filter(DiagnosisSuggestion.diagnosis.ilike(f"%{query}%")).order_by(DiagnosisSuggestion.diagnosis.asc()).all()
        diagnosis_suggestions_list = []
        for suggestion in diagnosis_suggestions:
            diagnosis_suggestions_list.append({
                "id": suggestion.id,
                "diagnosis": suggestion.diagnosis,
                "created_at": suggestion.created_at
            })
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Diagnosis suggestions retrieved successfully",
            "diagnosis_suggestions": diagnosis_suggestions_list
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@suggestion_router.patch("/update-diagnosis-suggestion/{diagnosis_suggestion_id}",
    response_model=Dict[str, str],
    summary="Update a diagnosis suggestion",
    description="Modify the diagnosis of an existing diagnosis suggestion.",
    responses={
        200: {
            "description": "Diagnosis suggestion updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Diagnosis suggestion updated successfully",
                        "diagnosis_suggestion": {
                            "id": 1,
                            "diagnosis": "Updated Diagnosis"
                        }
                    }
                }
            }
        },
        404: {
            "description": "Diagnosis suggestion not found",
            "content": {
                "application/json": {
                    "example": {"message": "Diagnosis suggestion not found"}
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    })
async def update_diagnosis_suggestion(diagnosis_suggestion_id: str, request: Request, diagnosis_suggestion_update: DiagnosisSuggestionSchema, db: Session = Depends(get_db)):
    try:        
        existing_suggestion = db.query(DiagnosisSuggestion).filter(DiagnosisSuggestion.id == diagnosis_suggestion_id).first()
        if not existing_suggestion:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Diagnosis suggestion not found"})
        
        existing_suggestion.diagnosis = diagnosis_suggestion_update.diagnosis
        db.commit()
        db.refresh(existing_suggestion)  # Refresh the existing_suggestion with the latest data from the database
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Diagnosis suggestion updated successfully",
            "diagnosis_suggestion": existing_suggestion
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    
@suggestion_router.delete(
    "/delete-diagnosis-suggestion/{diagnosis_suggestion_id}",
    status_code=200,
    summary="Delete a diagnosis suggestion",
    description="Delete an existing diagnosis suggestion by its ID",
    responses={
        200: {
            "description": "Diagnosis suggestion deleted successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Diagnosis suggestion deleted successfully"}
                }
            }
        },
        404: {
            "description": "Diagnosis suggestion not found",
            "content": {
                "application/json": {
                    "example": {"message": "Diagnosis suggestion not found"}
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    }
)
async def delete_diagnosis_suggestion(diagnosis_suggestion_id: str, request: Request, db: Session = Depends(get_db)):
    try:        
        existing_suggestion = db.query(DiagnosisSuggestion).filter(DiagnosisSuggestion.id == diagnosis_suggestion_id).first()
        if not existing_suggestion:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Diagnosis suggestion not found"})
        
        db.delete(existing_suggestion)
        db.commit()
        return JSONResponse(status_code=status.HTTP_200_OK, content={"message": "Diagnosis suggestion deleted successfully"})
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    
@suggestion_router.post(
    "/add-vital-sign-suggestion",
    status_code=201,
    summary="Add a new vital sign suggestion",
    description="Create a new vital sign suggestion in the system",
    responses={
        201: {
            "description": "Vital sign suggestion created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Vital sign suggestion added successfully",
                        "vital_sign_suggestion": {
                            "id": 1,
                            "vital_sign": "Blood Pressure",
                            "created_at": "2023-01-01T00:00:00"
                        }
                    }
                }
            }
        },
        409: {
            "description": "Vital sign suggestion already exists",
            "content": {
                "application/json": {
                    "example": {"message": "Vital sign suggestion already exists"}
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    }
)
async def add_vital_sign_suggestion(vital_sign_suggestion: VitalSignSuggestionSchema, db: Session = Depends(get_db)):
    try:
        existing_suggestion = db.query(VitalSignSuggestion).filter(VitalSignSuggestion.vital_sign == vital_sign_suggestion.vital_sign).first()
        if existing_suggestion:
            return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"message": "Vital sign suggestion already exists"})
        
        new_suggestion = VitalSignSuggestion(vital_sign=vital_sign_suggestion.vital_sign)
        db.add(new_suggestion)
        db.commit()
        db.refresh(new_suggestion)
        return JSONResponse(status_code=status.HTTP_201_CREATED, content={
            "message": "Vital sign suggestion added successfully",
            "vital_sign_suggestion": new_suggestion
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    
@suggestion_router.get(
    "/get-vital-sign-suggestions",
    status_code=200,
    summary="Get all vital sign suggestions",
    description="Retrieve a list of all vital sign suggestions ordered by creation date",
    responses={
        200: {
            "description": "Vital sign suggestions retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Vital sign suggestions retrieved successfully",
                        "vital_sign_suggestions": [
                            {
                                "id": 1,
                                "vital_sign": "Blood Pressure",
                                "created_at": "2023-01-01T00:00:00"
                            }
                        ]
                    }
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    }
)
async def get_vital_sign_suggestions(request: Request, db: Session = Depends(get_db)):
    try:        
        vital_sign_suggestions = db.query(VitalSignSuggestion).order_by(VitalSignSuggestion.created_at.desc()).all()
        vital_sign_suggestions_list = []
        for suggestion in vital_sign_suggestions:
            vital_sign_suggestions_list.append({
                "id": suggestion.id,
                "vital_sign": suggestion.vital_sign,
                "created_at": suggestion.created_at
            })
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Vital sign suggestions retrieved successfully",
            "vital_sign_suggestions": vital_sign_suggestions_list
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    
@suggestion_router.get(
    "/search-vital-sign-suggestion",
    status_code=200,
    summary="Search vital sign suggestions",
    description="Search for vital sign suggestions using a text query. The search is case-insensitive and matches partial strings.",
    responses={
        200: {
            "description": "Search completed successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Vital sign suggestions retrieved successfully",
                        "vital_sign_suggestions": [
                            {
                                "id": 1,
                                "vital_sign": "Blood Pressure",
                                "created_at": "2023-01-01T00:00:00"
                            }
                        ]
                    }
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    }
)
async def search_vital_sign_suggestion(request: Request, query: str, db: Session = Depends(get_db)):
    try:        
        vital_sign_suggestions = db.query(VitalSignSuggestion).filter(VitalSignSuggestion.vital_sign.ilike(f"%{query}%")).order_by(VitalSignSuggestion.vital_sign.asc()).all()
        vital_sign_suggestions_list = []
        for suggestion in vital_sign_suggestions:
            vital_sign_suggestions_list.append({
                "id": suggestion.id,
                "vital_sign": suggestion.vital_sign,
                "created_at": suggestion.created_at
            })
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Vital sign suggestions retrieved successfully",
            "vital_sign_suggestions": vital_sign_suggestions_list
        })
    except SQLAlchemyError as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@suggestion_router.patch(
    "/update-vital-sign-suggestion/{vital_sign_suggestion_id}",
    status_code=200,
    summary="Update a vital sign suggestion",
    description="Update an existing vital sign suggestion by its ID",
    responses={
        200: {
            "description": "Vital sign suggestion updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Vital sign suggestion updated successfully",
                        "vital_sign_suggestion": {
                            "id": 1,
                            "vital_sign": "Updated Blood Pressure",
                            "created_at": "2023-01-01T00:00:00"
                        }
                    }
                }
            }
        },
        404: {
            "description": "Vital sign suggestion not found",
            "content": {
                "application/json": {
                    "example": {"message": "Vital sign suggestion not found"}
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    }
)
async def update_vital_sign_suggestion(vital_sign_suggestion_id: str, request: Request, vital_sign_suggestion_update: VitalSignSuggestionSchema, db: Session = Depends(get_db)):
    try:        
        existing_suggestion = db.query(VitalSignSuggestion).filter(VitalSignSuggestion.id == vital_sign_suggestion_id).first()
        if not existing_suggestion:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Vital sign suggestion not found"})
        
        existing_suggestion.vital_sign = vital_sign_suggestion_update.vital_sign
        db.commit()
        db.refresh(existing_suggestion)
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "message": "Vital sign suggestion updated successfully",
            "vital_sign_suggestion": existing_suggestion
        })
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})

@suggestion_router.delete(
    "/delete-vital-sign-suggestion/{vital_sign_suggestion_id}",
    status_code=200,
    summary="Delete a vital sign suggestion",
    description="Delete an existing vital sign suggestion by its ID",
    responses={
        200: {
            "description": "Vital sign suggestion deleted successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Vital sign suggestion deleted successfully"}
                }
            }
        },
        404: {
            "description": "Vital sign suggestion not found",
            "content": {
                "application/json": {
                    "example": {"message": "Vital sign suggestion not found"}
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Database error or unexpected issue"}
                }
            }
        }
    }
)
async def delete_vital_sign_suggestion(vital_sign_suggestion_id: str, request: Request, db: Session = Depends(get_db)):
    try:        
        existing_suggestion = db.query(VitalSignSuggestion).filter(VitalSignSuggestion.id == vital_sign_suggestion_id).first()
        if not existing_suggestion:
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"message": "Vital sign suggestion not found"})
        
        db.delete(existing_suggestion)
        db.commit()
        return JSONResponse(status_code=status.HTTP_200_OK, content={"message": "Vital sign suggestion deleted successfully"})
    except SQLAlchemyError as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(e)})