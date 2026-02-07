from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Date, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from passlib.context import CryptContext
from datetime import date, timedelta
import random

DATABASE_URL = "sqlite:///./data/tracker.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String)  # 'admin', 'freelancer', 'client'
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)

class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    contact_email = Column(String)
    projects = relationship("Project", back_populates="client")

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"))
    status = Column(String)  # 'active', 'completed', 'on-hold'
    deadline = Column(Date)
    budget = Column(Float)
    
    client = relationship("Client", back_populates="projects")
    time_entries = relationship("TimeEntry", back_populates="project")
    invoices = relationship("Invoice", back_populates="project")

class TimeEntry(Base):
    __tablename__ = "time_entries"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    date = Column(Date)
    hours = Column(Float)
    description = Column(String)
    
    project = relationship("Project", back_populates="time_entries")

class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    amount = Column(Float)
    date_issued = Column(Date)
    status = Column(String)  # 'draft', 'sent', 'paid'
    
    project = relationship("Project", back_populates="invoices")

def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    # Check if seeded
    if db.query(User).first():
        db.close()
        return

    # Seed Clients
    clients = [
        Client(name="TechCorp Inc.", contact_email="contact@techcorp.com"),
        Client(name="DesignStudio Pro", contact_email="hello@designstudio.com"),
        Client(name="Startup Ventures", contact_email="founders@startup.io")
    ]
    db.add_all(clients)
    db.commit()
    
    # Refresh to get IDs
    for c in clients: db.refresh(c)

    # Seed Users
    users = [
        User(username="admin", hashed_password=pwd_context.hash("admin"), role="admin"),
        User(username="freelancer", hashed_password=pwd_context.hash("freelancer"), role="freelancer"),
        User(username="client", hashed_password=pwd_context.hash("client"), role="client", client_id=clients[0].id)
    ]
    db.add_all(users)
    db.commit()

    # Seed Projects
    statuses = ["active", "completed", "on-hold"]
    projects = []
    for i in range(5):
        client = random.choice(clients)
        p = Project(
            name=f"Project {client.name.split()[0]} {i+1}",
            client_id=client.id,
            status=random.choice(statuses),
            deadline=date.today() + timedelta(days=random.randint(10, 60)),
            budget=random.randint(1000, 10000)
        )
        projects.append(p)
    db.add_all(projects)
    db.commit()
    
    for p in projects: db.refresh(p)

    # Seed Time Entries
    for _ in range(20):
        project = random.choice(projects)
        entry = TimeEntry(
            project_id=project.id,
            date=date.today() - timedelta(days=random.randint(0, 30)),
            hours=round(random.uniform(1.0, 8.0), 1),
            description="Development and testing"
        )
        db.add(entry)
    
    # Seed Invoices
    invoice_statuses = ["draft", "sent", "paid"]
    for i in range(4):
        project = random.choice(projects)
        inv = Invoice(
            project_id=project.id,
            amount=random.randint(500, 3000),
            date_issued=date.today() - timedelta(days=random.randint(0, 20)),
            status=random.choice(invoice_statuses)
        )
        db.add(inv)
    
    db.commit()
    db.close()

if __name__ == "__main__":
    init_db()
