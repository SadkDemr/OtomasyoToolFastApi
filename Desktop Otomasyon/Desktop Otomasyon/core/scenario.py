from dataclasses import dataclass, field
from typing import List, Optional, Any

@dataclass
class Action:
    type: str  # CLICK, TYPE, WAIT, LAUNCH_APP, ASSERT_EXISTS
    params: dict = field(default_factory=dict)
    description: str = ""
    id: str = ""

@dataclass
class Scenario:
    name: str
    description: str
    actions: List[Action] = field(default_factory=list)

    def add_action(self, action: Action):
        self.actions.append(action)

    def as_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "actions": [
                {"type": a.type, "params": a.params, "description": a.description, "id": a.id}
                for a in self.actions
            ]
        }

    @staticmethod
    def from_dict(data: dict):
        scenario = Scenario(name=data["name"], description=data.get("description", ""))
        for action_data in data.get("actions", []):
            scenario.add_action(Action(
                type=action_data["type"],
                params=action_data.get("params", {}),
                description=action_data.get("description", ""),
                id=action_data.get("id", "")
            ))
        return scenario
