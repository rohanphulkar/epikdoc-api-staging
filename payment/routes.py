from fastapi import APIRouter, Depends, Request, Path, Query, Body
from fastapi.responses import JSONResponse
from .models import *
from .schema import *
from db.db import get_db
from sqlalchemy.orm import Session
from utils.auth import get_current_user
import razorpay
from decouple import config
from auth.model import User
import time
import hmac
import hashlib
from datetime import datetime, timedelta
from sqlalchemy import func, select
from typing import Dict, Any, Optional
from utils.generate_invoice import create_professional_invoice, generate_invoice_number
from utils.email import send_invoice_email
import os


# Initialize Razorpay client
client = razorpay.Client(auth=(config("RAZORPAY_KEY_ID"), config("RAZORPAY_KEY_SECRET")))

payment_router = APIRouter()


# Plan configurations
plans: list[Dict[str, Any]] = [
    {
        "name": "starter",
        "prices": {
            "monthly": 999,
            "half_yearly": 3999,
            "yearly": 5999,
        },
        "credits": 50,
        "plan_id": config("STARTER_PLAN_ID"),
    },
    {
        "name": "pro", 
        "prices": {
            "monthly": 1999,
            "half_yearly": 8999,
            "yearly": 13999,
        },
        "credits": 300,
        "plan_id": config("PRO_PLAN_ID"),
    },
    {
        "name": "max",
        "prices": {
            "monthly": 2999,
            "half_yearly": 14999,
            "yearly": 19999,
        },
        "credits": 600,
        "plan_id": config("MAX_PLAN_ID"),
    }
]


def get_plan_by_name(plan_name: str) -> Optional[Dict[str, Any]]:
    """Helper function to get plan details by name"""
    return next((p for p in plans if p["name"].lower() == plan_name.lower()), None)


@payment_router.get("/coupon/get-all-coupons",
    summary="Get all coupons",
    description="Retrieves list of all available discount coupons",
    response_description="Returns list of coupon objects with details like code, discount etc",
    responses={
        200: {"description": "Successfully retrieved coupons list"},
        500: {"description": "Server error while fetching coupons"}
    }
)
async def get_all_coupons(db: Session = Depends(get_db)):
    try:
        coupons = db.query(Coupon).all()
        return JSONResponse(status_code=200, content={"coupons": [{
            "id": coupon.id,
            "code": coupon.code,
            "type": str(coupon.type),
            "value": coupon.value,
            "max_uses": coupon.max_uses,
            "valid_from": coupon.valid_from.isoformat() if coupon.valid_from else None,
            "valid_until": coupon.valid_until.isoformat() if coupon.valid_until else None,
            "is_active": coupon.is_active
        } for coupon in coupons]})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@payment_router.get("/coupon/get-coupon-details/{coupon_id}",
    summary="Get coupon details",
    description="Retrieves detailed information about a specific coupon",
    response_description="Returns complete details of the requested coupon",
    responses={
        200: {"description": "Successfully retrieved coupon details"},
        404: {"description": "Coupon not found"},
        500: {"description": "Server error while fetching coupon"}
    }
)
async def get_coupon_details(
    coupon_id: str = Path(..., description="Unique identifier of the coupon"),
    db: Session = Depends(get_db)
):
    try:
        coupon = db.query(Coupon).filter(Coupon.id == coupon_id).first()
        if not coupon:
            return JSONResponse(status_code=404, content={"error": "Coupon not found"})
        
        return JSONResponse(status_code=200, content={"coupon": {
            "id": coupon.id,
            "code": coupon.code,
            "type": str(coupon.type),
            "value": coupon.value,
            "max_uses": coupon.max_uses,
            "valid_from": coupon.valid_from.isoformat() if coupon.valid_from else None,
            "valid_until": coupon.valid_until.isoformat() if coupon.valid_until else None,
            "is_active": coupon.is_active
        }})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@payment_router.post("/coupon/create-coupon",
    summary="Create discount coupon",
    description="Creates a new discount coupon. Admin only.",
    response_description="Returns confirmation of coupon creation",
    responses={
        200: {"description": "Coupon created successfully"},
        401: {"description": "Unauthorized - Admin access required"},
        500: {"description": "Server error while creating coupon"}
    }
)
async def create_coupon(
    request: Request,
    coupon: CouponSchema = Body(..., description="Coupon details including code, discount value and validity"),
    db: Session = Depends(get_db)
):
    try:
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
            
        user = db.query(User).filter(User.id == current_user).first()
        if not user or str(user.user_type) != "admin":
            return JSONResponse(status_code=401, content={"error": "Admin access required"})
            
        new_coupon = Coupon(
            code=coupon.code,
            type=coupon.type,
            value=coupon.value,
            max_uses=coupon.max_uses,
            valid_from=datetime.now(),
            valid_until=coupon.valid_until,
            is_active=coupon.is_active
        )
        db.add(new_coupon)
        db.commit()
        
        return JSONResponse(status_code=200, content={"message": "Coupon created successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@payment_router.patch("/coupon/update-coupon/{coupon_id}",
    summary="Update discount coupon",
    description="Updates an existing discount coupon. Admin only.",
    response_description="Returns confirmation of coupon update",
    responses={
        200: {"description": "Coupon updated successfully"},
        401: {"description": "Unauthorized - Admin access required"},
        404: {"description": "Coupon not found"},
        500: {"description": "Server error while updating coupon"}
    }
)
async def update_coupon(
    request: Request,
    coupon_id: str = Path(..., description="Unique identifier of coupon to update"),
    coupon: CouponSchema = Body(..., description="Updated coupon details"),
    db: Session = Depends(get_db)
):
    try:
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
            
        user = db.query(User).filter(User.id == current_user).first()
        if not user or user.user_type != "admin":
            return JSONResponse(status_code=401, content={"error": "Admin access required"})
        
        coupon_details = db.query(Coupon).filter(Coupon.id == coupon_id).first()
        if not coupon_details:
            return JSONResponse(status_code=404, content={"error": "Coupon not found"})
        
        # Update coupon fields if provided
        for field, value in coupon.dict(exclude_unset=True).items():
            setattr(coupon_details, field, value)

        db.commit()
        return JSONResponse(status_code=200, content={"message": "Coupon updated successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@payment_router.delete("/coupon/delete-coupon/{coupon_id}",
    summary="Delete discount coupon",
    description="Permanently deletes a discount coupon. Admin only.",
    response_description="Returns confirmation of coupon deletion",
    responses={
        200: {"description": "Coupon deleted successfully"},
        401: {"description": "Unauthorized - Admin access required"},
        404: {"description": "Coupon not found"},
        500: {"description": "Server error while deleting coupon"}
    }
)
async def delete_coupon(
    request: Request,
    coupon_id: str = Path(..., description="Unique identifier of coupon to delete"),
    db: Session = Depends(get_db)
):
    try:
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
            
        user = db.query(User).filter(User.id == current_user).first()
        if not user or user.user_type != "admin":
            return JSONResponse(status_code=401, content={"error": "Admin access required"})
        
        coupon = db.query(Coupon).filter(Coupon.id == coupon_id).first()
        if not coupon:
            return JSONResponse(status_code=404, content={"error": "Coupon not found"})
        
        db.delete(coupon)
        db.commit()
        return JSONResponse(status_code=200, content={"message": "Coupon deleted successfully"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@payment_router.post("/payment/create",
    summary="Create one-time payment",
    description="Initiates a new one-time payment with optional coupon",
    response_description="Returns payment order ID for verification",
    responses={
        200: {"description": "Payment initiated successfully"},
        401: {"description": "Unauthorized access"},
        404: {"description": "User/Plan not found"},
        500: {"description": "Server error while creating payment"}
    }
)
async def create_payment(
    request: Request,
    payment: PaymentCreateSchema = Body(..., description="Payment details including plan and optional coupon"),
    db: Session = Depends(get_db)
):
    try:
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == current_user).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})

        selected_plan = get_plan_by_name(payment.plan)
        if not selected_plan:
            return JSONResponse(status_code=404, content={"error": "Invalid plan selected"})

        # Get plan amount based on duration
        amount = selected_plan["prices"].get(payment.plan_type, selected_plan["prices"]["monthly"])

        # Handle coupon if provided
        discount_amount = 0
        coupon = None
        if payment.coupon:
            coupon = db.query(Coupon).filter(
                func.lower(Coupon.code) == payment.coupon.lower(),
                Coupon.is_active == True,
                Coupon.valid_until > datetime.now()
            ).first()
            
            if not coupon:
                return JSONResponse(status_code=400, content={"error": "Invalid or expired coupon"})
                
            coupon_usage = db.query(CouponUsers).filter(
                CouponUsers.coupon_id == coupon.id,
                CouponUsers.user_id == str(user.id)
            ).first()
            
            if coupon_usage:
                return JSONResponse(status_code=400, content={"error": "Coupon already used"})

            discount_amount = (
                int(amount * coupon.value / 100)
                if str(coupon.type) == "CouponType.PERCENTAGE"
                else int(coupon.value)
            )

        final_amount = amount - discount_amount

        # Create Razorpay order
        try:
            order_data = {
                'amount': final_amount * 100,  # Convert to paise
                'currency': 'INR',
                'notes': {
                    'plan_name': selected_plan['name'],
                    'plan_type': payment.plan_type
                }
            }
            razorpay_order = client.order.create(data=order_data)
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"error": f"Failed to create Razorpay order: {str(e)}"}
            )

        # Create order record
        order = Order(
            user=current_user,
            plan=selected_plan["name"],
            duration_months=12 if payment.plan_type == "yearly" else (6 if payment.plan_type == "half_yearly" else 1),
            coupon=coupon.id if coupon else None,
            amount=amount,
            discount_amount=discount_amount,
            final_amount=final_amount,
            payment_id=razorpay_order["id"],
            status=PaymentStatus.PENDING,
            billing_frequency=payment.plan_type
        )

        db.add(order)
        db.commit()

        # Generate invoice number and create pending invoice
        invoice_number = generate_invoice_number()
        
        # Create invoice with pending status
        items = [(f"{selected_plan['name']} Plan ({payment.plan_type})", amount)]
        invoice_path = create_professional_invoice(
            invoice_number=invoice_number,
            customer_name=user.name,
            customer_email=user.email,
            customer_phone=user.phone or "",
            items=items,
            subtotal=amount,
            discount=discount_amount,
            status="PENDING"
        )

        # Create invoice record
        invoice = Invoice(
            invoice_number=invoice_number,
            order_id=order.id,
            status=InvoiceStatus.PENDING,
            file_path=str(invoice_path)
        )
        db.add(invoice)
        db.commit()
        
        return JSONResponse(status_code=200, content={
            "message": "Payment created successfully",
            "order_id": razorpay_order["id"],
            "amount": final_amount
        })

    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})


@payment_router.post("/payment/verify",
    summary="Verify payment",
    description="Verifies payment signature and activates plan",
    response_description="Returns confirmation of payment verification and plan activation",
    responses={
        200: {"description": "Payment verified and plan activated"},
        400: {"description": "Invalid signature"},
        404: {"description": "Order/User/Plan not found"},
        500: {"description": "Server error while verifying payment"}
    }
)
async def verify_payment(
    payment: PaymentVerifySchema = Body(..., description="Payment verification details including signature"),
    db: Session = Depends(get_db)
):
    try:
        order = db.query(Order).filter(Order.payment_id == payment.razorpay_order_id).first()
        if not order:
            return JSONResponse(status_code=404, content={"error": "Order not found"})
        
        # Verify signature
        msg = f"{payment.razorpay_order_id}|{payment.razorpay_payment_id}"
        secret_key = str(config("RAZORPAY_KEY_SECRET"))
        generated_signature = hmac.new(
            secret_key.encode('utf-8'),
            msg.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        if generated_signature != payment.razorpay_signature:
            order.status = PaymentStatus.FAILED
            db.commit()
            return JSONResponse(status_code=400, content={"error": "Invalid signature"})
        
        user = db.query(User).filter(User.id == order.user).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})

        selected_plan = get_plan_by_name(order.plan)
        if not selected_plan:
            return JSONResponse(status_code=404, content={"error": "Plan not found"})
        
        # Update user credits and expiry
        user.account_type = selected_plan["name"]
        user.credits = selected_plan["credits"]
        user.total_credits = selected_plan["credits"]
        user.used_credits = 0
        user.last_credit_updated_at = datetime.now()
        user.credit_expiry = datetime.now() + timedelta(days=order.duration_months * 30)
        user.billing_frequency = order.billing_frequency
       
        order.status = PaymentStatus.PAID
        order.payment_id = payment.razorpay_payment_id
        db.add(order)
        
        # Add coupon usage after successful payment if coupon was used
        if order.coupon:
            coupon_user = CouponUsers(
                coupon_id=order.coupon,
                user_id=str(user.id)
            )
            db.add(coupon_user)
            
            coupon = db.query(Coupon).filter(Coupon.id == order.coupon).first()
            if coupon:
                coupon.used_count += 1
                db.add(coupon)

        # Get pending invoice
        invoice = db.query(Invoice).filter(Invoice.order_id == order.id).first()
        if not invoice:
            return JSONResponse(status_code=404, content={"error": "Invoice not found"})
        
        # Delete old invoice file if exists
        if os.path.exists(invoice.file_path):
            os.remove(invoice.file_path)

        # Generate new paid invoice
        items = [(f"{selected_plan['name'].capitalize()} Plan ({order.billing_frequency.replace('_', ' ').title()})", order.amount)]
        new_invoice_path = create_professional_invoice(
            invoice_number=invoice.invoice_number,
            customer_name=user.name,
            customer_email=user.email,
            customer_phone=user.phone or "",
            items=items,
            subtotal=order.amount,
            discount=order.discount_amount,
            status="PAID"
        )

        # Update invoice record
        invoice.status = InvoiceStatus.PAID
        invoice.file_path = str(new_invoice_path)
        db.add(invoice)
        db.add(user)
        db.commit()

        # Send invoice email only after successful payment
        email_sent = send_invoice_email(
            invoice_number=invoice.invoice_number,
            customer_name=user.name,
            customer_email=user.email,
            customer_phone=user.phone or "",
            items=items,
            subtotal=order.amount,
            discount=order.discount_amount,
            status="PAID",
            output_file=new_invoice_path
        )

        if not email_sent:
            print("Failed to send invoice email")

        return JSONResponse(status_code=200, content={"message": "Payment verified successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})


@payment_router.get("/fetch-plan-details",
    summary="Fetch plan details",
    description="Fetches the details of a plan",
    response_description="Returns the plan details",
    responses={
        200: {"description": "Plan details fetched successfully"},
        400: {"description": "Invalid plan name"},
        500: {"description": "Server error while fetching plan details"}
    }
)
async def fetch_plan_details(
    plan_name: str = Query(..., description="Name of the plan to fetch details for"),
    db: Session = Depends(get_db)
):
    try:
        plan = get_plan_by_name(plan_name)
        if not plan:
            return JSONResponse(status_code=400, content={"error": f"Plan '{plan_name}' not found"})

        return JSONResponse(status_code=200, content={
            "name": plan["name"],
            "prices": plan["prices"],
            "credits": plan["credits"]
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@payment_router.get("/apply-coupon",
    summary="Apply coupon",
    description="Applies a discount coupon to the payment",
    response_description="Returns the coupon details and the final amount",
    responses={
        200: {"description": "Coupon applied successfully"},
        400: {"description": "Invalid coupon/Expired coupon/Invalid plan"},
        500: {"description": "Server error while applying coupon"}
    }
)
async def apply_coupon(
    plan_name: str = Query(..., description="Name of the plan to apply coupon to"),
    coupon_code: str = Query(..., description="Coupon code to apply"),
    billing: str = Query(..., description="Billing type (monthly/half_yearly/yearly)"),
    db: Session = Depends(get_db)
):
    try:
        # Validate and fetch coupon - case insensitive search
        coupon = db.query(Coupon).filter(
            func.lower(Coupon.code) == coupon_code.lower(),
            Coupon.is_active.is_(True),
            Coupon.valid_until > datetime.now()
        ).first()
        
        if not coupon:
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid or expired coupon"}
            )

        # Validate and fetch plan
        plan = get_plan_by_name(plan_name)
        if not plan:
            return JSONResponse(
                status_code=400,
                content={"error": f"Plan '{plan_name}' not found"}
            )

        # Validate billing type
        if billing not in plan["prices"]:
            return JSONResponse(
                status_code=400,
                content={"error": f"Invalid billing type: {billing}"}
            )

        # Get plan amount based on billing type and calculate discount
        amount = plan["prices"][billing]
        
        discount_amount = (
            int(amount * coupon.value / 100)
            if str(coupon.type) == "CouponType.PERCENTAGE"
            else min(int(coupon.value), amount)
        )

        final_amount = amount - discount_amount

        return JSONResponse(
            status_code=200,
            content={
                "message": "Coupon applied successfully",
                "original_amount": amount,
                "discount_amount": discount_amount,
                "final_amount": final_amount,
                "coupon": {
                    "code": coupon.code,
                    "type": str(coupon.type),
                    "value": coupon.value
                }
            }
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to apply coupon: {str(e)}"}
        )


# Subscription routes
@payment_router.post("/payment/enable-subscription",
    summary="Enable subscription", 
    description="Enable a subscription for a user",
    response_description="Returns the subscription details",
    responses={
        200: {"description": "Subscription enabled successfully"},
        400: {"description": "Invalid subscription details"},
        401: {"description": "Unauthorized access"},
        404: {"description": "User or plan not found"},
        500: {"description": "Server error while enabling subscription"}
    }
)
async def enable_subscription(
    request: Request,
    subscription: SubscriptionSchema = Body(..., description="Subscription details including plan and duration"),
    db: Session = Depends(get_db)
):
    try:
        # Validate user
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == current_user).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        # Validate and get plan details
        selected_plan = get_plan_by_name(subscription.plan)
        if not selected_plan:
            return JSONResponse(status_code=404, content={"error": "Invalid plan"})

        plan_id = selected_plan["plan_id"]
        amount = selected_plan["prices"].get(subscription.plan_type, selected_plan["prices"]["monthly"])

        # Create subscription data
        subscription_data = {
            'plan_id': plan_id,
            'customer_notify': 1,
            'quantity': 1,
            'total_count': 12 if subscription.plan_type == "yearly" else 6 if subscription.plan_type == "half_yearly" else 1,
            'start_at': int(time.time()) + 600,  # Start after 10 minutes
            'notes': {
                'message': 'Subscription Payment',
                'user_id': current_user,
                'plan': subscription.plan,
                'plan_type': subscription.plan_type
            }
        }

        # Create Razorpay subscription
        try:
            razorpay_subscription = client.subscription.create(data=subscription_data)
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"error": f"Failed to create Razorpay subscription: {str(e)}"}
            )

        # Cancel existing active subscriptions
        active_subscriptions = (
            db.query(Subscription)
            .filter(
                Subscription.user == current_user,
                Subscription.status == SubscriptionStatus.ACTIVE
            )
            .all()
        )

        for active_subscription in active_subscriptions:
            try:
                client.subscription.cancel(active_subscription.subscription_id)
                active_subscription.status = SubscriptionStatus.CANCELLED
                active_subscription.cancelled_at = datetime.now()
                db.add(active_subscription)
            except Exception as e:
                # Log error but continue with the process
                print(f"Error cancelling subscription {active_subscription.subscription_id}: {str(e)}")

        # Calculate end date based on plan type
        duration_days = {
            "monthly": 30,
            "half_yearly": 180,
            "yearly": 365
        }
        end_date = datetime.now() + timedelta(days=duration_days[subscription.plan_type])

        # Create new subscription record
        new_subscription = Subscription(
            user=current_user,
            plan=subscription.plan,
            plan_type=subscription.plan_type,
            subscription_id=razorpay_subscription["id"],
            status=SubscriptionStatus.PENDING,
            start_date=datetime.now(),
            end_date=end_date,
            auto_renew=True
        )

        db.add(new_subscription)
        db.commit()

        user.billing_frequency = subscription.plan_type
        db.add(user)
        db.commit()

        # Create order record
        order = Order(
            user=current_user,
            plan=subscription.plan,
            duration_months=12 if subscription.plan_type == "yearly" else (6 if subscription.plan_type == "half_yearly" else 1),
            billing_frequency=subscription.plan_type,
            amount=amount,
            status=PaymentStatus.PENDING,
            coupon=None,
            final_amount=amount,
            discount_amount=0.0,
        )
        db.add(order)
        db.commit()

        # Generate invoice number
        invoice_number = generate_invoice_number()

        # Create pending invoice PDF
        items = [(f"{subscription.plan} Plan ({subscription.plan_type})", amount)]
        invoice_file = f"invoice_{invoice_number}.pdf"
        invoice_path = create_professional_invoice(
            invoice_number=invoice_number,
            customer_name=user.name,
            customer_email=user.email,
            customer_phone=user.phone or "",
            items=items,
            subtotal=amount,
            status="PENDING"
        )

        # Create invoice record
        invoice = Invoice(
            invoice_number=invoice_number,
            order_id=order.id,
            status=InvoiceStatus.PENDING,
            file_path=str(invoice_path)
        )
        db.add(invoice)
        db.commit()

        return JSONResponse(status_code=200, content={
            "message": "Subscription created successfully",
            "subscription_id": razorpay_subscription["id"],
            "amount": amount,
        })

    except Exception as e:
        db.rollback()
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to enable subscription: {str(e)}"}
        )


@payment_router.post("/payment/verify-subscription",
    summary="Verify subscription",
    description="Verify a subscription payment",
    response_description="Returns confirmation of subscription payment verification",
    responses={
        200: {"description": "Subscription payment verified successfully"},
        400: {"description": "Invalid subscription details"},
        401: {"description": "Unauthorized access"},
        404: {"description": "Subscription not found"},
        500: {"description": "Server error while verifying subscription payment"}
    }
)
async def verify_subscription(
    subscription_data: SubscriptionVerifySchema = Body(..., description="Subscription verification details including payment ID and signature"),
    db: Session = Depends(get_db)
):
    try:
        # Find the subscription
        subscription = (
            db.query(Subscription)
            .filter(Subscription.subscription_id == subscription_data.razorpay_subscription_id)
            .first()
        )
        if not subscription:
            return JSONResponse(
                status_code=404,
                content={"error": "Subscription not found"}
            )
        
        # Verify signature
        msg = f"{subscription_data.razorpay_payment_id}|{subscription_data.razorpay_subscription_id}"
        secret_key = str(config("RAZORPAY_KEY_SECRET"))
        generated_signature = hmac.new(
            secret_key.encode('utf-8'),
            msg.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        if generated_signature != subscription_data.razorpay_signature:
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid payment signature"}
            )
        
        # Activate subscription
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.payment_id = subscription_data.razorpay_payment_id
        db.add(subscription)
        
        # Find and update user
        user = db.query(User).filter(User.id == subscription.user).first()
        if not user:
            return JSONResponse(
                status_code=404,
                content={"error": "User not found"}
            )
        
        # Update user subscription details
        duration_days = {
            "monthly": 30,
            "half_yearly": 180,
            "yearly": 365
        }
        
        now = datetime.now()
        selected_plan = get_plan_by_name(subscription.plan)
        if not selected_plan:
            return JSONResponse(
                status_code=404,
                content={"error": "Plan not found"}
            )

        user.account_type = subscription.plan
        user.credits = selected_plan["credits"]
        user.total_credits = selected_plan["credits"]
        user.used_credits = 0
        user.last_credit_updated_at = now
        user.credit_expiry = now + timedelta(days=duration_days[subscription.plan_type])
        user.has_subscription = True

        db.add(user)
        db.commit()

        # Update order status
        order = db.query(Order).filter(Order.user == user.id, Order.status == PaymentStatus.PENDING).first()
        if not order:
            return JSONResponse(
                status_code=404,
                content={"error": "Order not found"}
            )
            
        order.status = PaymentStatus.PAID
        order.payment_id = subscription_data.razorpay_payment_id
        db.add(order)
        db.commit()

        # Get pending invoice
        invoice = db.query(Invoice).filter(Invoice.order_id == order.id).first()
        if not invoice:
            return JSONResponse(
                status_code=404,
                content={"error": "Invoice not found"}
            )
        
        # Delete old invoice file if exists
        if os.path.exists(invoice.file_path):
            os.remove(invoice.file_path)

        # Generate new paid invoice
        items = [(f"{subscription.plan.capitalize()} Plan ({subscription.plan_type.replace('_', ' ').title()})", order.final_amount)]
        new_invoice_path = create_professional_invoice(
            invoice_number=invoice.invoice_number,
            customer_name=user.name,
            customer_email=user.email,
            customer_phone=user.phone or "",
            items=items,
            subtotal=order.final_amount,
            discount=order.discount_amount,
            status="PAID"
        )

        # Update invoice record
        invoice.status = InvoiceStatus.PAID
        invoice.file_path = str(new_invoice_path)
        db.add(invoice)
        db.commit()

        # Send invoice email only after successful payment
        email_sent = send_invoice_email(
            invoice_number=invoice.invoice_number,
            customer_name=user.name,
            customer_email=user.email,
            customer_phone=user.phone or "",
            items=items,
            subtotal=order.final_amount,
            discount=order.discount_amount,
            status="PAID",
            output_file=new_invoice_path
        )

        if not email_sent:
            print("Failed to send invoice email")

        return JSONResponse(
            status_code=200,
            content={"message": "Subscription payment verified successfully"}
        )

    except Exception as e:
        db.rollback()  # Rollback any changes in case of error
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to verify subscription payment: {str(e)}"}
        )


@payment_router.get("/payment/get-subscription-details",
    summary="Get subscription details",
    description="Get details of a user's subscription",
    response_description="Returns the subscription details",
    responses={
        200: {"description": "Subscription details fetched successfully"},
        401: {"description": "Unauthorized access"},
        404: {"description": "Subscription not found"},
        500: {"description": "Server error while fetching subscription details"}
    }
)
async def get_subscription_details(
    request: Request,
    db: Session = Depends(get_db)
):
    try:
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == current_user).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        subscription = db.query(Subscription).filter(
            Subscription.user == current_user,
            Subscription.status == SubscriptionStatus.ACTIVE
        ).first()
        if not subscription:
            return JSONResponse(status_code=404, content={"error": "Subscription not found"})
        
        next_payment_date = subscription.end_date + timedelta(days=1)
        
        return JSONResponse(status_code=200, content={
            "subscription_id": subscription.subscription_id,
            "plan": subscription.plan,
            "plan_type": subscription.plan_type,
            "start_date": subscription.start_date.isoformat(),
            "end_date": subscription.end_date.isoformat(),
            "next_payment_date": next_payment_date.isoformat()
        })
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to fetch subscription details: {str(e)}"}
        )


@payment_router.post("/payment/cancel-subscription",
    summary="Cancel subscription",
    description="Cancel a user's subscription",
    response_description="Returns confirmation of subscription cancellation",
    responses={
        200: {"description": "Subscription cancelled successfully"},
        401: {"description": "Unauthorized access"},
        404: {"description": "Subscription not found"},
        500: {"description": "Server error while cancelling subscription"}
    }
)
async def cancel_subscription(
    request: Request,
    cancellation_request: CancellationRequestSchema = Body(..., description="Cancellation request details"),
    db: Session = Depends(get_db)
):
    try:
        # Validate user
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        # Get active subscription
        subscription = db.query(Subscription).filter(
            Subscription.user == current_user,
            Subscription.status == SubscriptionStatus.ACTIVE
        ).first()
        
        if not subscription:
            return JSONResponse(status_code=404, content={"error": "No active subscription found"})
        
        try:
            # Cancel subscription with payment provider
            client.subscription.cancel(subscription.subscription_id)
            
            # Update subscription status
            subscription.status = SubscriptionStatus.CANCELLED
            subscription.cancelled_at = datetime.now()
            db.add(subscription)
            
            # Create cancellation record
            cancellation = CancellationRequest(
                user=current_user,
                subscription=subscription.id,
                reason=cancellation_request.reason,
                feedback=cancellation_request.feedback,
                status=CancellationStatus.CANCELLED
            )
            db.add(cancellation)
            
            # Update user subscription flag
            user = db.query(User).filter(User.id == current_user).first()
            if user:
                user.has_subscription = False
                db.add(user)
            
            db.commit()
            
            return JSONResponse(
                status_code=200, 
                content={
                    "message": "Subscription cancelled successfully",
                    "cancelled_at": subscription.cancelled_at.isoformat()
                }
            )
            
        except Exception as e:
            db.rollback()
            raise Exception(f"Failed to cancel subscription with provider: {str(e)}")
            
    except Exception as e:
        return JSONResponse(
            status_code=500, 
            content={"error": f"Failed to cancel subscription: {str(e)}"}
        )
    
@payment_router.post("/payment/renew-payment",
    summary="Renew subscription",
    description="Renew a user's subscription",
    response_description="Returns confirmation of subscription renewal",
    responses={
        200: {"description": "Subscription renewed successfully"},
        400: {"description": "Invalid coupon or plan"},
        401: {"description": "Unauthorized access"},
        404: {"description": "User or plan not found"},
        500: {"description": "Server error while renewing subscription"}
    }
)
async def renew_payment(
    request: Request,
    payment: PlanRenewSchema = Body(..., description="Payment details including coupon"),
    db: Session = Depends(get_db)
):
    try:
        # Validate user
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == current_user).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})

        # Get plan details
        selected_plan = next(
            (p for p in plans if p["name"] == user.account_type),
            None
        )
        if not selected_plan:
            return JSONResponse(status_code=404, content={"error": "Invalid plan selected"})

        # Calculate base amount
        amount_mapping = {
            "monthly": selected_plan["prices"]["monthly"],
            "half_yearly": selected_plan["prices"]["half_yearly"],
            "yearly": selected_plan["prices"]["yearly"]
        }
        amount = amount_mapping.get(user.billing_frequency, amount_mapping["monthly"])

        # Process coupon if provided
        discount_amount = 0
        if payment.coupon:
            coupon = db.query(Coupon).filter(
                func.lower(Coupon.code) == payment.coupon.lower(),
                Coupon.is_active == True,
                Coupon.valid_until > datetime.now()
            ).first()
            
            if not coupon:
                return JSONResponse(status_code=400, content={"error": "Invalid or expired coupon"})

            # Check if coupon already used            
            coupon_usage = db.query(CouponUsers).filter(
                CouponUsers.coupon_id == coupon.id,
                CouponUsers.user_id == str(user.id)
            ).first()
            
            if coupon_usage:
                return JSONResponse(status_code=400, content={"error": "Coupon already used"})

            # Calculate discount
            discount_amount = (
                int(amount * coupon.value / 100)
                if str(coupon.type) == "CouponType.PERCENTAGE"
                else int(coupon.value)
            )

        final_amount = amount - discount_amount

        # Create Razorpay order
        order_data = {
            'amount': final_amount * 100,  # Convert to paise
            'currency': 'INR',
            'notes': {
                'plan_name': selected_plan['name'],
                'plan_type': user.billing_frequency
            }
        }
        razorpay_order = client.order.create(data=order_data)

        # Create order record
        duration_months = {
            "yearly": 12,
            "half_yearly": 6,
            "monthly": 1
        }[user.billing_frequency]

        order = Order(
            user=current_user,
            plan=selected_plan["name"],
            duration_months=duration_months,
            coupon=coupon.id if payment.coupon else None,
            amount=amount,
            discount_amount=discount_amount,
            final_amount=final_amount,
            payment_id=razorpay_order["id"],
            status=PaymentStatus.PENDING
        )

        db.add(order)
        db.commit()

        # Generate invoice number and create pending invoice
        invoice_number = generate_invoice_number()
        
        # Create invoice with pending status
        items = [(f"{selected_plan['name']} Plan ({user.billing_frequency})", amount)]
        invoice_path = create_professional_invoice(
            invoice_number=invoice_number,
            customer_name=user.name,
            customer_email=user.email,
            customer_phone=user.phone or "",
            items=items,
            subtotal=amount,
            discount=discount_amount,
            status="PENDING"
        )

        # Create invoice record
        invoice = Invoice(
            invoice_number=invoice_number,
            order_id=order.id,
            status=InvoiceStatus.PENDING,
            file_path=str(invoice_path)
        )
        db.add(invoice)
        db.commit()
        
        return JSONResponse(status_code=200, content={
            "message": "Payment created successfully",
            "order_id": razorpay_order["id"],
            "amount": final_amount
        })
        
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": f"Failed to renew subscription: {str(e)}"})


@payment_router.get("/payment/billing",
    summary="Get billing details", 
    description="Get billing details for a user",
    response_description="Returns billing details",
    responses={
        200: {"description": "Billing details fetched successfully"},
        401: {"description": "Unauthorized access"},
        404: {"description": "User not found"},
        500: {"description": "Server error while fetching billing details"}
    }
)
async def get_billing_details(request: Request,db: Session = Depends(get_db)):
    try:
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == current_user).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        if user.has_subscription:
            subscription = db.query(Subscription).filter(
                Subscription.user == current_user,
                Subscription.status == SubscriptionStatus.ACTIVE
            ).first()

            if not subscription:
                return JSONResponse(status_code=404, content={"error": "No active subscription found"})
            
            payment_id = subscription.payment_id
        
        else:
            order = db.query(Order).filter(Order.user == current_user, Order.status == PaymentStatus.PAID).order_by(Order.created_at.desc()).first()
            if not order:
                return JSONResponse(status_code=404, content={"error": "No active subscription found"})
            
            payment_id = order.payment_id

        payment_details = client.payment.fetch(payment_id)

        payment_method = payment_details.get("method", "unknown")

        payment_data = {}

        if payment_method == "card":
            payment_data = {
                "type": "card",
                "details": {
                    "network": payment_details.get("card", {}).get("network", "Card"),
                    "last4": payment_details.get("card", {}).get("last4", "****")
                }
            }
        elif payment_method == "upi":
            payment_data = {
                "type": "upi",
                "details": {
                    "vpa": payment_details.get("upi", {}).get("vpa", "N/A")
                }
            }
        elif payment_method == "netbanking":
            payment_data = {
                "type": "netbanking",
                "details": {
                    "bank": payment_details.get("netbanking", {}).get("bank", "N/A")
                }
            }
        elif payment_method == "wallet":
            payment_data = {
                "type": "wallet",
                "details": {
                    "wallet": payment_details.get("wallet", {}).get("entity", "Digital Wallet"),
                    "balance": payment_details.get("wallet", {}).get("balance", "N/A")
                }
            }

        orders = db.query(Order).filter(Order.user == current_user, Order.status == PaymentStatus.PAID).all()

        transactions = []

        for order in orders:
            invoice = db.query(Invoice).filter(Invoice.order_id == order.id).first()
            if invoice:
                url = f"{request.base_url}{invoice.file_path}"
            else:
                url = None
            transactions.append({
                "date": order.created_at.strftime("%Y-%m-%d"),
                "amount": order.final_amount,
                "status": order.status.value,
                "invoice_url": url
            })
        
        return JSONResponse(status_code=200, content={
            "paymentMethod": payment_data,
            "transactions": transactions
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to fetch billing details: {str(e)}"})
    
@payment_router.get("/payment/has-active-subscription",
    summary="Check if user has an active subscription",
    description="Check if a user has an active subscription",
    response_description="Returns True if user has an active subscription, False otherwise",
    responses={200: {"description": "Active subscription found"}, 404: {"description": "No active subscription found"}})
async def has_active_subscription(request: Request, db: Session = Depends(get_db)):
    try:
        current_user = get_current_user(request)
        if not current_user:
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        
        user = db.query(User).filter(User.id == current_user).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        subscription = db.query(Subscription).filter(
            Subscription.user == current_user,
            Subscription.status == SubscriptionStatus.ACTIVE
        ).first()

        if not subscription:
            has_active_subscription = False
        else:
            has_active_subscription = True
        
        return JSONResponse(status_code=200, content={"has_active_subscription": has_active_subscription})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to check for active subscription: {str(e)}"})

@payment_router.post("/payment/create-payment-link",
    summary="Create a payment link for a user",
    description="Create a payment link for a user", 
    response_description="Returns the payment link",
    responses={
        200: {"description": "Payment link created successfully"},
        401: {"description": "Unauthorized access"},
        404: {"description": "User not found"},
        500: {"description": "Server error while creating payment link"}
    }
)
async def create_payment_link(request: Request, payment: PaymentLinkSchema, db: Session = Depends(get_db)):
    try:
        email = payment.email
        name = payment.name
        phone = payment.phone
        plan = payment.plan
        billing_frequency = payment.billing_frequency

        if not email or not name or not phone or not plan:
            return JSONResponse(status_code=400, content={"error": "Invalid request"})
        
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(
                email=email,
                name=name,
                phone=phone,
                account_type=plan,
                credits=3
            )
            db.add(user)
            db.commit()

        selected_plan = next(
            (p for p in plans if p["name"] == plan),
            plans[0]
        )
        
        payment_data = {
            "amount": selected_plan["prices"][billing_frequency] * 100,
            "currency": "INR",
            "accept_partial": False,
            "description": f"Backupdoc {plan.capitalize()} Plan ({billing_frequency.replace('_', ' ').title()})",
            "customer": {
                "name": name,
                "email": email,
                "contact": phone
            },
            "notify": {
                "sms": True,
                "email": True
            },
        }

        payment_link = client.payment_link.create(data=payment_data)

        user.payment_link = payment_link["id"]
        db.commit()

        order = Order(
            user=user.id,
            plan=plan,
            duration_months=1,
            coupon=None,
            amount=selected_plan["prices"][billing_frequency],
            discount_amount=0,
            final_amount=selected_plan["prices"][billing_frequency],
            payment_id=payment_link["id"],
            status=PaymentStatus.PENDING,
            billing_frequency=billing_frequency
        )
        db.add(order)
        db.commit()

        # Generate invoice number and create pending invoice
        invoice_number = generate_invoice_number()
        
        # Create invoice with pending status
        items = [(f"{selected_plan['name']} Plan ({billing_frequency.replace('_', ' ').title()})", selected_plan["prices"][billing_frequency])]
        invoice_path = create_professional_invoice(
            invoice_number=invoice_number,
            customer_name=user.name,
            customer_email=user.email,
            customer_phone=user.phone or "",
            items=items,
            subtotal=selected_plan["prices"][billing_frequency],
            discount=0,
            status="PENDING"
        )

        # Create invoice record
        invoice = Invoice(
            invoice_number=invoice_number,
            order_id=order.id,
            status=InvoiceStatus.PENDING,
            file_path=str(invoice_path)
        )
        db.add(invoice)
        db.commit()

        return JSONResponse(status_code=200, content={"message": "Payment link created successfully", "payment_url": payment_link["short_url"]})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed to create payment link: {str(e)}"})
    

@payment_router.post("/payment/verify-payment-link",
    summary="Verify a payment link",
    description="Verify a payment link and update user subscription",
    response_description="Returns verification status", 
    responses={
        200: {"description": "Payment link verified successfully"},
        400: {"description": "Invalid payment status"},
        404: {"description": "Order or user not found"},
        500: {"description": "Server error"}
    })
async def verify_payment_link(request: Request, db: Session = Depends(get_db)):
    try:
        # Verify webhook signature
        webhook_secret = str(config("WEBHOOK_SECRET"))  # Convert to string before encode()
        webhook_signature = request.headers.get("x-razorpay-signature", "")
        
        # Get request body as raw bytes
        body = await request.body()
        body_str = await request.json()
        
        # Verify signature
        generated_signature = hmac.new(
            webhook_secret.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        
        if generated_signature != webhook_signature:
            return JSONResponse(status_code=400, content={"error": "Invalid webhook signature"})

        # Parse request data
        payment_id = body_str["payload"]["payment"]["entity"]["id"]
        payment_link_id = body_str["payload"]["payment_link"]["entity"]["id"]
        payment_status = body_str["payload"]["payment"]["entity"]["status"]

        if payment_status != "captured":
            return JSONResponse(status_code=400, content={"error": "Payment not captured"})
        
        # Find and validate order
        order = db.query(Order).filter(Order.payment_id == payment_link_id).first()
        if not order:
            return JSONResponse(status_code=404, content={"error": "Order not found"})

        # Find and validate user
        user = db.query(User).filter(User.id == order.user).first()
        if not user:
            return JSONResponse(status_code=404, content={"error": "User not found"})
        
        # Get plan details
        selected_plan = next(
            (p for p in plans if p["name"] == order.plan),
            plans[0]
        )

        # Update user subscription details
        user.account_type = selected_plan["name"]
        user.credits = selected_plan["credits"]
        user.total_credits = selected_plan["credits"]
        user.used_credits = 0
        user.last_credit_updated_at = datetime.now()
        user.credit_expiry = datetime.now() + timedelta(days=order.duration_months * 30)
        user.billing_frequency = order.billing_frequency
        user.payment_link = None
       
        # Update order status
        order.status = PaymentStatus.PAID
        order.payment_id = payment_id
        db.commit()

        # Get pending invoice
        invoice = db.query(Invoice).filter(Invoice.order_id == order.id).first()
        if not invoice:
            return JSONResponse(status_code=404, content={"error": "Invoice not found"})
        
        # Delete old invoice file if exists
        if os.path.exists(invoice.file_path):
            os.remove(invoice.file_path)

        # Generate new paid invoice
        items = [(f"{selected_plan['name'].capitalize()} Plan ({order.billing_frequency.replace('_', ' ').title()})", order.amount)]
        new_invoice_path = create_professional_invoice(
            invoice_number=invoice.invoice_number,
            customer_name=user.name,
            customer_email=user.email,
            customer_phone=user.phone or "",
            items=items,
            subtotal=order.amount,
            discount=order.discount_amount,
            status="PAID"
        )

        # Update invoice record
        invoice.status = InvoiceStatus.PAID
        invoice.file_path = str(new_invoice_path)
        db.add(invoice)
        db.add(user)
        db.commit()

        # Send invoice email only after successful payment
        email_sent = send_invoice_email(
            invoice_number=invoice.invoice_number,
            customer_name=user.name,
            customer_email=user.email,
            customer_phone=user.phone or "",
            items=items,
            subtotal=order.amount,
            discount=order.discount_amount,
            status="PAID",
            output_file=new_invoice_path
        )

        if not email_sent:
            print("Failed to send invoice email")

        return JSONResponse(status_code=200, content={"message": "Payment verified and subscription activated successfully"})
    except Exception as e:
        print(str(e))
        return JSONResponse(status_code=500, content={"error": f"Failed to verify payment: {str(e)}"})
