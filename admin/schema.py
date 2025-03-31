from pydantic import BaseModel, ConfigDict, Field, EmailStr, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from payment.models import PaymentStatus, SubscriptionStatus, CouponType, CancellationStatus, InvoiceStatus
from enum import Enum

class BaseResponseModel(BaseModel):
    """Base model with common timestamp handling"""
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    def model_dump(self) -> Dict[str, Any]:
        data = super().model_dump()
        for field in ['created_at', 'updated_at']:
            if data.get(field):
                data[field] = data[field].isoformat()
        # Convert enum values to strings
        for key, value in data.items():
            if isinstance(value, Enum):
                data[key] = value.value
        return data

class UserType(str, Enum):
    ADMIN = "admin"
    DOCTOR = "doctor"

class AccountType(str, Enum):
    FREE_TRIAL = "free_trial"
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    MAX = "max"

BillingFrequency = str

class UserCreateSchema(BaseModel):
    name: str
    email: EmailStr
    phone: str
    password: str
    bio: Optional[str]
    profile_url: Optional[str]
    user_type: UserType = UserType.DOCTOR
    account_type: AccountType = AccountType.FREE_TRIAL
    billing_frequency: BillingFrequency = "monthly"
    data_sharing: bool = True
    email_alert: bool = True
    push_notification: bool = True
    newsletter: bool = True

    model_config = ConfigDict(from_attributes=True)

class UserResponse(BaseResponseModel):
    id: str = Field(..., description="Unique identifier for the user")
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: Optional[str] = None
    bio: Optional[str] = None
    profile_url: Optional[str] = None
    is_verified: bool = Field(..., description="Whether user's email is verified")
    is_superuser: bool = False
    is_active: bool = True
    user_type: UserType
    account_type: AccountType
    billing_frequency: BillingFrequency
    credits: int = Field(ge=0)
    credit_expiry: Optional[datetime]
    is_annual: bool = False
    last_credit_updated_at: Optional[datetime]
    data_sharing: bool = False
    tfa_enabled: bool = False
    email_alert: bool = True
    push_notification: bool = True
    newsletter: bool = False
    has_subscription: bool = False
    total_credits: int = Field(ge=0)
    used_credits: int = Field(ge=0)
    payment_link: Optional[str]

    def model_dump(self) -> Dict[str, Any]:
        data = super().model_dump()
        for field in ['credit_expiry', 'last_credit_updated_at']:
            if data.get(field):
                data[field] = data[field].isoformat()
        return data

    @validator('used_credits')
    def used_credits_cannot_exceed_total(cls, v, values):
        if 'total_credits' in values and v > values['total_credits']:
            raise ValueError('Used credits cannot exceed total credits')
        return v

class UserUpdateSchema(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[EmailStr]
    phone: Optional[str] = Field(None, pattern=r'^\+?[1-9]\d{1,14}$')
    bio: Optional[str] = Field(None, max_length=500)
    profile_url: Optional[str] = Field(None, pattern=r'^https?://.+')
    is_verified: Optional[bool]
    is_superuser: Optional[bool]
    is_active: Optional[bool]
    user_type: Optional[UserType]
    account_type: Optional[AccountType]
    billing_frequency: Optional[BillingFrequency]
    credits: Optional[int] = Field(None, ge=0)
    credit_expiry: Optional[datetime]
    is_annual: Optional[bool]
    last_credit_updated_at: Optional[datetime]
    data_sharing: Optional[bool]
    tfa_enabled: Optional[bool]
    email_alert: Optional[bool]
    push_notification: Optional[bool]
    newsletter: Optional[bool]
    has_subscription: Optional[bool]
    total_credits: Optional[int] = Field(None, ge=0)
    used_credits: Optional[int] = Field(None, ge=0)
    payment_link: Optional[str]

    model_config = ConfigDict(from_attributes=True)

    def model_dump(self) -> Dict[str, Any]:
        data = super().model_dump()
        for field in ['credit_expiry', 'last_credit_updated_at']:
            if data.get(field):
                data[field] = data[field].isoformat()
        return data

    @validator('used_credits')
    def used_credits_cannot_exceed_total(cls, v, values):
        if v is not None and 'total_credits' in values and values['total_credits'] is not None:
            if v > values['total_credits']:
                raise ValueError('Used credits cannot exceed total credits')
        return v

ContactTopic = str

CompanySize = str

class ContactResponse(BaseResponseModel):
    id: str
    first_name: str = Field(..., min_length=1, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)
    email: EmailStr
    topic: ContactTopic
    company_name: str = Field(..., min_length=1, max_length=100)
    company_size: CompanySize
    query: str = Field(..., min_length=10, max_length=1000)

class FeedbackResponse(BaseResponseModel):
    id: str
    user: str
    feedback: str = Field(..., min_length=10, max_length=1000)
    rating: int = Field(..., ge=1, le=5)
    suggestions: Optional[str] = Field(None, max_length=1000)

class InvoiceResponse(BaseResponseModel):
    id: str
    invoice_number: str = Field(..., pattern=r'^INV-\d{6}$')
    order_id: str
    status: InvoiceStatus
    file_path: Optional[str]

class CouponResponse(BaseResponseModel):
    id: str
    code: str = Field(..., min_length=3, max_length=20, pattern=r'^[A-Z0-9_-]+$')
    type: CouponType
    value: float = Field(..., ge=0)
    max_uses: Optional[int] = Field(None, gt=0)
    used_count: int = Field(0, ge=0)
    valid_from: datetime
    valid_until: Optional[datetime]
    is_active: bool = True

    def model_dump(self) -> Dict[str, Any]:
        data = super().model_dump()
        for field in ['valid_from', 'valid_until']:
            if data.get(field):
                data[field] = data[field].isoformat()
        return data

    @validator('valid_until')
    def valid_until_must_be_after_valid_from(cls, v, values):
        if v and 'valid_from' in values and v <= values['valid_from']:
            raise ValueError('valid_until must be after valid_from')
        return v

class CouponCreate(BaseModel):
    code: str = Field(..., min_length=3, max_length=20, pattern=r'^[A-Z0-9_-]+$')
    type: CouponType
    value: float = Field(..., ge=0)
    max_uses: Optional[int] = Field(None, gt=0)
    valid_from: datetime = Field(default_factory=datetime.now)
    valid_until: Optional[datetime]
    is_active: bool = True

    model_config = ConfigDict(from_attributes=True)

    @validator('valid_until')
    def valid_until_must_be_after_valid_from(cls, v, values):
        if v and 'valid_from' in values and v <= values['valid_from']:
            raise ValueError('valid_until must be after valid_from')
        return v

class OrderResponse(BaseResponseModel):
    id: str
    user: str
    user_email: Optional[str] = None
    user_name: Optional[str] = Field(None, min_length=1, max_length=100)  # Made optional
    user_phone: Optional[str] = None
    plan: str
    duration_months: int = Field(..., gt=0)
    billing_frequency: BillingFrequency
    coupon: Optional[CouponResponse]
    amount: float = Field(..., ge=0)
    discount_amount: float = Field(..., ge=0)
    final_amount: float = Field(..., ge=0)
    payment_id: Optional[str]
    status: PaymentStatus
    invoices: List[InvoiceResponse] = []

    @validator('final_amount')
    def validate_final_amount(cls, v, values):
        if 'amount' in values and 'discount_amount' in values:
            expected = values['amount'] - values['discount_amount']
            if abs(v - expected) > 0.01:  # Allow small floating point differences
                raise ValueError(f'final_amount ({v}) must equal amount ({values["amount"]}) minus discount_amount ({values["discount_amount"]})')
        return round(v, 2)

class OrderUpdate(BaseModel):
    plan: Optional[str]
    duration_months: Optional[int]
    billing_frequency: Optional[BillingFrequency]
    amount: Optional[float]
    discount_amount: Optional[float]
    final_amount: Optional[float]
    status: Optional[PaymentStatus]

class SubscriptionResponse(BaseResponseModel):
    id: str
    user: str
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    user_phone: Optional[str] = None
    subscription_id: str
    plan: str
    plan_type: str
    start_date: datetime
    end_date: datetime
    status: SubscriptionStatus
    payment_id: Optional[str]
    auto_renew: bool = True
    cancelled_at: Optional[datetime]
    orders: List[OrderResponse] = []

    def model_dump(self) -> Dict[str, Any]:
        data = super().model_dump()
        for field in ['start_date', 'end_date', 'cancelled_at']:
            if data.get(field):
                data[field] = data[field].isoformat()
        return data

    @validator('end_date')
    def end_date_must_be_after_start_date(cls, v, values):
        if 'start_date' in values and v <= values['start_date']:
            raise ValueError('end_date must be after start_date')
        return v

class SubscriptionUpdate(BaseModel):
    status: Optional[SubscriptionStatus]
    auto_renew: Optional[bool]
    cancelled_at: Optional[datetime]

class CouponUpdate(BaseModel):
    value: Optional[float] = Field(None, ge=0)
    max_uses: Optional[int] = Field(None, gt=0)
    valid_until: Optional[datetime]
    is_active: Optional[bool]

class CancellationRequestResponse(BaseResponseModel):
    id: str
    user: str
    user_email: EmailStr
    user_name: str = Field(..., min_length=1, max_length=100)
    user_phone: str = Field(..., pattern=r'^\+?[1-9]\d{1,14}$')
    subscription: str
    reason: str = Field(..., min_length=10, max_length=500)
    feedback: Optional[str] = Field(None, max_length=1000)
    status: CancellationStatus

class CancellationRequestUpdate(BaseModel):
    status: Optional[CancellationStatus]
    feedback: Optional[str] = Field(None, max_length=1000)

class InvoiceUpdate(BaseModel):
    status: Optional[InvoiceStatus]
    file_path: Optional[str]

class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"

class PatientDetailResponse(BaseResponseModel):
    id: str
    doctor_id: str
    first_name: str = Field(..., min_length=1, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)
    phone: str
    age: int = Field(..., ge=0, le=150)
    gender: Gender
    xrays: List["PatientXrayDetail"] = []

class DeletedLabelDetail(BaseResponseModel):
    id: str
    label_id: str
    prediction_data: str

class LabelDetail(BaseResponseModel):
    id: str
    prediction_id: str
    name: str = Field(..., min_length=1, max_length=100)
    percentage: float = Field(..., ge=0, le=100)
    include: bool = True
    color_hex: str = Field(..., pattern=r'^#[0-9A-Fa-f]{6}$')
    deleted_labels: List[DeletedLabelDetail] = []

class PredictionDetail(BaseResponseModel):
    id: str
    patient: str
    original_image: str
    is_annotated: bool = False
    predicted_image: Optional[str]
    prediction: str
    notes: Optional[str] = Field(None, max_length=1000)
    labels: List[LabelDetail] = []

class PatientXrayDetail(BaseResponseModel):
    id: str
    patient: str
    prediction_id: Optional[str]
    original_image: str
    annotated_image: Optional[str]
    is_opg: bool = False
    prediction: Optional[PredictionDetail] = None

class PatientFullDetailResponse(BaseResponseModel):
    id: str
    doctor_id: str
    first_name: str = Field(..., min_length=1, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)
    phone: str
    age: int = Field(..., ge=0, le=150)
    gender: Gender
    xrays: List[PatientXrayDetail] = []
    predictions: List[PredictionDetail] = []
    total_xrays: int = Field(0, ge=0)
    total_predictions: int = Field(0, ge=0)
    total_labels: int = Field(0, ge=0)

    def model_dump(self) -> Dict[str, Any]:
        data = super().model_dump()
        
        # Calculate totals
        data['total_xrays'] = len(data['xrays'])
        data['total_predictions'] = len(data['predictions'])
        data['total_labels'] = sum(len(pred['labels']) for pred in data['predictions'])
        
        return data

class PatientUpdate(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=50)
    last_name: Optional[str] = Field(None, min_length=1, max_length=50)
    phone: Optional[str]
    age: Optional[int] = Field(None, ge=0, le=150)
    gender: Optional[Gender]

    model_config = ConfigDict(from_attributes=True)


class TicketStatus(str, Enum):
    OPEN = "open"
    PENDING = "pending" 
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"

class TicketPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class SupportTicketResponse(BaseModel):
    id: str
    user: str
    title: str
    description: str
    status: TicketStatus
    priority: TicketPriority
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda dt: dt.isoformat()
        }
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "user": "user123",
                "title": "Issue with login",
                "description": "Unable to login to the application",
                "status": "open",
                "priority": "high",
                "created_at": "2023-01-01T12:00:00",
                "updated_at": "2023-01-01T12:00:00"
            }
        }

class SupportTicketUpdate(BaseModel):
    status: Optional[TicketStatus]
    priority: Optional[TicketPriority]

    model_config = ConfigDict(from_attributes=True)