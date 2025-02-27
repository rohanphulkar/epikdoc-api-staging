from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse
from auth.model import User
from patients.model import Patient, Gender, PatientXray
from payment.models import Order, PaymentStatus, Subscription, SubscriptionStatus, Coupon, CancellationRequest, Invoice
from predict.model import Prediction, Label, DeletedLabel
from contact.model import ContactUs
from feedback.model import Feedback
from .schema import *
from db.db import get_db
from sqlalchemy.orm import Session
from utils.auth import get_current_user, signJWT, verify_password, validate_email, validate_phone, validate_password, get_password_hash
from datetime import datetime
from sqlalchemy import func, case, or_, desc, asc
from typing import List
from math import ceil
from support.model import Chat, Message, SupportTicket, TicketStatus, TicketPriority

admin_router = APIRouter(
    prefix="/admin-api",
    tags=["admin"],
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Not found"},
        500: {"description": "Internal server error"}
    }
)

# Auth middleware
def is_admin(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    user = db.query(User).filter(User.id == user_id).first()
    if not user or str(user.user_type) != "admin":
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    return True

@admin_router.post("/login", response_model=dict, status_code=200, summary="Login admin user")
async def login(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
        email = data.get("email")
        password = data.get("password")

        if not email or not password:
            return JSONResponse(status_code=400, content={"error": "Email and password are required"})

        user = db.query(User).filter(User.email == email).first()
        
        if not user:
            return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
            
        if str(user.user_type) != "admin":
            return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
            
        if not user.is_active:
            return JSONResponse(status_code=401, content={"error": "Your account is deactivated or deleted. Please contact support."})

        if not verify_password(password, str(user.password)):
            return JSONResponse(status_code=401, content={"error": "Invalid credentials"})
        
        jwt_token = signJWT(str(user.id))
        return JSONResponse(status_code=200, content={
            "access_token": jwt_token["access_token"], 
            "token_type": "bearer",
            "message": "Login successful"
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# User Routes
@admin_router.get(
    "/users",
    summary="Get all users",
    response_model=List[UserResponse],
    dependencies=[Depends(is_admin)]
)
async def get_users(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by name or email"),
    user_type: Optional[str] = Query(None, description="Filter by user type"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    account_type: Optional[str] = Query(None, description="Filter by account type"),
    has_subscription: Optional[bool] = Query(None, description="Filter by subscription status"),
    sort_by: str = Query("created_at", description="Sort by field"),
    sort_order: str = Query("desc", description="Sort order (asc/desc)")
):
    try:
        # Start with base query
        query = db.query(User)

        # Apply search filter
        if search:
            search = f"%{search}%"
            query = query.filter(
                or_(
                    User.name.ilike(search),
                    User.email.ilike(search)
                )
            )

        # Apply filters
        if user_type:
            query = query.filter(User.user_type == user_type)
        if is_active is not None:
            query = query.filter(User.is_active == is_active)
        if account_type:
            query = query.filter(User.account_type == account_type)
        if has_subscription is not None:
            query = query.filter(User.has_subscription == has_subscription)

        # Get total count before pagination
        total_count = query.count()

        # Apply sorting
        if hasattr(User, sort_by):
            sort_column = getattr(User, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(desc(sort_column))
            else:
                query = query.order_by(asc(sort_column))

        # Apply pagination
        offset = (page - 1) * limit
        query = query.offset(offset).limit(limit)

        # Execute query
        users = query.all()

        return JSONResponse(
            status_code=200,
            content={
                "users": [UserResponse.model_validate(user).model_dump() for user in users],
                "pagination": {
                    "total": total_count,
                    "page": page,
                    "limit": limit,
                    "total_pages": ceil(total_count / limit)
                }
            }
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@admin_router.get(
    "/user/{user_id}",
    summary="Get user by ID", 
    response_model=UserResponse,
    dependencies=[Depends(is_admin)]
)
async def get_user(user_id: str, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        return JSONResponse(status_code=200, content={"user": UserResponse.model_validate(user).model_dump()})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    

@admin_router.post(
    "/user/create",
    summary="Create user",
    response_model=UserResponse,
    dependencies=[Depends(is_admin)]
)
async def create_user(user_create: UserCreateSchema, db: Session = Depends(get_db)):
    try:
        if not user_create.email or not user_create.password or not user_create.name or not user_create.phone:
            return JSONResponse(status_code=400, content={"error": "All fields are required"})

        if not validate_email(user_create.email):
            return JSONResponse(status_code=400, content={"error": "Invalid email format"})
        if not validate_phone(user_create.phone):
            return JSONResponse(status_code=400, content={"error": "Invalid phone number"})
        if not validate_password(user_create.password):
            return JSONResponse(status_code=400, content={"error": "Password must contain at least 8 characters, one uppercase letter, one lowercase letter, and one number"})
        
        # Check if user exists with same email
        email_exists = db.query(User).filter(User.email == user_create.email).first()
        if email_exists:
            return JSONResponse(status_code=400, content={"error": "User already exists with this email"})

        # Check if user exists with same phone
        phone_exists = db.query(User).filter(User.phone == user_create.phone).first()
        if phone_exists:
            return JSONResponse(status_code=400, content={"error": "User already exists with this phone number"})
        
        hashed_password = get_password_hash(user_create.password)
        new_user = User(
            email=user_create.email,
            password=hashed_password,
            name=user_create.name,
            phone=user_create.phone,
            bio=user_create.bio,
            profile_url=user_create.profile_url,
            user_type=user_create.user_type,
            account_type=user_create.account_type,
            billing_frequency=user_create.billing_frequency,
            data_sharing=user_create.data_sharing,
            email_alert=user_create.email_alert,
            push_notification=user_create.push_notification,
            newsletter=user_create.newsletter,
            is_active=True
        )
        if user_create.user_type == UserType.ADMIN:
            setattr(new_user, 'is_superuser', True)
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return JSONResponse(status_code=201, content={"message": "User created successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@admin_router.patch(
    "/user/{user_id}",
    summary="Update user",
    response_model=UserResponse, 
    dependencies=[Depends(is_admin)]
)
async def update_user(user_id: str, user_update: UserUpdateSchema, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
            
        # Update user fields directly from the request data
        if user_update.name is not None:
            user.name = user_update.name
        if user_update.email is not None:
            user.email = user_update.email
        if user_update.phone is not None:
            user.phone = user_update.phone
        if user_update.account_type is not None:
            user.account_type = user_update.account_type
        if user_update.user_type is not None:
            user.user_type = user_update.user_type
        if user_update.credits is not None:
            user.credits = user_update.credits
        if user_update.total_credits is not None:
            user.total_credits = user_update.total_credits
        if user_update.is_active is not None:
            user.is_active = user_update.is_active
            
        db.commit()
        db.refresh(user)
        
        # Convert user object to dict for response
        user_dict = {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "phone": user.phone,
            "account_type": user.account_type,
            "user_type": user.user_type,
            "credits": user.credits,
            "total_credits": user.total_credits,
            "is_active": user.is_active
        }
        
        return JSONResponse(status_code=200, content={"user": user_dict})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@admin_router.delete(
    "/user/{user_id}",
    summary="Delete user",
    dependencies=[Depends(is_admin)]
)
async def delete_user(user_id: str, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        db.delete(user)
        db.commit()
        return JSONResponse(status_code=200, content={"message": "User deleted successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

# Patient Routes
@admin_router.get(
    "/patients",
    summary="Get all patients",
    response_model=List[PatientDetailResponse],
    dependencies=[Depends(is_admin)]
)
async def get_patients(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by name or phone"),
    gender: Optional[str] = Query(None, description="Filter by gender"),
    age_min: Optional[int] = Query(None, ge=0, description="Minimum age"),
    age_max: Optional[int] = Query(None, ge=0, description="Maximum age"),
    sort_by: str = Query("created_at", description="Sort by field"),
    sort_order: str = Query("desc", description="Sort order (asc/desc)")
):
    try:
        # Start with base query
        query = db.query(Patient)

        # Apply search filter
        if search:
            search = f"%{search}%"
            query = query.filter(
                or_(
                    Patient.first_name.ilike(search),
                    Patient.last_name.ilike(search),
                    Patient.phone.ilike(search)
                )
            )

        # Apply filters
        if gender:
            query = query.filter(Patient.gender == gender)
        if age_min is not None:
            query = query.filter(Patient.age >= age_min)
        if age_max is not None:
            query = query.filter(Patient.age <= age_max)

        # Get total count before pagination
        total_count = query.count()

        # Apply sorting
        if hasattr(Patient, sort_by):
            sort_column = getattr(Patient, sort_by)
            if sort_order == "desc":
                query = query.order_by(desc(sort_column))
            else:
                query = query.order_by(asc(sort_column))

        # Apply pagination
        query = query.offset((page - 1) * limit).limit(limit)
        patients = query.all()

        # Calculate pagination metadata
        total_pages = ceil(total_count / limit)
        has_next = page < total_pages
        has_prev = page > 1

        return JSONResponse(status_code=200, content={
            "patients": [PatientDetailResponse.model_validate(patient).model_dump() for patient in patients],
            "pagination": {
                "total": total_count,
                "page": page,
                "size": limit,
                "pages": total_pages,
                "has_next": has_next,
                "has_prev": has_prev
            }
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@admin_router.get(
    "/patient/{patient_id}",
    summary="Get patient by ID",
    response_model=PatientFullDetailResponse,
    dependencies=[Depends(is_admin)]
)
async def get_patient(patient_id: str, db: Session = Depends(get_db)):
    try:
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return JSONResponse(status_code=404, content={"error": "Patient not found"})
        return JSONResponse(status_code=200, content={"patient": PatientFullDetailResponse.model_validate(patient).model_dump()})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@admin_router.patch(
    "/patient/{patient_id}",
    summary="Update patient",
    response_model=PatientDetailResponse,
    dependencies=[Depends(is_admin)]
)
async def update_patient(patient_id: str, patient_update: PatientUpdate, db: Session = Depends(get_db)):
    try:
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return JSONResponse(status_code=404, content={"error": "Patient not found"})
            
        update_data = patient_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(patient, key, value)
            
        db.commit()
        db.refresh(patient)
        return JSONResponse(status_code=200, content={"patient": PatientDetailResponse.model_validate(patient).model_dump()})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})
    

@admin_router.delete(
    "/patient/{patient_id}",
    summary="Delete patient",
    dependencies=[Depends(is_admin)]
)
async def delete_patient(patient_id: str, db: Session = Depends(get_db)):
    try:
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        if not patient:
            return JSONResponse(status_code=404, content={"error": "Patient not found"})
            
        # Delete in correct order to handle foreign key constraints
        predictions = db.query(Prediction).filter(Prediction.patient == patient_id).all()
        
        for prediction in predictions:
            # First delete deleted_labels that reference labels
            labels = db.query(Label).filter(Label.prediction_id == prediction.id).all()
            for label in labels:
                deleted_labels = db.query(DeletedLabel).filter(DeletedLabel.label_id == label.id).all()
                for deleted_label in deleted_labels:
                    db.delete(deleted_label)
            db.commit()
            
            # Now delete labels
            for label in labels:
                db.delete(label)
            db.commit()
            
            # Delete prediction
            db.delete(prediction)
            db.commit()

        # Delete xrays
        xrays = db.query(PatientXray).filter(PatientXray.patient == patient_id).all()
        for xray in xrays:
            db.delete(xray)
        db.commit()
            
        # Finally delete patient
        db.delete(patient)
        db.commit()
        
        return JSONResponse(status_code=200, content={"message": "Patient and associated data deleted successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

# Order Routes
@admin_router.get(
    "/orders",
    summary="Get all orders",
    response_model=List[OrderResponse],
    dependencies=[Depends(is_admin)]
)
async def get_orders(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by payment_id"),
    status: Optional[PaymentStatus] = Query(None, description="Filter by payment status"),
    plan: Optional[str] = Query(None, description="Filter by plan"),
    billing_frequency: Optional[str] = Query(None, description="Filter by billing frequency"),
    min_amount: Optional[float] = Query(None, ge=0, description="Filter by minimum amount"),
    max_amount: Optional[float] = Query(None, ge=0, description="Filter by maximum amount"),
    sort_by: str = Query("created_at", description="Sort by field"),
    sort_order: str = Query("desc", description="Sort order (asc/desc)")
):
    try:
        # Start with base query
        query = db.query(Order)

        # Apply search filter
        if search:
            query = query.filter(Order.payment_id.ilike(f"%{search}%"))

        # Apply filters
        if status:
            query = query.filter(Order.status == status)
        if plan:
            query = query.filter(Order.plan == plan)
        if billing_frequency:
            query = query.filter(Order.billing_frequency == billing_frequency)
        if min_amount is not None:
            query = query.filter(Order.final_amount >= min_amount)
        if max_amount is not None:
            query = query.filter(Order.final_amount <= max_amount)

        # Get total count before pagination
        total_count = query.count()

        # Apply sorting
        if hasattr(Order, sort_by):
            sort_column = getattr(Order, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(desc(sort_column))
            else:
                query = query.order_by(asc(sort_column))

        # Apply pagination
        query = query.offset((page - 1) * limit).limit(limit)
        orders = query.all()

        # Calculate pagination metadata
        total_pages = ceil(total_count / limit)
        has_next = page < total_pages
        has_prev = page > 1

        return JSONResponse(status_code=200, content={
            "orders": [OrderResponse.model_validate(order).model_dump() for order in orders],
            "pagination": {
                "total": total_count,
                "page": page,
                "size": limit,
                "pages": total_pages,
                "has_next": has_next,
                "has_prev": has_prev
            }
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@admin_router.get("/order/{order_id}",
    summary="Get order by ID",
    response_model=OrderResponse
)
async def get_order(request: Request, order_id: str, db: Session = Depends(get_db)):
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return JSONResponse(status_code=404, content={"error": "Order not found"})
        
        order_user = db.query(User).filter(User.id == order.user).first()
        
        user_details = {
            "name": "Deleted User",
            "email": "deleted@user.com",
            "phone": "N/A"
        } if order_user is None else {
            "name": order_user.name,
            "email": order_user.email,
            "phone": order_user.phone
        }

        # Get associated invoice if exists
        invoice = db.query(Invoice).filter(Invoice.order_id == order.id).first()
        invoice_url = f"{request.base_url}{invoice.file_path}" if invoice else None
        
        order_details = {
            "id": order.id,
            "user": user_details,
            "plan": order.plan,
            "duration_months": order.duration_months,
            "billing_frequency": order.billing_frequency,
            "coupon": order.coupon,
            "amount": float(order.amount),
            "discount_amount": float(order.discount_amount),
            "final_amount": float(order.final_amount),
            "payment_id": order.payment_id,
            "status": order.status.value,
            "invoice_url": invoice_url,
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat()
        }

        return JSONResponse(status_code=200, content=order_details)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to get order: {str(e)}"})
    
@admin_router.patch(
    "/order/{order_id}",
    summary="Update order", 
    response_model=OrderResponse,
    dependencies=[Depends(is_admin)]
)
async def update_order(order_id: str, order_update: OrderUpdate, db: Session = Depends(get_db)):
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return JSONResponse(status_code=404, content={"error": "Order not found"})
            
        # Update fields directly from the request model
        if order_update.plan is not None:
            order.plan = order_update.plan
        if order_update.duration_months is not None:
            order.duration_months = order_update.duration_months
        if order_update.billing_frequency is not None:
            order.billing_frequency = order_update.billing_frequency
        if order_update.amount is not None:
            order.amount = order_update.amount
        if order_update.discount_amount is not None:
            order.discount_amount = order_update.discount_amount
        if order_update.final_amount is not None:
            order.final_amount = order_update.final_amount
        if order_update.status is not None:
            order.status = order_update.status
            
        db.commit()
        db.refresh(order)
        
        # Convert order to dict for response
        order_dict = {
            "id": order.id,
            "plan": order.plan,
            "duration_months": order.duration_months,
            "billing_frequency": order.billing_frequency,
            "amount": float(order.amount),
            "discount_amount": float(order.discount_amount),
            "final_amount": float(order.final_amount),
            "status": order.status.value,
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat()
        }
        
        return JSONResponse(status_code=200, content={"order": order_dict})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@admin_router.delete(
    "/order/{order_id}",
    summary="Delete order",
    dependencies=[Depends(is_admin)]
)
async def delete_order(order_id: str, db: Session = Depends(get_db)):
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            return JSONResponse(status_code=404, content={"error": "Order not found"})
        
        # Delete associated invoice
        invoice = db.query(Invoice).filter(Invoice.order_id == order_id).all()
        for inv in invoice: 
            db.delete(inv)
            db.commit()
        
        db.delete(order)
        db.commit()
        return JSONResponse(status_code=200, content={"message": "Order deleted successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

# Subscription Routes
@admin_router.get(
    "/subscriptions",
    summary="Get all subscriptions", 
    response_model=List[SubscriptionResponse],
    dependencies=[Depends(is_admin)]
)
async def get_subscriptions(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by subscription_id"),
    status: Optional[SubscriptionStatus] = Query(None, description="Filter by subscription status"),
    plan: Optional[str] = Query(None, description="Filter by plan"),
    plan_type: Optional[str] = Query(None, description="Filter by plan type"),
    auto_renew: Optional[bool] = Query(None, description="Filter by auto renew status"),
    sort_by: str = Query("created_at", description="Sort by field"),
    sort_order: str = Query("desc", description="Sort order (asc/desc)")
):
    try:
        # Start with base query
        query = db.query(Subscription)

        # Apply search filter
        if search:
            query = query.filter(Subscription.subscription_id.ilike(f"%{search}%"))

        # Apply filters
        if status:
            query = query.filter(Subscription.status == status)
        if plan:
            query = query.filter(Subscription.plan == plan)
        if plan_type:
            query = query.filter(Subscription.plan_type == plan_type)
        if auto_renew is not None:
            query = query.filter(Subscription.auto_renew == auto_renew)

        # Get total count before pagination
        total_count = query.count()

        # Apply sorting
        if hasattr(Subscription, sort_by):
            sort_column = getattr(Subscription, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(desc(sort_column))
            else:
                query = query.order_by(asc(sort_column))

        # Apply pagination
        query = query.offset((page - 1) * limit).limit(limit)
        subscriptions = query.all()

        return JSONResponse(
            status_code=200,
            content={
                "subscriptions": [SubscriptionResponse.model_validate(subscription).model_dump() for subscription in subscriptions],
                "total": total_count,
                "page": page,
                "limit": limit,
                "pages": (total_count + limit - 1) // limit
            }
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@admin_router.get("/subscription/{subscription_id}",
    summary="Get subscription by ID",
    response_model=SubscriptionResponse
)
async def get_subscription(request: Request, subscription_id: str, db: Session = Depends(get_db)):
    try:
        subscription = db.query(Subscription).filter(Subscription.id == subscription_id).first()
        if not subscription:
            return JSONResponse(status_code=404, content={"error": "Subscription not found"})
        
        sub_user = db.query(User).filter(User.id == subscription.user).first()
        user_details = {
            "name": "Deleted User",
            "email": "deleted@user.com",
            "phone": "N/A"
        } if sub_user is None else {
            "name": sub_user.name,
            "email": sub_user.email,
            "phone": sub_user.phone
        }

        # Get associated invoice if exists
        invoice = db.query(Invoice).filter(Invoice.order_id == subscription.payment_id).first()
        invoice_url = f"{request.base_url}{invoice.file_path}" if invoice else None

        subscription_details = {
            "id": subscription.id,
            "user": user_details,
            "subscription_id": subscription.subscription_id,
            "plan": subscription.plan,
            "plan_type": subscription.plan_type,
            "start_date": subscription.start_date.isoformat(),
            "end_date": subscription.end_date.isoformat(),
            "status": subscription.status.value,
            "payment_id": subscription.payment_id,
            "auto_renew": subscription.auto_renew,
            "invoice_url": invoice_url,
            "cancelled_at": subscription.cancelled_at.isoformat() if subscription.cancelled_at else None,
            "created_at": subscription.created_at.isoformat(),
            "updated_at": subscription.updated_at.isoformat()
        }

        return JSONResponse(status_code=200, content=subscription_details)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to get subscription: {str(e)}"})

@admin_router.patch(
    "/subscription/{subscription_id}",
    summary="Update subscription",
    response_model=SubscriptionResponse,
    dependencies=[Depends(is_admin)]
)
async def update_subscription(subscription_id: str, subscription_update: SubscriptionUpdate, db: Session = Depends(get_db)):
    try:
        subscription = db.query(Subscription).filter(Subscription.id == subscription_id).first()
        if not subscription:
            return JSONResponse(status_code=404, content={"error": "Subscription not found"})
            
        update_data = subscription_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(subscription, key, value)
            
        db.commit()
        db.refresh(subscription)
        return JSONResponse(status_code=200, content={"subscription": SubscriptionResponse.model_validate(subscription).model_dump()})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@admin_router.delete(
    "/subscription/{subscription_id}",
    summary="Delete subscription",
    dependencies=[Depends(is_admin)]
)
async def delete_subscription(subscription_id: str, db: Session = Depends(get_db)):
    try:
        subscription = db.query(Subscription).filter(Subscription.id == subscription_id).first()
        if not subscription:
            return JSONResponse(status_code=404, content={"error": "Subscription not found"})
        db.delete(subscription)
        db.commit()
        return JSONResponse(status_code=200, content={"message": "Subscription deleted successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

# Coupon Routes
@admin_router.get(
    "/coupons",
    summary="Get all coupons",
    response_model=List[CouponResponse],
    dependencies=[Depends(is_admin)]
)
async def get_coupons(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by coupon code"),
    coupon_type: Optional[CouponType] = Query(None, description="Filter by coupon type"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    min_value: Optional[float] = Query(None, ge=0, description="Filter by minimum value"),
    max_value: Optional[float] = Query(None, ge=0, description="Filter by maximum value"),
    sort_by: str = Query("created_at", description="Sort by field"),
    sort_order: str = Query("desc", description="Sort order (asc/desc)")
):
    try:
        # Start with base query
        query = db.query(Coupon)

        # Apply search filter
        if search:
            query = query.filter(Coupon.code.ilike(f"%{search}%"))

        # Apply filters
        if coupon_type:
            query = query.filter(Coupon.type == coupon_type)
        if is_active is not None:
            query = query.filter(Coupon.is_active == is_active)
        if min_value is not None:
            query = query.filter(Coupon.value >= min_value)
        if max_value is not None:
            query = query.filter(Coupon.value <= max_value)

        # Get total count before pagination
        total_count = query.count()

        # Apply sorting
        if hasattr(Coupon, sort_by):
            sort_column = getattr(Coupon, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(desc(sort_column))
            else:
                query = query.order_by(asc(sort_column))

        # Apply pagination
        query = query.offset((page - 1) * limit).limit(limit)
        coupons = query.all()

        return JSONResponse(
            status_code=200, 
            content={
                "coupons": [CouponResponse.model_validate(coupon).model_dump() for coupon in coupons],
                "total": total_count,
                "page": page,
                "limit": limit,
                "pages": (total_count + limit - 1) // limit
            }
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@admin_router.get(
    "/coupon/{coupon_id}",
    summary="Get coupon by ID",
    response_model=CouponResponse,
    dependencies=[Depends(is_admin)]
)
async def get_coupon(coupon_id: str, db: Session = Depends(get_db)):
    try:
        coupon = db.query(Coupon).filter(Coupon.id == coupon_id).first()
        if not coupon:
            return JSONResponse(status_code=404, content={"error": "Coupon not found"})
        return JSONResponse(status_code=200, content={"coupon": CouponResponse.model_validate(coupon).model_dump()})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@admin_router.post(
    "/coupon/create", 
    summary="Create coupon",
    response_model=CouponResponse,
    dependencies=[Depends(is_admin)]
)
async def create_coupon(coupon: CouponCreate, db: Session = Depends(get_db)):
    try:
        # Validate coupon data
        if coupon.valid_until and coupon.valid_until < coupon.valid_from:
            return JSONResponse(status_code=422, content={"error": "Valid until date must be after valid from date"})
            
        if coupon.max_uses is not None and coupon.max_uses <= 0:
            return JSONResponse(status_code=422, content={"error": "Max uses must be greater than 0"})
            
        if coupon.value <= 0:
            return JSONResponse(status_code=422, content={"error": "Value must be greater than 0"})
            
        if coupon.type == CouponType.PERCENTAGE and coupon.value > 100:
            return JSONResponse(status_code=422, content={"error": "Percentage value cannot be greater than 100"})

        # Check if coupon code already exists
        existing_coupon = db.query(Coupon).filter(Coupon.code == coupon.code.upper()).first()
        if existing_coupon:
            return JSONResponse(status_code=422, content={"error": "Coupon code already exists"})

        new_coupon = Coupon(**coupon.model_dump())
        db.add(new_coupon)
        db.commit()
        db.refresh(new_coupon)
        return JSONResponse(status_code=201, content={"coupon": CouponResponse.model_validate(new_coupon).model_dump()})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@admin_router.patch(
    "/coupon/{coupon_id}",
    summary="Update coupon",
    response_model=CouponResponse,
    dependencies=[Depends(is_admin)]
)
async def update_coupon(coupon_id: str, coupon: CouponUpdate, db: Session = Depends(get_db)):
    try:
        existing_coupon = db.query(Coupon).filter(Coupon.id == coupon_id).first()
        if not existing_coupon:
            return JSONResponse(status_code=404, content={"error": "Coupon not found"})
            
        update_data = coupon.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(existing_coupon, key, value)
            
        db.commit()
        db.refresh(existing_coupon)
        return JSONResponse(status_code=200, content={"coupon": CouponResponse.model_validate(existing_coupon).model_dump()})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@admin_router.delete(
    "/coupon/{coupon_id}",
    summary="Delete coupon",
    dependencies=[Depends(is_admin)]
)
async def delete_coupon(coupon_id: str, db: Session = Depends(get_db)):
    try:
        coupon = db.query(Coupon).filter(Coupon.id == coupon_id).first()
        if not coupon:
            return JSONResponse(status_code=404, content={"error": "Coupon not found"})
        db.delete(coupon)
        db.commit()
        return JSONResponse(status_code=200, content={"message": "Coupon deleted successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@admin_router.get(
    "/dashboard",
    summary="Get dashboard stats",
    dependencies=[Depends(is_admin)]
)
async def get_dashboard_stats(db: Session = Depends(get_db)):
    try:
        # User statistics
        total_users = db.query(User).count()
        active_users = db.query(User).filter(User.is_active == True).count()
        premium_users = db.query(User).filter(User.has_subscription == True).count()
        trial_users = db.query(User).filter(User.account_type == "free_trial").count()
        verified_users = db.query(User).filter(User.is_verified == True).count()
        tfa_enabled_users = db.query(User).filter(User.tfa_enabled == True).count()
        
        # User growth metrics
        user_growth = db.query(
            func.date_format(User.created_at, '%Y-%m').label('month'),
            func.count(User.id).label('count')
        ).group_by(func.date_format(User.created_at, '%Y-%m')).all()

        # User engagement metrics
        newsletter_subscribers = db.query(User).filter(User.newsletter == True).count()
        push_notification_enabled = db.query(User).filter(User.push_notification == True).count()
        email_alerts_enabled = db.query(User).filter(User.email_alert == True).count()

        # Credit usage statistics
        total_credits_allocated = db.query(func.sum(User.total_credits)).scalar() or 0
        total_credits_used = db.query(func.sum(User.used_credits)).scalar() or 0
        avg_credits_per_user = db.query(func.avg(User.total_credits)).scalar() or 0

        # Prediction statistics
        total_predictions = db.query(Prediction).count()
        annotated_predictions = db.query(Prediction).filter(Prediction.is_annotated == True).count()
        
        # Predictions by month
        prediction_growth = db.query(
            func.date_format(Prediction.created_at, '%Y-%m').label('month'),
            func.count(Prediction.id).label('count')
        ).group_by(func.date_format(Prediction.created_at, '%Y-%m')).all()

        # Patient demographics
        total_patients = db.query(Patient).count()
        avg_patient_age = db.query(func.avg(Patient.age)).scalar() or 0
        patients_by_gender = db.query(
            Patient.gender,
            func.count(Patient.id).label('count')
        ).group_by(Patient.gender).all()

        patients_by_age_group = db.query(
            case(
                (Patient.age < 18, 'Under 18'),
                (Patient.age.between(18, 30), '18-30'),
                (Patient.age.between(31, 50), '31-50'),
                (Patient.age.between(51, 70), '51-70'),
                else_='Over 70'
            ).label('age_group'),
            func.count(Patient.id).label('count')
        ).group_by('age_group').all()

        # Payment and revenue metrics
        total_revenue = db.query(func.sum(Order.final_amount))\
            .filter(Order.status == PaymentStatus.PAID).scalar() or 0
        avg_order_value = db.query(func.avg(Order.final_amount))\
            .filter(Order.status == PaymentStatus.PAID).scalar() or 0
            
        revenue_by_month = db.query(
            func.date_format(Order.created_at, '%Y-%m').label('month'),
            func.sum(Order.final_amount).label('revenue'),
            func.count(Order.id).label('order_count')
        ).filter(Order.status == PaymentStatus.PAID)\
         .group_by(func.date_format(Order.created_at, '%Y-%m')).all()

        payment_status_counts = db.query(
            Order.status,
            func.count(Order.id).label('count')
        ).group_by(Order.status).all()

        # Subscription analytics
        subscription_status = db.query(
            Subscription.status,
            func.count(Subscription.id).label('count')
        ).group_by(Subscription.status).all()

        subscription_plans = db.query(
            Subscription.plan,
            func.count(Subscription.id).label('count')
        ).group_by(Subscription.plan).all()

        auto_renew_count = db.query(Subscription)\
            .filter(Subscription.auto_renew == True).count()

        # Cancellation analytics
        cancellation_reasons = db.query(
            CancellationRequest.reason,
            func.count(CancellationRequest.id).label('count')
        ).group_by(CancellationRequest.reason).all()

        # Feedback metrics
        total_feedback = db.query(Feedback).count()
        avg_rating = db.query(func.avg(Feedback.rating)).scalar() or 0
        rating_distribution = db.query(
            Feedback.rating,
            func.count(Feedback.id).label('count')
        ).group_by(Feedback.rating).all()

        # Support queries
        total_queries = db.query(ContactUs).count()
        queries_by_topic = db.query(
            ContactUs.topic,
            func.count(ContactUs.id).label('count')
        ).group_by(ContactUs.topic).all()

        company_size_distribution = db.query(
            ContactUs.company_size,
            func.count(ContactUs.id).label('count')
        ).group_by(ContactUs.company_size).all()

        return JSONResponse(status_code=200, content={
            "users": {
                "total": total_users,
                "active": active_users,
                "premium": premium_users,
                "trial": trial_users,
                "verified": verified_users,
                "tfa_enabled": tfa_enabled_users,
                "monthly_growth": [{"month": x.month, "count": x.count} for x in user_growth],
                "engagement": {
                    "newsletter_subscribers": newsletter_subscribers,
                    "push_enabled": push_notification_enabled,
                    "email_alerts": email_alerts_enabled
                },
                "credits": {
                    "total_allocated": float(total_credits_allocated),
                    "total_used": float(total_credits_used),
                    "average_per_user": float(avg_credits_per_user)
                }
            },
            "predictions": {
                "total": total_predictions,
                "annotated": annotated_predictions,
                "monthly_growth": [{"month": x.month, "count": x.count} for x in prediction_growth]
            },
            "patients": {
                "total": total_patients,
                "average_age": float(avg_patient_age),
                "gender_distribution": [{"gender": x.gender.value, "count": x.count} for x in patients_by_gender],
                "age_groups": [{"group": x.age_group, "count": x.count} for x in patients_by_age_group]
            },
            "revenue": {
                "total": float(total_revenue),
                "average_order_value": float(avg_order_value),
                "monthly": [{
                    "month": x.month,
                    "revenue": float(x.revenue),
                    "order_count": x.order_count
                } for x in revenue_by_month]
            },
            "payments": {
                "status_distribution": [{"status": x.status.value, "count": x.count} for x in payment_status_counts]
            },
            "subscriptions": {
                "status_distribution": [{"status": x.status.value, "count": x.count} for x in subscription_status],
                "plan_distribution": [{"plan": x.plan, "count": x.count} for x in subscription_plans],
                "auto_renew_count": auto_renew_count,
                "cancellation_reasons": [{"reason": x.reason, "count": x.count} for x in cancellation_reasons]
            },
            "feedback": {
                "total": total_feedback,
                "average_rating": float(avg_rating),
                "rating_distribution": [{"rating": x.rating, "count": x.count} for x in rating_distribution]
            },
            "support": {
                "total_queries": total_queries,
                "by_topic": [{"topic": x.topic, "count": x.count} for x in queries_by_topic],
                "by_company_size": [{"size": x.company_size, "count": x.count} for x in company_size_distribution]
            }
        })

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@admin_router.get("/payments", 
    summary="Get all payment records",
    description="""
    Returns a comprehensive list of all payment records including:
    - Orders with user details and payment status
    - Active subscriptions with user details and renewal status  
    - Generated invoices with order and user information
    """,
    response_model=List[OrderResponse]
)
async def get_payments(request: Request, db: Session = Depends(get_db)):
    try:
        # Get orders with user details
        orders = db.query(Order).all()
        payments = []
        for order in orders:
            user = db.query(User).filter(User.id == order.user).first()
            user_details = {
                "name": "Deleted User",
                "email": "deleted@user.com",
                "phone": "N/A"
            } if user is None else {
                "name": user.name,
                "email": user.email,
                "phone": user.phone
            }
            
            payment = {
                "id": order.id,
                "user": user_details,
                "plan": order.plan,
                "duration_months": order.duration_months,
                "billing_frequency": order.billing_frequency,
                "coupon": order.coupon,
                "amount": order.amount,
                "discount_amount": order.discount_amount,
                "final_amount": order.final_amount,
                "payment_id": order.payment_id,
                "status": order.status.value,
                "created_at": order.created_at.isoformat(),
                "updated_at": order.updated_at.isoformat()
            }
            payments.append(payment)

        # Get subscriptions with user details  
        subscriptions = db.query(Subscription).all()
        subs = []
        for subscription in subscriptions:
            user = db.query(User).filter(User.id == subscription.user).first()
            user_details = {
                "name": "Deleted User",
                "email": "deleted@user.com",
                "phone": "N/A"
            } if user is None else {
                "name": user.name,
                "email": user.email,
                "phone": user.phone
            }
            
            sub = {
                "id": subscription.id,
                "user": user_details,
                "subscription_id": subscription.subscription_id,
                "plan": subscription.plan,
                "plan_type": subscription.plan_type,
                "start_date": subscription.start_date.isoformat(),
                "end_date": subscription.end_date.isoformat(),
                "status": subscription.status.value,
                "payment_id": subscription.payment_id,
                "auto_renew": subscription.auto_renew,
                "cancelled_at": subscription.cancelled_at.isoformat() if subscription.cancelled_at else None,
                "created_at": subscription.created_at.isoformat(),
                "updated_at": subscription.updated_at.isoformat()
            }
            subs.append(sub)

        # Get invoices with order and user details
        invoices = db.query(Invoice).all()
        invs = []
        for invoice in invoices:
            order = db.query(Order).filter(Order.id == invoice.order_id).first()
            if order:
                user = db.query(User).filter(User.id == order.user).first()
                user_details = {
                    "name": "Deleted User",
                    "email": "deleted@user.com",
                    "phone": "N/A"
                } if user is None else {
                    "name": user.name,
                    "email": user.email,
                    "phone": user.phone
                }
            else:
                user_details = {
                    "name": "Deleted User",
                    "email": "deleted@user.com",
                    "phone": "N/A"
                }
            
            inv = {
                "id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "order_id": invoice.order_id,
                "user": user_details,
                "status": invoice.status.value,
                "file_path": f"{request.base_url}{invoice.file_path}",
                "created_at": invoice.created_at.isoformat(),
                "updated_at": invoice.updated_at.isoformat()
            }
            invs.append(inv)

        return JSONResponse(
            status_code=200, 
            content={
                "orders": payments, 
                "subscriptions": subs, 
                "invoices": invs
            }
        )

    except Exception as e:
        return JSONResponse(
            status_code=500, 
            content={"error": f"Failed to get payments: {str(e)}"}
        )
     
@admin_router.get("/invoice/{invoice_id}",
    summary="Get invoice details by ID",
    description="""
    Returns detailed information about a specific invoice including:
    - Invoice details (number, status, file URL)
    - Associated order information
    - User details of the order owner
    Requires admin authentication.
    """,
    response_model=InvoiceResponse,
    responses={
        200: {"description": "Successfully retrieved invoice details"},
        404: {"description": "Invoice or associated order not found"},
        500: {"description": "Internal server error"}
    }
)
async def get_invoice(request: Request, invoice_id: str, db: Session = Depends(get_db)):
    try:
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice:
            return JSONResponse(status_code=404, content={"error": "Invoice not found"})
        
        order = db.query(Order).filter(Order.id == invoice.order_id).first()
        if not order:
            return JSONResponse(status_code=404, content={"error": "Order not found"})

        order_user = db.query(User).filter(User.id == order.user).first()
        user_details = {
            "name": "Deleted User",
            "email": "deleted@user.com",
            "phone": "N/A"
        } if order_user is None else {
            "name": order_user.name,
            "email": order_user.email,
            "phone": order_user.phone
        }
        
        invoice_details = {
            "id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "order_id": invoice.order_id,
            "user": user_details,
            "status": invoice.status.value,
            "file_url": f"{request.base_url}{invoice.file_path}",
            "created_at": invoice.created_at.isoformat(),
            "updated_at": invoice.updated_at.isoformat()
        }

        return JSONResponse(status_code=200, content=invoice_details)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to get invoice: {str(e)}"})

@admin_router.get("/support-tickets",
    summary="Get all support tickets",
    description="Returns a list of all support tickets with user details and ticket information",
    response_model=List[SupportTicketResponse]
)
async def get_support_tickets(db: Session = Depends(get_db)):
    try:
        tickets = db.query(SupportTicket).all()
        return JSONResponse(status_code=200, content={"tickets": [SupportTicketResponse.from_orm(ticket) for ticket in tickets]})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to get support tickets: {str(e)}"})
    
@admin_router.get("/support-tickets/{ticket_id}",
    summary="Get support ticket by ID",
    description="Returns detailed information about a specific support ticket",
    response_model=SupportTicketResponse
)
async def get_support_ticket(ticket_id: str, db: Session = Depends(get_db)):
    try:
        ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
        if not ticket:
            return JSONResponse(status_code=404, content={"error": "Ticket not found"})
        return JSONResponse(status_code=200, content=SupportTicketResponse.from_orm(ticket))
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to get support ticket: {str(e)}"})

@admin_router.patch("/support-tickets/{ticket_id}",
    summary="Update support ticket status and priority",
    description="Updates the status and priority of a support ticket",
    response_model=SupportTicketResponse
)
async def update_support_ticket(ticket_id: str, ticket_data: SupportTicketUpdate, db: Session = Depends(get_db)):
    try:
        ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
        if not ticket:
            return JSONResponse(status_code=404, content={"error": "Ticket not found"})
        
        if ticket_data.status:
            ticket.status = TicketStatus[ticket_data.status.upper()]
        if ticket_data.priority:
            ticket.priority = TicketPriority[ticket_data.priority.upper()]
            
        db.commit()
        db.refresh(ticket)
        return JSONResponse(status_code=200, content={"message": "Ticket updated successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to update support ticket: {str(e)}"})

@admin_router.delete("/support-tickets/{ticket_id}",
    summary="Delete a support ticket",
    description="Deletes a support ticket",
    response_model=SupportTicketResponse
)
async def delete_support_ticket(ticket_id: str, db: Session = Depends(get_db)):
    try:
        ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
        if not ticket:
            return JSONResponse(status_code=404, content={"error": "Ticket not found"})
        db.delete(ticket)
        db.commit()
        return JSONResponse(status_code=200, content={"message": "Ticket deleted successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to delete support ticket: {str(e)}"})