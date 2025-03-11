from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from .schemas import ExpenseCreate, ExpenseUpdate, ExpenseResponse, PaymentCreate, PaymentUpdate, PaymentResponse, InvoiceCreate, InvoiceUpdate, InvoiceResponse
from .models import Expense, Payment, Invoice, PaymentMethod, InvoiceItem
from db.db import get_db
from auth.models import User
from patient.models import Patient
from utils.auth import verify_token
from typing import Optional
from utils.generate_invoice import create_professional_invoice
import uuid
import os
from datetime import datetime
payment_router = APIRouter()

def update_url(url: str, request: Request):
    base_url = str(request.base_url).rstrip('/')
    return f"{base_url}/{url}"

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
    summary="Get all expenses",
    description="""
    Retrieve a list of all expenses for the authenticated doctor.
    
    The expenses are returned in chronological order with the most recent first.
    Each expense includes full details including date, type, amount, etc.
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    Query parameters:
    - page (int): Page number (default: 1)
    - per_page (int): Number of items per page (default: 10, max: 100)
    
    Returns:
    - 200: List of expenses with pagination details
    - 401: Unauthorized - Invalid or missing token  
    - 500: Internal server error with error details
    
    Response includes:
    - List of expense objects with full details
    - Pagination metadata (total count, current page, etc)
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
                            "per_page": 10
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
async def get_expenses(
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
        
        # Get total count
        total = db.query(Expense).filter(Expense.doctor_id == user.id).count()
        
        # Calculate offset
        offset = (page - 1) * per_page
        
        # Get paginated expenses
        expenses = (
            db.query(Expense)
            .filter(Expense.doctor_id == user.id)
            .order_by(Expense.created_at.desc())
            .offset(offset)
            .limit(per_page)
            .all()
        )
        
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
                "per_page": per_page
            }
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
    - payment_methods (array): List of payment methods used, each containing:
        - payment_mode (string): Mode of payment (Cash/Card/Cheque/NetBanking)
        - amount (float): Amount paid through this method
        - Additional fields based on payment mode:
            - For Card: card_number, card_type
            - For Cheque: cheque_number, cheque_bank
            - For NetBanking: netbanking_bank_name
    
    Optional parameters:
    - invoice_number (string): Associated invoice number
    - notes (string): Additional payment notes
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
        payment_methods = payment_data.pop("payment_methods")
        
        payment_data["doctor_id"] = user.id
        payment_data["patient_id"] = patient_id
        payment_data["patient_name"] = patient.name
        payment_data["patient_number"] = patient.patient_number

        new_payment = Payment(**payment_data)
        db.add(new_payment)
        db.flush()
        
        for method in payment_methods:
            method["payment_id"] = new_payment.id
            payment_method = PaymentMethod(**method)
            db.add(payment_method)
            
        db.commit()
        db.refresh(new_payment)

        return JSONResponse(status_code=201, content={"message": "Payment created successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@payment_router.get("/get-payments",
    response_model=dict,
    status_code=200,
    summary="Get all payments",
    description="""
    Retrieve a paginated list of all payments for the authenticated doctor.
    
    Query parameters:
    - page (integer, optional): Page number for pagination (default: 1)
    - per_page (integer, optional): Number of items per page (default: 10)
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    Returns:
    - 200: List of payments with pagination details
    - 401: Unauthorized - Invalid or missing token
    - 500: Internal server error with error details
    
    Response includes:
    - List of payment objects with full details including payment methods
    - Pagination metadata (total count, current page, total pages)
    
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
                                "payment_methods": [
                                    {
                                        "payment_mode": "Card",
                                        "amount": 1000.00,
                                        "card_number": "****1234"
                                    }
                                ]
                            }
                        ],
                        "pagination": {
                            "total": 50,
                            "page": 1,
                            "per_page": 10,
                            "total_pages": 5
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
                "refund": payment.refund,
                "refund_receipt_number": payment.refund_receipt_number,
                "refunded_amount": payment.refunded_amount,
                "cancelled": payment.cancelled,
                "created_at": payment.created_at.isoformat() if payment.created_at else None,
                "updated_at": payment.updated_at.isoformat() if payment.updated_at else None,
                "payment_methods": [{
                    "id": pm.id,
                    "payment_id": pm.payment_id,
                    "payment_mode": pm.payment_mode,
                    "card_number": pm.card_number,
                    "card_type": pm.card_type,
                    "cheque_number": pm.cheque_number,
                    "cheque_bank": pm.cheque_bank,
                    "netbanking_bank_name": pm.netbanking_bank_name,
                    "vendor_name": pm.vendor_name,
                    "vendor_fees_percent": pm.vendor_fees_percent,
                    "created_at": pm.created_at.isoformat(),
                    "updated_at": pm.updated_at.isoformat()
                } for pm in payment.payment_methods]
            }
            payments_list.append(payment_dict)
            
        return JSONResponse(status_code=200, content={
            "payments": payments_list,
            "pagination": {
                "total": total_count,
                "page": page,
                "per_page": per_page,
                "total_pages": (total_count + per_page - 1) // per_page
            }
        })
    except Exception as e:
        print(str(e))
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@payment_router.get("/get-payment-by-patient-id/{patient_id}",
    response_model=list[PaymentResponse],
    status_code=200,
    summary="Get payment by patient ID",
    description="""
    Retrieve a paginated list of all payments for a specific patient.
    
    Path parameters:
    - patient_id (string, required): Unique identifier of the patient
    
    Query parameters:
    - page (integer, optional): Page number for pagination (default: 1)
    - per_page (integer, optional): Number of items per page (default: 10)
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    Returns:
    - 200: List of patient's payments with pagination details
    - 401: Unauthorized - Invalid or missing token
    - 404: Patient not found
    - 500: Internal server error with error details
    
    Response includes:
    - List of payment objects with full details including payment methods
    - Pagination metadata (total count, current page, total pages)
    
    Each payment object contains:
    - Basic payment info (date, amount, receipt number)
    - Treatment details
    - Payment method details
    - Refund/cancellation status
    - Timestamps
    """,
    responses={
        200: {
            "description": "List of patient's payments retrieved successfully",
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
                                "payment_methods": [
                                    {
                                        "payment_mode": "Card",
                                        "amount": 1000.00,
                                        "card_number": "****1234"
                                    }
                                ]
                            }
                        ],
                        "pagination": {
                            "total": 10,
                            "page": 1,
                            "per_page": 10,
                            "total_pages": 1
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
async def get_payments_by_patient_id(
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
        
        # Calculate pagination
        offset = (page - 1) * per_page
        
        # Get total count
        total_count = db.query(Payment).filter(Payment.patient_id == patient_id).count()
        
        # Get paginated payments
        payments = db.query(Payment)\
            .filter(Payment.patient_id == patient_id)\
            .offset(offset)\
            .limit(per_page)\
            .all()
        
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
                "refund": payment.refund,
                "refund_receipt_number": payment.refund_receipt_number,
                "refunded_amount": payment.refunded_amount,
                "cancelled": payment.cancelled,
                "created_at": payment.created_at.isoformat() if payment.created_at else None,
                "updated_at": payment.updated_at.isoformat() if payment.updated_at else None,
                "payment_methods": [{
                    "id": pm.id,
                    "payment_id": pm.payment_id,
                    "payment_mode": pm.payment_mode,
                    "card_number": pm.card_number,
                    "card_type": pm.card_type,
                    "cheque_number": pm.cheque_number,
                    "cheque_bank": pm.cheque_bank,
                    "netbanking_bank_name": pm.netbanking_bank_name,
                    "vendor_name": pm.vendor_name,
                    "vendor_fees_percent": pm.vendor_fees_percent,
                    "created_at": pm.created_at.isoformat(),
                    "updated_at": pm.updated_at.isoformat()
                } for pm in payment.payment_methods]
            }
            payments_list.append(payment_dict)
            
        return JSONResponse(status_code=200, content={
            "payments": payments_list,
            "pagination": {
                "total": total_count,
                "page": page,
                "per_page": per_page,
                "total_pages": (total_count + per_page - 1) // per_page
            }
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
                        "payment_methods": [
                            {
                                "payment_mode": "CARD",
                                "amount": 1000.00
                            }
                        ]
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
            "refund": payment.refund,
            "refund_receipt_number": payment.refund_receipt_number,
            "refunded_amount": payment.refunded_amount,
            "cancelled": payment.cancelled,
            "created_at": payment.created_at.isoformat() if payment.created_at else None,
            "updated_at": payment.updated_at.isoformat() if payment.updated_at else None,
            "payment_methods": [{
                "id": pm.id,
                "payment_id": pm.payment_id,
                "payment_mode": pm.payment_mode,
                "card_number": pm.card_number,
                "card_type": pm.card_type,
                "cheque_number": pm.cheque_number,
                "cheque_bank": pm.cheque_bank,
                "netbanking_bank_name": pm.netbanking_bank_name,
                "vendor_name": pm.vendor_name,
                "vendor_fees_percent": pm.vendor_fees_percent,
                "created_at": pm.created_at.isoformat(),
                "updated_at": pm.updated_at.isoformat()
            } for pm in payment.payment_methods]
        }
        
        return JSONResponse(status_code=200, content=payment_dict)
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@payment_router.get("/search-payment",
    response_model=list[PaymentResponse], 
    status_code=200,
    summary="Search and filter payments",
    description="""
    Search and filter payments using various criteria with pagination support.
    
    Search parameters (optional, at least one required for search):
    - patient_id: Patient's unique identifier
    - patient_email: Patient's registered email address
    - patient_name: Full or partial name of the patient (case-insensitive)
    
    Date filter parameters (optional):
    - start_date: Start date for date range (format: YYYY-MM-DD)
    - end_date: End date for date range (format: YYYY-MM-DD)
    - date: Specific date to filter (format: YYYY-MM-DD)
    
    Pagination parameters:
    - page: Page number for results (default: 1)
    - per_page: Number of results per page (default: 10, max: 100)
    
    Returns:
    - List of matching payments with pagination details
    - Each payment includes full details and associated payment methods
    - Pagination metadata including total count and page information
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    Notes:
    - Results are filtered to only show payments for the authenticated doctor
    - Date filters can be used independently or in combination
    - Search is case-insensitive for patient name
    """,
    responses={
        200: {
            "description": "Search results retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "payments": [
                            {
                                "id": "123e4567-e89b-12d3-a456-426614174000",
                                "patient_name": "John Doe",
                                "amount_paid": 1000.00
                            }
                        ],
                        "pagination": {
                            "total": 50,
                            "page": 1,
                            "per_page": 10,
                            "total_pages": 5
                        }
                    }
                }
            }
        },
        401: {"description": "Unauthorized - Invalid or missing token"},
        500: {"description": "Internal server error - Error while processing request"}
    }
)
async def search_payments(
    request: Request,
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

        # Start with base query
        query = db.query(Payment).filter(Payment.doctor_id == user.id)

        # Apply search filters if provided
        if patient_id:
            query = query.filter(Payment.patient_id == patient_id)
        if patient_email:
            patient = db.query(Patient).filter(Patient.email == patient_email).first()
            if patient:
                query = query.filter(Payment.patient_id == patient.id)
        if patient_name:
            query = query.filter(Payment.patient_name.ilike(f"%{patient_name}%"))

        # Apply date filters if provided
        if date:
            query = query.filter(Payment.date == date)
        elif start_date and end_date:
            query = query.filter(Payment.date.between(start_date, end_date))
        elif start_date:
            query = query.filter(Payment.date >= start_date)
        elif end_date:
            query = query.filter(Payment.date <= end_date)

        # Get total count before pagination
        total_count = query.count()
        
        # Calculate pagination
        offset = (page - 1) * per_page
        
        # Apply pagination
        payments = query.offset(offset).limit(per_page).all()
        
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
                "refund": payment.refund,
                "refund_receipt_number": payment.refund_receipt_number,
                "refunded_amount": payment.refunded_amount,
                "cancelled": payment.cancelled,
                "created_at": payment.created_at.isoformat() if payment.created_at else None,
                "updated_at": payment.updated_at.isoformat() if payment.updated_at else None,
                "payment_methods": [{
                    "id": pm.id,
                    "payment_id": pm.payment_id,
                    "payment_mode": pm.payment_mode,
                    "card_number": pm.card_number,
                    "card_type": pm.card_type,
                    "cheque_number": pm.cheque_number,
                    "cheque_bank": pm.cheque_bank,
                    "netbanking_bank_name": pm.netbanking_bank_name,
                    "vendor_name": pm.vendor_name,
                    "vendor_fees_percent": pm.vendor_fees_percent,
                    "created_at": pm.created_at.isoformat(),
                    "updated_at": pm.updated_at.isoformat()
                } for pm in payment.payment_methods]
            }
            payments_list.append(payment_dict)
            
        return JSONResponse(status_code=200, content={
            "payments": payments_list,
            "pagination": {
                "total": total_count,
                "page": page,
                "per_page": per_page,
                "total_pages": (total_count + per_page - 1) // per_page
            }
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
    - refund: Toggle refund status (true/false)
    - refund_receipt_number: Receipt number for refund
    - refunded_amount: Amount refunded
    - cancelled: Mark payment as cancelled (true/false)
    - payment_methods: Updated list of payment methods
        - Each method can include: mode, card details, bank details, etc.
    
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
        payment_methods = payment_data.pop("payment_methods", None)

        for key, value in payment_data.items():
            setattr(existing_payment, key, value)

        if payment_methods:
            # Delete existing payment methods
            db.query(PaymentMethod).filter(PaymentMethod.payment_id == payment_id).delete()
            
            # Add new payment methods
            for method in payment_methods:
                method["payment_id"] = payment_id
                payment_method = PaymentMethod(**method)
                db.add(payment_method)

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

        # Delete associated payment methods first due to foreign key constraint
        db.query(PaymentMethod).filter(PaymentMethod.payment_id == payment_id).delete()
        
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
        invoice_data = {
            "id": str(uuid.uuid4()),
            "date": invoice.date or current_time,
            "patient_id": patient.id,
            "doctor_id": user.id,
            "patient_name": patient.name,
            "patient_number": patient.patient_number,
            "doctor_name": user.name,
            "invoice_number": invoice.invoice_number or f"INV-{current_time.strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}",
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
    summary="Get all invoices for logged in doctor",
    description="""
    Retrieves a list of all invoices associated with the authenticated doctor.
    
    The response includes full invoice details including items, amounts, taxes and discounts.
    Invoices are sorted by date in descending order (newest first).
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    Optional query parameters:
    - cancelled (boolean): Filter invoices by cancelled status
    - start_date (YYYY-MM-DD): Filter invoices created on or after this date
    - end_date (YYYY-MM-DD): Filter invoices created on or before this date
    - page (integer): Page number for pagination (default: 1)
    - per_page (integer): Number of items per page (default: 10, max: 100)
    
    Returns a list of invoice objects containing:
    - Basic invoice details (ID, number, dates, etc)
    - Patient and doctor information
    - Line items with treatment details
    - PDF file path if available
    - Pagination metadata
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
                            "items": [{
                                "treatment_name": "Consultation",
                                "amount": 100.00
                            }]
                        }],
                        "pagination": {
                            "total": 50,
                            "page": 1,
                            "per_page": 10,
                            "total_pages": 5
                        }
                    }
                }
            }
        },
        401: {"description": "Unauthorized - Invalid or missing authentication token"},
        500: {"description": "Internal server error - Failed to retrieve invoices"}
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
        
        # Build query with filters
        query = db.query(Invoice).filter(Invoice.doctor_id == user.id)
        
        if cancelled is not None:
            query = query.filter(Invoice.cancelled == cancelled)
            
        if start_date:
            query = query.filter(Invoice.date >= start_date)
            
        if end_date:
            query = query.filter(Invoice.date <= end_date)
            
        # Get total count before pagination
        total_count = query.count()
        
        # Calculate offset for pagination
        offset = (page - 1) * per_page
        
        # Apply pagination and ordering
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
                "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
                "updated_at": invoice.updated_at.isoformat() if invoice.updated_at else None,
                "items": []
            }
            
            # Get invoice items
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
            }
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@payment_router.get("/get-invoices-by-patient/{patient_id}",
    response_model=dict,
    status_code=200,
    summary="Get all invoices for a specific patient",
    description="""
    Retrieves all invoices associated with a specific patient ID.
    
    The response includes detailed invoice information including:
    - Basic invoice details (ID, number, dates)
    - Patient and doctor information  
    - Line items with treatment details
    - Calculated amounts including:
        - Subtotal before discounts/taxes
        - Discount amounts
        - Tax amounts
        - Final total
    - PDF file path if available
    
    Path parameters:
    - patient_id (string, required): Unique identifier of the patient
    
    Query parameters:
    - page (integer, optional): Page number for pagination (default: 1)
    - per_page (integer, optional): Number of items per page (default: 10, max: 100)
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    Returns a list of invoice objects with full details and calculated amounts.
    """,
    responses={
        200: {
            "description": "List of patient invoices retrieved successfully",
            "content": {
                "application/json": {
                    "example": [{
                        "id": "uuid",
                        "invoice_number": "INV-001", 
                        "patient_name": "John Doe",
                        "subtotal": 100.00,
                        "total_discount": 10.00,
                        "total_tax": 9.00,
                        "total_amount": 99.00,
                        "items": [{
                            "treatment_name": "Consultation",
                            "amount": 100.00,
                            "discount_amount": 10.00,
                            "tax_amount": 9.00,
                            "total": 99.00
                        }]
                    }]
                }
            }
        },
        401: {"description": "Unauthorized - Invalid or missing authentication token"},
        404: {"description": "Patient not found or no invoices exist for patient"},
        500: {"description": "Internal server error - Failed to retrieve patient invoices"}
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
        
        # Get total count
        total_count = db.query(Invoice).filter(Invoice.patient_id == patient_id).count()
        
        # Calculate offset for pagination
        offset = (page - 1) * per_page
        
        # Get paginated invoices
        invoices = (
            db.query(Invoice)
            .filter(Invoice.patient_id == patient_id)
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
            invoice_dict["total_amount"] = subtotal - total_discount + total_tax
            invoice_list.append(invoice_dict)
            
        return JSONResponse(status_code=200, content={
            "invoices": invoice_list,
            "pagination": {
                "total": total_count,
                "page": page,
                "per_page": per_page,
                "total_pages": (total_count + per_page - 1) // per_page
            }
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
                        "total": 99.00,
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
                db.add(invoice_item)

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
                "doctor_email": user.email
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
