from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from .models import DiscountType

class ExpenseResponse(BaseModel):
    id: str
    doctor_id: Optional[str]
    date: Optional[datetime]
    expense_type: Optional[str]
    description: Optional[str]
    amount: Optional[float]
    vendor_name: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

class ExpenseCreate(BaseModel):
    date: Optional[datetime] = None
    expense_type: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    vendor_name: Optional[str] = None

    class Config:
        from_attributes = True

class ExpenseUpdate(BaseModel):
    date: Optional[datetime] = None
    expense_type: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    vendor_name: Optional[str] = None

    class Config:
        from_attributes = True

class PaymentResponse(BaseModel):
    id: str
    date: Optional[datetime]
    patient_id: str
    doctor_id: Optional[str]
    patient_number: Optional[str]
    patient_name: Optional[str]
    receipt_number: Optional[str]
    treatment_name: Optional[str]
    amount_paid: Optional[float]
    invoice_number: Optional[str]
    notes: Optional[str]
    refund: Optional[bool]
    refund_receipt_number: Optional[str]
    refunded_amount: Optional[float]
    payment_mode: Optional[str]
    card_number: Optional[str]
    card_type: Optional[str]
    cheque_number: Optional[str]
    cheque_bank: Optional[str]
    netbanking_bank_name: Optional[str]
    vendor_name: Optional[str]
    vendor_fees_percent: Optional[float]
    cancelled: Optional[bool]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

class PaymentCreate(BaseModel):
    date: Optional[datetime] = None
    patient_id: str
    receipt_number: Optional[str] = None
    treatment_name: Optional[str] = None
    amount_paid: Optional[float] = None
    invoice_number: Optional[str] = None
    notes: Optional[str] = None
    refund: Optional[bool] = False
    refund_receipt_number: Optional[str] = None
    refunded_amount: Optional[float] = None
    payment_mode: Optional[str] = None
    card_number: Optional[str] = None
    card_type: Optional[str] = None
    cheque_number: Optional[str] = None
    cheque_bank: Optional[str] = None
    netbanking_bank_name: Optional[str] = None
    vendor_name: Optional[str] = None
    vendor_fees_percent: Optional[float] = None
    cancelled: Optional[bool] = False

    class Config:
        from_attributes = True

class PaymentUpdate(BaseModel):
    date: Optional[datetime] = None
    receipt_number: Optional[str] = None
    treatment_name: Optional[str] = None
    amount_paid: Optional[float] = None
    invoice_number: Optional[str] = None
    notes: Optional[str] = None
    refund: Optional[bool] = None
    refund_receipt_number: Optional[str] = None
    refunded_amount: Optional[float] = None
    payment_mode: Optional[str] = None
    card_number: Optional[str] = None
    card_type: Optional[str] = None
    cheque_number: Optional[str] = None
    cheque_bank: Optional[str] = None
    netbanking_bank_name: Optional[str] = None
    vendor_name: Optional[str] = None
    vendor_fees_percent: Optional[float] = None
    cancelled: Optional[bool] = None

    class Config:
        from_attributes = True

class InvoiceResponse(BaseModel):
    id: str
    date: Optional[datetime]
    patient_id: str
    doctor_id: Optional[str]
    patient_number: Optional[str]
    patient_name: Optional[str]
    doctor_name: Optional[str]
    invoice_number: Optional[str]
    treatment_name: Optional[str]
    unit_cost: Optional[float]
    quantity: Optional[int]
    discount: Optional[float]
    discount_type: Optional[DiscountType]
    type: Optional[str]
    invoice_level_tax_discount: Optional[float]
    tax_name: Optional[str]
    tax_percent: Optional[float]
    cancelled: Optional[bool]
    notes: Optional[str]
    description: Optional[str]
    file_path: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

class InvoiceCreate(BaseModel):
    date: Optional[datetime] = None
    patient_id: str
    invoice_number: Optional[str] = None
    treatment_name: Optional[str] = None
    unit_cost: Optional[float] = None
    quantity: Optional[int] = None
    discount: Optional[float] = None
    discount_type: Optional[DiscountType] = None
    type: Optional[str] = None
    invoice_level_tax_discount: Optional[float] = None
    tax_name: Optional[str] = None
    tax_percent: Optional[float] = None
    cancelled: Optional[bool] = False
    notes: Optional[str] = None
    description: Optional[str] = None

    class Config:
        from_attributes = True

class InvoiceUpdate(BaseModel):
    date: Optional[datetime] = None
    invoice_number: Optional[str] = None
    treatment_name: Optional[str] = None
    unit_cost: Optional[float] = None
    quantity: Optional[int] = None
    discount: Optional[float] = None
    discount_type: Optional[DiscountType] = None
    type: Optional[str] = None
    invoice_level_tax_discount: Optional[float] = None
    tax_name: Optional[str] = None
    tax_percent: Optional[float] = None
    cancelled: Optional[bool] = None
    notes: Optional[str] = None
    description: Optional[str] = None

    class Config:
        from_attributes = True
