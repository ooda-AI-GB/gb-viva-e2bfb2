from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import SessionLocal, engine, Base, User, Client, Project, TimeEntry, Invoice, init_db
from passlib.context import CryptContext
from itsdangerous import URLSafeTimedSerializer
from datetime import date, datetime
import calendar
from typing import Optional

# Initialize DB
init_db()

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = "supersecretkey"
serializer = URLSafeTimedSerializer(SECRET_KEY)

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        username = serializer.loads(token, max_age=3600*24) # 24 hours
        user = db.query(User).filter(User.username == username).first()
        return user
    except:
        return None

def login_required(request: Request, user: Optional[User] = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/login"})
    return user

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
def root(request: Request, user: Optional[User] = Depends(get_current_user)):
    if user:
        return RedirectResponse(url="/dashboard")
    return RedirectResponse(url="/login")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login(response: Response, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not pwd_context.verify(password, user.hashed_password):
        return RedirectResponse(url="/login?error=Invalid credentials", status_code=status.HTTP_303_SEE_OTHER)
    
    token = serializer.dumps(username)
    resp = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(key="session", value=token, httponly=True)
    return resp

@app.get("/logout")
def logout(response: Response):
    resp = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie("session")
    return resp

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: User = Depends(login_required), db: Session = Depends(get_db)):
    # Summary Cards Logic
    active_projects = 0
    total_hours = 0.0
    pending_invoices = 0
    total_earned = 0.0
    
    if user.role == "client":
        projects = db.query(Project).filter(Project.client_id == user.client_id).all()
        project_ids = [p.id for p in projects]
        active_projects = len([p for p in projects if p.status == 'active'])
        # For client, maybe show hours billed to them?
        total_hours = sum(e.hours for p in projects for e in p.time_entries if e.date.month == date.today().month)
        pending_invoices = db.query(Invoice).filter(Invoice.project_id.in_(project_ids), Invoice.status == 'sent').count()
        # Total spent by client
        total_earned = sum(i.amount for i in db.query(Invoice).filter(Invoice.project_id.in_(project_ids), Invoice.status == 'paid').all())
    else:
        # Admin / Freelancer
        active_projects = db.query(Project).filter(Project.status == 'active').count()
        # Hours this month
        today = date.today()
        entries = db.query(TimeEntry).filter(TimeEntry.date >= date(today.year, today.month, 1)).all()
        total_hours = sum(e.hours for e in entries)
        pending_invoices = db.query(Invoice).filter(Invoice.status != 'paid').count()
        paid_invoices = db.query(Invoice).filter(Invoice.status == 'paid').all()
        total_earned = sum(i.amount for i in paid_invoices)

    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "user": user,
        "active_projects": active_projects,
        "total_hours": total_hours,
        "pending_invoices": pending_invoices,
        "total_earned": total_earned
    })

@app.get("/projects", response_class=HTMLResponse)
def projects_page(request: Request, user: User = Depends(login_required), db: Session = Depends(get_db)):
    if user.role == "client":
        projects = db.query(Project).filter(Project.client_id == user.client_id).all()
    else:
        projects = db.query(Project).all()
    return templates.TemplateResponse("projects.html", {"request": request, "user": user, "projects": projects})

@app.get("/timelogs", response_class=HTMLResponse)
def timelogs_page(request: Request, user: User = Depends(login_required), db: Session = Depends(get_db)):
    # Everyone can see time logs for their accessible projects?
    # Usually clients might not see raw time logs unless billed, but for tracker visibility:
    if user.role == "client":
        projects = db.query(Project).filter(Project.client_id == user.client_id).all()
        p_ids = [p.id for p in projects]
        entries = db.query(TimeEntry).filter(TimeEntry.project_id.in_(p_ids)).order_by(TimeEntry.date.desc()).all()
    else:
        projects = db.query(Project).all()
        entries = db.query(TimeEntry).order_by(TimeEntry.date.desc()).all()
        
    # Calculate running total per project
    project_totals = {}
    for p in projects:
        total = sum(e.hours for e in p.time_entries)
        project_totals[p.id] = total

    return templates.TemplateResponse("timelogs.html", {
        "request": request, 
        "user": user, 
        "entries": entries, 
        "projects": projects,
        "project_totals": project_totals
    })

@app.post("/timelogs")
def add_timelog(
    request: Request,
    project_id: int = Form(...),
    hours: float = Form(...),
    description: str = Form(...),
    date_str: str = Form(..., alias="date"),
    user: User = Depends(login_required),
    db: Session = Depends(get_db)
):
    if user.role == "client":
        raise HTTPException(status_code=403, detail="Clients cannot add time logs")
        
    new_entry = TimeEntry(
        project_id=project_id,
        hours=hours,
        description=description,
        date=datetime.strptime(date_str, "%Y-%m-%d").date()
    )
    db.add(new_entry)
    db.commit()
    return RedirectResponse(url="/timelogs", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/invoices", response_class=HTMLResponse)
def invoices_page(request: Request, user: User = Depends(login_required), db: Session = Depends(get_db)):
    if user.role == "client":
        projects = db.query(Project).filter(Project.client_id == user.client_id).all()
        p_ids = [p.id for p in projects]
        invoices = db.query(Invoice).filter(Invoice.project_id.in_(p_ids)).all()
    else:
        invoices = db.query(Invoice).all()
    return templates.TemplateResponse("invoices.html", {"request": request, "user": user, "invoices": invoices})

@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request, user: User = Depends(login_required), db: Session = Depends(get_db)):
    # Hours per project
    if user.role == "client":
        projects = db.query(Project).filter(Project.client_id == user.client_id).all()
    else:
        projects = db.query(Project).all()
        
    project_data = []
    for p in projects:
        h = sum(e.hours for e in p.time_entries)
        project_data.append({"name": p.name, "hours": h})
    
    # Monthly earnings (last 6 months maybe? or just this year)
    # Simple: Group invoices by month
    monthly_revenue = {}
    # Top clients
    client_revenue = {}
    
    if user.role != "client":
        invoices = db.query(Invoice).filter(Invoice.status == 'paid').all()
        for inv in invoices:
            m = inv.date_issued.strftime("%Y-%m")
            monthly_revenue[m] = monthly_revenue.get(m, 0) + inv.amount
            
            c_name = inv.project.client.name
            client_revenue[c_name] = client_revenue.get(c_name, 0) + inv.amount

    # Convert dicts to lists for easier template iteration
    monthly_data = [{"month": k, "amount": v} for k, v in monthly_revenue.items()]
    monthly_data.sort(key=lambda x: x['month'])
    
    client_data = [{"name": k, "amount": v} for k, v in client_revenue.items()]
    client_data.sort(key=lambda x: x['amount'], reverse=True)
    
    max_hours = max([d['hours'] for d in project_data], default=1)
    max_monthly = max([d['amount'] for d in monthly_data], default=1)
    max_client = max([d['amount'] for d in client_data], default=1)
            
    return templates.TemplateResponse("reports.html", {
        "request": request, 
        "user": user,
        "project_data": project_data,
        "monthly_data": monthly_data,
        "client_data": client_data,
        "max_hours": max_hours,
        "max_monthly": max_monthly,
        "max_client": max_client
    })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
