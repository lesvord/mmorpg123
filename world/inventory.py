from dataclasses import dataclass, field
from typing import Dict, List
from .resources_data import ITEMS

@dataclass
class ItemStack:
    id: str
    qty: int

    @property
    def per_kg(self) -> float:
        return float(ITEMS[self.id]["kg"])

    @property
    def stack_cap(self) -> int:
        return int(ITEMS[self.id]["stack"])

    @property
    def total_weight(self) -> float:
        return self.qty * self.per_kg

    def add(self, n:int) -> int:
        """добавить до заполнения стака, вернуть сколько реально добавили"""
        free = max(0, self.stack_cap - self.qty)
        take = max(0, min(free, n))
        self.qty += take
        return take

@dataclass
class Inventory:
    capacity: float = 30.0
    items: List[ItemStack] = field(default_factory=list)

    def weight(self) -> float:
        return sum(i.total_weight for i in self.items)

    def can_take_weight(self, delta: float) -> bool:
        return self.weight() + delta <= self.capacity + 1e-6

    def add_item(self, item_id: str, qty: int) -> int:
        """Добавить qty, учитывая стаки и лимит веса. Возвращает фактически добавленное количество."""
        if item_id not in ITEMS: return 0
        per = float(ITEMS[item_id]["kg"])
        left = int(qty)

        # сначала доверху существующие стаки
        for st in self.items:
            if st.id != item_id: continue
            if left<=0: break
            would = st.add(left)
            if would>0 and not self.can_take_weight(would*per):
                # откат
                st.qty -= would
                return qty - left
            left -= would

        # затем новые стаки
        while left>0:
            take = min(left, int(ITEMS[item_id]["stack"]))
            if not self.can_take_weight(take*per):
                break
            self.items.append(ItemStack(item_id, take))
            left -= take

        return qty - left

    def remove_item(self, item_id: str, qty:int) -> int:
        left = int(qty)
        for st in list(self.items):
            if st.id!=item_id: continue
            if left<=0: break
            take = min(st.qty, left)
            st.qty -= take
            left -= take
            if st.qty<=0:
                self.items.remove(st)
        return qty - left

    def to_json(self) -> Dict:
        from .resources_data import ITEMS
        return {
            "capacity": self.capacity,
            "weight": round(self.weight(), 3),
            "items": [{
                "id": st.id,
                "name": ITEMS[st.id]["name"],
                "qty": st.qty,
                "per_kg": ITEMS[st.id]["kg"],
                "stack": ITEMS[st.id]["stack"],
                "total_weight": round(st.total_weight, 3),
            } for st in self.items]
        }
