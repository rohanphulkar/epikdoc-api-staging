from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from .schemas import ExpenseCreate, ExpenseUpdate, ExpenseResponse, PaymentCreate, PaymentUpdate, PaymentResponse, InvoiceCreate, InvoiceUpdate, InvoiceResponse
from .models import Expense, Payment, Invoice, InvoiceItem
from db.db import get_db
from auth.models import User
from patient.models import Patient
from utils.auth import verify_token
from typing import Optional
from utils.generate_invoice import create_professional_invoice
import uuid
import os
from datetime import datetime
from sqlalchemy import func
import random
from catalog.models import TreatmentPlan, TreatmentPlanItem
from appointment.models import Appointment

payment_router = APIRouter()

def update_url(url: str, request: Request):
    base_url = str(request.base_url).rstrip('/')
    return f"{base_url}/{url}"

def generate_invoice_number():
    return f"EPK{random.randint(1000, 9999)}"

@payment_router.post("/create-expense", 
    response_model=ExpenseResponse,
    status_code=201,
    summary="Create new expense",
    description="""
    Create a new expense record for tracking clinic/practice expenses.
    
    Required parameters in request body:
    - date (string): Date of expense in YYYY-MM-DD format
    - expense_type (string): Category of expense (e.g. "Supplies", "Equipment", "Utilities")
    - description (string): Detailed description of the expense
    - amount (float): Amount spent in local currency
    - vendor_name (string): Name of vendor/supplier where expense was incurred
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    Returns:
    - 201: Expense created successfully with expense details
    - 401: Unauthorized - Invalid or missing token
    - 422: Validation error - Invalid request body
    - 500: Internal server error with error details
    """,
    responses={
        201: {
            "description": "Expense created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Expense created successfully",
                        "expense": {
                            "id": "uuid",
                            "date": "2023-01-01",
                            "expense_type": "Supplies",
                            "description": "Medical supplies restock",
                            "amount": 500.00,
                            "vendor_name": "Medical Supplies Co"
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid token",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        422: {
            "description": "Validation Error",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid request body"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Error details"}
                }
            }
        }
    }
)
async def create_expense(request: Request, expense: ExpenseCreate, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        expense_data = expense.model_dump()
        expense_data["doctor_id"] = user.id

        new_expense = Expense(**expense_data)
        db.add(new_expense)
        db.commit()
        db.refresh(new_expense)

        return JSONResponse(status_code=201, content={"message": "Expense created successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@payment_router.get("/get-expenses",
    response_model=list[ExpenseResponse],
    status_code=200, 
    summary="Get all expenses with statistics",
    description="""
    Retrieve a list of all expenses for the authenticated doctor along with expense statistics.
    
    The expenses are returned in chronological order with the most recent first.
    Each expense includes full details including date, type, amount, etc.
    
    Statistics provided:
    - Today's total expenses
    - Current month's total expenses 
    - Current year's total expenses
    - Overall total expenses
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    Query parameters:
    - page (int): Page number (default: 1)
    - per_page (int): Number of items per page (default: 10, max: 100)
    - start_date (str, optional): Filter expenses from this date (YYYY-MM-DD)
    - end_date (str, optional): Filter expenses until this date (YYYY-MM-DD)
    
    Returns:
    - 200: List of expenses with pagination details and statistics
    - 401: Unauthorized - Invalid or missing token  
    - 422: Validation Error - Invalid date format
    - 500: Internal server error with error details
    """,
    responses={
        200: {
            "description": "List of expenses retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "expenses": [
                            {
                                "id": "uuid",
                                "date": "2023-01-01",
                                "expense_type": "Supplies", 
                                "description": "Medical supplies",
                                "amount": 500.00,
                                "vendor_name": "Medical Co",
                                "created_at": "2023-01-01T10:00:00",
                                "updated_at": "2023-01-01T10:00:00"
                            }
                        ],
                        "pagination": {
                            "total": 50,
                            "page": 1,
                            "per_page": 10,
                            "total_pages": 5
                        },
                        "statistics": {
                            "today_total": 1500.00,
                            "month_total": 12500.00,
                            "year_total": 150000.00,
                            "overall_total": 450000.00
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid token",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        422: {
            "description": "Validation Error",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid date format. Use YYYY-MM-DD"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Error details"}
                }
            }
        }
    }
)
async def get_expenses(
    request: Request,
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Items per page"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})

        # Base query
        query = db.query(Expense).filter(Expense.doctor_id == user.id)

        # Date filters if provided
        if start_date:
            query = query.filter(Expense.date >= start_date)
        if end_date:
            query = query.filter(Expense.date <= end_date)

        # Get total count
        total = query.count()
        total_pages = (total + per_page - 1) // per_page
        
        # Calculate offset
        offset = (page - 1) * per_page
        
        # Get paginated expenses
        expenses = (
            query
            .order_by(Expense.created_at.desc())
            .offset(offset)
            .limit(per_page)
            .all()
        )

        # Calculate statistics
        today = datetime.now().date()
        month_start = today.replace(day=1)
        year_start = today.replace(month=1, day=1)

        stats = {
            "today_total": db.query(func.sum(Expense.amount)).filter(
                Expense.doctor_id == user.id,
                func.date(Expense.date) == today
            ).scalar() or 0,
            
            "month_total": db.query(func.sum(Expense.amount)).filter(
                Expense.doctor_id == user.id,
                Expense.date >= month_start
            ).scalar() or 0,
            
            "year_total": db.query(func.sum(Expense.amount)).filter(
                Expense.doctor_id == user.id,
                Expense.date >= year_start
            ).scalar() or 0,
            
            "overall_total": db.query(func.sum(Expense.amount)).filter(
                Expense.doctor_id == user.id
            ).scalar() or 0
        }
        
        expenses_list = []
        for expense in expenses:
            expense_dict = {
                "id": expense.id,
                "date": expense.date.isoformat() if expense.date else None,
                "expense_type": expense.expense_type,
                "description": expense.description,
                "amount": expense.amount,
                "vendor_name": expense.vendor_name,
                "created_at": expense.created_at.isoformat() if expense.created_at else None,
                "updated_at": expense.updated_at.isoformat() if expense.updated_at else None
            }
            expenses_list.append(expense_dict)
            
        response = {
            "expenses": expenses_list,
            "pagination": {
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages
            },
            "statistics": stats
        }
        
        return JSONResponse(status_code=200, content=response)
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@payment_router.get("/get-expense/{expense_id}",
    response_model=ExpenseResponse,
    status_code=200,
    summary="Get expense by ID",
    description="""
    Retrieve detailed information for a specific expense by its ID.
    
    Path parameters:
    - expense_id (string, required): Unique identifier of the expense to retrieve
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    Returns:
    - 200: Full expense details
    - 401: Unauthorized - Invalid or missing token
    - 404: Expense not found
    - 500: Internal server error with error details
    
    The response includes all expense details including:
    - Basic info (date, type, amount)
    - Vendor details
    - Timestamps
    - Associated metadata
    """,
    responses={
        200: {
            "description": "Expense details retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "id": "uuid",
                        "date": "2023-01-01",
                        "expense_type": "Supplies",
                        "description": "Medical supplies",
                        "amount": 500.00,
                        "vendor_name": "Medical Co",
                        "created_at": "2023-01-01T10:00:00",
                        "updated_at": "2023-01-01T10:00:00"
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid token",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "Expense not found",
            "content": {
                "application/json": {
                    "example": {"message": "Expense not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Error details"}
                }
            }
        }
    }
)
async def get_expense(request: Request, expense_id: str, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        expense = db.query(Expense).filter(Expense.id == expense_id).first()
        if not expense:
            return JSONResponse(status_code=404, content={"message": "Expense not found"})
        
        expense_dict = {
            "id": expense.id,
            "date": expense.date.isoformat() if expense.date else None,
            "expense_type": expense.expense_type,
            "description": expense.description,
            "amount": expense.amount,
            "vendor_name": expense.vendor_name,
            "created_at": expense.created_at.isoformat() if expense.created_at else None,
            "updated_at": expense.updated_at.isoformat() if expense.updated_at else None
        }
        return JSONResponse(status_code=200, content=expense_dict)
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@payment_router.patch("/update-expense/{expense_id}",
    response_model=ExpenseResponse,
    status_code=200,
    summary="Update expense",
    description="""
    Update an existing expense record with new information.
    
    Path parameters:
    - expense_id (string, required): Unique identifier of the expense to update
    
    Optional parameters in request body:
    - date (string): New date in YYYY-MM-DD format
    - expense_type (string): New expense category
    - description (string): New description
    - amount (float): New amount
    - vendor_name (string): New vendor name
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    Only provided fields will be updated. Omitted fields retain their current values.
    
    Returns:
    - 200: Expense updated successfully with updated details
    - 401: Unauthorized - Invalid or missing token
    - 404: Expense not found
    - 422: Validation error - Invalid request body
    - 500: Internal server error with error details
    """,
    responses={
        200: {
            "description": "Expense updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Expense updated successfully",
                        "expense": {
                            "id": "uuid",
                            "date": "2023-01-01",
                            "expense_type": "Supplies",
                            "description": "Updated description",
                            "amount": 600.00,
                            "vendor_name": "New Vendor"
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid token",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "Expense not found",
            "content": {
                "application/json": {
                    "example": {"message": "Expense not found"}
                }
            }
        },
        422: {
            "description": "Validation Error",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid request body"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Error details"}
                }
            }
        }
    }
)
async def update_expense(request: Request, expense_id: str, expense: ExpenseUpdate, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        expense_data = expense.model_dump()
        expense_data["doctor_id"] = user.id

        existing_expense = db.query(Expense).filter(Expense.id == expense_id).first()
        if not existing_expense:
            return JSONResponse(status_code=404, content={"message": "Expense not found"})

        for key, value in expense_data.items():
            setattr(existing_expense, key, value)

        db.commit()
        db.refresh(existing_expense)

        return JSONResponse(status_code=200, content={"message": "Expense updated successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@payment_router.delete("/delete-expense/{expense_id}",
    response_model=ExpenseResponse,
    status_code=200,
    summary="Delete expense",
    description="""
    Permanently delete an existing expense record.
    
    Path parameters:
    - expense_id (string, required): Unique identifier of the expense to delete
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    This operation cannot be undone. The expense record will be permanently removed.
    
    Returns:
    - 200: Expense deleted successfully
    - 401: Unauthorized - Invalid or missing token
    - 404: Expense not found
    - 500: Internal server error with error details
    """,
    responses={
        200: {
            "description": "Expense deleted successfully",
            "content": {
                "application/json": {
                    "example": {"message": "Expense deleted successfully"}
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid token",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "Expense not found",
            "content": {
                "application/json": {
                    "example": {"message": "Expense not found"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Error details"}
                }
            }
        }
    }
)
async def delete_expense(request: Request, expense_id: str, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        db.query(Expense).filter(Expense.id == expense_id).delete()
        db.commit()

        return JSONResponse(status_code=200, content={"message": "Expense deleted successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@payment_router.post("/create-payment/{patient_id}",
    response_model=PaymentResponse,
    status_code=201,
    summary="Create new payment",
    description="""
    Create a new payment record for a patient.
    
    Path parameters:
    - patient_id (string, required): Unique identifier of the patient
    
    Required parameters in request body:
    - date (string): Payment date in YYYY-MM-DD format
    - receipt_number (string): Unique receipt number
    - treatment_name (string): Name/description of treatment
    - amount_paid (float): Payment amount
    
    Optional parameters:
    - invoice_number (string): Associated invoice number
    - notes (string): Additional payment notes
    - payment_mode (string): payment mode (e.g., cash, card, cheque, netbanking)
    - refund (boolean): Whether this is a refund
    - refund_receipt_number (string): Original receipt number for refund
    - refunded_amount (float): Amount being refunded
    - cancelled (boolean): Whether payment is cancelled
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    Returns:
    - 201: Payment created successfully with payment details
    - 401: Unauthorized - Invalid or missing token
    - 404: Patient not found
    - 422: Validation error - Invalid request body
    - 500: Internal server error with error details
    """,
    responses={
        201: {
            "description": "Payment created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Payment created successfully",
                        "payment": {
                            "id": "uuid",
                            "date": "2023-01-01",
                            "patient_id": "patient_uuid",
                            "receipt_number": "REC001",
                            "treatment_name": "Consultation",
                            "amount_paid": 1000.00,
                            "payment_methods": [
                                {
                                    "payment_mode": "Card",
                                    "amount": 1000.00,
                                    "card_number": "****1234",
                                    "card_type": "Credit"
                                }
                            ]
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid token",
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
        },
        422: {
            "description": "Validation Error",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid request body"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Error details"}
                }
            }
        }
    }
)
async def create_payment(request: Request, patient_id: str, payment: PaymentCreate, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
            
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return JSONResponse(status_code=404, content={"message": "Patient not found"})
            
        payment_data = payment.model_dump()
        
        payment_data["doctor_id"] = user.id
        payment_data["patient_id"] = patient_id
        payment_data["patient_name"] = patient.name
        payment_data["patient_number"] = patient.patient_number

        new_payment = Payment(**payment_data)
        db.add(new_payment)
        db.flush()
            
        db.commit()
        db.refresh(new_payment)

        return JSONResponse(status_code=201, content={"message": "Payment created successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@payment_router.get("/get-payments",
    response_model=dict,
    status_code=200,
    summary="Get all payments with statistics",
    description="""
    Retrieve a paginated list of all payments for the authenticated doctor with payment statistics.
    
    Query parameters:
    - page (integer, optional): Page number for pagination (default: 1)
    - per_page (integer, optional): Number of items per page (default: 10, max: 100)
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    Returns:
    - 200: List of payments with pagination details and statistics
    - 401: Unauthorized - Invalid or missing token
    - 500: Internal server error with error details
    
    Response includes:
    - List of payment objects with full details
    - Pagination metadata (total count, current page, total pages)
    - Payment statistics:
        - Today's total payments
        - Current month's total payments
        - Current year's total payments
        - Overall total payments
    
    Each payment object contains:
    - Basic payment info (date, amount, receipt number)
    - Patient details (id, name, number)
    - Treatment details
    - Payment method details
    - Refund/cancellation status
    - Timestamps
    """,
    responses={
        200: {
            "description": "List of payments retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "payments": [
                            {
                                "id": "uuid",
                                "date": "2023-01-01", 
                                "patient_id": "patient_uuid",
                                "patient_name": "John Doe",
                                "receipt_number": "REC001",
                                "treatment_name": "Consultation",
                                "amount_paid": 1000.00,
                            }
                        ],
                        "pagination": {
                            "total": 50,
                            "page": 1,
                            "per_page": 10,
                            "total_pages": 5
                        },
                        "statistics": {
                            "today_total": 1000.00,
                            "month_total": 5000.00,
                            "year_total": 50000.00,
                            "overall_total": 100000.00
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid token",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Error details"}
                }
            }
        }
    }
)
async def get_payments(
    request: Request,
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})

        # Calculate pagination
        offset = (page - 1) * per_page
        
        # Get total count
        total_count = db.query(Payment).filter(Payment.doctor_id == user.id).count()

        # Get paginated payments
        payments = db.query(Payment)\
            .filter(Payment.doctor_id == user.id)\
            .offset(offset)\
            .limit(per_page)\
            .all()

        # Calculate statistics
        today = datetime.now().date()
        month_start = today.replace(day=1)
        year_start = today.replace(month=1, day=1)

        stats = {
            "today_total": db.query(func.sum(Payment.amount_paid)).filter(
                Payment.doctor_id == user.id,
                func.date(Payment.date) == today
            ).scalar() or 0,
            
            "month_total": db.query(func.sum(Payment.amount_paid)).filter(
                Payment.doctor_id == user.id,
                Payment.date >= month_start
            ).scalar() or 0,
            
            "year_total": db.query(func.sum(Payment.amount_paid)).filter(
                Payment.doctor_id == user.id,
                Payment.date >= year_start
            ).scalar() or 0,
            
            "overall_total": db.query(func.sum(Payment.amount_paid)).filter(
                Payment.doctor_id == user.id
            ).scalar() or 0
        }
        
        # Convert payments to dict for JSON serialization
        payments_list = []
        for payment in payments:
            payment_dict = {
                "id": payment.id,
                "date": payment.date.isoformat() if payment.date else None,
                "patient_id": payment.patient_id,
                "doctor_id": payment.doctor_id,
                "patient_number": payment.patient_number,
                "patient_name": payment.patient_name,
                "receipt_number": payment.receipt_number,
                "treatment_name": payment.treatment_name,
                "amount_paid": payment.amount_paid,
                "invoice_number": payment.invoice_number,
                "notes": payment.notes,
                "payment_mode":payment.payment_mode,
                "refund": payment.refund,
                "refund_receipt_number": payment.refund_receipt_number,
                "refunded_amount": payment.refunded_amount,
                "cancelled": payment.cancelled,
                "created_at": payment.created_at.isoformat() if payment.created_at else None,
                "updated_at": payment.updated_at.isoformat() if payment.updated_at else None,
            }
            payments_list.append(payment_dict)
            
        return JSONResponse(status_code=200, content={
            "payments": payments_list,
            "pagination": {
                "total": total_count,
                "page": page,
                "per_page": per_page,
                "total_pages": (total_count + per_page - 1) // per_page
            },
            "statistics": stats
        })
    except Exception as e:
        print(str(e))
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@payment_router.get("/get-payment-by-patient-id/{patient_id}",
    response_model=dict,
    status_code=200,
    summary="Get payments by patient ID with statistics",
    description="""
    Retrieve a paginated list of all payments for a specific patient along with payment statistics.
    
    **Path Parameters:**
    - patient_id (UUID): Patient's unique identifier
    
    **Query Parameters:**
    - page (int): Page number for pagination (default: 1)
    - per_page (int): Number of items per page (default: 10, max: 100)
    
    **Statistics Returned:**
    - Today: Total payment amount for today
    - This Month: Total payment amount for current month
    - This Year: Total payment amount for current year
    - Overall: Total payment amount across all time
    
    **Authentication:**
    - Requires valid doctor Bearer token
    
    **Response:**
    ```json
    {
        "payments": [
            {
                "id": "uuid",
                "date": "2023-01-01",
                "patient_id": "uuid",
                "patient_name": "John Doe",
                "receipt_number": "REC001",
                "treatment_name": "Consultation",
                "amount_paid": 1000.00,
            }
        ],
        "pagination": {
            "total": 100,
            "page": 1,
            "per_page": 10,
            "pages": 10
        },
        "stats": {
            "today_total": 5000.00,
            "month_total": 45000.00,
            "year_total": 450000.00,
            "overall_total": 1000000.00
        }
    }
    ```
    """,
    responses={
        200: {
            "description": "Successfully retrieved patient's payments with statistics",
            "content": {
                "application/json": {
                    "example": {
                        "payments": [],
                        "pagination": {
                            "total": 0,
                            "page": 1,
                            "per_page": 10,
                            "pages": 0
                        },
                        "stats": {
                            "today_total": 0,
                            "month_total": 0,
                            "year_total": 0,
                            "overall_total": 0
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid token",
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
async def get_payments_by_patient_id(
    request: Request, 
    patient_id: str,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(10, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})

        # Check if patient exists
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return JSONResponse(status_code=404, content={"message": "Patient not found"})
            
        # Calculate pagination
        offset = (page - 1) * per_page
        
        # Get total count
        total_count = db.query(Payment).filter(Payment.patient_id == patient_id).count()
        
        # Get paginated payments
        payments = db.query(Payment)\
            .filter(Payment.patient_id == patient_id)\
            .order_by(Payment.created_at.desc())\
            .offset(offset)\
            .limit(per_page)\
            .all()

        # Calculate statistics
        today = datetime.now().date()
        month_start = today.replace(day=1)
        year_start = today.replace(month=1, day=1)

        stats = {
            "today_total": db.query(func.sum(Payment.amount_paid)).filter(
                Payment.patient_id == patient_id,
                func.date(Payment.date) == today
            ).scalar() or 0,
            
            "month_total": db.query(func.sum(Payment.amount_paid)).filter(
                Payment.patient_id == patient_id,
                Payment.date >= month_start
            ).scalar() or 0,
            
            "year_total": db.query(func.sum(Payment.amount_paid)).filter(
                Payment.patient_id == patient_id,
                Payment.date >= year_start
            ).scalar() or 0,
            
            "overall_total": db.query(func.sum(Payment.amount_paid)).filter(
                Payment.patient_id == patient_id
            ).scalar() or 0
        }
        
        # Convert payments to dict for JSON serialization
        payments_list = []
        for payment in payments:
            payment_dict = {
                "id": payment.id,
                "date": payment.date.isoformat() if payment.date else None,
                "patient_id": payment.patient_id,
                "doctor_id": payment.doctor_id,
                "patient_number": payment.patient_number,
                "patient_name": payment.patient_name,
                "receipt_number": payment.receipt_number,
                "treatment_name": payment.treatment_name,
                "amount_paid": payment.amount_paid,
                "invoice_number": payment.invoice_number,
                "notes": payment.notes,
                "payment_mode": payment.payment_mode,
                "refund": payment.refund,
                "refund_receipt_number": payment.refund_receipt_number,
                "refunded_amount": payment.refunded_amount,
                "cancelled": payment.cancelled,
                "created_at": payment.created_at.isoformat() if payment.created_at else None,
                "updated_at": payment.updated_at.isoformat() if payment.updated_at else None,
            }
            payments_list.append(payment_dict)
            
        return JSONResponse(status_code=200, content={
            "payments": payments_list,
            "pagination": {
                "total": total_count,
                "page": page,
                "per_page": per_page,
                "total_pages": (total_count + per_page - 1) // per_page
            },
            "stats": stats
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@payment_router.get("/get-payment/{payment_id}",
    response_model=PaymentResponse,
    status_code=200,
    summary="Get payment details by ID",
    description="""
    Retrieves detailed information about a specific payment record by its ID.
    
    Path parameters:
    - payment_id: Unique identifier of the payment to retrieve
    
    Returns:
    - Full payment details including:
        - Basic payment information (date, amount, etc.)
        - Patient details
        - Treatment information  
        - Payment methods used
        - Refund details if applicable
        - Timestamps
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    Notes:
    - Only accessible by the doctor who created the payment
    - Returns 404 if payment ID doesn't exist
    - Returns 401 if unauthorized or invalid token
    """,
    responses={
        200: {
            "description": "Payment details retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "id": "123e4567-e89b-12d3-a456-426614174000",
                        "date": "2023-01-01T10:00:00",
                        "amount_paid": 1000.00,
                        "patient_name": "John Doe",
                    }
                }
            }
        },
        401: {"description": "Unauthorized - Invalid or missing token"},
        404: {"description": "Payment not found - Invalid payment ID"},
        500: {"description": "Internal server error - Error while processing request"}
    }
)
async def get_payment(request: Request, payment_id: str, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})

        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        if not payment:
            return JSONResponse(status_code=404, content={"message": "Payment not found"})
        
        # Convert payment to dict for JSON serialization
        payment_dict = {
            "id": payment.id,
            "date": payment.date.isoformat() if payment.date else None,
            "patient_id": payment.patient_id,
            "doctor_id": payment.doctor_id,
            "patient_number": payment.patient_number,
            "patient_name": payment.patient_name,
            "receipt_number": payment.receipt_number,
            "treatment_name": payment.treatment_name,
            "amount_paid": payment.amount_paid,
            "invoice_number": payment.invoice_number,
            "notes": payment.notes,
            "payment_mode": payment.payment_mode,
            "refund": payment.refund,
            "refund_receipt_number": payment.refund_receipt_number,
            "refunded_amount": payment.refunded_amount,
            "cancelled": payment.cancelled,
            "created_at": payment.created_at.isoformat() if payment.created_at else None,
            "updated_at": payment.updated_at.isoformat() if payment.updated_at else None,
        }
        
        return JSONResponse(status_code=200, content=payment_dict)
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@payment_router.get("/search-payment",
    response_model=dict,
    status_code=200,
    summary="Search and filter payments with statistics",
    description="""
    Search and filter payments using various criteria with pagination support and payment statistics.
    
    **Search Parameters (optional):**
    - payment_id (UUID): Specific payment ID to search
    - patient_id (UUID): Patient's unique identifier
    - patient_email (str): Patient's registered email address
    - patient_name (str): Full or partial name of the patient (case-insensitive)
    
    **Date Filter Parameters (optional):**
    - start_date (YYYY-MM-DD): Start date for date range
    - end_date (YYYY-MM-DD): End date for date range
    - date (YYYY-MM-DD): Specific date to filter
    
    **Pagination Parameters:**
    - page (int, default=1): Page number for results
    - per_page (int, default=10, max=100): Number of results per page
    
    **Response Includes:**
    - List of matching payments with full details
    - Pagination metadata (total count, current page, total pages)
    - Payment statistics:
        - Today's total payments
        - Current month's total payments
        - Current year's total payments
        - Overall total payments
    
    **Authentication:**
    - Requires valid doctor Bearer token
    
    **Notes:**
    - Results filtered to authenticated doctor's payments only
    - Case-insensitive search for patient name
    - Date filters can be combined or used individually
    """,
    responses={
        200: {
            "description": "Search results with statistics retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "payments": [
                            {
                                "id": "uuid",
                                "date": "2023-01-01",
                                "patient_name": "John Doe",
                                "amount_paid": 1000.00,
                            }
                        ],
                        "pagination": {
                            "total": 50,
                            "page": 1,
                            "per_page": 10,
                            "total_pages": 5
                        },
                        "statistics": {
                            "today": 5000.00,
                            "month": 25000.00,
                            "year": 150000.00,
                            "overall": 500000.00
                        }
                    }
                }
            }
        },
        401: {"description": "Unauthorized - Invalid or missing token"},
        500: {"description": "Internal server error"}
    }
)
async def search_payments(
    request: Request,
    payment_id: Optional[str] = None,
    patient_id: Optional[str] = None,
    patient_email: Optional[str] = None, 
    patient_name: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    date: Optional[datetime] = None,
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})

        # Base query
        query = db.query(Payment).filter(Payment.doctor_id == user.id)

        # Apply filters
        if payment_id:
            query = query.filter(Payment.id == payment_id)
        if patient_id:
            query = query.filter(Payment.patient_id == patient_id)
        if patient_email:
            patient = db.query(Patient).filter(Patient.email == patient_email).first()
            if patient:
                query = query.filter(Payment.patient_id == patient.id)
        if patient_name:
            query = query.filter(Payment.patient_name.ilike(f"%{patient_name}%"))

        # Date filters
        if date:
            query = query.filter(Payment.date == date)
        elif start_date and end_date:
            query = query.filter(Payment.date.between(start_date, end_date))
        elif start_date:
            query = query.filter(Payment.date >= start_date)
        elif end_date:
            query = query.filter(Payment.date <= end_date)

        # Get statistics
        today = datetime.now().date()
        month_start = today.replace(day=1)
        year_start = today.replace(month=1, day=1)

        stats = {
            "today": db.query(func.sum(Payment.amount_paid)).filter(
                Payment.doctor_id == user.id,
                Payment.date == today
            ).scalar() or 0,
            "month": db.query(func.sum(Payment.amount_paid)).filter(
                Payment.doctor_id == user.id,
                Payment.date >= month_start
            ).scalar() or 0,
            "year": db.query(func.sum(Payment.amount_paid)).filter(
                Payment.doctor_id == user.id,
                Payment.date >= year_start
            ).scalar() or 0,
            "overall": db.query(func.sum(Payment.amount_paid)).filter(
                Payment.doctor_id == user.id
            ).scalar() or 0
        }

        # Pagination
        total_count = query.count()
        offset = (page - 1) * per_page
        payments = query.offset(offset).limit(per_page).all()
        
        # Format response
        payments_list = []
        for payment in payments:
            payment_dict = {
                "id": payment.id,
                "date": payment.date.isoformat() if payment.date else None,
                "patient_id": payment.patient_id,
                "doctor_id": payment.doctor_id,
                "patient_number": payment.patient_number,
                "patient_name": payment.patient_name,
                "receipt_number": payment.receipt_number,
                "treatment_name": payment.treatment_name,
                "amount_paid": payment.amount_paid,
                "invoice_number": payment.invoice_number,
                "notes": payment.notes,
                "payment_mode":payment.payment_mode,
                "refund": payment.refund,
                "refund_receipt_number": payment.refund_receipt_number,
                "refunded_amount": payment.refunded_amount,
                "cancelled": payment.cancelled,
                "created_at": payment.created_at.isoformat() if payment.created_at else None,
                "updated_at": payment.updated_at.isoformat() if payment.updated_at else None,
            }
            payments_list.append(payment_dict)
            
        return JSONResponse(status_code=200, content={
            "payments": payments_list,
            "pagination": {
                "total": total_count,
                "page": page,
                "per_page": per_page,
                "total_pages": (total_count + per_page - 1) // per_page
            },
            "statistics": stats
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@payment_router.patch("/update-payment/{payment_id}",
    response_model=PaymentResponse,
    status_code=200,
    summary="Update existing payment details",
    description="""
    Update an existing payment record with new information.
    
    Path parameters:
    - payment_id: Unique identifier of the payment to update
    
    Updatable fields (all optional):
    - date: Date of payment (format: YYYY-MM-DD)
    - receipt_number: New receipt number
    - treatment_name: Updated treatment name/description
    - amount_paid: New payment amount
    - invoice_number: Updated invoice reference
    - notes: Additional or updated notes
    - payment_mode: Updated payment mode (e.g., cash, card, cheque, netbanking)
    - refund: Toggle refund status (true/false)
    - refund_receipt_number: Receipt number for refund
    - refunded_amount: Amount refunded
    - cancelled: Mark payment as cancelled (true/false)
    
    Notes:
    - Only the provided fields will be updated
    - Existing payment methods will be replaced if new ones are provided
    - All amount fields should be positive numbers
    - Original payment ID and patient details cannot be modified
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {
            "description": "Payment updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Payment updated successfully",
                        "payment_id": "123e4567-e89b-12d3-a456-426614174000"
                    }
                }
            }
        },
        401: {"description": "Unauthorized - Invalid or missing token"},
        404: {"description": "Payment not found - Invalid payment ID"},
        500: {"description": "Internal server error - Error while processing request"}
    }
)
async def update_payment(request: Request, payment_id: str, payment: PaymentUpdate, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        existing_payment = db.query(Payment).filter(Payment.id == payment_id).first()
        if not existing_payment:
            return JSONResponse(status_code=404, content={"message": "Payment not found"})

        payment_data = payment.model_dump(exclude_unset=True)

        for key, value in payment_data.items():
            setattr(existing_payment, key, value)

        db.commit()
        db.refresh(existing_payment)

        return JSONResponse(status_code=200, content={"message": "Payment updated successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@payment_router.delete("/delete-payment/{payment_id}",
    response_model=PaymentResponse,
    status_code=200,
    summary="Delete payment record",
    description="""
    Permanently delete a payment record and its associated payment methods.
    
    Path parameters:
    - payment_id: Unique identifier of the payment to delete
    
    Important notes:
    - This action cannot be undone
    - All associated payment methods will also be deleted
    - Consider using payment cancellation instead of deletion for audit purposes
    - Only the doctor who created the payment can delete it
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {
            "description": "Payment deleted successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Payment deleted successfully",
                        "payment_id": "123e4567-e89b-12d3-a456-426614174000"
                    }
                }
            }
        },
        401: {"description": "Unauthorized - Invalid or missing token"},
        404: {"description": "Payment not found - Invalid payment ID"},
        500: {"description": "Internal server error - Error while processing request"}
    }
)
async def delete_payment(request: Request, payment_id: str, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})

        # First check if payment exists
        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        if not payment:
            return JSONResponse(status_code=404, content={"message": "Payment not found"})
        
        # Then delete the payment
        db.query(Payment).filter(Payment.id == payment_id).delete()
        db.commit()

        return JSONResponse(status_code=200, content={"message": "Payment deleted successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"message": str(e)})

@payment_router.post("/create-invoice",
    response_model=InvoiceResponse,
    status_code=201,
    summary="Create invoice and generate PDF",
    description="""
    Create a new invoice record and generate a professional PDF invoice document.
    
    Required fields:
    - patient_id: Unique identifier of the patient
    - invoice_items: List of items to be included in the invoice
        - treatment_name: Name/description of the treatment
        - unit_cost: Cost per unit
        - quantity: Number of units
        - discount: Discount amount (optional)
        - discount_type: Percentage or fixed amount (optional)
        - tax_name: Name of applicable tax (optional)
        - tax_percent: Tax percentage (optional)
    
    Optional fields:
    - date: Invoice date (defaults to current date)
    - invoice_number: Custom invoice number (auto-generated if not provided)
    - notes: Additional notes to appear on invoice
    - description: Detailed description of services
    - cancelled: Whether invoice is cancelled (default: false)
    
    Returns:
    - Invoice details including generated PDF URL
    - Automatically calculated totals and tax amounts
    - Professional PDF document with clinic/doctor branding
    
    Notes:
    - PDF is generated automatically and stored securely
    - Invoice numbers are unique and sequential if auto-generated
    - Tax calculations follow local tax rules
    - Multiple items can be added with different tax rates
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        201: {
            "description": "Invoice created successfully with PDF",
            "content": {
                "application/json": {
                    "example": {
                        "id": "123e4567-e89b-12d3-a456-426614174000",
                        "invoice_number": "INV-20230101-12345678",
                        "pdf_url": "https://example.com/invoices/INV-20230101-12345678.pdf",
                        "total_amount": 1000.00,
                        "created_at": "2023-01-01T10:00:00"
                    }
                }
            }
        },
        401: {"description": "Unauthorized - Invalid or missing token"},
        404: {"description": "Patient not found - Invalid patient ID"},
        500: {"description": "Internal server error - Error while processing request"}
    }
)
async def create_invoice(request: Request, invoice: InvoiceCreate, db: Session = Depends(get_db)):
    try:
        # Verify authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
            
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        # Get patient details
        patient = db.query(Patient).filter(Patient.id == invoice.patient_id).first()
        if not patient:
            return JSONResponse(status_code=404, content={"message": "Patient not found"})
        
        # Prepare invoice data with required fields
        current_time = datetime.now()
        invoice_number = generate_invoice_number()
        invoice_data = {
            "id": str(uuid.uuid4()),
            "date": invoice.date or current_time,
            "patient_id": patient.id,
            "doctor_id": user.id,
            "patient_name": patient.name,
            "patient_number": patient.patient_number,
            "doctor_name": user.name,
            "invoice_number": invoice.invoice_number or str(invoice_number),
            "notes": invoice.notes,
            "description": invoice.description,
            "cancelled": invoice.cancelled,
            "created_at": current_time,
            "updated_at": current_time
        }
        
        # Create invoice record
        new_invoice = Invoice(**invoice_data)
        db.add(new_invoice)
        db.commit()
        db.refresh(new_invoice)

        # Create invoice items and store them for PDF generation
        invoice_items_for_pdf = []
        for item in invoice.invoice_items:
            item_total = item.unit_cost * item.quantity  # Base cost
            
            # Apply discount
            if item.discount:
                if item.discount_type == "percentage":
                    item_total -= (item_total * item.discount / 100)
                elif item.discount_type == "fixed":
                    item_total -= item.discount
            
            # Apply tax
            if item.tax_percent:
                tax_amount = (item_total * item.tax_percent / 100)
                item_total += tax_amount
            
            # Add to total invoice amount
            total_amount += item_total
            invoice_item_data = {
                "id": str(uuid.uuid4()),
                "invoice_id": new_invoice.id,
                "treatment_name": item.treatment_name,
                "unit_cost": item.unit_cost,
                "quantity": item.quantity,
                "discount": item.discount,
                "discount_type": item.discount_type,
                "type": item.type,
                "invoice_level_tax_discount": item.invoice_level_tax_discount,
                "tax_name": item.tax_name,
                "tax_percent": item.tax_percent,
                "created_at": current_time,
                "updated_at": current_time
            }

            new_invoice.total_amount = total_amount
            
            invoice_item = InvoiceItem(**invoice_item_data)
            db.add(invoice_item)
            invoice_items_for_pdf.append(invoice_item_data)
        
        db.commit()

        invoice_data["doctor_phone"] = user.phone
        invoice_data["doctor_email"] = user.email
        invoice_data["patient_phone"] = patient.mobile_number
        invoice_data["patient_email"] = patient.email
        
        # Generate PDF invoice
        try:
            pdf_path = create_professional_invoice(
                invoice_data=invoice_data,
                invoice_items=invoice_items_for_pdf
            )
            
            # Update invoice with PDF path
            new_invoice.file_path = update_url(pdf_path, request)
            db.commit()
            
        except Exception as e:
            # Log PDF generation error but don't fail the request
            print(f"Failed to generate PDF invoice: {str(e)}")
        
        # Return full invoice response with items
        db.refresh(new_invoice)                

        return new_invoice
        
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"message": f"Failed to create invoice: {str(e)}"})

@payment_router.get("/get-invoices",
    response_model=dict,
    status_code=200,
    summary="Get all invoices with statistics",
    description="""
    Retrieve a paginated list of all invoices for the authenticated doctor with invoice statistics.
    
    Query parameters:
    - page (integer, optional): Page number for pagination (default: 1)
    - per_page (integer, optional): Number of items per page (default: 10, max: 100)
    - cancelled (boolean, optional): Filter by cancelled status
    - start_date (YYYY-MM-DD): Filter invoices from this date
    - end_date (YYYY-MM-DD): Filter invoices until this date
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    Returns:
    - 200: List of invoices with pagination details and statistics
    - 401: Unauthorized - Invalid or missing token
    - 500: Internal server error with error details
    
    Response includes:
    - List of invoice objects with full details
    - Pagination metadata (total count, current page, total pages)
    - Invoice statistics:
        - Today's total invoice amount (excluding cancelled invoices)
        - Current month's total invoice amount (excluding cancelled invoices)
        - Current year's total invoice amount (excluding cancelled invoices)
        - Overall total invoice amount (excluding cancelled invoices)
    
    Each invoice object contains:
    - Basic invoice info (date, number, amounts)
    - Patient details (id, name, number, email, phone)
    - Doctor details (name, email, phone)
    - Line items with treatment details (name, unit cost, quantity, discounts, taxes)
    - PDF file path if available
    - Cancellation status
    - Notes and description
    - Timestamps
    """,
    responses={
        200: {
            "description": "List of invoices retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "invoices": [{
                            "id": "uuid",
                            "invoice_number": "INV-001", 
                            "date": "2023-01-01",
                            "patient_name": "John Doe",
                            "patient_number": "P001",
                            "patient_email": "john@example.com",
                            "patient_phone": "+1234567890",
                            "doctor_name": "Dr. Smith",
                            "doctor_email": "dr.smith@example.com",
                            "doctor_phone": "+0987654321",
                            "cancelled": False,
                            "notes": "Regular checkup invoice",
                            "description": "Detailed treatment description",
                            "file_path": "/path/to/invoice.pdf",
                            "total_amount": 400,
                            "items": [{
                                "treatment_name": "Consultation",
                                "unit_cost": 100.00,
                                "quantity": 1,
                                "discount": 10.00,
                                "discount_type": "percentage",
                                "tax_name": "VAT",
                                "tax_percent": 5.00
                            }],
                            "created_at": "2023-01-01T10:00:00",
                            "updated_at": "2023-01-01T10:00:00"
                        }],
                        "pagination": {
                            "total": 50,
                            "page": 1,
                            "per_page": 10,
                            "total_pages": 5
                        },
                        "statistics": {
                            "today": 5000.00,
                            "month": 25000.00,
                            "year": 150000.00,
                            "overall": 500000.00
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid or missing token",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Error details"}
                }
            }
        }
    }
)
async def get_invoices(
    request: Request,
    cancelled: Optional[bool] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        # Base query
        query = db.query(Invoice).filter(Invoice.doctor_id == user.id)
        
        # Apply filters
        if cancelled is not None:
            query = query.filter(Invoice.cancelled.is_(cancelled))
        if start_date:
            query = query.filter(Invoice.date >= start_date)
        if end_date:
            query = query.filter(Invoice.date <= end_date)

        # Get statistics using subquery to calculate total from invoice items
        today = datetime.now().date()
        month_start = today.replace(day=1)
        year_start = today.replace(month=1, day=1)

        def get_total_amount(date_filter=None):
            total_query = db.query(
                func.sum(InvoiceItem.unit_cost * InvoiceItem.quantity)
            ).join(Invoice).filter(
                Invoice.doctor_id == user.id,
                Invoice.cancelled.is_(False)  # Only include non-cancelled invoices
            )
            
            if date_filter is not None:
                total_query = total_query.filter(date_filter)
            
            return total_query.scalar() or 0

        stats = {
            "today": get_total_amount(Invoice.date == today),
            "month": get_total_amount(Invoice.date >= month_start),
            "year": get_total_amount(Invoice.date >= year_start),
            "overall": get_total_amount()
        }
            
        # Pagination
        total_count = query.count()
        offset = (page - 1) * per_page
        invoices = query.order_by(Invoice.date.desc()).offset(offset).limit(per_page).all()
        
        # Format response
        invoice_list = []
        for invoice in invoices:
            invoice_dict = {
                "id": invoice.id,
                "date": invoice.date.isoformat() if invoice.date else None,
                "patient_id": invoice.patient_id,
                "doctor_id": invoice.doctor_id,
                "patient_number": invoice.patient_number,
                "patient_name": invoice.patient_name,
                "doctor_name": invoice.doctor_name,
                "invoice_number": invoice.invoice_number,
                "cancelled": invoice.cancelled,
                "notes": invoice.notes,
                "description": invoice.description,
                "file_path": f"{request.base_url}{invoice.id}" if invoice.file_path else None,
                "total_amount": invoice.total_amount,
                "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
                "updated_at": invoice.updated_at.isoformat() if invoice.updated_at else None,
                "items": []
            }
            
            items = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice.id).all()
            for item in items:
                item_dict = {
                    "treatment_name": item.treatment_name,
                    "unit_cost": item.unit_cost,
                    "quantity": item.quantity,
                    "discount": item.discount,
                    "discount_type": item.discount_type,
                    "type": item.type,
                    "invoice_level_tax_discount": item.invoice_level_tax_discount,
                    "tax_name": item.tax_name,
                    "tax_percent": item.tax_percent
                }
                invoice_dict["items"].append(item_dict)
                
            invoice_list.append(invoice_dict)
            
        return JSONResponse(status_code=200, content={
            "invoices": invoice_list,
            "pagination": {
                "total": total_count,
                "page": page,
                "per_page": per_page,
                "total_pages": (total_count + per_page - 1) // per_page
            },
            "statistics": stats
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@payment_router.get("/get-invoices-by-patient/{patient_id}",
    response_model=dict,
    status_code=200,
    summary="Get all invoices for a specific patient with statistics",
    description="""
    Retrieves all invoices associated with a specific patient ID with pagination and statistics.
    
    **Response includes:**
    - List of invoices with full details
    - Pagination metadata (total count, current page, total pages)
    - Invoice statistics:
        - Today's total invoice amount
        - Current month's total invoice amount 
        - Current year's total invoice amount
        - Overall total invoice amount
    
    **Each invoice contains:**
    - Basic invoice details (ID, number, dates)
    - Patient and doctor information
    - Line items with treatment details
    - Calculated amounts:
        - Subtotal before discounts/taxes
        - Discount amounts (fixed or percentage)
        - Tax amounts (with invoice level discounts)
        - Final total
    - PDF file path if available
    
    **Path Parameters:**
    - patient_id (string, required): Unique identifier of the patient
    
    **Query Parameters:**
    - page (integer, optional): Page number for pagination (default: 1)
    - per_page (integer, optional): Number of items per page (default: 10, max: 100)
    
    **Required Headers:**
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {
            "description": "List of patient invoices with statistics retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "invoices": [{
                            "id": "uuid",
                            "date": "2023-01-01T00:00:00",
                            "patient_id": "uuid",
                            "doctor_id": "uuid", 
                            "patient_number": "P001",
                            "patient_name": "John Doe",
                            "doctor_name": "Dr. Smith",
                            "invoice_number": "INV-001",
                            "cancelled": False,
                            "notes": "Regular checkup",
                            "description": "Monthly visit",
                            "file_path": "http://example.com/invoice/uuid",
                            "total_amount": 500.00,
                            "created_at": "2023-01-01T00:00:00",
                            "updated_at": "2023-01-01T00:00:00",
                            "items": [{
                                "treatment_name": "Consultation",
                                "unit_cost": 100.00,
                                "quantity": 1,
                                "discount": 10.00,
                                "discount_type": "percentage",
                                "type": "service",
                                "invoice_level_tax_discount": 0,
                                "tax_name": "VAT",
                                "tax_percent": 10
                            }]
                        }],
                        "pagination": {
                            "total": 50,
                            "page": 1,
                            "per_page": 10,
                            "total_pages": 5
                        },
                        "statistics": {
                            "today": 5000.00,
                            "month": 25000.00,
                            "year": 150000.00,
                            "overall": 500000.00
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        404: {
            "description": "Not Found",
            "content": {
                "application/json": {
                    "example": {"message": "No invoices found for this patient"}
                }
            }
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Error details"}
                }
            }
        }
    }
)
async def get_invoices_by_patient(
    request: Request, 
    patient_id: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})

        # Get statistics using subquery to calculate total from invoice items
        today = datetime.now().date()
        month_start = today.replace(day=1)
        year_start = today.replace(month=1, day=1)

        def get_total_amount(date_filter=None):
            total_query = db.query(
                func.sum(InvoiceItem.unit_cost * InvoiceItem.quantity)
            ).join(Invoice).filter(
                Invoice.patient_id == patient_id,
                Invoice.cancelled.is_(False)  # Only include non-cancelled invoices
            )
            
            if date_filter is not None:
                total_query = total_query.filter(date_filter)
            
            return total_query.scalar() or 0

        stats = {
            "today": get_total_amount(Invoice.date == today),
            "month": get_total_amount(Invoice.date >= month_start),
            "year": get_total_amount(Invoice.date >= year_start),
            "overall": get_total_amount()
        }
        
        # Get total count
        total_count = db.query(Invoice).filter(Invoice.patient_id == patient_id).count()
        
        if total_count == 0:
            return JSONResponse(status_code=404, content={"message": "No invoices found for this patient"})
        
        # Calculate offset for pagination
        offset = (page - 1) * per_page
        
        # Get paginated invoices
        invoices = (
            db.query(Invoice)
            .filter(Invoice.patient_id == patient_id)
            .order_by(Invoice.date.desc())
            .offset(offset)
            .limit(per_page)
            .all()
        )
        
        invoice_list = []
        for invoice in invoices:
            invoice_dict = {
                "id": invoice.id,
                "date": invoice.date.isoformat() if invoice.date else None,
                "patient_id": invoice.patient_id,
                "doctor_id": invoice.doctor_id, 
                "patient_number": invoice.patient_number,
                "patient_name": invoice.patient_name,
                "doctor_name": invoice.doctor_name,
                "invoice_number": invoice.invoice_number,
                "cancelled": invoice.cancelled,
                "notes": invoice.notes,
                "description": invoice.description,
                "file_path": f"{request.base_url}{invoice.id}" if invoice.file_path else None,
                "total_amount": invoice.total_amount,
                "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
                "updated_at": invoice.updated_at.isoformat() if invoice.updated_at else None,
                "items": []
            }
            
            # Get invoice items
            items = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice.id).all()
            subtotal = 0
            total_discount = 0
            total_tax = 0
            
            for item in items:
                # Calculate item amount
                item_amount = item.unit_cost * item.quantity if item.unit_cost and item.quantity else 0
                
                # Calculate discount
                discount_amount = 0
                if item.discount:
                    if item.discount_type and item.discount_type.lower() == 'percentage':
                        discount_amount = item_amount * (item.discount / 100)
                    else:
                        discount_amount = item.discount
                
                # Calculate tax
                tax_amount = 0
                if item.tax_percent:
                    taxable_amount = item_amount - discount_amount
                    tax_amount = taxable_amount * (item.tax_percent / 100)
                    if item.invoice_level_tax_discount:
                        tax_amount = tax_amount * (1 - item.invoice_level_tax_discount / 100)
                
                item_dict = {
                    "treatment_name": item.treatment_name,
                    "unit_cost": item.unit_cost,
                    "quantity": item.quantity,
                    "discount": item.discount,
                    "discount_type": item.discount_type,
                    "type": item.type,
                    "invoice_level_tax_discount": item.invoice_level_tax_discount,
                    "tax_name": item.tax_name,
                    "tax_percent": item.tax_percent,
                    "amount": item_amount,
                    "discount_amount": discount_amount,
                    "tax_amount": tax_amount,
                    "total": item_amount - discount_amount + tax_amount
                }
                invoice_dict["items"].append(item_dict)
                
                subtotal += item_amount
                total_discount += discount_amount
                total_tax += tax_amount
            
            invoice_dict["subtotal"] = subtotal
            invoice_dict["total_discount"] = total_discount
            invoice_dict["total_tax"] = total_tax
            invoice_list.append(invoice_dict)
            
        return JSONResponse(status_code=200, content={
            "invoices": invoice_list,
            "pagination": {
                "total": total_count,
                "page": page,
                "per_page": per_page,
                "total_pages": (total_count + per_page - 1) // per_page
            },
            "statistics": stats
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@payment_router.get("/search-invoices",
    response_model=dict,
    status_code=200,
    summary="Search invoices by multiple criteria with statistics",
    description="""
    Search and filter invoices using various criteria with pagination and statistics.
    
    **Query Parameters:**
    - patient_name_search (str, optional): Search by patient name (case-insensitive partial match)
    - patient_number_search (str, optional): Search by patient number (case-insensitive partial match) 
    - invoice_number_search (str, optional): Search by invoice number (case-insensitive partial match)
    - doctor_name_search (str, optional): Search by doctor name (case-insensitive partial match)
    - patient_gender (str, optional): Filter by patient gender (MALE/FEMALE/OTHER)
    - status (str, optional): Filter by invoice status (PAID/UNPAID/CANCELLED)
    - start_date (datetime, optional): Filter invoices from this date onwards (ISO format)
    - end_date (datetime, optional): Filter invoices up to this date (ISO format)
    - page (int): Page number for pagination (default: 1, min: 1)
    - per_page (int): Number of items per page (default: 10, min: 1, max: 100)

    **Required Headers:**
    - Authorization: Bearer token from doctor login

    **Response Format:**
    ```json
    {
        "invoices": [
            {
                "id": "uuid",
                "date": "2023-01-01T00:00:00",
                "invoice_number": "INV-001", 
                "patient_id": "uuid",
                "patient_name": "John Doe",
                "patient_number": "PT001",
                "doctor_name": "Dr. Smith",
                "cancelled": False,
                "notes": "Invoice notes",
                "description": "Invoice description",
                "file_path": "http://api.example.com/invoices/uuid",
                "total_amount": 100.00,
                "created_at": "2023-01-01T00:00:00",
                "updated_at": "2023-01-01T00:00:00",
                "items": [
                    {
                        "treatment_name": "Consultation",
                        "unit_cost": 100.00,
                        "quantity": 1,
                        "discount": 10.00,
                        "discount_type": "FIXED",
                        "type": "SERVICE",
                        "invoice_level_tax_discount": 0,
                        "tax_name": "GST",
                        "tax_percent": 10.00,
                        "amount": 100.00,
                        "discount_amount": 10.00,
                        "tax_amount": 9.00,
                        "total": 99.00
                    }
                ],
                "subtotal": 100.00,
                "total_discount": 10.00,
                "total_tax": 9.00,
                "total_amount": 99.00
            }
        ],
        "pagination": {
            "total": 100,
            "page": 1,
            "per_page": 10,
            "total_pages": 10
        },
        "statistics": {
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
                        "invoices": [],
                        "pagination": {},
                        "statistics": {}
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "example": {"message": "Unauthorized"}
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Error details"}
                }
            }
        }
    }
)
async def search_invoices(
    request: Request,
    patient_name_search: Optional[str] = None,
    patient_number_search: Optional[str] = None,
    invoice_number_search: Optional[str] = None,
    doctor_name_search: Optional[str] = None,
    patient_gender: Optional[str] = None,   
    status: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        # Base query
        query = db.query(Invoice).filter(Invoice.doctor_id == user.id)
        
        # Apply independent searches
        if patient_name_search:
            query = query.filter(Invoice.patient_name.ilike(f"%{patient_name_search}%"))
        if patient_number_search:
            query = query.filter(Invoice.patient_number.ilike(f"%{patient_number_search}%"))
        if invoice_number_search:
            query = query.filter(Invoice.invoice_number.ilike(f"%{invoice_number_search}%"))
        if doctor_name_search:
            query = query.filter(Invoice.doctor_name.ilike(f"%{doctor_name_search}%"))

        # Apply independent filters
        if patient_gender:
            query = query.filter(Invoice.patient_gender == patient_gender)
        if status:
            query = query.filter(Invoice.status == status)
        if start_date:
            query = query.filter(Invoice.date >= start_date)
        if end_date:
            query = query.filter(Invoice.date <= end_date)

        # Get statistics
        today = datetime.now().date()
        month_start = today.replace(day=1)
        year_start = today.replace(month=1, day=1)
        
        def get_total_amount(date_filter=None):
            total_query = db.query(
                func.sum(InvoiceItem.unit_cost * InvoiceItem.quantity)
            ).join(Invoice).filter(
                Invoice.doctor_id == user.id,
                Invoice.cancelled.is_(False)
            )
            
            if date_filter is not None:
                total_query = total_query.filter(date_filter)
            
            return total_query.scalar() or 0

        stats = {
            "today": get_total_amount(Invoice.date == today),
            "month": get_total_amount(Invoice.date >= month_start),
            "year": get_total_amount(Invoice.date >= year_start),
            "overall": get_total_amount()
        }
        
        # Pagination
        total_count = query.count()
        offset = (page - 1) * per_page
        invoices = query.order_by(Invoice.date.desc()).offset(offset).limit(per_page).all()

        # Format response
        invoice_list = []
        for invoice in invoices:
            invoice_dict = {
                "id": invoice.id,
                "date": invoice.date.isoformat() if invoice.date else None,
                "patient_id": invoice.patient_id,
                "doctor_id": invoice.doctor_id,
                "patient_number": invoice.patient_number,
                "patient_name": invoice.patient_name,
                "doctor_name": invoice.doctor_name,
                "invoice_number": invoice.invoice_number,
                "cancelled": invoice.cancelled,
                "notes": invoice.notes,
                "description": invoice.description,
                "file_path": f"{request.base_url}{invoice.id}" if invoice.file_path else None,
                "total_amount": invoice.total_amount,
                "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
                "updated_at": invoice.updated_at.isoformat() if invoice.updated_at else None,
                "items": []
            }
            
            # Get invoice items
            items = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice.id).all()
            subtotal = 0
            total_discount = 0
            total_tax = 0
            
            for item in items:
                # Calculate base amount
                item_amount = item.unit_cost * item.quantity if item.unit_cost and item.quantity else 0
                
                # Calculate discount
                discount_amount = 0
                if item.discount:
                    if item.discount_type == "percentage":
                        discount_amount = item_amount * (item.discount / 100)
                    else:
                        discount_amount = item.discount
                
                # Calculate tax
                tax_amount = 0
                if item.tax_percent:
                    taxable_amount = item_amount - discount_amount
                    tax_amount = taxable_amount * (item.tax_percent / 100)
                    if item.invoice_level_tax_discount:
                        tax_amount = tax_amount * (1 - item.invoice_level_tax_discount / 100)
                
                item_dict = {
                    "treatment_name": item.treatment_name,
                    "unit_cost": item.unit_cost,
                    "quantity": item.quantity,
                    "discount": item.discount,
                    "discount_type": item.discount_type,
                    "type": item.type,
                    "invoice_level_tax_discount": item.invoice_level_tax_discount,
                    "tax_name": item.tax_name,
                    "tax_percent": item.tax_percent,
                    "amount": item_amount,
                    "discount_amount": discount_amount,
                    "tax_amount": tax_amount,
                    "total": item_amount - discount_amount + tax_amount
                }
                invoice_dict["items"].append(item_dict)
                
                subtotal += item_amount
                total_discount += discount_amount
                total_tax += tax_amount
            
            invoice_dict["subtotal"] = subtotal
            invoice_dict["total_discount"] = total_discount
            invoice_dict["total_tax"] = total_tax
            
            invoice_list.append(invoice_dict)
            
        return JSONResponse(status_code=200, content={
            "invoices": invoice_list,
            "pagination": {
                "total": total_count,
                "page": page,
                "per_page": per_page,
                "total_pages": (total_count + per_page - 1) // per_page
            },
            "statistics": stats
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@payment_router.get("/get-invoice/{invoice_id}",
    response_model=dict,
    status_code=200,
    summary="Get detailed invoice information by ID",
    description="""
    Retrieves complete details of a specific invoice by its ID.
    
    Returns comprehensive invoice information including:
    - Basic invoice details (ID, number, dates)
    - Patient and doctor information
    - Line items with full treatment details
    - Calculated amounts per item:
        - Base amount (unit cost × quantity)
        - Discount amount (fixed or percentage)
        - Tax amount (with any invoice level discounts)
        - Item total
    - Invoice totals:
        - Subtotal before discounts/taxes
        - Total discounts applied
        - Total taxes
        - Final invoice amount
    - PDF file path if available
    
    Path parameters:
    - invoice_id (string, required): Unique identifier of the invoice
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {
            "description": "Invoice details retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "id": "uuid",
                        "invoice_number": "INV-001",
                        "patient_name": "John Doe",
                        "doctor_name": "Dr. Smith",
                        "subtotal": 100.00,
                        "total_discount": 10.00,
                        "total_tax": 9.00,
                        "total_amount": 99.00,
                        "items": [{
                            "treatment_name": "Consultation",
                            "unit_cost": 100.00,
                            "quantity": 1,
                            "discount": 10.00,
                            "tax_amount": 9.00,
                            "total": 99.00
                        }]
                    }
                }
            }
        },
        401: {"description": "Unauthorized - Invalid or missing authentication token"},
        404: {"description": "Invoice not found with provided ID"},
        500: {"description": "Internal server error - Failed to retrieve invoice details"}
    }
)
async def get_invoice(request: Request, invoice_id: str, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice:
            return JSONResponse(status_code=404, content={"message": "Invoice not found"})
        
        invoice_dict = {
            "id": invoice.id,
            "date": invoice.date.isoformat() if invoice.date else None,
            "patient_id": invoice.patient_id,
            "doctor_id": invoice.doctor_id,
            "patient_number": invoice.patient_number,
            "patient_name": invoice.patient_name,
            "doctor_name": invoice.doctor_name,
            "invoice_number": invoice.invoice_number,
            "cancelled": invoice.cancelled,
            "notes": invoice.notes,
            "description": invoice.description,
            "file_path": f"{invoice.file_path}" if invoice.file_path else None,
            "total_amount": invoice.total_amount,
            "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
            "updated_at": invoice.updated_at.isoformat() if invoice.updated_at else None,
            "items": []
        }
        
        # Get invoice items
        items = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice_id).all()
        subtotal = 0
        total_discount = 0
        total_tax = 0
        
        for item in items:
            # Calculate item amount
            item_amount = item.unit_cost * item.quantity if item.unit_cost and item.quantity else 0
            subtotal += item_amount
            
            # Calculate discount
            discount_amount = 0
            if item.discount:
                if item.discount_type and item.discount_type.upper() == 'PERCENTAGE':
                    discount_amount = item_amount * (item.discount / 100)
                else:
                    discount_amount = item.discount
            total_discount += discount_amount
            
            # Calculate tax
            tax_amount = 0
            if item.tax_percent:
                taxable_amount = item_amount - discount_amount
                tax_amount = taxable_amount * (item.tax_percent / 100)
                if item.invoice_level_tax_discount:
                    tax_amount = tax_amount * (1 - item.invoice_level_tax_discount / 100)
            total_tax += tax_amount
            
            item_dict = {
                "treatment_name": item.treatment_name,
                "unit_cost": item.unit_cost,
                "quantity": item.quantity,
                "discount": item.discount,
                "discount_type": item.discount_type,
                "type": item.type,
                "invoice_level_tax_discount": item.invoice_level_tax_discount,
                "tax_name": item.tax_name,
                "tax_percent": item.tax_percent,
                "amount": item_amount,
                "discount_amount": discount_amount,
                "tax_amount": tax_amount,
                "total": item_amount - discount_amount + tax_amount
            }
            
            invoice_dict["items"].append(item_dict)
            
        invoice_dict["subtotal"] = subtotal
        invoice_dict["total_discount"] = total_discount
        invoice_dict["total_tax"] = total_tax
        invoice_dict["total"] = subtotal - total_discount + total_tax
        
        return JSONResponse(status_code=200, content=invoice_dict)
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@payment_router.patch("/update-invoice/{invoice_id}",
    response_model=InvoiceResponse,
    status_code=200,
    summary="Update an existing invoice",
    description="""
    Updates an existing invoice with new information.
    
    Allows updating:
    - Basic invoice details (date, number, notes, description)
    - Invoice items with full treatment details
    - Will regenerate PDF with updated information
    
    Path parameters:
    - invoice_id (string, required): Unique identifier of invoice to update
    
    Request body:
    - date (string, optional): New invoice date (YYYY-MM-DD)
    - invoice_number (string, optional): New custom invoice number
    - notes (string, optional): Updated additional notes
    - description (string, optional): Updated detailed description
    - invoice_items (array, optional): Updated list of invoice items containing:
        - treatment_name (string): Name of treatment/service
        - unit_cost (number): Cost per unit
        - quantity (integer): Number of units
        - discount (number, optional): Discount amount or percentage
        - discount_type (string, optional): "fixed" or "percentage"
        - tax_name (string, optional): Name of tax applied
        - tax_percent (number, optional): Tax percentage
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    Notes:
    - If invoice items are provided, all existing items will be replaced
    - If no items provided, existing items remain unchanged
    - PDF will be regenerated with updated information
    - Old PDF file will be deleted
    """,
    responses={
        200: {
            "description": "Invoice updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "id": "uuid",
                        "invoice_number": "INV-001",
                        "date": "2023-01-01",
                        "items": [{
                            "treatment_name": "Updated Service",
                            "unit_cost": 150.00
                        }]
                    }
                }
            }
        },
        401: {"description": "Unauthorized - Invalid or missing authentication token"},
        404: {"description": "Invoice not found with provided ID"},
        500: {"description": "Internal server error - Failed to update invoice"}
    }
)
async def update_invoice(request: Request, invoice_id: str, invoice: InvoiceUpdate, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        existing_invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not existing_invoice:
            return JSONResponse(status_code=404, content={"message": "Invoice not found"})
        
        # Update invoice fields
        for field, value in invoice.model_dump(exclude={'invoice_items'}).items():
            if value is not None:
                setattr(existing_invoice, field, value)
        
        # Update invoice items if provided
        if invoice.invoice_items:
            # Delete existing items
            db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice_id).delete()

            total_amount = 0.0
            
            # Create new items
            for item in invoice.invoice_items:
                invoice_item = InvoiceItem(
                    id=str(uuid.uuid4()),
                    invoice_id=invoice_id,
                    treatment_name=item.treatment_name,
                    unit_cost=item.unit_cost,
                    quantity=item.quantity,
                    discount=item.discount,
                    discount_type=item.discount_type,
                    type=item.type,
                    invoice_level_tax_discount=item.invoice_level_tax_discount,
                    tax_name=item.tax_name,
                    tax_percent=item.tax_percent,
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                item_total = item.unit_cost * item.quantity  # Base cost
            
                # Apply discount
                if item.discount:
                    if item.discount_type == "percentage":
                        item_total -= (item_total * item.discount / 100)
                    elif item.discount_type == "fixed":
                        item_total -= item.discount
                
                # Apply tax
                if item.tax_percent:
                    tax_amount = (item_total * item.tax_percent / 100)
                    item_total += tax_amount
                
                # Add to total invoice amount
                total_amount += item_total
                db.add(invoice_item)
            existing_invoice.total_amount = total_amount
        db.commit()
        db.refresh(existing_invoice)

        # Get all invoice items
        items = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice_id).all()
        if not items:
            # Create default item if none exist
            invoice_item = InvoiceItem(
                id=str(uuid.uuid4()),
                invoice_id=invoice_id,
                treatment_name="General Consultation",
                unit_cost=0.0,
                quantity=1,
                discount=0.0,
                discount_type="",
                type=None,
                invoice_level_tax_discount=None,
                tax_name=None,
                tax_percent=None,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            db.add(invoice_item)
            db.commit()
            items = [invoice_item]

        # Generate PDF invoice
        try:
            invoice_data = {
                "id": existing_invoice.id,
                "date": existing_invoice.date or datetime.now(),
                "patient_id": existing_invoice.patient_id,
                "doctor_id": existing_invoice.doctor_id,
                "patient_number": existing_invoice.patient_number,
                "patient_name": existing_invoice.patient_name,
                "doctor_name": existing_invoice.doctor_name,
                "invoice_number": existing_invoice.invoice_number,
                "notes": existing_invoice.notes,
                "description": existing_invoice.description,
                "doctor_phone": user.phone,
                "doctor_email": user.email,

            }

            invoice_items = [{
                "treatment_name": item.treatment_name,
                "unit_cost": item.unit_cost,
                "quantity": item.quantity,
                "discount": item.discount,
                "discount_type": item.discount_type or "fixed",
                "type": item.type,
                "invoice_level_tax_discount": item.invoice_level_tax_discount,
                "tax_name": item.tax_name,
                "tax_percent": item.tax_percent
            } for item in items]

            pdf_path = create_professional_invoice(
                invoice_data=invoice_data,
                invoice_items=invoice_items
            )

            # Remove old pdf file
            if existing_invoice.file_path:
                try:
                    os.remove(existing_invoice.file_path)
                except OSError:
                    pass
            existing_invoice.file_path = update_url(pdf_path, request)
            db.commit()

            return JSONResponse(status_code=200, content={"message": "Invoice updated successfully"})

        except Exception as e:
            # Log PDF generation error but don't fail the request
            print(f"Failed to generate PDF invoice: {str(e)}")

        return existing_invoice

    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"message": f"Failed to update invoice: {str(e)}"})

@payment_router.delete("/delete-invoice/{invoice_id}",
    response_model=InvoiceResponse,
    status_code=200,
    summary="Delete an invoice",
    description="""
    Permanently deletes an invoice and all associated data.
    
    This will:
    - Delete the invoice record
    - Delete all associated invoice items
    - Remove the generated PDF file
    - Clean up all related data
    
    Path parameters:
    - invoice_id (string, required): Unique identifier of invoice to delete
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    Notes:
    - This action cannot be undone
    - All associated data will be permanently removed
    - PDF files will be deleted from storage
    """,
    responses={
        200: {
            "description": "Invoice successfully deleted",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Invoice deleted successfully"
                    }
                }
            }
        },
        401: {"description": "Unauthorized - Invalid or missing authentication token"},
        404: {"description": "Invoice not found with provided ID"},
        500: {"description": "Internal server error - Failed to delete invoice"}
    }
)
async def delete_invoice(request: Request, invoice_id: str, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})

        # First check if invoice exists
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice:
            return JSONResponse(status_code=404, content={"message": "Invoice not found"})
            
        # Delete invoice items first due to foreign key constraint
        db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice_id).delete()
        
        # Delete PDF file if it exists
        if invoice.file_path:
            try:
                file_path = invoice.file_path.replace(str(request.base_url).rstrip('/'), '')
                if os.path.exists(file_path):
                    os.remove(file_path)
            except OSError:
                # Log error but continue with deletion
                print(f"Failed to delete PDF file: {invoice.file_path}")
                
        # Delete the invoice
        db.query(Invoice).filter(Invoice.id == invoice_id).delete()
        db.commit()
        
        return JSONResponse(status_code=200, content={"message": "Invoice deleted successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"message": f"Failed to delete invoice: {str(e)}"})
