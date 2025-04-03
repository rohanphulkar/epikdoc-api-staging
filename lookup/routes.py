from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional, List
from db.db import get_db
from .models import Speciality, Country
from .schemas import SpecialityCreate, SpecialityUpdate, CountryCreate, CountryUpdate
from fastapi.responses import JSONResponse

lookup_router = APIRouter()

# Speciality Routes
@lookup_router.post("/speciality",
    response_model=dict,
    status_code=201,
    summary="Create speciality",
    description="Create a new medical speciality",
    responses={
        201: {"description": "Speciality created successfully"},
        500: {"description": "Internal server error"}
    }
)
async def create_speciality(speciality: SpecialityCreate, db: Session = Depends(get_db)):
    try:
        # Check if speciality already exists
        existing = db.query(Speciality).filter(Speciality.name.ilike(speciality.name)).first()
        if existing:
            return JSONResponse(status_code=400, content={"error": "Speciality already exists"})

        new_speciality = Speciality(name=speciality.name)
        db.add(new_speciality)
        db.commit()
        db.refresh(new_speciality)
        return JSONResponse(status_code=201, content={"message": "Speciality created successfully", "id": new_speciality.id})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@lookup_router.get("/specialities",
    response_model=dict,
    status_code=200,
    summary="Get all specialities",
    description="Retrieve a list of all medical specialities",
    responses={
        200: {"description": "List of specialities retrieved successfully"},
        500: {"description": "Internal server error"}
    }
)
async def get_specialities(db: Session = Depends(get_db)):
    try:
        specialities = db.query(Speciality).order_by(Speciality.name).all()
        specialities_data = [{"id": s.id, "name": s.name} for s in specialities]
        return JSONResponse(status_code=200, content={"specialities": specialities_data})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@lookup_router.get("/search-speciality",
    response_model=dict,
    status_code=200,
    summary="Search specialities",
    description="Search medical specialities by name (case-insensitive partial match)",
    responses={
        200: {"description": "Search results retrieved successfully"},
        500: {"description": "Internal server error"}
    }
)
async def search_speciality(query: Optional[str] = None, db: Session = Depends(get_db)):
    try:
        speciality_query = db.query(Speciality)
        if query:
            search = f"%{query}%"
            speciality_query = speciality_query.filter(Speciality.name.ilike(search))
        
        specialities = speciality_query.order_by(Speciality.name).all()
        specialities_data = [{"id": s.id, "name": s.name} for s in specialities]
        return JSONResponse(status_code=200, content={"specialities": specialities_data})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@lookup_router.patch("/speciality/{speciality_id}",
    response_model=dict,
    status_code=200,
    summary="Update speciality",
    description="Update an existing medical speciality by ID",
    responses={
        200: {"description": "Speciality updated successfully"},
        404: {"description": "Speciality not found"},
        500: {"description": "Internal server error"}
    }
)
async def update_speciality(speciality_id: str, speciality: SpecialityUpdate, db: Session = Depends(get_db)):
    try:
        db_speciality = db.query(Speciality).filter(Speciality.id == speciality_id).first()
        if not db_speciality:
            return JSONResponse(status_code=404, content={"error": "Speciality not found"})
        
        # Check if new name conflicts with existing speciality
        existing = db.query(Speciality).filter(
            Speciality.name.ilike(speciality.name),
            Speciality.id != speciality_id
        ).first()
        if existing:
            return JSONResponse(status_code=400, content={"error": "Speciality name already exists"})

        db_speciality.name = speciality.name
        db.commit()
        db.refresh(db_speciality)
        return JSONResponse(status_code=200, content={"message": "Speciality updated successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@lookup_router.delete("/speciality/{speciality_id}",
    response_model=dict,
    status_code=200,
    summary="Delete speciality",
    description="Delete an existing medical speciality by ID",
    responses={
        200: {"description": "Speciality deleted successfully"},
        404: {"description": "Speciality not found"},
        500: {"description": "Internal server error"}
    }
)
async def delete_speciality(speciality_id: str, db: Session = Depends(get_db)):
    try:
        db_speciality = db.query(Speciality).filter(Speciality.id == speciality_id).first()
        if not db_speciality:
            return JSONResponse(status_code=404, content={"error": "Speciality not found"})
        
        db.delete(db_speciality)
        db.commit()
        return JSONResponse(status_code=200, content={"message": "Speciality deleted successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

# Country Routes
@lookup_router.post("/country",
    response_model=dict,
    status_code=201,
    summary="Create country",
    description="Create a new country entry",
    responses={
        201: {"description": "Country created successfully"},
        400: {"description": "Country already exists"},
        500: {"description": "Internal server error"}
    }
)
async def create_country(country: CountryCreate, db: Session = Depends(get_db)):
    try:
        # Check if country already exists
        existing = db.query(Country).filter(Country.name.ilike(country.name)).first()
        if existing:
            return JSONResponse(status_code=400, content={"error": "Country already exists"})

        new_country = Country(name=country.name)
        db.add(new_country)
        db.commit()
        db.refresh(new_country)
        return JSONResponse(status_code=201, content={"message": "Country created successfully", "id": new_country.id})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@lookup_router.get("/countries",
    response_model=dict,
    status_code=200,
    summary="Get all countries",
    description="Retrieve a list of all countries",
    responses={
        200: {"description": "List of countries retrieved successfully"},
        500: {"description": "Internal server error"}
    }
)
async def get_countries(db: Session = Depends(get_db)):
    try:
        countries = db.query(Country).order_by(Country.name).all()
        countries_data = [{"id": c.id, "name": c.name} for c in countries]
        return JSONResponse(status_code=200, content={"countries": countries_data})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@lookup_router.get("/search-country",
    response_model=dict,
    status_code=200,
    summary="Search countries",
    description="Search countries by name (case-insensitive partial match)",
    responses={
        200: {"description": "Search results retrieved successfully"},
        500: {"description": "Internal server error"}
    }
)
async def search_country(query: Optional[str] = None, db: Session = Depends(get_db)):
    try:
        country_query = db.query(Country)
        if query:
            search = f"%{query}%"
            country_query = country_query.filter(Country.name.ilike(search))
        
        countries = country_query.order_by(Country.name).all()
        countries_data = [{"id": c.id, "name": c.name} for c in countries]
        return JSONResponse(status_code=200, content={"countries": countries_data})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@lookup_router.patch("/country/{country_id}",
    response_model=dict,
    status_code=200,
    summary="Update country",
    description="Update an existing country by ID",
    responses={
        200: {"description": "Country updated successfully"},
        404: {"description": "Country not found"},
        400: {"description": "Country name already exists"},
        500: {"description": "Internal server error"}
    }
)
async def update_country(country_id: str, country: CountryUpdate, db: Session = Depends(get_db)):
    try:
        db_country = db.query(Country).filter(Country.id == country_id).first()
        if not db_country:
            return JSONResponse(status_code=404, content={"error": "Country not found"})
        
        # Check if new name conflicts with existing country
        existing = db.query(Country).filter(
            Country.name.ilike(country.name),
            Country.id != country_id
        ).first()
        if existing:
            return JSONResponse(status_code=400, content={"error": "Country name already exists"})

        db_country.name = country.name
        db.commit()
        db.refresh(db_country)
        return JSONResponse(status_code=200, content={"message": "Country updated successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})

@lookup_router.delete("/country/{country_id}",
    response_model=dict,
    status_code=200,
    summary="Delete country",
    description="Delete an existing country by ID",
    responses={
        200: {"description": "Country deleted successfully"},
        404: {"description": "Country not found"},
        500: {"description": "Internal server error"}
    }
)
async def delete_country(country_id: str, db: Session = Depends(get_db)):
    try:
        db_country = db.query(Country).filter(Country.id == country_id).first()
        if not db_country:
            return JSONResponse(status_code=404, content={"error": "Country not found"})
        
        db.delete(db_country)
        db.commit()
        return JSONResponse(status_code=200, content={"message": "Country deleted successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": str(e)})
