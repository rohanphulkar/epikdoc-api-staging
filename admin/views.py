from auth.model import User
from patients.model import Patient, PatientXray, Gender
from predict.model import Prediction, Label, DeletedLabel
from payment.models import (
    Coupon, Order, CouponUsers, PaymentStatus, CouponType, 
    Subscription, SubscriptionStatus, CancellationRequest, CancellationStatus,
    Invoice, InvoiceStatus
)
from contact.model import ContactUs
from feedback.model import Feedback
from sqladmin import ModelView


class UserAdmin(ModelView, model=User):
    column_list = ["id", "email", "name", "user_type", "account_type", "credits", "is_active", "has_subscription"]
    column_searchable_list = ["id", "email", "name", "phone"]
    column_sortable_list = ["email", "name", "created_at", "credits", "has_subscription"]
    column_default_sort = ("created_at", True)
    form_excluded_columns = ["id", "created_at", "updated_at", "password", "otp", "otp_expiry", 
                           "reset_token", "reset_token_expiry", "tfa_otp", "tfa_otp_expiry"]
    can_create = True
    can_edit = True
    can_delete = True
    can_view_details = True
    name_plural = "Users"
    icon = "fa-solid fa-users"


class PatientAdmin(ModelView, model=Patient):
    column_list = ["id", "doctor_id", "first_name", "last_name", "phone", "age", "gender"]
    column_searchable_list = ["first_name", "last_name", "phone", "doctor_id"]
    column_sortable_list = ["first_name", "last_name", "created_at", "age"]
    column_default_sort = ("created_at", True)
    form_excluded_columns = ["id", "created_at", "updated_at"]
    can_create = True
    can_edit = True
    can_delete = True
    can_view_details = True
    name_plural = "Patients"
    icon = "fa-solid fa-hospital-user"


class PatientXrayAdmin(ModelView, model=PatientXray):
    column_list = ["id", "patient", "prediction_id", "is_opg", "created_at"]
    column_sortable_list = ["created_at", "is_opg"]
    column_default_sort = ("created_at", True)
    form_excluded_columns = ["id", "created_at", "updated_at"]
    can_create = True
    can_edit = True
    can_delete = True
    can_view_details = True
    name_plural = "Patient X-Rays"
    icon = "fa-solid fa-x-ray"


class PredictionAdmin(ModelView, model=Prediction):
    column_list = ["id", "patient", "is_annotated", "notes", "created_at"]
    column_sortable_list = ["created_at", "is_annotated"]
    column_default_sort = ("created_at", True)
    form_excluded_columns = ["id", "created_at", "updated_at", "predicted_image", "prediction"]
    can_create = False
    can_edit = True
    can_delete = True
    can_view_details = True
    name_plural = "Predictions"
    icon = "fa-solid fa-brain"
    chart_type = "bar"

    def chart_data(self):
        return {
            "labels": ["Annotated", "Not Annotated"],
            "datasets": [{
                "data": [
                    self.session.query(Prediction).filter_by(is_annotated=True).count(),
                    self.session.query(Prediction).filter_by(is_annotated=False).count()
                ]
            }]
        }


class LabelAdmin(ModelView, model=Label):
    column_list = ["id", "prediction_id", "name", "percentage", "include"]
    column_sortable_list = ["created_at", "percentage", "include"]
    column_default_sort = ("created_at", True)
    column_searchable_list = ['prediction_id', 'name']
    form_excluded_columns = ["id", "created_at", "updated_at"]
    can_create = True
    can_edit = True
    can_delete = True
    can_view_details = True
    name_plural = "Labels"
    icon = "fa-solid fa-tags"


class DeletedLabelAdmin(ModelView, model=DeletedLabel):
    column_list = ["id", "label_id", "created_at"]
    column_sortable_list = ["created_at"]
    column_default_sort = ("created_at", True)
    form_excluded_columns = ["id", "created_at", "updated_at"]
    can_create = False
    can_edit = False
    can_delete = True
    can_view_details = True
    name_plural = "Deleted Labels"
    icon = "fa-solid fa-trash"


class CouponAdmin(ModelView, model=Coupon):
    column_list = ["id", "code", "type", "value", "max_uses", "used_count", "valid_from", "valid_until", "is_active"]
    column_searchable_list = ["code"]
    column_sortable_list = ["created_at", "used_count", "is_active", "valid_until"]
    column_default_sort = ("created_at", True)
    form_excluded_columns = ["id", "created_at", "updated_at", "used_count", "used_by_users"]
    can_create = True
    can_edit = True
    can_delete = True
    can_view_details = True
    name_plural = "Coupons"
    icon = "fa-solid fa-ticket"


class OrderAdmin(ModelView, model=Order):
    column_list = ["id", "user", "plan", "duration_months", "billing_frequency", "amount", "discount_amount", "final_amount", "status", "payment_id"]
    column_searchable_list = ["id", "payment_id", "user"]
    column_sortable_list = ["created_at", "status", "amount", "final_amount"]
    column_default_sort = ("created_at", True)
    form_excluded_columns = ["id", "created_at", "updated_at"]
    can_create = False
    can_edit = True
    can_delete = True
    can_view_details = True
    name_plural = "Orders"
    icon = "fa-solid fa-shopping-cart"
    chart_type = "pie"

    def chart_data(self):
        return {
            "labels": ["Pending", "Paid", "Failed", "Refunded", "Cancelled"],
            "datasets": [{
                "data": [
                    self.session.query(Order).filter_by(status=PaymentStatus.PENDING).count(),
                    self.session.query(Order).filter_by(status=PaymentStatus.PAID).count(),
                    self.session.query(Order).filter_by(status=PaymentStatus.FAILED).count(),
                    self.session.query(Order).filter_by(status=PaymentStatus.REFUNDED).count(),
                    self.session.query(Order).filter_by(status=PaymentStatus.CANCELLED).count()
                ]
            }]
        }


class SubscriptionAdmin(ModelView, model=Subscription):
    column_list = ["id", "user", "subscription_id", "plan", "plan_type", "start_date", "end_date", "status", "auto_renew"]
    column_searchable_list = ["id", "user", "subscription_id"]
    column_sortable_list = ["created_at", "start_date", "end_date", "status"]
    column_default_sort = ("created_at", True)
    form_excluded_columns = ["id", "created_at", "updated_at"]
    can_create = False
    can_edit = True
    can_delete = True
    can_view_details = True
    name_plural = "Subscriptions"
    icon = "fa-solid fa-receipt"


class CancellationRequestAdmin(ModelView, model=CancellationRequest):
    column_list = ["id", "user", "subscription", "reason", "status", "created_at"]
    column_searchable_list = ["id", "user", "subscription"]
    column_sortable_list = ["created_at", "status"]
    column_default_sort = ("created_at", True)
    form_excluded_columns = ["id", "created_at", "updated_at"]
    can_create = False
    can_edit = True
    can_delete = True
    can_view_details = True
    name_plural = "Cancellation Requests"
    icon = "fa-solid fa-ban"


class InvoiceAdmin(ModelView, model=Invoice):
    column_list = ["id", "invoice_number", "order_id", "status", "file_path", "created_at"]
    column_searchable_list = ["id", "invoice_number", "order_id"]
    column_sortable_list = ["created_at", "status"]
    column_default_sort = ("created_at", True)
    form_excluded_columns = ["id", "created_at", "updated_at"]
    can_create = False
    can_edit = True
    can_delete = True
    can_view_details = True
    name_plural = "Invoices"
    icon = "fa-solid fa-file-invoice"


class ContactAdmin(ModelView, model=ContactUs):
    column_list = ["id", "first_name", "last_name", "email", "topic", "company_name", "company_size"]
    column_searchable_list = ["email", "first_name", "last_name", "company_name"]
    column_sortable_list = ["created_at", "company_size"]
    column_default_sort = ("created_at", True)
    form_excluded_columns = ["id", "created_at"]
    can_create = False
    can_edit = False
    can_delete = True
    can_view_details = True
    name_plural = "Contact Requests"
    icon = "fa-solid fa-envelope"


class FeedbackAdmin(ModelView, model=Feedback):
    column_list = ["id", "user", "feedback", "rating", "created_at"]
    column_searchable_list = ["id", "user"]
    column_sortable_list = ["created_at", "rating"]
    column_default_sort = ("created_at", True)
    form_excluded_columns = ["id", "created_at", "updated_at"]
    can_create = False
    can_edit = False
    can_delete = True
    can_view_details = True
    name_plural = "Feedback"
    icon = "fa-solid fa-comments"
