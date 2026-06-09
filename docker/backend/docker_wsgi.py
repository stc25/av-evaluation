import importlib.util
from pathlib import Path


def load_flask_app():
    module_path = Path(__file__).with_name('app.py')
    spec = importlib.util.spec_from_file_location('legacy_flask_app', module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Could not load Flask app module from {module_path}')

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.create_app()


app = load_flask_app()
