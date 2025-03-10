from fastapi import APIRouter, Depends, Request
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
    Create a new expense record.
    
    Required parameters:
    - date: Date of expense
    - expense_type: Type of expense
    - description: Description of expense
    - amount: Amount spent
    - vendor_name: Name of vendor/supplier
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        201: {"description": "Expense created successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        500: {"description": "Internal server error"}
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
    Get list of all expenses for the logged in doctor.
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "List of expenses retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        500: {"description": "Internal server error"}
    }
)
async def get_expenses(request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        expenses = db.query(Expense).filter(Expense.doctor_id == user.id).all()
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
        return JSONResponse(status_code=200, content=expenses_list)
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@payment_router.get("/get-expense/{expense_id}",
    response_model=ExpenseResponse,
    status_code=200,
    summary="Get expense by ID",
    description="""
    Get details of a specific expense by ID.
    
    Path parameters:
    - expense_id: ID of the expense to retrieve
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "Expense details retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Expense not found"},
        500: {"description": "Internal server error"}
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
    Update an existing expense record.
    
    Path parameters:
    - expense_id: ID of the expense to update
    
    Optional parameters:
    - date: Date of expense
    - expense_type: Type of expense  
    - description: Description of expense
    - amount: Amount spent
    - vendor_name: Name of vendor/supplier
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "Expense updated successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Expense not found"},
        500: {"description": "Internal server error"}
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
    Delete an existing expense record.
    
    Path parameters:
    - expense_id: ID of the expense to delete
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "Expense deleted successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        500: {"description": "Internal server error"}
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
    Create a new payment record.
    
    Required parameters:
    - date: Date of payment
    - patient_id: ID of the patient
    - receipt_number: Receipt number
    - treatment_name: Name of treatment
    - amount_paid: Amount paid
    - payment_methods: List of payment methods used
    
    Optional parameters:
    - invoice_number: Invoice number
    - notes: Additional notes
    - refund: Whether this is a refund payment
    - refund_receipt_number: Receipt number for refund
    - refunded_amount: Amount refunded
    - cancelled: Whether payment is cancelled

    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        201: {"description": "Payment created successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Patient not found"},
        500: {"description": "Internal server error"}
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
    Get list of all payments for the logged in doctor.
    
    Query parameters:
    - page: Page number (default: 1)
    - per_page: Number of items per page (default: 10)
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "List of payments retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        500: {"description": "Internal server error"}
    }
)
async def get_payments(
    request: Request, 
    page: int = 1,
    per_page: int = 10,
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
    Get all payments for a specific patient.
    
    Path parameters:
    - patient_id: ID of the patient
    
    Query parameters:
    - page: Page number (default: 1)
    - per_page: Number of items per page (default: 10)
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "Payments retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Patient not found"},
        500: {"description": "Internal server error"}
    }
)
async def get_payments_by_patient_id(
    request: Request, 
    patient_id: str, 
    page: int = 1,
    per_page: int = 10,
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
    summary="Get payment by ID",
    description="""
    Get details of a specific payment by ID.
    
    Path parameters:
    - payment_id: ID of the payment to retrieve
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "Payment details retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Payment not found"},
        500: {"description": "Internal server error"}
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
    summary="Search payments",
    description="""
    Search payments by patient details and/or date filters. Both are optional and independent.
    
    Search parameters (optional, only one required if searching):
    - patient_id: Patient's ID
    - patient_email: Patient's email
    - patient_name: Patient's name
    
    Filter parameters (optional):
    - start_date: Start date for date range filter (YYYY-MM-DD)
    - end_date: End date for date range filter (YYYY-MM-DD)
    - date: Specific date to filter (YYYY-MM-DD)
    
    Pagination parameters:
    - page: Page number (default: 1)
    - per_page: Number of items per page (default: 10)
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "Search results retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        500: {"description": "Internal server error"}
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
    page: int = 1,
    per_page: int = 10,
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
    summary="Update payment",
    description="""
    Update an existing payment record.
    
    Path parameters:
    - payment_id: ID of the payment to update
    
    Optional parameters:
    - date: Date of payment
    - receipt_number: Receipt number
    - treatment_name: Name of treatment
    - amount_paid: Amount paid
    - invoice_number: Invoice number
    - notes: Additional notes
    - refund: Whether this is a refund payment
    - refund_receipt_number: Receipt number for refund
    - refunded_amount: Amount refunded
    - cancelled: Whether payment is cancelled
    - payment_methods: List of payment methods used
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "Payment updated successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Payment not found"},
        500: {"description": "Internal server error"}
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
    summary="Delete payment",
    description="""
    Delete an existing payment record.
    
    Path parameters:
    - payment_id: ID of the payment to delete
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "Payment deleted successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Payment not found"},
        500: {"description": "Internal server error"}
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
    summary="Create new invoice and generate PDF",
    description="""
    Create a new invoice record and generate a professional PDF invoice.
    
    Required fields:
    - patient_id: ID of the patient
    - invoice_items: List of invoice items with treatment details
    
    Optional fields:
    - date: Invoice date (defaults to current date)
    - invoice_number: Custom invoice number
    - notes: Additional notes
    - description: Detailed description
    
    Returns:
    - 201: Invoice created successfully with PDF generated
    - 401: Unauthorized - Invalid token
    - 404: Patient not found
    - 500: Internal server error
    """)
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
    summary="Get all invoices",
    description="""
    Get list of all invoices for the logged in doctor.
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    Optional query parameters:
    - cancelled: Filter by cancelled status (true/false)
    - start_date: Filter by date range start (YYYY-MM-DD)
    - end_date: Filter by date range end (YYYY-MM-DD)
    """,
    responses={
        200: {"description": "List of invoices retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        500: {"description": "Internal server error"}
    }
)
async def get_invoices(
    request: Request, 
    cancelled: Optional[bool] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
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
            
        invoices = query.order_by(Invoice.date.desc()).all()
        
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
            
        return JSONResponse(status_code=200, content=invoice_list)
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@payment_router.get("/get-invoices-by-patient/{patient_id}",
    response_model=dict,
    status_code=200,
    summary="Get invoices by patient ID",
    description="""
    Get list of all invoices for a specific patient.
    
    Path parameters:
    - patient_id: ID of the patient
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "List of invoices retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Patient not found"},
        500: {"description": "Internal server error"}
    }
)
async def get_invoices_by_patient(request: Request, patient_id: str, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        invoices = db.query(Invoice).filter(Invoice.patient_id == patient_id).all()
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
            
        return JSONResponse(status_code=200, content=invoice_list)
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@payment_router.get("/get-invoice/{invoice_id}",
    response_model=dict,
    status_code=200,
    summary="Get invoice by ID",
    description="""
    Get details of a specific invoice by ID.
    
    Path parameters:
    - invoice_id: ID of the invoice to retrieve
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "Invoice details retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Invoice not found"},
        500: {"description": "Internal server error"}
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
        
        return JSONResponse(status_code=200, content=invoice_dict)
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@payment_router.patch("/update-invoice/{invoice_id}",
    response_model=InvoiceResponse,
    status_code=200,
    summary="Update invoice",
    description="""
    Update an existing invoice record.
    
    Path parameters:
    - invoice_id: ID of the invoice to update
    
    Optional parameters:
    - date: Invoice date
    - invoice_number: Custom invoice number
    - notes: Additional notes
    - description: Detailed description
    - invoice_items: List of invoice items with treatment details
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "Invoice updated successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Invoice not found"},
        500: {"description": "Internal server error"}
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
    summary="Delete invoice",
    description="""
    Delete an existing invoice record.
    
    Path parameters:
    - invoice_id: ID of the invoice to delete
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "Invoice deleted successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        404: {"description": "Invoice not found"},
        500: {"description": "Internal server error"}
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
