from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from db.db import Base
from datetime import datetime
import uuid

def generate_uuid():
    return str(uuid.uuid4())

class Feedback(Base):
    __tablename__ = "feedback"
    id= Column(String(36), primary_key=True, unique=True, default=generate_uuid, nullable=False)
    user = Column(String(36), ForeignKey("users.id"), nullable=False)
    feedback = Column(Text, nullable=False)
    rating = Column(Integer, nullable=False, default=0)
    suggestions = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<Feedback {self.user.email or str(self.id)}>"
