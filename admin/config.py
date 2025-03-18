from db.db import engine, SessionLocal
from auth.model import User
from utils.auth import verify_password
from admin.views import *
from sqlalchemy import select
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
from sqladmin import Admin


# This page will implement the authentication for your admin panel
class AdminAuth(AuthenticationBackend):

    async def login(self, request: Request) -> bool:
        form = await request.form()
        email = form.get("username")
        password = form.get("password")
        
        if not email or not password:
            return False
            
        db = SessionLocal()
        try:
            query = select(User).filter(User.email == email)
            result = db.execute(query)
            user = result.scalar_one_or_none()
            
            if user and verify_password(str(password), str(user.password)):
                if str(user.user_type) == "admin":
                    request.session.update({"token": user.email})
                    return True
            return False
        except Exception as e:
            return False
        finally:
            db.close()

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        token = request.session.get("token")
        if not token:
            return False
            
        db = SessionLocal()
        try:
            query = select(User).filter(User.email == token)
            result = db.execute(query)
            user = result.scalar_one_or_none()
            return user is not None and str(user.user_type) == "admin"
        except Exception as e:
            return False
        finally:
            db.close()


# add the views to admin
def create_admin(app):
    authentication_backend = AdminAuth(secret_key="supersecretkey")
    admin = Admin(app=app, engine=engine, authentication_backend=authentication_backend)
    
    # User management
    admin.add_view(UserAdmin)
    
    # Patient related
    admin.add_view(PatientAdmin)
    admin.add_view(PatientXrayAdmin)
    admin.add_view(PredictionAdmin)
    admin.add_view(LabelAdmin)
    admin.add_view(DeletedLabelAdmin)
    
    # Payment and billing
    admin.add_view(CouponAdmin)
    admin.add_view(OrderAdmin)
    admin.add_view(SubscriptionAdmin)
    admin.add_view(CancellationRequestAdmin)
    admin.add_view(InvoiceAdmin)
    
    # Support
    admin.add_view(ContactAdmin)
    admin.add_view(FeedbackAdmin)
    
    return admin
