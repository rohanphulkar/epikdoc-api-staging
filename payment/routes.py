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
from catalog.models import TreatmentPlan
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
        query = db.query(Expense).filter(Expense.doctor_id == user.id).order_by(Expense.created_at.desc())

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
    summary="Create new payment record",
    description="""
    Create a new payment record for a patient with optional invoice generation.
    
    Path parameters:
    - patient_id (string, required): Unique identifier of the patient
    
    Request body fields:
    - date (string, required): Payment date in YYYY-MM-DD format
    - receipt_number (string, required): Unique receipt number for the payment
    - treatment_name (string, required): Name/description of treatment or service
    - amount_paid (float, required): Payment amount (must be positive)
    - invoice_number (string, optional): Reference number of associated invoice
    - notes (string, optional): Additional notes or comments about payment
    - payment_mode (string, optional): Method of payment (cash, card, cheque, netbanking, etc)
    - status (string, optional): Payment status (pending, paid, failed)
    - refund (boolean, optional): Whether this is a refund payment
    - refund_receipt_number (string, optional): Receipt number of original payment being refunded
    - refunded_amount (float, optional): Amount being refunded
    - cancelled (boolean, optional): Whether payment is cancelled
    - clinic_id (string, optional): ID of the clinic where payment was made
    - appointment_id (string, optional): ID of associated appointment
    
    Notes:
    - Receipt numbers must be unique
    - Amount paid must be a positive number
    - If status is "paid", associated invoice will be updated
    - Refund payments require original receipt number
    - Patient details are auto-populated from patient_id
    - Doctor details are auto-populated from authentication token
    - Clinic details are auto-populated from doctor's default clinic
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    Returns:
    - 201: Payment created successfully with payment details
    - 401: Invalid or missing authentication token
    - 404: Patient ID not found
    - 422: Invalid input data format
    - 500: Server error while processing request
    """,
    responses={
        201: {
            "description": "Payment created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Payment created successfully",
                        "payment": {
                            "id": "123e4567-e89b-12d3-a456-426614174000",
                            "date": "2023-01-01",
                            "patient_id": "123e4567-e89b-12d3-a456-426614174111",
                            "doctor_id": "123e4567-e89b-12d3-a456-426614174222",
                            "clinic_id": "123e4567-e89b-12d3-a456-426614174333",
                            "receipt_number": "REC-2023-001",
                            "patient_name": "John Doe",
                            "patient_number": "P001", 
                            "treatment_name": "Dental Consultation",
                            "amount_paid": 1000.00,
                            "payment_mode": "card",
                            "status": "paid",
                            "created_at": "2023-01-01T10:00:00Z"
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
                    "example": {
                        "detail": [
                            {
                                "loc": ["body", "amount_paid"],
                                "msg": "Amount paid must be greater than 0",
                                "type": "value_error"
                            }
                        ]
                    }
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {"message": "Error creating payment record"}
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

        # Generate invoice if not already linked
        if not new_payment.invoice_id:
            invoice_data = {
                "date": new_payment.date,
                "patient_id": patient_id,
                "doctor_id": user.id,
                "patient_number": patient.patient_number,
                "patient_name": patient.name,
                "doctor_name": f"{user.name}",
                "invoice_number": f"INV-{datetime.now().strftime('%Y%m%d')}-{new_payment.receipt_number}",
                "notes": new_payment.notes,
                "description": new_payment.treatment_name,
                "total_amount": new_payment.amount_paid
            }

            invoice_items = [{
                "treatment_name": new_payment.treatment_name,
                "unit_cost": new_payment.amount_paid,
                "quantity": 1,
                "discount": 0,
                "discount_type": "fixed",
                "type": "treatment",
                "invoice_level_tax_discount": 0,
                "tax_name": None,
                "tax_percent": 0
            }]

            # Create invoice record
            new_invoice = Invoice(**invoice_data)
            db.add(new_invoice)
            db.flush()

            # Create invoice item
            new_invoice_item = InvoiceItem(
                invoice_id=new_invoice.id,
                **invoice_items[0]
            )
            db.add(new_invoice_item)
            db.flush()

            # Generate PDF
            pdf_path = create_professional_invoice(
                invoice_data=invoice_data,
                invoice_items=invoice_items
            )

            new_invoice.file_path = update_url(pdf_path, request)
            new_invoice.payment_id = new_payment.id
            new_payment.invoice_id = new_invoice.id
            
            db.commit()

        # Handle existing invoice
        elif new_payment.invoice_id:
            invoice = db.query(Invoice).filter(Invoice.id == new_payment.invoice_id).first()
            if invoice:
                items = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice.id).all()
                invoice_data = {
                    "id": invoice.id,
                    "date": invoice.date or datetime.now(),
                    "patient_id": invoice.patient_id,
                    "doctor_id": invoice.doctor_id,
                    "patient_number": invoice.patient_number,
                    "patient_name": invoice.patient_name,
                    "doctor_name": invoice.doctor_name,
                    "invoice_number": invoice.invoice_number,
                    "notes": invoice.notes,
                    "description": invoice.description,
                    "total_amount": invoice.total_amount
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
                if invoice.file_path:
                    try:
                        os.remove(invoice.file_path)
                    except OSError:
                        pass
                        
                invoice.file_path = update_url(pdf_path, request)
                invoice.payment_id = new_payment.id
                new_payment.invoice_id = invoice.id
                
                db.commit()

        return JSONResponse(status_code=201, content={"message": "Payment created successfully", "payment_id": new_payment.id})
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
                "invoice_id": payment.invoice_id,
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
                "status": payment.status,
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
                "invoice_id": payment.invoice_id,
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
                "status": payment.status,
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
            "invoice_id": payment.invoice_id,
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
            "status": payment.status,
            "created_at": payment.created_at.isoformat() if payment.created_at else None,
            "updated_at": payment.updated_at.isoformat() if payment.updated_at else None,
        }
        
        return JSONResponse(status_code=200, content=payment_dict)
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@payment_router.get("/search-payment",
    response_model=dict,
    status_code=200,
    summary="Search and filter payments with comprehensive statistics",
    description="""
    Advanced search endpoint for payments with detailed filtering, pagination, sorting and statistics.
    
    **Search Filters:**
    
    Patient Related:
    - patient_id (UUID): Filter by specific patient
    - patient_email (str): Search by patient email (case-insensitive)
    - patient_name (str): Search by full/partial patient name (case-insensitive)
    
    Payment Details:
    - payment_id (UUID): Search by specific payment ID
    - invoice_id (UUID): Filter by linked invoice
    - payment_mode (str): Filter by payment method (cash/card etc)
    - status (str): Filter by payment status
    - receipt_number (str): Search by receipt number
    - treatment_name (str): Filter by treatment name
    
    Amount Filters:
    - min_amount (float): Filter payments >= minimum amount
    - max_amount (float): Filter payments <= maximum amount
    
    Date Range Filters:
    - date (YYYY-MM-DD): Filter by specific payment date
    - start_date (YYYY-MM-DD): Filter payments from this date
    - end_date (YYYY-MM-DD): Filter payments until this date
    - created_after (YYYY-MM-DD): Filter by creation date >= this date
    - created_before (YYYY-MM-DD): Filter by creation date <= this date
    - updated_after (YYYY-MM-DD): Filter by last update >= this date
    - updated_before (YYYY-MM-DD): Filter by last update <= this date
    
    Special Filters:
    - refund (bool): Filter refunded payments (true/false)
    - cancelled (bool): Filter cancelled payments (true/false)
    
    **Pagination & Sorting:**
    - page (int, default=1): Page number for paginated results
    - per_page (int, default=10, max=100): Number of results per page
    - sort_by (str, default="created_at"): Field to sort results by
    - sort_order (str, default="desc"): Sort direction (asc/desc)
    
    **Response Format:**
    ```json
    {
        "payments": [
            {
                "id": "uuid",
                "date": "2023-01-01T10:00:00",
                "patient_id": "uuid",
                "doctor_id": "uuid",
                "invoice_id": "uuid",
                "patient_number": "P1234",
                "patient_name": "John Doe",
                "receipt_number": "R5678",
                "treatment_name": "Dental Cleaning",
                "amount_paid": 1000.00,
                "invoice_number": "INV1234",
                "notes": "Payment notes",
                "payment_mode": "card",
                "refund": false,
                "refund_receipt_number": null,
                "refunded_amount": 0.00,
                "cancelled": false,
                "status": "completed",
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
            "today": {
                "count": 5,
                "total_amount": 5000.00
            },
            "this_month": {
                "count": 25,
                "total_amount": 25000.00
            },
            "this_year": {
                "count": 150,
                "total_amount": 150000.00
            },
            "overall": {
                "count": 500,
                "total_amount": 500000.00
            }
        }
    }
    ```
    
    **Authentication:**
    - Requires valid doctor Bearer token in Authorization header
    - Results are scoped to authenticated doctor's payments only
    
    **Notes:**
    - All text searches are case-insensitive and support partial matching
    - Date filters can be combined for custom date ranges
    - Amount filters support decimal values
    - Statistics include payment counts and amounts for different time periods
    - Results are sorted by created_at in descending order by default
    """,
    responses={
        200: {
            "description": "Successfully retrieved payments with statistics",
            "content": {
                "application/json": {
                    "example": {
                        "payments": [
                            {
                                "id": "550e8400-e29b-41d4-a716-446655440000",
                                "date": "2023-01-01T10:00:00",
                                "patient_id": "uuid",
                                "doctor_id": "uuid",
                                "invoice_id": "uuid",
                                "patient_number": "P1234",
                                "patient_name": "John Doe",
                                "receipt_number": "R5678",
                                "treatment_name": "Dental Cleaning", 
                                "amount_paid": 1000.00,
                                "invoice_number": "INV1234",
                                "payment_mode": "card",
                                "status": "completed",
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
                            "today": {"count": 5, "total_amount": 5000.00},
                            "this_month": {"count": 25, "total_amount": 25000.00},
                            "this_year": {"count": 150, "total_amount": 150000.00},
                            "overall": {"count": 500, "total_amount": 500000.00}
                        }
                    }
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
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "example": {"message": "Internal server error occurred"}
                }
            }
        }
    }
)
async def search_payments(
    request: Request,
    payment_id: Optional[str] = None,
    patient_id: Optional[str] = None,
    patient_email: Optional[str] = None, 
    patient_name: Optional[str] = None,
    invoice_id: Optional[str] = None,
    payment_mode: Optional[str] = None,
    status: Optional[str] = None,
    receipt_number: Optional[str] = None,
    treatment_name: Optional[str] = None,
    refund: Optional[bool] = None,
    cancelled: Optional[bool] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    date: Optional[datetime] = None,
    created_after: Optional[datetime] = None,
    created_before: Optional[datetime] = None,
    updated_after: Optional[datetime] = None,
    updated_before: Optional[datetime] = None,
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=10, ge=1, le=100, description="Items per page"),
    sort_by: str = Query(default="created_at", description="Field to sort by"),
    sort_order: str = Query(default="desc", description="Sort direction (asc/desc)"),
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

        # Apply independent filters
        if payment_id:
            query = query.filter(Payment.id == payment_id)
        if patient_id:
            query = query.filter(Payment.patient_id == patient_id)
        if patient_email:
            patient = db.query(Patient).filter(Patient.email.ilike(f"%{patient_email}%")).first()
            if patient:
                query = query.filter(Payment.patient_id == patient.id)
        if patient_name:
            query = query.filter(Payment.patient_name.ilike(f"%{patient_name}%"))
        if invoice_id:
            query = query.filter(Payment.invoice_id == invoice_id)
        if payment_mode:
            query = query.filter(Payment.payment_mode.ilike(f"%{payment_mode}%"))
        if status:
            query = query.filter(Payment.status.ilike(f"%{status}%"))
        if receipt_number:
            query = query.filter(Payment.receipt_number.ilike(f"%{receipt_number}%"))
        if treatment_name:
            query = query.filter(Payment.treatment_name.ilike(f"%{treatment_name}%"))
        if refund is not None:
            query = query.filter(Payment.refund == refund)
        if cancelled is not None:
            query = query.filter(Payment.cancelled == cancelled)
            
        # Amount filters
        if min_amount is not None:
            query = query.filter(Payment.amount_paid >= min_amount)
        if max_amount is not None:
            query = query.filter(Payment.amount_paid <= max_amount)

        # Date filters
        if date:
            query = query.filter(func.date(Payment.date) == date.date())
        if start_date:
            query = query.filter(Payment.date >= start_date)
        if end_date:
            query = query.filter(Payment.date <= end_date)
            
        # Created/Updated filters    
        if created_after:
            query = query.filter(Payment.created_at >= created_after)
        if created_before:
            query = query.filter(Payment.created_at <= created_before)
        if updated_after:
            query = query.filter(Payment.updated_at >= updated_after)
        if updated_before:
            query = query.filter(Payment.updated_at <= updated_before)

        # Get statistics
        today = datetime.now().date()
        month_start = today.replace(day=1)
        year_start = today.replace(month=1, day=1)

        stats = {
            "today": db.query(func.sum(Payment.amount_paid)).filter(
                Payment.doctor_id == user.id,
                func.date(Payment.date) == today
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

        # Apply sorting
        sort_column = getattr(Payment, sort_by)
        if sort_order == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())

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
                "invoice_id": payment.invoice_id,
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
                "status": payment.status,
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
    - payment_id (string, required): Unique identifier of the payment to update
    
    Request body fields (all optional):
    - date (string): Date of payment in YYYY-MM-DD format
    - receipt_number (string): New receipt number for the payment
    - treatment_name (string): Name or description of the treatment
    - amount_paid (number): Payment amount (must be positive)
    - invoice_number (string): Reference number of associated invoice
    - notes (string): Additional notes or comments
    - payment_mode (string): Method of payment (cash, card, cheque, netbanking, etc)
    - status (string): Payment status (pending, paid, failed)
    - refund (boolean): Whether payment has been refunded
    - refund_receipt_number (string): Receipt number for refund transaction
    - refunded_amount (number): Amount that was refunded
    - cancelled (boolean): Whether payment has been cancelled
    
    Notes:
    - Only provided fields will be updated, others remain unchanged
    - Patient and doctor details cannot be modified
    - All amount fields must be positive numbers
    - Status changes may trigger additional workflows (e.g. invoice updates)
    - Refund and cancellation may have downstream effects
    
    Required headers:
    - Authorization: Bearer token from doctor login
    
    Returns:
    - 200: Payment successfully updated with updated payment details
    - 401: Invalid or missing authentication token
    - 404: Payment ID not found
    - 422: Invalid input data format
    - 500: Server error while processing request
    """,
    responses={
        200: {
            "description": "Payment updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Payment updated successfully",
                        "payment_id": "123e4567-e89b-12d3-a456-426614174000",
                        "status": "paid",
                        "amount_paid": 1000.00,
                        "updated_at": "2024-01-20T10:30:00Z"
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid or missing authentication token"
        },
        404: {
            "description": "Payment not found - Invalid payment ID"
        },
        422: {
            "description": "Validation error - Invalid input data format"
        },
        500: {
            "description": "Internal server error while processing request"
        }
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

        if existing_payment.invoice_id:
            invoice = db.query(Invoice).filter(Invoice.id == existing_payment.invoice_id).first()
            if invoice:
                if existing_payment.status == "paid":
                    items = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice.id).all()
                    invoice_data = {
                        "id": invoice.id,
                        "date": invoice.date or datetime.now(),
                        "patient_id": invoice.patient_id,
                        "doctor_id": invoice.doctor_id,
                        "patient_number": invoice.patient_number,
                        "patient_name": invoice.patient_name,
                        "doctor_name": invoice.doctor_name,
                        "invoice_number": invoice.invoice_number,
                        "notes": invoice.notes,
                        "description": invoice.description,
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
                    if invoice.file_path:
                        try:
                            os.remove(invoice.file_path)
                        except OSError:
                            pass
                    invoice.file_path = update_url(pdf_path, request)
                    invoice.payment_id = existing_payment.id
                    existing_payment.invoice_id = invoice.id
                    db.commit()

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
    - patient_id (UUID): Unique identifier of the patient
    - invoice_items (array): List of items to be included in the invoice
        - treatment_name (string): Name/description of the treatment
        - unit_cost (decimal): Cost per unit
        - quantity (integer): Number of units
        - discount (decimal, optional): Discount amount
        - discount_type (string, optional): Either 'percentage' or 'fixed'
        - tax_name (string, optional): Name of applicable tax
        - tax_percent (decimal, optional): Tax percentage
    
    Optional fields:
    - date (datetime): Invoice date (defaults to current date)
    - invoice_number (string): Custom invoice number (auto-generated if not provided)
    - notes (string): Additional notes to appear on invoice
    - description (string): Detailed description of services
    - cancelled (boolean): Whether invoice is cancelled (default: false)
    
    Returns:
    - id (UUID): Unique identifier for the invoice
    - invoice_number (string): Generated or provided invoice number
    - pdf_url (string): URL to download generated PDF
    - total_amount (decimal): Final calculated amount including tax and discounts
    - created_at (datetime): Timestamp of invoice creation
    
    Notes:
    - PDF is generated automatically with clinic/doctor branding
    - Invoice numbers are unique and sequential if auto-generated
    - Tax calculations follow local tax rules
    - Multiple items can be added with different tax rates
    - All monetary values use decimal precision
    
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
        400: {"description": "Bad request - Invalid input data"},
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
        
        # Prepare invoice data
        current_time = datetime.now()
        invoice_number = invoice.invoice_number or str(generate_invoice_number())
        
        # Create payment record first
        new_payment = Payment(
            id=str(uuid.uuid4()),
            patient_id=patient.id,
            doctor_id=user.id,
            amount_paid=0,  # Will update after calculating total
            payment_mode="invoice",
            status="pending",
            patient_number=patient.patient_number,
            patient_name=patient.name,
            invoice_number=invoice_number,
            date=current_time
        )
        
        db.add(new_payment)
        db.flush()  # Get ID without committing
        
        # Create invoice record with payment_id
        new_invoice = Invoice(
            id=str(uuid.uuid4()),
            date=invoice.date or current_time,
            patient_id=patient.id,
            doctor_id=user.id,
            payment_id=new_payment.id,  # Set payment_id from the start
            patient_name=patient.name,
            patient_number=patient.patient_number,
            doctor_name=user.name,
            invoice_number=invoice_number,
            notes=invoice.notes,
            description=invoice.description,
            cancelled=invoice.cancelled,
            created_at=current_time,
            updated_at=current_time,
            total_amount=0  # Initialize total amount
        )
        
        db.add(new_invoice)
        db.flush()  # Get ID without committing

        # Process invoice items
        total_amount = 0
        invoice_items_for_pdf = []
        
        for item in invoice.invoice_items:
            if not item.unit_cost or not item.quantity:
                raise ValueError("Unit cost and quantity are required for invoice items")
                
            item_total = float(item.unit_cost) * int(item.quantity)
            
            # Apply discount if present
            if item.discount:
                if item.discount_type == "percentage":
                    item_total -= (item_total * float(item.discount) / 100)
                else:  # fixed amount
                    item_total -= float(item.discount)
            
            # Apply tax if present    
            if item.tax_percent:
                tax_amount = (item_total * float(item.tax_percent) / 100)
                item_total += tax_amount
            
            total_amount += item_total

            # Create invoice item
            invoice_item = InvoiceItem(
                id=str(uuid.uuid4()),
                invoice_id=new_invoice.id,
                treatment_name=item.treatment_name,
                unit_cost=item.unit_cost,
                quantity=item.quantity,
                discount=item.discount,
                discount_type=item.discount_type,
                type=item.type,
                invoice_level_tax_discount=item.invoice_level_tax_discount,
                tax_name=item.tax_name,
                tax_percent=item.tax_percent,
                created_at=current_time,
                updated_at=current_time
            )
            
            db.add(invoice_item)
            invoice_items_for_pdf.append(invoice_item.__dict__)

        # Update invoice total
        new_invoice.total_amount = total_amount
        
        new_payment.invoice_id = new_invoice.id
        
        # Generate PDF with contact details
        invoice_data = {
            **new_invoice.__dict__,
            "doctor_phone": user.phone,
            "doctor_email": user.email,
            "patient_phone": patient.mobile_number,
            "patient_email": patient.email
        }
        
        try:
            pdf_path = create_professional_invoice(
                invoice_data=invoice_data,
                invoice_items=invoice_items_for_pdf
            )
            new_invoice.file_path = update_url(pdf_path, request)
        except Exception as e:
            print(f"Failed to generate PDF invoice: {str(e)}")
            # Continue without PDF
        
        # Commit all changes
        db.commit()
        db.refresh(new_invoice)
        
        return JSONResponse(status_code=201, content={"message": "Invoice created successfully", "invoice_id": new_invoice.id})
        
    except ValueError as e:
        db.rollback()
        return JSONResponse(status_code=400, content={"message": str(e)})
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
                "payment_id": invoice.payment_id,
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
                    "amount": item.unit_cost * item.quantity if item.unit_cost and item.quantity else 0,
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
                "payment_id": invoice.payment_id,
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
                "payment_id": invoice.payment_id,
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
            "payment_id": invoice.payment_id,
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
    Updates an existing invoice with new information and regenerates the PDF.
    
    Path parameters:
    - invoice_id: Unique identifier of invoice to update
    
    Request body:
    - date (string, optional): New invoice date in YYYY-MM-DD format
    - invoice_number (string, optional): New custom invoice number
    - notes (string, optional): Additional notes to appear on invoice
    - description (string, optional): Detailed description of services
    - invoice_items (array, optional): List of invoice items containing:
        - treatment_name (string): Name/description of the treatment
        - unit_cost (number): Cost per unit
        - quantity (integer): Number of units
        - discount (number, optional): Discount amount
        - discount_type (string, optional): "percentage" or "fixed"
        - tax_name (string, optional): Name of applicable tax
        - tax_percent (number, optional): Tax percentage
        - invoice_level_tax_discount (number, optional): Additional tax discount percentage
        - type (string, optional): Type of treatment/service
    
    Important notes:
    - Providing invoice_items will replace all existing items
    - Omitting invoice_items will preserve existing ones
    - PDF will be regenerated with updated information
    - Previous PDF file will be deleted
    - All calculations (totals, tax, discounts) will be recomputed
    - Payment record will be updated to match new total
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {
            "description": "Invoice updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Invoice updated successfully",
                        "invoice_id": "123e4567-e89b-12d3-a456-426614174000"
                    }
                }
            }
        },
        400: {"description": "Bad request - Invalid invoice data"},
        401: {"description": "Unauthorized - Invalid or missing token"},
        404: {"description": "Invoice not found - Invalid invoice ID"},
        500: {"description": "Internal server error - Failed to update invoice"}
    }
)
async def update_invoice(request: Request, invoice_id: str, invoice: InvoiceUpdate, db: Session = Depends(get_db)):
    try:
        # Verify authentication
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["user_id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        # Get existing invoice
        existing_invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not existing_invoice:
            return JSONResponse(status_code=404, content={"message": "Invoice not found"})
        
        # Update basic invoice fields
        update_data = invoice.model_dump(exclude={'invoice_items'}, exclude_unset=True)
        for field, value in update_data.items():
            setattr(existing_invoice, field, value)
        
        # Update invoice items if provided
        if invoice.invoice_items:
            # Delete existing items
            db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice_id).delete()

            total_amount = 0.0
            current_time = datetime.now()
            
            # Create new items
            for item in invoice.invoice_items:
                if not item.unit_cost or not item.quantity:
                    raise ValueError("Unit cost and quantity are required for invoice items")
                    
                item_total = float(item.unit_cost) * int(item.quantity)
            
                # Apply discount
                if item.discount:
                    if item.discount_type == "percentage":
                        item_total -= (item_total * float(item.discount) / 100)
                    else:  # fixed amount
                        item_total -= float(item.discount)
                
                # Apply tax
                if item.tax_percent:
                    tax_amount = (item_total * float(item.tax_percent) / 100)
                    if item.invoice_level_tax_discount:
                        tax_amount *= (1 - float(item.invoice_level_tax_discount) / 100)
                    item_total += tax_amount
                
                # Create invoice item
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
                    created_at=current_time,
                    updated_at=current_time
                )
                
                db.add(invoice_item)
                total_amount += item_total
                
            existing_invoice.total_amount = total_amount
            existing_invoice.updated_at = current_time

        db.commit()
        db.refresh(existing_invoice)

        # Get all invoice items for PDF generation
        items = db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice_id).all()
        
        # Generate PDF invoice
        try:
            invoice_data = {
                **existing_invoice.__dict__,
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
            print(f"Failed to generate PDF invoice: {str(e)}")
            # Continue without PDF

        # Update or create pending payment
        payment = db.query(Payment).filter(Payment.invoice_id == invoice_id).first()
        
        payment_data = {
            "date": datetime.now(),
            "patient_id": existing_invoice.patient_id,
            "doctor_id": existing_invoice.doctor_id,
            "invoice_id": existing_invoice.id,
            "patient_number": existing_invoice.patient_number,
            "patient_name": existing_invoice.patient_name,
            "treatment_name": existing_invoice.description,
            "amount_paid": existing_invoice.total_amount,
            "invoice_number": existing_invoice.invoice_number,
            "notes": existing_invoice.notes,
            "status": "pending"
        }

        if payment:
            for key, value in payment_data.items():
                setattr(payment, key, value)
        else:
            payment = Payment(**payment_data)
            db.add(payment)
            db.flush()
            existing_invoice.payment_id = payment.id

        db.commit()

        return JSONResponse(status_code=200, content={
            "message": "Invoice updated successfully",
            "invoice_id": existing_invoice.id
        })

    except ValueError as e:
        db.rollback()
        return JSONResponse(status_code=400, content={"message": str(e)})
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
        
        # Handle circular reference between Invoice and Payment
        # First, set payment_id to NULL in the invoice
        if invoice.payment_id:
            invoice.payment_id = None
            db.flush()
        
        # Delete invoice items due to foreign key constraint
        db.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice_id).delete(synchronize_session=False)
        db.flush()
        
        # Delete payments associated with this invoice
        db.query(Payment).filter(Payment.invoice_id == invoice_id).delete(synchronize_session=False)
        db.flush()
        
        # Delete PDF file if it exists
        if invoice.file_path:
            try:
                file_path = invoice.file_path.replace(str(request.base_url).rstrip('/'), '')
                if os.path.exists(file_path):
                    os.remove(file_path)
            except OSError:
                # Log error but continue with deletion
                print(f"Failed to delete PDF file: {invoice.file_path}")
        
        # Finally delete the invoice
        db.delete(invoice)
        db.commit()
        
        return JSONResponse(status_code=200, content={"message": "Invoice deleted successfully"})
    except Exception as e:
        db.rollback()
        print(f"Error deleting invoice: {str(e)}")
        return JSONResponse(status_code=500, content={"message": f"Failed to delete invoice: {str(e)}"})
