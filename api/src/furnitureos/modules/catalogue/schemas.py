"""Wire format for catalogue items.

One projection, because there is one consumer: the catalogue panel, which also feeds
the scene the dimensions it draws at. Stock is on the row and not here — see models.py.
"""

from pydantic import BaseModel

from furnitureos.modules.catalogue.item import Item


class ItemOut(BaseModel):
    id: str
    name: str
    category: str
    width_m: float
    depth_m: float
    height_m: float
    # `int`, not `float`: JSON has one number type, and serving 12500000.0 is an
    # invitation for the client to open a float path through a currency that has none.
    price_vnd: int
    preset_ref: str
    photo_url: str | None

    @classmethod
    def from_item(cls, item: Item) -> "ItemOut":
        return cls(
            id=item.id,
            name=item.name,
            category=item.category,
            width_m=item.width_m,
            depth_m=item.depth_m,
            height_m=item.height_m,
            price_vnd=item.price_vnd,
            preset_ref=item.preset_ref,
            photo_url=item.photo_url,
        )
