from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy import DateTime
from datetime import datetime
from sqlalchemy.orm import mapped_column

class TimestampMixin:
    @declared_attr
    def created_at(cls):
        return mapped_column(DateTime, default=datetime.now, nullable=True)

    @declared_attr
    def updated_at(cls):
        return mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=True)