import uuid
from database import db
from datetime import datetime, timezone

def get_uuid():
    """Generates a unique string ID."""
    return str(uuid.uuid4())

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Text, primary_key=True, default=get_uuid)

    username = db.Column(db.Text, unique=True, nullable=False)
    password = db.Column(db.Text, nullable=False)
    display_name = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False)
    create_time = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    update_time = db.Column(db.DateTime, 
                            default=lambda: datetime.now(timezone.utc), 
                            onupdate=lambda: datetime.now(timezone.utc))
    delete_time = db.Column(db.DateTime, nullable=True)
    role = db.Column(db.String(20), default='user')  # 'admin' or 'user'

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "is_deleted": self.is_deleted,
            "create_time": self.create_time.isoformat() if self.create_time else None,
            "update_time": self.update_time.isoformat() if self.update_time else None,
            "delete_time": self.delete_time.isoformat() if self.delete_time else None
        }