from fastapi import APIRouter

from app.attack.catalog import get_catalog

router = APIRouter()


@router.get("/attack/catalog")
async def get_attack_catalog():
    return get_catalog()
