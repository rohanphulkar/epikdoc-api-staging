from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from .schemas import ExpenseCreate, ExpenseUpdate, ExpenseResponse, PaymentCreate, PaymentUpdate, PaymentResponse, InvoiceCreate, InvoiceUpdate, InvoiceResponse
from .models import Expense, Payment, Invoice
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
        
        user = db.query(User).filter(User.id == decoded_token["id"]).first()
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
        
        user = db.query(User).filter(User.id == decoded_token["id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        expenses = db.query(Expense).filter(Expense.doctor_id == user.id).all()
        return JSONResponse(status_code=200, content={"expenses": expenses})
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
        
        user = db.query(User).filter(User.id == decoded_token["id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        expense = db.query(Expense).filter(Expense.id == expense_id).first()
        if not expense:
            return JSONResponse(status_code=404, content={"message": "Expense not found"})
        
        return JSONResponse(status_code=200, content={"expense": expense})
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
        
        user = db.query(User).filter(User.id == decoded_token["id"]).first()
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
        
        user = db.query(User).filter(User.id == decoded_token["id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        db.query(Expense).filter(Expense.id == expense_id).delete()
        db.commit()

        return JSONResponse(status_code=200, content={"message": "Expense deleted successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@payment_router.post("/create-payment",
    response_model=PaymentResponse,
    status_code=201,
    summary="Create new payment",
    description="""
    Create a new payment record.
    
    Required parameters:
    - date: Date of payment
    - patient_id: ID of the patient
    - amount: Amount paid

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
async def create_payment(request: Request, payment: PaymentCreate, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        payment_data = payment.model_dump()
        payment_data["doctor_id"] = user.id

        new_payment = Payment(**payment_data)
        db.add(new_payment)
        db.commit()
        db.refresh(new_payment)
    
        return JSONResponse(status_code=201, content={"message": "Payment created successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@payment_router.get("/get-payments",
    response_model=list[PaymentResponse],
    status_code=200,
    summary="Get all payments",
    description="""
    Get list of all payments for the logged in doctor.
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "List of payments retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        500: {"description": "Internal server error"}
    }
)
async def get_payments(request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        payments = db.query(Payment).filter(Payment.doctor_id == user.id).all()
        return JSONResponse(status_code=200, content={"payments": payments})
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
        
        user = db.query(User).filter(User.id == decoded_token["id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})

        payment = db.query(Payment).filter(Payment.id == payment_id).first()
        if not payment:
            return JSONResponse(status_code=404, content={"message": "Payment not found"})
        
        return JSONResponse(status_code=200, content={"payment": payment})
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
    db: Session = Depends(get_db)
):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["id"]).first()
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

        payments = query.all()
        return JSONResponse(status_code=200, content={"payments": payments})
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
    - patient_id: ID of the patient
    - amount: Amount paid
    
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
        
        user = db.query(User).filter(User.id == decoded_token["id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        payment_data = payment.model_dump()
        payment_data["doctor_id"] = user.id

        existing_payment = db.query(Payment).filter(Payment.id == payment_id).first()
        if not existing_payment:
            return JSONResponse(status_code=404, content={"message": "Payment not found"})

        for key, value in payment_data.items():
            setattr(existing_payment, key, value)

        db.commit()
        db.refresh(existing_payment)

        return JSONResponse(status_code=200, content={"message": "Payment updated successfully"})
    except Exception as e:
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
        500: {"description": "Internal server error"}
    }
)
async def delete_payment(request: Request, payment_id: str, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        db.query(Payment).filter(Payment.id == payment_id).delete()
        db.commit()

        return JSONResponse(status_code=200, content={"message": "Payment deleted successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@payment_router.post("/create-invoice",
    response_model=InvoiceResponse,
    status_code=201,
    summary="Create new invoice and generate PDF",
    description="""
    Create a new invoice record and generate a professional PDF invoice.
    
    Required fields:
    - patient_id: ID of the patient
    
    Optional fields:
    - date: Invoice date (defaults to current date)
    - invoice_number: Custom invoice number
    - treatment_name: Name of the treatment/procedure
    - unit_cost: Cost per unit
    - quantity: Number of units
    - discount: Discount amount or percentage (default: 0)
    - discount_type: "fixed" or "percentage" (default: fixed)
    - type: Invoice type
    - invoice_level_tax_discount: Tax discount percentage
    - tax_name: Name of tax
    - tax_percent: Tax percentage
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
            
        user = db.query(User).filter(User.id == decoded_token["id"]).first()
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
            "treatment_name": invoice.treatment_name or "General Consultation",
            "unit_cost": invoice.unit_cost or 0.0,
            "quantity": invoice.quantity or 1,
            "discount": invoice.discount or 0.0,
            "discount_type": invoice.discount_type or "fixed",
            "type": invoice.type,
            "invoice_level_tax_discount": invoice.invoice_level_tax_discount,
            "tax_name": invoice.tax_name,
            "tax_percent": invoice.tax_percent,
            "notes": invoice.notes,
            "description": invoice.description,
            "cancelled": False,
            "created_at": current_time,
            "updated_at": current_time
        }
        
        # Create invoice record
        new_invoice = Invoice(**invoice_data)
        db.add(new_invoice)
        db.commit()
        db.refresh(new_invoice)

        # Generate PDF invoice
        try:
            pdf_path = create_professional_invoice(
                id=invoice_data["id"],
                date=invoice_data["date"],
                patient_id=invoice_data["patient_id"],
                doctor_id=invoice_data["doctor_id"],
                patient_number=invoice_data["patient_number"],
                patient_name=invoice_data["patient_name"],
                doctor_name=invoice_data["doctor_name"],
                invoice_number=invoice_data["invoice_number"],
                treatment_name=invoice_data["treatment_name"],
                unit_cost=invoice_data["unit_cost"],
                quantity=invoice_data["quantity"],
                discount=invoice_data["discount"],
                discount_type=invoice_data["discount_type"].value,
                type=invoice_data["type"],
                invoice_level_tax_discount=invoice_data["invoice_level_tax_discount"],
                tax_name=invoice_data["tax_name"],
                tax_percent=invoice_data["tax_percent"],
                notes=invoice_data["notes"],
                description=invoice_data["description"]
            )
            
            # Update invoice with PDF path
            new_invoice.file_path = pdf_path
            db.commit()
            
        except Exception as e:
            # Log PDF generation error but don't fail the request
            print(f"Failed to generate PDF invoice: {str(e)}")
        
        return JSONResponse(status_code=201, content={"message": "Invoice created successfully"})
        
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"message": f"Failed to create invoice: {str(e)}"})

@payment_router.get("/get-invoices",
    response_model=list[InvoiceResponse],
    status_code=200,
    summary="Get all invoices",
    description="""
    Get list of all invoices for the logged in doctor.
    
    Required headers:
    - Authorization: Bearer token from doctor login
    """,
    responses={
        200: {"description": "List of invoices retrieved successfully"},
        401: {"description": "Unauthorized - Invalid token"},
        500: {"description": "Internal server error"}
    }
)
async def get_invoices(request: Request, db: Session = Depends(get_db)):
    try:
        decoded_token = verify_token(request)
        if not decoded_token:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        user = db.query(User).filter(User.id == decoded_token["id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        invoices = db.query(Invoice).filter(Invoice.doctor_id == user.id).all()
        return JSONResponse(status_code=200, content={"invoices": invoices})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})
    
@payment_router.get("/get-invoices-by-patient/{patient_id}",
    response_model=list[InvoiceResponse],
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
        
        user = db.query(User).filter(User.id == decoded_token["id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        invoices = db.query(Invoice).filter(Invoice.patient_id == patient_id).all()
        return JSONResponse(status_code=200, content={"invoices": invoices})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})

@payment_router.get("/get-invoice/{invoice_id}",
    response_model=InvoiceResponse,
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
        
        user = db.query(User).filter(User.id == decoded_token["id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice:
            return JSONResponse(status_code=404, content={"message": "Invoice not found"})
        
        return JSONResponse(status_code=200, content={"invoice": invoice})
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
    - treatment_name: Name of the treatment/procedure
    - unit_cost: Cost per unit
    - quantity: Number of units
    - discount: Discount amount or percentage
    - discount_type: "fixed" or "percentage"
    - type: Invoice type
    - invoice_level_tax_discount: Tax discount percentage
    - tax_name: Name of tax
    - tax_percent: Tax percentage
    - notes: Additional notes
    - description: Detailed description
    
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
        
        user = db.query(User).filter(User.id == decoded_token["id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        existing_invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not existing_invoice:
            return JSONResponse(status_code=404, content={"message": "Invoice not found"})
        
        for field, value in invoice.model_dump().items():
            setattr(existing_invoice, field, value)
        
        db.commit()
        db.refresh(existing_invoice)

        # Generate PDF invoice
        try:
            pdf_path = create_professional_invoice(
                id=existing_invoice.id or "",
                date=existing_invoice.date or datetime.now(),
                patient_id=existing_invoice.patient_id,
                doctor_id=existing_invoice.doctor_id or "",
                patient_number=existing_invoice.patient_number or "",
                patient_name=existing_invoice.patient_name or "",
                doctor_name=existing_invoice.doctor_name or "",
                invoice_number=existing_invoice.invoice_number or "",
                treatment_name=existing_invoice.treatment_name or "",
                unit_cost=existing_invoice.unit_cost or 0.0,
                quantity=existing_invoice.quantity or 0,
                discount=existing_invoice.discount or 0.0,
                discount_type=existing_invoice.discount_type.value if existing_invoice.discount_type else "fixed",
                type=existing_invoice.type,
                invoice_level_tax_discount=existing_invoice.invoice_level_tax_discount,
                tax_name=existing_invoice.tax_name,
                tax_percent=existing_invoice.tax_percent,
                notes=existing_invoice.notes,
                description=existing_invoice.description
            )

            # remove old pdf file
            if existing_invoice.file_path:
                os.remove(existing_invoice.file_path)
            
            existing_invoice.file_path = pdf_path
            db.commit()

        except Exception as e:
            # Log PDF generation error but don't fail the request
            print(f"Failed to generate PDF invoice: {str(e)}")
        return JSONResponse(status_code=200, content={"message": "Invoice updated successfully"})
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
        
        user = db.query(User).filter(User.id == decoded_token["id"]).first()
        if not user:
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        
        db.query(Invoice).filter(Invoice.id == invoice_id).delete()
        db.commit()
        
        return JSONResponse(status_code=200, content={"message": "Invoice deleted successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"message": f"Failed to delete invoice: {str(e)}"})
