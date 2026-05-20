import importlib.util
from pathlib import Path
from types import ModuleType

from app.models.schemas import StrategyDefinition


class StrategyLoader:
    def discover(self, root: Path) -> list[StrategyDefinition]:
        root = root.resolve()
        definitions: list[StrategyDefinition] = []
        if not root.exists():
            return definitions
        for file_path in root.glob("*.py"):
            if file_path.name.startswith("_"):
                continue
            strategy = self.load(file_path)
            definitions.append(
                StrategyDefinition(
                    name=getattr(strategy, "strategy_name", file_path.stem),
                    version=getattr(strategy, "version", "0.1.0"),
                    file_path=str(file_path),
                    config=getattr(strategy, "default_config", {}),
                )
            )
        return definitions

    def load(self, file_path: str | Path):
        module = self._module_from_path(Path(file_path))
        factory = getattr(module, "create_strategy", None)
        if factory:
            return factory()
        for value in module.__dict__.values():
            if isinstance(value, type) and hasattr(value, "on_market_data") and hasattr(value, "generate_signal"):
                return value()
        raise ValueError(f"No strategy class or create_strategy() found in {file_path}")

    def _module_from_path(self, file_path: Path) -> ModuleType:
        spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Cannot import strategy {file_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

