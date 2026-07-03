from fastapi import APIRouter

router = APIRouter()


def empty_layer() -> dict:
    return {
        "name": "TFM generated layer",
        "versions": {"attack": "16", "navigator": "5.1.0", "layer": "4.5"},
        "domain": "enterprise-attack",
        "description": "Placeholder layer - mapping pipeline not implemented yet",
        "techniques": [],
    }


@router.get("/matrix")
async def get_matrix():
    return empty_layer()
