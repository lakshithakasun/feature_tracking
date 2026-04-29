from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


@lru_cache(maxsize=None)
def _load_script(filename: str, module_name: str):
    path = SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load report script: {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render_product_dev(api_base: str, product_id: str = "identity-server", version: str | None = None) -> str:
    module = _load_script("12_report_product_dev.py", "product_dev_report")
    data = module.load_data(api_base, product_id, version_filter=version)
    return module.build_html(data, product_id)


def render_customer_success(api_base: str) -> str:
    module = _load_script("11_report_customer_success.py", "customer_success_report")
    return module.build_html(api_base)


def render_regional(api_base: str, region: str | None = None) -> str:
    module = _load_script("09_report_regional_gm.py", "regional_managers_report")
    return module.build_html(api_base, region_filter=region)


def render_technical_owner(api_base: str, customer_id: str) -> str:
    module = _load_script("08_report_account_manager.py", "technical_owner_report")
    return module.build_html(api_base, customer_id)
